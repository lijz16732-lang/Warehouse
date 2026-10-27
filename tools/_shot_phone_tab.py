# -*- coding: utf-8 -*-
"""对运行中的仓管家截「手机数据」页：ctypes 真实鼠标点击页签后截屏。"""
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
        if "v1.18.0" in n.value:
            hwnd = h
            return False
    return True


user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
if not hwnd:
    print("未找到 v1.18.0 窗口")
    sys.exit(1)

user32.ShowWindow(hwnd, 9)
try:
    user32.SetForegroundWindow(hwnd)
except Exception:
    pass
time.sleep(1.0)

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
click(L + 128, T + 205)         # 「手机出售记录」子页签看一眼
click(L + 69, T + 205)          # 切回「手机库存」
time.sleep(0.6)
screenshot.capture(os.path.join(ROOT, ".tmpdbg", "deploy_1180_align.png"))
print("shot -> deploy_1180_align.png")
