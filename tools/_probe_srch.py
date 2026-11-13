# -*- coding: utf-8 -*-
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from wm import app as wapp
from wm.store import Store
TMP = tempfile.mkdtemp(prefix="probe_sr_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
root = tk.Tk(); app = wapp.App(root); root.update()
app.open_appearance("look"); root.update()
win = app._settings_win; root.update()

def walk(w, out_l):
    out_l.append(w)
    for c in w.winfo_children():
        walk(c, out_l)

ws = []; walk(win, ws)
ents = [w for w in ws if isinstance(w, tk.Entry)]
lbs = [w for w in ws if isinstance(w, tk.Listbox)]
print("entries:", len(ents), "listboxes:", len(lbs))
for i, e in enumerate(ents[:4]):
    print(" ent%d text=%r parent=%s" % (i, e.get(), e.winfo_parent()))
ent = ents[0]; lb = lbs[0]
ent.delete(0, "end"); ent.insert(0, "导出")
print("ent.get=%r" % ent.get())
ent.event_generate("<KeyRelease>", keysym="o"); root.update()
print("bind:", repr(ent.bind("<KeyRelease>"))[:120])
try:
    win._search_do()
    print("direct call ok, lb size:", lb.size(), [lb.get(i) for i in range(lb.size())][:3])
except Exception as e:
    import traceback; traceback.print_exc()
print("lb size:", lb.size(), "mapped:", lb.winfo_ismapped())
print("items:", [lb.get(i) for i in range(min(3, lb.size()))])
root.destroy()
