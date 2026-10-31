# -*- coding: utf-8 -*-
"""v1.27.5 CellHover 事件转发验证（合成事件模式，锁屏可跑）。

对贴片本身 event_generate 派发事件（贴片在真实场景中收到的事件就是这些），
断言「贴片 → event_generate → tree 处理器」转发链路逐项工作：
  T1 树上 Motion → 贴片出现在划过格
  T2 对贴片发 Motion（指针移到同行另一格）→ 贴片跟随（v1.27.4 卡死的主症状）
  T3 对贴片发 Button-3 → tree 右键处理器被触发（原 bug：右键菜单失灵）
  T4 对贴片发 Button-1 → 选中/焦点落回 tree（Ctrl+C 恢复的前提）
  T5 对贴片发 MouseWheel → 贴片隐藏

要点（前两版探针踩过的坑）：
  - 表格是 stretch 列，App 布局稳定前列边界会漂移 → 坐标必须现算，
    且 bbox 按列名取（#n 显示序号在个别路径下与 identify 语义有出入）；
  - 物理指针先移出窗口（SetCursorPos 锁屏下仍有效），否则真实指针
    停在表格里会触发 Enter 校正循环、污染断言；
  - 轮询按物理指针刷新，合成模式禁用（真实行为由
    tools/_probe_cellhover.py 在解锁状态验证）。
"""
import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ctypes.windll.user32.SetProcessDPIAware()

import tkinter as tk  # noqa: E402

from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_cellhover_syn_")
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
root.update()
time.sleep(0.5)          # 等 App 的布局/自适应 after 钩子全部落定
root.update()
time.sleep(0.3)
root.update()
# 物理指针移出窗口，避免真实指针位置干扰合成事件断言
ctypes.windll.user32.SetCursorPos(2, 2)
time.sleep(0.2)
root.update()

REC = {"rc": 0, "dbl": 0}
app.tree.bind("<Button-3>", lambda e: REC.__setitem__("rc", REC["rc"] + 1))
app.tree.bind("<Double-1>", lambda e: REC.__setitem__("dbl", REC["dbl"] + 1))
app.cell_hover._ensure_poll = lambda: None   # 合成模式禁用轮询（防污染断言）

tree = app.tree
ch = app.cell_hover
kids = [str(i) for i in tree.get_children()]
row1 = kids[0]
cols = app._cols()
code_idx = cols.index("code")
model_idx = cols.index("model")


def cellpt(iid, idx):
    """单元格中心（相对 tree 坐标），现算现用；按列名取 bbox。"""
    b = tree.bbox(iid, column=cols[idx])
    assert b, "bbox empty: %s %s" % (iid, cols[idx])
    return (b[0] + b[2] // 2, b[1] + b[3] // 2)


def settle(t=0.35):
    end = time.time() + t
    while time.time() < end:
        root.update()
        time.sleep(0.02)


FAILS = []


def check(name, cond, info=""):
    print("%s %s %s" % ("PASS" if cond else "FAIL", name, info))
    if not cond:
        FAILS.append(name)


def tree_motion(x, y):
    rx, ry = x + tree.winfo_rootx(), y + tree.winfo_rooty()
    tree.event_generate("<Enter>", x=x, y=y, rootx=rx, rooty=ry)
    tree.event_generate("<Motion>", x=x, y=y, rootx=rx, rooty=ry)


def label_motion(x, y):
    ch.lbl.event_generate("<Motion>", x=x, y=y,
                          rootx=x + tree.winfo_rootx(),
                          rooty=y + tree.winfo_rooty())


# ---- T1 树上划过：贴片出现 ----
ra = cellpt(row1, code_idx)
tree_motion(*ra)
settle()
check("T1 划过首格贴片出现", ch.cell == (row1, code_idx), "cell=%s" % (ch.cell,))

# ---- T2 对贴片发 Motion（指针已在新格）：贴片跟随 ----
rb = cellpt(row1, model_idx)          # 现算（列边界可能因布局漂移）
label_motion(*rb)
settle()
check("T2 贴片事件转发后跟随新格", ch.cell == (row1, model_idx),
      "cell=%s" % (ch.cell,))

# ---- T3 对贴片发右键：tree 处理器触发 ----
rb = cellpt(row1, model_idx)
ch.lbl.event_generate("<Button-3>", x=rb[0], y=rb[1],
                      rootx=rb[0] + tree.winfo_rootx(),
                      rooty=rb[1] + tree.winfo_rooty())
settle()
check("T3 贴片右键转发到 tree", REC["rc"] == 1, "rc=%d" % REC["rc"])

# ---- T4 对贴片发左键：选中/焦点落回 tree（Ctrl+C 前提） ----
rb = cellpt(row1, model_idx)
ch.lbl.event_generate("<Button-1>", x=rb[0], y=rb[1],
                      rootx=rb[0] + tree.winfo_rootx(),
                      rooty=rb[1] + tree.winfo_rooty())
ch.lbl.event_generate("<ButtonRelease-1>", x=rb[0], y=rb[1],
                      rootx=rb[0] + tree.winfo_rootx(),
                      rooty=rb[1] + tree.winfo_rooty())
settle()
check("T4 贴片点击转发选中该行", row1 in tree.selection() and tree.focus() == row1,
      "sel=%s focus=%s" % (tree.selection(), tree.focus()))
tree.focus_set()
tree.event_generate("<Control-c>")
settle()
try:
    got = root.clipboard_get()
except Exception:
    got = "<空>"
print("INFO Ctrl+C 剪贴板: %r" % got)

# ---- T5 对贴片发滚轮：贴片隐藏 ----
rb = cellpt(row1, model_idx)
label_motion(*rb)                     # 先让贴片出现
settle()
ch.lbl.event_generate("<MouseWheel>", x=rb[0], y=rb[1], delta=-120,
                      rootx=rb[0] + tree.winfo_rootx(),
                      rooty=rb[1] + tree.winfo_rooty())
settle()
check("T5 贴片滚轮转发后隐藏", ch.cell is None, "cell=%s" % (ch.cell,))

root.destroy()
print("\n结果: %s（%d 项失败）" % ("全部通过" if not FAILS else "FAIL " + ",".join(FAILS),
                                 len(FAILS)))
sys.exit(1 if FAILS else 0)
