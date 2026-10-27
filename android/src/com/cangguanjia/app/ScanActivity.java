package com.cangguanjia.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ImageFormat;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.YuvImage;
import android.hardware.Camera;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
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

import com.googlecode.tesseract.android.TessBaseAPI;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 扫一扫识别型号：相机实时预览 + 本机离线 OCR（Tesseract，模型随 App 打包，不联网）。
 *
 * 交互：把型号对准中间的框 → 框下方实时出现识别候选 → 点一下就填回仓管家。
 * 识别完全在手机上跑，不需要电脑、不需要网络。
 *
 * 相机时序要点（v1.20.1 修黑屏）：
 *   必须等 SurfaceView 的 surface 真正创建后再 setPreviewDisplay + startPreview，
 *   否则会抛 "Surface is not valid" 且相机对象残留在半开状态，之后再也不出画面。
 */
public class ScanActivity extends Activity implements SurfaceHolder.Callback {

    public static final String EXTRA_TEXT = "text";

    private static final int REQ_PERM = 21;
    private static final long MIN_GAP_MS = 900L;      // 两次识别的最小间隔（省电、防卡）
    private static final String LANG = "chi_sim+eng";

    /** 识别引擎较重，做成静态复用：第二次进入扫一扫就不用再加载。 */
    private static TessBaseAPI sApi;
    private static final Object API_LOCK = new Object();
    private static final AtomicBoolean INITING = new AtomicBoolean(false);

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();

    private SurfaceView preview;
    private Camera camera;
    private Camera.Size previewSize;
    private int rotateDeg = 90;
    private int camIdx = 0;
    private volatile boolean previewRunning = false;
    private long lastFrameAt = 0L;
    private volatile int restartCount = 0;      // 重启次数：真收到画面帧才清零，防死循环

    private TextView status;
    private TextView hintBig;
    private LinearLayout choices;
    private FrameLayout root;

    private byte[] frameBuffer;
    private final AtomicBoolean busy = new AtomicBoolean(false);
    private long lastAt = 0L;
    private String lastShown = "";
    private String lastText = "";
    private int stable = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        buildUi();

        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_PERM);
        }
        // 相机不在这里开：等 surfaceCreated / 权限回调，避免 surface 未就绪导致黑屏
        prepareEngine();
    }

    // ------------------------------------------------------------- 界面
    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                getResources().getDisplayMetrics());
    }

    private void buildUi() {
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        preview = new SurfaceView(this);
        root.addView(preview, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        preview.getHolder().addCallback(this);

        // 取景框（中间一条：型号铭牌通常是窄长一条）
        root.addView(new FrameView(this), new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(dp(14), dp(10), dp(8), dp(10));
        top.setBackgroundColor(Color.argb(150, 0, 0, 0));

        TextView title = new TextView(this);
        title.setText("扫一扫识别型号");
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

        // 底部：状态 + 候选
        LinearLayout bottom = new LinearLayout(this);
        bottom.setOrientation(LinearLayout.VERTICAL);
        bottom.setPadding(dp(14), dp(12), dp(14), dp(20));
        bottom.setBackgroundColor(Color.argb(170, 0, 0, 0));

        status = new TextView(this);
        status.setText("正在打开相机…");
        status.setTextColor(Color.parseColor("#d7e2f5"));
        status.setTextSize(13);
        status.setGravity(Gravity.CENTER);
        status.setOnClickListener(new View.OnClickListener() {   // 点一下可重试
            @Override
            public void onClick(View v) {
                restartCount = 0;
                status.setText("正在重新打开相机…");
                releaseCamera();
                startCamera();
            }
        });

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

        bottom.addView(status);
        bottom.addView(hintBig);
        bottom.addView(choices);
        root.addView(bottom, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM));

        setContentView(root);
    }

    /** 半透明遮罩 + 中间取景框。 */
    private class FrameView extends View {
        private final Paint dim = new Paint();
        private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Rect box = new Rect();

        FrameView(Activity c) {
            super(c);
            dim.setColor(Color.argb(110, 0, 0, 0));
            line.setColor(Color.parseColor("#46b1ff"));
            line.setStyle(Paint.Style.STROKE);
            line.setStrokeWidth(dp(2));
        }

        private void calcBox() {
            int w = getWidth();
            int h = getHeight();
            int bw = (int) (w * 0.86f);
            int bh = Math.max(dp(64), (int) (h * 0.19f));
            int left = (w - bw) / 2;
            int top = (int) (h * 0.36f);
            box.set(left, top, left + bw, top + bh);
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

    // ------------------------------------------------------------- 相机
    @Override
    public void onRequestPermissionsResult(int req, String[] perms, int[] grants) {
        super.onRequestPermissionsResult(req, perms, grants);
        if (req != REQ_PERM) return;
        if (grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) {
            startCamera();
        } else {
            toast("没有相机权限，无法扫一扫（可在系统设置里允许）");
            setResult(RESULT_CANCELED);
            finish();
        }
    }

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
                p.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
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
                                grab(data, cam);
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
            String size = previewSize == null ? "" : (" " + previewSize.width + "×" + previewSize.height);
            status.setText("把型号对准框内…" + size);
            startWatchdog();
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

    /** 后摄优先（扫铭牌用后摄最清楚）。 */
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

    // ------------------------------------------------------------- 抓帧 + 识别
    private void grab(byte[] data, Camera cam) {
        long now = System.currentTimeMillis();
        if (now - lastAt < MIN_GAP_MS) return;
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
                    process(copy, w, h);
                } catch (Throwable ignored) {
                } finally {
                    busy.set(false);
                }
            }
        });
    }

    private void process(byte[] nv21, int w, int h) {
        TessBaseAPI api = sApi;
        if (api == null) return;

        YuvImage yuv = new YuvImage(nv21, ImageFormat.NV21, w, h, null);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        yuv.compressToJpeg(new Rect(0, 0, w, h), 82, bos);
        byte[] jpg = bos.toByteArray();
        Bitmap bmp = BitmapFactory.decodeByteArray(jpg, 0, jpg.length);
        if (bmp == null) return;

        Bitmap cropped = cropBand(bmp);
        try {
            String text;
            int conf;
            synchronized (API_LOCK) {
                api.setImage(cropped);
                text = api.getUTF8Text();
                conf = api.meanConfidence();
            }
            final List<String> lines = linesOf(text);
            if (!lines.isEmpty()) {
                final String first = lines.get(0);
                final int c = conf;
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        onResult(lines, first, c);
                    }
                });
            }
        } finally {
            cropped.recycle();
            bmp.recycle();
        }
    }

    /** 同一结果连续两帧、且置信度够高 → 直接填回（像扫码一样），否则只列候选。 */
    private void onResult(List<String> lines, String first, int conf) {
        if (first.equals(lastText)) {
            stable += 1;
        } else {
            lastText = first;
            stable = 0;
            lastShown = "";
        }
        show(lines);
        if (stable >= 1 && conf >= 60) {         // 第二帧仍相同 → 自动填入
            stable = 0;
            finishWith(first);
        }
    }

    /** 先按相机方向摆正，再按取景框比例裁剪出中间那一条（太小则放大，利于识别）。 */
    private Bitmap cropBand(Bitmap src) {
        Bitmap up = src;
        if (rotateDeg % 360 != 0) {
            Matrix m = new Matrix();
            m.postRotate(rotateDeg);
            up = Bitmap.createBitmap(src, 0, 0, src.getWidth(), src.getHeight(), m, true);
        }
        int w = up.getWidth();
        int h = up.getHeight();
        int bw = (int) (w * 0.86f);
        int bh = (int) (h * 0.19f);
        int left = (w - bw) / 2;
        int top = (int) (h * 0.36f);
        if (left < 0) left = 0;
        if (top < 0) top = 0;
        if (left + bw > w) bw = w - left;
        if (top + bh > h) bh = h - top;
        bw = Math.max(1, bw);
        bh = Math.max(1, bh);

        Bitmap band = Bitmap.createBitmap(up, left, top, bw, bh);
        if (up != src) up.recycle();

        if (bh < 110) {                              // 字号太小识别率差，等比放大
            float k = 110f / bh;
            Bitmap big = Bitmap.createScaledBitmap(band,
                    Math.max(1, (int) (bw * k)), Math.max(1, (int) (bh * k)), true);
            if (big != band) band.recycle();
            return big;
        }
        return band;
    }

    private List<String> linesOf(String text) {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        if (text != null) {
            for (String raw : text.split("\n")) {
                String s = raw == null ? "" : raw.trim();
                if (s.length() < 2) continue;
                s = s.replaceAll("[ \\t]{2,}", " ");
                if (s.replaceAll("[^0-9A-Za-z\\u4e00-\\u9fa5]", "").length() < 2) continue;
                out.add(s);
            }
        }
        List<String> list = new ArrayList<>(out);
        return list.size() > 4 ? list.subList(0, 4) : list;
    }

    private void show(List<String> lines) {
        if (lines.isEmpty()) return;
        String top = lines.get(0);
        if (top.equals(lastShown)) return;
        lastShown = top;

        hintBig.setText("填入：" + top);
        hintBig.setTag(top);
        hintBig.setBackgroundColor(Color.parseColor("#1f6feb"));
        status.setText("识别到 " + lines.size() + " 行，点下面的文字填入");

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

    private void finishWith(String text) {
        Intent it = new Intent();
        it.putExtra(EXTRA_TEXT, text);
        setResult(RESULT_OK, it);
        finish();
    }

    // ------------------------------------------------------------- 识别引擎
    private void prepareEngine() {
        if (sApi != null) {
            if (lastShown.length() == 0) status.setText("把型号对准框内…");
            return;
        }
        if (!INITING.compareAndSet(false, true)) return;
        status.setText("正在准备识别引擎（首次约 2 秒）…");
        worker.execute(new Runnable() {
            @Override
            public void run() {
                TessBaseAPI api = null;
                try {
                    File dir = new File(getFilesDir(), "tessdata");
                    if (!dir.exists()) dir.mkdirs();
                    for (String lang : new String[]{"chi_sim", "eng"}) {
                        File f = new File(dir, lang + ".traineddata");
                        if (f.exists() && f.length() > 1024) continue;
                        copyAsset("tessdata/" + lang + ".traineddata", f);
                    }
                    TessBaseAPI a = new TessBaseAPI();
                    boolean ok = a.init(getFilesDir().getAbsolutePath(), LANG);
                    if (!ok) {
                        a.recycle();
                        throw new IllegalStateException("init failed");
                    }
                    a.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SINGLE_BLOCK);
                    api = a;
                } catch (Throwable e) {
                    api = null;
                } finally {
                    INITING.set(false);
                }
                sApi = api;
                final boolean ok = api != null;
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (!ok) {
                            status.setText("识别引擎初始化失败，请重装 App 试试");
                        } else if (lastShown.length() == 0) {
                            status.setText(previewRunning ? "把型号对准框内…" : "正在打开相机…");
                        }
                    }
                });
            }
        });
    }

    private void copyAsset(String name, File dst) throws Exception {
        InputStream in = getAssets().open(name);
        FileOutputStream out = new FileOutputStream(dst);
        try {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            out.flush();
        } finally {
            try {
                in.close();
            } catch (Exception ignored) {
            }
            try {
                out.close();
            } catch (Exception ignored) {
            }
        }
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onPause() {
        super.onPause();
        ui.removeCallbacks(watchdog);
        releaseCamera();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
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
    }
}
