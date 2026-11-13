# -*- coding: utf-8 -*-
"""探针：局域网共享窗口的「制作工位」列 / 按钮 / 选择弹窗（v1.42.2）。"""
import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from tkinter import ttk  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.lanui import LanPanel  # noqa: E402
from wm.store import Store  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

tmp = tempfile.mkdtemp(prefix="wm_shot_stage_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()

ctypes.windll.user32.SetCursorPos(2, 2)

root = tk.Tk()
app = wapp.App(root)
ok, msg = app.start_lan_host(17664, "246810")
print("start host:", ok, msg)

srv = app.lan_server
srv.clients["10.0.0.8"] = {"name": "B-贴标电脑", "id": "pc-B", "allowed": False,
                           "last_seen": time.time(), "requests": 3}
srv.clients["10.0.0.9"] = {"name": "C-质检电脑", "id": "pc-C", "allowed": False,
                           "last_seen": time.time(), "requests": 2}

win = tk.Toplevel(root)
win.title("局域网共享")
win.configure(bg="#f5f6f8")
win.geometry("780x760+120+60")
panel = LanPanel(win, app, standalone=False)
panel.pack(fill="both", expand=True)
panel.refresh()

seq = []
fail = []


def chk(label, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + label
          + ("" if cond else "  %s" % (extra,)))
    if not cond:
        fail.append(label)


def shot(name):
    try:
        screenshot.capture(os.path.join(OUT, name))
    except Exception as e:
        print("  (截图失败：%s)" % e)


def step():
    if not seq:
        print("ALL OK" if not fail else "HAS FAIL: %s" % fail)
        root.destroy()
        return
    fn = seq.pop(0)
    try:
        fn()
    except Exception:
        import traceback
        traceback.print_exc()
        fail.append("exception")
    root.after(500, step)


def s_check_columns():
    cols = panel.tree["columns"]
    chk("客户端列表有制作工位列", "stage" in cols, cols)
    vals = panel.tree.item("10.0.0.8", "values")
    chk("默认工位显示「不限」", vals and vals[-1] == "不限", vals)


def s_open_dialog():
    panel.tree.selection_set("10.0.0.8")
    panel._sel_changed()
    chk("选中后可点制作工位", str(panel.btn_stage.cget("state")) == "normal")
    panel.set_stage()
    dlg = [w for w in panel.winfo_children() if isinstance(w, tk.Toplevel)]
    chk("工位弹窗已打开", bool(dlg), len(panel.winfo_children()))
    globals()["_dlg"] = dlg[0] if dlg else None
    seq.insert(0, s_shot_dialog)     # 先截图+选工位，再校验保存结果


def s_shot_dialog():
    d = globals().get("_dlg")
    if d is None:
        return
    shot("_lan_stage_dialog.png")
    boxes = [w for w in d.winfo_children() if isinstance(w, ttk.Combobox)]
    chk("弹窗里有工位下拉", bool(boxes))
    if boxes:
        stages = app.store.wf_stages()
        boxes[0].set(stages[1])          # 选「制作标签」
        chk("下拉包含全部节点", list(boxes[0].cget("values")) == ["不限"] + list(stages),
            boxes[0].cget("values"))
    def walk(w):
        out = [w]
        for c in w.winfo_children():
            out += walk(c)
        return out

    target = None
    for w in walk(d):
        try:
            if str(w.cget("text")) == "确定":
                target = w
        except Exception:
            pass
    chk("有确定按钮", target is not None)
    if target is not None:
        target.invoke()


def s_after_apply():
    stages = app.store.wf_stages()
    m = app.lan_cfg.get("stage_map") or {}
    chk("工位绑定已保存配置", m.get("pc-B") == 1, m)
    chk("服务端认得该工位", srv.stage_of("10.0.0.8") == 1,
        srv.stage_of("10.0.0.8"))
    vals = panel.tree.item("10.0.0.8", "values")
    chk("列表显示工位名", vals and vals[-1] == stages[1], vals)
    chk("另一台仍是不限", (panel.tree.item("10.0.0.9", "values") or [None])[-1] == "不限")
    shot("_lan_stage_list.png")
    app.stop_lan_host()


seq += [s_check_columns, s_open_dialog, s_after_apply]
root.after(700, step)
root.mainloop()
print("结果：%d 失败" % len(fail))
sys.exit(0 if not fail else 1)
