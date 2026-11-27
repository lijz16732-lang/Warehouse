# -*- coding: utf-8 -*-
"""探针：主库存工具栏「刷新」按钮（v1.45.6）。

断言：
1) 工具栏存在「刷新」按钮
2) 外部向数据库插入一条记录后，点刷新 → 表格行数 +1
3) 状态栏显示「已载入 N 条记录」
用法：.venv310/Scripts/python.exe tools/_probe_refresh_button.py
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

TMP = tempfile.mkdtemp(prefix="wm_refbtn_")
DB = os.path.join(TMP, "warehouse.db")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP

st = Store(DB)
for n in (1, 2):
    rec = blank_record()
    rec.update({"lid": n, "code": "WL-%04d" % n, "brand": "西门子",
                "model": "S10MD", "qty": 1, "price": 1200})
    st.insert(rec)
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
app.load_data()
root.update()

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print("  ok  %s" % name)
    else:
        print("  FAIL %s -> %r" % (name, detail))


def find_button(widget, text):
    for w in widget.winfo_children():
        if isinstance(w, tk.Misc) and str(w.winfo_class()) == "TButton" \
                and w.cget("text") == text:
            return w
        got = find_button(w, text) if hasattr(w, "winfo_children") else None
        if got:
            return got
    return None


def main():
    btn = find_button(app.tab_inv, "刷新")
    chk("工具栏有「刷新」按钮", btn is not None)
    before = len(app.tree.get_children())
    chk("初始 2 行", before == 2, before)

    # 外部插一条（模拟局域网另一工位/另一进程写库）
    st2 = Store(DB)
    rec = blank_record()
    rec.update({"lid": 3, "code": "WL-0003", "brand": "欧姆龙",
                "model": "E3Z", "qty": 5, "price": 120})
    st2.insert(rec)
    st2.close()
    chk("点刷新前界面仍 2 行", len(app.tree.get_children()) == 2)

    assert btn is not None
    btn.invoke()                    # 真点按钮：command=self.load_data
    root.update()
    after = len(app.tree.get_children())
    chk("点刷新后界面变 3 行", after == 3, after)
    chk("状态栏显示已载入 3 条", "已载入 3 条记录" in app.lbl_status.cget("text"),
        app.lbl_status.cget("text"))

    # F5 / 菜单入口仍保留（按钮不替代原有入口）
    src = open(os.path.join(ROOT, "wm", "app.py"), encoding="utf-8").read()
    chk("数据菜单「刷新数据」与 F5 入口仍在",
        'label="刷新数据", accelerator="F5"' in src
        and '("sc_refresh",  "刷新数据",       "F5",     "load_data")' in src)

    root.destroy()
    print("\n%d 项通过" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
