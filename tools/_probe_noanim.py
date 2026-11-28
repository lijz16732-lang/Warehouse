# -*- coding: utf-8 -*-
"""v1.47.2 窗口动画禁用探针。

用户反馈「最大化/最小化卡一下」= Windows 窗口动画期间旧尺寸位图缩放叠加，
Tk 覆盖层（网格线/徽章/复选框）坐标对不上，画面出现两个尺寸窗口重影。
修复：主窗口创建后调 screen.disable_window_animation()，用
DWMWA_TRANSITIONS_FORCEDISABLED 只禁本窗口动画。

验证：
1. disable_window_animation 在真窗口上返回 True；
2. 用的是 GA_ROOT 顶层句柄（不是 winfo_id 子句柄，DWM 会拒绝子句柄）；
3. main.py / app.py 主窗口创建路径都调用了它；
4. 非 Windows / 异常时静默降级返回 False 不抛。
"""
import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk
from wm.screen import disable_window_animation

ok = [0, 0]


def check(label, cond):
    ok[0] += 1
    ok[1] += bool(cond)
    print("  %-46s %s" % (label, "OK" if cond else "FAIL"))


# ---- 1/2 真窗口上生效 + 句柄正确 ----
root = tk.Tk()
root.geometry("900x600+100+100")
root.update()
u = ctypes.windll.user32
wid = root.winfo_id()
top = u.GetAncestor(wid, 2)
check("winfo_id 是子句柄（与 GA_ROOT 不同）", wid != top)
check("disable_window_animation 返回 True", disable_window_animation(root) is True)
# 在 GA_ROOT 上设值应成功（hr=0）
val = ctypes.c_int(1)
hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
    top, 3, ctypes.byref(val), ctypes.sizeof(val))
check("DwmSetWindowAttribute 在顶层句柄成功(hr=0)", (hr & 0xffffffff) == 0)
root.destroy()

# ---- 3 主入口都接入了动画禁用 ----
main_src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
app_src = open(os.path.join(ROOT, "wm", "app.py"), encoding="utf-8").read()
check("main.py 调用 disable_window_animation",
      "disable_window_animation" in main_src)
check("app.py main() 调用 disable_window_animation",
      "disable_window_animation" in app_src)

# ---- 4 异常降级 ----
try:
    class FakeRoot(object):
        def frame(self):
            raise RuntimeError("no frame")
        def winfo_id(self):
            raise RuntimeError("no id")
    check("异常时静默返回 False", disable_window_animation(FakeRoot()) is False)
except Exception:
    check("异常时静默返回 False", False)

print("PROBE NOANIM: %d/%d" % (ok[1], ok[0]))
