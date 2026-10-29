# -*- coding: utf-8 -*-
"""临时脚本：深色/浅色主题 + 操作日志页截屏（主题在导入界面模块前应用）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

THEME = sys.argv[1] if len(sys.argv) > 1 else "dark"

from wm import constants as C  # noqa: E402
C.apply_palette(THEME)

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
import wm.app as wapp  # noqa: E402

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
root.deiconify()
root.update()
out = os.path.join(ROOT, ".tmpdbg", "theme_%s_main.png" % THEME)
screenshot.capture_window(APP := "仓管家", out)
print("saved", out)

# 切到操作日志页
app.nb.select(5)
root.update()
out2 = os.path.join(ROOT, ".tmpdbg", "theme_%s_log.png" % THEME)
screenshot.capture_window("仓管家", out2)
print("saved", out2)
app.on_close()
