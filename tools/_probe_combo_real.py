# -*- coding: utf-8 -*-
"""真实 App 探针 v4：验证 guard_combobox 修复「开->不选->关」空白。
三条关闭路径各跑两轮，全有字 = PASS；并检查 repack 后布局没变。"""
import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab

from wm import app as wapp

try:
    from wm.screen import enable_dpi_awareness
    enable_dpi_awareness()
    print("dpi awareness: on")
except Exception as e:
    print("dpi awareness: off", e)

TMP = tempfile.mkdtemp(prefix="probe_combo_v4_")
wapp.resolve_data_dir = lambda: TMP

user32 = ctypes.windll.user32


def real_click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.35)


root = tk.Tk()
app = wapp.App(root)
root.update()

app.open_appearance("system")
root.update()
win = app._settings_win
win.attributes("-topmost", True)
win.lift()
root.update()
win.update()
time.sleep(0.8)
root.update()
win.update()

found = []


def walk(w):
    found.append(w)
    for c in w.winfo_children():
        walk(c)


walk(win)
cb = [w for w in found if isinstance(w, ttk.Combobox)
      and "永久保留" in (list(w.cget("values")) or [])][0]
for cv in [w for w in found if isinstance(w, tk.Canvas)]:
    try:
        cv.yview_moveto(1.0)
    except Exception:
        pass
root.update()
win.update()
time.sleep(0.3)
root.update()
win.update()

rx, ry = cb.winfo_rootx(), cb.winfo_rooty()
w, h = cb.winfo_width(), cb.winfo_height()
print("cb at %d,%d %dx%d" % (rx, ry, w, h))

layout_before = (str(cb.winfo_rootx()), str(cb.winfo_rooty()),
                 str(cb.winfo_width()), str(cb.winfo_height()))
row_widgets_before = [str(x) for x in cb.master.pack_slaves()]


def dark():
    root.update()
    win.update()
    img = ImageGrab.grab(bbox=(rx + 2, ry + 2, rx + w - 18, ry + h - 2)).convert("L")
    px = list(img.getdata())
    return sum(1 for p in px if p < 120) / max(len(px), 1)


fails = []


def case(name, way):
    d0 = dark()
    px, py = rx + w - 10, ry + h // 2
    if way == "arrow":
        real_click(px, py)
        real_click(px, py)
    elif way == "box":
        real_click(rx + w // 2, ry + h // 2)
        real_click(rx + w // 2, ry + h // 2)
    else:
        real_click(px, py)
        real_click(rx + w + 120, ry + h // 2)
    d1 = dark()
    ok = d1 > 0.01
    print("[%s] 关(%s) 前=%.4f 后=%.4f get=%r -> %s" % (
        name, way, d0, d1, cb.get(), "PASS" if ok else "FAIL 空白"))
    if not ok:
        fails.append("%s(%s)" % (name, way))
    time.sleep(0.2)


for i in (1, 2):
    case("轮%d" % i, "arrow")
    case("轮%d" % i, "box")
    case("轮%d" % i, "outside")

# 布局保持检查（repack 用 before= 保序）
root.update()
win.update()
layout_after = (str(cb.winfo_rootx()), str(cb.winfo_rooty()),
                str(cb.winfo_width()), str(cb.winfo_height()))
row_widgets_after = [str(x) for x in cb.master.pack_slaves()]
print("位置保持:", "PASS" if layout_before == layout_after else
      "FAIL %s -> %s" % (layout_before, layout_after))
print("兄弟保序:", "PASS" if row_widgets_before == row_widgets_after else
      "FAIL %s -> %s" % (row_widgets_before, row_widgets_after))
if layout_before != layout_after:
    fails.append("layout")
if row_widgets_before != row_widgets_after:
    fails.append("order")

# 额外：正常选择流程不破坏（点开第一行选中永久保留不弹对话框）
print("---- 正常选择流程 ----")
px, py = rx + w - 10, ry + h // 2
real_click(px, py)          # 开
# 弹层列表第一行：cb 下方第一行中心
real_click(rx + w // 2, ry + h + 12)
d = dark()
print("选择后 get=%r dark=%.4f" % (cb.get(), d))
if cb.get() != "永久保留":
    print("注意：选中的是别的项 ->", cb.get())

root.update()
time.sleep(0.3)
root.destroy()

print("\n==== %d fail ====" % len(fails))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
