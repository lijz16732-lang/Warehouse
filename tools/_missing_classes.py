# -*- coding: utf-8 -*-
"""扫描 dex：列出「被引用、但既不在 dex 里、也不属于 Android/Java 平台」的类型。

手写打包最怕缺第三方 jar：编译能过、安装能开，跑到某条代码路径才
NoClassDefFoundError（ML Kit 就是被 javax.inject.Provider 卡住的）。
用法: ./.venv310/Scripts/python.exe tools/_missing_classes.py [classes.dex]
"""
import os
import struct
import sys

PLATFORM = ("Ljava/", "Ljavax/", "Landroid/", "Ldalvik/", "Lkotlin/", "Lsun/",
            "Lorg/apache/http/", "Lorg/json/", "Lorg/w3c/", "Lorg/xml/",
            "Lorg/xmlpull/", "Ljunit/", "Ljava")
# javax.inject 不是平台自带（Maven Central 提供），单独保留
KEEP = ("Ljavax/inject/",)


def read_strings(buf, sid_size, sid_off):
    out = []
    for i in range(sid_size):
        off = struct.unpack_from("<I", buf, sid_off + i * 4)[0]
        p = off
        # uleb128 长度前缀
        while buf[p] & 0x80:
            p += 1
        p += 1
        end = buf.index(b"\x00", p)
        out.append(buf[p:end].decode("utf-8", "replace"))
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "android", "dist", "classes.dex")
    buf = open(path, "rb").read()
    if buf[:4] != b"dex\n":
        sys.exit("不是 dex 文件：%s" % path)
    sid_size, sid_off = struct.unpack_from("<II", buf, 0x38)
    tsize, toff = struct.unpack_from("<II", buf, 0x40)
    csize, coff = struct.unpack_from("<II", buf, 0x60)

    strings = read_strings(buf, sid_size, sid_off)
    types = []
    for i in range(tsize):
        types.append(strings[struct.unpack_from("<I", buf, toff + i * 4)[0]])
    defined = set()
    for i in range(csize):
        defined.add(types[struct.unpack_from("<I", buf, coff + i * 32)[0]])

    missing = {}
    for t in set(types):
        if t in defined or not t.startswith("L"):
            continue
        if any(t.startswith(p) for p in KEEP):
            pass
        elif any(t.startswith(p) for p in PLATFORM):
            continue
        missing[t] = missing.get(t, 0) + 1

    print("dex: %s" % path)
    print("类型总数 %d，已定义类 %d，疑似缺失 %d" % (tsize, len(defined), len(missing)))
    for t in sorted(missing):
        print("  ", t)


if __name__ == "__main__":
    main()
