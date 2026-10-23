# -*- coding: utf-8 -*-
"""截图：主机模式下「已连接电脑」的新功能（移除连接 / 加入黑名单 / 黑名单管理）。"""
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
root1.geometry("1200x760+80+40")
host = wapp.App(root1)
host.store.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                          "qty": 5, "price": 88.0}
                        for i in range(1, 4)])
host.load_data()
root1.update()
host.start_lan_host(18991, "135790")

TMP2 = tempfile.mkdtemp(prefix="wm_shot_c_")
wapp.app_dir = lambda: TMP2
Store(os.path.join(TMP2, "data", "warehouse.db")).close()
root2 = tk.Tk()
client = wapp.App(root2)
client.connect_lan("127.0.0.1", 18991, "135790")

dlg = LanDialog(root1, host)
root1.update()
# 模拟主机端已有第二台历史客户端 + 一条黑名单记录，画面更真实
dlg.tree.insert("", "end", iid="192.168.50.20",
                values=("客户端乙", "192.168.50.20", "5 分钟前", "只读"))
dlg.tree.selection_set("127.0.0.1")
root1.update()
root1.after(300, lambda: None)
root1.update()
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
screenshot.capture_window("局域网共享", os.path.join(OUT, "lan_host_kick.png"))

# 黑名单管理窗口（真实调用，往配置里塞两条）
wapp.messagebox.showinfo = lambda *a, **k: None
host.lan_block_client("192.168.50.30", "陌生电脑")
dlg.manage_blocked()
root1.update()
root1.after(300, lambda: None)
root1.update()
screenshot.capture_window("黑名单管理", os.path.join(OUT, "lan_blacklist.png"))

print("saved")

client.disconnect_lan()
root2.destroy()
host.stop_lan_host()
root1.destroy()
