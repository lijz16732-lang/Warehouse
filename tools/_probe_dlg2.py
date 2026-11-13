# -*- coding: utf-8 -*-
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from wm import app as wapp
from wm.store import Store
TMP = tempfile.mkdtemp(prefix="pdlg2_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
root = tk.Tk(); app = wapp.App(root); root.update()
app.start_lan_host(port=18767)
app.open_appearance("lan"); root.update()
win = app._settings_win
ws=[]
def walk(w,o):
    o.append(w)
    for c in w.winfo_children(): walk(c,o)
walk(win, ws)
panel = [w for w in ws if hasattr(w, "btn_sales")][0]
panel.show_sales_stats(); root.update()
def walk_all(w, o):
    o.append(w)
    for c in w.winfo_children(): walk_all(c, o)
alls=[]
walk_all(root, alls)
print("toplevels found:", [(str(w), w.title()) for w in alls
      if isinstance(w, tk.Toplevel)])
print("panel path:", panel, "panel toplevel:", panel.winfo_toplevel())
root.destroy()
