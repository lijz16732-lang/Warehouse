# -*- coding: utf-8 -*-
"""查明 Treeview 多 tag 同选项（background）时谁生效：创建先后 vs 列表顺序。"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.SetProcessDPIAware()
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = ctypes.c_uint32
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

import tkinter as tk
from tkinter import ttk


def pixel(x, y):
    hdc = user32.GetDC(None)
    try:
        c = gdi32.GetPixel(hdc, int(x), int(y))
    finally:
        user32.ReleaseDC(None, hdc)
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


root = tk.Tk()
root.geometry("700x400+100+100")
root.attributes("-topmost", True)
t = ttk.Treeview(root, columns=("a", "b"), show="headings", height=8)
t.heading("a", text="a")
t.heading("b", text="b")
t.column("a", width=200)
t.column("b", width=200)
t.pack()
# A 先创建（红），B 后创建（蓝）
t.tag_configure("A", background="#FF0000")
t.tag_configure("B", background="#0000FF")
for i in range(6):
    t.insert("", "end", iid=str(i), values=("x", "y"))
root.deiconify()
root.update()
time.sleep(0.5)
root.update()

CASES = [("0", ()), ("1", ("A",)), ("2", ("B",)),
         ("3", ("A", "B")), ("4", ("B", "A"))]
for iid, tags in CASES:
    t.item(iid, tags=tuple(tags))
root.update()
time.sleep(0.4)
root.update()
print("A 先创建=#FF0000(255,0,0)  B 后创建=#0000FF(0,0,255)  无 tag=白")
for iid, tags in CASES:
    real = tuple(t.item(iid, "tags"))
    b = t.bbox(iid, column="b")
    px = pixel(t.winfo_rootx() + b[0] + b[2] - 12,
               t.winfo_rooty() + b[1] + b[3] // 2)
    print("   行%s 传入=%-14s 实际=%-14s 像素=%s" % (iid, str(tags), str(real), px))
root.destroy()
