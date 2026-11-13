# -*- coding: utf-8 -*-
"""默认开 look 页 → 再切到 format 页：创建时被隐藏的下拉是否显示空白。"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from tkinter import ttk
from wm import app as wapp
from wm.store import Store
import screenshot

TMP = tempfile.mkdtemp(prefix="probe_lbl_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
out = os.path.join(ROOT, ".tmpdbg"); os.makedirs(out, exist_ok=True)

root = tk.Tk(); app = wapp.App(root); root.update()
app.open_appearance("look"); root.update()      # 用户真实路径：默认外观页
win = app._settings_win
win.title("W M CBL 探针"); root.update()

def walk(w, out_l):
    out_l.append(w)
    for c in w.winfo_children():
        walk(c, out_l)

win._show_page("format"); root.update()
ws = []; walk(win, ws)
for w in ws:
    if isinstance(w, ttk.Combobox) and w.winfo_viewable():
        print("切换后 get=%r" % w.get())
screenshot.capture_window("W M CBL 探针", os.path.join(out, "cbl_switch.png"))
root.destroy()
print("done")
