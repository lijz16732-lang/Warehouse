package com.cangguanjia.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * 数据导出中转（不引 androidx，纯 android.jar 实现，与 PhotoProvider 同款思路）。
 *
 * 用途：用户行使《个人信息保护法》第四十五条的查阅、复制权时，把「导出全部数据」
 * 生成的 JSON 备份文件包装成 content:// 交给系统分享面板（微信、文件管理、邮件），
 * 全程不需要存储权限，也不写公共目录。
 *
 * 安全：exported=false + grantUriPermissions=true，仅本 App 主动授权的应用可读；
 * 路径段禁止分隔符与 ".."，杜绝目录穿越。
 */
public class ExportProvider extends ContentProvider {

    public static final String AUTHORITY = "com.cangguanjia.app.export";

    private File dir() {
        return new File(getContext().getCacheDir(), "exports");
    }

    public static Uri uriFor(String name) {
        return Uri.parse("content://" + AUTHORITY + "/" + name);
    }

    private File fileFor(Uri uri) {
        String name = uri.getLastPathSegment();
        if (name == null || name.contains("/") || name.contains("\\")
                || name.contains("..")) {
            return null;
        }
        return new File(dir(), name);
    }

    @Override
    public boolean onCreate() {
        File d = dir();
        return d.isDirectory() || d.mkdirs();
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode)
            throws FileNotFoundException {
        File f = fileFor(uri);
        if (f == null || !f.isFile()) {
            throw new FileNotFoundException(uri.toString());
        }
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public Cursor query(Uri uri, String[] proj, String sel, String[] args,
                        String sort) {
        if (proj == null || proj.length == 0) {
            proj = new String[]{OpenableColumns.DISPLAY_NAME,
                                OpenableColumns.SIZE};
        }
        MatrixCursor c = new MatrixCursor(proj);
        File f = fileFor(uri);
        if (f != null && f.isFile()) {
            Object[] row = new Object[proj.length];
            for (int i = 0; i < proj.length; i++) {
                if (OpenableColumns.DISPLAY_NAME.equals(proj[i])) {
                    row[i] = f.getName();
                } else if (OpenableColumns.SIZE.equals(proj[i])) {
                    row[i] = f.length();
                } else {
                    row[i] = null;
                }
            }
            c.addRow(row);
        }
        return c;
    }

    @Override
    public String getType(Uri uri) {
        return "application/json";
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String sel, String[] args) {
        File f = fileFor(uri);
        return (f != null && f.isFile() && f.delete()) ? 1 : 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String sel, String[] args) {
        return 0;
    }
}
