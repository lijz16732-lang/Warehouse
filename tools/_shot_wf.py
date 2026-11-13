# -*- coding: utf-8 -*-
"""探针：v1.42.0 制作流程页（流程条 / 列表 / 发起弹窗 / 推进弹窗 / 时间线）。"""
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
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

tmp = tempfile.mkdtemp(prefix="wm_shot_wf_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()

ctypes.windll.user32.SetCursorPos(2, 2)

root = tk.Tk()
app = wapp.App(root)

rows = []
for i, (brand, cat, model) in enumerate([
        ("ABB", "变频器", "ACS510-01"), ("西门子", "PLC", "S7-200 CN"),
        ("三菱", "伺服", "MR-J4-70A")], start=1):
    r = blank_record()
    r.update({"code": "WL-%05d" % i, "brand": brand, "category": cat,
              "model": model, "price": 1000.0, "qty": 5, "shelf": "6排A-3",
              "condition": "全新", "listed": 1})
    rows.append(r)
app.store.insert_many(rows)
app.load_data()

# 造制作单：不同节点 / 状态
w1, _ = app.store.wf_create("修复 WL-00001 外壳划痕", kind="修复",
                            target="WL-00001", by="张三")
w2, _ = app.store.wf_create("更换 WL-00002 型号标签", kind="更换型号标签",
                            target="WL-00002", by="李四")
w3, _ = app.store.wf_create("返工 WL-00003 面板丝印", kind="返工",
                            target="WL-00003", by="王五")
app.store.wf_advance(w1, "李四", "外壳已修好")      # → 制作标签
app.store.wf_advance(w2, "赵六")                    # → 制作标签
app.store.wf_advance(w2, "赵六", "标签打印完成")     # → 贴标签
app.store.wf_advance(w3, "钱七")                    # → 制作标签
app.store.wf_advance(w3, "钱七")                    # → 贴标签
app.store.wf_advance(w3, "孙八", "贴好待检")         # → 质检
w4, _ = app.store.wf_create("重打铭牌一批", kind="其他", by="周九")
app.store.wf_advance(w4, "周九")
app.store.wf_advance(w4, "吴十")
app.store.wf_advance(w4, "吴十")
app.store.wf_advance(w4, "郑一", "全检通过")
app.store.wf_advance(w4, "郑一")                    # → 入库 = 完成
w5, _ = app.store.wf_create("报废件重做标牌", kind="其他", by="张三")
app.store.wf_cancel(w5, "张三", "客户取消了订单")


def _hwnd(w):
    return ctypes.windll.user32.GetAncestor(w.winfo_id(), 2)


def pump(n=3):
    for _ in range(n):
        root.update_idletasks()
        root.update()


def shot(name):
    root.update_idletasks()
    root.update()
    screenshot.capture_window("仓管家 · 仓库管理系统", os.path.join(OUT, name))


ok = True


def chk(label, cond, extra=""):
    global ok
    print(("  [PASS] " if cond else "  [FAIL] ") + label
          + ("" if cond else "  %s" % (extra,)))
    if not cond:
        ok = False


pump()

# 1) 切到制作流程页
wf_idx = None
for i in range(app.nb.index("end")):
    if "制作流程" in str(app.nb.tab(i, "text")):
        wf_idx = i
app.nb.select(wf_idx)
app.tab_workflow.refresh_tab()
pump()
shot("_wf_main.png")
chk("页面注册且能切换", wf_idx is not None)
chk("进行中 3 张单", len(app.tab_workflow.rows) == 3, len(app.tab_workflow.rows))
chk("流程条节点数=5", len(app.store.wf_counts()["counts"]) == 5)
chk("已完成计数 1", app.store.wf_counts()["done"] == 1)
chk("已取消计数 1", app.store.wf_counts()["cancelled"] == 1)


from wm.workflow import FlowDialog, DetailDialog, StagesDialog  # noqa: E402

# ---- mainloop 定时器模式：让窗口真正绘制后再截 ----
seq = []


def step():
    global ok
    if not seq:
        print("ALL OK" if ok else "HAS FAIL")
        root.destroy()
        return
    fn = seq.pop(0)
    try:
        fn()
    except Exception:
        import traceback; traceback.print_exc()
        ok = False
    root.after(600, step)


rec1 = app.tab_workflow._by_id[w1]
rec3 = app.tab_workflow._by_id[w3]

dlg = [None]


def s_flow():
    dlg[0] = FlowDialog(app.tab_workflow, app.tab_workflow, rec1, True)
    seq.append(lambda: (screenshot.capture(os.path.join(OUT, "_wf_flow.png")),
                        dlg[0].destroy()))


def s_flow_last():
    dlg[0] = FlowDialog(app.tab_workflow, app.tab_workflow, rec3, True)
    seq.append(lambda: (screenshot.capture(os.path.join(OUT, "_wf_flow_last.png")),
                        dlg[0].destroy()))


def s_detail():
    dlg[0] = DetailDialog(app.tab_workflow, app.tab_workflow,
                          app.tab_workflow._by_id[w3])
    seq.append(lambda: (screenshot.capture(os.path.join(OUT, "_wf_detail.png")),
                        dlg[0].destroy()))


def s_stages():
    dlg[0] = StagesDialog(app.tab_workflow, app.tab_workflow)
    seq.append(lambda: (screenshot.capture(os.path.join(OUT, "_wf_stages.png")),
                        dlg[0].destroy()))


seq += [s_flow, s_flow_last, s_detail, s_stages]
root.after(600, step)
root.mainloop()
