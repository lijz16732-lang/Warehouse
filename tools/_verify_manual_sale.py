# -*- coding: utf-8 -*-
"""验证（v1.10.8）：出售记录「+ 登记出售」手动补录。

覆盖：
  1. 出售页工具栏有「+ 登记出售」按钮
  2. 手填编号命中库存 → 自动带出品牌/品类/型号/货架/成本单价
  3. 校验：什么都不填 / 数量为 0 → 不通过，弹窗不关闭
  4. 正常登记 → 出售记录出现、KPI 计数 +1、库存数量完全不变
  5. 撤销手动记录 → 记录消失、库存仍不变
  6. 编号命中库存时给出「不扣库存」提示
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm import sales as wsales  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="wm_manual_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([
    blank_record() | {"code": "WL-00001", "brand": "ABB", "category": "PLC",
                      "model": "SM-1234", "shelf": "A-01", "qty": 5,
                      "price": 100.0, "listed": 1},
    blank_record() | {"code": "WL-00002", "brand": "西门子", "category": "变频器",
                      "model": "G120", "shelf": "B-02", "qty": 3,
                      "price": 500.0, "listed": 1},
])
# 成本单价由「采购入库」写入（insert 不带 cost），这里给 WL-00001 登记成本 80
rid = app.store.find_by_code("WL-00001")
app.store._execute('UPDATE items SET "cost" = ? WHERE id = ?', (80.0, rid))
app.load_data()
app.nb.select(app.tab_sales)
root.geometry("1500x900+60+40")
root.deiconify()
root.update()

print("== 1. 工具栏按钮 ==")


def walk(w):
    for c in w.winfo_children():
        yield c
        yield from walk(c)


texts = [str(c.cget("text")) for c in walk(app.tab_sales)
         if c.winfo_class() in ("TButton",)]
check("出售页有「+ 登记出售」按钮", "+ 登记出售" in texts, texts[:10])
check("出库页没有该按钮",
      "+ 登记出售" not in [str(c.cget("text")) for c in walk(app.tab_out)
                          if c.winfo_class() == "TButton"])

print("== 2. 弹窗：编号自动带出 + 校验 ==")
items = app.store.all_records()
dlg = wsales.ManualSaleDialog(root, app.fam, buyers=app.store.buyer_names(),
                              addr_map=app.store.buyer_address_map(), items=items)
root.update()
dlg.var_code.set("WL-00001")
dlg._fill_from_code()
check("品牌自动带出", dlg.var_brand.get() == "ABB", dlg.var_brand.get())
check("品类自动带出", dlg.var_category.get() == "PLC", dlg.var_category.get())
check("型号自动带出", dlg.var_model.get() == "SM-1234", dlg.var_model.get())
check("货架自动带出", dlg.var_shelf.get() == "A-01", dlg.var_shelf.get())
check("成本单价自动带出", dlg.var_cost.get() == "80.00", dlg.var_cost.get())
check("提示不扣库存", "不会扣它的库存" in dlg.lbl_note.cget("text"),
      dlg.lbl_note.cget("text"))

# 未登记过采购成本的商品：按原单价估算（与登记出售时的成本口径一致）
dlg.var_code.set("WL-00002")
for v in (dlg.var_brand, dlg.var_category, dlg.var_model, dlg.var_shelf,
          dlg.var_cost):
    v.set("")
dlg._fill_from_code()
check("未登记成本 → 按原价估算", dlg.var_cost.get() == "500.00",
      dlg.var_cost.get())

dlg.var_brand.set("")
dlg.var_category.set("")
dlg.var_model.set("")
dlg.var_shelf.set("")
dlg.var_code.set("")
dlg._ok()
check("空表单被拦下", dlg.result is None and "至少填写" in dlg.lbl_msg.cget("text"),
      dlg.lbl_msg.cget("text"))

dlg.var_code.set("WL-00001")
dlg._fill_from_code()
dlg.var_qty.set("0")
dlg._ok()
check("数量 0 被拦下", dlg.result is None and "大于 0" in dlg.lbl_msg.cget("text"),
      dlg.lbl_msg.cget("text"))

dlg.var_qty.set("2")
dlg.var_price.set("150")
dlg.var_buyer.set("张三")
dlg.var_addr.set("上海市浦东新区")
dlg.var_remark.set("手动补录")
dlg._refresh_total()
check("合计实时计算", "销售额 300.00" in dlg.lbl_total.cget("text"),
      dlg.lbl_total.cget("text"))
root.update()
screenshot.capture_window("手动登记出售", os.path.join(OUT, "manual_sale_dialog.png"))
dlg._ok()
data = dlg.result or {}
check("表单结果正确", data.get("qty") == 2 and data.get("price") == 150.0
      and data.get("buyer") == "张三", data)
root.update()

print("== 3. 登记后：记录出现、库存不变 ==")
stock_before = {r["code"]: int(r["qty"]) for r in app.store.all_records()}
before_count = len(app.tab_sales.rows)
ok, msg = app.store.add_manual_sale(**data)
app.tab_sales.refresh_rows()
check("登记成功", ok, msg)
check("记录条数 +1", len(app.tab_sales.rows) == before_count + 1,
      "%d -> %d" % (before_count, len(app.tab_sales.rows)))
top = app.tab_sales.rows[0]
check("新记录在最上面且为销售", str(top["code"]) == "WL-00001"
      and (top.get("out_type") or "销售") == "销售", top)
check("总额 = 2 × 150", float(top["total"]) == 300.0, top["total"])
check("item_id 为空（不挂库存）", top.get("item_id") in (None, ""), top.get("item_id"))
check("库存一件没少", {r["code"]: int(r["qty"]) for r in app.store.all_records()}
      == stock_before)
check("KPI 计入了这笔", app.tab_sales.kpi["count"].cget("text") ==
      "%d" % len(app.tab_sales.rows), app.tab_sales.kpi["count"].cget("text"))

print("== 4. 撤销手动记录 ==")
app.store.delete_sale(int(top["id"]))
app.tab_sales.refresh_rows()
check("撤销后记录消失", len(app.tab_sales.rows) == before_count,
      len(app.tab_sales.rows))
check("撤销后库存仍不变",
      {r["code"]: int(r["qty"]) for r in app.store.all_records()} == stock_before)

print("== 5. 页面按钮全流程（走 manual_add 接线）==")
wsales.ask_manual_sale = lambda *a, **k: {
    "code": "", "brand": "库房杂项", "category": "", "model": "旧货清仓",
    "shelf": "", "qty": 3, "price": 20.0, "cost": 5.0, "buyer": "李四",
    "address": "", "sale_date": "", "remark": "手动补录"}
app.tab_sales.refresh_rows()
app.tab_sales.manual_add()
check("按钮流程写入记录", any(str(r.get("model")) == "旧货清仓"
                              for r in app.tab_sales.rows),
      [(r.get("model"), r.get("qty")) for r in app.tab_sales.rows[:3]])
row = next(r for r in app.tab_sales.rows if str(r.get("model")) == "旧货清仓")
check("利润口径 = (20-5)×3", round(float(row["total"]) - float(row["cost"])
                                  * int(row["qty"]), 2) == 45.0,
      (row["total"], row["cost"], row["qty"]))
check("按钮流程不动库存",
      {r["code"]: int(r["qty"]) for r in app.store.all_records()} == stock_before)

print("== 6. 干净演示截图 ==")
dlg2 = wsales.ManualSaleDialog(root, app.fam, buyers=app.store.buyer_names(),
                               addr_map=app.store.buyer_address_map(),
                               items=app.store.all_records())
root.update()
dlg2.var_code.set("WL-00001")
dlg2._fill_from_code()
dlg2.var_qty.set("2")
dlg2.var_price.set("150")
dlg2.var_buyer.set("张三")
dlg2.var_addr.set("上海市浦东新区")
dlg2.var_remark.set("手动补录示例")
root.update()
screenshot.capture_window("手动登记出售",
                          os.path.join(OUT, "manual_sale_dialog.png"))
dlg2.destroy()
root.destroy()
print("\n结果：%d 项，失败 %d 项" % (0, len(FAILS)) if False else
      "\n失败项：%s" % (FAILS or "无"))
sys.exit(1 if FAILS else 0)
