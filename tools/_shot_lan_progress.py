# -*- coding: utf-8 -*-
"""截图：连接主机过程中的进度条。"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.lanui import LanDialog  # noqa: E402
from wm.store import Store  # noqa: E402

wapp.messagebox.showwarning = lambda *a, **k: None
wapp.messagebox.showinfo = lambda *a, **k: None
wapp.messagebox.showerror = lambda *a, **k: None

TMP = tempfile.mkdtemp(prefix="wm_shot_pb_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
root = tk.Tk()
app = wapp.App(root)
root.geometry("1200x760+60+60")
root.update()

dlg = LanDialog(root, app)
root.update()
dlg.var_host.set("10.255.255.1")   # 连不上的地址，让进度条多转一会儿
dlg.var_cport.set("8765")
dlg.var_ccode.set("123456")
dlg.connect()
root.update()
deadline = time.time() + 3
while time.time() < deadline:      # 转 3 秒让进度条动起来
    root.update()
    time.sleep(0.02)
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
screenshot.capture_window("局域网共享", os.path.join(OUT, "lan_connect_progress.png"))
print("saved")
deadline = time.time() + 12
while dlg._conn_busy and time.time() < deadline:
    root.update()
    time.sleep(0.02)
dlg.destroy()
root.destroy()
