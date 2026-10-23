# -*- coding: utf-8 -*-
"""临时脚本：验证标签页顺序（库存管理 | 出售记录 | 出库记录 | 数据分析）。"""
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

TMP = tempfile.mkdtemp(prefix="wm_tabs_")
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
                      "model": "MX MASTER 3", "price": 599.0, "qty": 8, "listed": 1},
    blank_record() | {"code": "WL-00002", "brand": "Apple", "category": "手机",
                      "model": "A2634", "price": 2899.0, "qty": 4, "listed": 1},
])
recs = {r["code"]: r for r in app.store.all_records()}
app.store.add_sale(recs["WL-00001"]["id"], 1, 650.0, buyer="张三",
                   sale_date="2026-10-02")
app.store.add_sale(recs["WL-00002"]["id"], 1, 0, out_type="报废",
                   sale_date="2026-10-06", remark="屏幕碎裂")
app.load_data()
root.title("仓管家-标签顺序验证")
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


want = ["库存管理", "出售记录", "出库记录", "数据分析"]
got = [app.nb.tab(i, "text").strip() for i in range(len(app.nb.tabs()))]
check("标签顺序 = 库存管理 | 出售记录 | 出库记录 | 数据分析", got == want, str(got))

# 依次切页，确认每页能正常刷新（索引路由正确）
app.nb.select(1)
root.update()
check("切到第 2 页=出售记录且已刷新",
      len(app.tab_sales.rows) == 1 and app.tab_sales.lbl_wh.cget("text") != "",
      "rows=%d" % len(app.tab_sales.rows))
app.nb.select(2)
root.update()
check("切到第 3 页=出库记录且已刷新（2 笔）",
      len(app.tab_out.rows) == 2 and app.tab_out.lbl_wh.cget("text") != "",
      "rows=%d" % len(app.tab_out.rows))
app.nb.select(3)
root.update()
check("切到第 4 页=数据分析不报错", app.nb.index(app.nb.select()) == 3)

app.nb.select(2)
root.update()
screenshot.capture_window("标签顺序验证", os.path.join(OUT, "tabs_order.png"))
print("shot -> tabs_order.png")

root.destroy()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%s" % ("ALL PASSED" if not FAIL else "FAILED: %s" % FAIL))
