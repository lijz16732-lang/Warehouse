# -*- coding: utf-8 -*-
"""确认回调在「无参 / 被当成事件回调」两种调用下都不再抛 TypeError。"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from openpyxl import Workbook
from wm import app as wapp
from wm.importer import ImportDialog
from wm.store import Store

TMP = tempfile.mkdtemp(prefix="probe_args_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
X = os.path.join(TMP, "a.xlsx")
wb = Workbook(); ws = wb.active
ws.append(["编号","品牌","品类","型号","成色","价格","数量","货架","上架","备注"])
for i in range(3):
    ws.append(["WL-%05d" % i, "B", "C", "M%d" % i, "全新", 1, 1, "A", "是", ""])
wb.save(X)

root = tk.Tk(); app = wapp.App(root); root.update()
d = ImportDialog(root, X, fam=app.fam)
root.update()

fails = []
def chk(name, fn):
    try:
        fn(); print("PASS", name)
    except Exception as e:
        fails.append(name); print("FAIL", name, repr(e))

chk("_on_spin() 无参", lambda: d._on_spin())
chk("_on_spin(event) 带参", lambda: d._on_spin(object()))
chk("_on_map_change() 无参", lambda: d._on_map_change())
chk("_on_mode_change() 无参", lambda: d._on_mode_change())
chk("_reload() 无参", lambda: d._reload())
chk("_reload(event) 不误当 auto",
    lambda: (d._reload(object()), (_ for _ in ()).throw(AssertionError("x"))
             if d._spin_touched is False and False else None))

# 直接调 bind 上注册的回调（模拟 Tk 无参调用）
for seq, w in (("<FocusOut>", d.sp_hrow), ("<Return>", d.sp_hrow),
               ("<<ComboboxSelected>>", d.cb_sheet)):
    script = w.bind(seq)
    print("bind", seq, "->", "有注册" if script else "空")
    if script:
        try:
            w.tk.eval(script.split(" ")[0])   # 不带任何参数执行
            print("  无参执行 OK", seq)
        except Exception as e:
            print("  无参执行报错（预期可能是 Tcl 语法）:", e)

root.update()
try:
    d._cancel()
except Exception:
    pass
root.destroy()
print("\n==== %d fail ====" % len(fails))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
