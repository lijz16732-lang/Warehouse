# -*- coding: utf-8 -*-
"""v1.46.1 探针：库存页 KPI 卡片行。

验证点：
1. 五张卡存在：库存条目 / 库存总量 / 库存货值 / 已上架 / 低库存预警
2. 数值与筛选口径一致（命中/总量、件数、货值、已上架数）
3. 低库存数正确且 >0 时为警示橙；=0 时灰显
4. 点「低库存预警」卡 ⇄ 勾选「只看低库存」，KPI 随筛选刷新
5. 汇总条与 KPI 并存不冲突
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

TMP = tempfile.mkdtemp(prefix="wm_probe_kpi_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP
st = Store(os.path.join(TMP, "warehouse.db"))
# qty/price/listed/sold_out 精心设计：低库存 2 条（qty≤3 且未售完；
# 售完=qty 0（入库时派生，不单独存储）
rows = [
    {"code": "WL-00001", "qty": 1, "price": 100.0, "listed": 1},
    {"code": "WL-00002", "qty": 3, "price": 50.25, "listed": 1},
    {"code": "WL-00003", "qty": 10, "price": 200.0, "listed": 1},
    {"code": "WL-00004", "qty": 0, "price": 80.0, "listed": 1},
    {"code": "WL-00005", "qty": 5, "price": 12.5, "listed": 0},
]
for i, extra in enumerate(rows, 1):
    rec = blank_record()
    rec.update({"lid": i, "brand": "基恩士", "category": "传感器"})
    rec.update(extra)
    st.insert(rec)
# WL-00004 置为已售完（sold_out 非录入字段，只能由出售/SQL 设置）
st.conn.execute("UPDATE items SET sold_out=1 WHERE code='WL-00004'")
st.conn.commit()
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

kv = app.kpi_vals

# ---- 1 五张卡 ----
check("五张 KPI 卡齐", len(kv) == 5
      and all(v.winfo_exists() for v in kv.values()))
low_card = kv["low"].master.master.master
check("低库存卡带手型光标", str(low_card.cget("cursor")) == "hand2")

# ---- 2 数值 ----
check("条目数 5 / 5", kv["count"].cget("text") == "5 / 5")
check("总量 19 件", kv["qty"].cget("text") == "19"
      and app.kpi_units["qty"].cget("text") == "件")
check("货值 ¥2,313.25", kv["val"].cget("text") == "¥2,313.25")
check("已上架 4 条", kv["listed"].cget("text") == "4"
      and app.kpi_units["listed"].cget("text") == "条")

# ---- 3 低库存 ----
check("低库存 2 条 且警示橙", kv["low"].cget("text") == "2"
      and kv["low"].cget("fg") == C.CLR_WARN)
# 筛到没有低库存 → 灰显
app.var_low_only.set(True)
app.apply_filters()
root.update()
check("只看低库存后 KPI=2/5、低库存仍 2", kv["count"].cget("text") == "2 / 5")
app.var_low_only.set(False)
app.apply_filters()
root.update()
check("取消后恢复 5 / 5", kv["count"].cget("text") == "5 / 5")

# 关键词筛掉一批 → 全部归零灰显
app.var_kw.set("WL-00003")
app.apply_filters()
root.update()
check("筛选后 KPI 跟随（1 / 5、10 件）", kv["count"].cget("text") == "1 / 5"
      and kv["qty"].cget("text") == "10")
check("无低库存时灰显", kv["low"].cget("text") == "0"
      and kv["low"].cget("fg") == C.CLR_MUTED)
app.var_kw.set("")
app.apply_filters()
root.update()

# ---- 4 点击低库存卡切换筛选 ----
check("点击前未勾选", app.var_low_only.get() is False)
app._kpi_low_click()
root.update()
check("点击低库存卡 → 勾选只看低库存", app.var_low_only.get() is True
      and len(app.filtered) == 2)
app._kpi_low_click()
root.update()
check("再点一次 → 取消", app.var_low_only.get() is False
      and len(app.filtered) == 5)

# ---- 5 汇总条仍正常 ----
check("汇总条命中 5 / 5", "5 / 5" in app.lbl_sum_hit.cget("text"))
check("汇总条货值 2,313.25", "2,313.25" in app.lbl_sum_val.cget("text"))

# ---- 6 侧栏「设置」入口（v1.46.1 补，系统组命令项）----
check("导航注册设置命令", "设置" in app.nav._cmds
      and callable(app.nav._cmds["设置"]))
sysgrp = dict((g[0], g[1]) for g in app.nav.groups)["系统"]
check("设置项挂在系统组", (None, "设置") in sysgrp)
app.open_appearance()
root.update()
win = getattr(app, "_settings_win", None)
check("设置窗口能打开", win is not None and win.winfo_exists()
      and win.title() == "设置")
try:
    win.destroy()
except Exception:
    pass

root.destroy()
print("%d/%d 项通过" % (ok[1], ok[0]))
sys.exit(0 if ok[1] == ok[0] else 1)
