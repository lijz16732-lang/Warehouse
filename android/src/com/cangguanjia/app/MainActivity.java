package com.cangguanjia.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 仓管家手机端：界面打包在 APK 里（assets/index.html，本地加载、离线可用），
 * 数据通过电脑端「局域网共享」的接口实时读写；安全（连接码/会话/授权）由电脑端负责。
 */
public class MainActivity extends Activity {

    private static final String PREFS = "cgm";
    private static final String KEY_URL = "server_url";
    private static final String LOCAL_PAGE = "file:///android_asset/index.html";

    private WebView web;
    private LinearLayout setup;      // 首次使用 / 更换地址
    private String pendingBase = "";

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
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
        // 界面文件在 APK 本地（file://），要向电脑发跨源请求（拿数据）：
        s.setAllowFileAccess(true);                        // API 30+ 默认 false，必须打开
        s.setAllowUniversalAccessFromFileURLs(true);       // 本地页 → http 接口跨源
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        web.setWebViewClient(new WebViewClient());         // 页面内部自行处理加载失败
        web.addJavascriptInterface(new Bridge(), "App");   // 页面可唤起「更换地址」原生界面

        setContentView(buildRoot());
        String saved = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_URL, "");
        if (saved.length() > 0) {
            load(saved);
        } else {
            showSetup();
        }
    }

    /** 暴露给页面 JS 的最小桥：只提供「更换电脑地址」一个动作。 */
    private class Bridge {
        @JavascriptInterface
        public void changeAddress() {
            runOnUiThread(new Runnable() {
                @Override public void run() { showSetup(); }
            });
        }
    }

    /* ---------------- 根布局：三层叠放 ---------------- */
    private ViewGroup buildRoot() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(buildSetup());
        return root;
    }

    /* ---------------- 首次使用界面 ---------------- */
    private View buildSetup() {
        setup = new LinearLayout(this);
        setup.setOrientation(LinearLayout.VERTICAL);
        setup.setBackgroundColor(Color.parseColor("#f4f6fa"));
        setup.setPadding(dp(28), dp(60), dp(28), dp(28));

        TextView logo = new TextView(this);
        logo.setText("\uD83D\uDCE6");
        logo.setTextSize(48);
        logo.setGravity(Gravity.CENTER);
        setup.addView(logo, vp(-2, dp(64)));

        TextView title = new TextView(this);
        title.setText("仓管家 · 手机端");
        title.setTextSize(22);
        title.setGravity(Gravity.CENTER);
        title.setTextColor(Color.parseColor("#1c2333"));
        setup.addView(title, vp(-2, dp(40)));

        TextView tip = new TextView(this);
        tip.setText("填电脑上「局域网共享 → 手机访问」里显示的地址\n"
                + "（电脑和手机要连同一个 WiFi）");
        tip.setTextSize(14);
        tip.setGravity(Gravity.CENTER);
        tip.setTextColor(Color.parseColor("#8a94a6"));
        setup.addView(tip, vp(-2, dp(60)));

        final EditText input = new EditText(this);
        input.setHint("例如 192.168.1.5:8765");
        input.setTextSize(15);
        input.setSingleLine(true);
        input.setBackgroundColor(Color.WHITE);
        input.setPadding(dp(14), dp(12), dp(14), dp(12));
        setup.addView(input, vp(-1, dp(50)));
        final EditText addr = input;

        Button go = new Button(this);
        go.setText("连 接");
        go.setTextColor(Color.WHITE);
        go.setBackgroundColor(Color.parseColor("#1f6feb"));
        go.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                String u = addr.getText().toString().trim();
                if (!u.startsWith("http://") && !u.startsWith("https://")) {
                    u = "http://" + u;
                }
                u = u.replaceAll("/+$", "");
                u = u.replaceAll("/m$", "");          // 只留协议://IP:端口，页面自己拼接口
                if (u.length() <= 7) {
                    Toast.makeText(MainActivity.this, "请填写电脑地址", Toast.LENGTH_SHORT).show();
                    return;
                }
                getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_URL, u).apply();
                load(u);
            }
        });
        setup.addView(go, vp(-1, dp(48)));

        TextView help = new TextView(this);
        help.setText("忘了地址？在电脑上打开仓管家 → 数据 → 局域网共享 → ③ 手机访问");
        help.setTextSize(12);
        help.setGravity(Gravity.CENTER);
        help.setTextColor(Color.parseColor("#8a94a6"));
        setup.addView(help, vp(-2, dp(80)));
        return setup;
    }

    /* ---------------- 流程控制 ---------------- */
    private void load(String base) {
        pendingBase = base;
        setup.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
        // 电脑地址经 hash 传给本地页面；连不上电脑时页面内部会提示
        web.loadUrl(LOCAL_PAGE + "#base=" + Uri.encode(base));
    }

    private void showSetup() {
        web.setVisibility(View.GONE);
        setup.setVisibility(View.VISIBLE);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (setup.getVisibility() == View.VISIBLE) {
                moveTaskToBack(true);
                return true;
            }
            if (web.canGoBack()) {
                web.goBack();
                return true;
            }
            moveTaskToBack(true);      // 不直接退出，保留会话
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    /* ---------------- 小工具 ---------------- */
    private LinearLayout.LayoutParams vp(int w, int h) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(w, h);
        if (w == -2 || w == -1) p.gravity = Gravity.CENTER_HORIZONTAL;
        p.topMargin = dp(6);
        return p;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
