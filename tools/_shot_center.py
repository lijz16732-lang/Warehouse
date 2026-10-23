# -*- coding: utf-8 -*-
"""临时脚本：验证 v1.7.11 所有弹窗居中（仓库管理 + 按型号检查重复）。"""
import os
import shutil
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.store import blank_record, Store  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_shot_")
wapp.app_dir = lambda: TMP
OUTDIR = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUTDIR, exist_ok=True)

st = Store(os.path.join(TMP, "data", "warehouse.db"))
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
# 灌入两条同型号数据，让「按型号检查重复」有内容
app.store.insert_many([
    blank_record() | {"code": "WL-00001", "brand": "罗技", "category": "外设",
                      "model": "MX Master 3", "qty": 2, "price": 599, "listed": 1},
    blank_record() | {"code": "WL-00002", "brand": "罗技", "category": "外设",
                      "model": "MX Master 3", "qty": 1, "price": 559, "listed": 0},
    blank_record() | {"code": "WL-00003", "brand": "西门子", "category": "驱动器",
                      "model": "V20", "qty": 3, "price": 1200, "listed": 1},
])
app.load_data()
root.deiconify()
root.geometry("1200x760+340+140")   # 故意把主窗口挪到非居中位置，检验弹窗是否跟随
root.update()

results = []


def step_dup():
    """打开「按型号检查重复」并截图。"""
    app.check_duplicates()
    root.update()

    def shot():
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel) and w.title() == "按型号检查重复":
                w.update_idletasks()
                print("dup geo:", w.geometry(),
                      "| root geo:", root.geometry(),
                      "| asked:", (root.winfo_rootx() + (root.winfo_width() - 760) // 2,
                                   root.winfo_rooty() + int((root.winfo_height() - 520) * 0.34)))
                screenshot.capture(os.path.join(OUTDIR, "center_dup.png"))
                print("shot ->", os.path.join(OUTDIR, "center_dup.png"))
                w.destroy()
        root.after(200, step_wh)

    root.after(600, shot)


def step_wh():
    """打开「仓库管理」并截图（模态，需在其事件循环内截图）。"""
    def watch():
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel) and w.title() == "仓库管理":
                w.update_idletasks()
                print("wh geo:", w.geometry(), "| root geo:", root.geometry())
                w.after(500, lambda: (screenshot.capture(
                    os.path.join(OUTDIR, "center_wh.png")),
                    print("shot ->", os.path.join(OUTDIR, "center_wh.png")),
                    w.destroy()))
                return
        root.after(120, watch)

    root.after(120, watch)
    app.manage_warehouses()
    root.after(300, root.destroy)


root.after(800, step_dup)
root.mainloop()
shutil.rmtree(TMP, ignore_errors=True)
print("done")
