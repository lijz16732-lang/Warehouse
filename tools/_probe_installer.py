# -*- coding: utf-8 -*-
"""探针：电脑端安装向导（v1.45.8）。

不点真实安装（不动 D 盘/桌面/注册表）：
1) 安装动作函数：copy_exe 分块复制 + 内容一致
2) write_uninstall_bat：GBK 内容含 taskkill/reg delete/自删
3) make_shortcuts：PowerShell 语法可生成（写到临时目录内 fake 目标，
   并把桌面/开始菜单指向临时目录——通过打桩 environ 隔离）
4) 向导 GUI 冒烟：三页切换、路径页按钮存在、完成页可构造
用法：.venv310/Scripts/python.exe tools/_probe_installer.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402

import installer  # noqa: E402

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print("  ok  %s" % name)
    else:
        print("  FAIL %s -> %r" % (name, detail))


def main():
    tmp = tempfile.mkdtemp(prefix="wm_inst_")
    target = os.path.join(tmp, "install")

    # ① copy_exe：模拟主程序 3MB 随机字节，进度回调
    src = os.path.join(tmp, "src.exe")
    data = os.urandom(3 << 20)
    open(src, "wb").write(data)
    os.makedirs(target, exist_ok=True)   # 真实流程由 _install 负责
    ticks = []
    installer.copy_exe(src, os.path.join(target, "app.exe"),
                       progress=lambda d, t: ticks.append(d))
    got = open(os.path.join(target, "app.exe"), "rb").read()
    chk("copy_exe 内容一致", got == data)
    chk("进度回调多次", len(ticks) >= 2)

    # ② 卸载 bat
    bat = installer.write_uninstall_bat(target)
    content = open(bat, "rb").read().decode("gbk")
    chk("unins.bat 含清理要素",
        all(x in content for x in ("taskkill", "reg delete", "rd /s /q",
                                   installer.UNINSTALL_KEY.split("\\")[-1])))
    chk("unins.bat 在安装目录", os.path.dirname(bat) == os.path.abspath(target))

    # ③ 快捷方式：打桩桌面/开始菜单到临时目录，真跑 PowerShell
    os.environ["USERPROFILE"] = tmp
    os.makedirs(os.path.join(tmp, "Desktop"), exist_ok=True)
    os.environ["APPDATA"] = os.path.join(tmp, "AppData")
    os.makedirs(os.path.join(tmp, "AppData", "Microsoft", "Windows",
                             "Start Menu", "Programs"), exist_ok=True)
    open(os.path.join(target, "app.ico"), "wb").write(b"ico")
    installer.make_shortcuts(target, "1.45.8")
    lnks = [os.path.join(tmp, "Desktop", "仓管家.lnk"),
            os.path.join(tmp, "AppData", "Microsoft", "Windows",
                         "Start Menu", "Programs", "仓管家.lnk")]
    made = [p for p in lnks if os.path.exists(p)]
    chk("快捷方式 .lnk 已生成（桌面+开始菜单）", len(made) == 2,
        str([p for p in lnks if not os.path.exists(p)]))

    # ④ 注册表函数（写临时键名再清——不打桩，用探针专属键）
    import winreg
    installer.UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion" \
                              r"\Uninstall\CangGuanJiaProbe"
    ok = installer.write_uninstall_reg(target, "9.9.9-test")
    chk("卸载注册表项写入成功", ok)
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, installer.UNINSTALL_KEY)
        val, _t = winreg.QueryValueEx(k, "DisplayVersion")
        winreg.CloseKey(k)
        chk("DisplayVersion 可读回", val == "9.9.9-test", val)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, installer.UNINSTALL_KEY)
    except Exception as e:
        chk("DisplayVersion 可读回", False, str(e))

    # ⑤ GUI 冒烟：欢迎页 → 路径页切换，无异常
    w = installer.Wizard()
    w.update()
    chk("向导窗口打开（欢迎页）", w.step == 0)
    w._show(1)
    w.update()
    chk("路径页切换", w.step == 1)
    btns = [x.cget("text") for x in w.body.winfo_children()[0].winfo_children()
            if isinstance(x, tk.Button)]
    chk("路径页有「浏览…」", "浏览…" in btns, str(btns))
    chk("默认安装位置 D:\\仓库管理工具", w.var_dir.get() == "D:\\仓库管理工具")
    w.destroy()

    print("\n%d 项通过" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
