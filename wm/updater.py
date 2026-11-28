# -*- coding: utf-8 -*-
"""电脑端云更新（v1.45.7）。

启动后台静默检查 GitHub 上的 deploy/version.json：
- 有新版本 → 状态栏提示 + 弹窗，用户确认后下载（校验 md5）
- 替换方式：下载为「<exe>.new」→ 写临时 bat（退出后删除旧 exe、
  改名新 exe、重新启动）→ 启动 bat → 本进程退出
- 检查失败（断网/没有代理/超时）一律静默，绝不影响正常使用

检查地址与发布侧 tools/release.py 约定一致：
https://raw.githubusercontent.com/<repo>/main/deploy/version.json
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import urllib.request
from tkinter import messagebox

RAW_URL = ("https://raw.githubusercontent.com/lijz16732-lang/Warehouse/"
           "main/deploy/version.json")
TIMEOUT = 8            # 秒：检查一次最长等待，超时即放弃（静默）


def _md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version_lt(a, b):
    """版本号比较：'1.9.1' < '1.10.0' 按数字逐段比（不是字符串序）。"""
    def parts(v):
        out = []
        for seg in str(v).split("."):
            num = ""
            for ch in seg:
                if ch.isdigit():
                    num += ch
                else:
                    break
            out.append(int(num or 0))
        return out
    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa < pb


def fetch_update_info(timeout=TIMEOUT):
    """拉 version.json；失败返回 None（静默）。"""
    try:
        req = urllib.request.Request(RAW_URL)
        req.add_header("User-Agent", "cangguanjia-updater")
        handlers = []
        px = os.environ.get("CGM_UPDATE_PROXY")
        if px:
            handlers.append(urllib.request.ProxyHandler(
                {"http": px, "https": px}))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(req, timeout=timeout) as r:
            info = json.loads(r.read().decode("utf-8"))
        return info if isinstance(info, dict) else None
    except Exception:
        return None


def new_exe_info(info):
    """version.json 里有比我新的 exe 版本 → 返回 dict，否则 None。"""
    from .constants import APP_VERSION
    exe = (info or {}).get("exe") or {}
    ver = str(exe.get("version") or "")
    if not ver or not exe.get("url"):
        return None
    if _version_lt(APP_VERSION, ver):
        return exe
    return None


def check_async(app):
    """启动后调用：后台线程检查，有新版时回到主线程弹窗。"""
    def work():
        info = fetch_update_info()
        if not info:
            return
        exe = new_exe_info(info)
        if exe:
            app._ui(lambda: _offer_update(app, exe))
    t = threading.Thread(target=work, daemon=True)
    t.start()


def _offer_update(app, exe):
    try:
        app._status("发现新版本 %s：可到「数据」菜单更新" % exe.get("version"))
    except Exception:
        pass
    if messagebox.askyesno(
            "发现新版本",
            "当前版本：%s\n最新版本：%s\n\n%s\n\n现在下载并安装新版本吗？\n"
            "（下载完成后会自动重启程序）"
            % (_cur_version(), exe.get("version"),
               exe.get("notes") or ""),
            parent=app.root):
        do_update(app, exe)


def _cur_version():
    from .constants import APP_VERSION
    return APP_VERSION


def do_update(app, exe, progress=None):
    """下载新 exe（校验 md5）→ bat 延迟替换 → 重启。失败弹错并留在旧版。"""
    url = exe.get("url")
    if not url:
        return
    app._status("正在下载新版本 %s …" % exe.get("version"))
    try:
        handlers = []
        px = os.environ.get("CGM_UPDATE_PROXY")
        if px:
            handlers.append(urllib.request.ProxyHandler(
                {"http": px, "https": px}))
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "cangguanjia-updater")
        tmp = _exe_path() + ".new"
        with opener.open(req, timeout=120) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                if progress:
                    progress()
        want = str(exe.get("md5") or "").lower()
        got = _md5_of(tmp)
        if want and got != want:
            os.remove(tmp)
            raise IOError("文件校验不一致（%s ≠ %s）" % (got, want))
        _spawn_replacer(tmp)
        # 库已由 WAL 落盘；直接退出，bat 会接手替换并重启
        os._exit(0)
    except Exception as e:
        messagebox.showerror("更新失败",
                             "下载或替换新版本失败，当前版本继续可用。\n\n%s" % e,
                             parent=app.root)
        try:
            app._status("更新失败：请检查网络后重试")
        except Exception:
            pass


def _exe_path():
    # PyInstaller onefile：sys.executable 就是安装目录里的 exe
    return os.path.abspath(sys.executable)


def _spawn_replacer(new_path):
    """写一个 bat：等 1 秒 → 删旧 exe → 新 exe 改名 → 重新启动。

    运行中的 exe 不能覆盖自己，所以交给 bat 在本进程退出后替换。
    bat 用 GBK 编码写（cmd 默认代码页），中文路径不会乱码。
    """
    old = _exe_path()
    bat = old + ".update.bat"
    script = (
        "@echo off\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"           # 等主进程退出
        "del /f /q \"{old}\"\r\n"
        "move /y \"{new}\" \"{old}\"\r\n"
        "start \"\" \"{old}\"\r\n"
        "del /f /q \"%~f0\"\r\n"
    ).format(old=old, new=new_path)
    with open(bat, "w", encoding="gbk", newline="") as f:
        f.write(script)
    subprocess.Popen(["cmd", "/c", bat], close_fds=True)
