# -*- coding: utf-8 -*-
"""探针：手机数据页筛选 + 导出跟随筛选（v1.29.2）。

断言：
1) 无筛选时表格 = 全量
2) 库存按品牌筛选后表格行数、导出 Excel 行数都跟着变
3) 出售按类型 + 日期区间筛选后同理
4) 多个条件叠加（品牌 + 状态）
5) 「清空筛选」恢复全量
用法：.venv310/Scripts/python.exe tools/_probe_phone_filter.py [--shot]
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402

import wm.app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_phoneflt_")
# 探针必须隔离数据目录（app_dir 只管图标路径，数据走 resolve_data_dir）
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP

st = Store(os.path.join(TMP, "warehouse.db"))     # 主仓库文件就在数据目录根部
ITEMS = [
    # lid, code, brand, category, condition, model, qty, price
    (1, "APP-0001", "西门子", "驱动器", "全新", "S10MD JXX XNT", 1, 1200),
    (2, "APP-0002", "西门子", "驱动器", "9成新", "V20", 2, 800),
    (3, "APP-0003", "施耐德", "断路器", "全新", "GV2ME08", 5, 260),
    (4, "APP-0004", "施耐德", "断路器", "9成新", "GV2ME10", 3, 280),
    (5, "APP-0005", "欧姆龙", "传感器", "全新", "E3Z-D61", 8, 120),
]
for lid, code, b, cat, cond, m, q, p in ITEMS:
    rec = blank_record()
    rec.update({"lid": lid, "code": code, "brand": b, "category": cat,
                "condition": cond, "model": m, "qty": q, "price": p})
    st.m_upsert_item(rec)
# 2 条标记为「已转入」
st.conn.execute("UPDATE phone_items SET transferred=1 WHERE lid IN (1, 3)")
# 同步时间拉开（验证按时间筛选）
for lid, ts in ((1, "2026-10-01 09:12:00"), (2, "2026-10-05 11:00:00"),
                (3, "2026-10-20 16:40:00"), (4, "2026-10-28 08:05:00"),
                (5, "2026-10-30 20:30:00")):
    st.conn.execute("UPDATE phone_items SET synced_at=? WHERE lid=?", (ts, lid))
st.conn.commit()

SALES = [
    # lid, code, brand, model, qty, price, total, buyer, date, out_type
    (1, "APP-0001", "西门子", "S10MD JXX XNT", 1, 1500, 1500, "张工",
     "2026-10-02 09:10:00", "出售"),
    (2, "APP-0002", "西门子", "V20", 1, 900, 900, "李工",
     "2026-10-20 14:30:00", "出售"),
    (3, "APP-0003", "施耐德", "GV2ME08", 2, 300, 600, "张工",
     "2026-10-25 18:00:00", "出售"),
    (4, "APP-0005", "欧姆龙", "E3Z-D61", 1, 150, 150, "王工",
     "2026-09-15 10:00:00", "退换"),
]
for lid, code, b, m, q, p, t, buyer, d, ot in SALES:
    st.m_upsert_sale({"lid": lid, "code": code, "brand": b, "model": m, "qty": q,
                      "price": p, "total": t, "buyer": buyer, "sale_date": d,
                      "out_type": ot})
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
tab = app.tab_phone
app.nb.select(tab)
tab.refresh_tab()

ok = True


def check(name, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                         "" if cond else "  ← " + str(extra)))


def rows(tree):
    return len(tree.get_children())


def export_counts(path):
    from openpyxl import load_workbook
    wb = load_workbook(path)
    n1 = wb["手机库存"].max_row - 1 if wb["手机库存"].max_row > 1 else 0
    n2 = wb["手机出售记录"].max_row - 1 if wb["手机出售记录"].max_row > 1 else 0
    wb.close()
    return n1, n2


# ---- 1) 无筛选 ----
check("默认显示全量库存 5 条", rows(tab.tree_items) == 5, rows(tab.tree_items))
check("默认显示全量出售 4 条", rows(tab.tree_sales) == 4, rows(tab.tree_sales))
check("下拉选项含数据里的品牌",
      "西门子" in tab.cb_brand.cget("values")
      and "施耐德" in tab.cb_brand.cget("values"), tab.cb_brand.cget("values"))

# ---- 2) 库存按品牌筛选 ----
tab.var_f_brand.set("西门子")
tab.refresh_rows()
check("品牌=西门子 → 库存 2 条", rows(tab.tree_items) == 2, rows(tab.tree_items))
p = os.path.join(TMP, "exp1.xlsx")
tab._export_to(p)
n1, n2 = export_counts(p)
check("导出跟随筛选：库存 2 行", n1 == 2, n1)
check("导出跟随筛选：出售仍全量 4 行", n2 == 4, n2)

# ---- 3) 叠加状态 ----
tab.var_f_state.set("待转入")
tab.refresh_rows()
check("品牌=西门子 + 待转入 → 1 条", rows(tab.tree_items) == 1, rows(tab.tree_items))
tab.var_f_cat.set("传感器")
tab.refresh_rows()
check("再叠加 品类=传感器（无交集）→ 0 条", rows(tab.tree_items) == 0,
      rows(tab.tree_items))

# ---- 4) 清空筛选 ----
tab.reset_filters()
check("清空筛选 → 库存回到 5 条", rows(tab.tree_items) == 5, rows(tab.tree_items))

# ---- 5) 出售按类型 + 日期 ----
tab.var_f_type.set("出售")
tab.refresh_rows()
check("类型=出售 → 3 条", rows(tab.tree_sales) == 3, rows(tab.tree_sales))
tab.var_f_from.set("2026-10-01")
tab.var_f_to.set("2026-10-21")
tab.refresh_rows()
check("类型=出售 + 10-01~10-21 → 2 条", rows(tab.tree_sales) == 2,
      rows(tab.tree_sales))
tab.var_f_from.set("20261001")           # 无分隔符也认
tab.var_f_to.set("")
tab.refresh_rows()
check("日期只填起始(20261001) → 3 条", rows(tab.tree_sales) == 3,
      rows(tab.tree_sales))

p2 = os.path.join(TMP, "exp2.xlsx")
tab._export_to(p2)
n1, n2 = export_counts(p2)
check("出售串筛选后导出：出售 3 行", n2 == 3, n2)
check("出售串筛选后导出：库存仍全量 5 行", n1 == 5, n1)

# ---- 6) 买家筛选 ----
tab.reset_filters()
tab.var_f_buyer.set("张工")
tab.refresh_rows()
check("买家=张工 → 2 条", rows(tab.tree_sales) == 2, rows(tab.tree_sales))

# ---- 7) 库存按同步时间筛选 ----
tab.reset_filters()
tab.var_f_sync_from.set("2026-10-20")
tab.var_f_sync_to.set("2026-10-30")
tab.refresh_rows()
check("同步时间 10-20~10-30 → 库存 3 条", rows(tab.tree_items) == 3,
      rows(tab.tree_items))
tab.var_f_sync_to.set("2026-10-20")
tab.refresh_rows()
check("同步时间只到 10-20 当天 → 1 条（含当天 16:40）",
      rows(tab.tree_items) == 1, rows(tab.tree_items))

# ---- 8) 出售时间精确到分 ----
tab.reset_filters()
tab.var_f_from.set("2026-10-20 14:00")
tab.var_f_to.set("2026-10-20 15:00")
tab.refresh_rows()
check("出售时间 10-20 14:00~15:00 → 1 条", rows(tab.tree_sales) == 1,
      rows(tab.tree_sales))
tab.var_f_from.set("2026-10-20 15:00")
tab.var_f_to.set("")
tab.refresh_rows()
check("出售时间起点 10-20 15:00 之后 → 1 条（10-02 与 14:30 均被排除）",
      rows(tab.tree_sales) == 1, rows(tab.tree_sales))
p3 = os.path.join(TMP, "exp3.xlsx")
tab._export_to(p3)
n1, n2 = export_counts(p3)
check("时间筛选后导出：出售 1 行", n2 == 1, n2)

# ---- 9) 本月 / 今天快捷键（与出售页一致）----
import datetime as _dt
_cm = _dt.datetime.now().strftime("%Y-%m")
_td = _dt.datetime.now().strftime("%Y-%m-%d")
tab.reset_filters()
tab.qb_sale_month.invoke()
exp = sum(1 for r in tab.raw_sales
          if str(r.get("sale_date") or "")[:7] == _cm)
check("出售「本月」快捷键 → %d 条" % exp, rows(tab.tree_sales) == exp,
      rows(tab.tree_sales))
tab.qb_sale_today.invoke()
exp = sum(1 for r in tab.raw_sales
          if str(r.get("sale_date") or "")[:10] == _td)
check("出售「今天」快捷键 → %d 条" % exp, rows(tab.tree_sales) == exp,
      rows(tab.tree_sales))
tab.reset_filters()
tab.qb_sync_month.invoke()
exp = sum(1 for r in tab.raw_items
          if str(r.get("synced_at") or "")[:7] == _cm)
check("库存「本月」同步时间快捷键 → %d 条" % exp, rows(tab.tree_items) == exp,
      rows(tab.tree_items))
tab.reset_filters()

print("\n%s" % ("ALL PROBES PASSED" if ok else "SOME PROBES FAILED"))

if "--shot" in sys.argv:
    import time
    import screenshot
    tab.reset_filters()
    tab.var_f_brand.set("施耐德")
    tab.refresh_rows()
    app.nb.select(tab)
    root.deiconify()
    root.lift()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    root.update()
    time.sleep(1.0)
    out = os.path.join(ROOT, ".tmpdbg", "phone_filter.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    screenshot.capture(out)
    print("shot:", out)

try:
    root.destroy()
except Exception:
    pass
sys.exit(0 if ok else 1)
