# -*- coding: utf-8 -*-
"""v1.46.9 探针：徽章胶囊底色 + 复选框格底色跟随选中行底色。

复现路径：下架行（listed=0，带 unlisted tag）被选中 →
Treeview 把整行画成选中蓝 CLR_SEL，但覆盖层贴片若按下架灰取色就会两色割裂。
断言：
1. _row_bg：选中态优先于 unlisted/low/odd，返回 CLR_SEL
2. 徽章贴片 canvas 底色 = CLR_SEL（选中时）
3. 复选框贴片 canvas 底色 = CLR_SEL（选中时）
4. 取消选中后回到 unlisted 灰
5. 徽章 PNG 缓存 key 带底色，不同底色生成不同图
6. 普通未选中行不受影响
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk

import wm.app as wapp
from wm.constants import CLR_SEL, CLR_UNLISTED_BG, CLR_INPUT
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="wm_probe_1469_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP
st = Store(os.path.join(TMP, "warehouse.db"))
for i in range(1, 13):
    rec = blank_record()
    rec.update({"lid": i, "code": "WL-%05d" % i, "brand": "基恩士",
                "category": "传感器", "model": "FS-V%d" % i,
                "qty": 2, "price": 100.0, "listed": 0})
    st.insert(rec)
st.close()

ok = [0, 0]


def check(name, cond):
    ok[0] += 1
    if cond:
        ok[1] += 1
    print(("ok  " if cond else "FAIL") + " " + name)


try:
    ctypes.windll.user32.SetCursorPos(2, 2)
except Exception:
    pass

root = tk.Tk()
root.geometry("1200x700+40+40")
app = wapp.App(root)
app.nb.select(app.tab_inv)
app.load_data()
root.update_idletasks()
root.update()

tree = app.tree
decor = app.decor
kids = list(tree.get_children())
check("有测试行", len(kids) >= 5)

# ---- 1 初始：下架行未选中 → unlisted 灰 ----
t0 = kids[0]
check("未选下架行 _row_bg=下架灰", decor._row_bg(t0) == CLR_UNLISTED_BG)
check("未选下架行徽章格底色=下架灰",
      decor._pills.get(t0) is not None and
      decor._pills[t0].cget("bg") == CLR_UNLISTED_BG)
check("未选下架行复选框格底色=下架灰",
      decor._chks.get(t0) is not None and
      decor._chks[t0].cget("bg") == CLR_UNLISTED_BG)

# ---- 2 选中该下架行 → 全部跟随选中蓝 ----
tree.selection_set([t0])
root.update()
decor.redraw()
root.update()
check("选中下架行 _row_bg=选中蓝", decor._row_bg(t0) == CLR_SEL)
check("选中下架行徽章格底色=选中蓝",
      decor._pills.get(t0) is not None and
      decor._pills[t0].cget("bg") == CLR_SEL)
check("选中下架行复选框格底色=选中蓝",
      decor._chks.get(t0) is not None and
      decor._chks[t0].cget("bg") == CLR_SEL)

# ---- 3 徽章 PNG 缓存：key 带底色，两色不同图 ----
img_a = decor._badge_image(False, 60, 24, CLR_SEL)
img_b = decor._badge_image(False, 60, 24, CLR_UNLISTED_BG)
check("两底色生成两张不同徽章图", img_a is not None and img_b is not None
      and img_a is not img_b)
check("徽章缓存 key 含底色",
      any(isinstance(k, tuple) and len(k) == 5 and k[4] == str(CLR_SEL)
          for k in decor._imgs))

# ---- 4 取消选中 → 回下架灰（走真实点击的 selection_remove 路径）----
tree.selection_remove(t0)
root.update()
decor.redraw()
root.update()
check("取消选中 _row_bg=下架灰", decor._row_bg(t0) == CLR_UNLISTED_BG)
check("取消选中徽章格底色=下架灰",
      decor._pills.get(t0) is not None and
      decor._pills[t0].cget("bg") == CLR_UNLISTED_BG)

# ---- 5 用户上色格仍最高优先 ----
app.cell_colors = {str(t0): {"listed": "#FF0000"}}
check("用户上色格最高优先", decor._row_bg(t0) == "#FF0000")

# ---- 6 已上架固定绿色语义胶囊，不随行底色变（v1.46.11）----
from wm.gridlines import _BADGE_ON
on_a = decor._badge_image(True, 60, 24, CLR_SEL)
on_b = decor._badge_image(True, 60, 24, CLR_UNLISTED_BG)
check("已上架在两底色下同一张图（底固定绿）", on_a is not None and on_a is on_b)
check("已上架缓存 key 的 bgc=绿色",
      any(isinstance(k, tuple) and len(k) == 5 and k[0] is True
          and k[4] == str(_BADGE_ON["light"][0])
          for k in decor._imgs))
# 下架仍随底色不同（已有 img_a/img_b）
check("下架仍随底色变化", img_a is not img_b)

print("PROBE 1469: %d/%d" % (ok[1], ok[0]))
root.destroy()
sys.exit(0 if ok[0] == ok[1] else 1)
