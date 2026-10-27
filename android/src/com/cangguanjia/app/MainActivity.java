package com.cangguanjia.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 仓管家手机端壳：WebView 加载电脑端「局域网共享」提供的手机页面（http://电脑IP:端口/m）。
 * 数据全部实时来自电脑，手机上不存副本；安全（连接码/会话/授权）由电脑端负责。
 */
public class MainActivity extends Activity {

    private static final String PREFS = "cgm";
    private static final String KEY_URL = "server_url";

    private WebView web;
    private LinearLayout setup;      // 首次使用：填电脑地址
    private LinearLayout failed;     // 加载失败：重试
    private TextView errText;
    private String pendingUrl = "";

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
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest req,
                                        WebResourceError err) {
                if (req != null && req.isForMainFrame()) showFailed();
            }
        });

        setContentView(buildRoot());
        String saved = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_URL, "");
        if (saved.length() > 0) {
            load(saved);
        } else {
            showSetup();
        }
    }

    /* ---------------- 根布局：三层叠放 ---------------- */
    private ViewGroup buildRoot() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(buildSetup());
        root.addView(buildFailed());
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
        input.setHint("例如 http://192.168.1.5:8765/m");
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
                if (!u.contains("/m")) {
                    u = u.replaceAll("/+$", "") + "/m";
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

    /* ---------------- 加载失败界面 ---------------- */
    private View buildFailed() {
        failed = new LinearLayout(this);
        failed.setOrientation(LinearLayout.VERTICAL);
        failed.setBackgroundColor(Color.parseColor("#f4f6fa"));
        failed.setPadding(dp(28), dp(80), dp(28), dp(28));
        failed.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView t = new TextView(this);
        t.setText("连接不上电脑");
        t.setTextSize(20);
        t.setTextColor(Color.parseColor("#1c2333"));
        failed.addView(t, vp(-2, dp(40)));

        errText = new TextView(this);
        errText.setText("请检查：电脑仓管家是否已「开启共享」；手机和电脑是否连着同一个 WiFi。");
        errText.setTextSize(14);
        errText.setTextColor(Color.parseColor("#8a94a6"));
        failed.addView(errText, vp(-2, dp(56)));

        Button retry = new Button(this);
        retry.setText("重 试");
        retry.setTextColor(Color.WHITE);
        retry.setBackgroundColor(Color.parseColor("#1f6feb"));
        retry.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { load(pendingUrl); }
        });
        failed.addView(retry, vp(-1, dp(48)));

        Button change = new Button(this);
        change.setText("更换电脑地址");
        change.setTextColor(Color.parseColor("#1f6feb"));
        change.setBackgroundColor(Color.WHITE);
        change.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showSetup(); }
        });
        failed.addView(change, vp(-1, dp(48)));
        return failed;
    }

    /* ---------------- 流程控制 ---------------- */
    private void load(String url) {
        pendingUrl = url;
        setup.setVisibility(View.GONE);
        failed.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
        web.loadUrl(url);
    }

    private void showSetup() {
        web.setVisibility(View.GONE);
        failed.setVisibility(View.GONE);
        setup.setVisibility(View.VISIBLE);
    }

    private void showFailed() {
        web.setVisibility(View.GONE);
        setup.setVisibility(View.GONE);
        errText.setText("地址：" + pendingUrl + "\n请检查：电脑仓管家是否已「开启共享」；"
                + "手机和电脑是否连着同一个 WiFi。");
        failed.setVisibility(View.VISIBLE);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (setup.getVisibility() == View.VISIBLE) {
                moveTaskToBack(true);
                return true;
            }
            if (failed.getVisibility() == View.VISIBLE) {
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
