# -*- coding: utf-8 -*-
"""临时脚本：出售功能界面截图（库存页工具栏 / 出售记录页 / 登记出售弹窗）。"""
import os
import shutil
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.sales import SaleDialog  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_sales_")
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
]
app.store.insert_many([blank_record() | {"code": c, "brand": b, "category": cat, "model": m,
                                         "condition": cond, "price": p, "qty": q,
                                         "shelf": sh, "listed": l}
                       for c, b, cat, m, cond, p, q, sh, l in data])
app.load_data()
recs = {r["code"]: r for r in app.store.all_records()}
app.store.add_sale(recs["WL-00001"]["id"], 2, 650.0, buyer="张三", sale_date="2026-10-07",
                   remark="微信转账")
app.store.add_sale(recs["WL-00005"]["id"], 2, 3800.0, buyer="李四", sale_date="2026-10-06",
                   remark="上门自提")
app.load_data()
app.tab_sales.refresh_rows()
root.deiconify()
root.geometry("1400x860+120+60")
root.update()

holder = []


def step1():
    screenshot.capture(os.path.join(OUT, "sales_main.png"))
    print("shot -> sales_main.png")
    app.nb.select(1)
    root.update()
    root.after(700, step2)


def step2():
    screenshot.capture(os.path.join(OUT, "sales_tab.png"))
    print("shot -> sales_tab.png")
    app.nb.select(0)
    root.update()
    root.after(300, step3)


def step3():
    rec = [r for r in app.store.all_records() if r["code"] == "WL-00002"][0]
    dlg = SaleDialog(root, rec, app.fam)
    holder.append(dlg)
    dlg.update()
    root.after(500, step4)


def step4():
    dlg = holder[0]
    dlg.attributes("-topmost", True)
    dlg.lift()
    dlg.update()
    screenshot.capture(os.path.join(OUT, "sales_dialog.png"))
    print("shot -> sales_dialog.png | 弹窗:", dlg.geometry())
    dlg.destroy()
    root.destroy()


root.after(900, step1)
root.mainloop()
shutil.rmtree(TMP, ignore_errors=True)
print("done")
