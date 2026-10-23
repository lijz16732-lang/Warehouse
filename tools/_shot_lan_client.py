# -*- coding: utf-8 -*-
"""截图：客户端状态下打开「局域网共享」窗口（① 区橙色提示 + ② 当前角色标签）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.lanui import LanDialog  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

wapp.messagebox.showwarning = lambda *a, **k: None
wapp.messagebox.showinfo = lambda *a, **k: None
wapp.messagebox.showerror = lambda *a, **k: None

TMP1 = tempfile.mkdtemp(prefix="wm_shot_h_")
wapp.app_dir = lambda: TMP1
Store(os.path.join(TMP1, "data", "warehouse.db")).close()
root1 = tk.Tk()
host = wapp.App(root1)
host.store.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                          "qty": 5, "price": 88.0}
                        for i in range(1, 4)])
host.load_data()
root1.update()
host.start_lan_host(18981, "246810")

TMP2 = tempfile.mkdtemp(prefix="wm_shot_c_")
wapp.app_dir = lambda: TMP2
Store(os.path.join(TMP2, "data", "warehouse.db")).close()
root2 = tk.Tk()
client = wapp.App(root2)
root2.geometry("1200x760+60+60")
root2.update()
client.connect_lan("127.0.0.1", 18981, "246810")

dlg = LanDialog(root2, client)
root2.update()
root2.after(400, lambda: None)
root2.update()
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
screenshot.capture_window("局域网共享", os.path.join(OUT, "lan_client_disabled.png"))
print("saved")

client.disconnect_lan()
client.stop_lan_host()
host.stop_lan_host()
root1.destroy()
root2.destroy()
