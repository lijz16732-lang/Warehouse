# -*- coding: utf-8 -*-
"""排查：划过上色行（贴片）与移出表格时，Motion/Leave 到底有没有到。"""
import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

import tkinter as tk  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_dbg_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                         "model": "M-%d" % i, "price": 10.0 * i,
                                         "qty": 8, "listed": 1}
                       for i in range(1, 21)])
app.load_data()
root.geometry("1500x900+60+40")
root.deiconify()
root.attributes("-topmost", True)
root.update()
time.sleep(0.5)
root.update()

EV = []
app.tree.bind("<Motion>", lambda e: EV.append("tree Motion"), add="+")
app.tree.bind("<Leave>", lambda e: EV.append("tree Leave"), add="+")
print("tree height:", app.tree.winfo_height(), "rooty:", app.tree.winfo_rooty())

kids = [str(i) for i in app.tree.get_children()]
row8 = kids[7]


def cell_px(iid, col="remark"):
    b = app.tree.bbox(iid, column=col)
    return (app.tree.winfo_rootx() + b[0] + b[2] // 2,
            app.tree.winfo_rooty() + b[1] + b[3] // 2)


# 1) 先给第 8 行上色
app.tree.selection_set(row8)
app.paint_cells("#FFD9D9")
app.tree.selection_set()
app.hover.set(None)
root.update()
print("贴片数:", len(app._paint_labels), "| 贴片绑定:",
      [b[0] for b in app._paint_labels[0].bind()])
print("标签行号:", sorted({lb._row_iid for lb in app._paint_labels}))

# 给贴片装调试钩子
for lb in app._paint_labels:
    lb.bind("<Motion>", lambda e: EV.append("label Motion"), add="+")
    lb.bind("<Leave>", lambda e: EV.append("label Leave"), add="+")

p = cell_px(row8)
EV.clear()
user32.SetCursorPos(4, 4)
time.sleep(0.3)
root.update()
user32.SetCursorPos(*p)
time.sleep(0.4)
root.update()
print("\n移到上色单元格(贴片)上:", p)
print("  事件:", EV[-6:])
print("  hover.row:", app.hover.row, "(应为 %s)" % row8)
print("  指针位置:", root.winfo_pointerxy(),
      "| row_at:", app.hover.row_at(*root.winfo_pointerxy()))

# 2) 移到表格下方（同一窗口内）
EV.clear()
p2 = (p[0], app.tree.winfo_rooty() + app.tree.winfo_height() + 60)
user32.SetCursorPos(*p2)
time.sleep(0.4)
root.update()
print("\n移到表格下方:", p2)
print("  事件:", EV[-6:])
print("  hover.row:", app.hover.row)
print("  指针位置:", root.winfo_pointerxy(),
      "| row_at:", app.hover.row_at(*root.winfo_pointerxy()))

# 3) 强制 sync 看看能否自愈
app.hover.sync()
print("\n手动 sync 后 hover.row:", app.hover.row)
root.destroy()
