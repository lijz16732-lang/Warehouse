# -*- coding: utf-8 -*-
"""排查：客户端模式下，「本机作为主机」这一区是否可见 / 可用。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.lanui import LanDialog  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

wapp.messagebox.showwarning = lambda *a, **k: None
wapp.messagebox.showinfo = lambda *a, **k: None
wapp.messagebox.showerror = lambda *a, **k: None

# 主机实例
TMP1 = tempfile.mkdtemp(prefix="wm_h_")
wapp.app_dir = lambda: TMP1
Store(os.path.join(TMP1, "data", "warehouse.db")).close()
root1 = tk.Tk()
host = wapp.App(root1)
host.store.insert_many([blank_record() | {"code": "WL-00001", "brand": "ABB",
                                          "qty": 5, "price": 88.0}])
host.load_data()
root1.update()
ok, msg = host.start_lan_host(18966, "246810")
print("主机开启:", ok, msg)

# 客户端实例
TMP2 = tempfile.mkdtemp(prefix="wm_c_")
wapp.app_dir = lambda: TMP2
Store(os.path.join(TMP2, "data", "warehouse.db")).close()
root2 = tk.Tk()
client = wapp.App(root2)
root2.geometry("1200x760+60+60")
root2.update()
ok, msg = client.connect_lan("127.0.0.1", 18966, "246810")
print("客户端连接:", ok, msg, "| mode:", client.lan_mode)

dlg = LanDialog(root2, client)
root2.update()

print("\n客户端模式下的局域网窗口：")
print("  标题状态标签:", dlg.lbl_state.cget("text"))
print("  ① 主机按钮:", dlg.btn_host.cget("text"),
      "| state =", dlg.btn_host.cget("state"),
      "| 可见:", bool(dlg.btn_host.winfo_ismapped()))
print("  ① 端口输入可编辑:", dlg.var_port.get() or "(空)",
      "| entry state =", dlg.btn_host.master.winfo_children()[0].cget("state")
      if False else "")
print("  ① 连接码:", dlg.var_code.get())
print("  ① 提示:", dlg.lbl_host_msg.cget("text"))
print("  ② 连接按钮 state:", dlg.btn_conn.cget("state"))
print("  「断开 / 回到本机」 state:", dlg.btn_disconn.cget("state"))
print("  窗口尺寸:", dlg.winfo_width(), "x", dlg.winfo_height())
print("  屏幕高度:", root2.winfo_screenheight())

# 关键：在客户端状态下点「开启共享」，看能不能切成主机
print("\n在客户端状态下点「开启共享」…")
dlg.var_port.set("18967")
dlg.var_code.set("135790")
dlg.toggle_host()
root2.update()
print("  点完 mode:", client.lan_mode, "| running:",
      client.lan_status()["running"], "| store:", type(client.store).__name__)
print("  按钮文案:", dlg.btn_host.cget("text"))
print("  提示:", dlg.lbl_host_msg.cget("text"))
print("  本机数据条数:", len(client.records))

client.stop_lan_host()
host.stop_lan_host()
root1.destroy()
root2.destroy()
