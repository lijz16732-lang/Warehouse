# -*- coding: utf-8 -*-
"""截图：工位设置弹窗 + 推进弹窗的「交给谁」下拉（v1.43.0）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk                           # noqa: E402
import screenshot                              # noqa: E402
from wm import app as wapp                     # noqa: E402
from wm import workflow as wfmod               # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="wf_shot_st_")
wapp.resolve_data_dir = lambda: TMP

import ctypes                                  # noqa: E402
ctypes.windll.user32.SetCursorPos(2, 2)


def tk_hwnd(w):
    """Tk 控件的真实窗口句柄（toplevel 需取父 HWND）。"""
    u = ctypes.windll.user32
    return u.GetParent(w.winfo_id()) or w.winfo_id()


def shot(w, path):
    try:
        w.attributes("-alpha", 1.0)     # 弹窗默认 alpha=0 防闪，先显形再抓
    except Exception:
        pass
    w.lift()
    w.attributes("-topmost", True)
    w.update_idletasks()
    w.update()
    screenshot.capture_window(w.title(), path)

wfmod.messagebox.showinfo = lambda *a, **k: None

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
root.deiconify()
root.geometry("1x1-3000-3000")
store = app.store

# 一个节点两个人：制作标签 / 制作标签B
store.wf_set_stations([{"name": "制作标签", "stage": 1},
                       {"name": "制作标签B", "stage": 1},
                       {"name": "贴标签A", "stage": 2},
                       {"name": "贴标签B", "stage": 2}])
w1, _ = store.wf_create("撤柜重做标签", kind="制作标签", by="张三",
                        target="WL-02054", note="客户催",
                        extra={"标签种类": "外箱标、机身标"})
store.wf_advance(w1, "张三", "标签已印", station="制作标签")

top = tk.Toplevel(root)
top.title("探针-工位设置")
top.geometry("620x400+60+60")
tab = wfmod.WorkflowTab(top, app)
tab.pack(fill="both", expand=True)
top.update()
tab.refresh_tab()
top.update()

# 1) 工位设置
dlg = wfmod.StationsDialog(top, tab)
dlg.title("探针-工位设置")
root.update()
root.update_idletasks()
dlg.update_idletasks()
shot(dlg, os.path.join(OUT, "_wf_stations.png"))
dlg.destroy()

# 2) 推进弹窗：交给谁
rec = [r for r in store.wf_list("active") if int(r["id"]) == w1][0]
fd = wfmod.FlowDialog(top, tab, rec, True)
fd.title("探针-推进交给谁")
fd.var_by.set("李四")
fd.var_station.set("贴标签B")
root.update()
root.update_idletasks()
fd.update_idletasks()
shot(fd, os.path.join(OUT, "_wf_flow_station.png"))
fd.destroy()

root.destroy()
app.store.close()
import shutil                                  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("截图已存：", OUT)
