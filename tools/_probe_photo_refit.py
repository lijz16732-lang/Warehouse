# -*- coding: utf-8 -*-
"""探针：入库弹窗添加照片后按钮不被裁掉、窗口自动长高（v1.42.8）。

复现用户反馈：添加图片后取消/确定按钮不见了。
模拟路径：先建窗 → store.photo_add → PhotoStrip.set_code 刷新（与
add_photos 之后的刷新路径一致）→ 断言窗口长高且确定/取消按钮完整可见。
用法：.venv310/Scripts/python.exe tools/_probe_photo_refit.py
"""
import base64
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm import workflow as wfmod  # noqa: E402
from wm.store import Store  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wf_refit_")
wapp.resolve_data_dir = lambda: TMP
import ctypes  # noqa: E402
ctypes.windll.user32.SetCursorPos(2, 2)

fails = []


def chk(name, cond, got=""):
    print(("[PASS] " if cond else "[FAIL] ") + name
          + ("" if cond else "  -> %s" % (got,)))
    if not cond:
        fails.append(name)


root = tk.Tk()
root.withdraw()
app = wapp.App(root)
store = app.store                 # 与 App 同一个库，避免双连接各看各的


class FakeTab:
    fam = "Microsoft YaHei"

    def __init__(self, app):
        self.app = app
        self.remember_name = lambda by: None


tab = FakeTab(app)
root.deiconify()
root.geometry("1x1-3000-3000")     # 主窗挪到屏幕外，别挡弹窗

stages = store.wf_stages()
wf_id, no = store.wf_create("照片撑高探针", kind="修复", by="张三")
for i in range(len(stages) - 1):
    store.wf_advance(wf_id, "工位%d" % i, "")
rec = [r for r in store.wf_list("active", "") if int(r["id"]) == wf_id][0]

dlg = wfmod.FlowDialog(root, tab, rec, True)
root.update_idletasks()
root.update()

h0 = dlg.winfo_height()
btns = {}


def collect(w, out):
    for c in w.winfo_children():
        if c.winfo_class() in ("TButton", "Button"):
            out[str(c.cget("text"))] = c
        collect(c, out)


collect(dlg, btns)
okb = btns.get("确定")
cancelb = btns.get("取消")
chk("建窗时确定/取消都存在", okb is not None and cancelb is not None,
    list(btns))
okb_bottom0 = okb.winfo_rooty() - dlg.winfo_rooty() + okb.winfo_height()

# 模拟「添加照片」：store 落盘 + 缩略图条刷新（同 add_photos 的刷新路径）
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAA"
    "YAAf8B9W8lAAAAAElFTkSuQmCC")
png2 = png[:-1] + bytes([png[-1] ^ 0xFF])
store.photo_add("wf", no, base64.b64encode(png).decode("ascii"), "a.png")
store.photo_add("wf", no, base64.b64encode(png2).decode("ascii"), "b.png")
dlg.photo_strip.set_code(no)
root.update_idletasks()
root.update()

h1 = dlg.winfo_height()
chk("加照片后窗口自动长高", h1 > h0 + 20, (h0, h1))
okb_bottom = okb.winfo_rooty() - dlg.winfo_rooty() + okb.winfo_height()
chk("确定按钮仍在窗口内", okb_bottom <= h1, (okb_bottom, h1))
chk("取消按钮仍在窗口内",
    cancelb.winfo_rooty() - dlg.winfo_rooty() + cancelb.winfo_height() <= h1)
chk("按钮仍在底层之上（没被照片区顶出屏幕）",
    okb.winfo_rooty() < dlg.winfo_screenheight(), okb.winfo_rooty())
chk("照片区显示 2 张",
    dlg.photo_strip.lbl_cap.cget("text").startswith("照片 2/"),
    dlg.photo_strip.lbl_cap.cget("text"))

dlg.destroy()
root.destroy()
print("\n%s" % ("ALL PASSED" if not fails else "FAILED: %s" % fails))
sys.exit(0 if not fails else 1)
