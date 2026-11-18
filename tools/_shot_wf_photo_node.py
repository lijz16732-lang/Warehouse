# -*- coding: utf-8 -*-
"""截图：制作单详情的照片按节点归属。"""
import base64
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

import tkinter as tk

from wm import app as wapp
from wm import workflow as wfmod
from wm.store import Store, wf_photo_code
import tools.screenshot as screenshot

TMP = tempfile.mkdtemp(prefix="wf_ph_shot_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
wfmod.messagebox.showinfo = lambda *a, **k: None
wfmod.messagebox.showwarning = lambda *a, **k: None

png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAA"
    "YAAf8B9W8lAAAAAElFTkSuQmCC")
B64 = base64.b64encode(png).decode("ascii")

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
top = tk.Toplevel(root)
top.geometry("760x520+80+60")
tab = wfmod.WorkflowTab(top, app)
tab.pack(fill="both", expand=True)
root.deiconify()
root.update_idletasks()
root.update()

store = app.store
stages = store.wf_stages()
wid, no = store.wf_create("水獭拭", kind="修复", by="3+3",
                          extra={"型号": "sda"})
store.photo_add("wf", wf_photo_code(no, 0), B64, "发起制作1.png")
store.photo_add("wf", wf_photo_code(no, 0), B64[:-4] + "AAAA", "发起制作2.png")
store.photo_add("wf", wf_photo_code(no, 1), B64, "制作标签1.png")
tab.refresh_rows()
root.update()

rec = [r for r in store.wf_list("active", "") if int(r["id"]) == wid][0]
dlg = wfmod.DetailDialog(top, tab, rec)
dlg.geometry("+80+80")


def shot(w, path):
    try:
        w.attributes("-alpha", 1.0)
        w.attributes("-topmost", True)
    except Exception:
        pass
    w.update_idletasks()
    root.update()
    screenshot.capture_window(w.title(), path)


shot(dlg, os.path.join(OUT, "_wf_photo_node.png"))
dlg.var_ph_node.set(stages[1])
dlg._set_ph_node()
root.update()
shot(dlg, os.path.join(OUT, "_wf_photo_node2.png"))
dlg.destroy()
root.destroy()
print("done", OUT)
