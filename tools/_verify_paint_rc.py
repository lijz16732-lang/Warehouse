# -*- coding: utf-8 -*-
"""真机验证：框选区块 → 右键 → 区域上色，是否按整个区块上色（v1.10.5 修复）。

覆盖三种场景（都用真实鼠标事件）：
  A. 直接框选（起点是普通格子）→ 右键区块内 → 是否识别整块
  B. 先上色，再从已上色格子开始框选（贴片起点）→ 右键区块内
  C. 右键落在区块外（应回落到单行，避免误上色）
"""
import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()          # 让 Tk 坐标 == 物理像素

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="wm_prc_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
app.store.insert_many([
    blank_record() | {"code": "WL-0000%d" % i, "brand": "LENZE伦茨" if i % 2 else "AB罗克韦尔",
                      "category": "电机" if i % 2 else "PLC底座",
                      "model": "MDSKSRS036-%d" % i, "price": 100.0 * i, "qty": i,
                      "shelf": "9排B-%d" % i, "listed": 1} for i in range(1, 7)])
app.load_data()
root.geometry("1500x900+60+40")
root.deiconify()
root.attributes("-topmost", True)
root.update()
time.sleep(0.6)
root.update()

# 关掉「拖选即复制」（避免复制动作干扰），改由区块保存路径验证
app.var_drag_copy.set(False)
app._save_drag_copy()
root.update()


def cell_xy(iid, colname):
    b = app.tree.bbox(iid, column=colname)
    if not b:
        raise RuntimeError("bbox 为空：%s / %s" % (iid, colname))
    return (app.tree.winfo_rootx() + b[0] + b[2] // 2,
            app.tree.winfo_rooty() + b[1] + b[3] // 2)


def real_drag(p0, p1, steps=10):
    user32.SetCursorPos(*p0)
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)          # 左键按下
    time.sleep(0.15)
    for i in range(1, steps + 1):
        user32.SetCursorPos(p0[0] + (p1[0] - p0[0]) * i // steps,
                            p0[1] + (p1[1] - p0[1]) * i // steps)
        time.sleep(0.06)
    user32.mouse_event(0x0004, 0, 0, 0, 0)          # 左键松开
    time.sleep(0.45)
    root.update()


def real_rclick(p):
    user32.SetCursorPos(*p)
    time.sleep(0.2)
    user32.mouse_event(0x0008, 0, 0, 0, 0)
    time.sleep(0.1)
    user32.mouse_event(0x0010, 0, 0, 0, 0)
    time.sleep(0.5)
    root.update()


captured = []
_orig_popup = tk.Menu.tk_popup


def _labels(menu):
    out = []
    try:
        n = menu.index("end")
    except Exception:
        return out
    if n is None:
        return out
    for i in range(n + 1):
        try:
            kind = menu.type(i)
        except Exception:
            kind = None
        if kind == "separator":
            continue
        try:
            out.append(str(menu.entrycget(i, "label")))
        except Exception:
            out.append("<%s>" % kind)
    return out


tk.Menu.tk_popup = lambda self, x, y, entry="": captured.append(_labels(self))

kids = list(app.tree.get_children())
print("行数:", len(kids))

# ---- A. 普通起点框选：行1「品牌」→ 行4「型号」 ----
p0 = cell_xy(kids[0], "brand")
p1 = cell_xy(kids[3], "model")
real_drag(p0, p1)
check("A 框选形成区块", bool(app._drag_block) and len(app._drag_block["rows"]) == 4,
      str(app._drag_block))
captured.clear()
real_rclick(cell_xy(kids[1], "model"))
labels = captured[0] if captured else []
cascade = [l for l in labels if l.startswith("区域上色")]
print("  A 菜单:", cascade, "| 区块:", app._drag_block)
check("A 右键后区块仍在", bool(app._drag_block), str(app._drag_block))
check("A 菜单显示整块（4 行 × 3 列）",
      bool(cascade) and "4 行 × 3 列" in cascade[0], str(cascade))
check("A 上色目标=12 格", len(app._paint_targets()) == 12,
      str(len(app._paint_targets())))
app.paint_cells("#FFE3E3")
root.update()
n_rows = len(app.cell_colors)
n_cells = sum(len(v) for v in app.cell_colors.values())
check("A 实际上色 4 行 × 3 列", n_rows == 4 and n_cells == 12,
      "行=%d 格=%d" % (n_rows, n_cells))
screenshot.capture_window("仓库管理", os.path.join(OUT, "paint_block_A.png"))

# ---- B. 从已上色格子起拖（贴片起点）→ 右键区块内 ----
app.clear_cell_colors(all_rows=True)
app._drag_block = None
app._block_preview = None
app.tree.selection_set(kids[0])
app.paint_cells("#D6E4FF")            # 第 1 行整行上色（贴片覆盖）
root.update()
check("B 已生成贴片", len(app._paint_labels) == len(app._cols()),
      "贴片=%d 列=%d" % (len(app._paint_labels), len(app._cols())))
p0 = cell_xy(kids[0], "brand")        # 起点落在贴片上
p1 = cell_xy(kids[3], "model")
real_drag(p0, p1)
check("B 贴片起点也能框选", bool(app._drag_block)
      and len(app._drag_block["rows"]) == 4, str(app._drag_block))
captured.clear()
real_rclick(cell_xy(kids[2], "model"))     # 区块内、且是已上色行
labels = captured[0] if captured else []
cascade = [l for l in labels if l.startswith("区域上色")]
check("B 右键后区块仍在", bool(app._drag_block), str(app._drag_block))
check("B 菜单显示整块", bool(cascade) and "4 行 × 3 列" in cascade[0], str(cascade))
check("B 上色目标=12 格", len(app._paint_targets()) == 12,
      str(len(app._paint_targets())))
app.paint_cells("#E2F7E2")
root.update()
n_rows = len(app.cell_colors)
blk_rows = [str(r) for r in (app._drag_block or {}).get("rows", [])]
# 第 1 行原本就整行上过色（保留），其余 3 行应各上 3 格 = 新色 9 格
new_cells = sum(1 for r in blk_rows[1:] for c in app.cell_colors.get(r, {}).values()
                if c == "#E2F7E2")
check("B 区块内 3 行 × 3 列上新色", n_rows == 4 and new_cells == 9
      and len(app.cell_colors.get(str(kids[0]), {})) == len(app._cols()),
      "行=%d 新色格=%d 首行格=%d" % (n_rows, new_cells,
                                 len(app.cell_colors.get(str(kids[0]), {}))))
screenshot.capture_window("仓库管理", os.path.join(OUT, "paint_block_B.png"))

# ---- C. 右键落在区块外 → 回落到单行（不该误上整块） ----
p0 = cell_xy(kids[0], "brand")
p1 = cell_xy(kids[2], "brand")
real_drag(p0, p1)
check("C 框选形成区块（3 行 × 1 列）",
      bool(app._drag_block) and len(app._drag_block["rows"]) == 3,
      str(app._drag_block))
captured.clear()
real_rclick(cell_xy(kids[5], "price"))     # 区块外的另一行
labels = captured[0] if captured else []
cascade = [l for l in labels if l.startswith("区域上色")]
print("  C 菜单:", cascade)
check("C 区块外右键回落为选中行", bool(cascade) and "框选区块" not in cascade[0],
      str(cascade))
check("C 上色目标=1 行整行", len(app._paint_targets()) == len(app._cols()),
      str(len(app._paint_targets())))

tk.Menu.tk_popup = _orig_popup
print("\nFAILS:", FAILS)
root.attributes("-topmost", False)
root.destroy()
sys.exit(1 if FAILS else 0)
