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
 * 极简照片 ContentProvider（不引 androidx，纯 android.jar 实现）。
 *
 * 作用：拍照功能里，相机应用（独立进程）不能直接写应用私有目录，
 * 必须给它一个 content:// Uri。androidx 的 FileProvider 在本工程里
 * 没有对应依赖，所以手写一个只服务 cacheDir/photos 的迷你版。
 *
 * 安全：exported=false + grantUriPermissions=true，只有本 App 主动
 * 授予临时读/写权限的调用方（相机）能访问；路径段禁止 ".." 防穿越。
 */
public class PhotoProvider extends ContentProvider {

    public static final String AUTHORITY = "com.cangguanjia.app.photos";

    private File dir() {
        return new File(getContext().getCacheDir(), "photos");
    }

    /** 把 photos 目录下的文件包装成可交给相机的 content Uri。 */
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
        int m = ParcelFileDescriptor.MODE_READ_ONLY;
        if ("w".equals(mode) || "rw".equals(mode)) {
            m = ParcelFileDescriptor.MODE_WRITE_ONLY
                    | ParcelFileDescriptor.MODE_CREATE
                    | ParcelFileDescriptor.MODE_TRUNCATE;
        }
        return ParcelFileDescriptor.open(f, m);
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
        return "image/jpeg";
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
