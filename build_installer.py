# -*- coding: utf-8 -*-
"""打包「仓管家安装程序.exe」（v1.45.8 安装向导）。

用法：.venv310/Scripts/python.exe build_installer.py
前提：build.py 已跑过（dist/仓管家-仓库管理系统.exe 存在）。
输出：dist/仓管家安装程序.exe（内嵌主程序与图标，单文件免安装直接分发）
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PYI = os.path.join(ROOT, ".venv310", "Scripts", "pyinstaller.exe")
SRC = os.path.join(ROOT, "tools", "installer.py")
APP = os.path.join(ROOT, "dist", "仓管家-仓库管理系统.exe")
ICO = os.path.join(ROOT, "assets", "app.ico")

for p in (PYI, SRC, APP, ICO):
    assert os.path.exists(p), "缺文件：" + p

cmd = [
    PYI, "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "仓管家安装程序",
    "--icon", ICO,
    "--add-data", APP + ";app",
    "--add-data", ICO + ";assets",
    "--distpath", os.path.join(ROOT, "dist"),
    "--workpath", os.path.join(ROOT, "build"),
    "--specpath", os.path.join(ROOT, "build"),
    SRC,
]
print("正在打包安装向导…")
r = subprocess.run(cmd)
if r.returncode:
    sys.exit(r.returncode)
out = os.path.join(ROOT, "dist", "仓管家安装程序.exe")
print("=== 安装向导打包完成 ===")
print("输出:", out, "(%.1f MB)" % (os.path.getsize(out) / 1048576))
