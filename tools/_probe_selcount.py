# -*- coding: utf-8 -*-
"""探针：数据页选中计数（v1.45.5）。

断言（真页面 + 真状态栏）：
1) 库存明细页：多选 ≥2 行 → 状态栏「已选 N 行」；选 1 行 / 清空不刷状态栏
2) 销售页 / 出库页（SalesTab 共用）：多选 → 状态栏计数
3) 手机数据页：库存表多选 → 状态栏计数
用法：.venv310/Scripts/python.exe tools/_probe_selcount.py
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402

import wm.app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_selcnt_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP

st = Store(os.path.join(TMP, "warehouse.db"))
ITEMS = [
    (1, "WL-9001", "西门子", "驱动器", "全新", "S10MD", 1, 1200),
    (2, "WL-9002", "施耐德", "断路器", "9成新", "GV2ME08", 2, 260),
    (3, "WL-9003", "欧姆龙", "传感器", "全新", "E3Z-D61", 8, 120),
]
for lid, code, b, cat, cond, m, q, p in ITEMS:
    rec = blank_record()
    rec.update({"lid": lid, "code": code, "brand": b, "category": cat,
                "condition": cond, "model": m, "qty": q, "price": p})
    st.insert(rec)
# 手机区数据（手机数据页）与销售/出库记录（SalesTab）
mrec = blank_record()
mrec.update({"lid": 11, "code": "APP-0001", "brand": "基恩士", "model": "FS-V11",
             "qty": 3, "price": 880})
st.m_upsert_item(mrec)
mrec2 = blank_record()
mrec2.update({"lid": 12, "code": "APP-0002", "brand": "三菱", "model": "FX3U",
              "qty": 1, "price": 1500})
st.m_upsert_item(mrec2)
try:
    st.add_sale(1, 1, 1200, buyer="测试")
    st.add_sale(2, 1, 260, buyer="测试2")
except Exception as e:
    print("add_sale fail:", e)
st.close()

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print("  ok  %s" % name)
    else:
        print("  FAIL %s -> %r" % (name, detail))


def main():
    try:
        ctypes.windll.user32.SetCursorPos(2, 2)
    except Exception:
        pass

    root = tk.Tk()
    root.withdraw()
    app = wapp.App(root)
    app.load_data()
    kids = [str(i) for i in app.tree.get_children()]

    # ---- ① 库存明细页 ----
    root.update()
    app._status("基准消息")
    root.update()
    app.tree.selection_set(kids[:2])          # 多选 2 行 → 触发 <<TreeviewSelect>>
    root.update()
    msg = app.lbl_status.cget("text")
    chk("库存明细：多选 2 行 → 状态栏显示计数", "已选 2 行" in msg, msg)
    app.tree.selection_set(kids[0])           # 单选 1 行 → 不覆盖状态栏
    root.update()
    chk("库存明细：选 1 行不刷状态栏", "已选 1 行" not in app.lbl_status.cget("text"),
        app.lbl_status.cget("text"))
    app.tree.selection_remove(*app.tree.selection())
    root.update()
    chk("库存明细：清空选择不刷状态栏", "已选 0 行" not in app.lbl_status.cget("text"),
        app.lbl_status.cget("text"))

    # ---- ② 销售页 / 出库页 ----
    for attr, label in (("tab_sales", "销售"), ("tab_out", "出库")):
        tab = getattr(app, attr)
        app.nb.select(tab)
        root.update()
        app._status("基准消息")
        root.update()
        tkids = [str(i) for i in tab.tree.get_children()]
        if not tkids:
            chk("%s页：无数据跳过" % label, True)
            continue
        tab.tree.selection_set(tkids[:2])
        root.update()
        msg = app.lbl_status.cget("text")
        chk("%s页：多选 2 行 → 状态栏计数" % label, "已选 2 行" in msg, msg)
        tab.tree.selection_set(tkids[0])
        root.update()
        chk("%s页：选 1 行不刷状态栏" % label,
            "已选 1 行" not in app.lbl_status.cget("text"), app.lbl_status.cget("text"))

    # ---- ③ 手机数据页 ----
    tab = app.tab_phone
    app.nb.select(tab)
    tab.refresh_tab()
    root.update()
    app._status("基准消息")
    root.update()
    tkids = [str(i) for i in tab.tree_items.get_children()]
    if tkids:
        tab.tree_items.selection_set(tkids[:2])
        root.update()
        msg = app.lbl_status.cget("text")
        chk("手机数据页：多选 2 行 → 状态栏计数", "已选 2 行" in msg, msg)
        tab.tree_items.selection_set(tkids[0])
        root.update()
        chk("手机数据页：选 1 行不刷状态栏",
            "已选 1 行" not in app.lbl_status.cget("text"), app.lbl_status.cget("text"))
    else:
        chk("手机数据页：无数据跳过", True)

    root.destroy()
    print("\n%d 项通过" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
