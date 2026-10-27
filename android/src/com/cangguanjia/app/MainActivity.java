package com.cangguanjia.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

/**
 * 仓管家手机 App：独立应用，数据存在手机本地（离线可用）；
 * 「数据共享到电脑端」在 App 的「设置」页配置（经电脑端局域网共享接口同步）。
 * 界面打包在 APK 内（assets/index.html），加载本地页面、秒开。
 */
public class MainActivity extends Activity {

    private static final String PREFS = "cgm";
    private static final String KEY_URL = "server_url";
    private static final String LOCAL_PAGE = "file:///android_asset/index.html";
    private static final int REQ_SCAN = 1001;
    private static final int REQ_QR = 1002;

    private WebView web;

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
        // 页面调用本机「扫一扫」识别文字（完全离线，不走电脑）
        web.addJavascriptInterface(new ScanBridge(), "AndroidOcr");

        setContentView(web);

        // 电脑地址在 App 设置页里配置；若以前填过，经 hash 传给页面做预填
        String saved = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_URL, "");
        String url = LOCAL_PAGE;
        if (saved.length() > 0) {
            url += "#base=" + Uri.encode(saved);
        }
        web.loadUrl(url);
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

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (data == null || resultCode != RESULT_OK) return;
        String text = data.getStringExtra(ScanActivity.EXTRA_TEXT);
        if (text == null || text.length() == 0) return;
        if (requestCode == REQ_SCAN) {
            callPage("window.__ocrFill(", text);
        } else if (requestCode == REQ_QR) {
            callPage("window.__qrResult(", text);
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
