package com.cangguanjia.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.text.method.LinkMovementMethod;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;

/**
 * 合规文本与同意状态（依据《个人信息保护法》第 14、17 条，《网络安全法》第 24、43 条，
 * 《移动互联网应用程序信息服务管理规定》第 10、12 条）。
 *
 * 设计要点：
 *  · 隐私政策与用户协议**分开独立展示**，不混在一个弹窗里；
 *  · 首次启动必须**主动勾选**同意（不默认勾选），未勾选点击"同意"不生效；
 *  · 同意状态记录的是**政策版本号**而不是布尔值 —— 政策升版后下次启动会重新征得同意；
 *  · "不同意"与"同意"同等显著，不同意即退出，不诱导、不反复纠缠；
 *  · 协议正文放在 assets/legal/*.txt，改文案不用改代码，也便于与上架材料保持一致。
 */
public final class Legal {

    /** 政策版本号：任何实质性修改都必须递增，否则老用户不会重新看到同意页。 */
    public static final String VERSION = "1.1";
    public static final String EFFECTIVE = "2026年11月2日";

    private static final String PREF = "cgm";
    private static final String KEY_VER = "legal_ver";

    private Legal() {
    }

    // ------------------------------------------------------------ 文本读取
    static String readAsset(Context c, String name) {
        InputStream in = null;
        try {
            in = c.getAssets().open("legal/" + name);
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) {
                bo.write(buf, 0, n);
            }
            return new String(bo.toByteArray(), "UTF-8");
        } catch (Throwable t) {
            return "协议正文读取失败（" + name + "），请重新安装应用或联系开发者。";
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (Throwable ignore) {
                }
            }
        }
    }

    static String privacyText(Context c) {
        return readAsset(c, "privacy.txt");
    }

    static String termsText(Context c) {
        return readAsset(c, "terms.txt");
    }

    // ------------------------------------------------------------ 同意状态
    static boolean agreed(Context c) {
        return VERSION.equals(c.getSharedPreferences(PREF, Context.MODE_PRIVATE)
                .getString(KEY_VER, ""));
    }

    static void markAgreed(Context c) {
        c.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit()
                .putString(KEY_VER, VERSION).apply();
    }

    static void clearAgreed(Context c) {
        SharedPreferences sp = c.getSharedPreferences(PREF, Context.MODE_PRIVATE);
        sp.edit().remove(KEY_VER).apply();
    }

    // ------------------------------------------------------------ 弹窗
    private static int dp(Context c, float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                c.getResources().getDisplayMetrics());
    }

    private static TextView body(Context c, String text) {
        TextView tv = new TextView(c);
        tv.setText(text);
        tv.setTextSize(13.5f);
        tv.setLineSpacing(0, 1.3f);
        tv.setTextColor(Color.parseColor("#222222"));
        tv.setTextIsSelectable(true);
        tv.setPadding(dp(c, 18), dp(c, 12), dp(c, 18), dp(c, 12));
        return tv;
    }

    /** 只读展示一份协议全文（可滚动、可长按复制）。 */
    static void showText(final Activity a, String title, String text) {
        ScrollView sc = new ScrollView(a);
        sc.addView(body(a, text));
        new AlertDialog.Builder(a)
                .setTitle(title)
                .setView(sc)
                .setPositiveButton("关闭", null)
                .show();
    }

    static void showPrivacy(Activity a) {
        showText(a, "隐私政策（v" + VERSION + "）", privacyText(a));
    }

    static void showTerms(Activity a) {
        showText(a, "用户协议（v" + VERSION + "）", termsText(a));
    }

    /** 个人信息收集使用清单：一眼看清处理了哪些信息、用来做什么。 */
    static void showPersonalInfo(Activity a) {
        String t = "本应用在你的手机上处理以下信息，全部只存在本机：\n\n"
                + "1. 库存与出售记录\n"
                + "   字段：编号、品牌、类别、型号、成色、进价、售价、数量、货位、\n"
                + "   备注、买家称呼、出售日期、交易金额\n"
                + "   用途：库存登记、出入库、销售记录与统计\n\n"
                + "2. 商品照片与照片备注\n"
                + "   用途：商品留档；仅在你开启共享时同步到你自己的电脑\n\n"
                + "3. 拍照识别时的图像\n"
                + "   用途：离线识别型号/二维码；仅在内存处理，不留存、不上传\n\n"
                + "4. 应用配置（主题、列显示、编号前缀、电脑地址、会话令牌）\n"
                + "   用途：记住使用偏好与连接状态\n\n"
                + "5. 崩溃日志（时间、版本号、错误堆栈）\n"
                + "   用途：定位故障；下次启动展示后即删除\n\n"
                + "6. 局域网连接记录（IP、时间、接口、结果）\n"
                + "   用途：安全审计；保存在你自己的电脑上，留存 180 天\n\n"
                + "不收集：通讯录、短信、通话记录、位置、设备标识符、\n"
                + "应用列表、剪贴板、生物识别信息。\n\n"
                + "未集成任何第三方 SDK；不向任何第三方共享、出售、公开披露。";
        showText(a, "个人信息收集使用清单", t);
    }

    /**
     * 首启同意页：摘要 + 两个协议全文入口 + 默认不勾选的复选框。
     * 未勾选时点"同意并继续"只提示、不关闭 —— 保证同意是主动作出的。
     */
    static void askConsent(final Activity a, final Runnable onAgree,
                           final Runnable onReject) {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(0, dp(a, 4), 0, 0);

        String summary = "本应用是本地库存管理工具：不设账号、不设云端服务器，"
                + "你的库存、出售记录与商品照片只保存在这台手机上，我们不会收到你的任何业务数据。\n\n"
                + "为提供服务，本应用在你的手机上处理：\n"
                + "· 你录入的库存与出售记录（含买家称呼）\n"
                + "· 你拍摄或选择的商品照片\n"
                + "· 拍照识别时的图像（仅内存处理，不留存）\n"
                + "· 应用配置与崩溃日志\n\n"
                + "本应用只申请「相机」一个权限，用于拍照留档与拍照识别；"
                + "你可以拒绝，拒绝后仍能手动输入型号、从相册选图。"
                + "相册选图使用系统照片选择器，不申请存储权限。\n\n"
                + "本应用未集成任何第三方 SDK，不向任何第三方共享、出售你的信息，"
                + "也不会把数据上传到互联网；只有你主动开启共享时，数据才会同步到"
                + "同一局域网内你自己的电脑。\n\n"
                + "你可以随时在「设置 → 隐私与数据」查看清单、导出数据、删除数据或撤回同意。";

        TextView tvSum = body(a, summary);
        tvSum.setTextIsSelectable(false);
        ScrollView sc = new ScrollView(a);
        sc.addView(tvSum);
        LinearLayout.LayoutParams lpSc = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f);
        box.addView(sc, lpSc);

        LinearLayout links = new LinearLayout(a);
        links.setOrientation(LinearLayout.HORIZONTAL);
        links.setGravity(Gravity.CENTER_VERTICAL);
        links.setPadding(dp(a, 8), dp(a, 6), dp(a, 8), 0);
        links.addView(link(a, "《隐私政策》全文", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showPrivacy(a);
            }
        }));
        links.addView(link(a, "《用户协议》全文", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTerms(a);
            }
        }));
        box.addView(links, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        final CheckBox cb = new CheckBox(a);
        cb.setText("我已阅读并同意《隐私政策》和《用户协议》");
        cb.setTextSize(13f);
        cb.setChecked(false);                 // 关键：不默认勾选
        cb.setPadding(dp(a, 14), dp(a, 6), dp(a, 8), 0);
        box.addView(cb);

        final AlertDialog d = new AlertDialog.Builder(a)
                .setTitle("欢迎使用仓管家")
                .setView(box)
                .setCancelable(false)
                .setPositiveButton("同意并继续", null)
                .setNegativeButton("不同意，退出", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dlg, int w) {
                        if (onReject != null) onReject.run();
                    }
                })
                .create();
        d.setOnShowListener(new DialogInterface.OnShowListener() {
            @Override
            public void onShow(DialogInterface dlg) {
                d.getButton(AlertDialog.BUTTON_POSITIVE)
                        .setOnClickListener(new View.OnClickListener() {
                            @Override
                            public void onClick(View v) {
                                if (!cb.isChecked()) {
                                    Toast.makeText(a, "请先阅读并勾选同意《隐私政策》和《用户协议》",
                                            Toast.LENGTH_SHORT).show();
                                    return;
                                }
                                markAgreed(a);
                                d.dismiss();
                                if (onAgree != null) onAgree.run();
                            }
                        });
            }
        });
        d.show();
    }

    private static TextView link(Activity a, String text, View.OnClickListener l) {
        TextView tv = new TextView(a);
        tv.setText(text);
        tv.setTextSize(13f);
        tv.setTextColor(Color.parseColor("#1f6feb"));
        tv.setPadding(dp(a, 8), dp(a, 4), dp(a, 8), dp(a, 4));
        tv.setMovementMethod(LinkMovementMethod.getInstance());
        tv.setOnClickListener(l);
        return tv;
    }
}
