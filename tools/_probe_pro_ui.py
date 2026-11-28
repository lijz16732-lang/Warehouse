# -*- coding: utf-8 -*-
"""v1.46.0 探针：专业版界面第一阶（深蓝侧栏 + 顶栏 + 表尾汇总条）。

验证点：
1. 侧栏底色为深蓝 CLR_SIDE_BG；品牌区有「仓管家」与版本号
2. 导航项带图标；激活项实心主题蓝底白字
3. 角标：低库存数挂「库存列表」，置 0 后清除
4. 顶栏存在：页面标题 + 分组面包屑 + 共享状态 + 版本；切页后标题联动
5. 表尾汇总条存在且数值正确（命中/数量/货值）；选中后显示「已选 N 行」
6. set_lan(False/True) 文案正确
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk

import wm.app as wapp
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="wm_probe_pro_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP
st = Store(os.path.join(TMP, "warehouse.db"))
for i in range(1, 4):
    rec = blank_record()
    rec.update({"lid": i, "code": "WL-%05d" % i, "brand": "基恩士",
                "category": "传感器", "model": "FS-V%d" % i,
                "qty": 1 if i == 1 else 3, "price": 1280.5})
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

from wm import constants as C

nav = app.nav

# ---- 1/2 侧栏 ----
check("侧栏底色为深蓝 CLR_SIDE_BG", nav.cget("bg") == C.CLR_SIDE_BG)


def _walk(w, out):
    for c in w.winfo_children():
        out.append(c)
        _walk(c, out)


_all = []
_walk(nav, _all)
blob = "|".join(str(w.cget("text")) for w in _all if isinstance(w, tk.Label))
try:
    blob += str(wapp.APP_VERSION)
except Exception:
    pass
check("品牌区含 仓管家 + 版本号", "仓管家" in blob
      and ("v" + wapp.APP_VERSION) in blob)
check("导航项带图标（ICONS 映射生效）", any(IC in blob for IC in ("▤", "¥", "✆")))

lbl0 = nav._item_lbls[0]
check("激活项为主题蓝底白字", lbl0.cget("bg") == C.CLR_ACCENT
      and lbl0.cget("fg") == C.CLR_SIDE_ON)

# ---- 3 角标（先验数据驱动，再验手动接口）----
check("低库存角标由数据驱动", nav._badges.get(0) == "3")
nav.set_badge(0, "6")
root.update()
bdg = nav._badge_lbls[0]
check("角标挂上（库存列表=6，红字）", bdg.cget("text") == "6" and bdg.cget("fg") == "#FCA5A5")
nav.set_badge(0, None)
root.update()
check("角标清除", bdg.cget("text") == "")
app._update_side_stats()   # 数据驱动恢复（顺带验证可重复刷新）
root.update()
check("数据驱动角标可恢复", nav._badges.get(0) == "3")

# ---- 4 顶栏 ----
tb_title = app.lbl_topbar.cget("text")
crumb = app.lbl_topbar_crumb.cget("text")
check("顶栏标题=当前页名（库存列表/库存管理）", tb_title == "库存列表" and crumb == "库存管理")
app.show_page(4)   # 手机数据
root.update()
check("切页后顶栏标题联动", app.lbl_topbar.cget("text") == "手机数据"
      and app.lbl_topbar_crumb.cget("text") == "数据报表")
app.show_page(0)
root.update()
check("共享状态初始文案", "共享" in app.lbl_top_share.cget("text"))
nav.set_lan(True, "共享中 · 2 台在线")
check("nav.set_lan(True) 绿点文案", app.nav._lbl_lan.cget("text") == "● 共享中 · 2 台在线"
      and app.nav._lbl_lan.cget("fg") == "#4ADE80")

# ---- 5 表尾汇总条 ----
check("汇总条存在", getattr(app, "lbl_sum_hit", None) is not None)
hit_txt = app.lbl_sum_hit.cget("text")
qty_txt = app.lbl_sum_qty.cget("text")
val_txt = app.lbl_sum_val.cget("text")
check("命中数正确（3/3）", "3 / 3" in hit_txt)
check("数量合计正确（7 件）", "7" in qty_txt)
# 精确值: 3 条 qty=1,3,3 price=1280.5 → 1280.5*7 = 8,963.50
check("货值精确 8,963.50", "8,963.50" in val_txt)

app.tree.selection_set([str(r["id"]) for r in app.filtered[:2]])
root.update()
sel_txt = app.lbl_sum_sel.cget("text")
check("选中后汇总条显示 已选 2 行", sel_txt == "已选 2 行"
      and app.lbl_sum_sel.cget("fg") == C.CLR_ACCENT)

root.destroy()
print("%d/%d 项通过" % (ok[1], ok[0]))
sys.exit(0 if ok[1] == ok[0] else 1)
