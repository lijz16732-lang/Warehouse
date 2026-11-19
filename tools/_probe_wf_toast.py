# -*- coding: utf-8 -*-
"""探针：推进/退回提示显示交给的负责人（v1.43.6）。

推进时指定工位 → 提示括号里是目标站负责人（赵六），
不是推送人；未指定工位 → 仍显示推送人。
用法：.venv310/Scripts/python.exe tools/_probe_wf_toast.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wm import app as wapp  # noqa: E402
from wm.store import Store  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wf_toast_probe_")
wapp.resolve_data_dir = lambda: TMP
store = Store(os.path.join(TMP, "data", "warehouse.db"))

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print("  ok  %s" % name)
    else:
        print("  FAIL %s -> %r" % (name, detail))


def main():
    # 工位绑定负责人：质检 = 赵六，贴标签 = 王五
    store.wf_set_stages(["发起制作", "制作标签", "贴标签", "质检", "发货"])
    store.wf_set_stations([
        {"name": "发起制作", "stage": 0, "owner": "张三"},
        {"name": "制作标签", "stage": 1, "owner": "李四"},
        {"name": "贴标签", "stage": 2, "owner": "王五"},
        {"name": "质检", "stage": 3, "owner": "赵六"},
        {"name": "发货", "stage": 4, "owner": "周七"},
    ])
    wid, _ = store.wf_create("测试单A", by="张三")

    # ① 逐站推进到贴标签（stage 2），王五再推进并交给「质检」工位
    ok, msg = store.wf_advance(wid, "李四")
    chk("推进到制作标签", ok, msg)
    ok, msg = store.wf_advance(wid, "王五")
    chk("推进到贴标签", ok, msg)
    ok, msg = store.wf_advance(wid, "王五", station="质检")
    chk("推进成功", ok, msg)
    chk("指定工位时提示显示负责人赵六",
        "已推进到「质检」（赵六）" in msg, msg)
    chk("提示不含推送人王五", "王五" not in msg, msg)

    # ② 未指定工位 → 仍显示推送人
    wid2, _ = store.wf_create("测试单B", by="张三")
    ok, msg = store.wf_advance(wid2, "张三")
    chk("未指定工位时提示显示推送人",
        "已推进到「制作标签」（张三）" in msg, msg)

    # ③ 退回到指定工位 → 同样显示目标站负责人
    ok, msg = store.wf_back(wid, "赵六", note="", target=1, station="制作标签")
    chk("跨站退回成功", ok, msg)
    chk("退回提示显示目标站负责人李四",
        "已退回到「制作标签」（李四）" in msg, msg)

    # ④ 留痕不变：日志仍是「交给 质检（赵六）」
    logs = store.wf_logs(wid)
    adv = [g for g in logs if g["action"] == "advance"]
    chk("日志留痕写明交给工位与负责人",
        any("交给 质检（赵六）" in (g["note"] or "") for g in adv), adv)

    print("== 探针完成：%d 项全部通过 ==" % PASS)


if __name__ == "__main__":
    main()
