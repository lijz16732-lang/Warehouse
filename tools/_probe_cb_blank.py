# -*- coding: utf-8 -*-
"""复现：设置页各下拉框打开后 textvariable 有值但显示空白？"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from tkinter import ttk
from wm import app as wapp
from wm.store import Store

TMP = tempfile.mkdtemp(prefix="probe_cb_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()

root = tk.Tk(); app = wapp.App(root); root.update()
app.open_appearance(); root.update()
win = app._settings_win

def walk(w, out):
    out.append(w)
    for c in w.winfo_children():
        walk(c, out)

for key in ("look", "format", "general", "backup", "system", "code"):
    win._show_page(key); root.update()
    ws = []; walk(win, ws)
    for w in ws:
        if isinstance(w, ttk.Combobox):
            try:
                var_val = str(w.cget("textvariable"))
                tv = root.globalgetvar(var_val) if var_val else "?"
            except Exception:
                tv = "?"
            print("page=%-8s get()=%-30r var=%r mapped=%s viewable=%s"
                  % (key, w.get(), tv, w.winfo_ismapped(), w.winfo_viewable()))
root.destroy()
print("OK")
