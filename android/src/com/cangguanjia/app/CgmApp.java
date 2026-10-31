package com.cangguanjia.app;

import android.app.Application;
import android.content.Context;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * 应用入口：attachBaseContext 早于所有 ContentProvider 被调用，是进程里最早能装
 * 「未捕获异常」钩子的地方。任何启动期崩溃（provider / Activity / WebView 初始化）
 * 都会把堆栈写进私有目录，下次打开时由 MainActivity 弹出来——用户截图即可定位，
 * 不用连电脑抓 logcat。
 */
public class CgmApp extends Application {

    static final String CRASH_FILE = "last_crash.txt";

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(base);
        final Thread.UncaughtExceptionHandler prev =
                Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
            @Override
            public void uncaughtException(Thread t, Throwable e) {
                try {
                    saveCrash(CgmApp.this, e);
                } catch (Throwable ignored) {
                    // 记录失败绝不能影响崩溃本身的上报
                }
                if (prev != null) prev.uncaughtException(t, e);
            }
        });
    }

    /** 只保留最近一次：启动几次累积的旧崩溃没有价值。 */
    private static void saveCrash(Context c, Throwable e) {
        StringWriter sw = new StringWriter();
        PrintWriter pw = new PrintWriter(sw);
        String ver;
        try {
            ver = c.getPackageManager().getPackageInfo(c.getPackageName(), 0).versionName;
        } catch (Throwable t) {
            ver = "?";
        }
        pw.println("时间：" + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.CHINA)
                .format(new Date()));
        pw.println("版本：v" + ver);
        pw.println("线程：" + Thread.currentThread().getName());
        pw.println();
        e.printStackTrace(pw);
        pw.flush();

        File f = new File(c.getFilesDir(), CRASH_FILE);
        FileOutputStream out = null;
        try {
            out = new FileOutputStream(f);
            out.write(sw.toString().getBytes("UTF-8"));
        } catch (Throwable ignored) {
        } finally {
            try {
                if (out != null) out.close();
            } catch (Throwable ignored) {
            }
        }
    }

    /** 取出并删除上次崩溃记录；没有则返回 null。 */
    static String takeCrash(Context c) {
        File f = new File(c.getFilesDir(), CRASH_FILE);
        if (!f.isFile()) return null;
        try {
            FileInputStream in = new FileInputStream(f);
            byte[] buf = new byte[(int) Math.min(f.length(), 20000)];
            int n = in.read(buf);
            in.close();
            f.delete();
            return new String(buf, 0, Math.max(n, 0), "UTF-8");
        } catch (Throwable t) {
            return null;
        }
    }
}
