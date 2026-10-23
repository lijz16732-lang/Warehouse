# -*- coding: utf-8 -*-
"""真机验证（v1.10.6）：上色 → 真实滚轮滚走 → 滚回来，颜色必须还在且对位。

修复前：滚轮滚动交给 Tk 类绑定，重画发生在滚动之前，贴片停在旧像素位置；
上色行滚出可视区后 _paint_labels 归零，滚回来再也不重画 → 颜色"消失"。
"""
import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()          # 让 Tk 坐标 == 物理像素

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="wm_psc_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([
    blank_record() | {"code": "WL-0000%d" % i, "brand": "ABB", "category": "PLC",
                      "model": "M-%d" % i, "price": 10.0 * i, "qty": i,
                      "shelf": "1排A", "listed": 1} for i in range(1, 61)])
app.load_data()
root.geometry("1500x900+60+40")
root.deiconify()
root.attributes("-topmost", True)
root.update()
time.sleep(0.6)
root.update()

cols = app._cols()
kids = list(app.tree.get_children())


def aligned():
    """贴片与同位置单元格文本一一对齐的数量。"""
    n = 0
    for lb in app._paint_labels:
        pi = lb.place_info()
        iid, idx = app._cell_at(int(pi["x"]) + 5, int(pi["y"]) + 5)
        if iid and app.fmt(cols[idx], app.by_id[str(iid)]) == lb.cget("text"):
            n += 1
    return n, len(app._paint_labels)


def real_wheel(cx, cy, notches):
    user32.SetCursorPos(cx, cy)
    time.sleep(0.15)
    for _ in range(notches):
        user32.mouse_event(0x0800, 0, 0, -120, 0)   # 滚轮向下 1 格
        time.sleep(0.12)
        root.update()
    time.sleep(0.3)
    root.update()


def tree_center():
    return (app.tree.winfo_rootx() + app.tree.winfo_width() // 2,
            app.tree.winfo_rooty() + app.tree.winfo_height() // 2)


# ---- 1. 给第 3 行整行上色（真实路径：选中行 + paint_cells） ----
tgt = str(kids[2])
app._drag_block = None
app._block_preview = None
app.tree.selection_set(tgt)
app.paint_cells("#FFD9D9")
root.update()
n0, tot0 = aligned()
check("上色生成贴片且对位", tot0 > 0 and n0 == tot0, "%d/%d" % (n0, tot0))

# ---- 2. 真实滚轮向下 5 格（上色行滚出可视区） ----
cx, cy = tree_center()
real_wheel(cx, cy, 5)
check("滚出可视区后贴片清空", not app._paint_labels and app.tree.bbox(tgt) == "",
      "labels=%d bbox=%s" % (len(app._paint_labels), app.tree.bbox(tgt)))

# ---- 3. 真实滚轮向上滚回（回到顶部） ----
user32.SetCursorPos(cx, cy)
time.sleep(0.15)
for _ in range(8):
    user32.mouse_event(0x0800, 0, 0, 120, 0)        # 滚轮向上 1 格
    time.sleep(0.12)
    root.update()
time.sleep(0.3)
root.update()
check("滚回顶部 yview 回到起点", app.tree.yview()[0] <= 0.001, str(app.tree.yview()))
n1, tot1 = aligned()
check("滚回来颜色恢复且对位", tot1 == tot0 and n1 == tot1, "%d/%d" % (n1, tot1))
screenshot.capture_window("仓管家", os.path.join(OUT, "verify_scroll_rc.png"))

# ---- 4. 鼠标停在上色格子上滚轮（贴片接管滚动） ----
bb = app.tree.bbox(tgt, column="brand")
user32.SetCursorPos(app.tree.winfo_rootx() + bb[0] + bb[2] // 2,
                    app.tree.winfo_rooty() + bb[1] + bb[3] // 2)
time.sleep(0.15)
user32.mouse_event(0x0800, 0, 0, -120, 0)
time.sleep(0.2)
root.update()
check("鼠标停在上色格子上也能滚动", app.tree.yview()[0] > 0.0, str(app.tree.yview()))
n2, tot2 = aligned()
check("贴片接管滚动后仍对位", tot2 == tot0 and n2 == tot2, "%d/%d" % (n2, tot2))
user32.mouse_event(0x0800, 0, 0, 120, 0)
time.sleep(0.2)
root.update()

print("== 结果：%s ==" % ("全部通过" if not FAILS else "失败 %d 项" % len(FAILS)))
root.destroy()
sys.exit(1 if FAILS else 0)
