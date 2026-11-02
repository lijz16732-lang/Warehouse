package com.cangguanjia.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.KeyguardManager;
import android.content.ClipData;
import android.content.Context;
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
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
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
    private static final String KEY_LOCK = "startup_lock";    // 启动验证（手机锁屏）
    private static final String LOCAL_PAGE = "file:///android_asset/index.html";
    private static final int REQ_SCAN = 1001;
    private static final int REQ_QR = 1002;
    private static final int REQ_FILE = 1003;      // 相册选照片（可多选）
    private static final int REQ_CAMERA = 1004;    // 拍照
    private static final int REQ_CAM_PERM = 1005;  // 相机运行时权限
    private static final int REQ_UNLOCK = 1006;    // 启动验证（系统锁屏）

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
            showLastCrash();            // 上次若闪退过，把堆栈摆出来（可长按复制）
            // 自检转发：adb am start -n 包名/.MainActivity --ez diag true
            // （ScanActivity 不导出，只能由本 App 自己拉起）
            if (getIntent().getBooleanExtra("diag", false)) {
                startActivity(new Intent(this, ScanActivity.class)
                        .putExtra("diag", true));
            }
        } catch (Throwable t) {
            showStartupError(t);        // 宁可显示一行报错，也不要静默闪退
        }
    }

    /** 上次进程崩溃的堆栈（CgmApp 在 attachBaseContext 里记录），显示后即删除。 */
    private void showLastCrash() {
        final String txt = CgmApp.takeCrash(this);
        if (txt == null) return;
        AlertDialog d = new AlertDialog.Builder(this)
                .setTitle("上次启动异常（长按可复制，发给开发者即可定位）")
                .setMessage(txt)
                .setPositiveButton("知道了", null)
                .create();
        d.setOnShowListener(x -> {
            android.widget.TextView tv = d.findViewById(android.R.id.message);
            if (tv != null) {
                tv.setTextIsSelectable(true);
                tv.setTextSize(10);
            }
        });
        d.show();
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

    /**
     * 启动顺序（合规相关，勿随意调整）：
     *   ① 启动验证（可选，走系统锁屏，不额外存密码）
     *   ② 隐私政策同意（版本号比对；未同意不加载界面、不创建 WebView）
     *   ③ 正常界面
     * 把同意放在创建 WebView 之前，是为了保证「未取得同意前不开始任何处理」。
     */
    private void buildUi(Bundle savedInstanceState) {
        if (Build.VERSION.SDK_INT >= 21) {
            getWindow().setStatusBarColor(Color.parseColor("#2563EB"));
        }
        if (lockEnabled()) {
            if (awaitUnlock()) {
                return;                 // 等系统锁屏回来再继续
            }
        }
        proceed();
    }

    /** 过了启动验证之后：先看同意状态，再建界面。 */
    private void proceed() {
        if (Legal.agreed(this)) {
            setupWeb();
            return;
        }
        showSplash();                   // 同意页背后放个品牌页，避免白屏
        Legal.askConsent(this,
                new Runnable() {
                    @Override
                    public void run() {
                        setupWeb();
                    }
                },
                new Runnable() {
                    @Override
                    public void run() {
                        finish();       // 不同意 → 退出，不做任何处理
                    }
                });
    }

    private void showSplash() {
        android.widget.TextView tv = new android.widget.TextView(this);
        tv.setText("仓管家\n\n本地库存管理 · 数据只存在你的手机上");
        tv.setGravity(android.view.Gravity.CENTER);
        tv.setTextSize(15);
        tv.setTextColor(Color.parseColor("#2563EB"));
        setContentView(tv);
    }

    // ------------------------------------------------------------ 启动验证（访问控制）
    /** 是否开启启动验证（由设置页写入）。 */
    private boolean lockEnabled() {
        return getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean(KEY_LOCK, false);
    }

    /**
     * 调起系统锁屏验证（图案/密码/指纹）。返回 true 表示已拉起、需等回调。
     * 用系统凭据而不是自建 PIN：用户不会忘记，也不会因为忘记密码而丢数据。
     */
    private boolean awaitUnlock() {
        KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
        if (km == null || !km.isDeviceSecure()) {
            getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                    .putBoolean(KEY_LOCK, false).apply();
            toast("手机未设置锁屏密码，启动验证已自动关闭");
            return false;
        }
        Intent it = km.createConfirmDeviceCredentialIntent("仓管家", "验证身份后查看库存数据");
        if (it == null) {
            return false;
        }
        try {
            startActivityForResult(it, REQ_UNLOCK);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** 建界面：加载 APK 内置页面，注册三个原生桥。 */
    @SuppressLint("SetJavaScriptEnabled")
    private void setupWeb() {
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        // 界面文件在 APK 本地（file://）；开启共享后要向电脑发跨源请求：
        s.setAllowFileAccess(true);                        // API 30+ 默认 false，必须打开
        s.setAllowUniversalAccessFromFileURLs(true);       // 本地页 → http 接口跨源
        s.setAllowFileAccessFromFileURLs(false);           // 本地页之间不互读
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setSaveFormData(false);
        s.setGeolocationEnabled(false);
        if (Build.VERSION.SDK_INT >= 21) {
            // 本地页面不允许混入公网 http 资源，配合 NetGuard 一起收紧出网面
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        }
        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView v,
                                                              WebResourceRequest req) {
                // 出网白名单：只允许私有网段/局域网主机（详见 NetGuard）
                String u = req == null || req.getUrl() == null
                        ? null : req.getUrl().toString();
                if (!NetGuard.allow(u)) {
                    android.util.Log.w("CGM", "已拦截非局域网请求：" + u);
                    return new WebResourceResponse("text/plain", "utf-8", null);
                }
                return null;
            }
        });
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
        // 页面「设置」里的隐私与数据功能（协议、清单、导出、撤回同意、启动验证）
        web.addJavascriptInterface(new InfoBridge(), "AndroidInfo");

        setContentView(web);

        // 电脑地址在 App 设置页里配置；若以前填过，经 hash 传给页面做预填
        String saved = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_URL, "");
        String url = LOCAL_PAGE;
        if (saved.length() > 0) {
            url += "#base=" + Uri.encode(saved);
        }
        web.loadUrl(url);
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

    /**
     * 页面 → 原生：设置页「隐私与数据」的全部合规功能。
     * 每项都对应一条法定义务：告知（协议/清单）、查阅复制（导出）、删除（清空）、
     * 撤回同意（PIPL 15）、访问控制（启动验证）。
     */
    public class InfoBridge {
        @JavascriptInterface
        public String legalVersion() {
            return Legal.VERSION;
        }

        @JavascriptInterface
        public void showPrivacy() {
            ui(new Runnable() {
                @Override
                public void run() {
                    Legal.showPrivacy(MainActivity.this);
                }
            });
        }

        @JavascriptInterface
        public void showTerms() {
            ui(new Runnable() {
                @Override
                public void run() {
                    Legal.showTerms(MainActivity.this);
                }
            });
        }

        @JavascriptInterface
        public void showPersonalInfo() {
            ui(new Runnable() {
                @Override
                public void run() {
                    Legal.showPersonalInfo(MainActivity.this);
                }
            });
        }

        /** 兼容旧页面：一个按钮看两份协议时按顺序展示（新版页面已分开）。 */
        @JavascriptInterface
        public void showAgreement() {
            showPrivacy();
        }

        /** 导出全部数据（JSON）：写缓存目录 → 系统分享面板，不需要存储权限。 */
        @JavascriptInterface
        public void exportData(final String json) {
            ui(new Runnable() {
                @Override
                public void run() {
                    if (json == null || json.length() == 0) {
                        toast("没有可导出的数据");
                        return;
                    }
                    if (!shareExport(json)) {
                        toast("导出失败，请检查手机存储空间");
                    }
                }
            });
        }

        @JavascriptInterface
        public boolean startupLock() {
            return lockEnabled();
        }

        /** 开关启动验证：开启前要求手机已设置锁屏密码。 */
        @JavascriptInterface
        public boolean setStartupLock(final boolean on) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    if (on) {
                        KeyguardManager km = (KeyguardManager) getSystemService(
                                Context.KEYGUARD_SERVICE);
                        if (km == null || !km.isDeviceSecure()) {
                            toast("请先在系统设置里为手机设置锁屏密码/图案，再开启启动验证");
                            return;
                        }
                    }
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                            .putBoolean(KEY_LOCK, on).apply();
                    toast(on ? "已开启启动验证" : "已关闭启动验证");
                }
            });
            return on;
        }

        /** 撤回同意：清除本机全部数据并退出（PIPL 第 15 条）。 */
        @JavascriptInterface
        public void withdrawConsent() {
            ui(new Runnable() {
                @Override
                public void run() {
                    askWithdraw();
                }
            });
        }
    }

    private void ui(final Runnable r) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                r.run();
            }
        });
    }

    // ------------------------------------------------------------ 导出（查阅、复制权）
    /** 把 JSON 备份写到缓存目录并经系统分享面板交给用户，全程不申请存储权限。 */
    private boolean shareExport(String json) {
        try {
            File dir = new File(getCacheDir(), "exports");
            if (!dir.isDirectory() && !dir.mkdirs()) {
                return false;
            }
            // 旧备份先清掉，避免缓存目录里堆积个人信息
            File[] old = dir.listFiles();
            if (old != null) {
                for (File f : old) {
                    f.delete();
                }
            }
            String stamp = new java.text.SimpleDateFormat("yyyyMMdd_HHmmss",
                    java.util.Locale.CHINA).format(new java.util.Date());
            String name = "仓管家备份_" + stamp + ".json";
            FileOutputStream fo = new FileOutputStream(new File(dir, name));
            fo.write(json.getBytes("UTF-8"));
            fo.close();

            Uri u = ExportProvider.uriFor(name);
            Intent it = new Intent(Intent.ACTION_SEND);
            it.setType("application/json");
            it.putExtra(Intent.EXTRA_STREAM, u);
            it.putExtra(Intent.EXTRA_SUBJECT, name);
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            it.setClipData(ClipData.newRawUri("export", u));
            try {
                startActivity(Intent.createChooser(it, "保存或转发备份文件"));
            } catch (Exception e) {
                it.setType("*/*");
                startActivity(Intent.createChooser(it, "保存或转发备份文件"));
            }
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    // ------------------------------------------------------------ 撤回同意（PIPL 15）
    private void askWithdraw() {
        new AlertDialog.Builder(this)
                .setTitle("撤回同意并清除数据")
                .setMessage("撤回后，我们将不再处理你的个人信息：\n\n"
                        + "· 本机上的库存、出售记录、商品照片会被删除\n"
                        + "· 应用会退出\n"
                        + "· 已同步到你电脑的数据需在电脑端自行删除\n\n"
                        + "建议先在「数据管理」里导出备份。此操作不可撤销。")
                .setPositiveButton("仍要撤回", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        doWithdraw();
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private void doWithdraw() {
        try {
            if (web != null) {
                web.evaluateJavascript("try{localStorage.clear()}catch(e){}", null);
            }
            WebStorage.getInstance().deleteAllData();
            CookieManager cm = CookieManager.getInstance();
            cm.removeAllCookies(null);
            cm.flush();
        } catch (Throwable ignore) {
        }
        deleteTree(new File(getCacheDir(), "photos"));
        deleteTree(new File(getCacheDir(), "exports"));
        File crash = new File(getFilesDir(), CgmApp.CRASH_FILE);
        crash.delete();
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().clear().apply();
        Legal.clearAgreed(this);
        toast("已撤回同意并清除本机数据");
        // 给 WebView 一点时间把 localStorage 真正落盘
        new android.os.Handler(getMainLooper()).postDelayed(new Runnable() {
            @Override
            public void run() {
                finish();
            }
        }, 400);
    }

    private void deleteTree(File f) {
        if (f == null || !f.exists()) {
            return;
        }
        File[] kids = f.listFiles();
        if (kids != null) {
            for (File k : kids) {
                deleteTree(k);
            }
        }
        f.delete();
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
                                                // 相册走系统照片选择器：无需存储权限，
                                                // 系统只把用户主动选中的图片授予本应用。
                                                nativePickMode = true;
                                                openGalleryNative();
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

    /** 权限被拒/弹窗被取消：按当前模式把「空结果」交回对应通道。 */
    private void onPermDenied(boolean gallery) {
        String tip = gallery
                ? "未选择照片，已取消"
                : "未授予相机权限，无法拍照；可在系统设置 → 应用 → 仓管家里允许，"
                        + "也可以改用「从相册选择」或手动输入型号";
        android.widget.Toast.makeText(this, tip, android.widget.Toast.LENGTH_LONG).show();
        if (nativePickMode) {
            deliverNative(null);
        } else {
            finishFileCb(null);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] perms,
                                           int[] results) {
        super.onRequestPermissionsResult(requestCode, perms, results);
        boolean granted = results.length > 0
                && results[0] == PackageManager.PERMISSION_GRANTED;
        if (requestCode == REQ_CAM_PERM) {
            if (granted && pendingAfterPerm != null) {
                Runnable r = pendingAfterPerm;
                pendingAfterPerm = null;
                r.run();
            } else if (!granted) {
                pendingAfterPerm = null;
                onPermDenied(false);
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
        if (requestCode == REQ_UNLOCK) {                // 启动验证：通过才继续，取消即退出
            if (resultCode == RESULT_OK) {
                proceed();
            } else {
                finish();
            }
            return;
        }
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
                                    nativePickMode = false;   // 同上：系统选择器无需权限
                                    openGalleryOld(params);
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
