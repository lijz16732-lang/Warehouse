# -*- coding: utf-8 -*-
"""截图：客户端「历史连接」下拉（连接成功过的主机一键填入）。"""
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
from wm.store import Store, blank_record  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_shot_hist_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([blank_record() | {"code": "WL-00001", "brand": "ABB",
                                         "qty": 5, "price": 88.0}])
app.load_data()
root.update()
app._add_lan_history("192.168.1.10", 8765, "246810")
app._add_lan_history("192.168.50.20", 8765, "135790")
app._add_lan_history("192.168.1.10", 8765, "246810")   # 模拟重复连接 → 置顶

dlg = LanDialog(root, app)
root.update()
root.after(300, lambda: None)
root.update()
root.update_idletasks()
root.after(200, lambda: None)
root.update()
dlg.canvas.yview_moveto(0.0)      # 顶部完整视图：① 主机区 + ② 客户端区都应可见
root.update()
root.after(300, lambda: None)
root.update()
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
screenshot.capture_window("局域网共享", os.path.join(OUT, "lan_history.png"))
print("saved", root.geometry())

dlg.destroy()
root.destroy()
