# -*- coding: utf-8 -*-
"""临时脚本：趋势图月份标签验证（11月/12月 + 统计区间副标题）。"""
import os
import shutil
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_trend_")
wapp.app_dir = lambda: TMP
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

st = Store(os.path.join(TMP, "data", "warehouse.db"))
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
app.store.insert_many([
    blank_record() | {"code": "WL-00001", "brand": "罗技", "category": "外设",
                      "model": "MX MASTER 3", "price": 599.0, "qty": 20, "listed": 1},
])
rec = app.store.all_records()[0]
# 去年 11/12 月 + 今年若干月，验证标签与金额
app.store.add_sale(rec["id"], 2, 500.0, sale_date="2025-11-20")
app.store.add_sale(rec["id"], 1, 600.0, sale_date="2025-12-05")
app.store.add_sale(rec["id"], 3, 700.0, sale_date="2026-03-15")
app.store.add_sale(rec["id"], 4, 800.0, sale_date="2026-10-01")
app.load_data()
root.title("仓管家-趋势图验证")
root.attributes("-topmost", True)
root.lift()
root.deiconify()
root.geometry("1440x900+60+20")
root.update()

FAIL = []


def check(name, cond, extra=""):
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, extra if not cond else ""))
    if not cond:
        FAIL.append(name)


app.nb.select(1)
app.tab_sales.refresh_tab()
app.tab_sales._toggle_trend()
root.update()

monthly = app.store.monthly_sales(12)
check("共 12 个月数据点", len(monthly) == 12, str(len(monthly)))
check("起点是去年 11 月", monthly[0][0] == "2025-11", str(monthly[0][0]))
check("终点是本月", monthly[-1][0].endswith("-10"), str(monthly[-1][0]))
chart = app.tab_sales.c_month
xlabels = [lab for lab, _v in chart._data]
check("横轴标签为 11月/12月/1月.../10月",
      xlabels[:2] == ["11月", "12月"] and xlabels[-1] == "10月", str(xlabels))
check("去年 11 月金额 1000", abs(dict((k, v) for k, v in monthly)["2025-11"] - 1000.0) < 1e-6,
      str(monthly))
sub = chart._subtitle
check("副标题含统计区间 2025-11 ~ ", "2025-11" in str(sub) and "~" in str(sub), str(sub))

screenshot.capture_window("趋势图验证", os.path.join(OUT, "trend_labels.png"))
print("shot -> trend_labels.png")

root.destroy()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%s" % ("ALL PASSED" if not FAIL else "FAILED: %s" % FAIL))
