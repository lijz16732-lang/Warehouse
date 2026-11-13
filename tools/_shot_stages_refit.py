# -*- coding: utf-8 -*-
"""探针：流程节点设置弹窗加/删节点后，保存按钮必须仍在窗口内可见。"""
import ctypes
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
from wm.store import Store  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
tmp = tempfile.mkdtemp(prefix="wm_stages_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()
ctypes.windll.user32.SetCursorPos(2, 2)

fail = []


def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))
    if not cond:
        fail.append(name)


root = tk.Tk()
app = wapp.App(root)
root.geometry("1200x760+40+30")

tab = wfmod.WorkflowTab(root, app)
tab.pack(fill="both", expand=True)
root.update_idletasks()
root.update()

# ---- 打开节点设置弹窗 ----
dlg_holder = []
orig = wfmod.StagesDialog


class SpyDialog(orig):
    def __init__(self, master, tab):
        super().__init__(master, tab)
        dlg_holder.append(self)


wfmod.StagesDialog = SpyDialog
tab.edit_stages()
root.update()
dlg = dlg_holder[0]
chk("弹窗已打开", dlg is not None and dlg.winfo_exists())


def foot_visible(d):
    out = {}

    def walk(w):
        for c in w.winfo_children():
            if c.winfo_class() in ("TButton", "Button"):
                out[str(c.cget("text"))] = c
            walk(c)
    walk(d)
    wh = d.winfo_height()
    vis = {}
    for t, b in out.items():
        y = b.winfo_rooty() - d.winfo_rooty()
        vis[t] = (0 <= y < wh and b.winfo_ismapped())
    return vis


v = foot_visible(dlg)
chk("初始状态保存/取消可见", v.get("保存") and v.get("取消"), v)

# ---- 连加 3 个节点 ----
add_btns = []


def find_add(d):
    res = []

    def walk(w):
        for c in w.winfo_children():
            if c.winfo_class() in ("TButton", "Button") and "添加节点" in str(c.cget("text")):
                res.append(c)
            walk(c)
    walk(d)
    return res


add_btns = find_add(dlg)
chk("找到添加节点按钮", bool(add_btns))
for _ in range(3):
    add_btns[0].invoke()
    dlg.update_idletasks()
    dlg.update()
v = foot_visible(dlg)
chk("加 3 个节点后保存仍可见", v.get("保存"), v)
chk("加 3 个节点后取消仍可见", v.get("取消"), v)
chk("行数=8", len(dlg._entries) == 8, len(dlg._entries))

# 保存按钮的底边不超过窗口底边
save_btn = None


def find_save(d):
    global save_btn
    res = []

    def walk(w):
        for c in w.winfo_children():
            if c.winfo_class() in ("TButton", "Button") and str(c.cget("text")) == "保存":
                res.append(c)
            walk(c)
    walk(d)
    return res


save_btn = find_save(dlg)[0]
bottom = save_btn.winfo_rooty() + save_btn.winfo_height() - dlg.winfo_rooty()
chk("保存按钮完整在窗口内", bottom <= dlg.winfo_height() + 1,
    "bottom=%d h=%d" % (bottom, dlg.winfo_height()))

screenshot.capture_window = screenshot.capture_window  # noqa: 保留引用

# ---- 删 2 个节点 ----
def first_del(d):
    for r, _e in reversed(list(d._entries)):
        for c in r.winfo_children():
            if c.winfo_class() in ("TButton", "Button"):
                return c
    return None


first_del(dlg).invoke()
first_del(dlg).invoke()
dlg.update_idletasks()
dlg.update()
v = foot_visible(dlg)
chk("删节点后保存仍可见", v.get("保存"), v)

dlg.destroy()
root.destroy()
print("RESULT:", "FAIL:%d" % len(fail) if fail else "ALL PASS")
sys.exit(1 if fail else 0)
