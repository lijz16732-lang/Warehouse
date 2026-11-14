# -*- coding: utf-8 -*-
"""工位（一个节点多人）探针：工位设置弹窗 / 本机工位下拉 / 推送选人 / 过滤。

跑法：.venv310\\Scripts\\python.exe -u tools/_probe_wf_stations.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wm import app as wapp                     # noqa: E402
from wm import workflow as wfmod               # noqa: E402

TMP = tempfile.mkdtemp(prefix="wf_station_")
wapp.resolve_data_dir = lambda: TMP

fails = []


def chk(name, cond, got=""):
    print(("[PASS] " if cond else "[FAIL] ") + name
          + ("" if cond else "  -> %s" % (got,)))
    if not cond:
        fails.append(name)


# 弹窗里的提示框会阻塞探针：全部改成静默
wfmod.messagebox.showinfo = lambda *a, **k: None
wfmod.messagebox.showwarning = lambda *a, **k: None
wfmod.messagebox.askyesno = lambda *a, **k: True

import tkinter as tk                           # noqa: E402
root = tk.Tk()
root.withdraw()
app = wapp.App(root)
root.deiconify()
root.geometry("1x1-3000-3000")
store = app.store
stages = store.wf_stages()

tab = wfmod.WorkflowTab(root, app)
root.update()
tab.refresh_tab()
root.update()

# ---- 1. 工位设置弹窗 ----
def _texts(w, out=None):
    out = out if out is not None else []
    for c in w.winfo_children():
        try:
            t = c.cget("text")
            if t:
                out.append(str(t))
        except Exception:
            pass
        _texts(c, out)
    return out


chk("顶栏有「工位设置」按钮", "工位设置" in _texts(tab), _texts(tab)[:12])

dlg = wfmod.StationsDialog(root, tab)
root.update()
chk("默认每节点一个工位（行数=节点数）",
      len(dlg._entries) == len(stages), len(dlg._entries))
# 给「制作标签」再加一个人：制作标签B
dlg._add_row("制作标签B", 1)
root.update()
chk("可添加工位行", len(dlg._entries) == len(stages) + 1, len(dlg._entries))
dlg._ok()
root.update()
names = store.wf_station_names(1)
chk("保存后同节点有两个工位",
      names == ["制作标签", "制作标签B"] or "制作标签B" in names, names)
chk("工位能反查节点", store.wf_station_stage("制作标签B") == 1,
    store.wf_station_stage("制作标签B"))

# ---- 2. 本机工位下拉改列工位名 ----
tab._sync_stage_picker()
root.update()
vals = list(tab.cb_stage.cget("values"))
chk("本机工位下拉含具名工位", "制作标签B" in vals, vals)
chk("主机多了「不限」", vals and vals[0] == "不限", vals)
tab.var_stage.set("制作标签B")
tab._pick_stage()
root.update()
chk("选中后本机工位落到设置里",
      app.settings.get("wf_my_station") == "制作标签B"
      and app.settings.get("wf_my_stage") == 1,
      (app.settings.get("wf_my_station"), app.settings.get("wf_my_stage")))
chk("_my_station / _my_stage 一致",
      tab._my_station() == "制作标签B" and tab._my_stage() == 1,
      (tab._my_station(), tab._my_stage()))

# ---- 3. 看得见整条流程，但只有本站的单能推（v1.43.1） ----
w_mine, _ = store.wf_create("给我的单", by="张三")
store.wf_advance(w_mine, "张三", "印好", station="制作标签B")
w_other, _ = store.wf_create("给别人的单", by="张三")
store.wf_advance(w_other, "张三", "印好", station="制作标签")
w_pool, _ = store.wf_create("公共池的单", by="张三")
store.wf_advance(w_pool, "张三", "印好")          # 不指定 = 该站任何人
w_down, _ = store.wf_create("已经走到下一站的单", by="张三")
store.wf_advance(w_down, "张三", "印好")
store.wf_advance(w_down, "李四", "贴好")          # 停在「贴标签」(第 3 站)
tab.var_only_mine.set(False)
tab.refresh_rows()
root.update()
ids = [int(i) for i in tab.tree.get_children()]
chk("默认看得到全部在办单（含别站）",
      all(x in ids for x in (w_mine, w_other, w_pool, w_down)), ids)
chk("指定给我的单看得到", w_mine in ids, ids)
chk("别站的单也看得到（看流程）", w_down in ids, ids)
chk("别站的单灰显 tag=other",
      "other" in tab.tree.item(str(w_down), "tags"),
      tab.tree.item(str(w_down), "tags"))
chk("我这一站的单不灰显",
      "other" not in tab.tree.item(str(w_mine), "tags"),
      tab.tree.item(str(w_mine), "tags"))

# 选中别站的单 → 推进/退回按钮禁用
tab.tree.selection_set(str(w_down))
tab.tree.focus(str(w_down))
tab._sync_action_btns()
root.update()
chk("选中别站的单时「推进」禁用", "disabled" in tab.btn_adv.state(),
    tab.btn_adv.state())
chk("选中别站的单时「退回」禁用", "disabled" in tab.btn_back.state(),
    tab.btn_back.state())
chk("提示行说明为什么不能推", "只读" in tab.lbl_hint.cget("text"),
    tab.lbl_hint.cget("text"))
tab.tree.selection_set(str(w_mine))
tab.tree.focus(str(w_mine))
tab._sync_action_btns()
root.update()
chk("选中本站的单时「推进」可用", "disabled" not in tab.btn_adv.state(),
    tab.btn_adv.state())

# 勾上「只看本站」→ 别站的单不列
tab.var_only_mine.set(True)
tab.refresh_rows()
root.update()
ids2 = [int(i) for i in tab.tree.get_children()]
chk("只看本站时别站的单不列", w_down not in ids2, ids2)
chk("只看本站时我的单还在", w_mine in ids2 and w_pool in ids2, ids2)
tab.var_only_mine.set(False)
tab.refresh_rows()
root.update()

# ---- 4. 推进弹窗能选「交给谁」 ----
rec = [r for r in store.wf_list("active", station="制作标签B")
       if int(r["id"]) == w_mine][0]
fd = wfmod.FlowDialog(root, tab, rec, True)
root.update()
svals = list(fd.cb_station.cget("values"))
chk("「交给谁」列出目标节点工位",
      svals[0] == "该节点任意人" and stages[2] in svals, svals)
chk("不默认指定人（公共池）", fd.var_station.get() == "该节点任意人",
    fd.var_station.get())
# 在该节点再加一个人，验证能选具体工位（保留第 2 站的 制作标签A/B）
store.wf_set_stations([{"name": "制作标签A", "stage": 1},
                       {"name": "制作标签B", "stage": 1},
                       {"name": "贴标签A", "stage": 2},
                       {"name": "贴标签B", "stage": 2}])
fd._fill_stations(2)
root.update()
svals = list(fd.cb_station.cget("values"))
chk("同节点多人时可选具体工位",
      "贴标签A" in svals and "贴标签B" in svals, svals)
fd.var_by.set("李四")
fd.var_station.set("贴标签B")
fd._ok()
root.update()
chk("确定后带回 5 元组（含交给谁）",
      isinstance(fd.result, tuple) and len(fd.result) == 5
      and fd.result[4] == "贴标签B", fd.result)

# ---- 5. 走一遍 move_selected：弹窗返回值能落到单据上 ----
# 真弹窗是模态的（wait_window），探针里用桩替代，只验 5 元组解包 + 传参
_RealFlow = wfmod.FlowDialog
tab.wait_window = lambda d=None: None      # 桩弹窗不是 widget，跳过等待
wfmod.FlowDialog = lambda *a, **k: type(
    "D", (), {"result": ("李四", "试推", None, None, "贴标签B"),
              "at_last": False})()
tab.tree.selection_set(str(w_mine))
tab.tree.focus(str(w_mine))
tab.move_selected(True)
wfmod.FlowDialog = _RealFlow
root.update()
rec = store.wf_one(w_mine)
chk("点推进后单据指派给「贴标签B」",
      rec["station"] == "贴标签B", rec["station"])
chk("日志写明交给谁",
      any("交给 贴标签B" in (g["note"] or "") for g in store.wf_logs(w_mine)),
      [g["note"] for g in store.wf_logs(w_mine)])

# ---- 6. 退回弹窗：换目标节点，工位下拉跟着换 ----
rec = [r for r in store.wf_list("active") if int(r["id"]) == w_mine][0]
fd2 = wfmod.FlowDialog(root, tab, rec, False)
root.update()
chk("退回弹窗也有「交给谁」", fd2.cb_station is not None)
fd2.var_target.set(stages[1])
fd2._fill_stations(1)
root.update()
chk("换成「制作标签」后工位下拉跟着换",
      "制作标签B" in list(fd2.cb_station.cget("values"))
      and "贴标签A" not in list(fd2.cb_station.cget("values")),
      list(fd2.cb_station.cget("values")))
fd2.destroy()

# ---- 7. 详情里能看到交给谁 ----
rec = [r for r in store.wf_list("active") if int(r["id"]) == w_mine][0]
dd = wfmod.DetailDialog(root, tab, rec)
root.update()
txt = []


def walk(w):
    for c in w.winfo_children():
        try:
            t = c.cget("text")
            if t:
                txt.append(str(t))
        except Exception:
            pass
        walk(c)


walk(dd)
chk("详情显示「交给：贴标签B」",
      any("交给：贴标签B" in t for t in txt), txt[:3])
dd.destroy()

root.destroy()
app.store.close()
import shutil                                  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("RESULT:", "ALL OK" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
