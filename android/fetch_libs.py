# -*- coding: utf-8 -*-
"""下载扫一扫需要的第三方文件（只需一次，之后构建离线可用）。

产物：
  android/libs/tesseract4android-4.7.0.aar     离线 OCR 引擎（含各架构 .so）
  android/assets/tessdata/chi_sim.traineddata  中文识别模型
  android/assets/tessdata/eng.traineddata      英文/数字识别模型

用法: .venv310/Scripts/python.exe android/fetch_libs.py
"""

import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(HERE, "libs")
TESS = os.path.join(HERE, "assets", "tessdata")

AAR_NAME = "tesseract4android-4.7.0.aar"
AAR_URLS = [
    "https://mirrors.cloud.tencent.com/nexus/repository/maven-public/cz/adaptech/"
    "tesseract4android/tesseract4android/4.7.0/" + AAR_NAME,
    "https://repo1.maven.org/maven2/cz/adaptech/tesseract4android/tesseract4android/"
    "4.7.0/" + AAR_NAME,
]
TESS_URLS = [
    "https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata_fast@main/%(n)s.traineddata",
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/%(n)s.traineddata",
]


def fetch(urls, dst, min_size=1024):
    if os.path.isfile(dst) and os.path.getsize(dst) >= min_size:
        print("已存在：%s" % os.path.relpath(dst, HERE))
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for u in urls:
        try:
            print("下载 %s" % u)
            req = urllib.request.Request(u, headers={"User-Agent": "cgm-build"})
            with urllib.request.urlopen(req, timeout=180) as r, open(dst, "wb") as f:
                data = r.read()
                if len(data) < min_size:
                    raise IOError("文件太小（%d 字节）" % len(data))
                f.write(data)
            print("  -> %s (%.1f MB)" % (os.path.relpath(dst, HERE), len(data) / 1048576.0))
            return True
        except Exception as e:                  # 换下一个镜像
            print("  失败：%s" % e)
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass
    return False


def main():
    ok = True
    ok = fetch(AAR_URLS, os.path.join(LIBS, AAR_NAME), 1024 * 1024) and ok
    for name in ("chi_sim", "eng"):
        urls = [u % {"n": name} for u in TESS_URLS]
        ok = fetch(urls, os.path.join(TESS, name + ".traineddata"), 512 * 1024) and ok
    if not ok:
        sys.exit("有文件没下载成功：连上网后重试，或手动放到上面列出的位置")
    print("全部就绪，可以构建：.venv310/Scripts/python.exe android/build_apk.py")


if __name__ == "__main__":
    main()
