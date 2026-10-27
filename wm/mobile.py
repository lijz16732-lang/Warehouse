# -*- coding: utf-8 -*-
"""手机端服务：主机内置的手机网页 + 会话管理（手机 App 的 WebView 就加载这个页面）。

安全模型（与电脑客户端同一套，再加手机专用防线）：
  · 所有请求先过 _gate —— 黑名单 / 被移除连接的手机同样拒收；
  · 登录用「连接码」换「随机会话令牌」（secrets.token_urlsafe，一次性生成），
    之后的请求只带令牌 Cookie（HttpOnly，页面脚本拿不到），连接码不再在网络上传输；
  · 会话令牌与手机 IP 绑定，换网络必须重新登录；12 小时滑动过期；
  · 登录失败限速：同一 IP 10 分钟内失败满 5 次 → 锁定 10 分钟（防连接码暴力试解）；
  · 写操作（出售登记）沿用主机「允许录入」授权：未授权的手机只读，
    可点「请求录入」，主机上弹窗审批；
  · 手机端只能调本模块固定白名单接口，不能像电脑客户端那样调任意 Store 方法；
  · 会话只存在内存里：主机关掉共享即全部下线，重启共享后手机要重新登录。
"""

import json
import secrets
import threading
import time

SESSION_TTL = 12 * 3600          # 会话 12 小时滑动过期
MAX_FAILS = 5                    # 登录失败次数上限
FAIL_WINDOW = 600.0              # 失败计数窗口（秒）
LOCKOUT = 600.0                  # 锁定时长（秒）
PAGE_LIMIT = 200                 # 列表接口单次最多返回条数
COOKIE_NAME = "cgm_session"

ITEM_FIELDS = ("id", "code", "brand", "category", "model", "condition",
               "price", "qty", "shelf", "listed", "sold_out", "remark")
SALE_FIELDS = ("id", "code", "brand", "model", "category", "qty", "price",
               "total", "buyer", "sale_date", "out_type", "remark")


def _trim(v, n=80):
    s = "" if v is None else str(v)
    return s if len(s) <= n else s[:n - 1] + "…"


class MobileService(object):
    """手机会话与手机端接口。挂在 LanServer 上（srv.mobile）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}     # token -> {"ip": str, "expires": float}
        self._fails = {}        # ip -> [失败时间戳]
        self._locked = {}       # ip -> 解锁时间

    # ------------------------------------------------------------ 会话
    def _locked_rest(self, ip):
        until = self._locked.get(ip)
        if until is None:
            return 0.0
        rest = until - time.time()
        if rest <= 0:
            del self._locked[ip]
            self._fails.pop(ip, None)
            return 0.0
        return rest

    def login(self, ip, code, code_ok):
        """登录：返回 (http_code, body, extra_headers)。code_ok 是连接码校验函数。"""
        with self._lock:
            rest = self._locked_rest(ip)
            if rest > 0:
                return 429, {"ok": False, "locked": True, "retry_after": int(rest),
                             "error": "失败次数太多，请 %d 分钟后再试" % (int(rest) // 60 + 1)}, NO_STORE
        if not code_ok(code):
            with self._lock:
                now = time.time()
                arr = [t for t in self._fails.get(ip, []) if now - t < FAIL_WINDOW]
                arr.append(now)
                self._fails[ip] = arr
                if len(arr) >= MAX_FAILS:
                    self._locked[ip] = now + LOCKOUT
                    self._fails[ip] = []
                    return 429, {"ok": False, "locked": True, "retry_after": int(LOCKOUT),
                                 "error": "连接码连续错误 %d 次，已锁定 10 分钟" % MAX_FAILS}, NO_STORE
            return 401, {"ok": False, "error": "连接码不正确"}, NO_STORE
        with self._lock:
            self._fails.pop(ip, None)
            token = secrets.token_urlsafe(32)
            self._sessions[token] = {"ip": ip, "expires": time.time() + SESSION_TTL}
        return 200, {"ok": True}, [_cookie(token)] + NO_STORE

    def check(self, token, ip):
        """会话是否有效（顺带滑动续期）。"""
        if not token:
            return False
        with self._lock:
            s = self._sessions.get(token)
            if s is None:
                return False
            now = time.time()
            if now >= s["expires"]:
                del self._sessions[token]
                return False
            if s["ip"] != ip:           # 换了网络 → 重新登录
                del self._sessions[token]
                return False
            s["expires"] = now + SESSION_TTL
            return True

    def logout(self, token):
        with self._lock:
            self._sessions.pop(token, None)

    def drop_ip(self, ip):
        """把某 IP 的手机会话全部踢下线（主机「手机下线」按钮用）。"""
        with self._lock:
            for t in [t for t, s in self._sessions.items() if s["ip"] == ip]:
                del self._sessions[t]

    def clear_all(self):
        with self._lock:
            self._sessions.clear()

    def count(self):
        with self._lock:
            now = time.time()
            for t in [t for t, s in self._sessions.items() if now >= s["expires"]]:
                del self._sessions[t]
            return len(self._sessions)

    def active_ips(self):
        with self._lock:
            now = time.time()
            return sorted({s["ip"] for s in self._sessions.values() if now < s["expires"]})


# ================================================================ 接口实现
# 每个函数返回 (http_code, body, extra_headers)；body 为 dict（JSON）或 bytes。

SECURITY_HEADERS = [
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
]

NO_STORE = [("Cache-Control", "no-store")]


def _cookie(token):
    return ("Set-Cookie",
            "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d"
            % (COOKIE_NAME, token, SESSION_TTL))


def _clear_cookie():
    return ("Set-Cookie",
            "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % COOKIE_NAME)


def _token_of(cookies):
    for part in (cookies or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE_NAME:
            return v.strip()
    return ""


def _fmt_price(v):
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        f = 0.0
    return ("%.2f" % f).rstrip("0").rstrip(".") or "0"


def handle_page():
    """GET /m —— 手机页面（登录与应用合一，由前端根据会话状态切换）。"""
    return 200, PAGE_HTML.encode("utf-8"), [
        ("Content-Type", "text/html; charset=utf-8")] + SECURITY_HEADERS


def handle_whoami(srv, ip, token):
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}, NO_STORE
    store = srv.get_store()
    try:
        rev = store.revision()
    except Exception:
        rev = 0
    try:
        wh = srv.get_warehouse() or ""
    except Exception:
        wh = ""
    return 200, {"ok": True, "warehouse": wh, "rev": rev,
                 "can_write": srv.can_write(ip), "port": srv.port}, NO_STORE


def handle_items(srv, ip, token, query):
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}, NO_STORE
    kw = (query.get("kw") or "").strip().lower()
    try:
        rows = srv.get_store().all_records()
    except Exception as e:
        return 500, {"ok": False, "error": "读取库存失败：%s" % e}, NO_STORE
    if kw:
        def hit(r):
            return any(kw in str(r.get(f) or "").lower()
                       for f in ("code", "brand", "category", "model", "shelf", "remark"))
        rows = [r for r in rows if hit(r)]
    rows.sort(key=lambda r: (int(r.get("sold_out") or 0), str(r.get("code") or "")))
    out = []
    for r in rows[:PAGE_LIMIT]:
        out.append({k: r.get(k) for k in ITEM_FIELDS})
        out[-1]["remark"] = _trim(out[-1]["remark"], 60)
        out[-1]["price"] = _fmt_price(out[-1]["price"])
    return 200, {"ok": True, "total": len(rows), "items": out}, NO_STORE


def handle_sales(srv, ip, token, query):
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}, NO_STORE
    kw = (query.get("kw") or "").strip()
    try:
        rows = srv.get_store().list_sales(kw=kw)[:PAGE_LIMIT]
    except Exception as e:
        return 500, {"ok": False, "error": "读取出售记录失败：%s" % e}, NO_STORE
    out = []
    for r in rows:
        d = {k: r.get(k) for k in SALE_FIELDS}
        d["price"] = _fmt_price(d["price"])
        d["total"] = _fmt_price(d["total"])
        d["remark"] = _trim(d["remark"], 60)
        out.append(d)
    return 200, {"ok": True, "sales": out}, NO_STORE


def handle_sell(srv, ip, token, payload):
    """出售登记：需要主机已授权该手机所在电脑/设备「允许录入」。"""
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}, NO_STORE
    if not srv.can_write(ip):
        return 403, {"ok": False, "readonly": True,
                     "error": "主机未授权录入（只读模式），可点「请求录入」向主机申请"}, NO_STORE
    code = str((payload or {}).get("code") or "").strip()
    if not code:
        return 400, {"ok": False, "error": "请填写商品编号"}, NO_STORE
    store = srv.get_store()
    try:
        item_id = store.find_by_code(code)
    except Exception as e:
        return 500, {"ok": False, "error": "查询失败：%s" % e}, NO_STORE
    if not item_id:
        return 404, {"ok": False, "error": "没有找到编号 %s 的商品" % code}, NO_STORE
    p = payload or {}
    try:
        ok, msg = store.add_sale(item_id, p.get("qty"), p.get("price"),
                                 buyer=str(p.get("buyer") or "")[:40],
                                 remark=str(p.get("remark") or "")[:120],
                                 address=str(p.get("address") or "")[:120])
    except Exception as e:
        return 500, {"ok": False, "error": "登记失败：%s" % e}, NO_STORE
    return (200 if ok else 400), {"ok": ok, "error": None if ok else msg,
                                  "message": msg}, NO_STORE


def handle_request_write(srv, ip, token):
    """请求录入权限：复用电脑客户端的审批流程（主机上弹窗询问）。"""
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}, NO_STORE
    if srv.can_write(ip):
        return 200, {"ok": True, "already": True}, NO_STORE
    c = srv._touch(ip, "手机", "mobile-" + ip)
    with srv._lock:
        c["requests"] = int(c.get("requests") or 0) + 1
    srv.on_event("request", {"ip": ip, "name": "手机（%s）" % ip})
    return 200, {"ok": True}, NO_STORE


def handle_logout(srv, ip, token):
    srv.mobile.logout(token)
    return 200, {"ok": True}, [_clear_cookie()]


# ================================================================ 手机页面
# 单文件、无外部依赖（局域网里未必有互联网）：原生 JS + 内联 CSS。

PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#1f6feb">
<title>仓管家</title>
<style>
:root { --bg:#f4f6fa; --card:#fff; --line:#e3e8f0; --txt:#1c2333; --mut:#8a94a6;
        --acc:#1f6feb; --ok:#18a058; --warn:#e8890c; --bad:#d4380d; }
* { box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent; }
body { background:var(--bg); color:var(--txt);
       font:15px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
header { background:var(--acc); color:#fff; padding:14px 16px 12px;
         padding-top:calc(14px + env(safe-area-inset-top)); }
header h1 { font-size:18px; display:inline; }
header .wh { font-size:12px; opacity:.85; margin-left:8px; }
#badge { float:right; font-size:11px; padding:2px 8px; border-radius:10px; background:rgba(255,255,255,.25); }
nav { display:flex; background:var(--card); border-bottom:1px solid var(--line);
      position:sticky; top:0; z-index:5; }
nav button { flex:1; border:0; background:none; padding:11px 0; font-size:15px; color:var(--mut); }
nav button.on { color:var(--acc); font-weight:600; box-shadow:inset 0 -2px 0 var(--acc); }
main { padding:12px 12px 40px; }
.srch { display:flex; gap:8px; margin-bottom:10px; }
.srch input { flex:1; border:1px solid var(--line); border-radius:10px; padding:9px 12px; font-size:15px; background:var(--card); }
.srch button { border:0; border-radius:10px; background:var(--acc); color:#fff; padding:0 18px; font-size:15px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; margin-bottom:10px; }
.card .t { font-weight:600; font-size:15px; }
.card .t .sold { color:#fff; background:var(--warn); font-size:11px; border-radius:8px; padding:1px 6px; margin-left:6px; font-weight:400; }
.card .row { display:flex; flex-wrap:wrap; gap:4px 14px; color:var(--mut); font-size:13px; margin-top:4px; }
.card .row b { color:var(--txt); font-weight:500; }
.price { color:var(--bad); font-weight:600; }
.empty { text-align:center; color:var(--mut); padding:40px 0; }
.notice { background:#fff7e6; border:1px solid #ffe0a3; color:#8a5a00; font-size:13px;
          border-radius:10px; padding:10px 12px; margin-bottom:10px; }
form.sell label { display:block; font-size:13px; color:var(--mut); margin:10px 0 4px; }
form.sell input { width:100%; border:1px solid var(--line); border-radius:10px; padding:10px 12px; font-size:15px; background:var(--card); }
form.sell .go { width:100%; border:0; border-radius:12px; background:var(--acc); color:#fff; padding:12px; font-size:16px; margin-top:16px; }
form.sell .go:disabled { background:#a9c4f2; }
.link { color:var(--acc); background:none; border:0; font-size:13px; padding:6px 0; text-decoration:underline; }
#toast { position:fixed; left:50%; bottom:60px; transform:translateX(-50%); background:rgba(28,35,51,.92);
         color:#fff; padding:10px 18px; border-radius:20px; font-size:14px; max-width:86%; display:none; z-index:99; }
#login { max-width:420px; margin:16vh auto 0; padding:0 24px; text-align:center; }
#login .logo { font-size:44px; }
#login h2 { margin:8px 0 4px; }
#login p { color:var(--mut); font-size:13px; margin-bottom:22px; }
#login input { width:100%; border:1px solid var(--line); border-radius:12px; padding:13px 14px;
               font-size:20px; text-align:center; letter-spacing:4px; background:var(--card); }
#login button { width:100%; border:0; border-radius:12px; background:var(--acc); color:#fff;
                padding:13px; font-size:16px; margin-top:14px; }
#login .err { color:var(--bad); font-size:13px; min-height:20px; margin-top:10px; }
footer { text-align:center; color:var(--mut); font-size:11px; padding:20px 0 max(20px, env(safe-area-inset-bottom)); }
footer a { color:var(--mut); }
</style>
</head>
<body>

<div id="login">
  <div class="logo">📦</div>
  <h2>仓管家 · 手机端</h2>
  <p>输入电脑上「局域网共享」里显示的连接码</p>
  <input id="code" type="text" inputmode="numeric" autocomplete="off" placeholder="连接码">
  <button id="btnLogin">进入</button>
  <div class="err" id="loginErr"></div>
</div>

<div id="app" style="display:none">
<header><h1>📦 仓管家</h1><span class="wh" id="wh"></span><span id="badge"></span></header>
<nav>
  <button data-p="items" class="on">库存</button>
  <button data-p="sales">出售记录</button>
  <button data-p="sell">登记出售</button>
</nav>
<main>
  <div id="p_items">
    <div class="srch"><input id="kwItems" placeholder="搜编号 / 品牌 / 型号 / 货架"><button id="goItems">搜索</button></div>
    <div id="listItems"><div class="empty">加载中…</div></div>
  </div>
  <div id="p_sales" style="display:none">
    <div class="srch"><input id="kwSales" placeholder="搜编号 / 买家 / 备注"><button id="goSales">搜索</button></div>
    <div id="listSales"><div class="empty">加载中…</div></div>
  </div>
  <div id="p_sell" style="display:none">
    <div class="notice" id="sellNotice" style="display:none"></div>
    <form class="sell" id="sellForm" onsubmit="return false">
      <label>商品编号（如 WL-00001）</label>
      <input id="sCode" placeholder="WL-00001">
      <label>数量</label>
      <input id="sQty" type="number" inputmode="numeric" value="1" min="1">
      <label>单价（元）</label>
      <input id="sPrice" type="number" inputmode="decimal" placeholder="0.00">
      <label>买家（可选）</label>
      <input id="sBuyer" placeholder="">
      <label>收货地址（可选）</label>
      <input id="sAddr" placeholder="">
      <label>备注（可选）</label>
      <input id="sRemark" placeholder="">
      <button class="go" id="btnSell">登记出售</button>
      <button class="link" id="btnAsk" type="button" style="display:none">主机未授权录入？点此申请权限</button>
    </form>
  </div>
</main>
<footer><a href="javascript:logout()">退出登录</a> · 仓管家手机端</footer>
</div>
<div id="toast"></div>

<script>
var $ = function(id){ return document.getElementById(id); };
var CAN_WRITE = false;

function toast(msg, ms){
  var t = $("toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(function(){ t.style.display = "none"; }, ms || 2200);
}
function api(path, opts, cb){
  opts = opts || {}; opts.credentials = "same-origin";
  opts.headers = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
  fetch(path, opts).then(function(r){
    if (r.status === 401) { showLogin(); throw new Error("need_login"); }
    return r.json();
  }).then(function(b){ cb(b); })
    .catch(function(e){ if (e.message !== "need_login") toast("网络错误，请确认与电脑连着同一 WiFi"); });
}
function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"]/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]; });
}
function showLogin(){
  $("app").style.display = "none"; $("login").style.display = "block";
  $("code").value = ""; $("loginErr").textContent = "";
}
function showApp(){
  $("login").style.display = "none"; $("app").style.display = "block";
  refreshWho(); goPage("items");
}
function refreshWho(){
  api("/m/api/whoami", {}, function(b){
    if (!b.ok) return;
    $("wh").textContent = b.warehouse ? " · " + b.warehouse : "";
    CAN_WRITE = !!b.can_write;
    $("badge").textContent = CAN_WRITE ? "可录入" : "只读";
    $("badge").style.background = CAN_WRITE ? "rgba(24,160,88,.85)" : "rgba(255,255,255,.25)";
    $("sellNotice").style.display = CAN_WRITE ? "none" : "block";
    $("sellNotice").textContent = "当前为只读：可查看库存和出售记录；登记出售需要主机在「局域网共享」里允许录入。";
    $("btnAsk").style.display = CAN_WRITE ? "none" : "inline";
    $("btnSell").disabled = !CAN_WRITE;
  });
}
/* ---- 登录 ---- */
$("btnLogin").onclick = function(){
  var code = $("code").value.trim();
  if (!code) { $("loginErr").textContent = "请输入连接码"; return; }
  $("btnLogin").disabled = true;
  fetch("/m/login", {method:"POST", credentials:"same-origin",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({code: code})})
  .then(function(r){ return r.json(); })
  .then(function(b){
    $("btnLogin").disabled = false;
    if (b.ok) { showApp(); }
    else { $("loginErr").textContent = b.error || "登录失败"; }
  })
  .catch(function(){ $("btnLogin").disabled = false; $("loginErr").textContent = "网络错误，请确认与电脑连着同一 WiFi"; });
};
$("code").addEventListener("keydown", function(e){ if (e.key === "Enter") $("btnLogin").click(); });
function logout(){
  api("/m/logout", {method:"POST"}, function(){ showLogin(); });
}
/* ---- 页签 ---- */
var pages = ["items", "sales", "sell"];
function goPage(p){
  pages.forEach(function(x){
    $("p_" + x).style.display = (x === p) ? "" : "none";
  });
  var bs = document.querySelectorAll("nav button");
  for (var i = 0; i < bs.length; i++) bs[i].className = (bs[i].getAttribute("data-p") === p) ? "on" : "";
  if (p === "items") loadItems();
  if (p === "sales") loadSales();
  if (p === "sell") refreshWho();
}
(function(){
  var bs = document.querySelectorAll("nav button");
  for (var i = 0; i < bs.length; i++) bs[i].onclick = function(){ goPage(this.getAttribute("data-p")); };
})();
/* ---- 库存 ---- */
function loadItems(){
  $("listItems").innerHTML = '<div class="empty">加载中…</div>';
  api("/m/api/items?kw=" + encodeURIComponent($("kwItems").value.trim()), {}, function(b){
    if (!b.ok) { $("listItems").innerHTML = '<div class="empty">' + esc(b.error) + "</div>"; return; }
    if (!b.items.length) { $("listItems").innerHTML = '<div class="empty">没有找到匹配的商品</div>'; return; }
    var h = "";
    b.items.forEach(function(r){
      h += '<div class="card"><div class="t">' + esc(r.code) +
           (r.sold_out ? ' <span class="sold">已售完</span>' : "") + "</div>" +
           '<div class="row"><span>品牌 <b>' + esc(r.brand || "-") + "</b></span>" +
           "<span>品类 <b>" + esc(r.category || "-") + "</b></span>" +
           "<span>型号 <b>" + esc(r.model || "-") + "</b></span></div>" +
           '<div class="row"><span>数量 <b>' + esc(r.qty) + "</b></span>" +
           '<span class="price">¥<b>' + esc(r.price || "0") + "</b></span>" +
           "<span>货架 <b>" + esc(r.shelf || "-") + "</b></span>" +
           "<span>成色 <b>" + esc(r.condition || "-") + "</b></span></div>" +
           (r.remark ? '<div class="row"><span>' + esc(r.remark) + "</span></div>" : "") +
           "</div>";
    });
    $("listItems").innerHTML = h;
  });
}
$("goItems").onclick = loadItems;
$("kwItems").addEventListener("keydown", function(e){ if (e.key === "Enter") loadItems(); });
/* ---- 出售记录 ---- */
function loadSales(){
  $("listSales").innerHTML = '<div class="empty">加载中…</div>';
  api("/m/api/sales?kw=" + encodeURIComponent($("kwSales").value.trim()), {}, function(b){
    if (!b.ok) { $("listSales").innerHTML = '<div class="empty">' + esc(b.error) + "</div>"; return; }
    if (!b.sales.length) { $("listSales").innerHTML = '<div class="empty">暂无出售记录</div>'; return; }
    var h = "";
    b.sales.forEach(function(r){
      h += '<div class="card"><div class="t">' + esc(r.code) + " × " + esc(r.qty) +
           ' <span style="color:var(--mut);font-size:12px;font-weight:400">' + esc(r.sale_date || "") +
           " · " + esc(r.out_type || "销售") + "</span></div>" +
           '<div class="row"><span>品牌 <b>' + esc(r.brand || "-") + "</b></span>" +
           "<span>型号 <b>" + esc(r.model || "-") + "</b></span>" +
           '<span class="price">¥<b>' + esc(r.total || "0") + "</b></span>" +
           "<span>买家 <b>" + esc(r.buyer || "-") + "</b></span></div>" +
           (r.remark ? '<div class="row"><span>' + esc(r.remark) + "</span></div>" : "") +
           "</div>";
    });
    $("listSales").innerHTML = h;
  });
}
$("goSales").onclick = loadSales;
$("kwSales").addEventListener("keydown", function(e){ if (e.key === "Enter") loadSales(); });
/* ---- 登记出售 ---- */
$("btnSell").onclick = function(){
  if (!CAN_WRITE) { toast("只读模式：请先向主机申请录入权限"); return; }
  var code = $("sCode").value.trim();
  if (!code) { toast("请填写商品编号"); return; }
  $("btnSell").disabled = true;
  api("/m/api/sell", {method:"POST", body: JSON.stringify({
      code: code, qty: $("sQty").value, price: $("sPrice").value,
      buyer: $("sBuyer").value.trim(), address: $("sAddr").value.trim(),
      remark: $("sRemark").value.trim()})}, function(b){
    $("btnSell").disabled = false;
    if (b.ok) { toast(b.message || "已登记", 3000);
      $("sCode").value = ""; $("sQty").value = "1"; $("sPrice").value = "";
      $("sBuyer").value = ""; $("sAddr").value = ""; $("sRemark").value = "";
    } else { toast(b.error || "登记失败", 3000); }
  });
};
$("btnAsk").onclick = function(){
  api("/m/api/request_write", {method:"POST"}, function(b){
    if (b.ok) { toast(b.already ? "已有录入权限" : "已向主机发送申请，请主机在电脑上确认", 3000); refreshWho(); }
    else toast(b.error || "申请失败", 3000);
  });
};
/* ---- 启动：有会话直接进应用 ---- */
api("/m/api/whoami", {}, function(b){ if (b.ok) showApp(); else showLogin(); });
</script>
</body>
</html>
"""
