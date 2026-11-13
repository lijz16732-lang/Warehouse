# -*- coding: utf-8 -*-
"""v1.40 手机端新接口探针：退货 / 统计 / 客户 / 回收站 / 盘点 / 挂账。

直接调 mobile.py 的 handler（不启 HTTP），用临时库跑一遍业务闭环。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wm.mobile import (MobileService, handle_add, handle_customers, handle_settle,  # noqa: E402
                       handle_del_item, handle_items, handle_purge,
                       handle_restore, handle_return_sale, handle_returns,
                       handle_sale_undo, handle_sales, handle_sell,
                       handle_stats, handle_stocktake, handle_trash,
                       handle_whoami)
from wm.store import Store  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  -> %s" % extra) if not cond else ""))
    if not cond:
        FAIL.append(name)


class Srv(object):
    def __init__(self, store, write=True):
        self.store = store
        self.mobile = MobileService()
        self.port = 8765
        self._write = write

    def get_store(self):
        return self.store

    def can_write(self, ip):
        return self._write

    def get_warehouse(self):
        return "测试仓"


tmp = tempfile.mkdtemp(prefix="probe_v140_")
st = Store(os.path.join(tmp, "t.db"))
srv = Srv(st)
ip = "192.168.1.50"
code, body, _h = srv.mobile.login(ip, "123456", lambda c: c == "123456",
                                  app_mode=True)
check("登录成功", code == 200 and body.get("ok"), body)
tok = body.get("token") or ""

# ---- 造数据 ----
ids = []
for i in range(3):
    codes = st.generate_codes(1)
    rid = st.insert({"code": codes[0], "brand": "施耐德", "category": "断路器",
                     "model": "S10MD-%d" % i, "price": 100.0 + i, "qty": 1 + i,
                     "shelf": "1排A", "listed": 1, "remark": ""})
    ids.append(rid)
check("造 3 条库存", len(ids) == 3)

sc, sb, _ = handle_sell(srv, ip, tok, {"code": st.all_records()[0]["code"],
                                       "qty": 1, "price": 120, "buyer": "王工",
                                       "paid": 0})
check("手机出售（挂账）成功", sc == 200 and sb.get("ok"), sb)
sale_id = st.list_sales()[-1]["id"]
check("挂账写入 paid=0", int(st.list_sales()[-1].get("paid") or 0) == 0,
      st.list_sales()[-1].get("paid"))

sc, sb, _ = handle_sales(srv, ip, tok, {})
row = sb["sales"][0]
check("出售列表带可退数量", sc == 200 and row.get("left") == 1, row)
check("出售列表带挂账标记", row.get("paid") == 0, row)

# ---- 退货 ----
sc, sb, _ = handle_return_sale(srv, ip, tok, {"sale_id": sale_id, "qty": 1,
                                              "refund": 120, "restock": True})
check("退货成功", sc == 200 and sb.get("ok"), sb)
sc, sb, _ = handle_sales(srv, ip, tok, {})
check("退货后 left 归零", sb["sales"][0]["left"] == 0, sb["sales"][0])
sc, sb, _ = handle_returns(srv, ip, tok, {})
check("退货记录可查", sc == 200 and len(sb["returns"]) == 1, sb)
sc, sb, _ = handle_return_sale(srv, ip, tok, {"sale_id": sale_id, "qty": 1})
check("超退被拒", sc == 400 and not sb.get("ok"), sb)

# ---- 统计 ----
sc, sb, _ = handle_stats(srv, ip, tok, {})
check("统计返回今日/本月/区间", sc == 200 and all(k in sb for k in
                                                ("today", "month", "range")), sb.keys())
check("今日销售额为毛额、实收已扣退款",
      sb["today"]["sales"] == 120 and sb["today"]["amount"] == 0, sb["today"])
check("统计含低库存与应收", "low" in sb and sb["unpaid"]["total"] == 0, sb.get("unpaid"))
check("统计含库存概览", sb["stock"]["items"] == 3, sb["stock"])

# 再卖一笔已付款，看统计有数
rc = st.all_records()[1]
sc, sb, _ = handle_sell(srv, ip, tok, {"code": rc["code"], "qty": 1, "price": 150,
                                       "buyer": "李工", "paid": 1})
check("已收款出售成功", sc == 200 and sb.get("ok"), sb)
sc, sb, _ = handle_stats(srv, ip, tok, {})
check("统计销售额累计 270", sb["today"]["sales"] == 270, sb["today"])
check("统计利润有值（成本按原价估）", sb["today"]["profit"] > 0, sb["today"])

# ---- 客户 ----
sc, sb, _ = handle_customers(srv, ip, tok, {})
names = {c["name"]: c for c in sb["customers"]}
check("客户列表含未建档买家累计消费",
      sc == 200 and names.get("李工", {}).get("amount") == 150, list(names))
check("客户应收字段存在", "debt" in (list(names.values())[0] if names else {}), names)

# ---- 挂账结清 ----
rc2 = st.all_records()[2]
handle_sell(srv, ip, tok, {"code": rc2["code"], "qty": 1, "price": 88,
                           "buyer": "赵工", "paid": 0})
sc, sb, _ = handle_stats(srv, ip, tok, {})
check("挂账进入应收", sb["unpaid"]["total"] == 88, sb["unpaid"])
sc, sb, _ = handle_settle(srv, ip, tok, {"buyer": "赵工"})
check("结清应收成功", sc == 200 and sb.get("settled") == 1, sb)
sc, sb, _ = handle_stats(srv, ip, tok, {})
check("结清后应收归零", sb["unpaid"]["total"] == 0, sb["unpaid"])

# ---- 回收站 ----
sc, sb, _ = handle_del_item(srv, ip, tok, {"id": ids[2]})
check("删除进回收站", sc == 200 and sb.get("deleted") == 1, sb)
sc, sb, _ = handle_trash(srv, ip, tok, {})
check("回收站有 1 条", sb["count"] == 1, sb)
sc, sb, _ = handle_restore(srv, ip, tok, {"ids": [ids[2]]})
check("恢复成功", sc == 200 and sb.get("restored") == 1, sb)
sc, sb, _ = handle_trash(srv, ip, tok, {})
check("恢复后回收站为空", sb["count"] == 0, sb)

# ---- 撤销出售 ----
sc, sb, _ = handle_sale_undo(srv, ip, tok, {"sale_id": st.list_sales()[-1]["id"]})
check("撤销出售成功", sc == 200 and sb.get("ok"), sb)

# ---- 盘点 ----
sc, sb, _ = handle_stocktake(srv, ip, tok, {}, {"op": "new", "name": "探针盘点"})
check("新建盘点单", sc == 200 and sb.get("id"), sb)
st_id = sb.get("id")
sc, sb, _ = handle_stocktake(srv, ip, tok, {"op": "detail", "id": st_id})
check("盘点明细可读", sc == 200 and len(sb["rows"]) >= 2, sb.get("rows"))
row0 = sb["rows"][0]
sc, sb, _ = handle_stocktake(srv, ip, tok, {}, {"op": "set",
                                               "row_id": row0["id"],
                                               "real_qty": row0["book"] + 5})
check("保存实盘数", sc == 200 and sb.get("ok"), sb)
sc, sb, _ = handle_stocktake(srv, ip, tok, {}, {"op": "commit", "id": st_id})
check("提交盘点", sc == 200 and sb.get("ok"), sb)
rec = [r for r in st.all_records() if r["code"] == row0["code"]][0]
check("提交后库存按实盘改写", int(rec["qty"]) == row0["book"] + 5, rec["qty"])
sc, sb, _ = handle_stocktake(srv, ip, tok, {"op": "list"})
check("盘点单列表", sc == 200 and sb["list"][0]["status"] == "done", sb.get("list"))

# ---- 只读模式拦截 ----
ro = Srv(st, write=False)
ro.mobile = srv.mobile          # 共用会话，否则令牌无效
sc, sb, _ = handle_return_sale(ro, ip, tok, {"sale_id": 1, "qty": 1})
check("只读禁止退货", sc == 403 and sb.get("readonly"), sb)
sc, sb, _ = handle_del_item(ro, ip, tok, {"id": ids[0]})
check("只读禁止删除", sc == 403, sb)
sc, sb, _ = handle_stocktake(ro, ip, tok, {}, {"op": "new"})
check("只读禁止新建盘点", sc == 403, sb)

# ---- 低库存标记 ----
st.set_meta("low_stock_threshold", 3)
sc, sb, _ = handle_items(srv, ip, tok, {})
lows = [r for r in sb["items"] if r.get("low")]
check("库存接口返回低库存标记", len(lows) >= 1, [(r["code"], r["qty"]) for r in sb["items"]])

# ---- 页面包含新入口 ----
from wm.mobile import PAGE_HTML
check("页面含 4 个页签", all(('data-p="%s"' % p) in PAGE_HTML
                             for p in ("items", "rec", "stat", "me")))
check("页面含退货/盘点/回收站入口",
      all(x in PAGE_HTML for x in ("/m/api/return_sale", "/m/api/stocktake",
                                   "/m/api/trash", "btnStocktake")))
check("页面无反斜杠转义残留", "\\" not in PAGE_HTML)

st.close()
print()
if FAIL:
    print("FAILED %d:" % len(FAIL))
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")
