# -*- coding: utf-8 -*-
"""探针：v1.32.0 数据层（客户 / 退货 / 利润 / 盘点）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wm.store import Store, blank_record  # noqa: E402

ok = True


def _qty(store, code):
    iid = store.find_by_code(code)
    for r in store.all_records():
        if int(r["id"]) == int(iid):
            return int(r.get("qty") or 0)
    return -1


def chk(label, cond, extra=""):
    global ok
    print(("  [PASS] " if cond else "  [FAIL] ") + label + ("" if cond else "  %s" % (extra,)))
    if not cond:
        ok = False


tmp = tempfile.mkdtemp(prefix="wm_biz_")
st = Store(os.path.join(tmp, "data", "warehouse.db"))

# 两条库存：A 10 件成本 100，B 3 件成本 50
st.insert_many([
    blank_record() | {"code": "WL-00001", "brand": "ABB", "category": "变频器",
                      "model": "ACS510", "price": 200.0, "qty": 10, "cost": 100.0},
    blank_record() | {"code": "WL-00002", "brand": "西门子", "category": "PLC",
                      "model": "S7-200", "price": 300.0, "qty": 3, "cost": 150.0},
])
# insert_many 不写 cost（成本只由采购/盘点维护），这里直接补成本单价
st._execute('UPDATE items SET cost = 100.0 WHERE code = ?', ("WL-00001",))
st._execute('UPDATE items SET cost = 150.0 WHERE code = ?', ("WL-00002",))
a_id = st.find_by_code("WL-00001")
b_id = st.find_by_code("WL-00002")

print("== 1. 出售 + 退货 ==")
r1, m1 = st.add_sale(a_id, 4, 200.0, buyer="张三", sale_date="2026-11-01")
r2, m2 = st.add_sale(b_id, 2, 300.0, buyer="李四", sale_date="2026-11-02")
chk("两笔出售成功", r1 and r2, (m1, m2))
sales = st.list_sales(scope="sale")
sid1 = [s for s in sales if s["code"] == "WL-00001"][0]["id"]
sid2 = [s for s in sales if s["code"] == "WL-00002"][0]["id"]

chk("可退数量 = 4", st.returnable_qty(sid1) == 4, st.returnable_qty(sid1))
r, m = st.add_return(sid1, 5)
chk("超量退货被拒", not r and "最多" in m, m)
r, m = st.add_return(sid1, 1, refund=None, restock=True,
                     return_date="2026-11-03", remark="客户不要了")
chk("退 1 件成功", r, m)
chk("退款默认按原单价 200", "200.00" in m, m)
chk("库存回到 7", _qty(st, "WL-00001") == 7, _qty(st, "WL-00001"))
chk("可退数量变 3", st.returnable_qty(sid1) == 3, st.returnable_qty(sid1))
r, m = st.add_return(sid2, 1, refund=150.0, restock=False,
                     return_date="2026-11-03", remark="只退钱不退货")
chk("不退货的退货成功", r, m)
chk("库存不变（仍 1）", _qty(st, "WL-00002") == 1, _qty(st, "WL-00002"))
t = st.returns_total("2026-11-01", "2026-11-30")
chk("退货汇总 2 笔", t["count"] == 2 and abs(t["refund"] - 350.0) < 0.01, t)

print("== 2. 利润（退货冲减原单） ==")
rows = st.profit_rows("2026-11-01", "2026-11-30")
r_a = [x for x in rows if x["code"] == "WL-00001"][0]
r_b = [x for x in rows if x["code"] == "WL-00002"][0]
chk("A 实收 800-200=600", abs(r_a["amount"] - 600.0) < 0.01, r_a["amount"])
chk("A 净成本 400-100=300", abs(r_a["cost"] - 300.0) < 0.01, r_a["cost"])
chk("A 利润 300", abs(r_a["profit"] - 300.0) < 0.01, r_a["profit"])
chk("A 毛利率 50%", abs(r_a["margin"] - 50.0) < 0.01, r_a["margin"])
chk("B 利润 450-150=300", abs(r_b["profit"] - 300.0) < 0.01, r_b["profit"])
chk("按品牌过滤", len(st.profit_rows("", "", brand="ABB")) == 1,
    len(st.profit_rows("", "", brand="ABB")))

print("== 3. 撤销退货 ==")
ret = [x for x in st.list_returns() if x["code"] == "WL-00001"][0]
r, m = st.delete_return(ret["id"])
chk("撤销成功", r, m)
chk("库存回到 6（10-4）", _qty(st, "WL-00001") == 6, _qty(st, "WL-00001"))
chk("利润回到 400", abs(
    [x for x in st.profit_rows() if x["code"] == "WL-00001"][0]["profit"] - 400.0) < 0.01)
ret2 = [x for x in st.list_returns() if x["code"] == "WL-00002"][0]
r, m = st.delete_return(ret2["id"])
chk("不退货的撤销也成功", r, m)

print("== 4. 客户 ==")
r, m = st.add_customer("张三", "13800000000", "上海市", "VIP", "老客户")
chk("新增客户", r, m)
r, m = st.add_customer("张三")
chk("重名客户被拒", not r and "已存在" in m, m)
r, m = st.add_customer("")
chk("空名被拒", not r, m)
n = st.import_buyers()
chk("从出售记录导入 1 个（李四）", n == 1, n)
cs = st.list_customers()
chk("客户列表 2 个", len(cs) == 2, [c["name"] for c in cs])
zs = [c for c in cs if c["name"] == "张三"][0]
chk("张三累计消费 800", abs(zs["amount"] - 800.0) < 0.01, zs)
chk("张三成交 1 笔 / 4 件", zs["count"] == 1 and zs["qty"] == 4, zs)
chk("搜索命中", len(st.list_customers("138")) == 1, len(st.list_customers("138")))
r, m = st.update_customer(zs["id"], phone="13900000000", level="金牌")
chk("修改客户", r, m)
chk("修改生效", [c for c in st.list_customers() if c["name"] == "张三"][0]["phone"]
    == "13900000000")
chk("删除客户", st.delete_customer(zs["id"]) == 1)

print("== 5. 盘点单 ==")
st_id, m = st.create_stocktake("11 月盘点")
chk("生成盘点单", st_id > 0, m)
chk("有明细", len(st.stocktake_detail(st_id)["rows"]) == 2,
    len(st.stocktake_detail(st_id)["rows"]))
rows = st.stocktake_detail(st_id)["rows"]
ra = [r for r in rows if r["code"] == "WL-00001"][0]
r, m = st.set_stocktake_qty(ra["id"], 4, "少 2 件")
chk("填实盘数", r, m)
chk("差异计数 1", st.list_stocktakes()[0]["diff"] == 1, st.list_stocktakes()[0])
chk("净差异 -2", st.list_stocktakes()[0]["diff_qty"] == -2, st.list_stocktakes()[0])
r, m = st.commit_stocktake(st_id)
chk("提交盘点", r, m)
chk("库存改为 4", _qty(st, "WL-00001") == 4, _qty(st, "WL-00001"))
r, m = st.commit_stocktake(st_id)
chk("重复提交被拒", not r, m)
r, m = st.set_stocktake_qty(ra["id"], 9)
chk("已提交的单不能改实盘", not r and "已提交" in m, m)
chk("已提交的单不给删", st.delete_stocktake(st_id) == -1)
chk("库存仍 4（没被二次改动）", _qty(st, "WL-00001") == 4)

st2_id, m = st.create_stocktake("空筛选")
chk("只盘有货的能生成", st2_id > 0, m)
chk("草稿单可删", st.delete_stocktake(st2_id) == 1)

print("== 6. 操作日志 ==")
logs = [dict(r) for r in st.conn.execute(
    "SELECT act FROM oplog ORDER BY id").fetchall()]
acts = [r["act"] for r in logs]
for want in ("销售退货", "撤销退货", "新增客户", "导入客户", "新建盘点单", "提交盘点"):
    chk("日志含「%s」" % want, want in acts, acts[-8:])

st.close()
print()
print("ALL OK" if ok else "HAS FAILURES")
