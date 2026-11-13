# -*- coding: utf-8 -*-
"""生成手机页面静态预览（假数据 + fetch 桩），用于无头浏览器截图检查排版。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wm.mobile import PAGE_HTML  # noqa: E402

ITEMS = [
    {"id": 1, "code": "WL-00012", "brand": "施耐德", "category": "断路器",
     "model": "S10MD JXX XNT", "condition": "全新", "price": "128", "qty": 1,
     "shelf": "6排A-3", "listed": 1, "sold_out": 0, "remark": "", "ph": 1, "low": 1},
    {"id": 2, "code": "WL-00013", "brand": "ABB", "category": "接触器",
     "model": "AX40-30-00", "condition": "99新", "price": "260", "qty": 6,
     "shelf": "2排B-1", "listed": 1, "sold_out": 0, "remark": "", "ph": 0, "low": 0},
    {"id": 3, "code": "WL-00014", "brand": "正泰", "category": "空开",
     "model": "NXB-63 C16", "condition": "全新", "price": "18.5", "qty": 0,
     "shelf": "1排C-2", "listed": 1, "sold_out": 1, "remark": "", "ph": 0, "low": 0},
    {"id": 4, "code": "WL-00015", "brand": "欧姆龙", "category": "继电器",
     "model": "MY2NJ", "condition": "全新", "price": "22", "qty": 3,
     "shelf": "4排A-5", "listed": 1, "sold_out": 0, "remark": "", "ph": 0, "low": 0},
]
SALES = [
    {"id": 11, "code": "WL-00012", "brand": "施耐德", "model": "S10MD JXX XNT",
     "category": "断路器", "qty": 1, "price": "128", "total": "128",
     "buyer": "王工", "sale_date": "2026-11-12", "out_type": "销售",
     "remark": "", "paid": 0, "returned": 0, "refund": "0", "left": 1},
    {"id": 12, "code": "WL-00014", "brand": "正泰", "model": "NXB-63 C16",
     "category": "空开", "qty": 2, "price": "18.5", "total": "37",
     "buyer": "李工", "sale_date": "2026-11-11", "out_type": "销售",
     "remark": "", "paid": 1, "returned": 1, "refund": "18.5", "left": 1},
]
RETURNS = [
    {"id": 3, "sale_id": 12, "code": "WL-00014", "brand": "正泰",
     "model": "NXB-63 C16", "qty": 1, "refund": "18.5", "buyer": "李工",
     "restock": 1, "return_date": "2026-11-11"},
]
KPI_T = {"amount": 164.5, "refund": 18.5, "sales": 183.0, "profit": 61.2,
         "qty": 2, "orders": 2}
KPI_M = {"amount": 4820.0, "refund": 120.0, "sales": 4940.0, "profit": 1633.5,
         "qty": 46, "orders": 21}
KPI_R = {"amount": 15680.0, "refund": 320.0, "sales": 16000.0, "profit": 5210.4,
         "qty": 152, "orders": 68}
STATS = {"ok": True, "today": KPI_T, "month": KPI_M,
         "range": dict(KPI_R, days=30), "days": 30, "thr": 3,
         "low": [{"id": 1, "code": "WL-00012", "brand": "施耐德",
                  "model": "S10MD JXX XNT", "qty": 1, "shelf": "6排A-3"},
                 {"id": 4, "code": "WL-00015", "brand": "欧姆龙",
                  "model": "MY2NJ", "qty": 3, "shelf": "4排A-5"}],
         "low_count": 2,
         "unpaid": {"total": 806.0, "count": 3,
                    "buyers": [{"name": "王工", "amount": 668.0, "count": 2},
                               {"name": "李工", "amount": 138.0, "count": 1}]},
         "top": [{"model": "S10MD JXX XNT", "profit": 320.5, "qty": 6},
                 {"model": "AX40-30-00", "profit": 210.0, "qty": 3},
                 {"model": "MY2NJ", "profit": 96.0, "qty": 8}],
         "stock": {"items": 4, "qty": 10, "value": 2019.0}}
CUSTS = {"ok": True, "unpaid": STATS["unpaid"], "customers": [
    {"id": 1, "name": "王工", "phone": "13800000000", "address": "", "level": "VIP",
     "note": "", "count": 6, "qty": 8, "amount": 1680.0, "debt": 668.0,
     "last": "2026-11-12"},
    {"id": 2, "name": "李工", "phone": "", "address": "", "level": "",
     "note": "", "count": 3, "qty": 4, "amount": 520.0, "debt": 138.0,
     "last": "2026-11-11"}]}

STUB = """
<script>
window.fetch = function(url, opts){
  var body = {ok: true};
  if (url.indexOf("/m/api/whoami") === 0) {
    body = {ok: true, warehouse: "主仓", can_write: true, port: 8765};
  } else if (url.indexOf("/m/api/items") === 0) {
    body = %s;
  } else if (url.indexOf("/m/api/sales") === 0) {
    body = %s;
  } else if (url.indexOf("/m/api/returns") === 0) {
    body = %s;
  } else if (url.indexOf("/m/api/stats") === 0) {
    body = %s;
  } else if (url.indexOf("/m/api/customers") === 0) {
    body = %s;
  } else if (url.indexOf("/m/api/trash") === 0) {
    body = {ok: true, count: 2, items: [
      {id: 9, code: "WL-00009", brand: "德力西", model: "DZ47", qty: 2,
       price: "15", deleted_at: "2026-11-10 09:20"}]};
  }
  return Promise.resolve({status: 200, json: function(){ return Promise.resolve(body); }});
};
</script>
""" % (json.dumps({"ok": True, "total": len(ITEMS), "offset": 0,
                   "has_more": False, "items": ITEMS}, ensure_ascii=False),
       json.dumps({"ok": True, "sales": SALES}, ensure_ascii=False),
       json.dumps({"ok": True, "returns": RETURNS}, ensure_ascii=False),
       json.dumps(STATS, ensure_ascii=False),
       json.dumps(CUSTS, ensure_ascii=False))

TAB_JS = """
<script>
setTimeout(function(){
  var t = (location.search.match(/tab=([a-z]+)/) || [])[1] || "items";
  if (typeof goPage === "function") goPage(t);
}, 260);
</script>
"""

OUT = os.path.join(ROOT, "tools", "_page_preview.html")
html = PAGE_HTML.replace("<script>", STUB + "<script>", 1)
html = html.replace("</body>", TAB_JS + "</body>")
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print("saved", OUT, len(html))
