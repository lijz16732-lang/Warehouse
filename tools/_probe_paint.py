# -*- coding: utf-8 -*-
"""v1.32.5 探针：上色行开关 / 快速拖动洪流 / 贴片增量复用。"""

import os
import sys
import tempfile

sys.path.insert(0, ".")
sys.path.insert(0, "tools")

import ctypes
import tkinter as tk

from screenshot import capture_window
from wm import app as wapp
from wm.store import Store, blank_record

ok = True


def chk(name, cond, detail=None):
    global ok
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  <- %r" % (detail,)))
    if not cond:
        ok = False


tmp = tempfile.mkdtemp(prefix="paint_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
# 指针移开（探针铁律）
ctypes.windll.user32.SetCursorPos(2, 2)

rows = []
for i in range(120):
    r = blank_record()
    r.update({"code": "WL-%05d" % i, "brand": "品牌%d" % (i % 5), "category": "变频器",
              "model": "M%d" % i, "condition": "全新", "price": 100.0 + i, "qty": 1,
              "shelf": "%d排A-1" % (i % 9), "listed": i % 2, "remark": ""})
    rows.append(r)
app.store.insert_many(rows)
app.load_data()
root.update()
root.update_idletasks()
root.update()

t = app.tree
decor = app.decor
kids = [str(i) for i in t.get_children()]
first = kids[0]

# ====================================================== 1. 整行上色（含 listed）
app.tree.selection_set(first)
app.tree.focus(first)
app.paint_cells("#FFE7CC")          # 淡橙，整行（_paint_targets 默认选中整行）

lbls = {getattr(lb, "_cell", None) for lb in app._paint_labels}
chk("listed 列不再创建贴片", ("listed" not in [k[1] for k in lbls if k]), sorted(lbls)[:3])
chk("listed 贴片缺失（只有其他列）", not any(k[1] == "listed" for k in lbls))
chk("开关还在（上色行）", first in decor._pills)
cv = decor._pills.get(first)
chk("开关底色 = 用户上色", cv is not None and cv["bg"] == "#FFE7CC", cv["bg"] if cv else None)
chk("单元格无文字（不露已上架）", t.set(first, "listed") == "", t.set(first, "listed"))
shot = capture_window("仓管家 · 仓库管理系统", ".tmpdbg/paint_row.png")
chk("截图", shot)

# 叠放：开关要在贴片之上（tkinter children 顺序，靠后 = 上层）
children = list(root.winfo_children(t)) if False else None
order = {w: i for i, w in enumerate(t.winfo_children())}
pill_idx = order.get(cv)
above = [order.get(lb) for lb in app._paint_labels
         if getattr(lb, "_row_iid", None) == first and lb.winfo_ismapped()]
chk("开关叠放在贴片之上", pill_idx is not None and all(a is not None and a > pill_idx for a in above),
    (pill_idx, above[:3]))

# 取消颜色：开关底色回到行色
app.clear_cell_colors()
cv2 = decor._pills.get(first)
chk("取消颜色后开关底色恢复", cv2 is not None and cv2["bg"] != "#FFE7CC",
    cv2["bg"] if cv2 else None)

# ====================================================== 2. 滚动洪流（模拟快速拖动）
# 不逐次 update：模拟事件洪流下 idle 任务被饿死的场景
for i in range(1, 61):
    t.yview_moveto(i / 60.0)
root.update()
root.update_idletasks()
root.update()
visible = [iid for iid in kids if t.bbox(iid)]
missing = [iid for iid in visible if iid not in decor._pills]
chk("洪流后可见行开关齐全", not missing, missing[:5])
bad = []
for iid in visible:
    pb = t.bbox(iid, column="listed")
    cv3 = decor._pills.get(iid)
    if cv3 is None or not cv3.winfo_ismapped():
        bad.append((iid, "missing"))
    else:
        pi = cv3.place_info()
        if (int(pi["x"]), int(pi["y"])) != (int(pb[0]), int(pb[1])):
            bad.append((iid, (pi["x"], pi["y"]), pb[:2]))
chk("洪流后开关对位准确", not bad, bad[:3])

# ====================================================== 3. 贴片增量复用（滚上色行不重建）
vis0 = [iid for iid in kids if t.bbox(iid)][0]
app.tree.selection_set(vis0)
app.paint_cells("#D6E4FF")          # 给当前视口第一行上色
before_labels = {getattr(lb, "_cell"): id(lb) for lb in app._paint_labels}
n_before = len(before_labels)
chk("上色贴片已创建", n_before > 0, n_before)
# 滚两格再滚回来（bbox 回到原位）
t.yview_scroll(2, "units")
root.update()
t.yview_scroll(-2, "units")
root.update()
after_labels = {getattr(lb, "_cell"): id(lb) for lb in app._paint_labels}
reused = sum(1 for k, lid in before_labels.items() if after_labels.get(k) == lid)
chk("滚动后贴片复用（无销毁重建）", reused == n_before and reused > 0,
    "%d/%d" % (reused, n_before))

# ====================================================== 4. 滚轮多格连滚
for _ in range(12):
    app._on_wheel(type("E", (), {"delta": -120})())
root.update()
root.update_idletasks()
root.update()
visible2 = [iid for iid in kids if t.bbox(iid)]
missing2 = [iid for iid in visible2 if iid not in decor._pills]
chk("滚轮连滚后开关齐全", not missing2, missing2[:5])

capture_window("仓管家 · 仓库管理系统", ".tmpdbg/paint_final.png")
ctypes.windll.user32.SetCursorPos(2, 2)
root.destroy()
print("ALL OK" if ok else "HAS FAILURES")
sys.exit(0 if ok else 1)
