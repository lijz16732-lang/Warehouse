# -*- coding: utf-8 -*-
"""打包产物托盘验收：确认 exe 里「关闭时最小化到托盘」真的生效。

流程：干净目录 + 预置 settings.json（close_to_tray=true）→ 启动 exe →
找到主窗口并发送 WM_CLOSE → 进程应仍然存活、主窗口不可见、
且能看到托盘用的隐藏窗口（类名 WmTrayWnd*）。
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "仓管家-仓库管理系统.exe")

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
WM_CLOSE = 0x0010

ok = True


def chk(name, cond, detail=""):
    global ok
    if not cond:
        ok = False
    print("%s %s %s" % ("[OK] " if cond else "[FAIL]", name, detail))


def windows_all():
    """全部顶层窗口 [(hwnd, 类名, 标题, 是否可见)]。"""
    out = []
    CB = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        tbuf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, tbuf, 256)
        out.append((hwnd, buf.value, tbuf.value,
                    bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(CB(cb), 0)
    return out


# PyInstaller onefile 会先起引导进程，真正的界面在子进程里，所以按
# 「窗口」而不是 pid 认目标；启动前先记下已有窗口，只认新出现的。
before = {h for h, _c, _t, _v in windows_all()}

tmp = tempfile.mkdtemp(prefix="cgm_tray_")
dst = os.path.join(tmp, os.path.basename(EXE))
shutil.copy2(EXE, dst)
data_dir = os.path.join(tmp, "data")
os.makedirs(data_dir, exist_ok=True)
with open(os.path.join(data_dir, "settings.json"), "w", encoding="utf-8") as f:
    json.dump({"close_to_tray": True, "min_to_tray": False}, f)
chk("exe 复制到干净目录并预置设置", os.path.isfile(dst))

p = subprocess.Popen([dst], cwd=tmp)
main_hwnd = None
tray_cls = None
t0 = time.time()
while time.time() - t0 < 30:
    for hwnd, cls, title, vis in windows_all():
        if hwnd in before:
            continue
        if cls.startswith("WmTrayWnd"):
            tray_cls = cls
        if vis and "仓管家" in title:
            main_hwnd = hwnd
    if main_hwnd and tray_cls:
        break
    time.sleep(0.4)

chk("进程存活", p.poll() is None, "pid=%s" % p.pid)
chk("主窗口出现", main_hwnd is not None, "%.1f s" % (time.time() - t0))
chk("托盘隐藏窗口已创建（托盘图标已挂上）", tray_cls is not None, tray_cls or "")

if main_hwnd:
    user32.PostMessageW(main_hwnd, WM_CLOSE, 0, 0)
    time.sleep(2.5)
    chk("点关闭后进程仍在运行（最小化到托盘）", p.poll() is None,
        "exit=%s" % p.poll())
    vis = [w for w in windows_all()
           if w[0] not in before and w[3] and "仓管家" in w[2]]
    chk("主窗口已隐藏", not vis, [w[2] for w in vis])

try:
    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                   capture_output=True, timeout=10)
except Exception:
    try:
        p.kill()
    except Exception:
        pass
time.sleep(1.0)
left = [w for w in windows_all() if w[0] not in before and "仓管家" in w[2]]
chk("进程与窗口已清理", not left, [w[2] for w in left])
shutil.rmtree(tmp, ignore_errors=True)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
