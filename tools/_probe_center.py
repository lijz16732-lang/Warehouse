# -*- coding: utf-8 -*-
"""验证 center_window 防闪左上角：真实 Tk 窗口。

断言：
1. 新建未映射弹窗 → center_window 期间不被映射（修复前 update_idletasks
   会把它按默认位置映射出来=闪左上角）→ 事件循环后出现在居中位置；
2. 已映射窗口重新居中 → 不做隐藏，平滑挪位；
3. 调用方自己 withdraw 过的窗口（photos 管理窗模式）→ 居中后正常显示。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import tkinter as tk

from wm import constants  # noqa: F401
from wm.constants import center_window


def main():
    root = tk.Tk()
    root.geometry("900x700+50+50")
    root.update_idletasks()

    # ---- 用例 1：新弹窗（最常见：__init__ 里居中）----
    d1 = tk.Toplevel(root)
    tk.Label(d1, text="hello", width=40, height=10).pack()
    assert d1.winfo_ismapped() == 0, "前置：新窗口应未映射"
    # 记录「映射那一刻」的坐标：闪左上角 = 以默认位置(~0,0)被映射
    map_pos = {}
    d1.bind("<Map>", lambda e: map_pos.update(
        x=d1.winfo_x(), y=d1.winfo_y()))
    center_window(d1, root)
    root.update()
    assert d1.winfo_ismapped() == 1, "事件循环后弹窗应已显示"
    assert map_pos, "<Map> 事件未触发"
    bx, by = root.winfo_rootx(), root.winfo_rooty()
    x, y = d1.winfo_x(), d1.winfo_y()
    assert x > bx + 50 and y > 50, "弹窗应出现在居中位置而不是左上角: %d,%d" % (x, y)
    assert map_pos["x"] > bx + 50, \
        "映射时刻坐标 %s 说明弹窗先在左上角被映射（闪框）" % map_pos
    print("case1 ok: mapped_at=%s final=(%d,%d)" % (map_pos, x, y))

    # ---- 用例 2：已映射窗口重新居中（不应消失再出现）----
    old_x = d1.winfo_x()
    root.geometry("900x700+400+300")
    root.update()
    center_window(d1, root)
    assert d1.winfo_ismapped() == 1, "已映射窗口重新居中不应被隐藏"
    root.update()
    print("case2 ok: recentered (%d,%d) -> (%d,%d)"
          % (old_x, d1.winfo_y(), d1.winfo_x(), d1.winfo_y()))

    # ---- 用例 3：调用方自己 withdraw 的模式（photos 管理窗/pv）----
    d2 = tk.Toplevel(root)
    tk.Label(d2, text="world", width=30, height=8).pack()
    d2.withdraw()
    center_window(d2, root)
    d2.deiconify()
    root.update()
    assert d2.winfo_ismapped() == 1, "调用方 withdraw 的窗口居中后应正常显示"
    assert d2.winfo_x() > 50, "应摆到居中位置: %d" % d2.winfo_x()
    print("case3 ok: (%d,%d)" % (d2.winfo_x(), d2.winfo_y()))

    root.destroy()
    print("PROBE OK")


if __name__ == "__main__":
    main()
