# -*- coding: utf-8 -*-
"""临时脚本：打开导入向导并截图，用于验证 v1.4.0 向导界面。"""
import ctypes
import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from wm.importer import ImportDialog  # noqa: E402
from wm.store import Store  # noqa: E402
import screenshot  # noqa: E402

REAL_DB = r"D:\仓库管理工具\data\warehouse.db"
XLSX = r"C:\Users\Administrator\Desktop\已修复1.xlsx"
OUT = os.path.join(ROOT, ".tmpdbg", "import_dialog_v140.png")

root = tk.Tk()
root.geometry("1x1+0+0")
store = Store(REAL_DB)
dlg = ImportDialog(root, XLSX, "Microsoft YaHei UI", existing_models=store.model_keys())
dlg.update()


def shoot():
    dlg.attributes("-topmost", True)
    dlg.deiconify()
    dlg.geometry("+80+60")
    dlg.lift()
    dlg.focus_force()
    dlg.update()
    print("mapped:", dlg.winfo_ismapped(), "viewable:", dlg.winfo_viewable(),
          "geom:", dlg.winfo_geometry(), "x,y:", dlg.winfo_x(), dlg.winfo_y())
    dlg.after(500, capture)


def capture():
    dlg.deiconify()
    dlg.update_idletasks()
    dlg.update()
    dlg.after(800, do_capture)


def do_capture():
    dlg.update()
    print("mapped:", dlg.winfo_ismapped(), "geom:", dlg.winfo_geometry())
    screenshot.capture(OUT)
    print("shot ->", OUT)
    print("模式:", dlg.var_mode.get())
    print("有 chk_skip:", hasattr(dlg, "chk_skip"), "有 chk_dedupe:", hasattr(dlg, "chk_dedupe"))
    print("提示:", dlg.lbl_hint.cget("text"))
    print("安全说明:", dlg.lbl_safe.cget("text"))
    dlg.destroy()
    root.destroy()


dlg.after(1200, shoot)
root.mainloop()
store.close()
