# -*- coding: utf-8 -*-
"""探针：退回弹窗跨站退回（v1.42.7）。

验证 FlowDialog 退回模式下「目标节点」下拉列出当前站之前的所有节点、
默认上一站、选中更早的站后 _ok 返回正确 target 序号；
store.wf_back(target=) 跨站退回并留痕；推进弹窗保持原样。
用法：.venv310/Scripts/python.exe tools/_probe_wf_back.py
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm import workflow as wf  # noqa: E402
from wm.store import Store  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wf_back_probe_")
wapp.resolve_data_dir = lambda: TMP
store = Store(os.path.join(TMP, "data", "warehouse.db"))
ctypes.windll.user32.SetCursorPos(2, 2)

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    print(("  [PASS] %s" if ok else "  [FAIL] %s") % name, detail or "")
    if not ok:
        sys.exit("探针失败：%s %s" % (name, detail))
    PASS += 1


class FakeTab:
    """最小 tab 桩：FlowDialog 只用到 fam / app.store / app.settings。"""

    fam = "Microsoft YaHei"

    def __init__(self):
        class A:
            pass
        a = A()
        a.store = store
        a.settings = {}
        self.app = a
        self.remember_name = lambda by: None


def walk(w):
    for c in w.winfo_children():
        yield c
        yield from walk(c)


def main():
    tab = FakeTab()

    # 五节点：发起制作/制作标签/贴标签/质检/入库；单子推到「质检」(stage=3)
    wid, _ = store.wf_create("探针-跨站退回", kind="修复", by="张三")
    for _ in range(3):
        store.wf_advance(wid, "张三")
    rec = [r for r in store.wf_list("active") if r["id"] == wid][0]
    chk("单据已到质检站", rec["stage"] == 3, rec["stage_name"])

    root = tk.Tk()
    root.withdraw()

    # ① 退回弹窗：下拉应列出质检之前的所有站，默认「贴标签」
    dlg = wf.FlowDialog(root, tab, rec, forward=False)
    chk("弹窗能构造", dlg.winfo_exists())
    combos = [w for w in walk(dlg) if w.winfo_class() == "TCombobox"]
    chk("退回弹窗有目标节点下拉", len(combos) == 2, len(combos))
    tgts = [c for c in combos
            if list(c["values"]) == ["发起制作", "制作标签", "贴标签"]]
    chk("目标节点下拉列出质检之前的所有站",
        len(tgts) == 1 and list(tgts[0]["values"])
        == ["发起制作", "制作标签", "贴标签"],
        [list(c["values"]) for c in combos])
    cb = tgts[0]
    chk("默认退回上一站（贴标签）", dlg.var_target.get() == "贴标签",
        dlg.var_target.get())

    # ② 模拟质检员选择直接退回「制作标签」→ _ok 应返回 target=1
    dlg.var_target.set("制作标签")
    dlg.var_by.set("质检员小王")
    dlg._ok()
    by, note, stock_rec, target, _station = dlg.result
    chk("_ok 返回跨站 target=1", target == 1, (by, target))
    chk("不勾库存时 stock_rec 为 None", stock_rec is None)

    # ③ store 层跨站退回 + 留痕
    ok, msg = store.wf_back(wid, "质检员小王", note, target=target)
    chk("跨站退回成功", ok, msg)
    rec2 = [r for r in store.wf_list("active") if r["id"] == wid][0]
    chk("单据回到制作标签站", rec2["stage"] == 1, rec2["stage_name"])
    logs = store.wf_logs(wid)
    chk("留痕写明退回目标站",
        any(g["action"] == "back" and "制作标签" in (g["note"] or "")
            for g in logs), logs[-1])

    # ④ 推进弹窗不受影响：只有「交给谁」下拉（v1.43.0），没有目标下拉
    rec3 = [r for r in store.wf_list("active") if r["id"] == wid][0]
    dlg2 = wf.FlowDialog(root, tab, rec3, forward=True)
    combos2 = [w for w in walk(dlg2) if w.winfo_class() == "TCombobox"]
    chk("推进弹窗无目标下拉（只有交给谁）",
        len(combos2) == 1
        and list(combos2[0]["values"])[0] == "该节点任意人",
        [list(c["values"])[:1] for c in combos2])
    dlg2.destroy()

    dlg.destroy()
    root.destroy()
    print("== 探针完成：%d 项全部通过 ==" % PASS)


if __name__ == "__main__":
    main()
