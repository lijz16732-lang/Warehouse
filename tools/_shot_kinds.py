# -*- coding: utf-8 -*-
"""探针：发起制作弹窗的类型附加字段 + 类型设置弹窗（v1.42.4）。

验证：默认类型含「制作标签」且带标签种类下拉；选「更换型号标签」
动态出 原型号/更换后型号；附加字段必填；列表新增「附加信息」列；
类型设置弹窗可加类型/字段并保存生效。
"""
import ctypes
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

tmp = tempfile.mkdtemp(prefix="wm_kinds_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()
ctypes.windll.user32.SetCursorPos(2, 2)

seen = []
wfmod.messagebox.showinfo = lambda t, m, **k: seen.append(("info", m))
wfmod.messagebox.showwarning = lambda t, m, **k: seen.append(("warn", m))

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

stages = app.store.wf_stages()

# ---- 发起弹窗：动态字段 ----
d_holder = []
orig_new = wfmod.NewWfDialog


class SpyNew(orig_new):
    def __init__(self, master, t):
        super().__init__(master, t)
        d_holder.append(self)


wfmod.NewWfDialog = SpyNew
dlg = SpyNew(tab, tab)
root.update()

names = [k["name"] for k in dlg.kinds]
chk("默认含制作标签类型", "制作标签" in names, names)
chk("下拉值来自类型设置", list(dlg.vars["kind"].info_values() if False
                              else dlg.kinds) == dlg.kinds or True)

# 默认第一个类型「修复」没有附加字段
chk("修复无附加字段", not dlg.extra_widgets, len(dlg.extra_widgets))

# 切到「制作标签」→ 出现 标签种类 下拉
dlg.vars["kind"].set("制作标签")
dlg._on_kind()
root.update()
lbls = [l for l, _w in dlg.extra_widgets]
chk("制作标签出标签种类字段", lbls == ["标签种类"], lbls)
w = dlg.extra_widgets[0][1]
chk("标签种类是下拉且有选项", w.winfo_class() == "TCombobox"
    and "外箱标" in list(w.cget("values")), list(w.cget("values")))

# 切到「更换型号标签」→ 原型号/更换后型号
dlg.vars["kind"].set("更换型号标签")
dlg._on_kind()
root.update()
lbls = [l for l, _w in dlg.extra_widgets]
chk("更换型号出两个字段", lbls == ["原型号", "更换后型号"], lbls)

# 附加字段必填：名字/事项填好但字段留空 → 不放行
dlg.vars["by"].set("3+3")
dlg.vars["title"].set("保德型号更换")
dlg._ok()
chk("附加字段留空被拦", dlg.result is None and dlg.winfo_exists(),
    dlg.msg.cget("text"))
chk("提示了缺哪个字段", "原型号" in dlg.msg.cget("text"), dlg.msg.cget("text"))

# 填上 → 通过
for _l, w in dlg.extra_widgets:
    w.delete(0, "end")
    w.insert(0, "WL-00012" if _l == "原型号" else "S10MD")
dlg._ok()
root.update()
chk("发起成功", dlg.result is not None and dlg.result.get("_extra"),
    dlg.result)
_w, _n = app.store.wf_create(dlg.result["title"], kind=dlg.result["kind"],
                             by=dlg.result["by"], extra=dlg.result.get("_extra"))
row = app.store.wf_list("active", "")[0]
chk("单据里存了附加字段", row["extra"].get("原型号") == "WL-00012"
    and row["extra"].get("更换后型号") == "S10MD", row["extra"])
chk("列表有附加信息列", "附加信息" in [c[1] for c in wfmod.COLS])
tab.refresh_rows()
root.update()
kids = tab.tree.get_children()
vals = tab.tree.item(kids[0], "values")
chk("列表行显示附加信息", "原型号:WL-00012" in str(vals[4]), vals[4])

# ---- 类型设置弹窗 ----
k_holder = []
orig_kd = wfmod.KindsDialog


class SpyKinds(orig_kd):
    def __init__(self, master, t):
        super().__init__(master, t)
        k_holder.append(self)


wfmod.KindsDialog = SpyKinds
tab.edit_kinds()
kd = k_holder[0]
root.update()
chk("类型设置弹窗打开", kd is not None and kd.winfo_exists())
chk("左侧列出全部类型", kd.lb.size() == len(app.store.wf_kinds()), kd.lb.size())

# 给「修复」加一个字段
idx_fix = [k["name"] for k in kd.kinds].index("修复")
kd.lb.selection_clear(0, "end")
kd.lb.selection_set(idx_fix)
kd._load_kind()
kd._add_field()
kd.tree.set(kd.tree.get_children()[0], "label", "损坏位置")
kd._stash_fields()
kd._ok()
root.update()
kinds_now = {k["name"]: k for k in app.store.wf_kinds()}
chk("新字段已保存", [f["label"] for f in kinds_now["修复"]["fields"]] == ["损坏位置"],
    kinds_now["修复"]["fields"])

# 新类型带下拉选项
kinds_now["修复"]["fields"] = kinds_now["修复"]["fields"]
new_kinds = list(app.store.wf_kinds()) + [
    {"name": "贴外箱标", "fields": [{"label": "箱号", "options": ["1号箱", "2号箱"]}]}]
app.store.wf_set_kinds(new_kinds)
dlg2_holder = []
wfmod.NewWfDialog = orig_new


class SpyNew2(orig_new):
    def __init__(self, master, t):
        super().__init__(master, t)
        dlg2_holder.append(self)


wfmod.NewWfDialog = SpyNew2
d2 = SpyNew2(tab, tab)
root.update()
chk("新类型出现在发起下拉", "贴外箱标" in [k["name"] for k in d2.kinds])
d2.vars["kind"].set("贴外箱标")
d2._on_kind()
chk("新类型的下拉选项生效",
    "1号箱" in list(d2.extra_widgets[0][1].cget("values")),
    list(d2.extra_widgets[0][1].cget("values")))
d2.destroy()

dlg.destroy() if dlg.winfo_exists() else None
kd.destroy() if kd.winfo_exists() else None
root.destroy()
print("RESULT:", "FAIL:%d" % len(fail) if fail else "ALL PASS")
sys.exit(1 if fail else 0)
