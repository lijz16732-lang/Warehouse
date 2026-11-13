# -*- coding: utf-8 -*-
"""Windows 托盘图标（纯 ctypes 实现，不引入第三方依赖）。

Tk 自己没有托盘能力，pystray / pywin32 又会给打包体积加几 MB。这里直接调
Shell_NotifyIconW：注册一个隐藏窗口接收鼠标消息，消息循环跑在独立线程，
菜单命令通过 queue 交回 Tk 主线程处理（Tk 不是线程安全的，任何界面操作
都必须在主线程执行）。

用法：
    tray = TrayIcon("仓管家", icon_path, on_show=..., on_settings=...,
                    on_exit=...)
    tray.start()          # 非阻塞，失败静默（没有托盘也不影响主程序）
    tray.stop()
"""

import ctypes
import ctypes.wintypes as wt
import os
import queue
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

WM_APP = 0x8000
WM_TRAY_CALLBACK = WM_APP + 20
WM_APP_ACTIVATE = WM_APP + 21   # wm/single.py 用它唤起已运行实例
TRAY_WIN_TITLE = "WmTray_CGM"   # 供 FindWindowW 寻址（单实例激活）
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_NULL = 0x0000

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_LEFTALIGN = 0x0000

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
SM_CXSMICON = 49
SM_CYSMICON = 50

CS_DBLCLKS = 0x0008

# 菜单项 id → 回调名
CMD_SHOW, CMD_SETTINGS, CMD_EXIT = 1, 2, 3


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD),
                ("Data3", wt.WORD), ("Data4", ctypes.c_byte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wt.HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT,
                             wt.WPARAM, wt.LPARAM)
WNDPROC_PTR = ctypes.c_void_p

LRESULT = ctypes.c_ssize_t

# 必须显式声明参数类型：不声明时 ctypes 默认按 C int 传，64 位下
# LPARAM / 指针会被判成 "int too long to convert"（wndproc 里直接抛异常）。
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wt.WORD
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.AppendMenuW.restype = wt.BOOL
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wt.HWND,
                                  ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.GetCursorPos.restype = wt.BOOL
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND,
                               wt.UINT, wt.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT,
                              ctypes.c_int, ctypes.c_int, wt.UINT]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadIconW.argtypes = [wt.HINSTANCE, wt.LPCWSTR]
user32.LoadIconW.restype = wt.HICON
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD,
                                      ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wt.BOOL

_LRESULT_OK = 0


class TrayIcon(object):
    """托盘图标 + 右键菜单。所有回调都在调用方传入的队列里排队。"""

    def __init__(self, title, icon_path=None, tooltip=None, on_show=None,
                 on_settings=None, on_exit=None, master=None):
        self.title = title or "仓管家"
        self.icon_path = icon_path
        self.tooltip = (tooltip or title or "仓管家")[:120]
        self.on_show = on_show
        self.on_settings = on_settings
        self.on_exit = on_exit
        self.master = master              # Tk root（保留引用，命令走队列）
        self.queue = queue.Queue()        # 托盘线程 → 主线程的命令队列
        self.hwnd = None
        self.hicon = None
        self._thread = None
        self._ready = threading.Event()
        self._wndproc = None              # 必须保持引用，否则被 GC 后回调崩
        self._stop = False
        self._cls = "WmTrayWnd_%d_%d" % (id(self), os.getpid())
        self.ok = False

    # ------------------------------------------------------------ 生命周期
    def start(self):
        """启动托盘线程；失败返回 False（不影响主程序运行）。"""
        if self._thread is not None:
            return self.ok
        self._thread = threading.Thread(target=self._run, name="tray",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        return self.ok

    def stop(self):
        if self.hwnd:
            try:
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        self._thread = None
        self.ok = False

    def balloon(self, text, title="仓管家"):
        """弹一个气泡提示（Win10+ 显示为通知）。"""
        if not self.hwnd:
            return
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfo = (text or "")[:250]
        nid.szInfoTitle = (title or "仓管家")[:60]
        nid.dwInfoFlags = 0x1                      # NIIF_INFO
        try:
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    # ------------------------------------------------------------ 线程内部
    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            self._wndproc = WNDPROC(self._on_message)
            wc = WNDCLASSW()
            wc.style = CS_DBLCLKS
            wc.lpfnWndProc = ctypes.cast(self._wndproc, WNDPROC_PTR)
            wc.hInstance = hinst
            wc.lpszClassName = self._cls
            if not user32.RegisterClassW(ctypes.byref(wc)):
                self._ready.set()
                return
            self.hwnd = user32.CreateWindowExW(
                0, self._cls, TRAY_WIN_TITLE, 0, 0, 0, 0, 0,
                None, None, hinst, None)
            if not self.hwnd:
                self._ready.set()
                return
            self._load_icon()
            nid = self._nid()
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAY_CALLBACK
            nid.hIcon = self.hicon
            nid.szTip = self.tooltip
            self.ok = bool(shell32.Shell_NotifyIconW(NIM_ADD,
                                                     ctypes.byref(nid)))
            self._ready.set()
            if not self.ok:
                user32.DestroyWindow(self.hwnd)
                return
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self.ok = False
            self._ready.set()

    def _load_icon(self):
        size = user32.GetSystemMetrics(SM_CXSMICON) or 16
        if self.icon_path and os.path.exists(self.icon_path):
            self.hicon = user32.LoadImageW(
                None, self.icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if not self.hicon:
            # 没有 ico 就退到系统默认应用图标（IDI_APPLICATION = 32512）
            self.hicon = user32.LoadIconW(
                None, ctypes.cast(ctypes.c_void_p(32512), wt.LPCWSTR))

    def _on_message(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY_CALLBACK:
                low = int(lparam) & 0xFFFF
                if low in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self._post("show")
                elif low == WM_RBUTTONUP:
                    self._menu()
                return 0
            if msg == WM_COMMAND:
                cmd = int(wparam) & 0xFFFF
                if cmd == CMD_SHOW:
                    self._post("show")
                elif cmd == CMD_SETTINGS:
                    self._post("settings")
                elif cmd == CMD_EXIT:
                    self._post("exit")
                return 0
            if msg == WM_APP_ACTIVATE:
                # 第二个实例启动 → 单实例模块发来激活消息，恢复主窗口
                self._post("show")
                return 0
            if msg == WM_CLOSE:
                nid = self._nid()
                try:
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                except Exception:
                    pass
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            user32.AppendMenuW(menu, MF_STRING, CMD_SHOW, "显示主窗口")
            user32.AppendMenuW(menu, MF_STRING, CMD_SETTINGS, "设置…")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, CMD_EXIT, "退出")
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(self.hwnd)
            cmd = user32.TrackPopupMenu(
                menu, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_LEFTALIGN,
                pt.x, pt.y, 0, self.hwnd, None)
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            if cmd:
                self._menu_cmd(int(cmd))
        finally:
            user32.DestroyMenu(menu)

    def _menu_cmd(self, cmd):
        if cmd == CMD_SHOW:
            self._post("show")
        elif cmd == CMD_SETTINGS:
            self._post("settings")
        elif cmd == CMD_EXIT:
            self._post("exit")

    # ------------------------------------------------------------ 回调派发
    def _post(self, action):
        """把动作塞进队列，由主线程 poll() 取走执行。

        Tk 不是线程安全的，托盘线程里连 root.after 都不能调（会触发
        "main thread is not in main loop"），所以统一走队列。
        """
        self.queue.put(action)

    def poll(self):
        """主线程定期调用：执行托盘菜单点下的命令。返回本次处理的动作列表。"""
        done = []
        while True:
            try:
                action = self.queue.get_nowait()
            except queue.Empty:
                break
            done.append(action)
            cb = {"show": self.on_show, "settings": self.on_settings,
                  "exit": self.on_exit}.get(action)
            if cb is None:
                continue
            try:
                cb()
            except Exception:
                pass
        return done
