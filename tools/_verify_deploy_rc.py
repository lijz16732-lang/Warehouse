# -*- coding: utf-8 -*-
"""真机验证部署后的 exe：右键出售记录列表 → 弹出复制菜单 → 截图。"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import screenshot  # noqa: E402

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

# 找标题含 v1.10.0 的窗口
hwnd = None


def _enum_cb(h, _):
    global hwnd
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, buf, 256)
    if "v1.10.0" in buf.value and user32.IsWindowVisible(h):
        hwnd = h
        return False
    return True


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
if not hwnd:
    print("未找到 v1.10.0 窗口")
    sys.exit(1)

user32.ShowWindow(hwnd, 9)
user32.SetForegroundWindow(hwnd)
time.sleep(1.0)

rect = wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
L, T = rect.left, rect.top
print("窗口:", L, T, rect.right - L, rect.bottom - T)


def click(x, y, right=False):
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    down, up = (0x0008, 0x0010) if right else (0x0002, 0x0004)
    user32.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(up, 0, 0, 0, 0)
    time.sleep(0.4)


# 1. 切到「出售记录」标签
click(L + 192, T + 92)
# 2. 在第一行数据上右键
click(L + 449, T + 431, right=True)
time.sleep(0.6)
screenshot.capture(os.path.join(ROOT, ".tmpdbg", "deploy_rightclick.png"))
print("shot -> deploy_rightclick.png")

# 3. Esc 关闭菜单
user32.keybd_event(0x1B, 0, 0, 0)
user32.keybd_event(0x1B, 0, 2, 0)
time.sleep(0.3)
