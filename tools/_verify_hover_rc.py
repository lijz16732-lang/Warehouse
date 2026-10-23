# -*- coding: utf-8 -*-
"""真机验证（v1.10.7）：鼠标划过整行高亮。

机器判定不看 tag，而是直接读屏幕像素（GDI GetPixel）：
  - 划过普通行/下架行/低库存行 → 背景 == 划过色（优先级高于斑马纹/下架灰/低库存橙）
  - 移开后 → 背景回到该行原本的颜色
  - 划过已上色行 → 单元格保持用户色，只多一圈淡蓝描边
"""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.SetProcessDPIAware()
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = ctypes.c_uint32
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.constants import CLR_HOVER_EDGE  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


def pixel(x, y):
    """屏幕像素 → (r, g, b)。"""
    hdc = user32.GetDC(None)
    try:
        c = gdi32.GetPixel(hdc, int(x), int(y))
    finally:
        user32.ReleaseDC(None, hdc)
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


HOVER = hex2rgb("#E9F1FF")
PLAIN = (255, 255, 255)
ALT = hex2rgb("#F7FAFD")
UNLISTED = hex2rgb("#F1F3F7")
LOW = hex2rgb("#FFF3E2")
EDGE = hex2rgb(CLR_HOVER_EDGE)


def near(a, b, tol=6):
    return all(abs(a[i] - b[i]) <= tol for i in range(3))


TMP = tempfile.mkdtemp(prefix="wm_hov_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
rows = []
for i in range(1, 31):
    rec = blank_record() | {"code": "WL-%05d" % i, "brand": "ABB", "category": "PLC",
                            "model": "M-%d" % i, "price": 10.0 * i, "qty": 8,
                            "listed": 1, "remark": ""}
    if i == 4:
        rec["listed"] = 0              # 下架行（灰显）
    if i == 6:
        rec["qty"] = 1                 # 低库存行（橙底）
    rows.append(rec)
app.store.insert_many(rows)
app.load_data()
app.var_low_hl.set(True)
app.toggle_low_hl()
app.var_unlisted_hl.set(True)
app.toggle_unlisted_hl()
root.geometry("1500x900+60+40")
root.deiconify()
root.attributes("-topmost", True)
root.update()
time.sleep(0.6)
root.update()


def cell_px(iid, colname, dx=0):
    b = app.tree.bbox(iid, column=colname)
    return (app.tree.winfo_rootx() + b[0] + b[2] // 2 + dx,
            app.tree.winfo_rooty() + b[1] + b[3] // 2)


def move_to(pt, pause=0.35):
    """移动鼠标并等事件循环跑完（Leave 事件是延迟 20ms 才判定，要多泵一轮）。"""
    user32.SetCursorPos(int(pt[0]), int(pt[1]))
    root.update()
    time.sleep(pause)
    root.update()
    time.sleep(0.08)
    root.update()


kids = [str(i) for i in app.tree.get_children()]
print("行数:", len(kids), "| 表头高:", app._head_height())

# ---- 1. 普通行（第 3 行，奇数行有斑马纹都测一遍） ----
for idx, base in ((2, PLAIN), (1, ALT)):
    iid = kids[idx]
    p = cell_px(iid, "remark")
    before = pixel(*p)
    move_to(p)
    after = pixel(*p)
    check("划过第 %d 行：tag 正确" % (idx + 1), app.hover.row == iid,
          "%s vs %s" % (app.hover.row, iid))
    check("划过第 %d 行：背景变划过色" % (idx + 1), near(after, HOVER),
          "%s→%s（底色 %s）" % (before, after, base))
    move_to((p[0], p[1] + 400))     # 移到表格空白/下面
    back = pixel(*p)
    print("   [调试] 移开后 hover.row=%s 该行tags=%s 像素=%s"
          % (app.hover.row, app.tree.item(iid, "tags"), back))
    check("移开第 %d 行：背景复原" % (idx + 1), near(back, base),
          "%s vs %s" % (back, base))

# ---- 2. 下架行 / 低库存行：划过色优先 ----
for idx, base, name in ((3, UNLISTED, "下架行"), (5, LOW, "低库存行")):
    iid = kids[idx]
    p = cell_px(iid, "remark")
    before = pixel(*p)
    ok_base = near(before, base)
    move_to(p)
    after = pixel(*p)
    check("%s 静止时底色正确" % name, ok_base, str(before))
    check("%s 划过时背景变划过色" % name, near(after, HOVER),
          "%s→%s" % (before, after))
    move_to((p[0], p[1] + 400))

# ---- 3. 表头 & 表格外不触发 ----
move_to((app.tree.winfo_rootx() + 120, app.tree.winfo_rooty() + 8))
check("划过表头不高亮", app.hover.row is None, str(app.hover.row))
user32.SetCursorPos(4, 4)          # 移到屏幕左上角（窗口外）
root.update()
time.sleep(0.35)
root.update()
time.sleep(0.08)
root.update()
check("鼠标移出窗口后清除高亮", app.hover.row is None
      and all("hover" not in app.tree.item(i, "tags") for i in app.tree.get_children()),
      str(app.hover.row))

# ---- 4. 已上色行：颜色不被覆盖，只加淡蓝描边 ----
iid = kids[7]
app._drag_block = None
app._block_preview = None
app.tree.selection_set(iid)
app.paint_cells("#FFD9D9")
app.tree.selection_set()
app.hover.set(None)
root.update()
p = cell_px(iid, "remark")
move_to(p)
body = pixel(p[0], p[1])
check("划过已上色行：单元格保持用户颜色", near(body, hex2rgb("#FFD9D9")),
      str(body))
bb = app.tree.bbox(iid, column="remark")
cx = app.tree.winfo_rootx() + bb[0] + bb[2] // 2
top = app.tree.winfo_rooty() + bb[1]
edge_samples = [pixel(cx, top + d) for d in (0, 1, 2)]
edge = min(edge_samples, key=lambda p: sum(abs(p[i] - EDGE[i]) for i in range(3)))
out_rows = [i for i in app.tree.get_children()
            if any(getattr(lb, "_row_iid", None) == str(i)
                   and int(str(lb.cget("highlightthickness"))) == 1
                   for lb in app._paint_labels)]
print("   [调试] 上色行 hover.row=%s 贴片数=%d 各行号=%s 描边=%s"
      % (app.hover.row, len(app._paint_labels),
         sorted({getattr(lb, "_row_iid", None) for lb in app._paint_labels}),
         sorted({int(str(lb.cget("highlightthickness"))) for lb in app._paint_labels})))
check("划过已上色行：贴片加淡蓝描边",
      str(iid) in out_rows and near(edge, EDGE, 40), "%s %s" % (out_rows, edge))
screenshot.capture_window("仓管家", os.path.join(OUT, "verify_hover_rc.png"))

# ---- 5. 出售/出库记录页也有划过高亮 ----
app.tab_out.refresh_rows()
root.update()
app.nb.select(app.tab_out)
root.update()
time.sleep(0.4)
ok_out = True
tr = app.tab_out.tree
o_kids = list(tr.get_children())
if o_kids:
    b = tr.bbox(str(o_kids[0]))
    pt = (tr.winfo_rootx() + b[0] + b[2] // 2, tr.winfo_rooty() + b[1] + b[3] // 2)
    move_to(pt, 0.5)
    tags_out = tr.item(str(o_kids[0]), "tags")
    ok_out = "hover" in tags_out and app.tab_out.hover.row == str(o_kids[0])
    print("  出库页划过:", app.tab_out.hover.row, tags_out)
check("出库记录页划过高亮", ok_out, str(app.tab_out.hover.row))

print("== 结果：%s ==" % ("全部通过" if not FAILS else "失败 %d 项" % len(FAILS)))
root.destroy()
sys.exit(1 if FAILS else 0)
