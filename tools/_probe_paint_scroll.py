# -*- coding: utf-8 -*-
"""排查：上色后滚动，颜色消失 / 错位（v1.10.6 修复前的现场取证）。

结论要点：
  1. 滚轮滚动时，实例绑定 <MouseWheel> 先于 TtkTreeview 类绑定执行 →
     重画发生在「真正的滚动」之前 → 贴片停在旧像素位置。
  2. 贴片一旦全部滚出可视区，_paint_labels 变空，_after_scroll 的
     `if self._paint_labels` 守卫让后续滚动再也不重画 → 颜色永久消失。
  3. 表头区域：贴片 y 小于表头下沿时会盖住表头（需裁剪）。
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

TMP = tempfile.mkdtemp(prefix="wm_probe_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([
    blank_record() | {"code": "WL-%05d" % i, "brand": "ABB", "category": "PLC",
                      "model": "M-%d" % i, "price": 10.0 * i, "qty": i,
                      "shelf": "1排A", "listed": 1} for i in range(1, 61)])
app.load_data()
root.geometry("1500x760+60+40")
root.deiconify()
root.update()
time.sleep(0.5)
root.update()

kids = app.tree.get_children()
cols = app._cols()
target = str(kids[2])
print("row height / header probe:")
print("  bbox first row  :", app.tree.bbox(kids[0]))
print("  tree height     :", app.tree.winfo_height())

# 给第 3 行整行上色
app._drag_block = None
app._block_preview = None
app.tree.selection_set(target)
app.paint_cells("#FFD9D9")
root.update()
print("painted labels  :", len(app._paint_labels))
print("bbox target row :", app.tree.bbox(target, column="brand"))
pi = app._paint_labels[0].place_info()
print("label0 pos      :", pi["x"], pi["y"])


def align_check(tag):
    """每个贴片的文本是否与同位置的真实单元格一致；并检查有没有贴到表头上。"""
    if not app._paint_labels:
        print("  %s: 贴片数量 0（颜色不可见）" % tag)
        return
    ok = 0
    for lb in app._paint_labels:
        info = lb.place_info()
        iid, idx = app._cell_at(int(info["x"]) + 5, int(info["y"]) + 5)
        if iid and app.fmt(cols[idx], app.by_id[str(iid)]) == lb.cget("text"):
            ok += 1
    ymin = min(int(lb.place_info()["y"]) for lb in app._paint_labels)
    print("  %s: 贴片 %d 个，对位正确 %d 个，最小 y=%d（表头 %d）"
          % (tag, len(app._paint_labels), ok, ymin, app._head_h))


print("初始:", end="")
align_check("初始")

# 1) 滚轮向下（走 Tk 自带的类绑定滚动）：一格一格看，弄清滚动与重画的先后
for i in range(6):
    app.tree.event_generate("<MouseWheel>", delta=-120)
    root.update()
    print("第 %d 格: 贴片 %d 个, 目标行 bbox=%s" %
          (i + 1, len(app._paint_labels), app.tree.bbox(target, column="brand")))
    align_check("      ")
align_check("滚后")
print("  yview:", app.tree.yview())

# 2) 继续滚到贴片全部离开可视区
for _ in range(20):
    app.tree.event_generate("<MouseWheel>", delta=-120)
    root.update()
print("滚到贴片离开可视区: 贴片 %d 个, yview=%s" % (len(app._paint_labels), app.tree.yview()))

# 3) 滚回顶部，看颜色是否还在
for _ in range(30):
    app.tree.event_generate("<MouseWheel>", delta=120)
    root.update()
print("滚回顶部: yview=%s" % (app.tree.yview(),))
align_check("滚回后")

# 4) 半行（表头压住上半截）时贴片不能盖到表头上
app.tree.yview_moveto(0.03)          # 0.03*60 ≈ 第 1.8 行 → 首行是半行
app._after_scroll()
root.update()
if app._paint_labels:
    ymin = min(int(lb.place_info()["y"]) for lb in app._paint_labels)
    print("半行状态: 贴片 %d 个，最小 y=%d（表头 %d）→ %s"
          % (len(app._paint_labels), ymin, app._head_h,
             "OK 未盖表头" if ymin >= app._head_h else "!! 盖住表头"))
else:
    print("半行状态: 贴片 0 个（首行半行被跳过，属预期）")
screenshot.capture_window("仓管家", os.path.join(OUT, "probe_scroll.png"))

# 5) 滚回顶部再看一眼
app.tree.yview_moveto(0.0)
app._after_scroll()
root.update()
align_check("回顶")
print("done")
