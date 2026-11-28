# -*- coding: utf-8 -*-
"""v1.46.7 探针：表头全选复选框（设计稿同款三态圆角方块）。

验证点：
1. 表头 heading 文字已清空（去掉旧「☑」字形）
2. 表头复选框覆盖层存在、贴在首列表头格内
3. 三态：未选=off / 全选=on / 部分选=partial（通过 _chk_image 缓存 key 验证）
4. 点表头复选框 → 全选；再点 → 全不选
5. 表头复选框置顶、不被网格线盖住
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk

import wm.app as wapp
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="wm_probe_1467_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP
st = Store(os.path.join(TMP, "warehouse.db"))
for i in range(1, 8):
    rec = blank_record()
    rec.update({"lid": i, "code": "WL-%05d" % i, "brand": "基恩士",
                "category": "传感器", "model": "FS-V%d" % i,
                "qty": 2, "price": 100.0})
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
root.geometry("1280x820+20+20")
app = wapp.App(root)
app.nb.select(app.tab_inv)
app.load_data()
root.update_idletasks()
root.update()

tree = app.tree
decor = app.decor

# ---- 1 表头字形去掉 ----
check("表头旧字形已清空", tree.heading("_chk", "text") == "")

# ---- 2 覆盖层存在且贴在表头 ----
hc = decor._head_chk
check("表头复选框覆盖层存在", hc is not None and hc.winfo_exists())
info = hc.place_info()
check("表头复选框已放置", bool(info) and int(info["y"]) == 0)
check("表头复选框在首列（x 靠左）", bool(info) and int(info["x"]) < 20)
check("表头复选框高度=表头高", info and abs(int(info["height"]) - app._head_height()) <= 2)
# v1.46.8：表头复选框中心必须与行复选框中心对齐（之前偏右十几像素）
row_cv = decor._chks[list(tree.get_children())[0]]
ri = row_cv.place_info()
head_cx = int(info["x"]) + int(info["width"]) // 2
row_cx = int(ri["x"]) + int(ri["width"]) // 2
check("表头与行复选框中心对齐", abs(head_cx - row_cx) <= 1)


def state_of():
    """从签名里读当前状态（sig=(state,px,w,h)）。"""
    sig = getattr(hc, "_sig", None)
    return sig[0] if sig else None


# ---- 3 状态：无选中=灰边，有选中=勾（不要半选横杠）----
check("初始未选态=off", state_of() is False)
tree.selection_set(list(tree.get_children())[:3])   # 部分选
root.update()
decor.redraw()
check("部分选中也显示勾（无横杠）", state_of() is True)
tree.selection_set(list(tree.get_children()))      # 全选
root.update()
decor.redraw()
check("全选态=on/True", state_of() is True)

# ---- 4 点击全选/全不选 ----
decor._on_head_chk_click(None)
root.update()
check("点表头复选框→全不选", len(tree.selection()) == 0)
decor._on_head_chk_click(None)
root.update()
check("再点→全选当前页", len(tree.selection()) == len(tree.get_children()))

# ---- 5 勾/灰边两态图片缓存都有（partial 横杠已废弃）----
check("勾/灰边两态都已渲染", all(("chk", s, hc._sig[1]) in decor._imgs
                            for s in ("on", "off")))

print("%d/%d 项通过" % (ok[1], ok[0]))
root.destroy()
sys.exit(0 if ok[1] == ok[0] else 1)
