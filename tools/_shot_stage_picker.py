# -*- coding: utf-8 -*-
"""探针：制作流程页顶部的「本机工位」选择器（v1.42.2）。

验证：下拉列出全部节点；第一次选择直接生效并锁定；
锁定后本机（主机）再改要确认；客户端模式下改工位走主机审批（发申请）。
"""
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

tmp = tempfile.mkdtemp(prefix="wm_shot_pick_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()

ctypes.windll.user32.SetCursorPos(2, 2)

# 拦截弹窗，避免探针被模态框卡住
seen = []
wfmod.messagebox.showinfo = lambda t, m, **k: seen.append(("info", t, m))
wfmod.messagebox.askyesno = lambda t, m, **k: (seen.append(("ask", t, m)) or True)
wfmod.messagebox.showwarning = lambda t, m, **k: seen.append(("warn", t, m))

root = tk.Tk()
app = wapp.App(root)

fail = []


def chk(label, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + label
          + ("" if cond else "  %s" % (extra,)))
    if not cond:
        fail.append(label)


idx = None
for i in range(app.nb.index("end")):
    if "制作流程" in str(app.nb.tab(i, "text")):
        idx = i
app.nb.select(idx)
tab = app.tab_workflow
tab.refresh_tab()
root.update_idletasks()
root.update()

stages = app.store.wf_stages()
chk("页面有工位下拉", hasattr(tab, "cb_stage"))
chk("下拉列出全部节点", list(tab.cb_stage.cget("values")) == ["不限"] + list(stages),
    tab.cb_stage.cget("values"))
chk("默认为不限", tab.var_stage.get() == "不限", tab.var_stage.get())
chk("默认未锁定", not tab._stage_locked())

# 第一次选择：直接生效并锁定
tab.var_stage.set(stages[1])
tab._pick_stage()
chk("首次选择立即生效", app.settings.get("wf_my_stage") == 1,
    app.settings.get("wf_my_stage"))
chk("首次选择后已锁定", tab._stage_locked())
chk("提示了已固定", any("已定为" in m for _k, _t, m in seen), seen[-1:])
chk("提示里带工位名", any(stages[1] in m for _k, _t, m in seen))
chk("页脚显示工位", stages[1] in tab.lbl_hint.cget("text"),
    tab.lbl_hint.cget("text"))

# 锁定后再改：主机模式需确认（这里 askyesno 返回 True）
tab.var_stage.set(stages[2])
tab._pick_stage()
chk("锁定后改工位需确认", any(k == "ask" for k, _t, _m in seen))
chk("确认后已改", app.settings.get("wf_my_stage") == 2,
    app.settings.get("wf_my_stage"))

# 客户机：下拉里没有「不限」，未绑定时提示先选工位
app.lan_mode = "client"
app.settings["wf_my_stage"] = -1
app.settings["wf_stage_locked"] = False
tab.refresh_tab()
root.update_idletasks()
root.update()
vals = list(tab.cb_stage.cget("values"))
chk("客户机下拉不含「不限」", "不限" not in vals, vals)
chk("客户机下拉就是全部节点", vals == list(stages), vals)
chk("客户机未选时显示请选择", tab.var_stage.get() == "请选择…",
    tab.var_stage.get())
chk("页脚提示请先选工位", "请先选择" in tab.lbl_hint.cget("text"),
    tab.lbl_hint.cget("text"))
chk("客户机未选时 _stage_ready 为假", not tab._stage_ready())

# 客户机第一次选具体工位：直接生效并锁定
tab.var_stage.set(stages[2])
tab._pick_stage()
chk("客户机首次选工位生效", app.settings.get("wf_my_stage") == 2,
    app.settings.get("wf_my_stage"))
chk("客户机选完已锁定", tab._stage_locked())
chk("客户机选完可操作流程", tab._stage_ready())

try:
    screenshot.capture(os.path.join(OUT, "_wf_stage_picker.png"))
except Exception as e:
    print("  (截图失败：%s)" % e)

root.destroy()
print("结果：%d 失败" % len(fail))
sys.exit(0 if not fail else 1)
