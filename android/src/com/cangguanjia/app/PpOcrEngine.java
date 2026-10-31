package com.cangguanjia.app;

import android.content.res.AssetManager;
import android.graphics.Bitmap;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.FloatBuffer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;


import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

/**
 * PP-OCR（RapidOCR 同源）轻量引擎：DB 文本检测 + CRNN/CTC 文本识别。
 *
 * <p>只用 onnxruntime-android 一个原生库，不引 OpenCV：
 * 检测后处理（二值化 / 膨胀 / 连通域 / 打分 / 外扩）与 CTC 解码都在这里手写，
 * 参数与 rapidocr 的 PP-OCRv6 配置保持一致（limit_side_len=736、thresh=0.3、
 * box_thresh=0.5、unclip_ratio=1.6、rec 高 48）。
 *
 * <p>模型放在 assets/ppocr/ 下，首次使用拷到 filesDir/ppocr/（ORT 需要文件路径）。
 * 识别字符集直接读 rec 模型自带的 metadata["character"]，不额外放字典文件。
 */
public class PpOcrEngine {

    private static final String TAG = "CGMOCR";
    private static final String ASSET_DIR = "ppocr";
    private static final String DET_FILE = "det.onnx";
    private static final String REC_FILE = "rec.onnx";
    private static final String CLS_FILE = "cls.onnx";

    // 与 rapidocr PP-OCRv6 配置一致
    private static final int LIMIT_SIDE = 736;
    private static final float DET_THRESH = 0.30f;
    private static final float BOX_THRESH = 0.50f;
    private static final float UNCLIP_RATIO = 1.6f;
    private static final int MAX_PIXELS = 2_200_000;   // 检测输入像素上限，防 OOM
    private static final int REC_H = 48;

    private final OrtEnvironment env;
    private final OrtSession det, rec, cls;
    private final String detInput;
    private final String recInput;
    private final String clsInput;
    private final String[] charset;          // [0]=blank
    public long loadMs;                      // 引擎加载耗时（诊断用）
    /** 调试：非空时把每行裁剪图存到该目录（排查「裁剪歪了还是识别糊了」）。 */
    public static java.io.File dumpDir;

    private void dump(Bitmap b, String tag) {
        if (dumpDir == null) {
            return;
        }
        try {
            dumpDir.mkdirs();
            File f = new File(dumpDir, tag + ".png");
            try (OutputStream os = new FileOutputStream(f)) {
                b.compress(Bitmap.CompressFormat.PNG, 90, os);
            }
        } catch (Throwable ignored) {
        }
    }

    public static class Line {
        public String text = "";
        public float score;
        public float x, y, w, h;             // 原图坐标

        @Override
        public String toString() {
            return text + "(" + String.format("%.2f", score) + ")";
        }
    }

    private PpOcrEngine(OrtEnvironment env, OrtSession det, OrtSession rec,
                        OrtSession cls, String[] charset) throws Exception {
        this.env = env;
        this.det = det;
        this.rec = rec;
        this.cls = cls;
        this.detInput = det.getInputNames().iterator().next();
        this.recInput = rec.getInputNames().iterator().next();
        this.clsInput = cls.getInputNames().iterator().next();
        this.charset = charset;
    }

    /** 创建引擎；模型缺失/加载失败时抛异常（调用方负责兜底）。 */
    public static PpOcrEngine create(AssetManager am, File filesDir) throws Exception {
        long t0 = System.currentTimeMillis();
        File dir = new File(filesDir, ASSET_DIR);
        File det = copyAsset(am, dir, DET_FILE);
        File rec = copyAsset(am, dir, REC_FILE);
        File clsF = copyAsset(am, dir, CLS_FILE);
        OrtEnvironment env = OrtEnvironment.getEnvironment();
        OrtSession.SessionOptions o = new OrtSession.SessionOptions();
        o.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
        o.setIntraOpNumThreads(Math.max(2, Math.min(4,
                Runtime.getRuntime().availableProcessors() / 2)));
        OrtSession detS = env.createSession(det.getAbsolutePath(), o);
        OrtSession recS = env.createSession(rec.getAbsolutePath(), o);
        OrtSession clsS;
        try {
            clsS = env.createSession(clsF.getAbsolutePath(), o);
        } catch (Throwable t) {                     // cls 缺失只影响倒置文字，不致命
            Log.w(TAG, "cls 加载失败: " + t);
            clsS = null;
        }
        String meta = recS.getMetadata().getCustomMetadata().get("character");
        if (meta == null || meta.isEmpty()) {
            throw new IllegalStateException("rec 模型缺少 character 字典");
        }
        String[] chars = meta.split("\n", -1);
        String[] table = new String[chars.length + 2];
        table[0] = "";                       // CTC blank
        System.arraycopy(chars, 0, table, 1, chars.length);
        table[table.length - 1] = " ";       // rapidocr 在末尾补一个空格
        PpOcrEngine e = new PpOcrEngine(env, detS, recS, clsS, table);
        e.loadMs = System.currentTimeMillis() - t0;
        return e;
    }

    public int charsetSize() {
        return charset.length;
    }

    /** 整图识别：返回按位置排序的文本行。 */
    public List<Line> run(Bitmap src) {
        List<Line> out = new ArrayList<>();
        DetResult dr = detect(src);
        if (dr.boxes.isEmpty()) {
            return out;
        }
        int k = 0;
        for (float[] b : dr.boxes) {
            Bitmap crop = warpCrop(src, b);
            if (crop == null) {
                continue;
            }
            try {
                dump(crop, "line" + (k++));
                if (cls != null && upright180(crop)) {   // 倒置文字：cls 判 180° 先转正
                    android.graphics.Matrix m = new android.graphics.Matrix();
                    m.postRotate(180);
                    Bitmap fix = Bitmap.createBitmap(crop, 0, 0,
                            crop.getWidth(), crop.getHeight(), m, true);
                    crop.recycle();
                    crop = fix;
                }
                Line ln = recognize(crop);
                if (ln != null && !ln.text.isEmpty()) {
                    float x1 = Math.min(Math.min(b[0], b[2]), Math.min(b[4], b[6]));
                    float x2 = Math.max(Math.max(b[0], b[2]), Math.max(b[4], b[6]));
                    float y1 = Math.min(Math.min(b[1], b[3]), Math.min(b[5], b[7]));
                    float y2 = Math.max(Math.max(b[1], b[3]), Math.max(b[5], b[7]));
                    ln.x = x1;
                    ln.y = y1;
                    ln.w = x2 - x1;
                    ln.h = y2 - y1;
                    out.add(ln);
                }
            } finally {
                crop.recycle();
            }
        }
        Collections.sort(out, new Comparator<Line>() {
            @Override
            public int compare(Line a, Line b) {
                if (Math.abs(a.y - b.y) > Math.max(a.h, b.h) * 0.6f) {
                    return Float.compare(a.y, b.y);
                }
                return Float.compare(a.x, b.x);
            }
        });
        return out;
    }

    /** 诊断用：分开返回检测耗时与识别耗时。 */
    public static class DetResult {
        public List<float[]> boxes = new ArrayList<>();   // {x1,y1,x2,y2} 原图坐标
        public long ms;
    }

    // --------------------------------------------------------------- 检测

    public DetResult detect(Bitmap src) {
        long t0 = System.currentTimeMillis();
        DetResult res = new DetResult();
        int W = src.getWidth();
        int H = src.getHeight();
        float ratio = 1f;
        if (Math.min(W, H) < LIMIT_SIDE) {
            ratio = (float) LIMIT_SIDE / Math.min(W, H);
        }
        int rw = Math.max(32, Math.round(W * ratio / 32f) * 32);
        int rh = Math.max(32, Math.round(H * ratio / 32f) * 32);
        // 像素上限：宽图（长条标签）按面积收一收，避免 float 输入把内存顶爆
        if (rw * rh > MAX_PIXELS) {
            float k = (float) Math.sqrt((double) MAX_PIXELS / (rw * rh));
            rw = Math.max(32, Math.round(rw * k / 32f) * 32);
            rh = Math.max(32, Math.round(rh * k / 32f) * 32);
        }

        float[] in = new float[3 * rw * rh];
        int[] px = new int[W * H];
        src.getPixels(px, 0, W, 0, 0, W, H);
        for (int y = 0; y < rh; y++) {
            int sy = Math.min(H - 1, y * H / rh);
            for (int x = 0; x < rw; x++) {
                int sx = Math.min(W - 1, x * W / rw);
                int c = px[sy * W + sx];
                int i = y * rw + x;
                in[i] = (((c >> 16) & 0xff) / 127.5f) - 1f;          // R
                in[rw * rh + i] = (((c >> 8) & 0xff) / 127.5f) - 1f; // G
                in[2 * rw * rh + i] = ((c & 0xff) / 127.5f) - 1f;    // B
            }
        }
        float[][][][] prob = null;
        try (OnnxTensor t = OnnxTensor.createTensor(env, FloatBuffer.wrap(in),
                new long[]{1, 3, rh, rw});
             OrtSession.Result r = det.run(Collections.singletonMap(detInput, t))) {
            prob = (float[][][][]) r.get(0).getValue();
        } catch (Exception e) {
            Log.w(TAG, "det 失败: " + e);
            res.ms = System.currentTimeMillis() - t0;
            return res;
        } finally {
            in = null;
        }
        if (prob == null) {
            res.ms = System.currentTimeMillis() - t0;
            return res;
        }

        // 二值化 + 2×2 膨胀（use_dilation）
        boolean[] mask = new boolean[rh * rw];
        for (int y = 0; y < rh; y++) {
            for (int x = 0; x < rw; x++) {
                mask[y * rw + x] = prob[0][0][y][x] > DET_THRESH;
            }
        }
        boolean[] dil = new boolean[rh * rw];
        for (int y = 0; y < rh; y++) {
            for (int x = 0; x < rw; x++) {
                if (mask[y * rw + x]) {
                    dil[y * rw + x] = true;
                    if (x + 1 < rw) dil[y * rw + x + 1] = true;
                    if (y + 1 < rh) dil[(y + 1) * rw + x] = true;
                    if (x + 1 < rw && y + 1 < rh) dil[(y + 1) * rw + x + 1] = true;
                }
            }
        }

        // 8 连通域扫描
        boolean[] seen = new boolean[rh * rw];
        int[] stack = new int[Math.min(rh * rw, 1 << 20)];
        int[] cpts = new int[8192];               // 当前连通域的点集（x,y 交替）
        for (int y = 0; y < rh; y++) {
            for (int x = 0; x < rw; x++) {
                int idx = y * rw + x;
                if (!dil[idx] || seen[idx]) {
                    continue;
                }
                int sp = 0;
                int cn = 0;
                stack[sp++] = idx;
                seen[idx] = true;
                while (sp > 0) {
                    int cur = stack[--sp];
                    int cy = cur / rw, cx = cur % rw;
                    if (cn + 2 > cpts.length) {
                        int[] bigger = new int[cpts.length * 2];
                        System.arraycopy(cpts, 0, bigger, 0, cpts.length);
                        cpts = bigger;
                    }
                    cpts[cn++] = cx;
                    cpts[cn++] = cy;
                    for (int dy = -1; dy <= 1; dy++) {
                        for (int dx = -1; dx <= 1; dx++) {
                            int nx = cx + dx, ny = cy + dy;
                            if (nx < 0 || ny < 0 || nx >= rw || ny >= rh) {
                                continue;
                            }
                            int ni = ny * rw + nx;
                            if (dil[ni] && !seen[ni]) {
                                if (sp >= stack.length) {          // 扩栈，防极长文本溢出
                                    int[] bigger = new int[stack.length * 2];
                                    System.arraycopy(stack, 0, bigger, 0, stack.length);
                                    stack = bigger;
                                }
                                stack[sp++] = ni;
                                seen[ni] = true;
                            }
                        }
                    }
                }
                // 从点集算外接框（只用于过滤与打分范围）
                int minX = Integer.MAX_VALUE, minY = Integer.MAX_VALUE;
                int maxX = -1, maxY = -1;
                for (int i = 0; i < cn; i += 2) {
                    int qx = cpts[i], qy = cpts[i + 1];
                    if (qx < minX) minX = qx;
                    if (qx > maxX) maxX = qx;
                    if (qy < minY) minY = qy;
                    if (qy > maxY) maxY = qy;
                }
                if (maxX < 0) {
                    continue;
                }
                int bw = maxX - minX + 1, bh = maxY - minY + 1;
                if (Math.min(bw, bh) < 3) {
                    continue;
                }
                // 框内平均得分（对应 box_score_fast）
                double sum = 0;
                int cnt = 0;
                for (int yy = minY; yy <= maxY; yy++) {
                    for (int xx = minX; xx <= maxX; xx++) {
                        sum += prob[0][0][yy][xx];
                        cnt++;
                    }
                }
                if (cnt == 0 || sum / cnt < BOX_THRESH) {
                    continue;
                }
                // v1.31.1：最小外接矩形（不是轴对齐框）——标签拍歪时轴对齐会把字裁斜，
                // 识别必糊。这里按连通域点集求最小外接矩形，再做透视矫正裁剪。
                float[] quad = minAreaQuad(trim(cpts, cn), UNCLIP_RATIO);
                if (quad == null) {
                    continue;
                }
                for (int i = 0; i < 8; i += 2) {          // 映射回原图坐标
                    quad[i] = Math.max(0, Math.min(quad[i] / ratio, W - 1));
                    quad[i + 1] = Math.max(0, Math.min(quad[i + 1] / ratio, H - 1));
                }
                res.boxes.add(quad);
            }
        }
        res.ms = System.currentTimeMillis() - t0;
        return res;
    }

    private static int[] trim(int[] a, int n) {
        int[] out = new int[n];
        System.arraycopy(a, 0, out, 0, n);
        return out;
    }

    /** 最小外接矩形（枚举凸包每条边方向）→ 外扩 → 返回 4 点（左上、右上、右下、左下）。 */
    private static float[] minAreaQuad(int[] pts, float unclipRatio) {
        if (pts.length < 8) {                      // 点太少（细线）：退回轴对齐
            return axisAligned(pts, unclipRatio);
        }
        int[] hull = convexHull(pts, pts.length / 2);
        int hn = hull.length / 2;
        if (hn < 3) {
            return axisAligned(pts, unclipRatio);
        }
        double bestArea = Double.MAX_VALUE;
        double bestAngle = 0;
        double[] best = new double[4];             // minU,maxU,minV,maxV
        for (int i = 0; i < hn; i++) {
            int i2 = (i + 1) % hn;
            double ang = Math.atan2(hull[i2 * 2 + 1] - hull[i * 2 + 1],
                    hull[i2 * 2] - hull[i * 2]);
            double ca = Math.cos(ang), sa = Math.sin(ang);
            double minU = Double.MAX_VALUE, maxU = -Double.MAX_VALUE;
            double minV = Double.MAX_VALUE, maxV = -Double.MAX_VALUE;
            for (int j = 0; j < hn; j++) {
                double px = hull[j * 2], py = hull[j * 2 + 1];
                double u = px * ca + py * sa;      // 投影到边方向
                double v = -px * sa + py * ca;     // 投影到法向
                if (u < minU) minU = u;
                if (u > maxU) maxU = u;
                if (v < minV) minV = v;
                if (v > maxV) maxV = v;
            }
            double area = (maxU - minU) * (maxV - minV);
            if (area < bestArea) {
                bestArea = area;
                bestAngle = ang;
                best[0] = minU;
                best[1] = maxU;
                best[2] = minV;
                best[3] = maxV;
            }
        }
        double w = best[1] - best[0], h = best[3] - best[2];
        if (w < 2 || h < 2) {
            return null;
        }
        double d = (w * h * unclipRatio) / (2.0 * (w + h));   // DB 外扩距离
        double cu = (best[0] + best[1]) / 2, cv = (best[2] + best[3]) / 2;
        double hu = w / 2 + d, hv = h / 2 + d;
        double ca = Math.cos(bestAngle), sa = Math.sin(bestAngle);
        double[][] uv = {{cu - hu, cv - hv}, {cu + hu, cv - hv},
                {cu + hu, cv + hv}, {cu - hu, cv + hv}};
        float[] out = new float[8];
        for (int i = 0; i < 4; i++) {
            double u = uv[i][0], v = uv[i][1];
            out[i * 2] = (float) (u * ca - v * sa);          // 转回 det 坐标
            out[i * 2 + 1] = (float) (u * sa + v * ca);
        }
        return out;
    }

    private static float[] axisAligned(int[] pts, float unclipRatio) {
        int minX = Integer.MAX_VALUE, minY = Integer.MAX_VALUE;
        int maxX = -1, maxY = -1;
        for (int i = 0; i < pts.length; i += 2) {
            if (pts[i] < minX) minX = pts[i];
            if (pts[i] > maxX) maxX = pts[i];
            if (pts[i + 1] < minY) minY = pts[i + 1];
            if (pts[i + 1] > maxY) maxY = pts[i + 1];
        }
        if (maxX < 0) {
            return null;
        }
        double w = maxX - minX + 1, h = maxY - minY + 1;
        double d = (w * h * unclipRatio) / (2.0 * (w + h));
        return new float[]{(float) (minX - d), (float) (minY - d),
                (float) (maxX + d), (float) (minY - d),
                (float) (maxX + d), (float) (maxY + d),
                (float) (minX - d), (float) (maxY + d)};
    }

    /** Andrew 单调链凸包，返回 [x0,y0,x1,y1,…]（逆时针）。 */
    private static int[] convexHull(int[] pts, int n) {
        long[] packed = new long[n];
        for (int i = 0; i < n; i++) {
            packed[i] = ((long) pts[i * 2] << 32) | (pts[i * 2 + 1] & 0xffffffffL);
        }
        java.util.Arrays.sort(packed);
        int[] hx = new int[2 * n], hy = new int[2 * n];
        int k = 0;
        for (int i = 0; i < n; i++) {
            int x = (int) (packed[i] >>> 32);
            int y = (int) (packed[i] & 0xffffffffL);
            while (k >= 2 && cross(hx[k - 2], hy[k - 2], hx[k - 1], hy[k - 1], x, y) <= 0) {
                k--;
            }
            hx[k] = x;
            hy[k] = y;
            k++;
        }
        int lower = k + 1;
        for (int i = n - 2; i >= 0; i--) {
            int x = (int) (packed[i] >>> 32);
            int y = (int) (packed[i] & 0xffffffffL);
            while (k >= lower && cross(hx[k - 2], hy[k - 2], hx[k - 1], hy[k - 1], x, y) <= 0) {
                k--;
            }
            hx[k] = x;
            hy[k] = y;
            k++;
        }
        int hn = Math.max(0, k - 1);
        int[] out = new int[hn * 2];
        for (int i = 0; i < hn; i++) {
            out[i * 2] = hx[i];
            out[i * 2 + 1] = hy[i];
        }
        return out;
    }

    private static long cross(int ax, int ay, int bx, int by, int cx, int cy) {
        return (long) (bx - ax) * (cy - ay) - (long) (by - ay) * (cx - ax);
    }

    /** 按四点做透视矫正裁剪（对应 PP-OCR 的 get_rotate_crop_image）。
     *  标签拍歪时这一步决定成败：直接裁轴对齐框，字是斜的，识别必糊。 */
    private static Bitmap warpCrop(Bitmap src, float[] q0) {
        float[] q = orderQuad(q0);
        Log.i(TAG, "warp in=" + Arrays.toString(q0) + " ord=" + Arrays.toString(q));
        double d01 = dist(q[0], q[1], q[2], q[3]);
        double d32 = dist(q[6], q[7], q[4], q[5]);
        double d03 = dist(q[0], q[1], q[6], q[7]);
        double d12 = dist(q[2], q[3], q[4], q[5]);
        int dw = (int) Math.round(Math.max(d01, d32));
        int dh = (int) Math.round(Math.max(d03, d12));
        if (dw < 4 || dh < 4) {
            return null;
        }
        dw = Math.min(dw, 2000);
        dh = Math.min(dh, 400);

        double[] h = homography(dw, dh, q);
        if (h == null) {
            return null;
        }
        int sw = src.getWidth(), sh = src.getHeight();
        int[] sp = new int[sw * sh];
        src.getPixels(sp, 0, sw, 0, 0, sw, sh);
        int[] dp = new int[dw * dh];
        for (int y = 0; y < dh; y++) {
            for (int x = 0; x < dw; x++) {
                double den = h[6] * x + h[7] * y + 1.0;
                if (Math.abs(den) < 1e-9) {
                    continue;
                }
                double u = (h[0] * x + h[1] * y + h[2]) / den;
                double v = (h[3] * x + h[4] * y + h[5]) / den;
                dp[y * dw + x] = bilinear(sp, sw, sh, u, v);
            }
        }
        Bitmap out = Bitmap.createBitmap(dw, dh, Bitmap.Config.ARGB_8888);
        out.setPixels(dp, 0, dw, 0, 0, dw, dh);
        return out;
    }

    /** 四点定序为 左上→右上→右下→左下（按 y 分上下、再按 x 分左右）。
     *  最小外接矩形的角点顺序随角度变化，不定序会裁出镜像/翻转的图，识别直接崩。 */
    private static float[] orderQuad(float[] q) {
        float[][] p = new float[4][2];
        for (int i = 0; i < 4; i++) {
            p[i][0] = q[i * 2];
            p[i][1] = q[i * 2 + 1];
        }
        java.util.Arrays.sort(p, new java.util.Comparator<float[]>() {
            @Override
            public int compare(float[] a, float[] b) {
                return Float.compare(a[1], b[1]);
            }
        });
        float[] tl, tr, bl, br;
        if (p[0][0] <= p[1][0]) {
            tl = p[0];
            tr = p[1];
        } else {
            tl = p[1];
            tr = p[0];
        }
        if (p[2][0] <= p[3][0]) {
            bl = p[2];
            br = p[3];
        } else {
            bl = p[3];
            br = p[2];
        }
        return new float[]{tl[0], tl[1], tr[0], tr[1], br[0], br[1], bl[0], bl[1]};
    }

    private static double dist(float x1, float y1, float x2, float y2) {
        double dx = x1 - x2, dy = y1 - y2;
        return Math.sqrt(dx * dx + dy * dy);
    }

    /** 解 3×3 单应矩阵（dst 像素 → 原图坐标），返回 [a,b,c,d,e,f,g,h]。 */
    private static double[] homography(int dw, int dh, float[] q) {
        double[][] m = new double[8][9];
        double[][] dst = {{0, 0}, {dw, 0}, {dw, dh}, {0, dh}};
        for (int i = 0; i < 4; i++) {
            double X = dst[i][0], Y = dst[i][1];
            double U = q[i * 2], V = q[i * 2 + 1];
            m[i * 2] = new double[]{X, Y, 1, 0, 0, 0, -X * U, -Y * U, U};
            m[i * 2 + 1] = new double[]{0, 0, 0, X, Y, 1, -X * V, -Y * V, V};
        }
        for (int col = 0; col < 8; col++) {          // 高斯消元
            int piv = col;
            for (int r = col + 1; r < 8; r++) {
                if (Math.abs(m[r][col]) > Math.abs(m[piv][col])) {
                    piv = r;
                }
            }
            if (Math.abs(m[piv][col]) < 1e-12) {
                return null;
            }
            double[] tmp = m[col];
            m[col] = m[piv];
            m[piv] = tmp;
            double p = m[col][col];
            for (int c = col; c <= 8; c++) {
                m[col][c] /= p;
            }
            for (int r = 0; r < 8; r++) {
                if (r == col) {
                    continue;
                }
                double f = m[r][col];
                if (f == 0) {
                    continue;
                }
                for (int c = col; c <= 8; c++) {
                    m[r][c] -= f * m[col][c];
                }
            }
        }
        double[] h = new double[8];
        for (int i = 0; i < 8; i++) {
            h[i] = m[i][8];
        }
        return h;
    }

    private static int bilinear(int[] sp, int w, int h, double u, double v) {
        int x0 = (int) Math.floor(u), y0 = (int) Math.floor(v);
        if (x0 < 0 || y0 < 0 || x0 >= w - 1 || y0 >= h - 1) {
            int xi = Math.max(0, Math.min(w - 1, (int) Math.round(u)));
            int yi = Math.max(0, Math.min(h - 1, (int) Math.round(v)));
            return sp[yi * w + xi];
        }
        double fx = u - x0, fy = v - y0;
        int c00 = sp[y0 * w + x0], c10 = sp[y0 * w + x0 + 1];
        int c01 = sp[(y0 + 1) * w + x0], c11 = sp[(y0 + 1) * w + x0 + 1];
        int r = (int) ((1 - fx) * (1 - fy) * ((c00 >> 16) & 0xff)
                + fx * (1 - fy) * ((c10 >> 16) & 0xff)
                + (1 - fx) * fy * ((c01 >> 16) & 0xff)
                + fx * fy * ((c11 >> 16) & 0xff));
        int g = (int) ((1 - fx) * (1 - fy) * ((c00 >> 8) & 0xff)
                + fx * (1 - fy) * ((c10 >> 8) & 0xff)
                + (1 - fx) * fy * ((c01 >> 8) & 0xff)
                + fx * fy * ((c11 >> 8) & 0xff));
        int b = (int) ((1 - fx) * (1 - fy) * (c00 & 0xff)
                + fx * (1 - fy) * (c10 & 0xff)
                + (1 - fx) * fy * (c01 & 0xff)
                + fx * fy * (c11 & 0xff));
        return 0xff000000 | (Math.min(255, r) << 16) | (Math.min(255, g) << 8) | Math.min(255, b);
    }

    // --------------------------------------------------------------- 识别

    /** cls 方向分类（PP-OCR 第三件套）：判断裁剪行是否上下颠倒。
     *  拍照时标签倒着放很常见，det 对倒字照样出框，但 rec 只认正的字——
     *  没有这一步，倒置的行会整行认成乱码。阈值 0.9 与 rapidocr 一致。 */
    private boolean upright180(Bitmap crop) {
        int w = crop.getWidth(), h = crop.getHeight();
        if (w < 4 || h < 4) {
            return false;
        }
        Bitmap s = Bitmap.createScaledBitmap(crop, 192, 48, true);
        float[] in = new float[3 * 48 * 192];
        int[] px = new int[192 * 48];
        s.getPixels(px, 0, 192, 0, 0, 192, 48);
        s.recycle();
        int plane = 48 * 192;
        for (int y = 0; y < 48; y++) {
            for (int x = 0; x < 192; x++) {
                int c = px[y * 192 + x];
                int i = y * 192 + x;
                in[i] = ((c >> 16) & 0xff) / 127.5f - 1f;
                in[plane + i] = ((c >> 8) & 0xff) / 127.5f - 1f;
                in[2 * plane + i] = (c & 0xff) / 127.5f - 1f;
            }
        }
        float[][] out;
        try (OnnxTensor t = OnnxTensor.createTensor(env, FloatBuffer.wrap(in),
                new long[]{1, 3, 48, 192});
             OrtSession.Result r = cls.run(Collections.singletonMap(clsInput, t))) {
            out = (float[][]) r.get(0).getValue();
        } catch (Exception e) {
            return false;
        }
        return out != null && out[0].length >= 2 && out[0][1] > 0.9f;
    }

    public Line recognize(Bitmap crop) {
        int w = crop.getWidth();
        int h = crop.getHeight();
        if (w < 4 || h < 4) {
            return null;
        }
        int rh = REC_H;
        int content = Math.max(8, Math.min(1600, Math.round(rh * (float) w / h)));
        // 与 PP-OCR 一致：画布宽至少 320，内容左对齐、余下补黑（归一化后为 -1）。
        // 不补的话短文本时间步太少，尾部字符会被吞（实测 "T40 59633" → "T40 596"）。
        int rw = Math.max(320, content);
        Bitmap scaled = Bitmap.createScaledBitmap(crop, content, rh, true);
        float[] in = new float[3 * rh * rw];
        java.util.Arrays.fill(in, -1f);
        int[] px = new int[content * rh];
        scaled.getPixels(px, 0, content, 0, 0, content, rh);
        scaled.recycle();
        int plane = rh * rw;
        for (int y = 0; y < rh; y++) {
            for (int x = 0; x < content; x++) {
                int c = px[y * content + x];
                int i = y * rw + x;
                // (v/255 - 0.5)/0.5
                in[i] = ((c >> 16) & 0xff) / 127.5f - 1f;
                in[plane + i] = ((c >> 8) & 0xff) / 127.5f - 1f;
                in[2 * plane + i] = (c & 0xff) / 127.5f - 1f;
            }
        }
        float[][][] out;
        try (OnnxTensor t = OnnxTensor.createTensor(env, FloatBuffer.wrap(in),
                new long[]{1, 3, rh, rw});
             OrtSession.Result r = rec.run(Collections.singletonMap(recInput, t))) {
            out = (float[][][]) r.get(0).getValue();
        } catch (Exception e) {
            Log.w(TAG, "rec 失败: " + e);
            return null;
        }
        return ctc(out[0]);
    }

    /** CTC 贪心解码：跳 blank(0)、合并重复，置信度取所选字符概率均值。 */
    private Line ctc(float[][] logits) {
        StringBuilder sb = new StringBuilder();
        float sum = 0;
        int n = 0;
        int prev = -1;
        for (float[] step : logits) {
            int best = 0;
            float bestP = step[0];
            for (int i = 1; i < step.length; i++) {
                if (step[i] > bestP) {
                    bestP = step[i];
                    best = i;
                }
            }
            if (best != 0 && best != prev) {
                if (best < charset.length) {
                    sb.append(charset[best]);
                    sum += bestP;
                    n++;
                }
            }
            prev = best;
        }
        Line ln = new Line();
        ln.text = sb.toString().trim();
        ln.score = n == 0 ? 0 : sum / n;
        return ln;
    }

    public void close() {
        try {
            det.close();
        } catch (Exception ignored) {
        }
        try {
            rec.close();
        } catch (Exception ignored) {
        }
        if (cls != null) {
            try {
                cls.close();
            } catch (Exception ignored) {
            }
        }
    }

    // ------------------------------------------------------------- 资源拷贝

    private static File copyAsset(AssetManager am, File dir, String name) throws Exception {
        if (!dir.exists() && !dir.mkdirs()) {
            throw new IllegalStateException("无法创建模型目录 " + dir);
        }
        File out = new File(dir, name);
        long assetSize = -1;
        try (InputStream is = am.open(ASSET_DIR + "/" + name)) {
            assetSize = is.available();
            if (out.isFile() && out.length() > 0) {
                return out;                    // 已拷过（大小不可靠时按存在即用）
            }
            try (OutputStream os = new FileOutputStream(out)) {
                byte[] buf = new byte[1 << 16];
                int n;
                while ((n = is.read(buf)) > 0) {
                    os.write(buf, 0, n);
                }
            }
        }
        Log.i(TAG, "模型已就绪: " + name + " " + out.length() / 1024 + "KB");
        return out;
    }

    /** 诊断：把识别结果拼成一行，便于日志阅读。 */
    public static String join(List<Line> lines, String sep) {
        StringBuilder sb = new StringBuilder();
        for (Line l : lines) {
            if (sb.length() > 0) {
                sb.append(sep);
            }
            sb.append(l.text);
        }
        return sb.toString();
    }

    public static String[] names(List<Line> lines) {
        List<String> out = new ArrayList<>();
        for (Line l : lines) {
            out.add(l.text);
        }
        return out.toArray(new String[0]);
    }

    @Override
    public String toString() {
        return "PpOcrEngine{chars=" + charset.length + ", load=" + loadMs + "ms}";
    }
}
