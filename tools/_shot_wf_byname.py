# -*- coding: utf-8 -*-
"""截图：推进弹窗自动带出经手人名字。"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
import tkinter as tk
from wm import app as wapp
from wm import workflow as wfmod
from wm.store import Store

TMP = tempfile.mkdtemp(prefix="wf_by_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
wfmod.messagebox.showinfo = lambda *a, **k: None
root = tk.Tk(); root.withdraw()
app = wapp.App(root)
top = tk.Toplevel(root); top.geometry("900x420+80+60")
tab = wfmod.WorkflowTab(top, app); tab.pack(fill="both", expand=True)
root.deiconify(); root.update_idletasks(); root.update()
store = app.store
stages = store.wf_stages()
wid, no = store.wf_create("水獭拭", kind="修复", by="3+3")
store.wf_advance(wid, "3+3", "")   # 推到第 2 站，经手人 3+3
tab.refresh_rows(); root.update()
rec = [r for r in store.wf_list("active", "") if int(r["id"]) == wid][0]
dlg = wfmod.FlowDialog(top, tab, rec, True)
dlg.geometry("+90+90")
try:
    dlg.attributes("-alpha", 1.0); dlg.attributes("-topmost", True)
except Exception: pass
root.update()
screenshot = __import__("tools.screenshot", fromlist=["capture_window"])
screenshot.capture_window(dlg.title(), os.path.join(OUT, "_wf_byname.png"))
dlg.destroy(); root.destroy()
print("done")
