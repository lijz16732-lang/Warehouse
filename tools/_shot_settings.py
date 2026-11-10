# -*- coding: utf-8 -*-
"""截图：v1.33.0 新设置页（浅色）。"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.store import Store  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

tmp = tempfile.mkdtemp(prefix="wm_shot_set_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()

ctypes.windll.user32.SetCursorPos(2, 2)

root = tk.Tk()
app = wapp.App(root)
root.update()
root.update_idletasks()
root.update()

app.open_appearance()
root.update()
root.update_idletasks()
root.update()

# 设置窗口标题太通用，易匹配到浏览器等外部窗口 → 临时改成唯一标题再截
dlg = None
for w in root.winfo_children():
    if isinstance(w, tk.Toplevel) and str(w.title()) == "设置":
        dlg = w
assert dlg is not None, "设置窗口未打开"
dlg.title("W M 设置探针 %d" % os.getpid())
root.update()
screenshot.capture_window("W M 设置探针", os.path.join(OUT, "settings_new.png"))
root.destroy()
print("saved:", os.path.join(OUT, "settings_new.png"))
