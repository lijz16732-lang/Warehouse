package com.cangguanjia.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.File;

/**
 * 仓管家手机 App：独立应用，数据存在手机本地（离线可用）；
 * 「数据共享到电脑端」在 App 的「设置」页配置（经电脑端局域网共享接口同步）。
 * 界面打包在 APK 内（assets/index.html），加载本地页面、秒开。
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

    private WebView web;
    private ValueCallback<Uri[]> fileCb;     // 页面文件选择回调（拍照/相册共用）
    private File pendingCamFile;             // 本次拍照要写入的文件

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
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
        // 文件选择（照片添加）：WebView 的 <input type=file> 必须有
        // WebChromeClient.onShowFileChooser 才会弹系统选择器，否则点了没反应
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
        // 页面调用本机「扫一扫」识别文字（完全离线，不走电脑）
        web.addJavascriptInterface(new ScanBridge(), "AndroidOcr");

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

    private int dp(float v) {
        return (int) android.util.TypedValue.applyDimension(
                android.util.TypedValue.COMPLEX_UNIT_DIP, v,
                getResources().getDisplayMetrics());
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

    /** 协议正文（应用商店合规要求：首启展示、说明权限用途与数据去向）。 */
    private static final String PRIVACY_TEXT =
            "在使用本应用前，请务必阅读并理解《隐私政策》和《用户协议》：\n\n"
            + "一、隐私政策\n\n"
            + "1. 数据存储：您的全部库存数据仅保存在本机（手机本地存储 / 电脑本地数据库），"
            + "本应用不连接任何云服务器，不在云端留存任何数据。\n\n"
            + "2. 局域网同步：仅当您主动开启「数据共享到电脑端」时，应用才会与同一局域网内"
            + "您自己的电脑直接通信；数据不经互联网传输，也不经过任何第三方。\n\n"
            + "3. 相机权限：仅用于 ① 拍照添加商品照片 ② 扫一扫识别型号文字 / 二维码。"
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

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_FILE) {                  // 相册：支持单/多选
            finishFileCb(WebChromeClient.FileChooserParams
                    .parseResult(resultCode, data));
            return;
        }
        if (requestCode == REQ_CAMERA) {                // 拍照：成功把文件 Uri 交给页面
            if (resultCode == RESULT_OK && pendingCamFile != null
                    && pendingCamFile.isFile() && pendingCamFile.length() > 0) {
                finishFileCb(new Uri[]{PhotoProvider.uriFor(pendingCamFile.getName())});
            } else {
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

    // ------------------------------------------------------------ 照片选择（拍照 / 相册）
    /** 页面触发文件选择时弹「拍照 / 相册」二选一；取消则告知页面（回调 null）。 */
    private void showPickDialog(final WebChromeClient.FileChooserParams params) {
        new AlertDialog.Builder(this)
                .setTitle("添加照片")
                .setItems(new String[]{"拍照", "从相册选择"},
                        new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int which) {
                                if (which == 0) {
                                    startCamera();
                                } else {
                                    startGallery(params);
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

    private void startGallery(WebChromeClient.FileChooserParams params) {
        try {
            // createIntent 带 image/* 与多选标记（页面 input 已设 multiple）
            startActivityForResult(Intent.createChooser(
                    params.createIntent(), "选择照片"), REQ_FILE);
        } catch (Exception e) {
            finishFileCb(null);
        }
    }

    private void startCamera() {
        if (Build.VERSION.SDK_INT >= 23 && checkSelfPermission(
                android.Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
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
                                    finishFileCb(null);
                                }
                            })
                    .setOnCancelListener(new DialogInterface.OnCancelListener() {
                        @Override
                        public void onCancel(DialogInterface d) {
                            finishFileCb(null);
                        }
                    })
                    .show();
            return;
        }
        launchCamera();
    }

    private void launchCamera() {
        File dir = new File(getCacheDir(), "photos");
        if (!dir.isDirectory()) {
            dir.mkdirs();
        }
        pendingCamFile = new File(dir, "cam_" + System.currentTimeMillis() + ".jpg");
        Intent it = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
        it.putExtra(android.provider.MediaStore.EXTRA_OUTPUT,
                PhotoProvider.uriFor(pendingCamFile.getName()));
        it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try {
            startActivityForResult(it, REQ_CAMERA);
        } catch (Exception e) {
            pendingCamFile = null;
            finishFileCb(null);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] perms,
                                           int[] results) {
        super.onRequestPermissionsResult(requestCode, perms, results);
        if (requestCode == REQ_CAM_PERM) {
            if (results.length > 0
                    && results[0] == PackageManager.PERMISSION_GRANTED) {
                launchCamera();
            } else {
                android.widget.Toast.makeText(this,
                        "未授予相机权限，无法拍照；可在系统设置 → 应用 → 仓管家里允许",
                        android.widget.Toast.LENGTH_LONG).show();
                finishFileCb(null);
            }
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
