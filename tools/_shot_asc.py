# -*- coding: utf-8 -*-
"""临时脚本：默认升序（不是降序）验证 + 新增/导入后定位到最新记录。"""
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

TMP = tempfile.mkdtemp(prefix="wm_asc_")
wapp.app_dir = lambda: TMP
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

st = Store(os.path.join(TMP, "data", "warehouse.db"))
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)

DATA = [
    ("WL-00001", "罗技", "外设", "MX MASTER 3", 599.0, 2),
    ("WL-00002", "Apple", "手机", "A2634", 2899.0, 3),
    ("WL-00003", "西门子", "驱动器", "V20", 1200.0, 1),
    ("WL-00004", "戴尔", "显示器", "U2720Q", 1580.0, 5),
    ("WL-00005", "联想", "笔记本", "X1C Gen9", 3600.0, 4),
]
app.store.insert_many([blank_record() | {"code": c, "brand": b, "category": cat, "model": m,
                                         "price": p, "qty": q, "listed": 1}
                       for c, b, cat, m, p, q in DATA])
app.load_data()
root.title("仓管家-升序验证窗口")
root.deiconify()
root.geometry("1400x880+80+30")
root.update()

FAIL = []


def check(name, cond, extra=""):
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, extra if not cond else ""))
    if not cond:
        FAIL.append(name)


print("== 1. 默认升序 ==")
check("数据层 all_records 首条为最小编号",
      app.store.all_records()[0]["code"] == "WL-00001",
      str(app.store.all_records()[0]["code"]))
check("数据层 all_records 末条为最大编号",
      app.store.all_records()[-1]["code"] == "WL-00005")
codes = [r["code"] for r in app.records]
check("界面 records 为升序", codes == sorted(codes), str(codes))
first_row = app.tree.get_children()[0]
check("表格第一行是 WL-00001", app.by_id[str(first_row)]["code"] == "WL-00001")
check("编号列默认显示 ▲", "▲" in app.tree.heading("code")["text"],
      str(app.tree.heading("code")["text"]))
check("未点击表头时 sort_key 仍为 None", app.sort_key is None)
screenshot.capture_window("升序验证", os.path.join(OUT, "asc_default.png"))
print("shot -> asc_default.png（默认升序）")

print("== 2. 点表头排序仍正常 ==")
app.sort_column("price")
prices = [float(r["price"]) for r in app.filtered]
check("第一次点价格 = 升序", prices == sorted(prices))
app.sort_column("price")
prices = [float(r["price"]) for r in app.filtered]
check("第二次点价格 = 降序", prices == sorted(prices, reverse=True))
check("降序时表头显示 ▼", "▼" in app.tree.heading("price")["text"])
app.sort_column("price")           # 回到升序
app.sort_key, app.sort_desc = None, False
app.apply_filters()
root.update()

print("== 3. 分页下新增记录自动定位 ==")
app._set_page_size("2")
check("每页 2 条时共 3 页", app.page == 1 and len(app.tree.get_children()) == 2)
wapp.ask_record = lambda *a, **k: (blank_record() | {
    "code": "", "brand": "华为", "category": "网络", "model": "S5720",
    "price": 2100.0, "qty": 7, "listed": 1})
app.add_record()
root.update()
newest = app.store.all_records()[-1]["code"]
check("新增后落在最后一页", app.page == 3, "page=%s" % app.page)
check("新增记录被选中", app.tree.selection() and
      app.by_id[str(app.tree.selection()[0])]["code"] == newest, newest)
check("新增记录编号顺延", newest == "WL-00006", newest)
check("未排序时列表仍升序（新记录在末尾）",
      [r["code"] for r in app.filtered][-1] == newest)

print("== 4. 跳到最后一页（导入后定位用） ==")
app.goto_page(1)
app._goto_last_page()
check("_goto_last_page 到第 3 页", app.page == 3, "page=%s" % app.page)
app._set_page_size("全部")
root.update()
screenshot.capture_window("升序验证", os.path.join(OUT, "asc_after_add.png"))
print("shot -> asc_after_add.png（新增后升序 + 选中最新）")

root.destroy()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%s" % ("ALL PASSED" if not FAIL else "FAILED: %s" % FAIL))
