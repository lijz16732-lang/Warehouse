# -*- coding: utf-8 -*-
"""截图：v1.34 左侧功能导航骨架（浅色 + 各页切换）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

tmp = tempfile.mkdtemp(prefix="wm_shot_nav_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()
root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([
    blank_record() | {"code": "WL-%05d" % i, "brand": b, "model": "M%d" % i,
                      "price": 88.0 + i, "qty": 5, "shelf": "6排A-3",
                      "condition": "全新", "category": "变频器"}
    for i, b in enumerate(["ABB", "西门子", "三菱", "施耐德", "台达"], start=1)])
app.load_data()
root.update()

import ctypes
ctypes.windll.user32.SetCursorPos(2, 2)   # 指针移开，防 hover 干扰
root.update()


def shot(name):
    root.update_idletasks()
    root.update()
    screenshot.capture_window("仓管家 · 仓库管理系统", os.path.join(OUT, name))


shot("nav_inv.png")
app.show_page(1)
root.update()
shot("nav_sales.png")
app.show_page(3)
root.update()
shot("nav_ana.png")
# 折叠「销售管理」组再截一张
app.show_page(0)
root.update()
app.nav._toggle("销售管理")
root.update()
shot("nav_collapsed.png")
root.destroy()
print("done")
