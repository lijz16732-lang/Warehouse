# -*- coding: utf-8 -*-
"""一次性补丁：/m 页与手机接口的工位定向支持（后端已改，这里改前端与字段）。"""
import io

p = "wm/mobile.py"
s = io.open(p, encoding="utf-8").read()


def rep(old, new, cnt=1):
    global s
    assert old in s, old[:60]
    s = s.replace(old, new, cnt)


# _wf_out 带工位
rep('        "urgent": int(r.get("urgent") or 0),',
    '        "urgent": int(r.get("urgent") or 0),\n'
    '        "station": str(r.get("station") or ""),')

# 状态里加 stations
rep('var WF = {stages:[], kinds:[], counts:[], rows:[], status:"active", stage:-1,',
    'var WF = {stages:[], kinds:[], stations:[], counts:[], rows:[], '
    'status:"active", stage:-1,')

# stages 接口回填 stations
rep('    WF.stages = b.stages || []; WF.kinds = b.kinds || [];\n'
    '    WF.counts = b.counts || []; WF.last = b.last || 0;',
    '    WF.stages = b.stages || []; WF.kinds = b.kinds || [];\n'
    '    WF.stations = b.stations || [];\n'
    '    WF.counts = b.counts || []; WF.last = b.last || 0;')

# 我的工位：从工位列表选
rep('''    + '<label class="lbl">工位名</label><input class="inp" id="wfStName" value="'
    + esc(MYWF.station) + '" placeholder="如：制作标签A（不填就用节点名）">'
    + '<label class="lbl">绑定节点（这张工位能推进哪一站）</label><select class="inp" id="wfStStage">';
  for (var i = 0; i < WF.stages.length; i++) {
    h += '<option value="' + i + '"' + (MYWF.stage === i ? " selected" : "") + ">"
       + esc(WF.stages[i]) + "</option>";
  }''',
    '''    + '<label class="lbl">我的工位（名称由电脑端「工位设置」维护）</label>'
    + '<select class="inp" id="wfStPick">';
  for (var i = 0; i < WF.stations.length; i++) {
    h += '<option value="' + esc(WF.stations[i].name) + '"'
       + (MYWF.station === WF.stations[i].name ? " selected" : "") + ">"
       + esc(WF.stations[i].name) + "（" + esc(wfStageName(WF.stations[i].stage))
       + "）</option>";
  }''')

rep('''    $("wfStGo").onclick = function(){
      MYWF.station = $("wfStName").value.trim();
      MYWF.stage = Number($("wfStStage").value);
      MYWF.name = $("wfStBy").value.trim();
      saveMyWf(); sheetClose(); toast("工位已保存"); loadWF(true);
    };''',
    '''    $("wfStGo").onclick = function(){
      MYWF.station = $("wfStPick").value;
      for (var i = 0; i < WF.stations.length; i++) {
        if (WF.stations[i].name === MYWF.station) MYWF.stage = WF.stations[i].stage;
      }
      MYWF.name = $("wfStBy").value.trim();
      saveMyWf(); sheetClose(); toast("工位已保存"); loadWF(true);
    };''')

# 列表请求带工位
rep('  api("/m/api/wf?q=list&status=" + WF.status + "&stage=" + st, {}, function(b){',
    '  api("/m/api/wf?q=list&status=" + WF.status + "&stage=" + st\n'
    '      + "&station=" + encodeURIComponent(MYWF.station || ""), {}, function(b){')

# 行里显示交给谁
rep('''      + '<div class="rows">经手人 ' + esc(r.handler || "—") + " · 停留 " + r.days + " 天</div>"''',
    '''      + '<div class="rows">经手人 ' + esc(r.handler || "—")
      + (r.station ? " · 交给 " + esc(r.station) : "") + " · 停留 " + r.days + " 天</div>"''')

# 详情显示交给谁
rep('''      + '<div class="rows">当前：' + esc(w.stage_name) + "（第 " + (w.stage + 1) + " / "
      + stages.length + " 站）· 经手人 " + esc(w.handler || "—") + "</div>"''',
    '''      + '<div class="rows">当前：' + esc(w.stage_name) + "（第 " + (w.stage + 1) + " / "
      + stages.length + " 站）· 交给 " + esc(w.station || "该节点任意人")
      + " · 经手人 " + esc(w.handler || "—") + "</div>"''')

# 推进弹窗：加「交给谁」
rep('''function wfMoveSheet(w, stages){
  var h = '<div class="sum"><div class="sumt">' + esc(w.no) + "</div>"
    + '<div class="rows">推进到：' + esc(stages[w.stage + 1]) + "</div></div>"
    + '<label class="lbl">经手人（必填）</label><input class="inp" id="wfBy" value="'
    + esc(MYWF.name) + '">' '''.rstrip(),
    '''function wfStationOptions(stage, cur){
  var h = '<option value="">该节点任意人</option>';
  for (var i = 0; i < WF.stations.length; i++) {
    if (WF.stations[i].stage !== stage) continue;
    h += '<option value="' + esc(WF.stations[i].name) + '"'
       + (WF.stations[i].name === cur ? " selected" : "") + ">"
       + esc(WF.stations[i].name) + "</option>";
  }
  return h;
}
function wfMoveSheet(w, stages){
  var h = '<div class="sum"><div class="sumt">' + esc(w.no) + "</div>"
    + '<div class="rows">推进到：' + esc(stages[w.stage + 1]) + "</div></div>"
    + '<label class="lbl">交给谁（同一节点有多人时选具体工位）</label>'
    + '<select class="inp" id="wfTo">' + wfStationOptions(w.stage + 1, "") + "</select>"
    + '<label class="lbl">经手人（必填）</label><input class="inp" id="wfBy" value="'
    + esc(MYWF.name) + '">' '''.rstrip())

rep('''      post("/m/api/wf", {op:"move", id:w.id, by:by, stage: MYWF.stage,
        note: $("wfNote").value.trim()}, function(b2){''',
    '''      post("/m/api/wf", {op:"move", id:w.id, by:by, stage: MYWF.stage,
        station: MYWF.station, to_station: $("wfTo").value,
        note: $("wfNote").value.trim()}, function(b2){''')

# 退回弹窗：加「交给谁」
rep('''  h += '</select><label class="lbl">经手人（必填）</label><input class="inp" id="wfBy2" value="'
    + esc(MYWF.name) + '">' '''.rstrip(),
    '''  h += '</select><label class="lbl">交给谁</label>'
    + '<select class="inp" id="wfTo2">' + wfStationOptions(w.stage - 1, "") + "</select>"
    + '<label class="lbl">经手人（必填）</label><input class="inp" id="wfBy2" value="'
    + esc(MYWF.name) + '">' '''.rstrip())

rep('''      post("/m/api/wf", {op:"back", id:w.id, by:by, stage: MYWF.stage,
        target: $("wfTgt").value, note: $("wfNote2").value.trim()}, function(b2){''',
    '''      post("/m/api/wf", {op:"back", id:w.id, by:by, stage: MYWF.stage,
        station: MYWF.station, to_station: $("wfTo2").value,
        target: $("wfTgt").value, note: $("wfNote2").value.trim()}, function(b2){''')

# 发起：加「发给谁」
rep('''    + '<label class="lbl">关联编号（可选）</label><input class="inp" id="crTarget">' '''.rstrip(),
    '''    + '<label class="lbl">发给谁（第一站有多人时选）</label>'
    + '<select class="inp" id="crTo">' + wfStationOptions(0, MYWF.station) + "</select>"
    + '<label class="lbl">关联编号（可选）</label><input class="inp" id="crTarget">' '''.rstrip())

rep('''      post("/m/api/wf", {op:"create", by:by, stage: MYWF.stage, title:title,
        kind:kind, target:$("crTarget").value.trim(), note:$("crNote").value.trim(),
        extra: extra}, function(b2){''',
    '''      post("/m/api/wf", {op:"create", by:by, stage: MYWF.stage, title:title,
        station: MYWF.station, to_station: $("crTo").value,
        kind:kind, target:$("crTarget").value.trim(), note:$("crNote").value.trim(),
        extra: extra}, function(b2){''')

# 其它 wf 请求都带上我自己的工位名（服务端用它判断指定给谁）
import re as _re
s = _re.sub(r"stage: MYWF\.stage(?=[,}])",
            "stage: MYWF.stage, station: MYWF.station", s)

io.open(p, "w", encoding="utf-8").write(s)
print("patched")
