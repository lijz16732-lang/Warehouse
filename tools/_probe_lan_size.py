# -*- coding: utf-8 -*-
"""探针：打印局域网共享窗口的实际尺寸与内容需求高度，验证一屏能否放下。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.lanui import LanDialog  # noqa: E402
from wm.store import Store  # noqa: E402
from wm import screen  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_probe_lan_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
root = tk.Tk()
app = wapp.App(root)
app.load_data()
root.update()
app._add_lan_history("192.168.1.10", 8765, "246810")

dlg = LanDialog(root, app)
root.update()
root.update_idletasks()
m = app.screen_metrics
print("work_area =", (m["w"], m["h"]), "dpi_scale =", m["scale"])
print("body.req =", dlg.body.winfo_reqheight(),
      "head.req =", dlg._head.winfo_reqheight(),
      "foot.req =", dlg._foot.winfo_reqheight())
print("dialog geometry =", dlg.geometry())
print("canvas height =", dlg.canvas.winfo_height(),
      "scrollbar mapped =", dlg.vsb.winfo_ismapped())
dlg.destroy()
root.destroy()
