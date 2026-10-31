# -*- coding: utf-8 -*-
"""v1.27.5 CellHover 事件转发票：真实鼠标验证贴片跟随 / 右键 / Ctrl+C / 双击。

背景（v1.27.4 实测 bug）：CellHover 贴片盖在指针下面后，tree 的
Motion/Enter/点击/右键/滚轮全被吃掉——贴片不跟随、右键菜单失灵、Ctrl+C 失灵。
修复：贴片事件 event_generate 转发回 tree + 指针位置轮询兜底。
本探针用 ctypes 真实鼠标（event_generate 模拟点击有假阳性）逐项断言。
"""
import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

from PIL import ImageGrab  # noqa: E402
import tkinter as tk  # noqa: E402

from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_cellhover_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP   # 隔离数据目录（否则会连到项目 data/ 开发库）
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                         "model": "M-%d" % i, "price": 10.0 * i,
                                         "qty": 8, "listed": 1}
                       for i in range(1, 21)])
app.load_data()
root.geometry("1500x900+60+40")
root.deiconify()
root.attributes("-topmost", True)
root.update()
time.sleep(0.4)
root.update()

RIGHTDOWN, RIGHTUP = 0x0008, 0x0010
LEFTDOWN, LEFTUP = 0x0002, 0x0004
WHEELEVENT = 0x0800
VK_CTRL, VK_C = 0x11, 0x43

REC = {"rc": 0, "dbl": 0}
# 用替换绑定拦住会弹模态菜单/对话框的处理器（只记录不执行原逻辑）
app.tree.bind("<Button-3>", lambda e: REC.__setitem__("rc", REC["rc"] + 1))
app.tree.bind("<Double-1>", lambda e: REC.__setitem__("dbl", REC["dbl"] + 1))

kids = [str(i) for i in app.tree.get_children()]
row1 = kids[0]
cols = app._cols()
code_idx = cols.index("code")
model_idx = cols.index("model")
ch = app.cell_hover


def cellpx(iid, idx):
    """单元格中心（绝对屏幕坐标），现算现用；按列名取 bbox。"""
    b = app.tree.bbox(iid, column=cols[idx])
    assert b, "bbox empty: %s %s" % (iid, cols[idx])
    return (app.tree.winfo_rootx() + b[0] + b[2] // 2,
            app.tree.winfo_rooty() + b[1] + b[3] // 2)


def blue(x, y):
    r, g, b = ImageGrab.grab(bbox=(x, y, x + 1, y + 1)).getpixel((0, 0))[:3]
    return abs(r - 0x35) < 24 and abs(g - 0x84) < 24 and abs(b - 0xE4) < 24


def settle(t=0.45):
    end = time.time() + t
    while time.time() < end:
        root.update()
        time.sleep(0.03)


FAILS = []


def check(name, cond, info=""):
    print("%s %s %s" % ("PASS" if cond else "FAIL", name, info))
    if not cond:
        FAILS.append(name)


pa = cellpx(row1, code_idx)
pb = cellpx(row1, model_idx)

# ---- 1) 划入首格：贴片出现 ----
user32.SetCursorPos(4, 4)
settle(0.3)
user32.SetCursorPos(*pa)
settle()
check("T1 贴片出现在划过格", ch.cell == (row1, code_idx) and blue(*pa),
      "cell=%s" % (ch.cell,))

# ---- 2) 同行移到另一格：贴片跟随（本次报障主症状） ----
user32.SetCursorPos(*pb)
settle()
check("T2 贴片跟随到新格", ch.cell == (row1, model_idx),
      "cell=%s" % (ch.cell,))
check("T2b 新格蓝底/旧格已还原", blue(*pb) and not blue(*pa))

# ---- 3) 贴片上右键：菜单处理器被触发（原 bug：贴片吞掉右键） ----
ctypes.windll.user32.mouse_event(RIGHTDOWN, 0, 0, 0, 0)
time.sleep(0.08)
ctypes.windll.user32.mouse_event(RIGHTUP, 0, 0, 0, 0)
settle(0.3)
check("T3 贴片上右键到达 tree", REC["rc"] == 1, "rc=%d" % REC["rc"])

# ---- 4) 贴片格点击后 Ctrl+C：复制所指单元格 ----
ctypes.windll.user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)
time.sleep(0.06)
ctypes.windll.user32.mouse_event(LEFTUP, 0, 0, 0, 0)
settle(0.55)          # 等 350ms 冷却结束、贴片按轮询恢复
user32.keybd_event(VK_CTRL, 0, 0, 0)
time.sleep(0.05)
user32.keybd_event(VK_C, 0, 0, 0)
time.sleep(0.05)
user32.keybd_event(VK_C, 0, 2, 0)
user32.keybd_event(VK_CTRL, 0, 2, 0)
settle(0.3)
want = app.fmt("model", app.by_id[row1])
try:
    got = root.clipboard_get()
except Exception:
    got = "<无法读取>"
check("T4 Ctrl+C 复制所指单元格", got == want, "got=%r want=%r" % (got, want))

# ---- 5) 贴片格双击：Double-1 要能触发（生成+真实按键的序列） ----
user32.SetCursorPos(*pa)
settle()
for _ in range(2):
    ctypes.windll.user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.mouse_event(LEFTUP, 0, 0, 0, 0)
    time.sleep(0.08)
settle(0.3)
check("T5 贴片格双击触发 Double-1", REC["dbl"] == 1, "dbl=%d" % REC["dbl"])

# ---- 6) 滚轮：贴片先藏（滚动后不残留旧位置） ----
user32.SetCursorPos(*pb)
settle()
ctypes.windll.user32.mouse_event(WHEELEVENT, 0, 0, -120, 0)
settle(0.3)
check("T6 滚轮后贴片隐藏", ch.cell is None, "cell=%s" % (ch.cell,))

# ---- 7) 滚动后停住不动：轮询兜底让贴片按指针归位 ----
settle(0.6)           # 不动鼠标，等至少一个 150ms 轮询周期
check("T7 轮询兜底重新贴合", ch.cell == (row1, model_idx) and blue(*pb),
      "cell=%s" % (ch.cell,))

user32.SetCursorPos(4, 4)
root.destroy()
print("\n结果: %s（%d 项失败）" % ("全部通过" if not FAILS else "FAIL " + ",".join(FAILS),
                                 len(FAILS)))
sys.exit(1 if FAILS else 0)
