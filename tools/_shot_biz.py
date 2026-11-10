# -*- coding: utf-8 -*-
"""探针：v1.32.0 四个新页面（客户 / 退货 / 利润 / 盘点）。"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.returns import ReturnDialog  # noqa: E402
from wm.stocktake import NewStocktakeDialog, StocktakeDialog  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

tmp = tempfile.mkdtemp(prefix="wm_shot_biz_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()

ctypes.windll.user32.SetCursorPos(2, 2)

root = tk.Tk()
app = wapp.App(root)

rows = []
for i, (brand, cat, model, price, qty, cost) in enumerate([
        ("ABB", "变频器", "ACS510-01", 1200.0, 10, 800.0),
        ("西门子", "PLC", "S7-200 CN", 900.0, 6, 600.0),
        ("三菱", "伺服", "MR-J4-70A", 1500.0, 4, 1100.0),
        ("台达", "变频器", "VFD-M", 600.0, 8, 380.0),
        ("施耐德", "断路器", "NSX100", 700.0, 5, 480.0)], start=1):
    r = blank_record()
    r.update({"code": "WL-%05d" % i, "brand": brand, "category": cat,
              "model": model, "price": price, "qty": qty, "shelf": "6排A-3",
              "condition": "全新", "listed": 1, "remark": "利润表测试"})
    rows.append(r)
app.store.insert_many(rows)
app.store._execute('UPDATE items SET cost = 800.0 WHERE code = ?', ("WL-00001",))
app.store._execute('UPDATE items SET cost = 600.0 WHERE code = ?', ("WL-00002",))
app.store._execute('UPDATE items SET cost = 1100.0 WHERE code = ?', ("WL-00003",))
app.store._execute('UPDATE items SET cost = 380.0 WHERE code = ?', ("WL-00004",))
app.store._execute('UPDATE items SET cost = 480.0 WHERE code = ?', ("WL-00005",))
app.load_data()

cs = {r["code"]: app.store.find_by_code(r["code"]) for r in rows}
app.store.add_sale(cs["WL-00001"], 2, 1200.0, buyer="张三", sale_date="2026-11-02")
app.store.add_sale(cs["WL-00002"], 1, 900.0, buyer="李四", sale_date="2026-11-03")
app.store.add_sale(cs["WL-00003"], 1, 1500.0, buyer="张三", sale_date="2026-11-05")
app.store.add_sale(cs["WL-00004"], 3, 600.0, buyer="王五", sale_date="2026-10-28")
sid1 = [s for s in app.store.list_sales(scope="sale")
        if s["code"] == "WL-00001"][0]["id"]
app.store.add_return(sid1, 1, restock=True, return_date="2026-11-06",
                     remark="客户尺寸不合")
app.store.add_customer("张三", "13800000000", "上海市浦东新区", "VIP", "老客户")
app.store.import_buyers()
app.load_data()

ok = True


def chk(label, cond, extra=""):
    global ok
    print(("  [PASS] " if cond else "  [FAIL] ") + label + ("" if cond else "  %s" % (extra,)))
    if not cond:
        ok = False


def shot(name):
    root.update_idletasks()
    root.update()
    screenshot.capture_window("仓管家 · 仓库管理系统", os.path.join(OUT, name))


def pump(n=3):
    for _ in range(n):
        root.update_idletasks()
        root.update()


pump()

print("== 1. 导航与页面 ==")
chk("四个新页已注册", app.nb.index("end") == 10, app.nb.index("end"))
nav_items = dict(app.nav._item_lbls)
chk("导航有「客户管理」", 6 in nav_items and nav_items[6].cget("text").strip() == "客户管理",
    nav_items.get(6))
chk("导航有「盘点单」", 9 in nav_items and nav_items[9].cget("text").strip() == "盘点单",
    nav_items.get(9))

print("== 2. 客户管理页 ==")
app.show_page(6)
pump()
chk("客户表有 3 个客户", len(app.tab_customer.tree.get_children()) == 3,
    [app.tab_customer.tree.item(i, "values") for i in app.tab_customer.tree.get_children()])
zs = [r for r in app.tab_customer.rows if r["name"] == "张三"][0]
chk("张三累计消费 3900", abs(zs["amount"] - 3900.0) < 0.01, zs)
chk("张三成交 2 笔", zs["count"] == 2, zs)
shot("biz_customer.png")

print("== 3. 销售利润表 ==")
app.show_page(8)
pump()
prof = app.tab_profit
chk("默认按品牌汇总", len(prof.view) == 4, [v["key"] for v in prof.view])
abb = [v for v in prof.view if v["key"] == "ABB"][0]
chk("ABB 实收 2400-1200=1200", abs(abb["amount"] - 1200.0) < 0.01, abb)
chk("ABB 净成本 1600-800=800", abs(abb["cost"] - 800.0) < 0.01, abb)
chk("ABB 毛利 400", abs(abb["profit"] - 400.0) < 0.01, abb)
chk("KPI 毛利合计 1760", prof.kpi["profit"].cget("text") == "1,760.00",
    prof.kpi["profit"].cget("text"))
shot("biz_profit.png")
prof.var_group.set("sale")
prof.refresh_rows()
pump()
chk("逐笔 4 行", len(prof.tree.get_children()) == 4, len(prof.tree.get_children()))
chk("逐笔列头是出售日期",
    prof.tree.heading("date")["text"] == "出售日期", prof.tree.heading("date"))
prof.var_group.set("month")
prof.refresh_rows()
pump()
chk("按月 2 行（10/11 月）", len(prof.view) == 2, [v["key"] for v in prof.view])

print("== 4. 销售退货页 ==")
app.show_page(7)
pump()
rt = app.tab_return
chk("退货表 1 行", len(rt.tree.get_children()) == 1, len(rt.tree.get_children()))
chk("KPI 退款 1200", rt.kpi["refund"].cget("text") == "1,200.00",
    rt.kpi["refund"].cget("text"))
shot("biz_return.png")

dlg = ReturnDialog(root, app, app.fam)
pump()
chk("退货弹窗列出可退记录", len(dlg.tree.get_children()) >= 2,
    len(dlg.tree.get_children()))
dlg.tree.selection_set(dlg.tree.get_children()[0])
pump()
chk("选中后自动填数量", dlg.var_qty.get() != "", dlg.var_qty.get())
chk("退款跟着数量算", dlg.var_refund.get() not in ("", "0.00"), dlg.var_refund.get())
root.update_idletasks()
root.update()
screenshot.capture_window("登记销售退货", os.path.join(OUT, "biz_return_dialog.png"))
dlg._cancel()
pump()

print("== 5. 盘点单 ==")
app.show_page(9)
pump()
stt = app.tab_stocktake
chk("盘点单页初始为空", len(stt.tree.get_children()) == 0,
    len(stt.tree.get_children()))

nd = NewStocktakeDialog(root, app, app.fam)
pump()
root.update_idletasks()
root.update()
screenshot.capture_window("新建盘点单", os.path.join(OUT, "biz_st_new.png"))
nd._ok()
st_id = nd.result[0] if nd.result else 0
chk("生成盘点单成功", st_id > 0, nd.result)
stt.refresh_rows()
pump()
chk("列表出现 1 张单", len(stt.tree.get_children()) == 1, len(stt.tree.get_children()))

sd = StocktakeDialog(root, app, st_id, app.fam)
pump()
items = sd.detail["rows"]
chk("盘点明细 5 条（卖出后仍 >0 的）", len(items) == 5, len(items))
r0 = items[0]
app.store.set_stocktake_qty(r0["id"], int(r0["book_qty"]) - 2, "盘亏 2 件")
sd.refresh_rows()
pump()
chk("差异显示 -2", sd.lbl_stat.cget("text").find("净变动 -2") >= 0,
    sd.lbl_stat.cget("text"))
root.update_idletasks()
root.update()
screenshot.capture_window("盘点单", os.path.join(OUT, "biz_st_detail.png"))
before = [r for r in app.store.all_records() if int(r["id"]) == int(r0["item_id"])][0]
sd.commit()
pump()
after = [r for r in app.store.all_records() if int(r["id"]) == int(r0["item_id"])][0]
chk("提交后库存按实盘改",
    int(after["qty"]) == int(before["qty"]) - 2, (before["qty"], after["qty"]))
chk("状态变已提交", sd.lbl_status.cget("text") == "已提交",
    sd.lbl_status.cget("text"))
sd._close()
pump()
stt.refresh_rows()
chk("列表显示已提交", stt.tree.item(stt.tree.get_children()[0], "values")[2] == "已提交",
    stt.tree.item(stt.tree.get_children()[0], "values"))
shot("biz_stocktake.png")

print()
print("ALL OK" if ok else "HAS FAILURES")
root.destroy()
