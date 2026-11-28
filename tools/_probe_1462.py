# -*- coding: utf-8 -*-
"""v1.46.2 表格精修探针：复选框列 / 筛选回显条 / 上架徽章。

铁律：resolve_data_dir 打桩到临时目录；指针移开；断言用真实值。
"""
import os
import sys
import tempfile
import ctypes

sys.path.insert(0, ".")

ok = [0, 0]


def check(name, cond, extra=""):
    ok[0] += 1
    if cond:
        ok[1] += 1
    print(("ok  " if cond else "FAIL") + " " + name + ("" if cond else "  -> " + str(extra)))


TMP = tempfile.mkdtemp(prefix="wm_probe_1462_")

import wm.app as wapp
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP

import tkinter as tk
from wm.store import Store, blank_record

st = Store(os.path.join(TMP, "warehouse.db"))
rows = [("基恩士", 3, 1280.5, 1), ("西门子", 1, 2150.0, 1), ("欧姆龙", 56, 38.0, 0)]
for i, (brand, qty, price, listed) in enumerate(rows, 1):
    rec = blank_record()
    rec.update({"lid": i, "code": "WL-%05d" % i, "brand": brand,
                "category": "传感器", "model": "M%d" % i, "qty": qty,
                "price": price, "listed": listed})
    st.insert(rec)
st.close()

ctypes.windll.user32.SetCursorPos(2, 2)
root = tk.Tk()
root.geometry("1840x900+10+10")
app = wapp.App(root)
app.nb.select(app.tab_inv)
app.load_data()
root.update_idletasks()
root.update()

kids = list(app.tree.get_children())
check("首列是复选框列", list(app.tree["columns"])[0] == "_chk")
check("每行首格是 ☐", all(app.tree.set(k, "_chk") == "☐" for k in kids))

# ---- 复选框跟随选中 ----
app.tree.selection_set([kids[0]])
root.update()
check("选中行变 ☑", app.tree.set(kids[0], "_chk") == "☑"
      and app.tree.set(kids[1], "_chk") == "☐")

# 表头全选 / 全不选
app._toggle_check_all()
root.update()
check("表头全选", len(app.tree.selection()) == len(kids)
      and all(app.tree.set(k, "_chk") == "☑" for k in kids))
app._toggle_check_all()
root.update()
check("表头全不选", not app.tree.selection()
      and all(app.tree.set(k, "_chk") == "☐" for k in kids))

# _cell_at 不把复选框列当数据格（编码列开头也不误判）
bb = app.tree.bbox(kids[0], column="_chk")
r = app._cell_at(bb[0] + 2, bb[1] + 2)
check("点复选框格不是数据格", r == (None, None), r)
bb2 = app.tree.bbox(kids[0], column="code")
r2 = app._cell_at(bb2[0] + 4, bb2[1] + 2)
check("编码列开头仍判为第 0 数据列", r2 == (str(kids[0]), 0), r2)

# 点复选框格 = 切换该行且不清其他行
app.tree.selection_set([kids[1]])
root.update()


class E:
    x = bb[0] + 2
    y = bb[1] + 2


consumed = app._on_chk_click(E())
check("点勾选格被消费且保留他行",
      consumed and set(app.tree.selection()) == {str(kids[0]), str(kids[1])})

# ---- 筛选回显条 ----
app.tree.selection_remove(*app.tree.selection())
app.f_vars["brand"].set("基恩士")
app.var_kw.set("WL-00001")
app.apply_filters()
root.update()
texts = "|".join(str(w._text) if hasattr(w, "_text") else ""
                 for w in app.frm_chips.winfo_children())
check("品牌+关键词回显两颗", "品牌：基恩士" in texts and "关键词：WL-00001" in texts,
      texts)
n_before = len(app.frm_chips.winfo_children())
# 点品牌胶囊 → 移除品牌筛选
brand_chip = [w for w in app.frm_chips.winfo_children()
              if "品牌" in str(getattr(w, "_text", ""))][0]
brand_chip._click()
root.update()
texts2 = "|".join(str(w._text) if hasattr(w, "_text") else ""
                  for w in app.frm_chips.winfo_children())
check("点胶囊移除品牌筛选", len(app.frm_chips.winfo_children()) == n_before - 1
      and "品牌" not in texts2 and app.f_vars["brand"].get() == "全部", texts2)
app.var_kw.set("")
app.apply_filters()
root.update()
check("无筛选时回显条隐藏", not app.frm_chips.winfo_ismapped())

# ---- 上架徽章 ----
decor = getattr(app, "decor", None)
check("网格线装饰存在（徽章宿主）", decor is not None)
from wm import gridlines as _gl
check("徽章配色表齐", len(_gl._BADGE_ON["light"]) == 2
      and len(_gl._BADGE_OFF["dark"]) == 2)
img_on = decor._badge_image(True, 120, 30)
img_off = decor._badge_image(False, 120, 30)
check("徽章 PNG 能生成（上架/下架）", img_on is not None and img_off is not None)
check("徽章按参数缓存", decor._badge_image(True, 120, 30) is img_on)

# ---- 翻页/重渲染后选中保持 ----
app.tree.selection_set([kids[0]])
app.apply_filters(keep_page=True)
root.update()
check("重渲染后选中保持", str(kids[0]) in app.tree.selection())

print()
print("%d/%d 项通过" % (ok[1], ok[0]))
root.destroy()
sys.exit(0 if ok[1] == ok[0] else 1)
