# -*- coding: utf-8 -*-
"""探针：入库弹窗（照片区 / 货架等字段）截图与可视性检查。"""
import base64
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

tmp = tempfile.mkdtemp(prefix="wf_in_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()
wfmod.messagebox.showinfo = lambda *a, **k: None

import ctypes  # noqa: E402
ctypes.windll.user32.SetCursorPos(2, 2)

root = tk.Tk()
app = wapp.App(root)
tab = wfmod.WorkflowTab(root, app)
tab.pack(fill="both", expand=True)
root.update_idletasks()
root.update()

stages = app.store.wf_stages()
wf_id, no = app.store.wf_create("保德型号更换", kind="更换型号标签", by="张三",
                                extra={"原型号": "WL-00012", "更换后型号": "S10MD"})
for i in range(len(stages) - 2):
    app.store.wf_advance(wf_id, "工位%d" % i, "")
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAAYAAf8B9W8lAAAAAElFTkSuQmCC")
png2 = png[:-1] + bytes([png[-1] ^ 0xFF])   # 改一字节避开内容去重
app.store.photo_add("wf", no, base64.b64encode(png).decode("ascii"), "入库1.png")
app.store.photo_add("wf", no, base64.b64encode(png2).decode("ascii"), "入库2.png")

rec = [r for r in app.store.wf_list("active", "") if int(r["id"]) == wf_id][0]
dlg = wfmod.FlowDialog(tab, tab, rec, True)
dlg.attributes("-topmost", True)

fails = []
checks = []


def chk(name, cond, got=""):
    checks.append((name, bool(cond), got))


def step2():
    root.update_idletasks()
    root.update()
    h = dlg.winfo_height()
    w = dlg.winfo_width()
    chk("弹窗宽度合理", 470 <= w <= 820, w)
    chk("弹窗高度不超屏", h < dlg.winfo_screenheight() - 40, h)
    # 底部按钮可见
    btns = []

    def walk(x):
        for c in x.winfo_children():
            if c.winfo_class() in ("TButton", "Button"):
                btns.append(c)
            walk(c)
    walk(dlg)
    texts = {str(b.cget("text")): b for b in btns}
    chk("有确定/取消按钮", "确定" in texts and "取消" in texts, list(texts))
    okb = texts.get("确定")
    chk("确定按钮在窗口内",
        okb is not None and okb.winfo_y() + okb.winfo_height() <= h,
        (okb.winfo_y() if okb else None, h))
    # 照片区在窗口内
    ps = dlg.photo_strip
    chk("照片区可见", ps.winfo_ismapped() and ps.winfo_height() > 40,
        ps.winfo_height())
    chk("照片区显示 2 张", ps.lbl_cap.cget("text").startswith("照片 2/"),
        ps.lbl_cap.cget("text"))
    # 货架字段可见
    ents = [w for w in dlg._stock_widgets]
    chk("入库字段 7 个", len(ents) == 7, len(ents))
    chk("货架输入框在窗口内",
        all(e.winfo_ismapped() and e.winfo_rooty() - dlg.winfo_rooty()
            + e.winfo_height() <= h for e in ents),
        [(e.winfo_rooty() - dlg.winfo_rooty(), e.winfo_height()) for e in ents])
    screenshot.capture_window("推进", os.path.join(OUT, "_wf_inbound.png"))
    dlg.destroy()
    root.after(200, done)


def done():
    okn = 0
    for name, cond, got in checks:
        print(("[PASS] " if cond else "[FAIL] ") + name
              + ("" if cond else "  -> %s" % (got,)))
        if not cond:
            fails.append(name)
        else:
            okn += 1
    print("\n%d/%d passed -> %s" % (okn, len(checks),
                                    "ALL PASSED" if not fails else fails))
    root.destroy()


root.after(600, step2)
root.mainloop()
