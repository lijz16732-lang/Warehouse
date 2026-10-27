# -*- coding: utf-8 -*-
"""手机端服务：主机内置的手机网页 + 会话管理（手机 App 的 WebView 就加载这个页面）。

安全模型（与电脑客户端同一套，再加手机专用防线）：
  · 所有请求先过 _gate —— 黑名单 / 被移除连接的手机同样拒收；
  · 登录用「连接码」换「随机会话令牌」（secrets.token_urlsafe，一次性生成），
    之后的请求只带令牌 Cookie（HttpOnly，页面脚本拿不到），连接码不再在网络上传输；
  · 会话令牌与手机 IP 绑定，换网络必须重新登录；12 小时滑动过期；
  · 登录失败限速：同一 IP 10 分钟内失败满 5 次 → 锁定 10 分钟（防连接码暴力试解）；
  · 写操作（新增 / 修改 / 出售登记）沿用主机「允许录入」授权：未授权的手机只读，
    可点「申请权限」，主机上弹窗审批；
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
# 手机端「新增 / 修改」允许写的字段（编号自动生成，不允许改 deleted_at 等）
EDIT_FIELDS = ("brand", "category", "model", "condition",
               "price", "qty", "shelf", "listed", "remark")
_EDIT_LEN = {"brand": 40, "category": 40, "model": 120, "condition": 20,
             "shelf": 120, "remark": 200}


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

    def login(self, ip, code, code_ok, app_mode=False):
        """登录：返回 (http_code, body, extra_headers)。code_ok 是连接码校验函数。

        app_mode=True（APK 自带页面）时在响应体里附带令牌 —— 本地页面向主机
        发跨源请求带不了 Cookie，App 把令牌存本地、用 X-MToken 头携带。
        """
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
            self._sessions[token] = {"ip": ip, "expires": time.time() + SESSION_TTL,
                                     "app": bool(app_mode)}
        body = {"ok": True}
        if app_mode:
            body["token"] = token
        return 200, body, [_cookie(token)] + NO_STORE

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

    def is_app(self, token):
        """该会话是否来自 APK（app:1 登录）。App 的数据同步写入手机数据区。"""
        with self._lock:
            s = self._sessions.get(token)
            return bool(s and s.get("app"))

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


MTOKEN_HEADER = "X-MToken"


def _token_from(headers):
    """从请求里取会话令牌：优先 X-MToken 头（App 自带页面用，浏览器页面用 Cookie）。

    App 的界面打包在 APK 本地（file://），向主机发跨源请求时浏览器 SameSite
    策略不会带 Cookie，所以 App 登录后把令牌存在本地、放在这个头里传来。
    令牌本身仍是主机签发的随机会话令牌，安全模型不变。
    """
    t = (headers.get(MTOKEN_HEADER) or "").strip()
    if t:
        return t
    return _token_of(headers.get("Cookie") or "")


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
        d = {k: r.get(k) for k in ITEM_FIELDS}
        d["remark"] = _trim(d["remark"], 60)
        d["price"] = _fmt_price(d["price"])
        out.append(d)
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


def handle_coltitles(srv, ip, token, payload=None):
    """GET/POST /m/api/coltitles —— 表格列题自定义（电脑端与手机端共享一份）。

    GET  → {"ok":True, "titles": {字段: 当前标题}}（含默认标题，App 直接用）
    POST → {"titles": {字段: 新标题}} 保存；值为空 = 恢复默认。
    保存属于写操作（电脑端表头同步变化），需主机「允许录入」授权。
    """
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}, NO_STORE
    from .constants import FIELD_LABEL
    store = srv.get_store()
    if payload is None:                       # GET
        custom = store.col_titles()
        titles = {f: custom.get(f) or FIELD_LABEL[f] for f in FIELD_LABEL}
        return 200, {"ok": True, "titles": titles, "custom": custom}, NO_STORE
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], dict(gate[1], readonly=True), NO_STORE
    titles = (payload or {}).get("titles")
    if not isinstance(titles, dict):
        return 400, {"ok": False, "error": "参数不正确（titles 必须是对象）"}, NO_STORE
    try:
        store.set_col_titles(titles)
    except Exception as e:
        return 500, {"ok": False, "error": "保存列题失败：%s" % e}, NO_STORE
    custom = store.col_titles()
    all_titles = {f: custom.get(f) or FIELD_LABEL[f] for f in FIELD_LABEL}
    return 200, {"ok": True, "message": "列题已保存，电脑端同步生效",
                 "titles": all_titles, "custom": custom}, NO_STORE


def _need_write(srv, ip, token):
    """公共前置检查：返回 (None) 或 (http_code, body)。"""
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}
    if not srv.can_write(ip):
        return 403, {"ok": False, "readonly": True,
                     "error": "主机未授权录入（只读模式），可点「申请权限」向主机申请"}
    return None


def handle_add(srv, ip, token, payload):
    """新增一条库存记录：编号自动生成（与电脑端同一套编号规则）。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    p = payload or {}
    rec = {}
    for k in EDIT_FIELDS:
        v = p.get(k)
        if k in _EDIT_LEN:
            rec[k] = str(v or "").strip()[:_EDIT_LEN[k]]
        elif k == "price":
            try:
                rec[k] = float(v or 0)
            except (TypeError, ValueError):
                rec[k] = 0.0
        elif k == "qty":
            try:
                rec[k] = int(float(v or 0))
            except (TypeError, ValueError):
                rec[k] = 0
        elif k == "listed":
            rec[k] = 1 if v in (1, True, "1", "是") else 0
    if not any(rec.get(k) for k in ("brand", "model", "category")):
        return 400, {"ok": False, "error": "品牌 / 型号 / 品类 至少填一个"}, NO_STORE
    store = srv.get_store()
    try:
        codes = store.generate_codes(1)
        rec["code"] = codes[0]
        rid = store.insert(rec)
    except Exception as e:
        return 500, {"ok": False, "error": "保存失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "id": rid, "code": rec["code"],
                 "message": "已入库，编号 %s" % rec["code"]}, NO_STORE


def handle_update(srv, ip, token, payload):
    """修改一条记录的指定字段（字段白名单内的才能改）。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    p = payload or {}
    try:
        rid = int(p.get("id") or 0)
    except (TypeError, ValueError):
        rid = 0
    field = str(p.get("field") or "").strip()
    if rid <= 0 or field not in EDIT_FIELDS:
        return 400, {"ok": False, "error": "参数不正确（字段不允许修改）"}, NO_STORE
    value = p.get("value")
    if field in _EDIT_LEN:
        value = str(value if value is not None else "").strip()[:_EDIT_LEN[field]]
    elif field == "price":
        try:
            value = float(value or 0)
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "价格格式不正确"}, NO_STORE
    elif field == "qty":
        try:
            value = int(float(value or 0))
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "数量格式不正确"}, NO_STORE
    elif field == "listed":
        value = 1 if value in (1, True, "1", "是") else 0
    store = srv.get_store()
    try:
        if not any(r.get("id") == rid for r in store.all_records()):
            return 404, {"ok": False, "error": "记录不存在（可能已被删除）"}, NO_STORE
        store.update_field(rid, field, value)
    except Exception as e:
        return 500, {"ok": False, "error": "保存失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "message": "已保存"}, NO_STORE


def handle_update_all(srv, ip, token, payload):
    """整条保存（手机「修改」表单）：先取原记录合并，编号等不可改字段原样保留。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    p = payload or {}
    try:
        rid = int(p.get("id") or 0)
    except (TypeError, ValueError):
        rid = 0
    if rid <= 0:
        return 400, {"ok": False, "error": "参数不正确"}, NO_STORE
    store = srv.get_store()
    try:
        rec = None
        for r in store.all_records():
            if r.get("id") == rid:
                rec = dict(r)
                break
        if rec is None:
            return 404, {"ok": False, "error": "记录不存在（可能已被删除）"}, NO_STORE
        for k in EDIT_FIELDS:
            v = p.get(k)
            if k in _EDIT_LEN:
                rec[k] = str(v if v is not None else rec.get(k) or "").strip()[:_EDIT_LEN[k]]
            elif k == "price":
                try:
                    rec[k] = float(v if v not in (None, "") else rec.get(k) or 0)
                except (TypeError, ValueError):
                    return 400, {"ok": False, "error": "价格格式不正确"}, NO_STORE
            elif k == "qty":
                try:
                    rec[k] = int(float(v if v not in (None, "") else rec.get(k) or 0))
                except (TypeError, ValueError):
                    return 400, {"ok": False, "error": "数量格式不正确"}, NO_STORE
            # listed 手机表单暂不提供，保持原值
        store.update(rid, rec)
    except Exception as e:
        return 500, {"ok": False, "error": "保存失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "message": "已保存"}, NO_STORE


def handle_sell(srv, ip, token, payload):
    """出售登记：需要主机已授权该手机所在电脑/设备「允许录入」。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
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


# ---------------------------------------------------------------- 手机数据区
# App 同步的记录写入 phone_items / phone_sales（电脑端「手机数据」页查看管理），
# 绝不写主库存；需要主机「允许录入」授权，和其它写接口同一套安全模型。

_M_EDIT_LEN = {"brand": 40, "category": 40, "model": 120, "condition": 20,
               "shelf": 120, "remark": 200, "code": 40}


def _m_str(p, k, n=None):
    v = p.get(k)
    return str(v if v is not None else "").strip()[:(n or _M_EDIT_LEN.get(k, 120))]


def _m_int(p, k):
    try:
        return int(float(p.get(k) or 0))
    except (TypeError, ValueError):
        return 0


def _m_float(p, k):
    try:
        return float(p.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def handle_m_item(srv, ip, token, payload):
    """App 商品同步（按手机本地 id 覆盖保存）。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    p = payload or {}
    lid = _m_int(p, "lid")
    if lid <= 0:
        return 400, {"ok": False, "error": "缺少商品本地编号"}, NO_STORE
    rec = {"lid": lid}
    for k in ("code", "brand", "category", "model", "condition", "shelf", "remark"):
        rec[k] = _m_str(p, k)
    rec["price"] = _m_float(p, "price")
    rec["qty"] = max(0, _m_int(p, "qty"))
    rec["listed"] = 1 if p.get("listed") in (1, True, "1", "是") else 0
    rec["sold_out"] = 1 if p.get("sold_out") in (1, True, "1", "是") else 0
    if not any(rec.get(k) for k in ("brand", "model", "category")):
        return 400, {"ok": False, "error": "品牌 / 型号 / 品类 至少填一个"}, NO_STORE
    store = srv.get_store()
    try:
        store.m_upsert_item(rec)
    except Exception as e:
        return 500, {"ok": False, "error": "同步失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "message": "已同步到电脑「手机数据」"}, NO_STORE


def handle_m_sale(srv, ip, token, payload):
    """App 出售记录同步（幂等，按手机本地 id 覆盖保存；不在电脑端重复扣库存）。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    p = payload or {}
    lid = _m_int(p, "lid")
    if lid <= 0:
        return 400, {"ok": False, "error": "缺少记录本地编号"}, NO_STORE
    qty = _m_int(p, "qty")
    if qty <= 0:
        return 400, {"ok": False, "error": "出售数量至少 1"}, NO_STORE
    rec = {"lid": lid, "item_lid": _m_int(p, "item_lid"), "code": _m_str(p, "code"),
           "brand": _m_str(p, "brand"), "category": _m_str(p, "category"),
           "model": _m_str(p, "model"), "qty": qty, "price": _m_float(p, "price"),
           "total": _m_float(p, "total") or round(qty * _m_float(p, "price"), 2),
           "buyer": _m_str(p, "buyer"), "sale_date": _m_str(p, "sale_date", 20),
           "out_type": _m_str(p, "out_type", 20) or "出售",
           "remark": _m_str(p, "remark")}
    store = srv.get_store()
    try:
        store.m_upsert_sale(rec)
    except Exception as e:
        return 500, {"ok": False, "error": "同步失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "message": "出售记录已同步到电脑「手机数据」"}, NO_STORE


def handle_logout(srv, ip, token):
    srv.mobile.logout(token)
    return 200, {"ok": True}, [_clear_cookie()]


# ================================================================ 手机页面
# 单文件、无外部依赖（局域网里未必有互联网）：原生 JS + 内联 CSS。
# 注意：本字符串里不允许出现反斜杠（tests 有断言）——Python 会把 JS 的转义吃掉。

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
nav button { flex:1; border:0; background:none; padding:11px 0; font-size:14px; color:var(--mut); }
nav button.on { color:var(--acc); font-weight:600; box-shadow:inset 0 -2px 0 var(--acc); }
main { padding:12px 12px 40px; }
.srch { display:flex; gap:8px; margin-bottom:10px; }
.srch input { flex:1; border:1px solid var(--line); border-radius:10px; padding:9px 12px; font-size:15px; background:var(--card); }
.srch button { border:0; border-radius:10px; background:var(--acc); color:#fff; padding:0 18px; font-size:15px; }
.tblwrap { overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:12px; }
table { border-collapse:collapse; min-width:720px; width:100%; font-size:13px; }
th, td { border-bottom:1px solid var(--line); padding:9px 10px; text-align:left; white-space:nowrap; }
th { background:#eef2f8; color:#5a6478; font-weight:600; position:sticky; top:0; }
tr:last-child td { border-bottom:0; }
tbody tr:active { background:#eef4ff; }
td .sold { color:#fff; background:var(--warn); font-size:10px; border-radius:8px; padding:1px 6px; }
td.num { text-align:right; }
td.price { color:var(--bad); font-weight:600; }
.tblhint { color:var(--mut); font-size:12px; margin:6px 2px 0; }
.empty { text-align:center; color:var(--mut); padding:40px 0; }
.notice { background:#fff7e6; border:1px solid #ffe0a3; color:#8a5a00; font-size:13px;
          border-radius:10px; padding:10px 12px; margin-bottom:10px; }
form.mform label { display:block; font-size:13px; color:var(--mut); margin:10px 0 4px; }
form.mform input { width:100%; border:1px solid var(--line); border-radius:10px; padding:10px 12px; font-size:15px; background:var(--card); }
form.mform .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:0 12px; }
form.mform .go { width:100%; border:0; border-radius:12px; background:var(--acc); color:#fff; padding:12px; font-size:16px; margin-top:16px; }
form.mform .go:disabled { background:#a9c4f2; }
.card-title { font-weight:600; font-size:15px; margin:4px 2px 10px; }
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
  <button data-p="entry">录入</button>
  <button data-p="sell">出售</button>
  <button data-p="sales">记录</button>
</nav>
<main>
  <div id="p_items">
    <div class="srch"><input id="kwItems" placeholder="搜编号 / 品牌 / 型号 / 货架"><button id="goItems">搜索</button></div>
    <div class="tblwrap"><table>
      <thead><tr><th>编号</th><th>品牌</th><th>型号</th><th>数量</th><th>价格</th><th>货架</th></tr></thead>
      <tbody id="listItems"><tr><td colspan="6" class="empty">加载中…</td></tr></tbody>
    </table></div>
    <div class="tblhint">点一行可修改该商品的数量 / 价格 / 货架等；只读模式只能看。</div>
  </div>
  <div id="p_entry" style="display:none">
    <div class="notice" id="entryNotice" style="display:none"></div>
    <div class="card-title" id="entryTitle">＋ 新增入库</div>
    <form class="mform" id="entryForm" onsubmit="return false">
      <input type="hidden" id="eId" value="">
      <div class="grid2">
        <div><label>品牌</label><input id="eBrand" placeholder="如 ABB"></div>
        <div><label>品类</label><input id="eCategory" placeholder="如 断路器"></div>
        <div><label>型号</label><input id="eModel" placeholder=""></div>
        <div><label>成色</label><input id="eCondition" placeholder="如 全新 / 99新"></div>
        <div><label>单价（元）</label><input id="ePrice" type="number" inputmode="decimal" placeholder="0.00"></div>
        <div><label>数量</label><input id="eQty" type="number" inputmode="numeric" value="1" min="0"></div>
      </div>
      <label>货架</label><input id="eShelf" placeholder="如 6排A-3">
      <label>备注</label><input id="eRemark" placeholder="">
      <button class="go" id="btnSaveEntry">保存入库</button>
      <button class="link" id="btnResetEntry" type="button">清空，重新新增</button>
      <button class="link" id="btnAskEntry" type="button" style="display:none">主机未授权录入？点此申请权限</button>
    </form>
  </div>
  <div id="p_sell" style="display:none">
    <div class="notice" id="sellNotice" style="display:none"></div>
    <form class="mform" id="sellForm" onsubmit="return false">
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
  <div id="p_sales" style="display:none">
    <div class="srch"><input id="kwSales" placeholder="搜编号 / 买家 / 备注"><button id="goSales">搜索</button></div>
    <div class="tblwrap"><table>
      <thead><tr><th>日期</th><th>编号</th><th>品牌</th><th>型号</th><th>数量</th><th>合计</th><th>买家</th><th>类型</th></tr></thead>
      <tbody id="listSales"><tr><td colspan="8" class="empty">加载中…</td></tr></tbody>
    </table></div>
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
  return String(s == null ? "" : s).replace(/[&<>]/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;"}[c]; });
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
    $("sellNotice").textContent = "当前为只读：可查看库存和记录；登记出售需要主机在「局域网共享」里允许录入。";
    $("entryNotice").style.display = CAN_WRITE ? "none" : "block";
    $("entryNotice").textContent = "当前为只读：不能新增或修改数据；点下面「申请权限」由主机确认。";
    $("btnAsk").style.display = CAN_WRITE ? "none" : "inline";
    $("btnAskEntry").style.display = CAN_WRITE ? "none" : "inline";
    $("btnSell").disabled = !CAN_WRITE;
    $("btnSaveEntry").disabled = !CAN_WRITE;
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
var pages = ["items", "entry", "sell", "sales"];
function goPage(p){
  pages.forEach(function(x){
    $("p_" + x).style.display = (x === p) ? "" : "none";
  });
  var bs = document.querySelectorAll("nav button");
  for (var i = 0; i < bs.length; i++) bs[i].className = (bs[i].getAttribute("data-p") === p) ? "on" : "";
  if (p === "items") loadItems();
  if (p === "sales") loadSales();
  if (p === "sell" || p === "entry") refreshWho();
}
(function(){
  var bs = document.querySelectorAll("nav button");
  for (var i = 0; i < bs.length; i++) bs[i].onclick = function(){ goPage(this.getAttribute("data-p")); };
})();
/* ---- 库存表格 ---- */
function loadItems(){
  $("listItems").innerHTML = '<tr><td colspan="6" class="empty">加载中…</td></tr>';
  api("/m/api/items?kw=" + encodeURIComponent($("kwItems").value.trim()), {}, function(b){
    if (!b.ok) { $("listItems").innerHTML = '<tr><td colspan="6" class="empty">' + esc(b.error) + "</td></tr>"; return; }
    if (!b.items.length) { $("listItems").innerHTML = '<tr><td colspan="6" class="empty">没有找到匹配的商品</td></tr>'; return; }
    var h = "";
    b.items.forEach(function(r){
      h += '<tr data-id="' + esc(r.id) + '" data-code="' + esc(r.code) + '">'
         + "<td>" + esc(r.code) + (r.sold_out ? ' <span class="sold">售完</span>' : "") + "</td>"
         + "<td>" + esc(r.brand || "-") + "</td>"
         + "<td>" + esc(r.model || "-") + "</td>"
         + '<td class="num">' + esc(r.qty) + "</td>"
         + '<td class="num price">' + esc(r.price || "0") + "</td>"
         + "<td>" + esc(r.shelf || "-") + "</td></tr>";
    });
    $("listItems").innerHTML = h;
    var rows = document.querySelectorAll("#listItems tr");
    for (var i = 0; i < rows.length; i++) {
      rows[i].onclick = function(){ openEdit(this.getAttribute("data-id")); };
    }
  });
}
$("goItems").onclick = loadItems;
$("kwItems").addEventListener("keydown", function(e){ if (e.key === "Enter") loadItems(); });
/* ---- 编辑 / 新增 ---- */
function openEdit(id){
  api("/m/api/items?kw=", {}, function(b){
    if (!b.ok) { toast(b.error || "读取失败"); return; }
    var rec = null;
    for (var i = 0; i < b.items.length; i++) { if (String(b.items[i].id) === String(id)) { rec = b.items[i]; break; } }
    if (!rec) { toast("记录不存在"); return; }
    $("eId").value = rec.id;
    $("entryTitle").textContent = "修改 " + rec.code + "（编号不可改）";
    $("eBrand").value = rec.brand || "";
    $("eCategory").value = rec.category || "";
    $("eModel").value = rec.model || "";
    $("eCondition").value = rec.condition || "";
    $("ePrice").value = rec.price || "";
    $("eQty").value = rec.qty;
    $("eShelf").value = rec.shelf || "";
    $("eRemark").value = rec.remark || "";
    $("btnSaveEntry").textContent = "保存修改";
    goPage("entry");
  });
}
function resetEntry(){
  $("eId").value = "";
  $("entryTitle").textContent = "＋ 新增入库";
  $("eBrand").value = ""; $("eCategory").value = ""; $("eModel").value = "";
  $("eCondition").value = ""; $("ePrice").value = ""; $("eQty").value = "1";
  $("eShelf").value = ""; $("eRemark").value = "";
  $("btnSaveEntry").textContent = "保存入库";
}
$("btnResetEntry").onclick = resetEntry;
$("btnSaveEntry").onclick = function(){
  if (!CAN_WRITE) { toast("只读模式：请先向主机申请录入权限"); return; }
  var editing = $("eId").value !== "";
  var body = {brand: $("eBrand").value.trim(), category: $("eCategory").value.trim(),
              model: $("eModel").value.trim(), condition: $("eCondition").value.trim(),
              price: $("ePrice").value, qty: $("eQty").value,
              shelf: $("eShelf").value.trim(), remark: $("eRemark").value.trim()};
  $("btnSaveEntry").disabled = true;
  if (editing) {
    body.id = $("eId").value;
    api("/m/api/update_all", {method:"POST", body: JSON.stringify(body)}, function(b){
      $("btnSaveEntry").disabled = false;
      if (b.ok) { toast(b.message || "已保存", 2600); resetEntry(); loadItems(); goPage("items"); }
      else toast(b.error || "保存失败", 3000);
    });
  } else {
    api("/m/api/add", {method:"POST", body: JSON.stringify(body)}, function(b){
      $("btnSaveEntry").disabled = false;
      if (b.ok) { toast(b.message || "已入库", 2600); resetEntry(); }
      else toast(b.error || "保存失败", 3000);
    });
  }
};
$("btnAskEntry").onclick = function(){
  api("/m/api/request_write", {method:"POST"}, function(b){
    if (b.ok) { toast(b.already ? "已有录入权限" : "已向主机发送申请，请主机在电脑上确认", 3000); refreshWho(); }
    else toast(b.error || "申请失败", 3000);
  });
};
/* ---- 出售记录表格 ---- */
function loadSales(){
  $("listSales").innerHTML = '<tr><td colspan="8" class="empty">加载中…</td></tr>';
  api("/m/api/sales?kw=" + encodeURIComponent($("kwSales").value.trim()), {}, function(b){
    if (!b.ok) { $("listSales").innerHTML = '<tr><td colspan="8" class="empty">' + esc(b.error) + "</td></tr>"; return; }
    if (!b.sales.length) { $("listSales").innerHTML = '<tr><td colspan="8" class="empty">暂无出售记录</td></tr>'; return; }
    var h = "";
    b.sales.forEach(function(r){
      h += "<tr><td>" + esc(r.sale_date || "-") + "</td>"
         + "<td>" + esc(r.code) + "</td>"
         + "<td>" + esc(r.brand || "-") + "</td>"
         + "<td>" + esc(r.model || "-") + "</td>"
         + '<td class="num">' + esc(r.qty) + "</td>"
         + '<td class="num price">' + esc(r.total || "0") + "</td>"
         + "<td>" + esc(r.buyer || "-") + "</td>"
         + "<td>" + esc(r.out_type || "销售") + "</td></tr>";
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
