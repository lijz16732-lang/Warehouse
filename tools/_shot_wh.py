# -*- coding: utf-8 -*-
"""临时脚本：打开仓库管理对话框并截图，验证 v1.7.1 卡片式界面。"""
import ctypes
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
OUT = os.path.join(ROOT, ".tmpdbg", "wh_dialog_v171.png")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

# 造数据：主仓库 5 条 + 二号仓 3 条
st = Store(os.path.join(TMP, "data", "warehouse.db"))
for i in range(5):
    st.insert(blank_record() | {"code": "WL-%05d" % (i + 1), "brand": "罗技",
                                "category": "外设", "model": "G%d" % (i + 1),
                                "qty": i + 1, "price": 99 + i, "listed": 1})
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
app.store.insert_many([blank_record() |
                       {"code": "WL-00001", "brand": "西门子", "category": "驱动器",
                        "model": "V20", "qty": 2, "price": 1200, "listed": 0}])
app.load_data()
app.add_warehouse("二号仓")
app.add_warehouse("旧货仓")
app.load_data()
root.deiconify()
root.update()

dlg_holder = []


def shoot():
    app.manage_warehouses.__self__  # noqa - just ensure exists
    # manage_warehouses 是模态的：先安排截图再打开
    def _shoot_when_open():
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel) and w.title() == "仓库管理":
                dlg_holder.append(w)
                w.attributes("-topmost", True)
                w.lift()
                w.update()
                w.after(600, capture)
                return
        root.after(150, _shoot_when_open)

    def capture():
        screenshot.capture(OUT)
        print("shot ->", OUT)
        for w in dlg_holder:
            w.destroy()
        root.destroy()

    root.after(120, _shoot_when_open)
    app.manage_warehouses()


root.after(1000, shoot)
root.mainloop()
shutil.rmtree(TMP, ignore_errors=True)
