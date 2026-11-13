# -*- coding: utf-8 -*-
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from wm import app as wapp
from wm.store import Store
TMP = tempfile.mkdtemp(prefix="probe_sr2_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
root = tk.Tk(); app = wapp.App(root); root.update()
app.open_appearance("look"); root.update()
win = app._settings_win; root.update()
fn = win._search_do
for name, cell in zip(fn.__code__.co_freevars, fn.__closure__ or []):
    v = cell.cell_contents
    p = ""
    try:
        p = str(v)
    except Exception:
        p = repr(v)
    print("%-12s %s" % (name, p[:90]))
root.destroy()
