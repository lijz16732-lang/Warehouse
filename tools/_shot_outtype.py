# -*- coding: utf-8 -*-
"""v1.10.1 新增功能验证 + 截屏：修改出库类型（出库维修 → 修好卖出）。

① 数据层：改类型（非销售 → 销售 / 销售 → 非销售 / 批量）；
② 界面：修改出库类型弹窗（选销售时出现售价/买家/地址；选非销售时不出现）；
③ 出库记录页与出售记录页的入口按钮 + 改完后两页同步。
"""
import os
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.sales import OutTypeDialog  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_outtype_")
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
    ("WL-00001", "小米", "手机", "红米 K40", "9成新", 800.0, 4, "6排A-3", 1),
    ("WL-00002", "Apple", "手机", "A2634", "95新", 2899.0, 3, "7排B-2", 1),
    ("WL-00003", "戴尔", "显示器", "U2720Q", "9成新", 1580.0, 2, "8排C-1", 1),
]
app.store.insert_many([blank_record() | {"code": c, "brand": b, "category": cat,
                                         "model": m, "condition": cond, "price": p,
                                         "qty": q, "shelf": sh, "listed": l}
                       for c, b, cat, m, cond, p, q, sh, l in data])
app.load_data()
recs = {r["code"]: r for r in app.store.all_records()}

# 一笔出售（有买家与地址，供地址下拉用）、一笔送修、一笔报废
app.store.add_sale(recs["WL-00002"]["id"], 1, 3100.0, buyer="李四",
                   sale_date="2026-10-02", address="北京市朝阳区建国路 88 号 SOHO 现代城 B 座")
app.store.add_sale(recs["WL-00001"]["id"], 2, 0, sale_date="2026-10-05",
                   remark="屏幕碎裂，送修", out_type="借出")
app.store.add_sale(recs["WL-00003"]["id"], 1, 0, sale_date="2026-10-06",
                   remark="外壳破损", out_type="其他")
app.load_data()

print("== 1. 数据层：改类型 ==")
send = [r for r in app.store.list_sales() if r["out_type"] == "借出"][0]
qty_before = int([r for r in app.store.all_records()
                  if r["id"] == send["item_id"]][0]["qty"])
ok1, msg1 = app.store.update_sale_type(
    send["id"], "销售", price=520.0, buyer="王五",
    address="上海市浦东新区世纪大道 100 号", remark="已修好，卖出",
    sale_date="2026-10-08")
check("借出（送修）可改为销售", ok1, msg1)
row = [r for r in app.store.list_sales() if r["id"] == send["id"]][0]
check("类型/金额/买家/地址都已更新",
      row["out_type"] == "销售" and float(row["total"]) == 1040.0
      and row["buyer"] == "王五" and row["address"].startswith("上海市"),
      str((row["out_type"], row["total"], row["buyer"], row["address"])))
check("改类型不重复扣库存",
      int([r for r in app.store.all_records()
           if r["id"] == send["item_id"]][0]["qty"]) == qty_before,
      "%s vs %s" % (qty_before, [r for r in app.store.all_records()
                                 if r["id"] == send["item_id"]][0]["qty"]))
check("出售页已包含这笔", len(app.store.list_sales(scope="sale")) == 2,
      str(len(app.store.list_sales(scope="sale"))))

print("== 2. 修改出库类型弹窗 ==")
app.load_data()
root.deiconify()
root.geometry("1500x880+60+30")
app.nb.select(2)
root.update()
ob = app.tab_out
ob.refresh_tab()
root.update()

target = [r for r in app.store.list_sales() if r["out_type"] == "其他"][0]
dlg = OutTypeDialog(root, [target], app.fam,
                    buyers=app.store.buyer_names(),
                    addr_map=app.store.buyer_address_map())
dlg.update()
check("弹窗有全部表单行",
      set(dlg.row_frames) == {"type", "price", "buyer", "address", "date", "remark"},
      str(sorted(dlg.row_frames)))
check("默认类型＝当前类型", dlg.var_type.get() == "其他", dlg.var_type.get())
check("选非销售时不显示售价行",
      dlg.row_frames["price"].winfo_manager() != "pack",
      str(dlg.row_frames["price"].winfo_manager()))
dlg.var_type.set("销售")
dlg._apply_type()
dlg.update()
check("选销售后出现售价/买家/地址行",
      all(dlg.row_frames[k].winfo_manager() == "pack"
          for k in ("price", "buyer", "address")),
      str({k: dlg.row_frames[k].winfo_manager()
           for k in ("price", "buyer", "address")}))
dlg.var_price.set("888")
dlg.var_buyer.set("李四")
dlg._fill_addr()
check("选历史买家自动带出地址",
      dlg.var_addr.get() == "北京市朝阳区建国路 88 号 SOHO 现代城 B 座",
      dlg.var_addr.get())
dlg.var_date.set("2026-10-08")
dlg.var_remark.set("外壳破损，修好后卖出")
dlg.attributes("-topmost", True)
dlg.lift()
dlg.update()
screenshot.capture_window("修改出库类型", os.path.join(OUT, "outtype_dialog.png"))
print("shot -> outtype_dialog.png（改为销售）")
dlg._ok()
check("弹窗返回销售表单结果",
      dlg.result and dlg.result["out_type"] == "销售"
      and dlg.result["price"] == 888.0 and dlg.result["buyer"] == "李四",
      str(dlg.result))

# 非销售分支的界面
d2 = OutTypeDialog(root, [target], app.fam,
                   buyers=app.store.buyer_names(),
                   addr_map=app.store.buyer_address_map())
d2.update()
d2.var_type.set("损耗")
d2._apply_type()
d2.update()
check("选非销售时售价行隐藏",
      d2.row_frames["price"].winfo_manager() != "pack",
      str(d2.row_frames["price"].winfo_manager()))
check("非销售提示文案含「不计销售额」",
      "不计销售额" in d2.lbl_total.cget("text"), d2.lbl_total.cget("text"))
d2.attributes("-topmost", True)
d2.lift()
d2.update()
screenshot.capture_window("修改出库类型", os.path.join(OUT, "outtype_dialog_out.png"))
print("shot -> outtype_dialog_out.png（改为损耗）")
d2._ok()
check("非销售结果不含金额",
      d2.result and d2.result["out_type"] == "损耗" and d2.result["price"] == 0.0,
      str(d2.result))

# 多选：批量
d3 = OutTypeDialog(root, app.store.list_sales()[:2], app.fam)
d3.update()
try:
    vals = list(d3.row_frames["type"].winfo_children()[1].cget("values"))
except Exception:
    vals = []
check("多选下拉不含「销售」", "销售" not in vals, str(vals))
check("多选时不出日期/备注行",
      d3.row_frames["date"].winfo_manager() != "pack"
      and d3.row_frames["remark"].winfo_manager() != "pack")
d3._cancel()

print("== 3. 页面入口与同步 ==")
root.update()
ob = app.tab_out
texts = []


def walk(w):
    for c in w.winfo_children():
        try:
            if c.winfo_class() in ("TButton",):
                texts.append(str(c.cget("text")))
        except Exception:
            pass
        walk(c)


walk(ob)
check("出库页有「修改类型」按钮", "修改类型" in texts, str(texts))
walk(app.tab_sales)
check("出售页也有「修改类型」按钮", "修改类型" in texts, str(texts))

ok2, msg2 = app.store.update_sale_type(target["id"], "销售", price=888.0,
                                       buyer="李四",
                                       address="北京市朝阳区建国路 88 号 SOHO 现代城 B 座",
                                       remark="修好后卖出", sale_date="2026-10-08")
app.load_data()
app._on_sale_changed()
root.update()
kid = [k for k in ob.tree.get_children()
       if ob.row_map()[k].get("id") == target["id"]]
check("出库页刷新后该行显示为销售",
      bool(kid) and (ob.row_map()[kid[0]].get("out_type") or "") == "销售",
      str([(k, ob.row_map()[k].get("out_type")) for k in ob.tree.get_children()]))
check("出售页能看到改后的记录",
      any(r["code"] == "WL-00003" for r in app.tab_sales.rows),
      str([r["code"] for r in app.tab_sales.rows]))
root.update()
screenshot.capture_window("v1.10.1", os.path.join(OUT, "outtype_page.png"))
print("shot -> outtype_page.png（出库记录页）")

print()
if FAILS:
    print("FAILURES: %d -> %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("ALL SHOT CHECKS PASSED")
app.on_close()
