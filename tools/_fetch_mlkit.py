# -*- coding: utf-8 -*-
"""一次性工具：从 dl.google.com 递归下载 ML Kit text-recognition-chinese 及其全部
编译期依赖（AAR/JAR），放进 android/libs/，供无 Gradle 的 build_apk.py 打包。
用法: ./.venv310/Scripts/python.exe tools/_fetch_mlkit.py
"""
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://dl.google.com/android/maven2/"
# Maven Central：javax.inject 等非 Google 依赖不在 dl.google.com，必须另找
CENTRAL = "https://repo1.maven.org/maven2/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBS = os.path.join(ROOT, "android", "libs")
TOP = [
    ("com.google.mlkit", "text-recognition-chinese", "16.0.1"),
    # dagger/transport 的父接口 Provider 在这里；缺了它 ML Kit 创建识别器时
    # NoClassDefFoundError: javax/inject/Provider → 表现为「识别引擎没能启动」
    ("javax.inject", "javax.inject", "1"),
]
NS = "{http://maven.apache.org/POM/4.0.0}"


def fetch(url):
    # 沙箱代理对 dl.google.com 返回 502，强制直连
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": "cgm-fetch/1.0"})
    with opener.open(req, timeout=60) as r:
        return r.read()


def repos(g):
    """该 groupId 该去哪找：Google 自家在 dl.google.com，其余优先 Central。"""
    if g.startswith(("com.google", "androidx")):
        return [BASE, CENTRAL]
    return [CENTRAL, BASE]


def pom_path(g, a, v):
    return "%s/%s/%s/%s-%s.pom" % (g.replace(".", "/"), a, v, a, v)


def parse_deps(pom_bytes):
    """极简 POM 解析：抓 <dependencies> 里 scope=compile/runtime 的条目。"""
    txt = pom_bytes.decode("utf-8", "replace")
    txt = re.sub(r"<parent>.*?</parent>", "", txt, flags=re.S)
    root = ET.fromstring(txt)
    out = []
    dep = root.find(NS + "dependencies")
    if dep is None:
        return out
    for d in dep.findall(NS + "dependency"):
        scope = (d.findtext(NS + "scope") or "compile").strip()
        if scope not in ("compile", "runtime"):
            continue
        if (d.findtext(NS + "optional") or "").strip().lower() == "true":
            continue
        g = (d.findtext(NS + "groupId") or "").strip()
        a = (d.findtext(NS + "artifactId") or "").strip()
        v = (d.findtext(NS + "version") or "").strip()
        if g and a and v:
            out.append((g, a, v))
    return out


def pom_packaging(pom_bytes):
    root = ET.fromstring(re.sub(r"<parent>.*?</parent>", "",
                                pom_bytes.decode("utf-8", "replace"), flags=re.S))
    return (root.findtext(NS + "packaging") or "jar").strip()


def main():
    os.makedirs(LIBS, exist_ok=True)
    todo = list(TOP)
    seen = set()
    while todo:
        g, a, v = todo.pop()
        key = (g, a, v)
        if key in seen:
            continue
        seen.add(key)
        pom = None
        for repo in repos(g):
            try:
                pom = fetch(repo + pom_path(g, a, v))
                break
            except Exception as e:
                last = e
        if pom is None:
            print("!! POM 拉取失败 %s:%s:%s → %s" % (g, a, v, last))
            continue
        pkg = pom_packaging(pom)
        ext = "aar" if pkg.lower() == "aar" else "jar"
        fname = "%s-%s.%s" % (a, v, ext)
        dst = os.path.join(LIBS, fname)
        if not os.path.exists(dst):
            data, used = None, None
            for repo in repos(g):
                url = "%s%s/%s/%s/%s" % (repo, g.replace(".", "/"), a, v, fname)
                try:
                    data, used = fetch(url), url
                    break
                except Exception as e:
                    last = e
            if data is None:
                print("!! 下载失败 %s:%s:%s → %s" % (g, a, v, last))
                continue
            with open(dst, "wb") as f:
                f.write(data)
            print("+ %-8s %-60s %6.1f KB" % (ext, fname, len(data) / 1024.0))
        else:
            print("  已有   %s" % fname)
        for dep in parse_deps(pom):
            todo.append(dep)
    print("\n共解析 %d 个包，libs 目录：" % len(seen))
    for n in sorted(os.listdir(LIBS)):
        print("   ", n)


if __name__ == "__main__":
    sys.exit(main())
