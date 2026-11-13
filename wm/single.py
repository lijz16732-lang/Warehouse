# -*- coding: utf-8 -*-
"""单实例保护：程序只允许跑一份，重复启动时唤起已有实例。

背景：主窗口可以「最小化/关闭到托盘」隐藏运行，进程并不退出。用户此时再点
一次桌面图标，就会多开一个新进程 —— 托盘多一个图标、任务栏多一个同款窗口，
两边还同时写同一个数据库。这里用命名互斥量做单实例闸门：

  · 第一个实例    CreateMutex 成功持有，正常运行；
  · 后续的启动    GetLastError() == ERROR_ALREADY_EXISTS → 给已有实例的
    托盘窗口发一条激活消息（托盘线程收到后把主窗口恢复），本进程直接退出。

托盘被用户关掉时，退回按窗口标题模糊匹配 + ShowWindow 恢复。
互斥量随进程退出自动释放，不需要显式清理。
"""

import ctypes
import ctypes.wintypes as wt

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

MUTEX_NAME = r"Local\WarehouseManager_Single_9f3c"
TRAY_WIN_TITLE = "WmTray_CGM"          # 与 wm/tray.py 的托盘窗口标题一致
WM_APP_ACTIVATE = 0x8000 + 21          # WM_APP+21：请显示主窗口
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9

kernel32.CreateMutexW.argtypes = [wt.LPCWSTR, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
# 注意：不能直接调 kernel32.GetLastError() —— ctypes 内部调用会覆盖线程
# 最后错误值，必须用 use_last_error=True + ctypes.get_last_error()。
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.ShowWindowAsync.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindowAsync.restype = wt.BOOL
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL

ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [ENUMPROC, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL

# 互斥量句柄保持进程级引用（进程活着就要一直持有）
_mutex = None


def first_instance():
    """是否允许本进程继续启动。

    True  = 我是第一个实例，照常启动；
    False = 已有实例在运行，本进程不要启动（已通知它显示主窗口）。
    """
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        activate_existing()
        return False
    return True


def activate_existing():
    """唤起已运行的实例：优先托盘窗口消息，失败则按标题找主窗口。"""
    hwnd = user32.FindWindowW(None, TRAY_WIN_TITLE)
    if hwnd:
        user32.PostMessageW(hwnd, WM_APP_ACTIVATE, 0, 0)
        return True
    # 托盘没开（设置里关了）时的兜底：枚举顶层可见窗口按标题匹配
    found = []

    def _cb(h, _l):
        try:
            if not user32.IsWindowVisible(h):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if "仓管家" in buf.value:
                found.append(h)
                return False
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(ENUMPROC(_cb), 0)
    except Exception:
        pass
    if found:
        user32.ShowWindowAsync(found[0], SW_RESTORE)
        user32.SetForegroundWindow(found[0])
        return True
    return False
