# -*- coding: utf-8 -*-
"""临时脚本：验证 v1.7.12 多货架导入（同字段多列自动合并）。

构造带「货架(位置1)/货架(位置2)/货架(位置3)」列的 xlsx，
打开导入向导截图，并打印合并后的货架值。"""
import os
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import openpyxl  # noqa: E402
from wm.importer import ImportDialog  # noqa: E402
from wm.store import Store  # noqa: E402
from wm.constants import MULTI_SEP  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_multi_")
XLSX = os.path.join(TMP, "multi_shelf.xlsx")
OUT = os.path.join(ROOT, ".tmpdbg", "import_multi_shelf.png")

wb = openpyxl.Workbook()
ws = wb.active
ws.append(["品牌", "品类", "型号", "数量", "价格(元)", "货架(位置1)", "货架(位置2)", "货架(位置3)", "是否上架"])
rows = [
    ["罗技", "外设", "MX MASTER 3", 2, 599, "6排A-3", "7排A-1", "", "是"],
    ["罗技", "外设", "MX KEYS", 1, 399, "2排A-1", "2排B-1", "2排B-2", "否"],
    ["西门子", "驱动器", "V20", 3, 1200, "5排A-1", "5排A-1", "", "是"],
    ["戴尔", "显示器", "U2720Q", 1, 1580, "8排C-1", "", "", "是"],
]
for r in rows:
    ws.append(r)
wb.save(XLSX)

db = os.path.join(TMP, "warehouse.db")
store = Store(db)

root = tk.Tk()
root.geometry("1x1+0+0")
dlg = ImportDialog(root, XLSX, "Microsoft YaHei UI",
                   existing_models=store.model_keys())
dlg.update()


def shoot():
    dlg.attributes("-topmost", True)
    dlg.lift()
    dlg.update()
    dlg.after(600, capture)


def capture():
    dlg.update()
    screenshot.capture(OUT)
    print("shot ->", OUT)
    print("mapping:", dlg.mapping)
    print("unmapped:", dlg.unmapped)
    from wm.xlsxio import normalize_record
    for r in dlg.records:
        print("货架值:", repr(normalize_record(r)["shelf"]))
    dlg.destroy()
    root.destroy()


dlg.after(1000, shoot)
root.mainloop()
store.close()
