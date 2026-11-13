# -*- coding: utf-8 -*-
"""复现：导入 XLSX 对话框的 TypeError（lambda 缺 e）。

ImportDialog._build.<locals>.<lambda>() missing 1 required positional argument: 'e'
"""

import ctypes
import os
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk

from openpyxl import Workbook

from wm import app as wapp
from wm.importer import ImportDialog
from wm.store import Store

TMP = tempfile.mkdtemp(prefix="probe_imp_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
ctypes.windll.user32.SetCursorPos(2, 2)

XLSX = os.path.join(TMP, "库存.xlsx")
wb = Workbook()
ws = wb.active
ws.title = "库存"
ws.append(["编号", "品牌", "品类", "型号", "成色", "价格", "数量", "货架", "上架", "备注"])
for i in range(5):
    ws.append(["WL-%05d" % i, "B%d" % i, "C", "M%d" % i, "全新", 100, 2,
               "1排A-1", "是", ""])
wb.save(XLSX)

errs = []


def catch(tag, fn):
    try:
        fn()
        print("ok   %s" % tag)
    except Exception as e:
        errs.append((tag, e))
        print("ERR  %s -> %r" % (tag, e))
        traceback.print_exc()


root = tk.Tk()
app = wapp.App(root)
root.update()


def on_exc(exc, val, tb):
    errs.append(("callback", val))
    print("CALLBACK-ERR %r" % (val,))
    traceback.print_exception(exc, val, tb)


root.report_callback_exception = on_exc

dlg = None
catch("构造 ImportDialog", lambda: globals().__setitem__(
    "dlg", ImportDialog(root, XLSX, fam=app.fam,
                        existing_models=app.store.distinct("model"),
                        existing_blank=set())))
root.update()
d = globals()["dlg"]
print("dialog:", d)

if d is not None:
    time.sleep(0.3)
    root.update()

    # 1) 表头行 Spinbox 回车 / 失焦
    catch("sp_hrow event <Return>",
          lambda: (d.sp_hrow.event_generate("<Return>"), root.update()))
    catch("sp_hrow 失焦（焦点给下拉）",
          lambda: (d.sp_hrow.focus_set(), root.update(),
                   d.cb_sheet.focus_set(), root.update()))

    # 2) 切换工作表
    catch("cb_sheet <<ComboboxSelected>>",
          lambda: (d.cb_sheet.event_generate("<<ComboboxSelected>>"),
                   root.update()))

    # 3) 自动识别表头按钮
    def click_auto():
        for w in d.winfo_children():
            for c in _all(w):
                if c.winfo_class() == "TButton" and str(c.cget("text")) == "自动识别表头":
                    c.invoke()
                    return
        raise RuntimeError("没找到按钮")

    def _all(w, out=None):
        out = out if out is not None else []
        out.append(w)
        for c in w.winfo_children():
            _all(c, out)
        return out

    catch("点「自动识别表头」", click_auto)
    root.update()

    # 4) 切换导入方式
    catch("切到覆盖全部", lambda: (d.var_mode.set("replace"),
                                   d._on_mode_change(), root.update()))

    # 5) 开始导入（会 destroy）
    catch("点「开始导入」", lambda: (d.btn_ok.invoke(), root.update()))

root.destroy()
print("\n==== errors: %d ====" % len(errs))
for t, e in errs:
    print(" -", t, "->", repr(e))
sys.exit(1 if errs else 0)
