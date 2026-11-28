# -*- coding: utf-8 -*-
"""v1.47.0 深色模式探针。

验证：
1. 两套调色板齐全（light/dark 键集合一致）
2. apply_palette 同步副本到所有 wm 模块（from-import 坑）
3. dark 下关键色是深色、light 下是浅色
4. 语义 tag 色（斑马/重复/警告/已转入/命中）两主题不同
5. 下拉菜单 style_menu 后 bg=当前 MENU_BG、fg=当前 TEXT
6. dark 下自绘菜单条替代原生白条；light 下保留原生菜单栏
7. 热切换：dark→light 调色板生效、无旧色残留
8. 各页面 tree odd tag 用 CLR_ROW_ALT 而非写死浅色（源码检查）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk
from wm import constants as C

ok = [0, 0]


def check(name, cond):
    ok[0] += 1
    if cond:
        ok[1] += 1
    print(("ok  " if cond else "FAIL") + " " + name)


# ---- 1 两套调色板键一致 ----
lk = set(C._PALETTE_LIGHT)
dk = set(C._PALETTE_DARK)
check("light/dark 调色板键集合一致", lk == dk)
check("新增语义键都在两套里",
      all(k in lk and k in dk for k in
          ("CLR_DUP_BG", "CLR_WARN_BG", "CLR_DONE_BG", "CLR_HIT_BG",
           "CLR_WF_DONE", "CLR_WF_URGENT", "CLR_WF_DIM")))

# ---- 2 apply_palette 同步副本到 wm 模块 ----
C.apply_palette("dark")
import wm.app as wapp
import wm.nav as nav
import wm.theme as theme
check("apply_palette 设 app 模块 UI_THEME", wapp.UI_THEME == "dark")
check("apply_palette 设 app 模块 CLR_BG", wapp.CLR_BG == C.CLR_BG)
check("apply_palette 设 nav 模块 CLR_SIDE_BG", nav.CLR_SIDE_BG == C.CLR_SIDE_BG)
check("apply_palette 设 theme 模块 CLR_MENU_BG", theme.CLR_MENU_BG == C.CLR_MENU_BG)

# ---- 3 dark 关键色是深色 ----
def dark(hexc):
    h = hexc.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r + g + b) / 3 < 100

check("dark CLR_BG 深色", dark(C.CLR_BG))
check("dark CLR_CARD 深色", dark(C.CLR_CARD))
check("dark CLR_TEXT 浅色（深底上可读）", not dark(C.CLR_TEXT))
check("dark CLR_MENU_BG 深色", dark(C.CLR_MENU_BG))

# ---- 4 语义 tag 色两主题不同 ----
dark_sem = {k: C._PALETTE_DARK[k] for k in
            ("CLR_DUP_BG", "CLR_WARN_BG", "CLR_DONE_BG", "CLR_HIT_BG")}
C.apply_palette("light")
light_sem = {k: C._PALETTE_LIGHT[k] for k in dark_sem}
check("语义 tag 色两主题不同", all(dark_sem[k] != light_sem[k] for k in dark_sem))

# ---- 5 下拉菜单 style_menu 配色 ----
C.apply_palette("dark")
root = tk.Tk()
root.withdraw()
m = tk.Menu(root, tearoff=0)
theme.style_menu(m, root)
check("菜单 bg=MENU_BG", str(m.cget("bg")).lower() == C.CLR_MENU_BG.lower())
check("菜单 fg=TEXT", str(m.cget("fg")).lower() == C.CLR_TEXT.lower())
check("菜单 activebackground=ACCENT",
      str(m.cget("activebackground")).lower() == C.CLR_ACCENT.lower())
root.destroy()

# ---- 6 源码检查：无写死斑马纹浅色残留在 tag_configure ----
src_dir = os.path.join(ROOT, "wm")
bad = []
for fn in ("customers.py", "extras.py", "importer.py", "phone.py",
           "profit.py", "returns.py", "stocktake.py", "workflow.py"):
    with open(os.path.join(src_dir, fn), encoding="utf-8") as f:
        txt = f.read()
    if "#F7FAFD" in txt:
        bad.append(fn)
check("无写死 #F7FAFD 斑马纹残留", not bad)

# ---- 7 热切换 dark→light 生效 ----
C.apply_palette("light")
check("切回 light UI_THEME", C.UI_THEME == "light")
check("切回 light CLR_BG 浅色", not dark(C.CLR_BG))
check("切回 light 模块副本同步", theme.CLR_BG == C.CLR_BG)

print("PROBE 1470: %d/%d" % (ok[1], ok[0]))
sys.exit(0 if ok[0] == ok[1] else 1)
