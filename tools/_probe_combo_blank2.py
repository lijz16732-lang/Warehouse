# -*- coding: utf-8 -*-
"""探针 v2：readonly 下拉「开 -> 不选 -> 关」后显示层是否空白。
用 PIL ImageGrab 抓 entry 区域，统计暗像素（文字）占比作为“有没有画字”的判据。
场景：
  A 点箭头开 -> 点箭头关
  B 点框开 -> 点框关
  C 点箭头开 -> 点窗口其他位置关（FocusOut 路径）
每个场景先测裸 combobox（无 guard），再测套 guard_combobox 的。
"""
import sys
import os
import time
import ctypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab

from wm.constants import guard_combobox

user32 = ctypes.windll.user32


def real_click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.25)


def text_pixels(bbox):
    """entry 区域暗像素占比（近似“文字是否画出”）"""
    img = ImageGrab.grab(bbox=bbox).convert("L")
    px = list(img.getdata())
    dark = sum(1 for p in px if p < 120)
    return dark / max(len(px), 1)


root = tk.Tk()
root.geometry("320x140+100+100")
root.title("combo probe")

var = tk.StringVar(value="60 天")
cb = ttk.Combobox(root, textvariable=var, state="readonly", width=14,
                  values=["永久保留", "30 天", "60 天", "90 天", "180 天"])
cb.place(x=40, y=40)

root.update()
root.update_idletasks()

rx, ry = cb.winfo_rootx(), cb.winfo_rooty()
w, h = cb.winfo_width(), cb.winfo_height()
ax, ay = rx + w - 10, ry + h // 2       # 箭头
bx, by = rx + w // 2, ry + h // 2       # 框中央
ox, oy = rx + w + 60, ry + h // 2       # 窗口内其他位置
bbox = (rx + 2, ry + 2, rx + w - 18, ry + h - 2)  # entry 文字区（不含箭头）

user32.SetCursorPos(2, 2)


def report(tag):
    cb.tk.call("update", "idletasks")
    cb.tk.call("update")
    try:
        v_var = str(cb.tk.globalgetvar(str(var)))
    except Exception as e:
        v_var = "<err %s>" % e
    ratio = text_pixels(bbox)
    print("[%s] cb.get()=%r var=%r dark=%.3f -> %s" % (
        tag, cb.get(), v_var, ratio,
        "有字" if ratio > 0.01 else "空白!"))


def run_case(guarded):
    var.set("60 天")
    label = "guard" if guarded else "裸  "
    report("%s init        " % label)

    real_click(ax, ay)   # 点箭头开
    report("%s 开(点箭头)  " % label)
    real_click(ax, ay)   # 点箭头关
    report("%s 关(点箭头)  " % label)

    real_click(bx, by)
    report("%s 开(点框)    " % label)
    real_click(bx, by)
    report("%s 关(点框)    " % label)

    real_click(ax, ay)
    report("%s 开(点箭头)  " % label)
    real_click(ox, oy)   # 点别处
    report("%s 关(点别处)  " % label)
    print("-" * 60)


print("=== 场景 A-C：裸 combobox ===")
run_case(False)

print("=== 场景 A-C：guard_combobox ===")
cb2 = ttk.Combobox(root, textvariable=var, state="readonly", width=14,
                   values=["永久保留", "30 天", "60 天", "90 天", "180 天"])
guard_combobox(cb2)
cb2.place(x=40, y=80)
root.update()
rx2, ry2 = cb2.winfo_rootx(), cb2.winfo_rooty()
w2, h2 = cb2.winfo_width(), cb2.winfo_height()
ax, ay = rx2 + w2 - 10, ry2 + h2 // 2
bx, by = rx2 + w2 // 2, ry2 + h2 // 2
bbox = (rx2 + 2, ry2 + 2, rx2 + w2 - 18, ry2 + h2 - 2)
run_case(True)

root.after(300, root.destroy)
root.mainloop()
