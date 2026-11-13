# -*- coding: utf-8 -*-
"""验证：焦点在「表头行」Spinbox 上时销毁导入对话框 / 让它失焦，会不会 0 参调用 lambda。"""
import os, sys, tempfile, time, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from openpyxl import Workbook
from wm import app as wapp
from wm.importer import ImportDialog
from wm.store import Store

TMP = tempfile.mkdtemp(prefix="probe_des_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()

X = os.path.join(TMP, "a.xlsx")
wb = Workbook(); ws = wb.active
ws.append(["编号","品牌","品类","型号","成色","价格","数量","货架","上架","备注"])
for i in range(3):
    ws.append(["WL-%05d" % i, "B", "C", "M%d" % i, "全新", 1, 1, "A", "是", ""])
wb.save(X)

root = tk.Tk(); app = wapp.App(root); root.update()
errs = []
def on_exc(exc, val, tb):
    errs.append(val); print("CALLBACK-ERR", repr(val)); traceback.print_exception(exc, val, tb)
root.report_callback_exception = on_exc

# 场景 A：焦点在 sp_hrow 上直接 destroy
d = ImportDialog(root, X, fam=app.fam)
root.update(); time.sleep(0.2); root.update()
d.sp_hrow.focus_set(); root.update()
d.destroy(); root.update()
print("A done, errs=%d" % len(errs))

# 场景 B：焦点在 sp_hrow 上点取消
d = ImportDialog(root, X, fam=app.fam)
root.update(); time.sleep(0.2); root.update()
d.sp_hrow.focus_set(); root.update()
d._cancel(); root.update()
print("B done, errs=%d" % len(errs))

# 场景 C：对话框销毁后仍有排队事件
d = ImportDialog(root, X, fam=app.fam)
root.update(); time.sleep(0.2); root.update()
d.sp_hrow.focus_set()
d.destroy()
for _ in range(10):
    root.update(); time.sleep(0.02)
print("C done, errs=%d" % len(errs))

root.destroy()
print("TOTAL errors:", len(errs), errs)
