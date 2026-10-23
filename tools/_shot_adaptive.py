# -*- coding: utf-8 -*-
"""截图：屏幕自适应三种场景（1080p 台式 / 1366×768 笔记本 / 150% 缩放笔记本）。"""
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

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)


def make_app(tmp_prefix="wm_shot_a_"):
    tmp = tempfile.mkdtemp(prefix=tmp_prefix)
    wapp.app_dir = lambda: tmp
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
    return root, app


def shot(win, name):
    win.update_idletasks()
    win.update()
    screenshot.capture_window("v1.12.0", os.path.join(OUT, name))
    print("saved", name)


# 1) 台式 1080p（真实屏幕 1920×1080，Win11 工作区 1032）→ 1440×900 居中
r1, a1 = make_app()
shot(r1, "adaptive_desktop.png")
print("desktop window:", r1.geometry(), "scale:", a1.ui_scale)
r1.destroy()

# 2) 笔记本 1366×768：窗口缩到该尺寸，检查工具栏 / 侧栏 / 表格是否完整
r2, a2 = make_app()
r2.geometry("1366x728+30+30")
shot(r2, "adaptive_laptop.png")
print("laptop window:", r2.geometry(), "min:", r2.minsize())
r2.destroy()

# 3) 150% 缩放笔记本：DPI 与工作区都按 1.5 档模拟
_orig_dpi, _orig_area = scr.dpi_scale, scr.work_area
scr.dpi_scale = lambda: 1.5
scr.work_area = lambda: (0, 0, 1920, 1032)
r3, a3 = make_app()
shot(r3, "adaptive_hidpi.png")
print("hidpi window:", r3.geometry(), "scale:", a3.ui_scale,
      "rowheight:", r3.tk.call("ttk::style", "lookup", "Treeview", "-rowheight"))
r3.destroy()
scr.dpi_scale, scr.work_area = _orig_dpi, _orig_area
