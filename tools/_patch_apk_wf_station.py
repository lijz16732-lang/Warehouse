# -*- coding: utf-8 -*-
"""APK 内置页：工位定向补丁（工位选择 / 交给谁 / 请求带工位名）。"""
import io

p = "android/assets/index.html"
s = io.open(p, encoding="utf-8").read()


def rep(old, new, cnt=1):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, cnt)


# 状态里加工位列表
rep("var WF = { stages: [], kinds: [], counts: [], rows: [], status: 'active',\n"
    "           stage: -1, last: 0, all: false };",
    "var WF = { stages: [], kinds: [], stations: [], counts: [], rows: [],\n"
    "           status: 'active', stage: -1, last: 0, all: false };")

rep("    WF.counts = j.counts || []; WF.last = j.last || 0;",
    "    WF.stations = j.stations || [];\n"
    "    WF.counts = j.counts || []; WF.last = j.last || 0;")

# 工位弹层：选工位名（不是节点）
rep("""  var h = '<div class="hint" style="margin:0 0 10px">一个节点可以有多个人：工位名写成「制作标签A」「制作标签B」，'
    + '都绑定同一个节点即可，推进时按各自姓名留痕。</div>'
    + '<div class="row"><label>工位名</label><input id="wfStName" value="' + escWf(MYWF.station)
    + '" placeholder="如：制作标签A"></div>'
    + '<div class="row"><label>绑定节点</label><select id="wfStStage" style="flex:1">';
  for (var i = 0; i < WF.stages.length; i += 1)
    h += '<option value="' + i + '"' + (MYWF.stage === i ? ' selected' : '') + '>'
      + escWf(WF.stages[i]) + '</option>';
  h += '</select></div>'""",
    """  var h = '<div class="hint" style="margin:0 0 10px">工位名（如「制作标签A」「制作标签B」）'
    + '由电脑端「工位设置」维护；同节点多个人各选自己的工位。</div>'
    + '<div class="row"><label>我的工位</label><select id="wfStPick" style="flex:1">';
  for (var i = 0; i < WF.stations.length; i += 1)
    h += '<option value="' + escWf(WF.stations[i].name) + '"'
      + (MYWF.station === WF.stations[i].name ? ' selected' : '') + '>'
      + escWf(WF.stations[i].name) + '（' + escWf(wfSName(WF.stations[i].stage))
      + '）</option>';
  h += '</select></div>'""")

rep("""  $('wfStGo').onclick = function () {
    MYWF.station = $('wfStName').value.trim();
    MYWF.stage = Number($('wfStStage').value);
    MYWF.name = $('wfStBy').value.trim();""",
    """  $('wfStGo').onclick = function () {
    MYWF.station = $('wfStPick').value;
    for (var i = 0; i < WF.stations.length; i += 1) {
      if (WF.stations[i].name === MYWF.station) MYWF.stage = WF.stations[i].stage;
    }
    MYWF.name = $('wfStBy').value.trim();""")

# 列表请求带工位
rep("  api('GET', '/m/api/wf?q=list&status=' + WF.status + '&stage=' + st).then(function (j) {",
    "  api('GET', '/m/api/wf?q=list&status=' + WF.status + '&stage=' + st\n"
    "    + '&station=' + encodeURIComponent(MYWF.station || '')).then(function (j) {")

# 行里显示交给谁
rep("        + '<div class=\"row-sub\">经手人 ' + escWf(r.handler || '—') + ' · 停留 ' + r.days",
    "        + '<div class=\"row-sub\">经手人 ' + escWf(r.handler || '—')\n"
    "        + (r.station ? ' · 交给 ' + escWf(r.station) : '') + ' · 停留 ' + r.days")

# 详情显示交给谁
rep("      + '<div class=\"row-sub\">' + escWf(w.stage_name) + '（第 ' + (w.stage + 1) + ' / '\n"
    "      + stages.length + ' 站）· 经手人 ' + escWf(w.handler || '—') + '</div>'",
    "      + '<div class=\"row-sub\">' + escWf(w.stage_name) + '（第 ' + (w.stage + 1) + ' / '\n"
    "      + stages.length + ' 站）· 交给 ' + escWf(w.station || '该节点任意人')\n"
    "      + ' · 经手人 ' + escWf(w.handler || '—') + '</div>'")

# 交给谁下拉工具
rep("function wfMoveSheet(w, stages) {",
    """function wfStationOptions(stage, cur) {
  var h = '<option value="">该节点任意人</option>';
  for (var i = 0; i < WF.stations.length; i += 1) {
    if (WF.stations[i].stage !== stage) continue;
    h += '<option value="' + escWf(WF.stations[i].name) + '"'
      + (WF.stations[i].name === cur ? ' selected' : '') + '>'
      + escWf(WF.stations[i].name) + '</option>';
  }
  return h;
}
function wfMoveSheet(w, stages) {""")

# 推进弹层加「交给谁」
rep("""  wfSheet('推进', '<div class="row-sub">推进到：' + escWf(stages[w.stage + 1]) + '</div>'
    + '<div class="row"><label>经手人</label><input id="wfBy" value="' + escWf(MYWF.name) + '"></div>'""",
    """  wfSheet('推进', '<div class="row-sub">推进到：' + escWf(stages[w.stage + 1]) + '</div>'
    + '<div class="row"><label>交给谁</label><select id="wfTo" style="flex:1">'
    + wfStationOptions(w.stage + 1, '') + '</select></div>'
    + '<div class="row"><label>经手人</label><input id="wfBy" value="' + escWf(MYWF.name) + '"></div>'""")

rep("""    api('POST', '/m/api/wf', { op: 'move', id: w.id, by: by, stage: MYWF.stage,
      note: $('wfNote').value.trim() }).then(function (j) {""",
    """    api('POST', '/m/api/wf', { op: 'move', id: w.id, by: by, stage: MYWF.stage,
      station: MYWF.station, to_station: $('wfTo').value,
      note: $('wfNote').value.trim() }).then(function (j) {""")

# 退回弹层加「交给谁」
rep("""  h += '</select></div>'
    + '<div class="row"><label>经手人</label><input id="wfBy2" value="' + escWf(MYWF.name) + '"></div>'""",
    """  h += '</select></div>'
    + '<div class="row"><label>交给谁</label><select id="wfTo2" style="flex:1">'
    + wfStationOptions(w.stage - 1, '') + '</select></div>'
    + '<div class="row"><label>经手人</label><input id="wfBy2" value="' + escWf(MYWF.name) + '"></div>'""")

rep("""    api('POST', '/m/api/wf', { op: 'back', id: w.id, by: by, stage: MYWF.stage,
      target: $('wfTgt').value, note: $('wfNote2').value.trim() }).then(function (j) {""",
    """    api('POST', '/m/api/wf', { op: 'back', id: w.id, by: by, stage: MYWF.stage,
      station: MYWF.station, to_station: $('wfTo2').value,
      target: $('wfTgt').value, note: $('wfNote2').value.trim() }).then(function (j) {""")

# 发起弹层加「发给谁」
rep("""    + '<div class="row"><label>关联编号</label><input id="crTarget"></div>'""",
    """    + '<div class="row"><label>发给谁</label><select id="crTo" style="flex:1">'
    + wfStationOptions(0, MYWF.station) + '</select></div>'
    + '<div class="row"><label>关联编号</label><input id="crTarget"></div>'""")

rep("""    api('POST', '/m/api/wf', { op: 'create', by: by, stage: MYWF.stage, title: title,
      kind: kind, target: $('crTarget').value.trim(), note: $('crNote').value.trim(),
      extra: extra }).then(function (j) {""",
    """    api('POST', '/m/api/wf', { op: 'create', by: by, stage: MYWF.stage, title: title,
      station: MYWF.station, to_station: $('crTo').value,
      kind: kind, target: $('crTarget').value.trim(), note: $('crNote').value.trim(),
      extra: extra }).then(function (j) {""")

# urgent / stock / finish 也带我的工位名
s = s.replace("        by: MYWF.name, stage: MYWF.stage }).then(function (j2) {",
              "        by: MYWF.name, stage: MYWF.stage, station: MYWF.station })"
              ".then(function (j2) {", 1)
s = s.replace("    api('POST', '/m/api/wf', { op: 'stock', id: w.id, by: by, stage: MYWF.stage,",
              "    api('POST', '/m/api/wf', { op: 'stock', id: w.id, by: by,"
              " stage: MYWF.stage, station: MYWF.station,", 1)
s = s.replace("    api('POST', '/m/api/wf', { op: 'finish', id: w.id, by: by, stage: MYWF.stage,",
              "    api('POST', '/m/api/wf', { op: 'finish', id: w.id, by: by,"
              " stage: MYWF.stage, station: MYWF.station,", 1)

io.open(p, "w", encoding="utf-8").write(s)
print("apk patched")
