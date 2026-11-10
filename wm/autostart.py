# -*- coding: utf-8 -*-
"""开机自启（写 HKCU 的 Run 键，不需要管理员权限）。

只操作当前用户的注册表项，不改系统级设置；关闭时删除该值即可完全还原。
"""

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WarehouseManager"


def command_line():
    """开机自启要执行的命令行：打包后是 exe 本身，源码运行是 pythonw + main.py。"""
    if getattr(sys, "frozen", False):
        return '"%s"' % os.path.abspath(sys.executable)
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entry = os.path.join(root, "main.py")
    return '"%s" "%s"' % (exe, entry)


def is_enabled():
    """注册表里是否已开启（值存在且指向当前程序）。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            try:
                val, _t = winreg.QueryValueEx(k, VALUE_NAME)
            except FileNotFoundError:
                return False
        return bool(str(val or "").strip())
    except Exception:
        return False


def enable():
    """写入自启项；返回 (成功, 提示)。"""
    import winreg
    cmd = command_line()
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, cmd)
        return True, cmd
    except Exception as e:
        return False, str(e)


def disable():
    """删除自启项；返回 (成功, 提示)。"""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY,
                            access=winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, VALUE_NAME)
            except FileNotFoundError:
                pass
        return True, ""
    except Exception as e:
        return False, str(e)


def sync(flag):
    """按期望状态开启/关闭；返回 (实际状态, 提示)。"""
    if flag:
        ok, msg = enable()
        return (ok, msg)
    ok, msg = disable()
    return (False if ok else is_enabled(), msg)
