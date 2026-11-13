# -*- coding: utf-8 -*-
"""切到文件格式页：截图A（原始）→ 强制重设值 → 截图B（修复后对比）。"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from tkinter import ttk
from wm import app as wapp
from wm.store import Store
import screenshot

TMP = tempfile.mkdtemp(prefix="probe_cbs_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
out = os.path.join(ROOT, ".tmpdbg"); os.makedirs(out, exist_ok=True)

root = tk.Tk(); app = wapp.App(root); root.update()
app.open_appearance("format"); root.update()
win = app._settings_win
win.title("W M CB探针")
root.update()

def walk(w, out_l):
    out_l.append(w)
    for c in w.winfo_children():
        walk(c, out_l)

ws = []; walk(win, ws)
cbs = [w for w in ws if isinstance(w, ttk.Combobox)]
screenshot.capture_window("W M CB探针", os.path.join(out, "cb_before.png"))

def resync():
    for cb in cbs:
        try:
            v = cb.get()
            if v:
                cb.set(v)      # Tcl 写 trace 每次都触发，即使同值
        except Exception:
            pass
    win.update_idletasks()

resync(); root.update()
screenshot.capture_window("W M CB探针", os.path.join(out, "cb_after.png"))
root.destroy()
print("shots saved")
