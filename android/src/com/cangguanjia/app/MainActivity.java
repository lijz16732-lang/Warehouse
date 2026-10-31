package com.cangguanjia.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;

/**
 * 仓管家手机 App：独立应用，数据存在手机本地（离线可用）；
 * 「数据共享到电脑端」在 App 的「设置」页配置（经电脑端局域网共享接口同步）。
 * 界面打包在 APK 内（assets/index.html），加载本地页面、秒开。
 *
 * 照片选择：页面经 window.AndroidPhotos.pick() 走原生桥——原生完成
 * 「拍照/相册二选一 → 权限 → 读取 → 压缩 → base64」，直接把图片数据返回给页面。
 * 不再依赖 WebView 的 <input type=file> 回传（部分机型 WebView 的
 * FileChooserParams.parseResult 只认 getData()，相册多选结果在 ClipData 里会被
 * 丢弃，导致拍照/选图后页面拿不到任何文件）。
 */
public class MainActivity extends Activity {

    private static final String PREFS = "cgm";
    private static final String KEY_URL = "server_url";
    private static final String KEY_PRIVACY = "privacy_agreed";   // 首启协议同意标记
    private static final String LOCAL_PAGE = "file:///android_asset/index.html";
    private static final int REQ_SCAN = 1001;
    private static final int REQ_QR = 1002;
    private static final int REQ_FILE = 1003;      // 相册选照片（可多选）
    private static final int REQ_CAMERA = 1004;    // 拍照
    private static final int REQ_CAM_PERM = 1005;  // 相机运行时权限
    private static final int REQ_GAL_PERM = 1006;  // 相册读取权限

    private WebView web;
    private ValueCallback<Uri[]> fileCb;     // 旧 <input type=file> 回调（兜底保留）
    private File pendingCamFile;             // 本次拍照要写入的文件
    private WebChromeClient.FileChooserParams pendingGalleryParams;  // 权限通过后继续打开相册
    private Runnable pendingAfterPerm;       // 权限通过后要继续的动作
    private boolean nativePickMode;          // true=结果走原生桥；false=走 fileCb

    // 原生桥照片结果：JavaBridge 线程阻塞等 UI 流程完成
    private volatile String nativePickResult;
    private volatile CountDownLatch nativePickLatch;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            buildUi(savedInstanceState);
        } catch (Throwable t) {
            showStartupError(t);        // 宁可显示一行报错，也不要静默闪退
        }
    }

    /** 启动失败时把异常直接显示在屏幕上（截图即可定位），避免用户只看到「闪退」。 */
    private void showStartupError(Throwable t) {
        android.widget.TextView tv = new android.widget.TextView(this);
        tv.setText("启动失败：" + t.getClass().getSimpleName() + "\n"
                + t.getMessage() + "\n\n" + android.util.Log.getStackTraceString(t));
        tv.setTextSize(11);
        tv.setPadding(dp(16), dp(40), dp(16), dp(16));
        setContentView(tv);
    }

    private void buildUi(Bundle savedInstanceState) {
        if (Build.VERSION.SDK_INT >= 21) {
            getWindow().setStatusBarColor(Color.parseColor("#1f6feb"));
        }

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        // 界面文件在 APK 本地（file://）；开启共享后要向电脑发跨源请求：
        s.setAllowFileAccess(true);                        // API 30+ 默认 false，必须打开
        s.setAllowUniversalAccessFromFileURLs(true);       // 本地页 → http 接口跨源
        s.setMediaPlaybackRequiresUserGesture(true);
        web.setWebViewClient(new WebViewClient());
        // 兜底：若页面仍走 <input type=file>（如浏览器环境无原生桥），仍弹系统选择器
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView wv, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                if (fileCb != null) {
                    fileCb.onReceiveValue(null);   // 上一次没回来，先作废
                }
                fileCb = cb;
                showPickDialog(params);
                return true;
            }
        });
        // 页面调用本机「拍照识别」识别文字（完全离线，不走电脑）
        web.addJavascriptInterface(new ScanBridge(), "AndroidOcr");
        // 页面调用本机「拍照/相册」加照片（原生读取+压缩，回传 base64）
        web.addJavascriptInterface(new PhotoBridge(), "AndroidPhotos");
        // 页面「设置」里随时重看《隐私政策》和《用户协议》
        web.addJavascriptInterface(new InfoBridge(), "AndroidInfo");

        setContentView(web);

        // 电脑地址在 App 设置页里配置；若以前填过，经 hash 传给页面做预填
        String saved = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_URL, "");
        String url = LOCAL_PAGE;
        if (saved.length() > 0) {
            url += "#base=" + Uri.encode(saved);
        }
        // 首次打开必须先阅读并同意《隐私政策》与《用户协议》才能进入
        if (getSharedPreferences(PREFS, MODE_PRIVATE)
                .getBoolean(KEY_PRIVACY, false)) {
            web.loadUrl(url);
        } else {
            showPrivacyDialog(url);
        }
    }

    @Override
    protected void onDestroy() {
        CountDownLatch l = nativePickLatch;
        if (l != null) {
            l.countDown();     // 防止 JavaBridge 线程永久阻塞
        }
        super.onDestroy();
    }

    private int dp(float v) {
        return (int) android.util.TypedValue.applyDimension(
                android.util.TypedValue.COMPLEX_UNIT_DIP, v,
                getResources().getDisplayMetrics());
    }

    private void toast(String msg) {
        android.widget.Toast.makeText(this, msg,
                android.widget.Toast.LENGTH_SHORT).show();
    }

    // ------------------------------------------------------------ 首启协议
    /** 首次打开：滚动展示隐私政策+用户协议，同意才加载界面，不同意退出。 */
    private void showPrivacyDialog(final String url) {
        android.widget.ScrollView sc = new android.widget.ScrollView(this);
        android.widget.TextView tv = new android.widget.TextView(this);
        tv.setText(PRIVACY_TEXT);
        tv.setTextSize(13.5f);
        tv.setLineSpacing(0, 1.25f);
        tv.setPadding(dp(18), dp(10), dp(18), dp(10));
        sc.addView(tv);
        new AlertDialog.Builder(this)
                .setTitle("欢迎使用仓管家")
                .setView(sc)
                .setCancelable(false)
                .setPositiveButton("同意并继续",
                        new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int w) {
                                getSharedPreferences(PREFS, MODE_PRIVATE)
                                        .edit().putBoolean(KEY_PRIVACY, true).apply();
                                web.loadUrl(url);
                            }
                        })
                .setNegativeButton("不同意并退出",
                        new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int w) {
                                finish();
                            }
                        })
                .show();
    }

    /** 设置页 → 随时重看协议：只读展示，关闭即回，不重复要同意。 */
    private void showAgreementDialog() {
        android.widget.ScrollView sc = new android.widget.ScrollView(this);
        android.widget.TextView tv = new android.widget.TextView(this);
        tv.setText(PRIVACY_TEXT);
        tv.setTextSize(13.5f);
        tv.setLineSpacing(0, 1.25f);
        tv.setPadding(dp(18), dp(10), dp(18), dp(10));
        sc.addView(tv);
        new AlertDialog.Builder(this)
                .setTitle("隐私政策与用户协议")
                .setView(sc)
                .setCancelable(true)
                .setPositiveButton("我知道了", null)
                .show();
    }

    /** 协议正文（应用商店合规要求：首启展示、说明权限用途与数据去向）。 */
    private static final String PRIVACY_TEXT =            "在使用本应用前，请务必阅读并理解《隐私政策》和《用户协议》：\n\n"
            + "一、隐私政策\n\n"
            + "1. 数据存储：您的全部库存数据仅保存在本机（手机本地存储 / 电脑本地数据库），"
            + "本应用不连接任何云服务器，不在云端留存任何数据。\n\n"
            + "2. 局域网同步：仅当您主动开启「数据共享到电脑端」时，应用才会与同一局域网内"
            + "您自己的电脑直接通信；数据不经互联网传输，也不经过任何第三方。\n\n"
            + "3. 相机权限：仅用于 ① 拍照添加商品照片 ② 拍照识别型号文字 / 二维码。"
            + "相机画面只在手机本地处理，不拍摄存储无关内容、不上传互联网。\n\n"
            + "4. 照片：您添加的商品照片经压缩后保存在本机；开启共享后仅同步到您自己的电脑，"
            + "删除记录时照片一并删除。\n\n"
            + "5. 我们不收集、不分析、不共享、不出售您的任何数据。\n\n"
            + "二、用户协议\n\n"
            + "1. 本应用供个人或小型商户进行本地库存管理，按「现状」提供。\n"
            + "2. 您的数据由您自行保管，重要数据请定期在电脑端导出备份；"
            + "因设备丢失、系统故障、误删除等造成的数据损失，需由您自行承担。\n"
            + "3. 请遵守当地法律法规使用本应用，不得用于非法用途。\n"
            + "4. 点击「同意并继续」即表示您已阅读并同意以上全部条款。";

    /** 页面 → 原生：window.AndroidOcr.scan() 识别型号文字；scanQr() 扫电脑二维码。 */
    public class ScanBridge {
        @JavascriptInterface
        public boolean available() {
            return true;
        }

        @JavascriptInterface
        public void scan() {
            open(ScanActivity.class, REQ_SCAN, null);
        }

        @JavascriptInterface
        public void scanQr() {
            open(ScanActivity.class, REQ_QR, ScanActivity.MODE_QR);
        }

        private void open(final Class<?> cls, final int req, final String mode) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    Intent it = new Intent(MainActivity.this, cls);
                    if (mode != null) it.putExtra(ScanActivity.EXTRA_MODE, mode);
                    startActivityForResult(it, req);
                }
            });
        }
    }

    /** 页面 → 原生：window.AndroidInfo.showAgreement() 重看隐私政策/用户协议。 */
    public class InfoBridge {
        @JavascriptInterface
        public void showAgreement() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    showAgreementDialog();
                }
            });
        }
    }

    /** 页面 → 原生：window.AndroidPhotos.pick() 拍照/选图，返回 base64 dataURL 数组 JSON。 */
    public class PhotoBridge {
        @JavascriptInterface
        public boolean available() {
            return true;
        }

        /** 阻塞直到用户完成/取消选择；返回 JSON 数组（元素为 data:image/jpeg;base64,…）。 */
        @JavascriptInterface
        public String pick() {
            nativePickResult = null;
            final CountDownLatch latch = new CountDownLatch(1);
            nativePickLatch = latch;
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    new AlertDialog.Builder(MainActivity.this)
                            .setTitle("添加照片")
                            .setItems(new String[]{"拍照", "从相册选择"},
                                    new DialogInterface.OnClickListener() {
                                        @Override
                                        public void onClick(DialogInterface d, int which) {
                                            if (which == 0) {
                                                askCameraPerm(new Runnable() {
                                                    @Override
                                                    public void run() {
                                                        nativePickMode = true;
                                                        launchCamera();
                                                    }
                                                });
                                            } else {
                                                askGalleryPerm(new Runnable() {
                                                    @Override
                                                    public void run() {
                                                        nativePickMode = true;
                                                        openGalleryNative();
                                                    }
                                                });
                                            }
                                        }
                                    })
                            .setOnCancelListener(new DialogInterface.OnCancelListener() {
                                @Override
                                public void onCancel(DialogInterface d) {
                                    deliverNative(null);
                                }
                            })
                            .show();
                }
            });
            try {
                latch.await();
            } catch (InterruptedException e) {
                return "[]";
            }
            String r = nativePickResult;
            return r == null ? "[]" : r;
        }
    }

    // ------------------------------------------------------------ 权限（用途说明 → 申请）
    private void askCameraPerm(Runnable cont) {
        if (Build.VERSION.SDK_INT >= 23 && checkSelfPermission(
                android.Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            pendingAfterPerm = cont;
            // 申请前先给用途说明（应用市场合规要求：权限用途告知）
            new AlertDialog.Builder(this)
                    .setTitle("需要相机权限")
                    .setMessage("「拍照」需要使用相机拍摄商品照片。"
                            + "照片仅保存在本机并同步到您自己的电脑，不会上传互联网。")
                    .setPositiveButton("去允许",
                            new DialogInterface.OnClickListener() {
                                @Override
                                public void onClick(DialogInterface d, int w) {
                                    requestPermissions(new String[]{
                                            android.Manifest.permission.CAMERA},
                                            REQ_CAM_PERM);
                                }
                            })
                    .setNegativeButton("暂不",
                            new DialogInterface.OnClickListener() {
                                @Override
                                public void onClick(DialogInterface d, int w) {
                                    onPermDenied(false);
                                }
                            })
                    .setOnCancelListener(new DialogInterface.OnCancelListener() {
                        @Override
                        public void onCancel(DialogInterface d) {
                            onPermDenied(false);
                        }
                    })
                    .show();
            return;
        }
        cont.run();
    }

    private void askGalleryPerm(Runnable cont) {
        String perm = galleryPerm();
        if (Build.VERSION.SDK_INT >= 23 && perm != null && checkSelfPermission(perm)
                != PackageManager.PERMISSION_GRANTED) {
            pendingAfterPerm = cont;
            // 申请前先给用途说明（合规要求：权限使用告知）
            new AlertDialog.Builder(this)
                    .setTitle("需要照片权限")
                    .setMessage("「从相册选择」需要读取您相册里的照片，"
                            + "用于添加商品照片。照片仅保存在本机并同步到您自己的电脑，"
                            + "不会上传互联网。")
                    .setPositiveButton("去允许",
                            new DialogInterface.OnClickListener() {
                                @Override
                                public void onClick(DialogInterface d, int w) {
                                    requestPermissions(new String[]{galleryPerm()},
                                            REQ_GAL_PERM);
                                }
                            })
                    .setNegativeButton("暂不",
                            new DialogInterface.OnClickListener() {
                                @Override
                                public void onClick(DialogInterface d, int w) {
                                    onPermDenied(true);
                                }
                            })
                    .setOnCancelListener(new DialogInterface.OnCancelListener() {
                        @Override
                        public void onCancel(DialogInterface d) {
                            onPermDenied(true);
                        }
                    })
                    .show();
            return;
        }
        cont.run();
    }

    /** 权限被拒/弹窗被取消：按当前模式把「空结果」交回对应通道。 */
    private void onPermDenied(boolean gallery) {
        String tip = gallery
                ? "未授予照片权限，无法从相册选择；可在系统设置 → 应用 → 仓管家里允许"
                : "未授予相机权限，无法拍照；可在系统设置 → 应用 → 仓管家里允许";
        android.widget.Toast.makeText(this, tip, android.widget.Toast.LENGTH_LONG).show();
        if (nativePickMode) {
            deliverNative(null);
        } else {
            finishFileCb(null);
        }
    }

    /** 相册读取权限名：API 33+ 用 READ_MEDIA_IMAGES，旧系统用 READ_EXTERNAL_STORAGE。 */
    private String galleryPerm() {
        if (Build.VERSION.SDK_INT >= 33) {
            return "android.permission.READ_MEDIA_IMAGES";
        }
        if (Build.VERSION.SDK_INT >= 23) {
            return android.Manifest.permission.READ_EXTERNAL_STORAGE;
        }
        return null;    // 6.0 以下安装时授予，无需运行时申请
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] perms,
                                           int[] results) {
        super.onRequestPermissionsResult(requestCode, perms, results);
        boolean granted = results.length > 0
                && results[0] == PackageManager.PERMISSION_GRANTED;
        if (requestCode == REQ_CAM_PERM || requestCode == REQ_GAL_PERM) {
            if (granted && pendingAfterPerm != null) {
                Runnable r = pendingAfterPerm;
                pendingAfterPerm = null;
                r.run();
            } else if (!granted) {
                pendingAfterPerm = null;
                onPermDenied(requestCode == REQ_GAL_PERM);
            }
        }
    }

    // ------------------------------------------------------------ 拍照 / 相册（两种模式共用）
    private void launchCamera() {
        File dir = new File(getCacheDir(), "photos");
        if (!dir.isDirectory()) {
            dir.mkdirs();
        }
        pendingCamFile = new File(dir, "cam_" + System.currentTimeMillis() + ".jpg");
        Uri out = PhotoProvider.uriFor(pendingCamFile.getName());
        Intent it = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
        it.putExtra(android.provider.MediaStore.EXTRA_OUTPUT, out);
        // 关键：EXTRA_OUTPUT 的 content:// 必须经 ClipData 授权，只加 Intent flags
        // 部分相机（如 MIUI）拿不到写权限 → 不写文件、只回缩略图 → 照片丢失
        it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        it.setClipData(ClipData.newRawUri("photos", out));
        try {
            startActivityForResult(it, REQ_CAMERA);
        } catch (Exception e) {
            pendingCamFile = null;
            if (nativePickMode) {
                deliverNative(null);
            } else {
                finishFileCb(null);
            }
        }
    }

    /** 相机没写 EXTRA_OUTPUT 时，把返回的缩略图 Bitmap 落盘兜底（质量 90）。 */
    private void saveCameraThumbnail(Intent data) {
        try {
            Bitmap bm = (data == null || data.getExtras() == null)
                    ? null : (Bitmap) data.getExtras().get("data");
            if (bm == null) {
                return;
            }
            java.io.FileOutputStream fo = new java.io.FileOutputStream(pendingCamFile);
            bm.compress(Bitmap.CompressFormat.JPEG, 90, fo);
            fo.close();
        } catch (Exception e) {
            // 落盘失败就按拍照失败处理
        }
    }

    /** 原生桥相册：自建选择意图（多选），结果在 onActivityResult 里自己解析。 */
    private void openGalleryNative() {
        Intent it = new Intent(Intent.ACTION_GET_CONTENT);
        it.addCategory(Intent.CATEGORY_OPENABLE);
        it.setType("image/*");
        it.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        try {
            startActivityForResult(Intent.createChooser(it, "选择照片"), REQ_FILE);
        } catch (Exception e) {
            deliverNative(null);
        }
    }

    // ------------------------------------------------------------ onActivityResult
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_FILE) {                  // 相册：支持单/多选
            Uri[] uris = parsePickerResult(resultCode, data);
            if (nativePickMode) {
                deliverNative(uris);
                return;
            }
            if (uris == null && resultCode == RESULT_OK) {
                toast("没有获取到所选照片，请重试");
            } else if (uris != null) {
                toast("已获取 " + uris.length + " 张照片，处理中…");
            }
            finishFileCb(uris);
            return;
        }
        if (requestCode == REQ_CAMERA) {                // 拍照：成功把文件 Uri 交给页面
            boolean ok = resultCode == RESULT_OK && pendingCamFile != null;
            if (ok && (!pendingCamFile.isFile()
                    || pendingCamFile.length() == 0)) {
                saveCameraThumbnail(data);              // 部分相机不写 EXTRA_OUTPUT，
            }                                           // 只回缩略图，这里兜底落盘
            ok = ok && pendingCamFile.isFile() && pendingCamFile.length() > 0;
            if (nativePickMode) {
                if (ok) {
                    toast("照片已拍摄，处理中…");
                    deliverNative(new Uri[]{
                            PhotoProvider.uriFor(pendingCamFile.getName())});
                } else {
                    if (resultCode == RESULT_OK) {
                        toast("拍照没有保存成功，请重试");
                    }
                    deliverNative(null);
                }
                if (pendingCamFile != null && !ok) {
                    pendingCamFile.delete();
                }
                pendingCamFile = null;
                return;
            }
            if (ok) {
                toast("照片已拍摄，处理中…");
                finishFileCb(new Uri[]{PhotoProvider.uriFor(pendingCamFile.getName())});
            } else {
                if (resultCode == RESULT_OK) {
                    toast("拍照没有保存成功，请重试");
                }
                if (pendingCamFile != null) {
                    pendingCamFile.delete();            // 拍照取消/失败：清掉空文件
                }
                finishFileCb(null);
            }
            pendingCamFile = null;
            return;
        }
        if (data == null || resultCode != RESULT_OK) return;
        String text = data.getStringExtra(ScanActivity.EXTRA_TEXT);
        if (text == null || text.length() == 0) return;
        if (requestCode == REQ_SCAN) {
            callPage("window.__ocrFill(", text);
        } else if (requestCode == REQ_QR) {
            callPage("window.__qrResult(", text);
        }
    }

    /**
     * 解析相册选择结果。关键：不能只用 FileChooserParams.parseResult——
     * 部分机型（小米等）相册把结果放在 ClipData，而某些 WebView 版本的
     * parseResult 只读 getData()，多选/单选都会被解析成空。
     */
    private Uri[] parsePickerResult(int resultCode, Intent data) {
        if (resultCode != RESULT_OK || data == null) {
            return null;
        }
        ArrayList<Uri> list = new ArrayList<Uri>();
        ClipData clip = data.getClipData();
        if (clip != null) {
            for (int i = 0; i < clip.getItemCount(); i++) {
                Uri u = clip.getItemAt(i).getUri();
                if (u != null) {
                    list.add(u);
                }
            }
        }
        if (list.isEmpty() && data.getData() != null) {
            list.add(data.getData());
        }
        return list.isEmpty() ? null : list.toArray(new Uri[list.size()]);
    }

    // ------------------------------------------------------------ 原生读取与压缩
    /** 把选中的图片（原生模式）读取、降采样到 ≤1024px、JPEG 压缩后转 base64 交回页面。 */
    private void deliverNative(final Uri[] uris) {
        final CountDownLatch latch = nativePickLatch;
        new Thread(new Runnable() {
            @Override
            public void run() {
                StringBuilder sb = new StringBuilder("[");
                boolean first = true;
                if (uris != null) {
                    for (Uri u : uris) {
                        String b64 = readImageBase64(u);
                        if (b64 == null) {
                            continue;
                        }
                        if (!first) {
                            sb.append(',');
                        }
                        first = false;
                        sb.append('"').append(b64).append('"');
                    }
                }
                sb.append(']');
                nativePickResult = sb.toString();
                if (latch != null) {
                    latch.countDown();
                }
            }
        }).start();
    }

    /** 单张：content:// → 降采样 Bitmap → JPEG(60) → dataURL 字符串；失败返回 null。 */
    private String readImageBase64(Uri u) {
        InputStream is = null;
        try {
            BitmapFactory.Options o = new BitmapFactory.Options();
            o.inJustDecodeBounds = true;
            is = getContentResolver().openInputStream(u);
            BitmapFactory.decodeStream(is, null, o);
            if (o.outWidth <= 0 || o.outHeight <= 0) {
                return null;
            }
            int sample = 1;
            while (Math.max(o.outWidth, o.outHeight) / (sample * 2) >= 1024) {
                sample *= 2;
            }
            BitmapFactory.Options o2 = new BitmapFactory.Options();
            o2.inSampleSize = sample;
            is.close();
            is = getContentResolver().openInputStream(u);
            Bitmap bm = BitmapFactory.decodeStream(is, null, o2);
            if (bm == null) {
                return null;
            }
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            bm.compress(Bitmap.CompressFormat.JPEG, 60, bo);
            bm.recycle();
            return "data:image/jpeg;base64,"
                    + Base64.encodeToString(bo.toByteArray(), Base64.NO_WRAP);
        } catch (Exception e) {
            return null;
        } finally {
            if (is != null) {
                try {
                    is.close();
                } catch (Exception ignore) {
                    // 忽略关闭异常
                }
            }
        }
    }

    // ------------------------------------------------------------ 旧 input=file 通道（兜底）
    /** 页面触发文件选择时弹「拍照 / 相册」二选一；取消则告知页面（回调 null）。 */
    private void showPickDialog(final WebChromeClient.FileChooserParams params) {
        new AlertDialog.Builder(this)
                .setTitle("添加照片")
                .setItems(new String[]{"拍照", "从相册选择"},
                        new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int which) {
                                if (which == 0) {
                                    askCameraPerm(new Runnable() {
                                        @Override
                                        public void run() {
                                            nativePickMode = false;
                                            launchCamera();
                                        }
                                    });
                                } else {
                                    askGalleryPerm(new Runnable() {
                                        @Override
                                        public void run() {
                                            nativePickMode = false;
                                            openGalleryOld(params);
                                        }
                                    });
                                }
                            }
                        })
                .setOnCancelListener(new DialogInterface.OnCancelListener() {
                    @Override
                    public void onCancel(DialogInterface d) {
                        finishFileCb(null);
                    }
                })
                .show();
    }

    /** 旧通道相册：用页面 FileChooserParams 的意图（accept/multiple 已带好）。 */
    private void openGalleryOld(WebChromeClient.FileChooserParams params) {
        try {
            startActivityForResult(Intent.createChooser(
                    params.createIntent(), "选择照片"), REQ_FILE);
        } catch (Exception e) {
            finishFileCb(null);
        }
    }

    /** 统一把文件选择结果交回页面（只交一次，之后清空）。 */
    private void finishFileCb(Uri[] uris) {
        ValueCallback<Uri[]> cb = fileCb;
        fileCb = null;
        if (cb != null) {
            cb.onReceiveValue(uris);
        }
    }

    /** 把扫描结果安全地回填给页面（JSON 转义，防引号/换行注入）。 */
    private void callPage(String prefix, String text) {
        if (web == null) return;
        web.evaluateJavascript(prefix + JSONObject.quote(text) + ")", null);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            moveTaskToBack(true);      // 不直接退出，保留数据与登录状态
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
