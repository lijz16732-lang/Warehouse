# -*- coding: utf-8 -*-
"""真机验证：用真实鼠标事件在表格里拖选一块单元格，检查是否自动复制。

运行后会打开主窗口 → 模拟按下左键、划过 4 行 × 3 列 → 松开 → 读取剪贴板并截图。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk  # noqa: E402

from wm import app as wapp  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   ".tmpdbg", "drag_copy.png")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

root = tk.Tk()
app = wapp.App(root)
root.update()
rows = list(app.tree.get_children())[:4]
cols = app._cols()
print("列:", cols)
print("行数:", len(rows))
print("拖选即复制 =", app.var_drag_copy.get())

col_a = cols.index("brand")
col_b = cols.index("qty")


def center(iid, col_idx):
    b = app.tree.bbox(iid, column=col_idx)
    if not b:
        raise RuntimeError("bbox 为空：%s / %s" % (iid, col_idx))
    return b[0] + 6, b[1] + b[3] // 2


sx, sy = center(rows[0], col_a)
ex, ey = center(rows[3], col_b)
print("起点:", sx, sy, " 终点:", ex, ey)

app.tree.event_generate("<ButtonPress-1>", x=sx, y=sy)
root.update()
for i in range(1, 7):
    mx = sx + (ex - sx) * i // 6
    my = sy + (ey - sy) * i // 6
    app.tree.event_generate("<B1-Motion>", x=mx, y=my)
    root.update()
    time.sleep(0.02)
app.tree.event_generate("<ButtonRelease-1>", x=ex, y=ey)
root.update()

print("区块:", app._drag_block)
try:
    got = root.clipboard_get()
except tk.TclError:
    got = ""
print("--- 剪贴板内容 ---")
print(got)
print("------------------")
ok = bool(app._drag_block) and got.count("\n") == 4
print("拖选并自动复制:", "通过" if ok else "失败")
print("详情区标题:", app.lbl_detail_title.cget("text"))
app.tree.focus(rows[0])
root.update()
app.root.update_idletasks()
time.sleep(0.3)

try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools"))
    import screenshot
    screenshot.capture(OUT)
    print("截图 ->", OUT)
except Exception as e:
    print("截图失败:", e)

app._stopped = True
root.destroy()
print("完成")
