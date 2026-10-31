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

import com.google.android.gms.tasks.OnCompleteListener;
import com.google.android.gms.tasks.OnFailureListener;
import com.google.android.gms.tasks.OnSuccessListener;
import com.google.android.gms.tasks.Task;
import com.google.mlkit.common.MlKit;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions;
import com.google.zxing.BarcodeFormat;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import java.io.File;
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
 * 拍照识别型号（v1.28.0 重构）：拍照 → 框选 → ML Kit 本地离线识别。
 *
 * 为什么不用实时预览帧识别（v1.27.x 及以前的做法）：
 *   实时预览流分辨率低（≤1600px）、连续对焦近距常不收敛，识别率差还费电；
 *   系统相机拍一张是全分辨率 + 自动对焦/HDR，配合手动框选排除背景干扰，
 *   只识别一次，又准又省电。照片走 cacheDir 临时文件，用完即删，不进相册。
 *
 * 识别引擎：Google ML Kit 文字识别 v2（中文捆绑版），模型随 App 打包，
 * 完全离线、不依赖 Google 服务框架、不联网。
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

    /** 识别引擎全局复用：第二次进入拍照识别不用重新创建。 */
    private static TextRecognizer sRecognizer;

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

    // ------------------------------------------------------------- 入口流

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
        status.setText("拖动四角框住要识别的文字，点「识别」");
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
        try {
            InputImage img = InputImage.fromBitmap(crop, 0);
            getRecognizer().process(img)
                    .addOnSuccessListener(new OnSuccessListener<Text>() {
                        @Override
                        public void onSuccess(Text text) {
                            setActionsEnabled(true);
                            showLines(extractLines(text));
                        }
                    })
                    .addOnFailureListener(new OnFailureListener() {
                        @Override
                        public void onFailure(Exception e) {
                            setActionsEnabled(true);
                            status.setText("识别失败：" + brief(e) + "，点「识别」重试");
                        }
                    })
                    .addOnCompleteListener(new OnCompleteListener<Text>() {
                        @Override
                        public void onComplete(Task<Text> task) {
                            crop.recycle();     // 识别完立即释放，内存不留峰值
                        }
                    });
        } catch (Throwable t) {
            setActionsEnabled(true);
            crop.recycle();
            status.setText("识别引擎没能启动（" + brief(t)
                    + "），点「识别」重试");
        }
    }

    /** 异常压成一小段可读文字，方便用户反馈时截图。 */
    private String brief(Throwable t) {
        String m = t.getMessage();
        if (m == null || m.trim().isEmpty()) return t.getClass().getSimpleName();
        m = m.replace('\n', ' ').trim();
        return m.length() > 60 ? m.substring(0, 60) + "…" : m;
    }

    private TextRecognizer getRecognizer() {
        if (sRecognizer == null) {
            status.setText("正在准备识别引擎…");
            ensureMlKit();
            sRecognizer = TextRecognition.getClient(
                    new ChineseTextRecognizerOptions.Builder().build());
        }
        return sRecognizer;
    }

    /** 手动初始化 ML Kit（与 AAR 里 MlKitInitProvider 内部调用等价）。
     *  不声明那个 provider 是为了避免它 attachInfo 的 authority 断言在启动时崩 App。 */
    private void ensureMlKit() {
        try {
            MlKit.initialize(getApplicationContext());
        } catch (Throwable ignored) {
            // 已初始化 / 组件注册异常都落到这里，交给 getClient 暴露具体原因
        }
    }

    /** 从识别结果里挑出像型号/说明的行（去空、去符号行、去重）。 */
    private List<String> extractLines(Text text) {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        if (text != null) {
            for (Text.TextBlock b : text.getTextBlocks()) {
                for (Text.Line l : b.getLines()) {
                    String s = l.getText() == null ? "" : l.getText().trim();
                    if (s.length() < 2) continue;
                    s = s.replaceAll("[ \\t]{2,}", " ");
                    if (s.replaceAll("[^0-9A-Za-z\\u4e00-\\u9fa5]", "").length() < 2) {
                        continue;
                    }
                    out.add(s);
                }
            }
        }
        List<String> list = new ArrayList<>(out);
        return list.size() > 6 ? list.subList(0, 6) : list;
    }

    private void showLines(List<String> lines) {
        if (lines.isEmpty()) {
            status.setText("没认出文字，试着框小一点只框住文字，或靠近点重拍");
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

    /** 框选层：照片按比例铺满显示，拖动四角/整体调整框，框住要识别的文字。 */
    private class CropView extends View {
        private static final int M_NONE = 0;
        private static final int M_MOVE = 1;
        private static final int M_TL = 2;
        private static final int M_TR = 3;
        private static final int M_BL = 4;
        private static final int M_BR = 5;

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
            float dw = iw * k;
            float dh = ih * k;
            draw.set((vw - dw) / 2f, (vh - dh) / 2f, (vw + dw) / 2f, (vh + dh) / 2f);
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
                else mode = M_NONE;
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_MOVE && mode != M_NONE) {
                float dnx = (x - lastX) / draw.width();
                float dny = (y - lastY) / draw.height();
                lastX = x;
                lastY = y;
                if (mode == M_MOVE) {
                    float w = r - l;
                    float hh = b - t;
                    l = clamp01(Math.min(Math.max(0f, l + dnx), 1f - w));
                    r = l + w;
                    t = clamp01(Math.min(Math.max(0f, t + dny), 1f - hh));
                    b = t + hh;
                } else {
                    float minSize = 0.05f;
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
                return true;
            }
            return true;
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
