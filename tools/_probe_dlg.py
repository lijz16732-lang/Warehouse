# -*- coding: utf-8 -*-
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from wm import app as wapp
from wm.store import Store
TMP = tempfile.mkdtemp(prefix="pdlg_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
root = tk.Tk(); app = wapp.App(root); root.update()
ok, msg = app.start_lan_host(port=18766)
print("host:", ok, msg)
app.open_appearance("lan"); root.update()
win = app._settings_win
ws=[]
def walk(w,o):
    o.append(w)
    for c in w.winfo_children(): walk(c,o)
walk(win, ws)
panel = [w for w in ws if hasattr(w, "btn_sales")][0]
try:
    panel.show_sales_stats()
    print("called ok")
except Exception as e:
    import traceback; traceback.print_exc()
root.update()
tops = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
print("toplevels:", [(t.title()) for t in tops])
root.destroy()
