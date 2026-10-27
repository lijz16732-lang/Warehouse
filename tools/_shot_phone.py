# -*- coding: utf-8 -*-
"""临时脚本：v1.18.0「手机数据」页截屏验证（独立临时库，不影响真实数据）。"""
import os
import shutil
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.store import Store  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_v1180_")
wapp.app_dir = lambda: TMP
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

st = Store(os.path.join(TMP, "data", "warehouse.db"))
st.m_upsert_item({"lid": 101, "code": "APP-00001", "brand": "端到端测试品",
                  "category": "配件", "model": "E2E-1", "condition": "全新",
                  "qty": 2, "price": 66, "shelf": "T1",
                  "synced_at": "2026-10-27 11:43:30"})
st.m_upsert_sale({"lid": 201, "item_lid": 101, "code": "APP-00001",
                  "brand": "端到端测试品", "model": "E2E-1", "qty": 1,
                  "price": 70, "total": 70, "buyer": "测试买家",
                  "sale_date": "2026-10-27 11:50",
                  "synced_at": "2026-10-27 11:43:30"})
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)


def step_phone():
    root.title("仓管家-手机数据页验证")
    app.nb.select(app.tab_phone)
    app.tab_phone.refresh_rows()
    root.update()


def step_shot():
    root.update()
    screenshot.capture_window("手机数据页验证",
                              os.path.join(OUT, "deploy_1180_align.png"))
    print("shot -> deploy_1180_align.png")
    root.destroy()


root.after(800, step_phone)
root.after(1800, step_shot)
root.mainloop()
shutil.rmtree(TMP, ignore_errors=True)
print("done")
