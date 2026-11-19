# -*- coding: utf-8 -*-
"""手机端制作流程探针：手机发起 → 电脑推进 → 手机推进（互通）+ 工位校验/加急/退回/入库。

直接调 mobile.handle_wf（不启 HTTP），用临时库跑完整闭环。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wm.mobile import MobileService, handle_wf          # noqa: E402
from wm.store import Store                             # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name
          + (("  -> %s" % extra) if not cond else ""))
    if not cond:
        FAIL.append(name)


class Srv(object):
    def __init__(self, store):
        self.store = store
        self.mobile = MobileService()
        self.port = 8765

    def get_store(self):
        return self.store

    def can_write(self, ip):
        return False                   # 制作流程不需要「允许录入」授权

    def get_warehouse(self):
        return "测试仓"


tmp = tempfile.mkdtemp(prefix="probe_mwf_")
st = Store(os.path.join(tmp, "t.db"))
srv = Srv(st)
ip = "192.168.1.60"
code, body, _h = srv.mobile.login(ip, "123456", lambda c: c == "123456",
                                  app_mode=True)
check("手机登录", code == 200 and body.get("ok"), body)
tok = body.get("token") or ""

stages = st.wf_stages()
n = len(stages)
print("节点：", " → ".join(stages))

# ---- 1. 节点 / 类型定义 ----
c, b, _ = handle_wf(srv, ip, tok, {"q": "stages"})
check("取节点与类型", c == 200 and b.get("stages") == stages
      and isinstance(b.get("kinds"), list) and b.get("last") == n - 1, b)

# ---- 2. 手机发起（工位=第一站） ----
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "create", "by": "小周", "stage": 0, "title": "手机发起的标签单",
    "kind": "制作标签", "note": "客户催", "target": "WL-02054",
    "extra": {"标签种类": "外箱标、机身标"}})
check("手机发起成功", c == 200 and b.get("ok") and b.get("no"), b)
wf1 = int(b.get("id") or 0)

c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "create", "by": "小周", "stage": 1, "title": "工位不对"})
check("非第一站不能发起", c == 403 and "工位" in (b.get("error") or ""), b)

# ---- 3. 电脑端立刻能看到（同一库） ----
c, b, _ = handle_wf(srv, ip, tok, {"q": "list", "status": "active", "stage": "0"})
check("电脑端（同库）列表可见手机单",
      c == 200 and any(r["id"] == wf1 for r in b["rows"]), b)
check("列表带回备注与加急位",
      any(r["note"] == "客户催" and r["urgent"] == 0 for r in b["rows"]), b["rows"])

# ---- 4. 电脑推进 → 手机下一站看得到 ----
ok, msg = st.wf_advance(wf1, "电脑-李四", "标签印好")
check("电脑推进到下一站", ok, msg)
c, b, _ = handle_wf(srv, ip, tok, {"q": "list", "status": "active", "stage": "1"})
check("手机在第二站看到该单（互通）",
      any(r["id"] == wf1 and r["stage"] == 1 for r in b["rows"]), b["rows"])
check("电脑备注带到手机", any(r["note"] == "标签印好" for r in b["rows"]), b["rows"])

# ---- 5. 手机推进（自己的站） ----
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "move", "id": wf1, "by": "小周", "stage": 1, "note": "手机贴好"})
check("手机在自己的站推进成功", c == 200 and b.get("ok"), b)
check("推进后备注跟随",
      st.wf_one(wf1)["note"] == "手机贴好", st.wf_one(wf1)["note"])

# ---- 6. 工位校验 ----
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "move", "id": wf1, "by": "小周", "stage": 0})
check("越站推进被拒", c == 403 and "不是你负责" in (b.get("error") or ""), b)
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "move", "id": wf1, "by": "小周", "stage": -1})
check("没设工位被拒", c == 403 and "工位" in (b.get("error") or ""), b)
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "move", "id": wf1, "by": "", "stage": 2})
check("不填经手人被拒", c == 400 and "名字" in (b.get("error") or ""), b)

# ---- 7. 加急（任何工位都能标） ----
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "urgent", "id": wf1, "by": "小周", "stage": 0, "flag": 1})
check("手机加急成功", c == 200 and st.wf_one(wf1)["urgent"] == 1, b)
c, b, _ = handle_wf(srv, ip, tok, {"q": "list", "status": "active", "stage": "2"})
check("加急单排在列表最前",
      b["rows"] and b["rows"][0]["id"] == wf1 and b["rows"][0]["urgent"] == 1,
      b.get("rows"))

# ---- 8. 跨站退回（手机在质检退回制作标签） ----
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "back", "id": wf1, "by": "小周", "stage": 2, "target": 1,
    "note": "标签印歪"})
check("手机跨站退回成功", c == 200 and st.wf_one(wf1)["stage"] == 1, b)
check("退回原因留痕",
      any(g["action"] == "back" and g["note"] == "标签印歪"
          for g in st.wf_logs(wf1)))

# ---- 9. 详情 ----
c, b, _ = handle_wf(srv, ip, tok, {"q": "detail", "id": str(wf1)})
check("详情返回流转记录", c == 200 and len(b.get("logs") or []) >= 4, b.get("logs"))
check("详情节点名正确", (b.get("wf") or {}).get("stage_name") == stages[1], b.get("wf"))

# ---- 10. 推到最后一站 → 手机入库 ----
while int(st.wf_one(wf1)["stage"]) < n - 1:
    st.wf_advance(wf1, "电脑-王五", "")
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "move", "id": wf1, "by": "小周", "stage": n - 1})
check("最后一站不能再「推进」，提示入库/结单",
      c == 400 and "入库" in (b.get("error") or ""), b)

c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "stock", "id": wf1, "by": "小周", "stage": n - 1,
    "fields": {"brand": "保德", "category": "断路器", "model": "S10MD",
               "qty": "1", "price": "188", "shelf": "3排B"}})
check("手机入库成功", c == 200 and b.get("ok"), b)
check("入库后单据已完成", st.wf_one(wf1)["status"] == "done", st.wf_one(wf1))
check("库存里出现该型号",
      any(r["model"] == "S10MD" for r in st.all_records()), st.all_records()[-3:])
check("入库回写关联编号",
      (st.wf_one(wf1)["target"] or "").startswith("WL-"), st.wf_one(wf1)["target"])

# ---- 11. 结单（不建库存） ----
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "create", "by": "小周", "stage": 0, "title": "报废单"})
wf2 = int(b.get("id") or 0)
while int(st.wf_one(wf2)["stage"]) < n - 1:
    st.wf_advance(wf2, "电脑-王五", "")
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "finish", "id": wf2, "by": "小周", "stage": n - 1, "note": "报废"})
check("手机直接结单", c == 200 and st.wf_one(wf2)["status"] == "done", b)

# ---- 12. 一个节点多人：具名工位 + 定向推送（v1.43.0）----
c, b, _ = handle_wf(srv, ip, tok, {"q": "stages"})
check("stages 带回工位定义",
      isinstance(b.get("stations"), list) and b["stations"]
      and b["stations"][0].get("stage") == 0, b.get("stations"))
st.wf_set_stations(
    [{"name": "发起制作A", "stage": 0}, {"name": "发起制作B", "stage": 0},
     {"name": "制作标签A", "stage": 1},
     {"name": "制作标签B", "stage": 1, "owner": "李四"}])
c, b, _ = handle_wf(srv, ip, tok, {"q": "stages"})
_names = [s["name"] for s in (b.get("stations") or [])]
check("改完工位后 stages 立刻反映",
      "制作标签A" in _names and "制作标签B" in _names, _names)
_owners = {s["name"]: s.get("owner") for s in (b.get("stations") or [])}
check("工位负责人随 stages 下发",
      _owners.get("制作标签B") == "李四"
      and not _owners.get("制作标签A"), _owners)
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "create", "by": "小周", "stage": 0, "station": "发起制作A",
    "title": "A/B 工位单", "to_station": "发起制作A"})
wf3 = int(b.get("id") or 0)
check("手机发起时可直接指定工位",
      c == 200 and wf3 and st.wf_one(wf3)["station"] == "发起制作A", b)
c, b, _ = handle_wf(srv, ip, tok, {"q": "list", "status": "active",
                                   "stage": "0", "station": "发起制作B",
                                   "mine_stage": "0"})
check("别站的单也看得到（只是 mine=false）",
      any(r["id"] == wf3 and r["mine"] is False for r in (b.get("rows") or [])),
      b.get("rows"))
c, b, _ = handle_wf(srv, ip, tok, {"q": "list", "status": "active",
                                   "stage": "0", "station": "发起制作B",
                                   "mine_stage": "0", "only": "1"})
check("勾「只看我的」时别站的单不出现",
      all(r["id"] != wf3 for r in (b.get("rows") or [])), b.get("rows"))
c, b, _ = handle_wf(srv, ip, tok, {"q": "list", "status": "active",
                                   "stage": "0", "station": "发起制作A",
                                   "mine_stage": "0"})
check("指定给我的单 mine=true、可推进",
      any(r["id"] == wf3 and r["mine"] is True for r in (b.get("rows") or [])),
      b.get("rows"))
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "move", "id": wf3, "by": "小周", "stage": 0,
    "station": "发起制作B", "to_station": "制作标签B"})
check("不是我的单（工位不符）不能推", c == 403 and "指定交给" in
      (b.get("error") or ""), b)
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "move", "id": wf3, "by": "小周", "stage": 0,
    "station": "发起制作A", "to_station": "制作标签B"})
check("推给下一站的具体工位",
      c == 200 and st.wf_one(wf3)["station"] == "制作标签B", b)
c, b, _ = handle_wf(srv, ip, tok, None, {
    "op": "move", "id": wf3, "by": "小周", "stage": 1,
    "station": "制作标签B"})
check("被指定的工位可以接着往下推",
      c == 200 and st.wf_one(wf3)["station"] == "", b)
check("日志写明交给哪个工位",
      any("交给 制作标签B" in (g["note"] or "") for g in st.wf_logs(wf3)),
      [g["note"] for g in st.wf_logs(wf3)])
st.wf_set_stations([{"name": s, "stage": i}
                    for i, s in enumerate(st.wf_stages())])

# ---- 13. 登录校验 ----
c, b, _ = handle_wf(srv, ip, "bad-token", {"q": "stages"})
check("未登录被拒", c == 401, b)

st.close()
import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
print("全部通过" if not FAIL else "失败：%s" % FAIL)
sys.exit(1 if FAIL else 0)
