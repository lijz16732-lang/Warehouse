# -*- coding: utf-8 -*-
"""真机验证：出售记录页 / 出库记录页的拖选复制、Ctrl+C、右键复制。

窗口打开后：
1. 切到「出售记录」页，用真实鼠标事件从「品牌」列拖到「数量」列 → 读剪贴板；
2. 切到「出库记录」页同样拖一次；
3. 打印区块与剪贴板内容，并截屏。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import tkinter as tk  # noqa: E402

from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

# 用临时库 + 造几行数据，避免动到真实仓库
TMP = tempfile.mkdtemp(prefix="wm_drag_")
wapp.app_dir = lambda: TMP
_boot = Store(os.path.join(TMP, "data", "warehouse.db"))
_boot.close()

root = tk.Tk()
app = wapp.App(root)
root.deiconify()
root.geometry("1400x860+80+40")
root.update()
app.store.insert_many([
    blank_record() | {"code": "WL-00001", "brand": "罗技", "category": "外设",
                      "model": "MX3", "price": 599.0, "qty": 5, "shelf": "6排A-3",
                      "listed": 1},
    blank_record() | {"code": "WL-00002", "brand": "Apple", "category": "手机",
                      "model": "A2634", "price": 2899.0, "qty": 4, "shelf": "7排B-2",
                      "listed": 1},
    blank_record() | {"code": "WL-00003", "brand": "戴尔", "category": "显示器",
                      "model": "U2720Q", "price": 1580.0, "qty": 3, "shelf": "8排C-1",
                      "listed": 1},
])
app.load_data()
recs = {r["code"]: r for r in app.store.all_records()}
app.store.add_sale(recs["WL-00001"]["id"], 1, 650.0, buyer="张三",
                   sale_date="2026-10-02", address="广东省深圳市南山区科技园1号")
app.store.add_sale(recs["WL-00002"]["id"], 1, 3100.0, buyer="李四",
                   sale_date="2026-10-05", address="北京市朝阳区建国路88号")
app.store.add_sale(recs["WL-00003"]["id"], 1, 0, sale_date="2026-10-06", out_type="报废")
app.load_data()
root.update()


def center(tree, iid, colname):
    b = tree.bbox(iid, column=colname)
    if not b:
        raise RuntimeError("bbox 为空：%s / %s" % (iid, colname))
    return b[0] + 6, b[1] + b[3] // 2


def drag(tree, iid_a, col_a, iid_b, col_b):
    sx, sy = center(tree, iid_a, col_a)
    ex, ey = center(tree, iid_b, col_b)
    print("  起点 %s -> 终点 %s" % ((sx, sy), (ex, ey)))
    tree.event_generate("<ButtonPress-1>", x=sx, y=sy)
    root.update()
    for i in range(1, 8):
        mx = sx + (ex - sx) * i // 7
        my = sy + (ey - sy) * i // 7
        tree.event_generate("<B1-Motion>", x=mx, y=my)
        root.update()
        time.sleep(0.02)
    tree.event_generate("<ButtonRelease-1>", x=ex, y=ey)
    root.update()


def clip():
    try:
        return root.clipboard_get()
    except tk.TclError:
        return ""


def shot(name):
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools"))
        import screenshot
        screenshot.capture(os.path.join(OUT, name))
        print("  截图 ->", name)
    except Exception as e:
        print("  截图失败:", e)


report = []

# ---- 1. 出售记录页 ----
app.nb.select(1)
root.update()
tb = app.tab_sales
tb.refresh_rows()
root.update()
kids = tb.tree.get_children()
print("出售页行数:", len(kids), "列:", tb.col_keys())
if len(kids) >= 2:
    b1 = tb.tree.bbox(kids[0], column="qty")
    print("  qty 单元格 bbox:", b1, "-> _cell_at:",
          tb._cell_at(b1[0] + 3, b1[1] + 3) if b1 else None)
    drag(tb.tree, kids[0], "code", kids[-1], "qty")
    got = clip()
    print("  区块:", tb._drag_block)
    print("  剪贴板行数:", got.count("\n") + 1 if got else 0)
    print("  内容:\n" + "\n".join(got.split("\n")[:4]))
    report.append(("出售页拖选复制", bool(tb._drag_block) and bool(got)))
    shot("drag_sales.png")
    # Ctrl+C 复制选中行
    tb._drag_block = None
    tb.tree.selection_set(kids[0])
    tb.tree.focus(kids[0])
    root.update()
    tb.copy_shortcut()
    report.append(("出售页 Ctrl+C", "\n" not in clip() and bool(clip())))

# ---- 2. 出库记录页 ----
app.nb.select(2)
root.update()
ob = app.tab_out
ob.refresh_tab()
root.update()
okids = ob.tree.get_children()
print("出库页行数:", len(okids), "列:", ob.col_keys())
if len(okids) >= 2:
    b2 = ob.tree.bbox(okids[0], column="qty")
    print("  qty 单元格 bbox:", b2, "-> _cell_at:",
          ob._cell_at(b2[0] + 3, b2[1] + 3) if b2 else None)
    drag(ob.tree, okids[0], "out_type", okids[-1], "qty")
    got2 = clip()
    print("  区块:", ob._drag_block)
    print("  内容:\n" + "\n".join(got2.split("\n")[:4]))
    report.append(("出库页拖选复制", bool(ob._drag_block) and bool(got2)))
    shot("drag_out.png")
    ob._drag_block = None
    ob.tree.selection_set(okids[0])
    ob.tree.focus(okids[0])
    root.update()
    ob.copy_shortcut()
    report.append(("出库页 Ctrl+C", bool(clip())))

print("--- 结果 ---")
for name, ok in report:
    print(("通过  " if ok else "失败  ") + name)
app._stopped = True
root.destroy()
