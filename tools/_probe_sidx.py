# -*- coding: utf-8 -*-
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from wm import app as wapp
from wm.store import Store
TMP = tempfile.mkdtemp(prefix="probe_si_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
root = tk.Tk(); app = wapp.App(root); root.update()
app.open_appearance("look"); root.update()
win = app._settings_win
root.update()
idx = win._search_index
print("index size:", len(idx))
for k, t, c in idx[:12]:
    print(" ", k, "|", t[:30])
root.destroy()
