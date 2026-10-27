# -*- coding: utf-8 -*-
"""临时脚本：v1.22.0 部署后截屏（主界面 + 手机数据页）。"""
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import screenshot  # noqa: E402

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
hwnd = None


def _enum_cb(h, _l):
    global hwnd
    if user32.IsWindowVisible(h):
        n = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, n, 256)
        if "v1.22.0" in n.value:
            hwnd = h
            return False
    return True


user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
if not hwnd:
    print("未找到 v1.22.0 窗口")
    sys.exit(1)

user32.ShowWindow(hwnd, 9)
try:
    user32.SetForegroundWindow(hwnd)
except Exception:
    pass
time.sleep(1.2)

os.makedirs(os.path.join(ROOT, ".tmpdbg"), exist_ok=True)
screenshot.capture(os.path.join(ROOT, ".tmpdbg", "deploy_1210_main.png"))
print("shot -> deploy_1210_main.png")

rect = wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
L, T = rect.left, rect.top


def click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.5)


click(L + 391, T + 92)          # 「手机数据」页签
time.sleep(0.8)
screenshot.capture(os.path.join(ROOT, ".tmpdbg", "deploy_1210_phone.png"))
print("shot -> deploy_1210_phone.png")
