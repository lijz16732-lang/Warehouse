# -*- coding: utf-8 -*-
"""截图：工位固定但能看全程（别站的行灰显、推进按钮禁用）。"""
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
TMP = tempfile.mkdtemp(prefix="wf_shot_ro_")
wapp.resolve_data_dir = lambda: TMP

import ctypes                                  # noqa: E402
ctypes.windll.user32.SetCursorPos(2, 2)

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
store = app.store
store.wf_set_stations([{"name": "制作标签", "stage": 1},
                       {"name": "制作标签B", "stage": 1},
                       {"name": "贴标签A", "stage": 2},
                       {"name": "贴标签B", "stage": 2}])
# 本机 = 制作标签（第 2 站）
app.settings["wf_my_station"] = "制作标签"
app.settings["wf_my_stage"] = 1
app.settings["wf_stage_locked"] = True

w1, _ = store.wf_create("撤柜重做标签", kind="制作标签", by="张三",
                        target="WL-02054", note="客户催")
store.wf_advance(w1, "张三", "标签已印", station="制作标签A"
                 if store.wf_station_stage("制作标签A") >= 0 else "制作标签")
w2, _ = store.wf_create("返修外壳", kind="返工", by="李四")
store.wf_advance(w2, "李四", "已印好")            # 公共池，本机可接
w3, _ = store.wf_create("新机贴标", kind="制作标签", by="王五")
store.wf_advance(w3, "王五", "标签已印")
store.wf_advance(w3, "李四", "贴好了")            # 停在第 3 站（别站）
w4, _ = store.wf_create("补打外箱标", kind="制作标签", by="赵六")
for _ in range(3):
    store.wf_advance(w4, "赵六", "")              # 停在最后一站（别站）
store.wf_set_urgent(w4, 1, "赵六")

top = tk.Toplevel(root)
top.title("探针-工位只读")
tab = wfmod.WorkflowTab(top, app)
tab.pack(fill="both", expand=True)
top.geometry("1240x640+60+60")
top.update()
tab.refresh_tab()
tab.var_only_mine.set(False)
tab.refresh_rows()
root.update()
root.update_idletasks()

# 选中一个别站的单：推进/退回应灰掉
tab.tree.selection_set(str(w3))
tab.tree.focus(str(w3))
tab._sync_action_btns()
root.update()
root.update_idletasks()

try:
    top.attributes("-alpha", 1.0)
except Exception:
    pass
top.lift()
top.attributes("-topmost", True)
top.update()
screenshot.capture_window("探针-工位只读",
                          os.path.join(OUT, "_wf_readonly.png"))
print("截图已存：", OUT)
root.destroy()
app.store.close()
import shutil                                  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
