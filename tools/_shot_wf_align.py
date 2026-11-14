# -*- coding: utf-8 -*-
"""探针：制作流程列表对齐（表头锚点跟随列锚点）截图与断言。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm import workflow as wfmod  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

tmp = tempfile.mkdtemp(prefix="wf_align_")
wapp.resolve_data_dir = lambda: tmp

import ctypes  # noqa: E402
ctypes.windll.user32.SetCursorPos(2, 2)

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
top = tk.Toplevel(root)
top.title("探针-对齐")
tab = wfmod.WorkflowTab(top, app)
tab.pack(fill="both", expand=True)
top.geometry("1150x320+40+40")
top.update()

stages = app.store.wf_stages()
w1, _ = app.store.wf_create("撤柜重做标签", kind="制作标签", by="张三",
                            note="加急",
                            extra={"标签种类": "外箱标、机身标、配件标"})
app.store.wf_advance(w1, "李四", "")
app.store.wf_set_urgent(w1, 1, "张三")
w2, _ = app.store.wf_create("普通返修", kind="返工", by="王五")
app.store.wf_advance(w2, "钱七", "外观没问题")
tab.refresh_rows()
root.update()
root.update_idletasks()

fails = []


def chk(name, cond, got=""):
    print(("[PASS] " if cond else "[FAIL] ") + name
          + ("" if cond else "  -> %s" % (got,)))
    if not cond:
        fails.append(name)


# 表头锚点 == 列锚点
for key, title, w, anchor in wfmod.COLS:
    hk = tab.tree.heading(key)
    chk("表头 %s 锚点=%s" % (title, anchor), hk.get("anchor") == anchor,
        hk)

# 事项/备注（左对齐宽列）表头必须靠左
for key in ("title", "note", "extra"):
    a = tab.tree.heading(key).get("anchor")
    chk("%s 表头靠左" % key, a in ("w", "sw"), a)

root.title("探针-对齐")
screenshot.capture_window("探针-对齐", os.path.join(OUT, "_wf_align.png"))

root.destroy()
app.store.close()
import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
print("RESULT:", "ALL OK" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
