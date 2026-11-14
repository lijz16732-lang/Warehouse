# -*- coding: utf-8 -*-
"""加急功能探针：列表加急列/红色tag/按钮文字切换/排序。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wm import app as wapp                     # noqa: E402
from wm import workflow as wfmod               # noqa: E402

TMP = tempfile.mkdtemp(prefix="wf_urgent_")
wapp.resolve_data_dir = lambda: TMP

fails = []


def chk(name, cond, got=""):
    print(("[PASS] " if cond else "[FAIL] ") + name
          + ("" if cond else "  -> %s" % (got,)))
    if not cond:
        fails.append(name)


root = wapp.tk.Tk() if hasattr(wapp, "tk") else None
import tkinter as tk                           # noqa: E402
root = tk.Tk()
root.withdraw()
app = wapp.App(root)
root.deiconify()
root.geometry("1x1-3000-3000")

store = app.store
stages = store.wf_stages()
w1, _ = store.wf_create("普通单", by="张三")
w2, _ = store.wf_create("加急单", by="张三")
store.wf_set_urgent(w2, 1, "张三")

tab = wfmod.WorkflowTab(root, app)
root.update()
tab.refresh_rows()
root.update()

ids = [int(iid) for iid in tab.tree.get_children()]
chk("加急单排在最前", ids and ids[0] == w2, ids)
vals = tab.tree.item(str(w2), "values")
chk("加急列显示 🔥", vals[1] == "🔥", vals)
chk("加急行红色 tag", "urgent" in tab.tree.item(str(w2), "tags"),
    tab.tree.item(str(w2), "tags"))

# 选中加急单 → 按钮变「取消加急」；点一次取消
tab.tree.selection_set(str(w2))
tab.tree.focus(str(w2))
tab.refresh_rows()
chk("选中加急单按钮显示取消加急", tab.btn_urgent.cget("text") == "取消加急",
    tab.btn_urgent.cget("text"))
app.settings["wf_name"] = "张三"
tab.toggle_urgent()
root.update()
rec = [r for r in store.wf_list("active") if int(r["id"]) == w2][0]
chk("点按钮取消加急", int(rec["urgent"]) == 0, rec)
chk("取消后按钮复原为加急", tab.btn_urgent.cget("text") == "加急",
    tab.btn_urgent.cget("text"))

root.destroy()
app.store.close()
import shutil                                  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("RESULT:", "ALL OK" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
