# -*- coding: utf-8 -*-
"""一键构建仓管家手机 App（APK）。

用法: .venv310/Scripts/python.exe android/build_apk.py
依赖: JDK 17 + Android SDK build-tools/platforms（默认在 D:\android-build、D:\android-sdk，
      可用环境变量 CGM_JDK / CGM_SDK 覆盖）
产物: dist/仓管家手机版.apk（界面自带：assets/index.html 打包在 APK 内，离线可开；
      数据经电脑端局域网共享接口实时读写）
签名: 首次运行自动生成 android/cgm-release.keystore（密码 cgm12345，请妥善保存：
      以后升级 App 必须用同一把钥匙签名，否则手机上无法覆盖安装）
"""

import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                    # warehouse_manager/
OUT_DIR = os.path.join(ROOT, "dist")
SDK = os.environ.get("CGM_SDK", r"D:\android-sdk")
JDK = os.environ.get("CGM_JDK", "")
BUILD_TOOLS = os.path.join(SDK, "build-tools", "34.0.0")
PLATFORM = os.path.join(SDK, "platforms", "android-34", "android.jar")
KS = os.path.join(HERE, "cgm-release.keystore")
KS_PASS = "cgm12345"

LIBS = os.path.join(HERE, "libs")          # 第三方 AAR（离线 OCR：tesseract4android）
ABIS = ("arm64-v8a", "armeabi-v7a")        # 只打手机真机用的两种架构（省体积）

ICON_SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def unpack_aars(work):
    """把 libs/*.aar 拆成 classes.jar（编译/转 dex 用）和 jni 原生库（打进 APK）。"""
    jars, natives = [], []
    if not os.path.isdir(LIBS):
        return jars, natives
    out = os.path.join(work, "aar")
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(LIBS)):
        if not name.lower().endswith(".aar"):
            continue
        with zipfile.ZipFile(os.path.join(LIBS, name)) as z:
            names = z.namelist()
            if "classes.jar" in names:
                p = os.path.join(out, name[:-4] + ".jar")
                with open(p, "wb") as f:
                    f.write(z.read("classes.jar"))
                jars.append(p)
            for n in names:
                parts = n.split("/")
                if (len(parts) == 3 and parts[0] == "jni" and parts[1] in ABIS
                        and n.endswith(".so")):
                    d = os.path.join(out, "jni", parts[1])
                    os.makedirs(d, exist_ok=True)
                    dst = os.path.join(d, parts[2])
                    with open(dst, "wb") as f:
                        f.write(z.read(n))
                    natives.append((parts[1], dst))
    return jars, natives


def find_jdk():
    if JDK:
        return JDK
    base = r"D:\android-build"
    if os.path.isdir(base):
        for name in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, name, "bin")
            if name.lower().startswith("jdk") and os.path.isfile(os.path.join(p, "java.exe")):
                return os.path.join(base, name)
    raise SystemExit("找不到 JDK：请解压 JDK 到 D:\\android-build\\ 或设置环境变量 CGM_JDK")


def run(env, cmd, cwd=None):
    print("+", " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
    r = subprocess.call(cmd, cwd=cwd or HERE, env=env)
    if r != 0:
        sys.exit("命令失败（退出码 %d）：%s" % (r, cmd[0]))


def make_icons():
    """从 assets/app.ico 生成各密度启动图标。"""
    from PIL import Image
    src = os.path.join(ROOT, "assets", "app.ico")
    img = Image.open(src).convert("RGBA")
    for dpi, size in ICON_SIZES.items():
        d = os.path.join(HERE, "res", "mipmap-" + dpi)
        os.makedirs(d, exist_ok=True)
        img.resize((size, size), Image.LANCZOS).save(os.path.join(d, "ic_launcher.png"))
    print("图标已生成（%d 个密度）" % len(ICON_SIZES))


def ensure_keystore(env):
    if os.path.exists(KS):
        return
    keytool = os.path.join(env["CGM_JDK_BIN"], "keytool.exe")
    run(env, [keytool, "-genkeypair", "-v",
              "-keystore", KS, "-alias", "cgm",
              "-keyalg", "RSA", "-keysize", "2048", "-validity", "10950",
              "-storepass", KS_PASS, "-keypass", KS_PASS,
              "-dname", "CN=CangGuanJia, OU=CangGuanJia, O=CangGuanJia, C=CN"])


def main():
    jdk = find_jdk()
    if not os.path.isfile(os.path.join(BUILD_TOOLS, "aapt2.exe")):
        raise SystemExit("找不到 aapt2：%s（先用 sdkmanager 装 build-tools;34.0.0）" % BUILD_TOOLS)
    if not os.path.isfile(PLATFORM):
        raise SystemExit("找不到 android.jar：%s（先装 platforms;android-34）" % PLATFORM)

    env = dict(os.environ)
    env["JAVA_HOME"] = jdk
    env["PATH"] = os.path.join(jdk, "bin") + os.pathsep + env.get("PATH", "")
    env["CGM_JDK_BIN"] = os.path.join(jdk, "bin")

    make_icons()
    ensure_keystore(env)

    work = os.path.join(HERE, ".work")
    shutil.rmtree(work, ignore_errors=True)
    obj = os.path.join(work, "obj"); os.makedirs(obj)
    dex = os.path.join(work, "dex"); os.makedirs(dex)
    os.makedirs(OUT_DIR, exist_ok=True)

    aapt2 = os.path.join(BUILD_TOOLS, "aapt2.exe")
    javac = os.path.join(jdk, "bin", "javac.exe")
    d8 = os.path.join(BUILD_TOOLS, "d8.bat")
    zipalign = os.path.join(BUILD_TOOLS, "zipalign.exe")
    apksigner = os.path.join(BUILD_TOOLS, "apksigner.bat")

    # 1. 编译资源
    res_zip = os.path.join(work, "res.zip")
    run(env, [aapt2, "compile", "--dir", os.path.join(HERE, "res"), "-o", res_zip])
    # 2. 链接资源 + 清单 + assets（App 自带界面）→ 未装代码的 apk
    base = os.path.join(work, "base.apk")
    assets_dir = os.path.join(HERE, "assets")
    link_cmd = [aapt2, "link", "-o", base, "-I", PLATFORM,
                "--manifest", os.path.join(HERE, "AndroidManifest.xml"),
                "-R", res_zip, "--auto-add-overlay"]
    if os.path.isdir(assets_dir):
        link_cmd += ["-A", assets_dir]
    run(env, link_cmd)
    # 3. 编译 Java → class → dex（含第三方 AAR 的 classes.jar）
    jars, natives = unpack_aars(work)
    srcs = []
    for dirpath, _, names in os.walk(os.path.join(HERE, "src")):
        srcs += [os.path.join(dirpath, n) for n in names if n.endswith(".java")]
    cp = os.pathsep.join([PLATFORM] + jars)
    run(env, [javac, "-encoding", "UTF-8", "-source", "1.8", "-target", "1.8",
              "-classpath", cp, "-d", obj] + srcs)
    classes = []
    for dirpath, _, names in os.walk(obj):
        classes += [os.path.join(dirpath, n) for n in names if n.endswith(".class")]
    run(env, [d8, "--release", "--lib", PLATFORM, "--output", dex] + classes + jars)
    # 4. classes*.dex + native 库塞进 apk
    with zipfile.ZipFile(base, "a") as z:
        for n in sorted(os.listdir(dex)):
            if n.endswith(".dex"):
                z.write(os.path.join(dex, n), n)
        for abi, path in natives:
            z.write(path, "lib/" + abi + "/" + os.path.basename(path),
                    compress_type=zipfile.ZIP_STORED)
    # 5. 对齐（-p：按页对齐未压缩的 .so，AGP 同款做法）+ 签名
    aligned = os.path.join(work, "aligned.apk")
    run(env, [zipalign, "-p", "-f", "4", base, aligned])
    out = os.path.join(OUT_DIR, "仓管家手机版.apk")
    run(env, [apksigner, "sign", "--ks", KS, "--ks-pass", "pass:" + KS_PASS,
              "--key-pass", "pass:" + KS_PASS, "--ks-key-alias", "cgm",
              "--out", out, aligned])
    print("\n=== APK 构建完成 ===")
    print("输出: %s (%.2f MB)" % (out, os.path.getsize(out) / 1048576.0))
    print("装到手机：把 apk 传到手机（微信文件传输/数据线均可）→ 安装 →")
    print("打开 App 填电脑上「局域网共享 → 手机访问」的地址和连接码即可。")


if __name__ == "__main__":
    main()
