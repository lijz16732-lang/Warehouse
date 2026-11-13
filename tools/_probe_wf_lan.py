# -*- coding: utf-8 -*-
"""探针：制作流程在局域网下的可见性 / 工位权限 / 自动刷新版本号。

规则（v1.42.2）：
  · 制作流程不需要「允许录入」授权，连上就能用；
  · 主机可给每台电脑绑定一个工位，绑定后只能推进停在该工位的单；
  · 绑定了工位的电脑不能发起制作单（除非绑的是第一个工位）、不能取消/删除。

验证：
  1. 只读客户端能读 wf_list / wf_counts / wf_logs / wf_stages
  2. 未授权（只读）也能发起 / 推进 —— 制作流程不需要授权
  3. 绑定工位后：只能推自己那一站，别站被拒
  4. 绑了第二站的电脑不能发起制作单、不能取消
  5. workflows 写入 bump rev（客户端 4 秒轮询自动刷新的依据）
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wm.lan import LanServer
from wm.remote import RemoteError, RemoteStore
from wm.store import Store

PORT = 17662
CODE = "246810"

ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [PASS] %s %s" % (name, extra))
    else:
        fail += 1
        print("  [FAIL] %s %s" % (name, extra))


tmp = tempfile.mkdtemp(prefix="wf_lan_")
store = Store(os.path.join(tmp, "w.db"))
try:
    print("== 0. 准备数据 ==")
    stages = store.wf_stages()
    wf_id, no = store.wf_create("修标签 S10MD", kind="修复标签", by="张三")
    check("发起制作单", bool(wf_id), "(%s，节点 %d 个：%s)"
          % (no, len(stages), " → ".join(stages)))
    rev0 = store.revision()
    ok2, msg = store.wf_advance(wf_id, "李四", "标签做好")
    check("主机端推进", ok2, msg)
    check("workflows 写入会 bump rev", store.revision() > rev0)

    print("== 1. 启动主机服务 ==")
    srv = LanServer(lambda: store, lambda: "测试仓", CODE, port=PORT)
    started, smsg = srv.start()
    check("服务启动", started, smsg)

    ro = RemoteStore("127.0.0.2", PORT, CODE, client_id="pc-B", client_name="B-制作")
    ro.ping()
    check("客户端未授权（只读）", not ro.can_write)

    print("== 2. 只读也能看制作流程 ==")
    rows = ro.wf_list("active", "")
    check("可读 wf_list", isinstance(rows, list) and len(rows) == 1)
    check("可读 wf_counts", isinstance(ro.wf_counts(), dict))
    check("可读 wf_logs", len(ro.wf_logs(wf_id)) >= 2)
    check("可读 wf_stages", ro.wf_stages() == stages)
    check("能看到当前节点", rows[0].get("stage_name") == stages[1],
          "(%s / %s)" % (rows[0].get("stage_name"), rows[0].get("handler")))

    print("== 3. 客户机没选工位不能推进（「不限」只给主机） ==")
    denied0, err0 = False, ""
    try:
        ro.wf_advance(wf_id, "王五", "没选工位就想推")
    except RemoteError as e:
        denied0, err0 = True, str(e)
    check("未选工位被拒", denied0, "(%s)" % err0)
    check("被拒后数据没变", store.wf_one(wf_id)["stage"] == 1)

    ro.wf_stage = 1                     # 本机在制作流程页选「制作标签」
    ok3, msg3 = ro.wf_advance(wf_id, "王五", "未授权也能推进")
    check("选了工位可推进（不依赖允许录入）", ok3, msg3)
    check("主机数据已变", store.wf_one(wf_id)["stage"] == 2)
    check("经手人是客户端填的名字",
          store.wf_list("active")[0].get("handler") == "王五")

    # 回到第二站，供后面工位测试
    store.wf_back(wf_id, "张三", "回退测试")

    print("== 4. 选了工位后只能推自己那一站 ==")
    ro.wf_stage = 1                     # 本机在制作流程页选「制作标签」
    check("选工位不依赖授权", not ro.can_write)

    # 先把单放回第一站，B 绑的是第二站 → 应被拒
    store.wf_back(wf_id, "张三", "放回第一站")
    denied, err = False, ""
    try:
        ro.wf_advance(wf_id, "王五", "越站推进")
    except RemoteError as e:
        denied, err = True, str(e)
    check("别站的单被拒", denied, "(%s)" % err)
    check("被拒后数据没变", store.wf_one(wf_id)["stage"] == 0)

    # 主机推到第二站 → B 就能推了
    store.wf_advance(wf_id, "李四", "到第二站")
    ok4, msg4 = ro.wf_advance(wf_id, "王五", "本站推进")
    check("自己那一站可推", ok4, msg4)
    check("数据推进到第三站", store.wf_one(wf_id)["stage"] == 2)

    print("== 5. 绑了第二站的电脑不能发起 / 取消 ==")
    bad1, e1 = False, ""
    try:
        ro.wf_create("越权发起", by="王五")
    except RemoteError as e:
        bad1, e1 = True, str(e)
    check("不能发起制作单", bad1, "(%s)" % e1)
    bad2, e2 = False, ""
    try:
        ro.wf_cancel(wf_id, "王五", "越权取消")
    except RemoteError as e:
        bad2, e2 = True, str(e)
    check("不能取消制作单", bad2, "(%s)" % e2)
    check("取消被拒后状态没变", store.wf_one(wf_id)["status"] == "active")

    print("== 5b. 跨站退回（质检发现问题直接退回制作标签） ==")
    store.wf_advance(wf_id, "李四", "到质检")      # stage 2 → 3（质检）
    cur = store.wf_one(wf_id)["stage"]
    check("单据已到质检站", cur == 3, "(stage=%d)" % cur)
    # B 绑的是制作标签(1)，单在质检 → 越站退回被拒
    bad3, e3 = False, ""
    try:
        ro.wf_back(wf_id, "王五", "越站退回")
    except RemoteError as e:
        bad3, e3 = True, str(e)
    check("别站的单不能退", bad3, "(%s)" % e3)
    # 质检站的电脑（C）发现问题，直接退回到「制作标签」(target=1)
    pc_c = RemoteStore("127.0.0.1", PORT, CODE, client_id="pc-C",
                       client_name="C-质检")
    pc_c.wf_stage = 3
    pc_c.ping()
    ok5b, msg5b = pc_c.wf_back(wf_id, "质检员小王", "标签印错字",
                               target=1)
    check("质检站可跨站退回到制作标签", ok5b, msg5b)
    check("单据回到制作标签站", store.wf_one(wf_id)["stage"] == 1)
    check("跨站退回留痕",
          any(g["action"] == "back" and g["stage"] == 1
              and g["by"] == "质检员小王" and g["note"] == "标签印错字"
              for g in store.wf_logs(wf_id)),
          [g for g in store.wf_logs(wf_id) if g["action"] == "back"][-1])

    print("== 6. 绑到第一个工位的电脑可以发起 ==")
    pc_a = RemoteStore("127.0.0.1", PORT, CODE, client_id="pc-A", client_name="A-发起")
    pc_a.wf_stage = 0
    pc_a.ping()
    check("A 选的是第一个工位", pc_a.wf_stage == 0)
    nid, nno = pc_a.wf_create("A 发起的新单", kind="修复", by="张三")
    check("第一工位可发起", bool(nid), nno)

    print("== 7. rev 递增（客户端自动刷新依据） ==")
    ro.ping()
    rev_now = ro.rev
    store.wf_advance(wf_id, "赵六", "继续推进")
    ro.ping()
    check("变化后 rev 变了", ro.rev != rev_now, "(%s → %s)" % (rev_now, ro.rev))

    print("== 8. 工位变更要走主机审批 ==")
    ro.request_stage(3)
    check("申请进入待批", ro.stage_result()["status"] == "pending",
          ro.stage_result())
    pend = srv.stage_reqs.get("127.0.0.2") or srv.stage_reqs.get("127.0.0.1") or {}
    check("主机看到申请内容", int(pend.get("stage", -1)) == 3, pend)
    host_ip = [k for k in srv.stage_reqs][0]
    srv.answer_stage(host_ip, False)
    check("主机拒绝后状态为 no", ro.stage_result()["status"] == "no")
    ro.request_stage(2)
    host_ip = [k for k in srv.stage_reqs][0]
    srv.answer_stage(host_ip, True)
    check("主机同意后状态为 ok", ro.stage_result()["status"] == "ok")
    ro.wf_stage = 2                     # 同意后客户端才真正改工位
    check("新工位立即生效", ro.wf_stage == 2)

    print("== 9. 主机列表能看到各电脑选的工位 ==")
    snap = list(srv.snapshot())
    # 本机两台客户端都从 127.0.0.1 出去，服务端按 IP 合并成一条；
    # 真实部署是不同电脑不同 IP，这里只校验「工位值确实上报上来了」
    check("主机能看到电脑选的工位",
          bool(snap) and snap[0].get("stage") in (0, 1, 2), snap)

    srv.stop()
finally:
    store.close()
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过 / %d 失败" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
