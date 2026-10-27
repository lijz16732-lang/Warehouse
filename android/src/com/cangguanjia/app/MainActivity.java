package com.cangguanjia.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * 仓管家手机 App：独立应用，数据存在手机本地（离线可用）；
 * 「数据共享到电脑端」在 App 的「设置」页配置（经电脑端局域网共享接口同步）。
 * 界面打包在 APK 内（assets/index.html），加载本地页面、秒开。
 */
public class MainActivity extends Activity {

    private static final String PREFS = "cgm";
    private static final String KEY_URL = "server_url";
    private static final String LOCAL_PAGE = "file:///android_asset/index.html";

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
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            moveTaskToBack(true);      // 不直接退出，保留数据与登录状态
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
