# -*- coding: utf-8 -*-
"""单实例：逐步交互，每步打印下拉框取值，定位「没选就变空白」。"""
import ctypes, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from tkinter import ttk
from wm import app as wapp
from wm.store import Store
import screenshot

u32 = ctypes.windll.user32
u32.SetCursorPos(2, 2)
TMP = tempfile.mkdtemp(prefix="probe_cbr_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
out = os.path.join(ROOT, ".tmpdbg"); os.makedirs(out, exist_ok=True)

root = tk.Tk(); app = wapp.App(root); root.update()
tk.Toplevel.grab_set = lambda self, *a: None   # 环境里可能有别的 grab
app.open_appearance("format"); root.update()
win = app._settings_win
win.title("W M CBR 探针"); win.lift(); win.focus_force()
root.update(); time.sleep(0.3); root.update()

def walk(w, out_l):
    out_l.append(w)
    for c in w.winfo_children():
        walk(c, out_l)

ws = []; walk(win, ws)
cbs = [w for w in ws if isinstance(w, ttk.Combobox) and w.winfo_viewable()]
cb = cbs[-1]          # 默认导出格式
print("初始 get=%r" % cb.get())

def click(px, py, tag):
    u32.SetCursorPos(int(px), int(py))
    time.sleep(0.1)
    u32.mouse_event(2, 0, 0, 0, 0)
    time.sleep(0.04)
    u32.mouse_event(4, 0, 0, 0, 0)
    root.update(); time.sleep(0.15); root.update()
    print("%-14s get=%r  sel=%s" % (tag, cb.get(),
          _sel(cb) if _ok(cb) else "-"))

def _ok(w):
    try:
        w.winfo_exists(); return True
    except Exception:
        return False

def _sel(w):
    try:
        return w.selection_present()
    except Exception:
        return "-"

cx = cb.winfo_rootx() + cb.winfo_width() // 3
cy = cb.winfo_rooty() + cb.winfo_height() // 2
ax_ = cb.winfo_rootx() + cb.winfo_width() - 8     # 箭头
away_x = win.winfo_rootx() + 620
away_y = win.winfo_rooty() + 300                   # 页面空白区

# S1 点输入区 → 点空白
click(cx, cy, "S1点输入区")
click(away_x, away_y, "S1点空白")

# S2 点箭头展开 → 点空白收起（不选值）
click(ax_, cy, "S2点箭头")
screenshot.capture_window("W M CBR 探针", os.path.join(out, "cbr_popdown.png"))
click(away_x, away_y, "S2点空白")

# S3 再点一次输入区
click(cx, cy, "S3点输入区")
screenshot.capture_window("W M CBR 探针", os.path.join(out, "cbr_final.png"))

u32.SetCursorPos(2, 2); root.update()
root.destroy()
print("done")
