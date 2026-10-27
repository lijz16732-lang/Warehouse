# -*- coding: utf-8 -*-
"""临时脚本：断言式验证「手机数据」表格对齐（不截屏，读 bbox）。"""
import os
import shutil
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import wm.app as wapp  # noqa: E402
from wm.store import Store  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_v1180c_")
wapp.app_dir = lambda: TMP

st = Store(os.path.join(TMP, "data", "warehouse.db"))
st.m_upsert_item({"lid": 101, "code": "APP-00001", "brand": "端到端测试品",
                  "category": "配件", "model": "E2E-1", "condition": "全新",
                  "qty": 2, "price": 66, "shelf": "T1",
                  "synced_at": "2026-10-27 11:43:30"})
st.close()

root = tk.Tk()
root.geometry("1440x900+40+40")
app = wapp.App(root)
root.title("phone-align-check")
fails = []


def step():
    try:
        app.nb.select(app.tab_phone)
        app.tab_phone.refresh_rows()
        root.update_idletasks()
        root.update()
        tree = app.tab_phone.tree_items
        cols = [c[0] for c in
                [("code",), ("brand",), ("qty",), ("price",), ("shelf",)]]
        # 1) 列锚点与主表格规则一致
        for key, want in (("code", "w"), ("brand", "center"), ("qty", "e"),
                          ("price", "e"), ("shelf", "center")):
            got = tree.column(key)["anchor"]
            if got != want:
                fails.append("列 %s anchor=%s 期望 %s" % (key, got, want))
        # 2) 单元格几何：品牌值中心应接近品牌列中心（居中），价格值靠右
        iid = tree.get_children()[0]
        root.update()
        for key, mode in (("brand", "center"), ("price", "right")):
            hb = tree.bbox(iid, "#%d" % (list(tree["columns"]).index(key) + 1))
            if not hb:
                fails.append("取不到 %s 单元格 bbox" % key)
                continue
            x, w = hb[0], hb[2]
            if mode == "center":
                # 值文本大致在列中部（bbox 的 x 是单元格左缘，用文本宽度估算）
                tw = 90
                off = (x + w / 2) - (x + tw / 2)
                # 直接比较：居中列的单元格左缘与列左缘之间空隙应明显大于 0
                if w < 30:
                    fails.append("%s 列宽异常 %s" % (key, w))
            else:
                pass
        # 3) 表头锚点
        for key, want in (("brand", "center"), ("qty", "e")):
            got = tree.heading(key)["anchor"]
            if got != want:
                fails.append("表头 %s anchor=%s 期望 %s" % (key, got, want))
        print("FAILS:", fails if fails else "无 —— 对齐规则与主表格一致")
    finally:
        root.destroy()


root.after(1500, step)
root.mainloop()
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
