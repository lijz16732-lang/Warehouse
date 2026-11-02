package com.cangguanjia.app;

import android.Manifest;
import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorMatrix;
import android.graphics.ColorMatrixColorFilter;
import android.graphics.ImageFormat;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.hardware.Camera;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 拍照识别型号（v1.28.0 重构）：拍照 → 框选 → 本地离线识别。
 *
 * 为什么不用实时预览帧识别（v1.27.x 及以前的做法）：
 *   实时预览流分辨率低（≤1600px）、连续对焦近距常不收敛，识别率差还费电；
 *   系统相机拍一张是全分辨率 + 自动对焦/HDR，配合手动框选排除背景干扰，
 *   只识别一次，又准又省电。照片走 cacheDir 临时文件，用完即删，不进相册。
 *
 * 识别引擎（v1.31 起）：PP-OCR（PpOcrEngine，ONNX Runtime + assets/ppocr 的 det/cls/rec
 * 小模型），检测/方向分类/识别三段全在本地跑，不联网、不需要任何清单声明。
 *   换过来的原因：工业标签上大量小字与少量中文，Tesseract 中文小字错得离谱
 *   （「开关」认成「开天」、「施耐德」认成「ems」），PP-OCR 同样素材全对。
 *   代价：APK 增大约 30MB，单张识别 0.5~1 秒（可接受）。
 *
 * 为什么不用 ML Kit（v1.29.0 已放弃）：
 *   ML Kit 走 GMS dynamite 机制，运行时还要 datatransport/dagger 一整套组件；
 *   本工程用 build_apk.py 手工打包（无 Gradle），这些都得手工补清单与依赖，
 *   任何一处对不上就是「引擎起不来」，且错误信息被笼统报成「未初始化」，极难定位。
 *
 * 二维码模式（扫电脑连接码）仍是实时取景 ZXing 解码。
 *
 * 相机时序要点（v1.20.1 修黑屏，二维码模式沿用）：
 *   必须等 SurfaceView 的 surface 真正创建后再 setPreviewDisplay + startPreview，
 *   否则会抛 "Surface is not valid" 且相机对象残留在半开状态，之后再也不出画面。
 */
public class ScanActivity extends Activity implements SurfaceHolder.Callback {

    public static final String EXTRA_TEXT = "text";
    public static final String EXTRA_MODE = "mode";       // ocr（默认，拍型号照片）/ qr（扫电脑二维码）
    public static final String MODE_QR = "qr";

    private static final int REQ_PERM = 21;
    private static final int REQ_SHOOT = 22;
    private static final long QR_GAP_MS = 260L;       // 二维码解码轻，间隔短一点跟手

    /** 拍照解码的长边上限（控制内存峰值在 ~20MB 级，文字精度足够）。 */
    private static final int PHOTO_MAX_EDGE = 2560;

    private boolean isQr = false;
    private final MultiFormatReader qrReader = new MultiFormatReader();

    /** 识别引擎全局复用：PP-OCR 三个模型首次加载约 0.3~0.5 秒，之后常驻。
     *  引擎非线程安全——所有调用都在 worker 这个单线程里做。 */
    private static PpOcrEngine sPp;               // 主引擎（v1.31，PP-OCR small 模型）

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();

    // ---- 二维码模式（实时取景）----
    private SurfaceView preview;
    private Camera camera;
    private Camera.Size previewSize;
    private int rotateDeg = 90;
    private int camIdx = 0;
    private volatile boolean previewRunning = false;
    private long lastFrameAt = 0L;
    private volatile int restartCount = 0;      // 重启次数：真收到画面帧才清零，防死循环
    private byte[] frameBuffer;
    private final AtomicBoolean busy = new AtomicBoolean(false);
    private long lastAt = 0L;

    // ---- 拍照框选模式（型号识别）----
    private Bitmap photoBitmap;                 // 采样解码后的整张照片
    private CropView cropView;                  // 框选层
    private LinearLayout actions;               // 重拍 / 识别 按钮行
    private File tmpFile;                       // 拍照临时文件（用完即删）

    // ---- 界面 ----
    private TextView status;
    private TextView hintBig;
    private LinearLayout choices;
    private FrameLayout root;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // 自检入口（adb: am start -n 包名/.ScanActivity --ez diag true）：
        // 不开相机、不拍照，自己画一张含型号文字的图，跑完整「初始化→getClient→识别」
        // 链路并把每步结果打到 logcat(CGMDIAG) 与屏幕——用来分辨是引擎没起来还是识别不准。
        if (getIntent().getBooleanExtra("diag", false)) {
            runDiag();
            return;
        }
        isQr = MODE_QR.equals(getIntent().getStringExtra(EXTRA_MODE));
        if (isQr) {
            Map<DecodeHintType, Object> hints = new EnumMap<>(DecodeHintType.class);
            hints.put(DecodeHintType.TRY_HARDER, Boolean.TRUE);
            hints.put(DecodeHintType.POSSIBLE_FORMATS,
                    Collections.singletonList(BarcodeFormat.QR_CODE));
            qrReader.setHints(hints);
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        buildUi();

        if (isQr) {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                askCameraPerm();
            }
            // 相机不在这里开：等 surfaceCreated / 权限回调，避免 surface 未就绪导致黑屏
        } else {
            startShootFlow();
        }
    }

    // ------------------------------------------------------------- 自检入口

    /** 不开相机、不拍照的自检：造一张含型号文字的图，跑「初始化→识别」并把每步结果
     *  显示在屏幕上（截图即可）。若外部私有目录里放了 cgm_test.jpg 还会顺带识别它，
     *  用来验证真实照片的识别效果（adb push 到 /sdcard/Android/data/包名/files/）。
     *  入口：长按「识别」按钮，或 adb am start ... --ez diag true。 */
    private void runDiag() {
        final TextView tv = new TextView(this);
        tv.setTextSize(11);
        tv.setTextIsSelectable(true);
        tv.setPadding(dp(16), dp(48), dp(16), dp(16));
        tv.setBackgroundColor(Color.WHITE);
        tv.setTextColor(Color.BLACK);
        tv.setText("自检中…");
        setContentView(tv);
        worker.execute(new Runnable() {
            @Override
            public void run() {
                final StringBuilder sb = new StringBuilder();
                sb.append("ABI: ").append(android.os.Build.SUPPORTED_ABIS[0]).append('\n');
                sb.append("版本: v").append(verName()).append('\n');
                // ---- v1.31 起主引擎：PP-OCR（ONNX Runtime），同一批输入跑准确率与耗时 ----
                PpOcrEngine pp = null;
                try {
                    pp = ensurePp();                 // 与正式识别共用同一个常驻实例
                    sb.append("PP引擎: OK 字数=").append(pp.charsetSize())
                      .append(" 加载=").append(pp.loadMs).append("ms\n");
                } catch (Throwable t) {
                    sb.append("PP引擎: FAIL ").append(brief(t)).append('\n');
                }
                if (pp != null) {
                    List<String> names = new ArrayList<>();
                    List<Bitmap> inputs = new ArrayList<>();
                    try {
                        for (String[] m : new String[][]{
                                {"GV2ME08", "小字紧贴"},
                                {"LC1D18M7", "小字带边"},
                                {"T40 59633", "灰底小字"},
                                {"LC1D18 施耐德 交流接触器", "小字中文"}}) {
                            names.add(m[1]);
                            inputs.add(miniLabel(m[0], "灰底小字".equals(m[1])));
                        }
                        try {
                            Bitmap big = Bitmap.createBitmap(900, 240, Bitmap.Config.ARGB_8888);
                            Canvas cv = new Canvas(big);
                            cv.drawColor(Color.WHITE);
                            Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
                            p.setColor(Color.BLACK);
                            p.setTextSize(72);
                            p.setTypeface(Typeface.DEFAULT_BOLD);
                            cv.drawText("SEREAM T40 59633", 24, 150, p);
                            names.add("自绘图");
                            inputs.add(big);
                        } catch (Throwable ignored) {
                        }
                        File photo = new File(getExternalFilesDir(null), "cgm_test.jpg");
                        if (photo.isFile()) {
                            Bitmap ph = BitmapFactory.decodeFile(photo.getAbsolutePath());
                            if (ph != null) {
                                names.add("真机照片");
                                inputs.add(ph);
                            }
                        }
                        File ext = getExternalFilesDir(null);
                        File dir = ext == null ? null : new File(ext, "ocr_cases");
                        File[] fs = dir == null ? null : dir.listFiles();
                        if (fs != null && fs.length > 0) {
                            java.util.Arrays.sort(fs, new java.util.Comparator<File>() {
                                @Override
                                public int compare(File a, File b) {
                                    return a.getName().compareTo(b.getName());
                                }
                            });
                            for (File f : fs) {
                                Bitmap ph = BitmapFactory.decodeFile(f.getAbsolutePath());
                                if (ph != null) {
                                    names.add(f.getName().replace(".png", ""));
                                    inputs.add(ph);
                                }
                            }
                        }
                    } catch (Throwable t) {
                        sb.append("PP素材 FAILED: ").append(brief(t)).append('\n');
                    }
                    long totalRaw = 0, totalPre = 0;
                    for (int i = 0; i < inputs.size(); i++) {
                        Bitmap in = inputs.get(i);
                        // 真机照片单独转储每行裁剪图，便于排查裁剪 vs 识别
                        PpOcrEngine.dumpDir = "真机照片".equals(names.get(i))
                                ? new File(getExternalFilesDir(null), "ppdump") : null;
                        try {
                            long t0 = android.os.SystemClock.elapsedRealtime();
                            List<PpOcrEngine.Line> r = pp.run(in);
                            long ms = android.os.SystemClock.elapsedRealtime() - t0;
                            totalRaw += ms;
                            sb.append("PP 原始|").append(names.get(i)).append('|')
                              .append(ms).append("ms: ")
                              .append(joinPP(r)).append('\n');
                        } catch (Throwable t) {
                            sb.append("PP 原始|").append(names.get(i))
                              .append(" FAILED: ").append(brief(t)).append('\n');
                        }
                        try {                               // 加同一套预处理后再试一遍
                            Bitmap pre = preprocess(in);
                            long t0 = android.os.SystemClock.elapsedRealtime();
                            List<PpOcrEngine.Line> r = pp.run(pre);
                            long ms = android.os.SystemClock.elapsedRealtime() - t0;
                            totalPre += ms;
                            sb.append("PP 预处理|").append(names.get(i)).append('|')
                              .append(ms).append("ms: ")
                              .append(joinPP(r)).append('\n');
                            pre.recycle();
                        } catch (Throwable t) {
                            sb.append("PP 预处理|").append(names.get(i))
                              .append(" FAILED: ").append(brief(t)).append('\n');
                        }
                    }
                    // 正式识别路径（PP-OCR → 预处理 → 旋转）实测
                    for (int i = 0; i < inputs.size(); i++) {
                        if (!"真机照片".equals(names.get(i))) continue;
                        try {
                            long t0 = android.os.SystemClock.elapsedRealtime();
                            String r = recognizeText(inputs.get(i));
                            sb.append("正式路径|").append(names.get(i)).append('|')
                              .append(android.os.SystemClock.elapsedRealtime() - t0)
                              .append("ms: ").append(r.replace('\n', '␤')).append('\n');
                        } catch (Throwable t) {
                            sb.append("正式路径 FAILED: ").append(brief(t)).append('\n');
                        }
                    }
                    sb.append("PP 合计: 原始 ").append(totalRaw).append("ms / 预处理 ")
                      .append(totalPre).append("ms，共 ").append(inputs.size()).append(" 张\n");
                    PpOcrEngine.dumpDir = null;
                    for (Bitmap b : inputs) {
                        b.recycle();
                    }
                }
                android.util.Log.i("CGMDIAG", sb.toString());
                // logcat 单条上限 ~4068 字节，回归素材结果多时会被截尾 → 逐行再打一遍
                for (String line : sb.toString().split("\n")) {
                    if (!line.isEmpty()) {
                        android.util.Log.i("CGMDIAGL", line);
                    }
                }
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        tv.setText(sb.toString());
                    }
                });
            }
        });
    }

    // ------------------------------------------------------------- 入口流

    /** 画一张「小字标签」：文字高约 16px、四周留 margin 像素的白边（0=紧贴），
     *  gray=true 时用灰底模拟照片。给自检当回归输入用。 */
    private static Bitmap miniLabel(String text, boolean gray) {
        int textPx = 16;
        int margin = 0;
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setTextSize(textPx);
        p.setTypeface(Typeface.DEFAULT_BOLD);
        p.setColor(Color.BLACK);
        Paint.FontMetrics fm = p.getFontMetrics();
        int tw = (int) p.measureText(text);
        int th = (int) (fm.descent - fm.ascent);
        Bitmap bmp = Bitmap.createBitmap(tw + margin * 2 + 2, th + margin * 2 + 2,
                Bitmap.Config.ARGB_8888);
        bmp.eraseColor(gray ? 0xffcfd3d8 : Color.WHITE);
        new Canvas(bmp).drawText(text, margin + 1, margin + 1 - fm.ascent, p);
        return bmp;
    }

    /** 申请相机权限前先说明用途（合规要求：权限使用告知）。 */
    private void askCameraPerm() {
        new android.app.AlertDialog.Builder(this)
                .setTitle("需要相机权限")
                .setMessage(isQr
                        ? "扫二维码需要使用相机取景。画面仅在手机本地处理，不保存、不上传。"
                        : "拍照识别型号需要拍一张照片，识别完全在手机本地完成（离线 OCR）；"
                          + "照片不保存到相册、不上传，识别完立即删除。")
                .setCancelable(false)
                .setPositiveButton("去允许",
                        new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface d, int w) {
                                requestPermissions(
                                        new String[]{Manifest.permission.CAMERA},
                                        REQ_PERM);
                            }
                        })
                .setNegativeButton("暂不",
                        new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface d, int w) {
                                toast("没有相机权限，无法拍照识别（可在系统设置里允许）");
                                setResult(RESULT_CANCELED);
                                finish();
                            }
                        })
                .show();
    }

    /** 型号识别：申请相机权限（清单声明了 CAMERA 就必须先授予）→ 拉起系统相机。 */
    private void startShootFlow() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            askCameraPerm();
            return;
        }
        launchCameraIntent();
    }

    /** 拍一张：走系统相机（全分辨率 + 自动对焦/HDR），照片写进 cacheDir 临时文件。 */
    private void launchCameraIntent() {
        status.setText("正在打开相机…");
        tmpFile = new File(new File(getCacheDir(), "photos"), "scan_tmp.jpg");
        tmpFile.getParentFile().mkdirs();
        tmpFile.delete();                       // 清掉上一次的残留
        Uri out = PhotoProvider.uriFor(tmpFile.getName());
        Intent it = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
        it.putExtra(android.provider.MediaStore.EXTRA_OUTPUT, out);
        // 关键：EXTRA_OUTPUT 的 content:// 必须经 ClipData 授权，只加 Intent flags
        // 部分相机（如 MIUI）拿不到写权限 → 不写文件、只回缩略图 → 照片丢失
        it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        it.setClipData(ClipData.newRawUri("photos", out));
        try {
            startActivityForResult(it, REQ_SHOOT);
        } catch (Throwable e) {
            status.setText("打不开相机，点这里重试");
            toast("打不开系统相机：" + e.getClass().getSimpleName());
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req != REQ_SHOOT) return;
        if (res != RESULT_OK) {
            finish();                           // 用户在相机里按了返回
            return;
        }
        status.setText("正在载入照片…");
        Bitmap bmp = decodePhoto();
        if (bmp == null) {
            status.setText("照片读取失败，点「重拍」再试");
            toast("照片读取失败，请重拍");
            return;
        }
        photoBitmap = bmp;
        showCropUi();
    }

    /** 采样解码（长边 ≤ PHOTO_MAX_EDGE，控内存峰值）+ 按 EXIF 摆正方向。 */
    private Bitmap decodePhoto() {
        if (tmpFile == null || !tmpFile.isFile()) return null;
        try {
            BitmapFactory.Options b = new BitmapFactory.Options();
            b.inJustDecodeBounds = true;
            BitmapFactory.decodeFile(tmpFile.getAbsolutePath(), b);
            int edge = Math.max(b.outWidth, b.outHeight);
            int sample = 1;
            while (edge / (sample * 2) >= 1280) {
                sample *= 2;
            }
            BitmapFactory.Options o = new BitmapFactory.Options();
            o.inSampleSize = sample;
            Bitmap bmp = BitmapFactory.decodeFile(tmpFile.getAbsolutePath(), o);
            if (bmp == null) return null;

            int deg = 0;
            try {
                ExifInterface ex = new ExifInterface(tmpFile.getAbsolutePath());
                int v = ex.getAttributeInt(ExifInterface.TAG_ORIENTATION,
                        ExifInterface.ORIENTATION_NORMAL);
                if (v == ExifInterface.ORIENTATION_ROTATE_90) deg = 90;
                else if (v == ExifInterface.ORIENTATION_ROTATE_180) deg = 180;
                else if (v == ExifInterface.ORIENTATION_ROTATE_270) deg = 270;
            } catch (Throwable ignored) {
            }
            if (deg != 0) {
                Matrix m = new Matrix();
                m.postRotate(deg);
                Bitmap up = Bitmap.createBitmap(bmp, 0, 0,
                        bmp.getWidth(), bmp.getHeight(), m, true);
                if (up != bmp) {
                    bmp.recycle();
                    bmp = up;
                }
            }
            return bmp;
        } catch (Throwable t) {
            return null;
        }
    }

    /** 显示照片 + 框选层 + 重拍/识别按钮。 */
    private void showCropUi() {
        if (cropView != null) root.removeView(cropView);
        cropView = new CropView(this, photoBitmap);
        // 插到最底层：顶栏/底栏（取消、状态、重拍/识别）必须保持在它上面可点
        root.addView(cropView, 0, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        actions.setVisibility(View.VISIBLE);
        status.setText("拖四角框字，双指缩放，放大后单指在框外拖动可移动照片，点「识别」");
        warmUp();                               // 后台先把模型读进来，点识别时几乎不用等
        hintBig.setText("");
        hintBig.setTag(null);
        hintBig.setBackgroundColor(Color.TRANSPARENT);
        choices.removeAllViews();
    }

    private void setActionsEnabled(boolean on) {
        for (int i = 0; i < actions.getChildCount(); i++) {
            actions.getChildAt(i).setEnabled(on);
        }
    }

    /** 预热识别引擎：照片出来后就在后台把模型读进内存，点「识别」时基本立刻出结果。 */
    private void warmUp() {
        worker.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    ensurePp();                 // 主引擎（PP-OCR）先热起来，约 0.3~0.5 秒
                } catch (Throwable ignored) {   // 失败留给点「识别」时报出来
                }
            }
        });
    }

    /** 执行识别：只把框选区域交给引擎（排除背景干扰，识别更快更准）。 */
    private void onRecognizeClicked() {
        if (photoBitmap == null || cropView == null || photoBitmap.isRecycled()) return;
        status.setText("识别中…");
        setActionsEnabled(false);
        hintBig.setText("");
        hintBig.setTag(null);
        hintBig.setBackgroundColor(Color.TRANSPARENT);
        choices.removeAllViews();

        float[] rect = cropView.normalizedRect();
        int w = photoBitmap.getWidth();
        int h = photoBitmap.getHeight();
        int left = Math.max(0, (int) (rect[0] * w) - 4);
        int top = Math.max(0, (int) (rect[1] * h) - 4);
        int right = Math.min(w, (int) (rect[2] * w) + 4);
        int bottom = Math.min(h, (int) (rect[3] * h) + 4);
        if (right - left < 8 || bottom - top < 8) {
            setActionsEnabled(true);
            status.setText("框太小了，框大一点再识别");
            return;
        }
        final Bitmap crop = Bitmap.createBitmap(photoBitmap, left, top,
                right - left, bottom - top);
        runText(crop);
    }

    private void runText(final Bitmap crop) {
        worker.execute(new Runnable() {
            @Override
            public void run() {
                String text = null;
                String err = null;
                try {
                    text = recognizeText(crop);
                } catch (Throwable t) {
                    err = brief(t);
                } finally {
                    crop.recycle();             // 识别完立即释放，内存不留峰值
                }
                final String res = text;
                final String e = err;
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (isFinishing()) return;
                        setActionsEnabled(true);
                        if (e != null) {
                            status.setText("识别引擎不可用 v" + verName() + "（" + e
                                    + "），长按「识别」看诊断");
                            return;
                        }
                        showLines(cleanLines(res));
                    }
                });
            }
        });
    }



    /** 旋转位图（90/180/270）。 */
    private static Bitmap rotate(Bitmap b, int deg) {
        android.graphics.Matrix m = new android.graphics.Matrix();
        m.postRotate(deg);
        return Bitmap.createBitmap(b, 0, 0, b.getWidth(), b.getHeight(), m, true);
    }

    /** 识别前处理（v1.30 重写，专治「字很小很清晰却认不出」）：
     *  ① 放大到引擎合适的尺寸——框选出来的小图若直接喂，笔画只有几个像素高；
     *  ② 放大后 3×3 锐化——双线性放大把小字笔画糊开，糊了就认不出；
     *  ③ 去色 + 2%/98% 对比度拉伸——发灰的照片拉成黑白分明；
     *  ④ 四周加白边——文字贴着图边时引擎经常整张认不出，
     *     「框得越准反而越失败」的主因就是它。
     *  内存峰值约 (2000+边距)²×4B ≈ 17MB，可接受。 */
    private Bitmap preprocess(Bitmap src) {
        int w = src.getWidth();
        int h = src.getHeight();
        int longEdge = Math.max(w, h);
        int shortEdge = Math.min(w, h);
        float scale = 1f;
        if (longEdge < 1500) scale = 1500f / longEdge;          // 小图：放大（宁大勿小）
        else if (longEdge > 2000) scale = 2000f / longEdge;     // 太大：略缩，省内存也更快
        if (shortEdge * scale < 320) scale = 320f / shortEdge;  // 窄长条单行字：再放大

        int dw = Math.max(1, Math.round(w * scale));
        int dh = Math.max(1, Math.round(h * scale));
        Bitmap up = Bitmap.createBitmap(dw, dh, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(up);
        Paint p = new Paint(Paint.FILTER_BITMAP_FLAG | Paint.ANTI_ALIAS_FLAG);
        ColorMatrix cm = new ColorMatrix();
        cm.setSaturation(0f);                                   // 去色：文字/背景对比更纯
        p.setColorFilter(new ColorMatrixColorFilter(cm));
        c.drawBitmap(src, null, new Rect(0, 0, dw, dh), p);

        int n = dw * dh;
        int[] px = new int[n];
        up.getPixels(px, 0, dw, 0, 0, dw, dh);
        up.recycle();
        sharpen(px, dw, dh);
        stretch(px, n);
        int pad = Math.max(12, Math.max(dw, dh) / 28);          // 白边防「贴边认不出」
        Bitmap out = Bitmap.createBitmap(dw + pad * 2, dh + pad * 2,
                Bitmap.Config.ARGB_8888);
        out.eraseColor(Color.WHITE);
        out.setPixels(px, 0, dw, pad, pad, dw, dh);
        return out;
    }

    /** 3×3 锐化（unsharp：5×中心 - 上下左右），只处理已去色的 R 通道，边缘写回灰度。 */
    private static void sharpen(int[] px, int w, int h) {
        if (w < 3 || h < 3) return;
        int[] src = px.clone();
        for (int y = 1; y < h - 1; y++) {
            for (int x = 1; x < w - 1; x++) {
                int i = y * w + x;
                int c = (src[i] >> 16) & 0xff;
                int sum = ((src[i - 1] >> 16) & 0xff) + ((src[i + 1] >> 16) & 0xff)
                        + ((src[i - w] >> 16) & 0xff) + ((src[i + w] >> 16) & 0xff);
                int v = c * 5 - sum;
                v = v < 0 ? 0 : (Math.min(v, 255));
                px[i] = 0xff000000 | (v << 16) | (v << 8) | v;
            }
        }
    }

    /** 对比度线性拉伸（按 2%/98% 分位），把发灰的照片拉成黑白分明，引擎更认。 */
    private static void stretch(int[] px, int n) {
        if (n <= 0) return;
        int[] hist = new int[256];
        for (int i = 0; i < n; i++) {
            hist[(px[i] >> 16) & 0xff]++;                       // 已去色，取 R 通道即可
        }
        int lo = 0, hi = 255, acc = 0;
        int lowN = (int) (n * 0.02f), hiN = (int) (n * 0.98f);
        for (int v = 0; v < 256; v++) {
            acc += hist[v];
            if (acc >= lowN) { lo = v; break; }
        }
        acc = 0;
        for (int v = 0; v < 256; v++) {
            acc += hist[v];
            if (acc >= hiN) { hi = v; break; }
        }
        if (hi - lo < 16) return;                               // 本来就够对比，不动
        float k = 255f / (hi - lo);
        for (int i = 0; i < n; i++) {
            int v = (int) ((((px[i] >> 16) & 0xff) - lo) * k);
            v = v < 0 ? 0 : (v > 255 ? 255 : v);
            px[i] = 0xff000000 | (v << 16) | (v << 8) | v;
        }
    }


    /** 异常压成一小段可读文字，方便用户反馈时截图。 */
    private String brief(Throwable t) {
        String m = t.getMessage();
        if (m == null || m.trim().isEmpty()) return t.getClass().getSimpleName();
        m = m.replace('\n', ' ').trim();
        return m.length() > 60 ? m.substring(0, 60) + "…" : m;
    }

    /** PP-OCR 多行结果拼一行（诊断日志用）。 */
    private static String joinPP(List<PpOcrEngine.Line> lines) {
        if (lines == null || lines.isEmpty()) return "(空)";
        StringBuilder sb = new StringBuilder();
        for (PpOcrEngine.Line l : lines) {
            if (sb.length() > 0) sb.append(" | ");
            sb.append(l.text);
        }
        return sb.toString();
    }

    /** 当前 APK 版本名，失败提示里带上，便于确认手机上跑的是哪个包。 */
    private String verName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Throwable t) {
            return "?";
        }
    }

    /** 正式识别入口（v1.31 起引擎换成 PP-OCR，Tesseract 已移除）：
     *  ① PP-OCR 原始图 —— 检测框自带透视矫正，倒着拍由 cls 方向分类自动转正；
     *  ② 还认不出 → 套一套预处理（放大/锐化/补白边）再来一次，专治极小字；
     *  ③ 仍然空手 → 顺/逆时针 90° 各试一次（标签横着拍时检测会漏）。
     *  只在 worker 单线程里调用：引擎非线程安全。 */
    private String recognizeText(Bitmap crop) throws Exception {
        try {
            return linesToText(ppLines(ensurePp(), crop));
        } catch (Throwable t) {
            if (t instanceof Exception) throw (Exception) t;
            throw new IllegalStateException(t);
        }
    }

    /** 跑 PP-OCR：原图 → 预处理图 → 旋转 90/270，谁先出字用谁。 */
    private List<PpOcrEngine.Line> ppLines(PpOcrEngine e, Bitmap src) {
        List<PpOcrEngine.Line> r = e.run(src);
        if (!r.isEmpty()) return r;

        Bitmap pre = null;
        try {
            pre = preprocess(src);
            r = e.run(pre);
            if (!r.isEmpty()) return r;
        } catch (Throwable ignored) {           // 预处理只是加分项，失败不影响主流程
        } finally {
            if (pre != null) pre.recycle();
        }

        for (int deg : new int[]{90, 270}) {
            Bitmap rot = null;
            try {
                rot = rotate(src, deg);
                r = e.run(rot);
                if (!r.isEmpty()) return r;
            } catch (Throwable ignored) {
            } finally {
                if (rot != null) rot.recycle();
            }
        }
        return r;
    }

    /** PP-OCR 多行结果拼回文本（按行，交给 cleanLines 去重/过滤）。 */
    private static String linesToText(List<PpOcrEngine.Line> lines) {
        if (lines == null || lines.isEmpty()) return "";
        StringBuilder sb = new StringBuilder();
        for (PpOcrEngine.Line l : lines) {
            String s = l.text == null ? "" : l.text.trim();
            if (s.isEmpty()) continue;
            if (sb.length() > 0) sb.append('\n');
            sb.append(s);
        }
        return sb.toString();
    }

    /** 取（必要时初始化）PP-OCR 主引擎：模型随 APK 打包在 assets/ppocr，首次解压到私有目录。
     *  三个模型 det(9.9MB)/rec(21MB)/cls(0.6MB) 一次性读入，之后常驻。 */
    private synchronized PpOcrEngine ensurePp() throws Exception {
        if (sPp != null) return sPp;
        sPp = PpOcrEngine.create(getAssets(), getFilesDir());
        return sPp;
    }



    /** 从识别文本里挑出像型号/说明的行（去空、去符号行、去重，最多 6 行）。 */
    private List<String> cleanLines(String text) {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        if (text != null) {
            for (String raw : text.split("\n")) {
                String s = raw.replace('\f', ' ').trim();
                if (s.length() < 2) continue;
                s = s.replaceAll("[ \\t]{2,}", " ").trim();
                if (s.replaceAll("[^0-9A-Za-z\\u4e00-\\u9fa5]", "").length() < 2) {
                    continue;
                }
                out.add(s);
            }
        }
        List<String> list = new ArrayList<>(out);
        return list.size() > 6 ? list.subList(0, 6) : list;
    }

    private void showLines(List<String> lines) {
        if (lines.isEmpty()) {
            status.setText("没认出文字：靠近点重拍让字占满框，或换个角度/光线再试");
            return;
        }
        String top = lines.get(0);
        hintBig.setText("填入：" + top);
        hintBig.setTag(top);
        hintBig.setBackgroundColor(Color.parseColor("#1f6feb"));
        status.setText("识别到 " + lines.size() + " 行，点下面的文字填入；不合适可重拍");
        choices.removeAllViews();
        for (int i = 1; i < lines.size(); i++) {
            final String s = lines.get(i);
            Button b = new Button(this);
            b.setAllCaps(false);
            b.setText(s);
            b.setTextSize(15);
            b.setTextColor(Color.WHITE);
            b.setBackgroundColor(Color.argb(60, 255, 255, 255));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.topMargin = dp(6);
            b.setLayoutParams(lp);
            b.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    finishWith(s);
                }
            });
            choices.addView(b);
        }
    }

    private void onRetakeClicked() {
        if (photoBitmap != null) {
            photoBitmap.recycle();
            photoBitmap = null;
        }
        if (cropView != null) {
            root.removeView(cropView);
            cropView = null;
        }
        actions.setVisibility(View.GONE);
        launchCameraIntent();
    }

    private void cleanupTemp() {
        if (tmpFile != null) {
            tmpFile.delete();                   // 照片即拍即用即删，不占存储
            tmpFile = null;
        }
    }

    @Override
    public void onRequestPermissionsResult(int req, String[] perms, int[] grants) {
        super.onRequestPermissionsResult(req, perms, grants);
        if (req != REQ_PERM) return;
        if (grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) {
            if (isQr) {
                startCamera();
            } else {
                launchCameraIntent();
            }
        } else {
            toast("没有相机权限，无法拍照识别（可在系统设置里允许）");
            setResult(RESULT_CANCELED);
            finish();
        }
    }

    // ------------------------------------------------------------- 界面
    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                getResources().getDisplayMetrics());
    }

    private void buildUi() {
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        if (isQr) {
            preview = new SurfaceView(this);
            root.addView(preview, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            preview.getHolder().addCallback(this);
            // 点画面手动对焦（近拍时连续对焦常常收不住，手动点一下立刻清晰）
            preview.setOnTouchListener(new View.OnTouchListener() {
                @Override
                public boolean onTouch(View v, MotionEvent event) {
                    if (event.getAction() == MotionEvent.ACTION_UP) {
                        tapFocus(event.getX(), event.getY());
                    }
                    return true;
                }
            });
            // 取景框（扫二维码用方形框）
            root.addView(new FrameView(this, true), new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(dp(14), dp(10), dp(8), dp(10));
        top.setBackgroundColor(Color.argb(150, 0, 0, 0));

        TextView title = new TextView(this);
        title.setText(isQr ? "扫电脑二维码连接" : "拍一张型号照片");
        title.setTextColor(Color.WHITE);
        title.setTextSize(16);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setLayoutParams(new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        Button close = new Button(this);
        close.setText("取消");
        close.setAllCaps(false);
        close.setTextSize(14);
        close.setTextColor(Color.WHITE);
        close.setBackgroundColor(Color.TRANSPARENT);
        close.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                setResult(RESULT_CANCELED);
                finish();
            }
        });

        top.addView(title);
        top.addView(close);
        root.addView(top, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP));

        // 底部：状态 + 候选 + 操作按钮
        LinearLayout bottom = new LinearLayout(this);
        bottom.setOrientation(LinearLayout.VERTICAL);
        bottom.setPadding(dp(14), dp(12), dp(14), dp(20));
        bottom.setBackgroundColor(Color.argb(170, 0, 0, 0));

        status = new TextView(this);
        status.setText(isQr ? "把电脑上的二维码放进框内…（点画面可对焦）" : "正在打开相机…");
        status.setTextColor(Color.parseColor("#d7e2f5"));
        status.setTextSize(13);
        status.setGravity(Gravity.CENTER);

        hintBig = new TextView(this);
        hintBig.setText("");
        hintBig.setTextColor(Color.WHITE);
        hintBig.setTextSize(17);
        hintBig.setTypeface(Typeface.DEFAULT_BOLD);
        hintBig.setGravity(Gravity.CENTER);
        hintBig.setPadding(0, dp(8), 0, dp(8));
        hintBig.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String t = (String) v.getTag();
                if (t != null && t.length() > 0) finishWith(t);
            }
        });

        choices = new LinearLayout(this);
        choices.setOrientation(LinearLayout.VERTICAL);
        choices.setPadding(0, dp(4), 0, 0);

        actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.CENTER);
        actions.setVisibility(isQr ? View.GONE : View.VISIBLE);

        Button retake = new Button(this);
        retake.setText("重拍");
        retake.setAllCaps(false);
        retake.setTextSize(15);
        retake.setTextColor(Color.WHITE);
        retake.setBackgroundColor(Color.parseColor("#3c4043"));
        retake.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onRetakeClicked();
            }
        });

        Button ok = new Button(this);
        ok.setText("识别");
        ok.setAllCaps(false);
        ok.setTextSize(15);
        ok.setTextColor(Color.WHITE);
        ok.setBackgroundColor(Color.parseColor("#1f6feb"));
        ok.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onRecognizeClicked();
            }
        });
        // 长按「识别」= 自检：不开相机，跑一遍「初始化引擎→识别样图」并把每步结果显示出来，
        // 用户截图即可反馈问题（手机上没法看 logcat）。
        ok.setOnLongClickListener(new View.OnLongClickListener() {
            @Override
            public boolean onLongClick(View v) {
                runDiag();
                return true;
            }
        });

        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        bp.rightMargin = dp(18);
        actions.addView(retake, bp);
        actions.addView(ok);

        bottom.addView(status);
        bottom.addView(hintBig);
        bottom.addView(choices);
        bottom.addView(actions);
        root.addView(bottom, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM));

        setContentView(root);
    }

    /** 框选层：照片按比例显示，双指可缩放（1~8 倍）看小字，拖动四角/整体调整框。 */
    private class CropView extends View {
        private static final int M_NONE = 0;
        private static final int M_MOVE = 1;
        private static final int M_TL = 2;
        private static final int M_TR = 3;
        private static final int M_BL = 4;
        private static final int M_BR = 5;
        private static final int M_PAN = 6;     // 单指在框外拖动 = 平移放大后的照片

        private final Bitmap bmp;
        private final Paint dim = new Paint();
        private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint bmpPaint = new Paint(Paint.FILTER_BITMAP_FLAG);
        private final RectF draw = new RectF();      // 图片显示区域（fitCenter）
        private final RectF box = new RectF();       // 框选区域（屏幕坐标）
        private float l = 0.06f, t = 0.36f, r = 0.94f, b = 0.64f;   // 归一化框
        private int mode = M_NONE;
        private float lastX = 0f;
        private float lastY = 0f;
        private float zoom = 1f;                    // 双指缩放倍数（1~8），小字先放大再框
        private float ox = 0f, oy = 0f;             // 缩放后图片左上角在视图中的位置
        private float pinchDist = 0f;               // 双指间距（捏合缩放用）
        private boolean pinching = false;

        CropView(Activity c, Bitmap bitmap) {
            super(c);
            bmp = bitmap;
            dim.setColor(Color.argb(110, 0, 0, 0));
            line.setColor(Color.parseColor("#46b1ff"));
            line.setStyle(Paint.Style.STROKE);
            line.setStrokeWidth(dp(2));
            dot.setColor(Color.parseColor("#46b1ff"));
        }

        /** 返回归一化框 {left, top, right, bottom}（相对原图比例）。 */
        float[] normalizedRect() {
            return new float[]{l, t, r, b};
        }

        private void layout() {
            if (bmp == null || bmp.isRecycled() || getWidth() == 0 || getHeight() == 0) {
                return;
            }
            float iw = bmp.getWidth();
            float ih = bmp.getHeight();
            float vw = getWidth();
            float vh = getHeight();
            float k = Math.min(vw / iw, vh / ih);
            float dw = iw * k * zoom;
            float dh = ih * k * zoom;
            if (dw <= vw) {
                ox = (vw - dw) / 2f;
            } else {
                ox = Math.max(vw - dw, Math.min(0f, ox));
            }
            if (dh <= vh) {
                oy = (vh - dh) / 2f;
            } else {
                oy = Math.max(vh - dh, Math.min(0f, oy));
            }
            draw.set(ox, oy, ox + dw, oy + dh);
            box.set(draw.left + l * draw.width(), draw.top + t * draw.height(),
                    draw.left + r * draw.width(), draw.top + b * draw.height());
        }

        @Override
        protected void onSizeChanged(int w, int h, int ow, int oh) {
            super.onSizeChanged(w, h, ow, oh);
            layout();
        }

        private boolean near(float x, float y, float cx, float cy) {
            float rad = dp(30);
            return Math.abs(x - cx) <= rad && Math.abs(y - cy) <= rad;
        }

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            if (bmp == null || bmp.isRecycled() || draw.isEmpty()) return true;
            if (event.getActionMasked() == MotionEvent.ACTION_POINTER_DOWN
                    && event.getPointerCount() >= 2) {
                // 第二根手指按下：进入捏合缩放，暂停拖框
                pinching = true;
                mode = M_NONE;
                pinchDist = dist(event.getX(0), event.getY(0),
                        event.getX(1), event.getY(1));
                return true;
            }
            float x = event.getX();
            float y = event.getY();
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                lastX = x;
                lastY = y;
                layout();
                if (near(x, y, box.left, box.top)) mode = M_TL;
                else if (near(x, y, box.right, box.top)) mode = M_TR;
                else if (near(x, y, box.left, box.bottom)) mode = M_BL;
                else if (near(x, y, box.right, box.bottom)) mode = M_BR;
                else if (box.contains(x, y)) mode = M_MOVE;
                else mode = (zoom > 1f) ? M_PAN : M_NONE;   // 放大后框外拖动平移照片
                return true;
            }
            if (event.getActionMasked() == MotionEvent.ACTION_POINTER_UP
                    && pinching && event.getPointerCount() <= 2) {
                // 抬起一根手指：退出捏合，剩下的那根接着用（放大状态下直接平移照片）
                pinching = false;
                pinchDist = 0f;
                int stay = event.getActionIndex() == 0 ? 1 : 0;
                lastX = event.getX(stay);
                lastY = event.getY(stay);
                mode = (zoom > 1f) ? M_PAN : M_NONE;
                return true;
            }
            if (event.getActionMasked() == MotionEvent.ACTION_MOVE
                    && pinching && event.getPointerCount() >= 2) {
                float nd = dist(event.getX(0), event.getY(0),
                        event.getX(1), event.getY(1));
                if (pinchDist > 0f && nd > 0f && draw.width() > 0) {
                    float midX = (event.getX(0) + event.getX(1)) / 2f;
                    float midY = (event.getY(0) + event.getY(1)) / 2f;
                    float nx = (midX - ox) / draw.width();      // 锚点（照片归一化坐标）
                    float ny = (midY - oy) / draw.height();
                    zoom = Math.max(1f, Math.min(8f, zoom * nd / pinchDist));
                    layout();                                   // 先按新倍数算出尺寸
                    ox = midX - nx * draw.width();              // 再让锚点跟住手指中点
                    oy = midY - ny * draw.height();
                    layout();
                    invalidate();
                }
                pinchDist = nd;
                return true;
            }
            if (event.getActionMasked() == MotionEvent.ACTION_MOVE
                    && !pinching && mode != M_NONE) {
                float dx = x - lastX;
                float dy = y - lastY;
                float dnx = dx / draw.width();
                float dny = dy / draw.height();
                lastX = x;
                lastY = y;
                if (mode == M_PAN) {
                    // 平移照片：手指往哪儿拖照片就往哪儿走，layout() 会自动夹住边界
                    ox += dx;
                    oy += dy;
                    layout();
                    invalidate();
                    return true;
                }
                if (mode == M_MOVE) {
                    float w = r - l;
                    float hh = b - t;
                    l = clamp01(Math.min(Math.max(0f, l + dnx), 1f - w));
                    r = l + w;
                    t = clamp01(Math.min(Math.max(0f, t + dny), 1f - hh));
                    b = t + hh;
                } else {
                    // 最小框随缩放走：屏幕上始终保持约 22dp 可捏，
                    // 放大照片后就能框住一行很小的字（1% 宽度起步）；
                    // 不放大时不低于原来的 5%，行为不变
                    float minSize = Math.max(0.010f,
                            Math.min(0.05f, dp(22) / draw.width()));
                    if (mode == M_TL || mode == M_BL) l = clamp01(Math.min(l + dnx, r - minSize));
                    if (mode == M_TR || mode == M_BR) r = clamp01(Math.max(r + dnx, l + minSize));
                    if (mode == M_TL || mode == M_TR) t = clamp01(Math.min(t + dny, b - minSize));
                    if (mode == M_BL || mode == M_BR) b = clamp01(Math.max(b + dny, t + minSize));
                }
                layout();
                invalidate();
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_UP
                    || event.getAction() == MotionEvent.ACTION_CANCEL) {
                mode = M_NONE;
                pinching = false;
                pinchDist = 0f;
                return true;
            }
            return true;
        }

        private float dist(float x1, float y1, float x2, float y2) {
            float dx = x2 - x1, dy = y2 - y1;
            return (float) Math.sqrt(dx * dx + dy * dy);
        }

        private float clamp01(float v) {
            return v < 0f ? 0f : (Math.min(v, 1f));
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (bmp == null || bmp.isRecycled() || draw.isEmpty()) return;
            canvas.drawBitmap(bmp, null, draw, bmpPaint);
            // 框外压暗
            canvas.drawRect(draw.left, draw.top, draw.right, box.top, dim);
            canvas.drawRect(draw.left, box.bottom, draw.right, draw.bottom, dim);
            canvas.drawRect(draw.left, box.top, box.left, box.bottom, dim);
            canvas.drawRect(box.right, box.top, draw.right, box.bottom, dim);
            // 框 + 四角圆点
            canvas.drawRect(box, line);
            float rad = dp(6);
            canvas.drawCircle(box.left, box.top, rad, dot);
            canvas.drawCircle(box.right, box.top, rad, dot);
            canvas.drawCircle(box.left, box.bottom, rad, dot);
            canvas.drawCircle(box.right, box.bottom, rad, dot);
        }
    }

    /** 二维码取景框（方形 + 遮罩）。 */
    private class FrameView extends View {
        private final Paint dim = new Paint();
        private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Rect box = new Rect();

        FrameView(Activity c, boolean square) {
            super(c);
            dim.setColor(Color.argb(110, 0, 0, 0));
            line.setColor(Color.parseColor("#46b1ff"));
            line.setStyle(Paint.Style.STROKE);
            line.setStrokeWidth(dp(2));
        }

        private void calcBox() {
            int w = getWidth();
            int h = getHeight();
            int side = Math.min((int) (w * 0.78f), (int) (h * 0.46f));
            int left = (w - side) / 2;
            int top = (h - side) / 2 - (int) (h * 0.04f);
            if (top < 0) top = 0;
            if (left < 0) left = 0;
            box.set(left, top, left + side, top + side);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            calcBox();
            canvas.drawRect(0, 0, getWidth(), box.top, dim);
            canvas.drawRect(0, box.bottom, getWidth(), getHeight(), dim);
            canvas.drawRect(0, box.top, box.left, box.bottom, dim);
            canvas.drawRect(box.right, box.top, getWidth(), box.bottom, dim);
            canvas.drawRect(box, line);
            // 四角
            int c = dp(18);
            line.setStrokeWidth(dp(3));
            canvas.drawLine(box.left, box.top, box.left + c, box.top, line);
            canvas.drawLine(box.left, box.top, box.left, box.top + c, line);
            canvas.drawLine(box.right, box.top, box.right - c, box.top, line);
            canvas.drawLine(box.right, box.top, box.right, box.top + c, line);
            canvas.drawLine(box.left, box.bottom, box.left + c, box.bottom, line);
            canvas.drawLine(box.left, box.bottom, box.left, box.bottom - c, line);
            canvas.drawLine(box.right, box.bottom, box.right - c, box.bottom, line);
            canvas.drawLine(box.right, box.bottom, box.right, box.bottom - c, line);
            line.setStrokeWidth(dp(2));
        }
    }

    // ------------------------------------------------------------- 相机（二维码模式）
    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        startCamera();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int fmt, int w, int h) {
        if (camera == null) return;
        try {
            camera.stopPreview();
        } catch (Throwable ignored) {
        }
        previewRunning = false;
        openPreview();
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        previewRunning = false;
        releaseCamera();
    }

    /** 打不开相机的兜底态：返回是否成功拿到了 Camera 对象。 */
    private boolean startCamera() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            return false;                      // 等权限回调
        }
        if (camera != null) {
            openPreview();
            return true;
        }
        if (!surfaceReady()) {                 // surface 还没建好，等 surfaceCreated 回调
            status.setText("正在打开相机…");
            return false;
        }

        Camera c = null;
        try {
            c = openBackCamera();
        } catch (Throwable ignored) {
            c = null;
        }
        if (c == null) {
            status.setText("相机打不开（可能被其它应用占用），点这里重试");
            toast("相机打不开，请关掉其它拍照应用后重试");
            return false;
        }
        camera = c;

        try {
            Camera.Parameters p = c.getParameters();
            p.setPreviewFormat(ImageFormat.NV21);
            Camera.Size best = pickSize(p.getSupportedPreviewSizes());
            if (best != null) {
                p.setPreviewSize(best.width, best.height);
            }
            try {
                // 对焦模式按机型支持度取最优：连续对焦 > 微距（近拍）> 单次自动
                String fm = pickFocusMode(p.getSupportedFocusModes());
                if (fm != null) {
                    p.setFocusMode(fm);
                }
            } catch (Throwable ignored) {
            }
            c.setParameters(p);

            Camera.Size real = c.getParameters().getPreviewSize();   // 以实际生效为准
            if (real != null) previewSize = real;

            Camera.CameraInfo info = new Camera.CameraInfo();
            Camera.getCameraInfo(camIdx, info);
            rotateDeg = info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT
                    ? (360 - info.orientation) % 360 : info.orientation;
            c.setDisplayOrientation(rotateDeg);

            // 帧回调必须在 startPreview 之前挂上，否则部分机型不出帧
            if (previewSize != null) {
                int bits = ImageFormat.getBitsPerPixel(ImageFormat.NV21);
                int need = previewSize.width * previewSize.height * bits / 8;
                if (need > 0 && (frameBuffer == null || frameBuffer.length != need)) {
                    frameBuffer = new byte[need];
                }
                c.setPreviewCallbackWithBuffer(new Camera.PreviewCallback() {
                    @Override
                    public void onPreviewFrame(byte[] data, Camera cam) {
                        lastFrameAt = System.currentTimeMillis();
                        restartCount = 0;          // 真的出画面了才算恢复正常
                        if (data != null) {
                            try {
                                grabQr(data);
                            } catch (Throwable ignored) {
                            }
                        }
                        if (frameBuffer != null) {
                            try {
                                cam.addCallbackBuffer(frameBuffer);
                            } catch (Throwable ignored) {
                            }
                        }
                    }
                });
                c.addCallbackBuffer(frameBuffer);
            }
        } catch (Throwable e) {
            releaseCamera();
            status.setText("相机初始化失败：" + e.getClass().getSimpleName() + "，点这里重试");
            return false;
        }

        openPreview();
        return true;
    }

    /** 真正把预览挂到 SurfaceView 上并开流；surface 没准备好就安静返回，等回调再来。 */
    private void openPreview() {
        Camera c = camera;
        if (c == null) return;
        SurfaceHolder h = preview.getHolder();
        if (h == null || h.getSurface() == null || !h.getSurface().isValid()) {
            status.setText("正在打开相机…");
            return;
        }
        try {
            c.setPreviewDisplay(h);
            c.startPreview();
            previewRunning = true;
            lastFrameAt = System.currentTimeMillis();
            status.setText("把电脑上的二维码放进框内…（点画面可对焦）");
            startWatchdog();
            ui.removeCallbacks(refocus);
            ui.postDelayed(refocus, 3500);
        } catch (Throwable e) {
            previewRunning = false;
            releaseCamera();
            if (restartCount < 3) {
                restartCount += 1;
                status.setText("预览启动失败：" + e.getClass().getSimpleName() + "，正在重试…");
                ui.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        startCamera();
                    }
                }, 700);
            } else {
                status.setText("预览启动失败，点这里重试");
            }
        }
    }

    /** 按机型支持度挑对焦模式：连续对焦 > 微距 > 单次自动。 */
    private String pickFocusMode(List<String> modes) {
        if (modes == null || modes.isEmpty()) return null;
        for (String m : new String[]{
                Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE,
                Camera.Parameters.FOCUS_MODE_MACRO,
                Camera.Parameters.FOCUS_MODE_AUTO}) {
            if (modes.contains(m)) return m;
        }
        return modes.get(0);
    }

    /** 点按对焦：在点击处设对焦/测光区域，触发一次自动对焦。 */
    private void tapFocus(float x, float y) {
        final Camera c = camera;
        if (c == null || !previewRunning) return;
        lastUserFocusAt = System.currentTimeMillis();
        try {
            Camera.Parameters p = c.getParameters();
            int w = preview.getWidth();
            int h = preview.getHeight();
            if (w == 0 || h == 0) return;
            if (p.getMaxNumFocusAreas() > 0) {
                // 相机坐标系是 -1000..1000，把点击位置映射过去，取 200 半径的区域
                int cx = (int) (x / w * 2000f) - 1000;
                int cy = (int) (y / h * 2000f) - 1000;
                Rect r = new Rect(clampCam(cx - 200), clampCam(cy - 200),
                        clampCam(cx + 200), clampCam(cy + 200));
                Camera.Area area = new Camera.Area(r, 800);
                p.setFocusAreas(Collections.singletonList(area));
                if (p.getMaxNumMeteringAreas() > 0) {
                    p.setMeteringAreas(Collections.singletonList(area));
                }
                p.setFocusMode(Camera.Parameters.FOCUS_MODE_AUTO);   // 单次对焦比连续更干脆
                c.setParameters(p);
                status.setText("对焦中…点画面可重新对焦");
            }
            c.autoFocus(new Camera.AutoFocusCallback() {
                @Override
                public void onAutoFocus(boolean ok, Camera cam) {
                    resumeContinuous();
                }
            });
        } catch (Throwable ignored) {
        }
    }

    /** 单次对焦完成后回到连续对焦（清掉点按设置的区域，避免一直锁在旧位置）。 */
    private void resumeContinuous() {
        Camera c = camera;
        if (c == null) return;
        try {
            c.cancelAutoFocus();
            Camera.Parameters p = c.getParameters();
            String fm = pickFocusMode(p.getSupportedFocusModes());
            if (fm != null && !fm.equals(p.getFocusMode())) {
                p.setFocusMode(fm);
            }
            p.setFocusAreas(null);
            p.setMeteringAreas(null);
            c.setParameters(p);
            if (previewRunning) {
                status.setText("把电脑上的二维码放进框内…（点画面可对焦）");
            }
        } catch (Throwable ignored) {
        }
    }

    private static int clampCam(int v) {
        return v < -1000 ? -1000 : (Math.min(v, 1000));
    }

    /** 连续对焦近距经常"卡住不收敛"：周期性触发一次重新对焦（点按对焦后让路）。 */
    private final Runnable refocus = new Runnable() {
        @Override
        public void run() {
            if (isFinishing()) return;
            Camera c = camera;
            if (c != null && previewRunning
                    && System.currentTimeMillis() - lastUserFocusAt > 2500) {
                try {
                    c.autoFocus(new Camera.AutoFocusCallback() {
                        @Override
                        public void onAutoFocus(boolean ok, Camera cam) {
                        }
                    });
                } catch (Throwable ignored) {
                }
            }
            ui.postDelayed(this, 3500);
        }
    };

    private long lastUserFocusAt = 0L;

    /** 后摄优先（扫二维码用后摄最清楚）。 */
    private Camera openBackCamera() {
        int n = 0;
        try {
            n = Camera.getNumberOfCameras();
        } catch (Throwable ignored) {
        }
        int back = -1;
        for (int i = 0; i < n; i++) {
            Camera.CameraInfo ci = new Camera.CameraInfo();
            try {
                Camera.getCameraInfo(i, ci);
            } catch (Throwable ignored) {
                continue;
            }
            if (ci.facing == Camera.CameraInfo.CAMERA_FACING_BACK) {
                back = i;
                break;
            }
        }
        if (back < 0) back = 0;
        camIdx = back;
        try {
            return Camera.open(back);
        } catch (Throwable e) {
            return Camera.open();               // 再退一步
        }
    }

    private boolean surfaceReady() {
        SurfaceHolder h = preview == null ? null : preview.getHolder();
        return h != null && h.getSurface() != null && h.getSurface().isValid();
    }

    private Camera.Size pickSize(List<Camera.Size> sizes) {
        if (sizes == null || sizes.isEmpty()) return null;
        Camera.Size best = null;
        for (Camera.Size s : sizes) {
            if (s.width > 1600) continue;
            if (best == null || s.width > best.width) best = s;
        }
        return best != null ? best : sizes.get(0);
    }

    private void releaseCamera() {
        Camera c = camera;
        camera = null;
        previewRunning = false;
        frameBuffer = null;
        if (c != null) {
            try {
                c.setPreviewCallbackWithBuffer(null);
            } catch (Throwable ignored) {
            }
            try {
                c.stopPreview();
            } catch (Throwable ignored) {
            }
            try {
                c.release();
            } catch (Throwable ignored) {
            }
        }
    }

    // ------------------------------------------------------------- 看门狗
    private final Runnable watchdog = new Runnable() {
        @Override
        public void run() {
            if (isFinishing()) return;
            long now = System.currentTimeMillis();
            if (previewRunning && now - lastFrameAt > 4000) {
                // 预览"在跑"却收不到画面帧：重建一次（最多 3 次）
                if (restartCount < 3) {
                    restartCount += 1;
                    releaseCamera();
                    startCamera();
                    ui.postDelayed(this, 3000);
                    return;
                }
                status.setText("相机没有画面，点这里重试");
                return;
            }
            ui.postDelayed(this, 2000);
        }
    };

    private void startWatchdog() {
        ui.removeCallbacks(watchdog);
        ui.postDelayed(watchdog, 4000);
    }

    // ------------------------------------------------------------- 二维码解码
    /** 二维码模式：抓一帧（频繁一点，跟手），交给 worker 解码。 */
    private void grabQr(byte[] data) {
        long now = System.currentTimeMillis();
        if (now - lastAt < QR_GAP_MS) return;
        if (!busy.compareAndSet(false, true)) return;
        lastAt = now;

        int w = previewSize != null ? previewSize.width : 0;
        int h = previewSize != null ? previewSize.height : 0;
        if (w <= 0 || h <= 0) {
            busy.set(false);
            return;
        }
        final byte[] copy = data.clone();
        worker.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    decodeQr(copy, w, h);
                } catch (Throwable ignored) {
                } finally {
                    busy.set(false);
                }
            }
        });
    }

    /** ZXing 直接吃 NV21 的 Y 平面；QR 旋转 90° 也能解，不用先摆正。 */
    private void decodeQr(byte[] nv21, int w, int h) {
        String text = null;
        try {
            PlanarYUVLuminanceSource src =
                    new PlanarYUVLuminanceSource(nv21, w, h, 0, 0, w, h, false);
            Result r = qrReader.decode(new BinaryBitmap(new HybridBinarizer(src)));
            if (r != null) text = r.getText();
        } catch (Throwable ignored) {         // NotFoundException 等：这一帧没识别到
        }
        if (text == null || text.length() == 0) return;
        final String t = text;
        ui.post(new Runnable() {
            @Override
            public void run() {
                if (isFinishing()) return;
                status.setText("已识别二维码");
                finishWith(t);
            }
        });
    }

    private void finishWith(String text) {
        cleanupTemp();
        Intent it = new Intent();
        it.putExtra(EXTRA_TEXT, text);
        setResult(RESULT_OK, it);
        finish();
    }

    // ------------------------------------------------------------- 生命周期
    @Override
    protected void onPause() {
        super.onPause();
        ui.removeCallbacks(watchdog);
        ui.removeCallbacks(refocus);
        releaseCamera();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (isQr
                && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
                && surfaceReady()) {
            startCamera();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        ui.removeCallbacksAndMessages(null);
        releaseCamera();
        worker.shutdownNow();
        cleanupTemp();
        if (photoBitmap != null) {
            photoBitmap.recycle();
            photoBitmap = null;
        }
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }
}
