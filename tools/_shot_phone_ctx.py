# -*- coding: utf-8 -*-
"""对运行中的仓管家截「手机数据」页右键菜单：在表格空白处右键，看菜单是否弹出。"""
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
        if "v1.21.4" in n.value:
            hwnd = h
            return False
    return True


user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
if not hwnd:
    print("未找到 v1.21.4 窗口")
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


def click(x, y, right=False):
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    down, up = (0x0008, 0x0010) if right else (0x0002, 0x0004)
    user32.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(up, 0, 0, 0, 0)
    time.sleep(0.6)


click(L + 391, T + 92)          # 「手机数据」页签
time.sleep(0.4)
click(L + 500, T + 430, right=True)   # 表格空白处右键
time.sleep(0.6)
screenshot.capture(os.path.join(ROOT, ".tmpdbg", "phone_ctx_blank.png"))
print("shot -> phone_ctx_blank.png")
user32.keybd_event(0x1B, 0, 0, 0)     # Esc 关菜单
user32.keybd_event(0x1B, 0, 2, 0)
time.sleep(0.3)
