# -*- coding: utf-8 -*-
"""临时脚本：v1.9.0 新功能界面截图验证。"""
import os
import shutil
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.extras import (BatchEditDialog, BuyerDialog, PurchaseDialog,  # noqa: E402
                       PurchaseListDialog, RecycleBinDialog)
from wm.store import Store, blank_record  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_v190_")
wapp.app_dir = lambda: TMP
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

st = Store(os.path.join(TMP, "data", "warehouse.db"))
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)

data = [
    ("WL-00001", "罗技", "外设", "MX MASTER 3", "99新", 599.0, 2, "6排A-3 / 7排A-1", 1),
    ("WL-00002", "Apple", "手机", "A2634", "95新", 2899.0, 3, "7排B-2", 1),
    ("WL-00003", "西门子", "驱动器", "V20", "全新", 1200.0, 1, "5排A-1", 0),
    ("WL-00004", "戴尔", "显示器", "U2720Q", "9成新", 1580.0, 5, "8排C-1", 1),
    ("WL-00005", "联想", "笔记本", "X1C Gen9", "8成新", 3600.0, 2, "9排A-2", 0),
    ("WL-00006", "华为", "网络", "S5720", "9成新", 2100.0, 12, "4排A-1", 1),
]
app.store.insert_many([blank_record() | {"code": c, "brand": b, "category": cat, "model": m,
                                         "condition": cond, "price": p, "qty": q,
                                         "shelf": sh, "listed": l}
                       for c, b, cat, m, cond, p, q, sh, l in data])
app.load_data()
recs = {r["code"]: r for r in app.store.all_records()}
# 采购 + 出售（制造趋势/利润数据）
app.store.add_purchase(recs["WL-00001"]["id"], 10, 320.0, supplier="深圳老王",
                       purchase_date="2026-08-12")
app.store.add_purchase(recs["WL-00001"]["id"], 6, 360.0, supplier="深圳老王",
                       purchase_date="2026-09-20")
app.store.add_purchase(recs["WL-00004"]["id"], 8, 900.0, supplier="广州老李",
                       purchase_date="2026-09-05")
for code, q, price, buyer, d in (("WL-00001", 1, 650.0, "张三", "2026-08-20"),
                                 ("WL-00004", 2, 1750.0, "李四", "2026-09-15"),
                                 ("WL-00002", 1, 2900.0, "张三", "2026-09-28"),
                                 ("WL-00005", 1, 3800.0, "王五", "2026-10-05"),
                                 ("WL-00006", 5, 2300.0, "李四", "2026-10-06")):
    app.store.add_sale(recs[code]["id"], q, price, buyer=buyer, sale_date=d)
app.store.set_meta("monthly_target", 20000)
app.load_data()
app.tab_sales.refresh_rows()
app.var_low_only.set(True)
app.apply_filters()
app.tab_sales._toggle_trend()
root.deiconify()
root.geometry("1400x880+100+40")
root.update()

holder = []
STEPS = []


def add(fn):
    STEPS.append(fn)
    return fn


@add
def s_main():
    screenshot.capture(os.path.join(OUT, "v190_main.png"))
    print("shot -> v190_main.png（低库存筛选 + 工具栏）")


@add
def s_sales():
    app.var_low_only.set(False)
    app.apply_filters()
    app.nb.select(1)
    root.update()
    root.after(800, None)


@add
def s_sales_shot():
    screenshot.capture(os.path.join(OUT, "v190_sales.png"))
    print("shot -> v190_sales.png（趋势图 + 目标 + 买家）")
    app.nb.select(0)
    root.update()
    root.after(300, None)


@add
def s_recycle():
    app.store.delete_ids([recs["WL-00003"]["id"]])
    app.load_data()
    d = RecycleBinDialog(app, app.fam)
    holder.append(d)
    d.win.update()
    root.after(600, None)


@add
def s_recycle_shot():
    d = holder[-1]
    d.win.attributes("-topmost", True)
    d.win.lift()
    d.win.update()
    screenshot.capture(os.path.join(OUT, "v190_recycle.png"))
    print("shot -> v190_recycle.png")
    d.win.destroy()


@add
def s_batch():
    app.tree.selection_set([str(r["id"]) for r in app.store.all_records()[:3]])
    d = BatchEditDialog(app, app.fam)
    holder.append(d)
    d.win.update()
    root.after(500, None)


@add
def s_batch_shot():
    d = holder[-1]
    d.win.attributes("-topmost", True)
    d.win.lift()
    d.win.update()
    screenshot.capture(os.path.join(OUT, "v190_batch.png"))
    print("shot -> v190_batch.png")
    d.win.destroy()


@add
def s_purchase():
    d = PurchaseDialog(root, recs["WL-00006"], app.fam)
    holder.append(d)
    d.update()
    root.after(500, None)


@add
def s_purchase_shot():
    d = holder[-1]
    d.attributes("-topmost", True)
    d.lift()
    d.update()
    screenshot.capture(os.path.join(OUT, "v190_purchase.png"))
    print("shot -> v190_purchase.png")
    d.destroy()


@add
def s_purchlist():
    d = PurchaseListDialog(app, app.fam)
    holder.append(d)
    d.win.update()
    root.after(500, None)


@add
def s_purchlist_shot():
    d = holder[-1]
    d.win.attributes("-topmost", True)
    d.win.lift()
    d.win.update()
    screenshot.capture(os.path.join(OUT, "v190_purchlist.png"))
    print("shot -> v190_purchlist.png")
    d.win.destroy()


@add
def s_buyer():
    d = BuyerDialog(app, app.fam)
    holder.append(d)
    d.win.update()
    root.after(500, s_buyer_shot)


def s_buyer_shot():
    d = holder[-1]
    d.win.attributes("-topmost", True)
    d.win.lift()
    d.win.update()
    screenshot.capture(os.path.join(OUT, "v190_buyer.png"))
    print("shot -> v190_buyer.png")
    d.win.destroy()
    root.destroy()


def run(i=0):
    if i >= len(STEPS):
        return
    STEPS[i]()
    root.after(700, lambda: run(i + 1))


root.after(900, run)
root.mainloop()
shutil.rmtree(TMP, ignore_errors=True)
print("done")
