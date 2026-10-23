# -*- coding: utf-8 -*-
"""v1.10.2 界面验证 + 截屏：筛选区与编辑弹窗支持手动输入。

① 库存页筛选区：品牌/品类/成色/货架可手动输入（输入即筛，包含匹配）；
② 编辑弹窗：品牌/品类/成色/货架为可输入下拉（有历史出下拉，无历史也能打字）；
③ 出售/出库页品牌筛选可手动输入。
"""
import os
import sys
import tempfile
import tkinter as tk
from tkinter import ttk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.editor import RecordDialog  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_manual_")
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

data = [
    ("WL-00001", "罗技", "外设", "G502 LIGHTSPEED", "99新", 389.5, 12, "3排A-1", 1),
    ("WL-00002", "Apple", "手机", "A2634", "95新", 2899.0, 3, "7排B-2", 1),
    ("WL-00003", "戴尔", "显示器", "U2720Q", "9成新", 1580.0, 2, "10排A架旁", 1),
    ("WL-00004", "小米", "穿戴", "SPP4020", "全新", 199.9, 30, "4排B-1", 0),
]
app.store.insert_many([blank_record() | {"code": c, "brand": b, "category": cat,
                                         "model": m, "condition": cond, "price": p,
                                         "qty": q, "shelf": sh, "listed": l}
                       for c, b, cat, m, cond, p, q, sh, l in data])
app.load_data()
root.deiconify()
root.attributes("-topmost", True)
root.update()

print("== 1. 库存页筛选区可手动输入 ==")
for k in ("brand", "category", "condition", "shelf"):
    check("筛选框「%s」可输入" % k,
          str(app.f_combos[k].cget("state")) == "normal",
          str(app.f_combos[k].cget("state")))
check("筛选框「上架状态」保持只读",
      str(app.f_combos["listed"].cget("state")) == "readonly")

app.f_vars["brand"].set("罗")
app.apply_filters()
check("输入品牌子串「罗」筛出罗技",
      len(app.filtered) == 1 and app.filtered[0]["brand"] == "罗技",
      str([r["brand"] for r in app.filtered]))
app.f_vars["brand"].set("APP")
app.apply_filters()
check("输入大写「APP」命中 Apple（不区分大小写）",
      len(app.filtered) == 1 and app.filtered[0]["brand"] == "Apple",
      str([r["brand"] for r in app.filtered]))
app.f_vars["brand"].set("不存在的品牌")
app.apply_filters()
check("输入不存在的品牌筛出 0 条", len(app.filtered) == 0)
app.reset_filters()
check("重置后恢复 4 条", len(app.filtered) == 4, str(len(app.filtered)))

print("== 2. 编辑弹窗：可输入下拉 ==")
dlg = RecordDialog(root, dict(app.records[0]), app.suggestions(), "编辑记录", app.fam)
dlg.update()


def _all_combos(w):
    out = []
    for c in w.winfo_children():
        if isinstance(c, ttk.Combobox):
            out.append(c)
        out.extend(_all_combos(c))
    return out


cbs = {k: [w for w in _all_combos(dlg)
           if str(w.cget("textvariable")) == str(dlg.vars[k])]
       for k in ("brand", "category", "condition", "shelf")}
for k, ws in cbs.items():
    check("弹窗「%s」为可输入下拉" % k,
          bool(ws) and str(ws[0].cget("state")) != "readonly",
          "state=%r" % (str(ws[0].cget("state")) if ws else None))
check("弹窗品牌下拉含历史建议", "罗技" in list(cbs["brand"][0].cget("values")),
      str(list(cbs["brand"][0].cget("values"))[:5]))
dlg.vars["brand"].set("哈曼卡顿-新品牌")
dlg.vars["model"].set("NEW-M1")
dlg._save()
check("手动输入的新品牌可保存",
      dlg.result and dlg.result["brand"] == "哈曼卡顿-新品牌",
      str(dlg.result and dlg.result["brand"]))
dlg.destroy()

# 无历史建议的空库也用下拉（不再是普通输入框）
dlg2 = RecordDialog(root, blank_record(), {}, "新增记录", app.fam)
dlg2.update()
cbs2 = [w for w in _all_combos(dlg2)
        if str(w.cget("textvariable")) == str(dlg2.vars["brand"])]
check("无历史时品牌仍是可输入下拉",
      bool(cbs2) and str(cbs2[0].cget("state")) != "readonly",
      "state=%r" % (str(cbs2[0].cget("state")) if cbs2 else None))
dlg2.destroy()

print("== 3. 出售/出库页品牌筛选 ==")
rec_apple = [r for r in app.records if r["brand"] == "Apple"][0]
app.store.add_sale(rec_apple["id"], 1, 350.0, buyer="测试", sale_date="2026-10-09")
app.load_data()
app.nb.select(1)
root.update()
tb = app.tab_sales
check("出售页品牌筛选可输入",
      str(tb.cb_brand.cget("state")) != "readonly",
      str(tb.cb_brand.cget("state")))
tb.var_brand.set("AP")
tb.refresh_rows()
check("出售页输入品牌子串可筛", any(r["brand"] == "Apple" for r in tb.rows),
      str([r["brand"] for r in tb.rows]))
tb.var_brand.set("全部")
tb.refresh_rows()

# 截屏：筛选区（输入品牌子串后）
app.nb.select(0)
root.update()
app.f_vars["brand"].set("罗")
app.apply_filters()
root.update()
screenshot.capture_window("1.10.2", os.path.join(OUT, "manual_filter.png"))
app.f_vars["brand"].set("全部")
app.apply_filters()

# 截屏：编辑弹窗
dlg3 = RecordDialog(root, dict(app.records[1]), app.suggestions(), "编辑记录", app.fam)
dlg3.update()
screenshot.capture_window("编辑记录", os.path.join(OUT, "manual_editor.png"))
dlg3.destroy()

print()
if FAILS:
    print("FAILURES: %d -> %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("ALL SHOT CHECKS PASSED")
