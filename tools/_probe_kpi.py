# -*- coding: utf-8 -*-
"""v1.46.3 探针：库存页 KPI 卡片行（设计稿 4 卡版）。

验证点：
1. 四张卡存在：在库件数 / 库存货值（成本）/ 低库存预警 / 今日出售
2. 数值口径：件数+型号数、成本货值+售价货值副行、低库存橙显、今日出售+毛利
3. 今日出售卡含近 14 天折线画布；有出售数据时折线更新
4. 点「低库存预警」卡 ⇄ 勾选「只看低库存」，KPI 随筛选刷新
5. 左侧筛选面板默认收起，工具栏「筛选」可切换
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
# qty 精心设计：总量 19，低库存 2 条（qty≤3 且未售完）
rows = [
    {"code": "WL-00001", "qty": 1, "price": 100.0, "model": "FS-V1", "listed": 1},
    {"code": "WL-00002", "qty": 3, "price": 50.25, "model": "FS-V2", "listed": 1},
    {"code": "WL-00003", "qty": 10, "price": 200.0, "model": "FS-V3", "listed": 1},
    {"code": "WL-00004", "qty": 0, "price": 80.0, "model": "FS-V1", "listed": 1},
    {"code": "WL-00005", "qty": 5, "price": 12.5, "model": "FS-V5", "listed": 0},
]
for i, extra in enumerate(rows, 1):
    rec = blank_record()
    rec.update({"lid": i, "brand": "基恩士", "category": "传感器"})
    rec.update(extra)
    st.insert(rec)
# WL-00004 置为已售完（sold_out 非录入字段，只能由出售/SQL 设置）
st.conn.execute("UPDATE items SET sold_out=1 WHERE code='WL-00004'")
# 今日一笔出售：金额 500、2 件、成本 200/件 → 毛利 = 500 - 400 = 100
st.conn.execute(
    "INSERT INTO sales (item_id, code, model, qty, price, total, cost, sale_date) "
    "VALUES (1, 'WL-00001', 'FS-V1', 2, 250.0, 500.0, 200.0, ?)",
    (wapp.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
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

# ---- 1 四张卡 ----
check("四张 KPI 卡齐", sorted(kv) == ["count", "low", "today", "val"]
      and all(v.winfo_exists() for v in kv.values()))
low_card = kv["low"].master.master.master
check("低库存卡带手型光标", str(low_card.cget("cursor")) == "hand2")

# ---- 2 数值 ----
check("在库件数 19 · 4 个型号", kv["count"].cget("text") == "19"
      and "4 个型号" in kv["count"].master.winfo_children()[1].cget("text"))
check("副行 命中 5 / 共 5 条",
      "命中 5 / 共 5 条" in app.kpi_subs["count"][0].cget("text"))
check("成本货值 ¥0 + 售价货值 ¥2,313",
      kv["val"].cget("text") == "¥0"
      and app.kpi_subs["val"][1].cget("text") == "¥2,313")

# ---- 3 今日出售 ----
check("今日出售 ¥500 · 2 件", kv["today"].cget("text") == "¥500"
      and "· 2 件" in app.kpi_units["today"].cget("text"))
check("毛利副行 ¥100", "¥100" in app.kpi_subs["today"][1].cget("text"))
check("折线画布存在且有线段", app.kpi_spark.winfo_exists()
      and len(app.kpi_spark.find_all()) > 0)

# ---- 4 低库存 ----
check("低库存 2 项 且警示橙", kv["low"].cget("text") == "2"
      and kv["low"].cget("fg") == C.CLR_WARN)
app.var_kw.set("WL-00003")
app.apply_filters()
root.update()
check("筛选后 KPI 跟随（件数 10、命中 1/5）", kv["count"].cget("text") == "10"
      and "命中 1 / 共 5 条" in app.kpi_subs["count"][0].cget("text"))
check("无低库存时灰显", kv["low"].cget("text") == "0"
      and kv["low"].cget("fg") == C.CLR_MUTED)
app.var_kw.set("")
app.apply_filters()
root.update()

# ---- 5 点击低库存卡切换筛选 ----
check("点击前未勾选", app.var_low_only.get() is False)
app._kpi_low_click()
root.update()
check("点击低库存卡 → 勾选只看低库存", app.var_low_only.get() is True
      and len(app.filtered) == 2)
app._kpi_low_click()
root.update()
check("再点一次 → 取消", app.var_low_only.get() is False
      and len(app.filtered) == 5)

# ---- 6 筛选面板默认收起 + 开关 ----
check("筛选面板默认收起", not app.frm_filter_panel.winfo_ismapped()
      and not app.settings.get("filter_panel"))
app._toggle_filter_panel()
root.update()
check("点筛选 → 面板展开", app.frm_filter_panel.winfo_ismapped()
      and app.settings.get("filter_panel") is True)
app._toggle_filter_panel()
root.update()
check("再点筛选 → 收起", not app.frm_filter_panel.winfo_ismapped())

# ---- 7 汇总条仍正常 ----
check("汇总条命中 5 / 5", "5 / 5" in app.lbl_sum_hit.cget("text"))
check("汇总条货值 2,313.25", "2,313.25" in app.lbl_sum_val.cget("text"))

# ---- 8 侧栏「设置」入口 ----
check("导航注册设置命令", "设置" in app.nav._cmds
      and callable(app.nav._cmds["设置"]))
sysgrp = dict((g[0], g[1]) for g in app.nav.groups)["系统"]
check("设置项挂在系统组", (None, "设置") in sysgrp)

root.destroy()
print("%d/%d 项通过" % (ok[1], ok[0]))
sys.exit(0 if ok[1] == ok[0] else 1)
