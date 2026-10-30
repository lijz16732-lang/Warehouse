# -*- coding: utf-8 -*-
"""一键打包：生成 exe。

用法: .venv310/Scripts/python.exe build.py
产物: dist/仓管家-仓库管理系统.exe
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, "assets", "app.ico")
NAME = "WarehouseManager"
OUT_NAME = "仓管家-仓库管理系统"

VERSION_TEMPLATE = '''# -*- coding: utf-8 -*-
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 26, 4, 0),
    prodvers=(1, 26, 4, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', '仓管家'),
        StringStruct('FileDescription', '仓管家 · 仓库管理系统'),
        StringStruct('FileVersion', '1.26.4.0'),
        StringStruct('InternalName', 'WarehouseManager'),
        StringStruct('LegalCopyright', 'Copyright (C) 2026'),
        StringStruct('OriginalFilename', '%(out)s.exe'),
        StringStruct('ProductName', '仓管家 · 仓库管理系统'),
        StringStruct('ProductVersion', '1.26.4.0')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
'''


def run(cmd):
    print("+", " ".join(cmd))
    r = subprocess.call(cmd, cwd=HERE)
    if r != 0:
        sys.exit("命令失败，退出码 %d" % r)


def main():
    if not os.path.exists(ICON):
        print("生成图标...")
        subprocess.check_call([sys.executable,
                               os.path.join(HERE, "tools", "make_icon.py")])

    vfile = os.path.join(HERE, "build_version.txt")
    with open(vfile, "w", encoding="utf-8") as f:
        f.write(VERSION_TEMPLATE % {"out": OUT_NAME})

    cmd = [
        os.path.join(HERE, ".venv310", "Scripts", "pyinstaller.exe"),
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME,
        "--icon", ICON,
        "--version-file", vfile,
        "--add-data", ICON + ";assets",
        "--distpath", "dist", "--workpath", "build", "--specpath", "build",
        "main.py",
    ]
    run(cmd)

    src = os.path.join(HERE, "dist", NAME + ".exe")
    dst = os.path.join(HERE, "dist", OUT_NAME + ".exe")
    if os.path.exists(dst):
        os.remove(dst)
    shutil.copy2(src, dst)
    print("\n=== 打包完成 ===")
    print("输出: %s (%.1f MB)" % (dst, os.path.getsize(dst) / 1048576.0))


if __name__ == "__main__":
    main()
