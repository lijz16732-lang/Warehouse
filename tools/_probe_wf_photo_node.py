# -*- coding: utf-8 -*-
"""探针：制作单照片按节点归属（v1.43.2）。

- 编号#s节点 文件夹方案 + 旧版整单文件夹自动迁移
- DetailDialog 节点下拉切换照片条
- 入库站照片只属于最后一站、结单/删除级联清理
"""
import base64
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk

from wm import app as wapp
from wm import workflow as wfmod
from wm.store import Store, wf_photo_code

TMP = tempfile.mkdtemp(prefix="wf_ph_node_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
wfmod.messagebox.showinfo = lambda *a, **k: None
wfmod.messagebox.showwarning = lambda *a, **k: None

fails = []


def chk(name, cond, got=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + ("" if cond else "  -> %s" % (got,)))
    if not cond:
        fails.append(name)


png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAA"
    "YAAf8B9W8lAAAAAElFTkSuQmCC")
B64 = base64.b64encode(png).decode("ascii")

root = tk.Tk()
app = wapp.App(root)
tab = wfmod.WorkflowTab(root, app)
tab.pack(fill="both", expand=True)
root.update_idletasks()
root.update()
store = app.store
stages = store.wf_stages()

# ---- 1. 旧版整单文件夹自动迁移到第 1 个节点 ----
wid, no = store.wf_create("旧单迁移", by="张三")
legacy = store.photos_dir("wf", no)
os.makedirs(legacy, exist_ok=True)
with open(os.path.join(legacy, "aaa.jpg"), "wb") as f:
    f.write(png)
store.wf_photo_migrate(no)
chk("旧文件夹搬空并删除", not os.path.isdir(legacy), legacy)
chk("照片归入第 1 个节点",
    store.photos_list("wf", wf_photo_code(no, 0)) == ["aaa.jpg"],
    store.photos_list("wf", wf_photo_code(no, 0)))
store.wf_photo_migrate(no)          # 重复调用无害
chk("重复迁移无副作用",
    store.photos_list("wf", wf_photo_code(no, 0)) == ["aaa.jpg"])

# ---- 2. 各节点照片互相隔离 ----
store.photo_add("wf", wf_photo_code(no, 1), B64, "b.jpg")
store.photo_add("wf", wf_photo_code(no, 2), B64[:-4] + "AAAA", "c.jpg")
chk("节点 0/1/2 各自的照片",
    len(store.photos_list("wf", wf_photo_code(no, 0))) == 1
    and len(store.photos_list("wf", wf_photo_code(no, 1))) == 1
    and len(store.photos_list("wf", wf_photo_code(no, 2))) == 1)

# ---- 3. 列表 📷 标记：任一节点有照片就打标记 ----
tab.var_status.set("active")
tab.refresh_rows()
root.update()
chk("列表显示照片标记", tab.tree.set(str(wid), "photo") == "📷",
    tab.tree.set(str(wid), "photo"))

# ---- 4. 详情弹窗：节点下拉切换照片条 ----
rec = [r for r in store.wf_list("active", "") if int(r["id"]) == wid][0]
dlg = wfmod.DetailDialog(root, tab, rec)
root.update()
chk("节点下拉存在且默认当前节点",
    str(dlg.cb_ph_node.cget("values")) .find(stages[0]) >= 0
    and dlg.var_ph_node.get() == stages[0], dlg.var_ph_node.get())
chk("默认显示节点 0 的 1 张",
    dlg.photo_strip.lbl_cap.cget("text").startswith("照片 1/"),
    dlg.photo_strip.lbl_cap.cget("text"))
dlg.var_ph_node.set(stages[1])
dlg._set_ph_node()
root.update()
chk("切到节点 1 显示它自己的 1 张",
    dlg.photo_strip.lbl_cap.cget("text").startswith("照片 1/")
    and dlg.photo_strip.code == wf_photo_code(no, 1),
    (dlg.photo_strip.code, dlg.photo_strip.lbl_cap.cget("text")))
dlg.var_ph_node.set(stages[-1])
dlg._set_ph_node()
root.update()
chk("最后一站没照片显示 0",
    dlg.photo_strip.lbl_cap.cget("text").startswith("照片 0/"),
    dlg.photo_strip.lbl_cap.cget("text"))
dlg.destroy()

# ---- 5. 删除单据级联清所有节点 ----
store.wf_delete(wid)
chk("删除后各节点照片清空",
    all(store.photos_list("wf", wf_photo_code(no, i)) == []
        for i in range(len(stages))) and not os.path.isdir(
        store.photos_dir("wf", no)))

root.destroy()
print("\n%s" % ("ALL PASSED" if not fails else "FAILED: %s" % fails))
sys.exit(0 if not fails else 1)
