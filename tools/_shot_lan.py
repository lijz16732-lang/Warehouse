# -*- coding: utf-8 -*-
"""局域网共享窗口：布局检查 + 截图（v1.11.0）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


wapp.messagebox.showwarning = lambda *a, **k: None
wapp.messagebox.showinfo = lambda *a, **k: None

TMP = tempfile.mkdtemp(prefix="wm_lanshot_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                         "model": "M-%d" % i, "qty": 5,
                                         "price": 100.0} for i in range(1, 4)])
app.load_data()
root.geometry("1300x820+60+40")
root.update()

app.start_lan_host(18767, "112233")
app.open_lan()
root.update()
dlg = None
for w in root.winfo_children():
    if isinstance(w, tk.Toplevel) and w.title() == "局域网共享":
        dlg = w
check("局域网共享窗口已打开", dlg is not None)
if dlg:
    dlg.update_idletasks()
    check("内容高度不超过窗口（不被截断）",
          dlg.winfo_reqheight() <= 720, dlg.winfo_reqheight())
    check("窗口标题带共享中状态",
          "共享" in dlg.lbl_state.cget("text") or "主机" in dlg.lbl_state.cget("text"),
          dlg.lbl_state.cget("text"))
    check("显示本机地址", "本机地址" in dlg.lbl_ips.cget("text"), dlg.lbl_ips.cget("text"))
    check("按钮为「停止共享」", dlg.btn_host.cget("text") == "停止共享",
          dlg.btn_host.cget("text"))
    root.update()
    screenshot.capture_window("局域网共享", os.path.join(OUT, "lan_dialog.png"))
    dlg.destroy()

app.stop_lan_host()
root.destroy()
print("\n失败项：%s" % (FAILS or "无"))
sys.exit(1 if FAILS else 0)
