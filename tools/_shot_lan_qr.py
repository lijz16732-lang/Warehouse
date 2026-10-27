# -*- coding: utf-8 -*-
"""临时脚本：开发环境打开「局域网共享」窗口，截屏验证二维码完整显示。

跑法：.venv310/Scripts/python.exe tools/_shot_lan_qr.py
"""
import os
import sys
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from wm.screen import enable_dpi_awareness          # noqa: E402
from wm.app import App                              # noqa: E402
import screenshot                                   # noqa: E402
import ctypes                                       # noqa: E402
import ctypes.wintypes as wintypes                  # noqa: E402

enable_dpi_awareness()
root = tk.Tk()
root.withdraw()
app = App(root)
root.update_idletasks()
root.update()
app.open_lan()
for _ in range(40):                                  # 等二维码 PNG 生成、窗口摆好
    root.update()
    time.sleep(0.05)

dlg = getattr(app, "lan_dlg", None)
if dlg is None:
    print("FAIL：局域网窗口没打开")
    sys.exit(1)
dlg.update_idletasks()
# 开发验证用：换端口 8766 开启共享（避开真实程序占用的 8765），让二维码渲染出来
dlg.var_port.set("8766")
dlg.toggle_host()
for _ in range(60):                                  # 等服务器起来、二维码 PNG 生成
    root.update()
    time.sleep(0.05)
dlg.update_idletasks()
root.update()

user32 = ctypes.windll.user32
rect = wintypes.RECT()
hwnd = int(dlg.frame(), 16) if isinstance(dlg.frame(), str) else dlg.winfo_id()
# Toplevel 用 winfo_id 不是顶层 HWND，改用窗口标题查找
found = []


def _enum_cb(h, _l):
    n = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, n, 256)
    if n.value == "局域网共享" and user32.IsWindowVisible(h):
        found.append(h)
        return False
    return True


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
if not found:
    print("FAIL：找不到局域网共享窗口 HWND")
    dlg.destroy()
    root.destroy()
    sys.exit(1)
user32.GetWindowRect(found[0], ctypes.byref(rect))
print("窗口尺寸:", rect.right - rect.left, "x", rect.bottom - rect.top)

out = os.path.join(ROOT, ".tmpdbg", "lan_qr.png")
screenshot.capture(out)
try:
    dlg.toggle_host()          # 关掉开发验证用的共享
    root.update()
except Exception:
    pass
dlg.destroy()
root.destroy()
print("shot ->", out)
