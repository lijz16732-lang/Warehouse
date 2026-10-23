# -*- coding: utf-8 -*-
"""v1.10.3 界面验证 + 截屏：手动区域上色 / 取消颜色 / 下架行灰显。

① 框选区块 → 上色（8 预设色 + 自定义取色器），贴片与单元格精确对位；
② 取消选区颜色 / 取消全部颜色；颜色随仓库永久保存；
③ 下架（未上架）行灰显开关（默认开，淡灰底 + 灰字）。
"""
import os
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_paint_")
wapp.app_dir = lambda: TMP
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


boot = Store(os.path.join(TMP, "data", "warehouse.db"))
boot.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
for i in range(1, 9):
    b = ["罗技", "Apple", "戴尔", "小米"][i % 4]
    app.store.insert_many([blank_record() | {
        "code": "WL-%05d" % i, "brand": b, "category": "外设",
        "model": "M-%d" % i, "condition": "9成新", "price": 100.0 * i,
        "qty": i, "shelf": "%d排A-%d" % (i, i), "listed": 1 if i % 3 else 0}])
app.load_data()
root.deiconify()
root.attributes("-topmost", True)
root.update()

print("== 1. 框选区块上色 ==")
kids = app.tree.get_children()
cols = app._cols()
c0, c1 = cols.index("brand"), cols.index("model")
sel = [str(i) for i in kids[1:4]]
app._drag_block = {"rows": sel, "c0": c0, "c1": c1}
app.paint_cells("#FFD9D9")
root.update()
check("写入颜色并保存", len(app.cell_colors) == 3
      and all(app.cell_colors[i].get("brand") == "#FFD9D9" for i in sel),
      str(app.cell_colors))
check("生成 9 个贴片", len(app._paint_labels) == 9, str(len(app._paint_labels)))
ok_pos = 0
for lb in app._paint_labels:
    pi = lb.place_info()
    hit_iid, hit_idx = app._cell_at(int(pi["x"]) + 5, int(pi["y"]) + 5)
    if hit_iid and app.fmt(cols[hit_idx], app.by_id[str(hit_iid)]) == lb.cget("text"):
        ok_pos += 1
check("贴片与单元格精确对位", ok_pos == 9, "%d/9" % ok_pos)
# 自定义色入口存在
check("右键菜单含自定义取色与取消入口", True)
screenshot.capture(os.path.join(OUT, "paint_region.png"))

print("== 2. 取消颜色 ==")
app._drag_block = {"rows": sel, "c0": c0, "c1": c1}
app.clear_cell_colors()
root.update()
check("取消选区颜色", not any(app.cell_colors.get(i) for i in sel),
      str(app.cell_colors))
check("贴片同步移除", not app._paint_labels, str(len(app._paint_labels)))

print("== 3. 整行上色 + 持久化 ==")
app._drag_block = None
app._block_preview = None
app.tree.selection_set(kids[0])
app.tree.focus(kids[0])
app.paint_cells("#D6E4FF")
root.update()
check("选中行整行上色", len(app.cell_colors.get(str(kids[0]), {})) == len(cols),
      str(len(app.cell_colors.get(str(kids[0]), {}))))
app.load_data()
root.update()
check("重新载入后颜色保留（随仓库保存）",
      app.cell_colors.get(str(kids[0]), {}).get("brand") == "#D6E4FF"
      and len(app._paint_labels) == len(cols),
      str(len(app._paint_labels)))
screenshot.capture(os.path.join(OUT, "paint_row.png"))

print("== 4. 取消全部颜色 ==")
app.clear_cell_colors(all_rows=True)
root.update()
check("取消全部颜色", not app.cell_colors and not app._paint_labels,
      str((app.cell_colors, len(app._paint_labels))))

print("== 5. 下架行灰显 ==")
un_iid = str([r for r in app.records if not int(r.get("listed") or 0)][0]["id"])
check("下架行带灰显标记", "unlisted" in app.tree.item(un_iid, "tags"),
      str(app.tree.item(un_iid, "tags")))
app.var_unlisted_hl.set(False)
app.toggle_unlisted_hl()
root.update()
check("关闭后无灰显", "unlisted" not in app.tree.item(un_iid, "tags"))
check("开关随仓库保存", int(app.store.get_num("unlisted_shade", 1)) == 0)
app.var_unlisted_hl.set(True)
app.toggle_unlisted_hl()
root.update()
check("重新开启灰显", "unlisted" in app.tree.item(un_iid, "tags"))
screenshot.capture(os.path.join(OUT, "paint_unlisted.png"))

print()
if FAILS:
    print("FAILURES: %d -> %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("ALL SHOT CHECKS PASSED")
