# -*- coding: utf-8 -*-
"""用 ctypes 真实鼠标点「表头行」Spinbox 的上下箭头、工作表下拉，抓回调异常。"""
import ctypes, ctypes.wintypes as wt, os, sys, tempfile, time, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from openpyxl import Workbook
from wm import app as wapp
from wm.importer import ImportDialog
from wm.store import Store

u32 = ctypes.windll.user32
u32.SetCursorPos(2, 2)

TMP = tempfile.mkdtemp(prefix="probe_clk_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()

X = os.path.join(TMP, "a.xlsx")
wb = Workbook(); ws = wb.active
ws.append(["编号","品牌","品类","型号","成色","价格","数量","货架","上架","备注"])
for i in range(3):
    ws.append(["WL-%05d" % i, "B", "C", "M%d" % i, "全新", 1, 1, "A", "是", ""])
ws2 = wb.create_sheet("第二个表")
for i in range(3):
    ws2.append(["编号","品牌","品类","型号","成色","价格","数量","货架","上架","备注"])
wb.save(X)

root = tk.Tk(); app = wapp.App(root); root.update()
errs = []
def on_exc(exc, val, tb):
    errs.append(val); print("CALLBACK-ERR", repr(val)); traceback.print_exception(exc, val, tb)
root.report_callback_exception = on_exc

def click(x, y, n=1):
    u32.SetCursorPos(int(x), int(y))
    for _ in range(n):
        u32.mouse_event(2, 0, 0, 0, 0)   # down
        u32.mouse_event(4, 0, 0, 0, 0)   # up
        root.update(); time.sleep(0.08)

d = ImportDialog(root, X, fam=app.fam)
root.update(); time.sleep(0.4); root.update()

sp = d.sp_hrow
x0, y0 = sp.winfo_rootx(), sp.winfo_rooty()
w, h = sp.winfo_width(), sp.winfo_height()
print("spin at", x0, y0, w, h)

# 点下箭头 / 上箭头（ttk spinbox 右侧两个小按钮）
click(x0 + w - 8, y0 + h - 5)
print("after down-arrow errs=%d" % len(errs))
click(x0 + w - 8, y0 + 4)
print("after up-arrow errs=%d" % len(errs))
click(x0 + w - 8, y0 + h - 5)
click(x0 + w - 8, y0 + h - 5)
print("after 3x down errs=%d" % len(errs))

# 点进输入框再回车
click(x0 + 10, y0 + h // 2)
d.sp_hrow.event_generate("<Return>"); root.update()

# 点工作表下拉，展开再选第二项
cb = d.cb_sheet
cx, cy = cb.winfo_rootx() + 10, cb.winfo_rooty() + cb.winfo_height() // 2
click(cx, cy)
root.update(); time.sleep(0.2)
print("combobox opened errs=%d" % len(errs))
click(cx, cy + 30)      # 选第二项
root.update(); time.sleep(0.2)
print("after pick sheet errs=%d" % len(errs))

u32.SetCursorPos(2, 2); root.update()
try:
    d._cancel()
except Exception:
    pass
root.update()
root.destroy()
print("\nTOTAL errors:", len(errs))
for e in errs:
    print(" -", repr(e))
sys.exit(1 if errs else 0)
