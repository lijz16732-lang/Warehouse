# -*- coding: utf-8 -*-
"""验证（v1.11.3）：连接失败不卡界面。

对不存在的 IP 发起「连接」：探测在后台线程做（最多 8 秒），
期间界面事件循环照常跳动，超时后进度条收起、红色错误提示。
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.lanui import LanDialog  # noqa: E402
from wm.constants import CLR_DANGER  # noqa: E402
from wm.constants import CLR_DANGER  # noqa: E402
from wm.store import Store  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


wapp.messagebox.showwarning = lambda *a, **k: None
wapp.messagebox.showinfo = lambda *a, **k: None
wapp.messagebox.showerror = lambda *a, **k: None

TMP = tempfile.mkdtemp(prefix="wm_err_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
root = tk.Tk()
app = wapp.App(root)
root.geometry("1200x760+60+60")
root.update()

dlg = LanDialog(root, app)
root.update()
dlg.var_host.set("10.255.255.1")   # 不可路由地址，必然连不上
dlg.var_cport.set("8765")
dlg.var_ccode.set("123456")

t0 = time.time()
ticks = {"n": 0}


def pump():
    """连接期间持续跳动界面事件循环，统计跳了多少下（卡住的话接近 0）。"""
    ticks["n"] += 1
    if ticks["n"] < 1000 and dlg._conn_busy:
        root.after(30, pump)


dlg.connect()
root.update()
pump()

deadline = time.time() + 20
while dlg._conn_busy and time.time() < deadline:
    root.update()
    time.sleep(0.02)
elapsed = time.time() - t0
root.update()

check("连接期间界面事件循环正常跳动（不卡死）",
      ticks["n"] > 20, ticks["n"])
check("探测在后台完成（耗时约 8 秒而非阻塞主线程）",
      6 < elapsed < 20, "%.1fs" % elapsed)
check("进度条已收起", str(dlg.pb.winfo_manager()) == "",
      dlg.pb.winfo_manager())
check("按钮恢复可点", str(dlg.btn_conn.cget("state")) == "normal",
      dlg.btn_conn.cget("state"))
check("红色错误提示写明连不上",
      "连不上主机" in dlg.lbl_cli_msg.cget("text")
      and dlg.lbl_cli_msg.cget("fg") == CLR_DANGER,
      dlg.lbl_cli_msg.cget("text")[:60])
check("本机仍是独立模式、数据可用",
      app.lan_mode == "off" and app.store is not None and
      len(app.records) == 0)
check("_conn_busy 已复位", dlg._conn_busy is False)

dlg.destroy()
root.destroy()
print("\n失败项：%s" % (FAILS or "无"))
sys.exit(1 if FAILS else 0)
