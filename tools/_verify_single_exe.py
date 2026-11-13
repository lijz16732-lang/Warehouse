# -*- coding: utf-8 -*-
"""exe 级验收单实例：D 盘 exe 启动两次，第二个进程应自动退出。"""
import os
import subprocess
import sys
import time

import ctypes
import ctypes.wintypes as wt

EXE = r"D:\仓库管理工具\仓管家-仓库管理系统.exe"
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND


def wait_window(timeout=40):
    """等主窗口出现（标题含 仓管家 的可见顶层窗口）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, None)
        # FindWindow 顺序枚举不可控，用 EnumWindows 匹配标题
        found = []

        ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def cb(h, _l):
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, buf, 256)
                if "仓管家" in buf.value and "设置" not in buf.value:
                    found.append(h)
                    return False
            return True

        user32.EnumWindows(ENUMPROC(cb), 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def pids_of(exe_name="仓管家-仓库管理系统.exe"):
    import re
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq 仓管家-仓库管理系统.exe",
                          "/FO", "CSV"], capture_output=True).stdout
    txt = out.decode("gbk", "ignore")
    return re.findall(r'"仓管家-仓库管理系统\.exe","(\d+)"', txt)


p1 = subprocess.Popen([EXE])
print("实例1 pid:", p1.pid)
hwnd = wait_window()
print("主窗口:", hwnd)
assert hwnd, "实例1 主窗口没出现"
time.sleep(3)                    # 等托盘初始化（启动 900ms 后创建）

p2 = subprocess.Popen([EXE])
print("实例2 pid:", p2.pid)
# 实例2 应在几秒内自行退出
deadline = time.time() + 20
exited = False
while time.time() < deadline:
    if p2.poll() is not None:
        exited = True
        break
    time.sleep(0.3)
print("实例2 退出:", exited, "code:", p2.poll())

left = pids_of()
print("剩余进程:", left)
ok = exited and p1.poll() is None
print("RESULT:", "PASS" if ok else "FAIL")

# 清理：让实例1 正常退出
if hwnd:
    import ctypes as c
    WM_CLOSE = 0x0010
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
try:
    p1.wait(timeout=15)
except Exception:
    p1.kill()
sys.exit(0 if ok else 1)
