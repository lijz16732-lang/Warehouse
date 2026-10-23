# -*- coding: utf-8 -*-
"""验证：开启 DPI 感知后，反复改变窗口大小内容是否完整（不会变白/消失）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm import screen as scr  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

level = scr.enable_dpi_awareness()          # 与 main.py 一致（系统级）
print("dpi awareness level:", level)

TMP = tempfile.mkdtemp(prefix="wm_resize_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                         "model": "M%d" % i, "price": 88.0,
                                         "qty": 5, "shelf": "6排A-3"}
                       for i in range(1, 6)])
app.load_data()
root.update()

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)


def step(size, name):
    root.geometry(size + "+60+60")
    for _ in range(6):
        root.update()
        root.after(60, lambda: None)
    screenshot.capture_window("v1.12.1", os.path.join(OUT, name))
    print("shot", name, root.geometry(), "tree rows:", len(app.tree.get_children()))


step("1400x860", "resize_1_1400.png")     # 正常
step("1120x700", "resize_2_small.png")    # 缩小到接近最小
step("1600x940", "resize_3_large.png")    # 再放大
root.state("zoomed")
for _ in range(6):
    root.update()
    root.after(60, lambda: None)
screenshot.capture_window("v1.12.1", os.path.join(OUT, "resize_4_max.png"))
print("shot resize_4_max", root.geometry())
root.state("normal")
for _ in range(6):
    root.update()
    root.after(60, lambda: None)
print("restored:", root.geometry(), "tree rows:", len(app.tree.get_children()))
root.destroy()
