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
  · 例外：App 把数据同步到电脑「手机数据」区（/m/api/m_item、/m/api/m_sale）
    只写独立的手机数据表，不碰主库存，登录后即可直接同步，无需申请录入；
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
PAGE_LIMIT = 500                 # 列表接口单次最多返回条数
COOKIE_NAME = "cgm_session"

ITEM_FIELDS = ("id", "code", "brand", "category", "model", "condition",
               "price", "qty", "shelf", "listed", "sold_out", "remark")
SALE_FIELDS = ("id", "code", "brand", "model", "category", "qty", "price",
               "total", "buyer", "sale_date", "out_type", "remark", "paid")
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
                                     "app": bool(app_mode), "last": time.time()}
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
            s["last"] = now
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

    def sessions_info(self):
        """在线手机列表（按 IP 合并多会话，取最近活动）。

        返回 [{"ip", "app", "expires", "last"}]，按最近活动倒序 —— 供主机
        局域网窗口显示连接信息、单台下线/拉黑用。
        """
        with self._lock:
            now = time.time()
            info = {}
            for s in self._sessions.values():
                if now >= s["expires"]:
                    continue
                cur = info.get(s["ip"])
                if cur is None or s.get("last", 0) > cur["last"]:
                    info[s["ip"]] = {"ip": s["ip"], "app": bool(s.get("app")),
                                     "expires": s["expires"],
                                     "last": s.get("last", 0)}
            return sorted(info.values(), key=lambda d: -d["last"])


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
    store = srv.get_store()
    try:
        rows = store.all_records()
    except Exception as e:
        return 500, {"ok": False, "error": "读取库存失败：%s" % e}, NO_STORE
    try:
        thr = int(store.get_num("low_stock_threshold", 3) or 3)
    except Exception:
        thr = 3
    if kw:
        def hit(r):
            return any(kw in str(r.get(f) or "").lower()
                       for f in ("code", "brand", "category", "model", "shelf", "remark"))
        rows = [r for r in rows if hit(r)]
    rows.sort(key=lambda r: (int(r.get("sold_out") or 0), str(r.get("code") or "")))
    try:
        offset = max(0, int(query.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(query.get("limit") or PAGE_LIMIT)
    except (TypeError, ValueError):
        limit = PAGE_LIMIT
    limit = max(1, min(limit, PAGE_LIMIT))
    page = rows[offset:offset + limit]
    try:
        has_ph = store.photo_codes("item")   # 📷 指示列数据源
    except Exception:
        has_ph = set()
    out = []
    for r in page:
        d = {k: r.get(k) for k in ITEM_FIELDS}
        d["remark"] = _trim(d["remark"], 60)
        d["price"] = _fmt_price(d["price"])
        d["ph"] = 1 if (r.get("code") or "") in has_ph else 0
        q = int(r.get("qty") or 0)
        d["low"] = 1 if (not int(r.get("sold_out") or 0) and thr > 0
                         and q <= thr) else 0
        out.append(d)
    return 200, {"ok": True, "total": len(rows), "offset": offset,
                 "has_more": offset + limit < len(rows), "items": out}, NO_STORE


def handle_sales(srv, ip, token, query):
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}, NO_STORE
    kw = (query.get("kw") or "").strip()
    store = srv.get_store()
    try:
        rows = store.list_sales(kw=kw)[:PAGE_LIMIT]
    except Exception as e:
        return 500, {"ok": False, "error": "读取出售记录失败：%s" % e}, NO_STORE
    try:
        rmap = store.returns_by_sale([r.get("id") for r in rows])
    except Exception:
        rmap = {}
    out = []
    for r in rows:
        d = {k: r.get(k) for k in SALE_FIELDS}
        d["price"] = _fmt_price(d["price"])
        d["total"] = _fmt_price(d["total"])
        d["remark"] = _trim(d["remark"], 60)
        rr = rmap.get(int(r.get("id") or 0)) or {}
        d["returned"] = int(rr.get("qty") or 0)
        d["refund"] = _fmt_price(rr.get("refund") or 0)
        d["left"] = max(0, int(r.get("qty") or 0) - d["returned"])
        d["paid"] = 1 if (r.get("paid") is None or int(r.get("paid") or 0)) else 0
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


def _need_login(srv, ip, token):
    """只校验登录（用于手机数据区：写入独立表，不需要「允许录入」授权）。"""
    if not srv.mobile.check(token, ip):
        return 401, {"ok": False, "need_login": True, "error": "请先登录"}
    return None


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
    paid = p.get("paid") not in (0, False, "0", "否", "false")
    try:
        ok, msg = store.add_sale(item_id, p.get("qty"), p.get("price"),
                                 buyer=str(p.get("buyer") or "")[:40],
                                 remark=str(p.get("remark") or "")[:120],
                                 address=str(p.get("address") or "")[:120],
                                 paid=paid)
    except Exception as e:
        return 500, {"ok": False, "error": "登记失败：%s" % e}, NO_STORE
    return (200 if ok else 400), {"ok": ok, "error": None if ok else msg,
                                  "message": msg}, NO_STORE


# ---------------------------------------------------------------- 退货 / 撤销
def handle_return_sale(srv, ip, token, payload):
    """销售退货：可部分退，可选是否把货退回库存（默认退）。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    p = payload or {}
    try:
        sale_id = int(p.get("sale_id") or 0)
    except (TypeError, ValueError):
        sale_id = 0
    if sale_id <= 0:
        return 400, {"ok": False, "error": "请指定要退货的出售记录"}, NO_STORE
    refund = p.get("refund")
    if refund in (None, ""):
        refund = None
    else:
        try:
            refund = float(refund)
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "退款金额请填数字"}, NO_STORE
    restock = p.get("restock") not in (0, False, "0", "否", "false")
    store = srv.get_store()
    try:
        ok, msg = store.add_return(sale_id, p.get("qty"), refund=refund,
                                   restock=restock,
                                   remark=str(p.get("remark") or "")[:120])
    except Exception as e:
        return 500, {"ok": False, "error": "退货失败：%s" % e}, NO_STORE
    return (200 if ok else 400), {
        "ok": ok, "message": msg,
        "error": None if ok else msg}, NO_STORE


def handle_sale_undo(srv, ip, token, payload):
    """撤销一整笔出售（库存加回，记录作废）。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    try:
        sale_id = int((payload or {}).get("sale_id") or 0)
    except (TypeError, ValueError):
        sale_id = 0
    if sale_id <= 0:
        return 400, {"ok": False, "error": "请指定要撤销的出售记录"}, NO_STORE
    try:
        ok, msg = srv.get_store().delete_sale(sale_id, restore=True)
    except Exception as e:
        return 500, {"ok": False, "error": "撤销失败：%s" % e}, NO_STORE
    return (200 if ok else 400), {
        "ok": ok, "message": msg,
        "error": None if ok else msg}, NO_STORE


# ---------------------------------------------------------------- 统计 / 客户
def _profit_sum(rows):
    """一组 profit_rows 的汇总。amount 是实收（已扣退款）。"""
    amount = sum(float(r.get("amount") or 0) for r in rows)
    refund = sum(float(r.get("refund") or 0) for r in rows)
    profit = sum(float(r.get("profit") or 0) for r in rows)
    qty = sum(int(r.get("qty") or 0) - int(r.get("rq") or 0) for r in rows)
    return {"amount": round(amount, 2), "refund": round(refund, 2),
            "sales": round(amount + refund, 2), "profit": round(profit, 2),
            "qty": qty, "orders": len(rows)}


def handle_stats(srv, ip, token, query):
    """手机统计页：今日 / 本月 / 近 N 天 + 低库存 + 应收 + 本月利润榜。"""
    gate = _need_login(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    try:
        days = int((query or {}).get("days") or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))
    today = time.strftime("%Y-%m-%d")
    month_start = today[:8] + "01"
    range_start = time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    start = min(month_start, range_start)
    store = srv.get_store()
    try:
        rows = store.profit_rows(start=start)
        recs = store.all_records()
        unpaid = store.sales_unpaid()
        thr = int(store.get_num("low_stock_threshold", 3) or 3)
    except Exception as e:
        return 500, {"ok": False, "error": "统计失败：%s" % e}, NO_STORE

    def pick(lo):
        return [r for r in rows if (r.get("date") or "") >= lo]

    today_rows = [r for r in rows if (r.get("date") or "") == today]
    month_rows = pick(month_start)
    range_rows = pick(range_start)

    low = []
    for r in recs:
        if int(r.get("sold_out") or 0):
            continue
        q = int(r.get("qty") or 0)
        if thr > 0 and q <= thr:
            low.append({"id": r.get("id"), "code": r.get("code") or "",
                        "brand": r.get("brand") or "", "model": r.get("model") or "",
                        "qty": q, "shelf": r.get("shelf") or ""})
    low.sort(key=lambda d: (d["qty"], d["code"]))

    by_model = {}
    for r in month_rows:
        key = (r.get("model") or r.get("brand") or "未填型号").strip()
        cur = by_model.setdefault(key, {"model": key, "profit": 0.0, "qty": 0})
        cur["profit"] = round(cur["profit"] + float(r.get("profit") or 0), 2)
        cur["qty"] += int(r.get("qty") or 0) - int(r.get("rq") or 0)
    top = sorted(by_model.values(), key=lambda d: -d["profit"])[:5]

    stock = {"items": len(recs), "qty": sum(int(r.get("qty") or 0) for r in recs),
             "value": round(sum(int(r.get("qty") or 0)
                                * float(r.get("price") or 0) for r in recs), 2)}
    return 200, {"ok": True, "today": _profit_sum(today_rows),
                 "month": _profit_sum(month_rows),
                 "range": dict(_profit_sum(range_rows), days=days),
                 "days": days, "thr": thr,
                 "low": low[:30], "low_count": len(low),
                 "unpaid": unpaid, "top": top, "stock": stock}, NO_STORE


def handle_customers(srv, ip, token, query):
    """客户列表（含累计消费与应收），按姓名与出售记录对应。"""
    gate = _need_login(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    kw = str((query or {}).get("kw") or "").strip()
    store = srv.get_store()
    try:
        cs = store.list_customers(kw, include_buyers=True)
        unpaid = store.sales_unpaid()
    except Exception as e:
        return 500, {"ok": False, "error": "读取客户失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "customers": cs, "unpaid": unpaid}, NO_STORE


def handle_settle(srv, ip, token, payload):
    """结清应收：把某个买家（不传 buyer 则全部）的挂账标记为已收款。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    buyer = str((payload or {}).get("buyer") or "").strip()[:40]
    try:
        n = srv.get_store().settle_unpaid(buyer)
    except Exception as e:
        return 500, {"ok": False, "error": "结清失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "settled": n,
                 "message": ("已结清 %d 笔应收" % n) if n else "没有待收的挂账单"}, NO_STORE


def handle_returns(srv, ip, token, query):
    """退货记录列表（手机「记录 · 退货」页）。"""
    gate = _need_login(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    kw = str((query or {}).get("kw") or "").strip()
    try:
        rows = srv.get_store().list_returns(kw=kw)[:PAGE_LIMIT]
    except Exception as e:
        return 500, {"ok": False, "error": "读取退货记录失败：%s" % e}, NO_STORE
    out = []
    for r in rows:
        out.append({"id": r.get("id"), "sale_id": r.get("sale_id"),
                    "code": r.get("code") or "", "brand": r.get("brand") or "",
                    "model": r.get("model") or "", "qty": int(r.get("qty") or 0),
                    "refund": _fmt_price(r.get("refund")),
                    "buyer": r.get("buyer") or "",
                    "restock": int(r.get("restock") or 0),
                    "return_date": r.get("return_date") or ""})
    return 200, {"ok": True, "returns": out}, NO_STORE


# ---------------------------------------------------------------- 回收站
def _deleted_view(r):
    return {"id": r.get("id"), "code": r.get("code") or "",
            "brand": r.get("brand") or "", "model": r.get("model") or "",
            "qty": int(r.get("qty") or 0),
            "price": _fmt_price(r.get("price")),
            "deleted_at": r.get("deleted_at") or ""}


def handle_trash(srv, ip, token, query):
    gate = _need_login(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    kw = str((query or {}).get("kw") or "").strip().lower()
    store = srv.get_store()
    try:
        rows = store.list_deleted()
    except Exception as e:
        return 500, {"ok": False, "error": "读取回收站失败：%s" % e}, NO_STORE
    if kw:
        rows = [r for r in rows
                if any(kw in str(r.get(f) or "").lower()
                       for f in ("code", "brand", "model", "category"))]
    return 200, {"ok": True, "count": len(rows),
                 "items": [_deleted_view(r) for r in rows[:PAGE_LIMIT]]}, NO_STORE


def _ids_of(payload):
    raw = (payload or {}).get("ids")
    if raw is None:
        raw = [(payload or {}).get("id")]
    out = []
    for v in (raw if isinstance(raw, list) else [raw]):
        try:
            i = int(v or 0)
        except (TypeError, ValueError):
            continue
        if i > 0:
            out.append(i)
    return out


def handle_del_item(srv, ip, token, payload):
    """删除商品（软删除 → 回收站，可恢复）。"""
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    ids = _ids_of(payload)
    if not ids:
        return 400, {"ok": False, "error": "请指定要删除的记录"}, NO_STORE
    try:
        n = srv.get_store().delete_ids(ids, soft=True)
    except Exception as e:
        return 500, {"ok": False, "error": "删除失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "deleted": n,
                 "message": "已移入回收站 %d 条，可恢复" % n}, NO_STORE


def handle_restore(srv, ip, token, payload):
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    ids = _ids_of(payload)
    if not ids:
        return 400, {"ok": False, "error": "请指定要恢复的记录"}, NO_STORE
    try:
        n = srv.get_store().restore_ids(ids)
    except Exception as e:
        return 500, {"ok": False, "error": "恢复失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "restored": n,
                 "message": "已恢复 %d 条" % n}, NO_STORE


def handle_purge(srv, ip, token, payload):
    gate = _need_write(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    ids = _ids_of(payload)
    if not ids:
        return 400, {"ok": False, "error": "请指定要彻底删除的记录"}, NO_STORE
    try:
        n = srv.get_store().purge_ids(ids)
    except Exception as e:
        return 500, {"ok": False, "error": "彻底删除失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "purged": n,
                 "message": "已彻底删除 %d 条（含照片）" % n}, NO_STORE


# ---------------------------------------------------------------- 盘点
def handle_stocktake(srv, ip, token, query, payload=None):
    """盘点单：list / detail 只读；new / set / commit / del 需录入授权。"""
    gate = _need_login(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    p = payload or {}
    op = str(p.get("op") or (query or {}).get("op") or "list")
    store = srv.get_store()
    if op == "list":
        try:
            return 200, {"ok": True, "list": store.list_stocktakes()}, NO_STORE
        except Exception as e:
            return 500, {"ok": False, "error": "读取盘点单失败：%s" % e}, NO_STORE
    if op == "detail":
        try:
            st_id = int(p.get("id") or (query or {}).get("id") or 0)
        except (TypeError, ValueError):
            st_id = 0
        try:
            d = store.stocktake_detail(st_id)
        except Exception as e:
            return 500, {"ok": False, "error": "读取盘点单失败：%s" % e}, NO_STORE
        if not d:
            return 404, {"ok": False, "error": "盘点单不存在"}, NO_STORE
        head = d.get("head") or {}
        rows = [{"id": r.get("id"), "code": r.get("code") or "",
                 "brand": r.get("brand") or "", "model": r.get("model") or "",
                 "shelf": r.get("shelf") or "",
                 "book": int(r.get("book_qty") or 0),
                 "real": int(r.get("real_qty") or 0),
                 "note": r.get("note") or ""} for r in (d.get("rows") or [])]
        return 200, {"ok": True, "head": {
            "id": head.get("id"), "no": head.get("no") or "",
            "name": head.get("name") or "", "status": head.get("status") or "draft",
            "created_at": head.get("created_at") or "",
            "done_at": head.get("done_at") or ""}, "rows": rows}, NO_STORE

    wgate = _need_write(srv, ip, token)
    if wgate:
        return wgate[0], dict(wgate[1], readonly=True), NO_STORE
    if op == "new":
        try:
            st_id, msg = store.create_stocktake(
                name=str(p.get("name") or "")[:40],
                brand=str(p.get("brand") or "")[:40],
                category=str(p.get("category") or "")[:40],
                shelf=str(p.get("shelf") or "")[:60],
                kw=str(p.get("kw") or "")[:60],
                only_stock=bool(p.get("only_stock", True)))
        except Exception as e:
            return 500, {"ok": False, "error": "新建盘点失败：%s" % e}, NO_STORE
        return (200 if st_id else 400), {
            "ok": bool(st_id), "id": st_id, "message": msg,
            "error": None if st_id else msg}, NO_STORE
    if op == "set":
        try:
            row_id = int(p.get("row_id") or 0)
        except (TypeError, ValueError):
            row_id = 0
        if row_id <= 0:
            return 400, {"ok": False, "error": "缺少明细编号"}, NO_STORE
        try:
            ok, msg = store.set_stocktake_qty(row_id, p.get("real_qty"))
        except Exception as e:
            return 500, {"ok": False, "error": "保存实盘数失败：%s" % e}, NO_STORE
        return (200 if ok else 400), {"ok": ok, "message": msg or "已保存",
                                      "error": None if ok else msg}, NO_STORE
    if op == "commit":
        try:
            st_id = int(p.get("id") or 0)
        except (TypeError, ValueError):
            st_id = 0
        try:
            ok, msg = store.commit_stocktake(st_id)
        except Exception as e:
            return 500, {"ok": False, "error": "提交盘点失败：%s" % e}, NO_STORE
        return (200 if ok else 400), {"ok": ok, "message": msg,
                                      "error": None if ok else msg}, NO_STORE
    if op == "del":
        try:
            st_id = int(p.get("id") or 0)
        except (TypeError, ValueError):
            st_id = 0
        n = store.delete_stocktake(st_id)
        if n == -1:
            return 400, {"ok": False, "error": "已提交的盘点单不能删除"}, NO_STORE
        if n == 0:
            return 404, {"ok": False, "error": "盘点单不存在"}, NO_STORE
        return 200, {"ok": True, "message": "盘点单已删除"}, NO_STORE
    return 400, {"ok": False, "error": "不支持的操作"}, NO_STORE


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
# 绝不写主库存。这两张表与主库存完全隔离，所以只校验登录、不要求「允许录入」：
# 手机录完数据连上电脑就自动/一键同步，不用再去电脑上批一次授权。

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
    """App 商品同步（按手机本地 id 覆盖保存）。登录即可，无需申请录入。"""
    gate = _need_login(srv, ip, token)
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
    gate = _need_login(srv, ip, token)
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


# ---------------------------------------------------------------- 照片 v1.25.0
def _photo_args(payload, need_code=True):
    kind = str((payload or {}).get("kind") or "item")
    code = str((payload or {}).get("code") or "").strip()
    if kind not in ("item", "phone"):
        return None
    if need_code and not code:
        return None
    return kind, code


def handle_photos(srv, ip, token, query):
    """GET /m/api/photos?kind=&code=：照片文件名列表（登录即可看）。"""
    gate = _need_login(srv, ip, token)
    if gate:
        return gate
    a = _photo_args(query)
    if not a:
        return 400, {"ok": False, "error": "参数不正确"}
    try:
        names = srv.get_store().photos_list(a[0], a[1])
    except Exception as e:
        return 500, {"ok": False, "error": "读取失败：%s" % e}
    return 200, {"ok": True, "photos": names}


def handle_photo_get(srv, ip, token, query):
    """GET /m/api/photo_get?kind=&code=&name=：单张照片（base64）。"""
    gate = _need_login(srv, ip, token)
    if gate:
        return gate
    a = _photo_args(query)
    name = str((query or {}).get("name") or "")
    if not a or not name:
        return 400, {"ok": False, "error": "参数不正确"}
    b64 = srv.get_store().photo_data(a[0], a[1], name)
    if b64 is None:
        return 404, {"ok": False, "error": "照片不存在"}
    return 200, {"ok": True, "data": b64}


def handle_photo_add(srv, ip, token, payload):
    """POST /m/api/photo_add {kind, code, data(base64), name?}。
    主库存照片需要「允许录入」授权；手机区照片登录即可（独立数据）。"""
    p = payload or {}
    a = _photo_args(p)
    if not a:
        return 400, {"ok": False, "error": "参数不正确"}
    gate = _need_write(srv, ip, token) if a[0] == "item" \
        else _need_login(srv, ip, token)
    if gate:
        return gate
    data = p.get("data") or ""
    if not data:
        return 400, {"ok": False, "error": "缺少照片数据"}
    try:
        name = srv.get_store().photo_add(a[0], a[1], data,
                                         str(p.get("name") or ""))
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}, NO_STORE
    except Exception as e:
        return 500, {"ok": False, "error": "保存失败：%s" % e}, NO_STORE
    return 200, {"ok": True, "name": name, "message": "照片已保存"}, NO_STORE


def handle_photo_del(srv, ip, token, payload):
    """POST /m/api/photo_del {kind, code, name}。权限同 photo_add。"""
    p = payload or {}
    a = _photo_args(p)
    name = str(p.get("name") or "")
    if not a or not name:
        return 400, {"ok": False, "error": "参数不正确"}
    gate = _need_write(srv, ip, token) if a[0] == "item" \
        else _need_login(srv, ip, token)
    if gate:
        return gate
    ok = srv.get_store().photo_del(a[0], a[1], name)
    if not ok:
        return 404, {"ok": False, "error": "照片不存在"}, NO_STORE
    return 200, {"ok": True, "message": "已删除"}, NO_STORE


# ================================================================ 制作流程
# 手机端与电脑端共用同一个库：手机上发起的单，电脑端刷新即见；电脑推进后，
# 手机下一页轮询也能看到。权限与电脑端制作流程一致——不需要「允许录入」授权，
# 但必须登录；能推哪一站由手机自己上报的工位节点（stage）决定。
_WF_MAX_NOTE = 120
_WF_STOCK_LEN = {"brand": 40, "category": 40, "model": 120, "shelf": 120,
                 "remark": 200}


def _wf_stage_of(payload, query=None):
    """手机上报的工位节点序号（-1 = 未设置工位）。"""
    v = None
    if query is not None and query.get("stage") is not None:
        v = query.get("stage")
    if v is None and isinstance(payload, dict):
        v = payload.get("stage")
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def _wf_by(payload):
    return str((payload or {}).get("by") or "").strip()[:20]


def _truthy(v):
    """查询参数里的布尔（"0"/"false"/空 都算假）。"""
    if v is None:
        return False
    return str(v).strip().lower() not in ("", "0", "false", "no", "off")


def _wf_can_do(rec, st, my_station=""):
    """这张单能不能由本机（这个工位）推进——看得到 ≠ 能推。

    条件：在办 + 停在我负责的节点 + 没有指定交给同节点的另一个人。
    """
    if not rec or str(rec.get("status") or "active") != "active":
        return False
    if st < 0 or int(rec.get("stage") or 0) != st:
        return False
    owner = str(rec.get("station") or "")
    return (not owner) or owner == (my_station or "")


def _wf_stage_guard(store, rec, st, my_station=""):
    """校验：手机工位是不是单据当前所在节点；指定给别人的单不能接。"""
    try:
        stages = store.wf_stages()
    except Exception:
        stages = []
    if st < 0:
        return "请先在「我的工位」里选择你负责的节点"
    if st >= len(stages):
        return "工位设置已失效（节点被调整过），请重新选择工位"
    cur = int(rec.get("stage") or 0)
    if cur != st:
        return ("这张单现在在「%s」，不是你负责的「%s」"
                % (stages[cur] if 0 <= cur < len(stages) else ("节点%d" % (cur + 1)),
                   stages[st]))
    owner = str(rec.get("station") or "")
    if owner and owner != (my_station or ""):
        return ("这张单指定交给「%s」，你是「%s」，不能接"
                % (owner, my_station or stages[st]))
    return ""


def handle_wf(srv, ip, token, query, payload=None):
    """GET/POST /m/api/wf —— 手机端制作流程。

    GET  q=stages  → 节点 / 类型定义 / 各站在办数
    GET  q=list&status=active&stage=0&kw=  → 制作单列表
    GET  q=detail&id=3  → 单据 + 流转记录 + 照片
    POST op=create|move|back|stock|finish|urgent
    """
    gate = _need_login(srv, ip, token)
    if gate:
        return gate[0], gate[1], NO_STORE
    from .store import wf_photo_code
    store = srv.get_store()
    q = query or {}
    try:
        stages = store.wf_stages()
    except Exception as e:
        return 500, {"ok": False, "error": "读取流程节点失败：%s" % e}, NO_STORE

    # ---------------------------------------------------------- 读
    if not payload:
        what = str(q.get("q") or "list")
        if what == "stages":
            try:
                kinds = store.wf_kinds()
                counts = store.wf_counts()
            except Exception:
                kinds, counts = [], {}
            try:
                sts = store.wf_stations()
            except Exception:
                sts = []
            return 200, {"ok": True, "stages": stages, "kinds": kinds,
                         "stations": sts,
                         "counts": counts.get("counts") or [],
                         "done": counts.get("done") or 0,
                         "cancelled": counts.get("cancelled") or 0,
                         "last": max(0, len(stages) - 1)}, NO_STORE
        if what == "detail":
            try:
                wf_id = int(q.get("id") or 0)
            except (TypeError, ValueError):
                wf_id = 0
            rec = store.wf_one(wf_id) if wf_id else None
            if not rec:
                return 404, {"ok": False, "error": "制作单不存在"}, NO_STORE
            logs = store.wf_logs(wf_id)
            try:
                store.wf_photo_migrate(rec.get("no") or "")
            except Exception:
                pass
            by_stage = {}
            for si in range(len(stages)):
                try:
                    by_stage[str(si)] = store.photos_list(
                        "wf", wf_photo_code(rec.get("no") or "", si))
                except Exception:
                    by_stage[str(si)] = []
            photos = [n for si in sorted(by_stage, key=int)
                      for n in by_stage[si]]
            d = _wf_out(rec)
            d["stage_name"] = (stages[int(rec.get("stage") or 0)]
                               if 0 <= int(rec.get("stage") or 0) < len(stages)
                               else "")
            return 200, {"ok": True, "wf": d,
                         "logs": [{"at": str(g.get("at") or "")[:19],
                                   "action": g.get("action_name") or "",
                                   "by": g.get("by") or "",
                                   "note": g.get("note") or ""} for g in logs],
                         "photos": photos, "photos_by_stage": by_stage,
                         "stages": stages}, NO_STORE
        # list
        status = str(q.get("status") or "active")
        if status not in ("active", "done", "cancelled"):
            status = "active"
        kw = str(q.get("kw") or "").strip()
        st = _wf_stage_of(None, q)                 # 视图筛选（胶囊）
        my_station = str(q.get("station") or "").strip()[:20]
        my_st = _wf_stage_of(None, {"stage": q.get("mine_stage")})
        if my_st < 0:
            my_st = st                             # 没单独报我的节点：沿用筛选
        only = _truthy(q.get("only"))
        try:
            # v1.43.1：工位固定也要看得见整条流程——默认回全部单，
            # 每张带 mine 标记（能不能由我推进），前端灰显别站的单
            rows = store.wf_list(status, kw)
        except Exception as e:
            return 500, {"ok": False, "error": "读取制作单失败：%s" % e}, NO_STORE
        if st >= 0:
            rows = [r for r in rows if int(r.get("stage") or 0) == st]
        out, mine_n = [], 0
        for r in rows[:PAGE_LIMIT]:
            d = _wf_out(r)
            d["mine"] = _wf_can_do(r, my_st, my_station)
            if d["mine"]:
                mine_n += 1
            out.append(d)
        if only:
            out = [d for d in out if d["mine"]]
        return 200, {"ok": True, "rows": out, "stages": stages,
                     "stage": st, "mine_count": mine_n}, NO_STORE

    # ---------------------------------------------------------- 写
    p = payload or {}
    op = str(p.get("op") or "")
    by = _wf_by(p)
    if not by:
        return 400, {"ok": False, "error": "请先填写你的名字（经手人）"}, NO_STORE
    st = _wf_stage_of(p)
    note = str(p.get("note") or "").strip()[:_WF_MAX_NOTE]

    if op == "create":
        if st != 0:
            return 403, {"ok": False,
                         "error": "发起制作请用节点「%s」对应的工位"
                                  % (stages[0] if stages else "第一站")}, NO_STORE
        title = str(p.get("title") or "").strip()[:60]
        if not title:
            return 400, {"ok": False, "error": "请填写事项（做什么）"}, NO_STORE
        kind = str(p.get("kind") or "").strip()[:20]
        target = str(p.get("target") or "").strip()[:40]
        extra = p.get("extra") if isinstance(p.get("extra"), dict) else None
        if extra:
            extra = {str(k)[:20]: str(v)[:120] for k, v in extra.items()
                     if str(k).strip() and str(v).strip()}
            extra = extra or None
        to_station = str(p.get("to_station") or "").strip()[:20]
        try:
            wf_id, no = store.wf_create(title, kind=kind, target=target,
                                        note=note, by=by, extra=extra,
                                        station=to_station)
        except Exception as e:
            return 500, {"ok": False, "error": "发起失败：%s" % e}, NO_STORE
        if not wf_id:
            return 400, {"ok": False, "error": str(no or "发起失败")}, NO_STORE
        return 200, {"ok": True, "id": wf_id, "no": no,
                     "message": "已发起 %s，已推送到「%s」"
                                % (no, stages[0] if stages else "第一站")}, NO_STORE

    # 其余操作都要先确认单据停在自己的工位上
    try:
        wf_id = int(p.get("id") or 0)
    except (TypeError, ValueError):
        wf_id = 0
    rec = store.wf_one(wf_id) if wf_id else None
    if not rec:
        return 404, {"ok": False, "error": "制作单不存在"}, NO_STORE

    if op == "urgent":
        ok, msg = store.wf_set_urgent(wf_id, 1 if p.get("flag") else 0, by)
        return (200 if ok else 400), {"ok": ok, "message": msg,
                                      "error": "" if ok else msg}, NO_STORE

    last = max(0, len(stages) - 1)
    my_station = str(p.get("station") or "").strip()[:20]
    to_station = str(p.get("to_station") or "").strip()[:20]
    if op == "move":
        bad = _wf_stage_guard(store, rec, st, my_station)
        if bad:
            return 403, {"ok": False, "error": bad}, NO_STORE
        if int(rec.get("stage") or 0) == last:
            return 400, {"ok": False,
                         "error": "这张单已经在最后一站「%s」，请用「入库」或「结单」收尾"
                                  % stages[last]}, NO_STORE
        ok, msg = store.wf_advance(wf_id, by, note, station=to_station)
        return (200 if ok else 400), {"ok": ok, "message": msg,
                                      "error": "" if ok else msg}, NO_STORE

    if op == "back":
        bad = _wf_stage_guard(store, rec, st, my_station)
        if bad:
            return 403, {"ok": False, "error": bad}, NO_STORE
        target = p.get("target")
        try:
            target = int(target) if target not in (None, "") else None
        except (TypeError, ValueError):
            target = None
        ok, msg = store.wf_back(wf_id, by, note, target=target,
                                station=to_station)
        return (200 if ok else 400), {"ok": ok, "message": msg,
                                      "error": "" if ok else msg}, NO_STORE

    if op == "stock":
        bad = _wf_stage_guard(store, rec, st, my_station)
        if bad:
            return 403, {"ok": False, "error": bad}, NO_STORE
        fields = p.get("fields") if isinstance(p.get("fields"), dict) else {}
        clean = {}
        for k, n in _WF_STOCK_LEN.items():
            v = str(fields.get(k) or "").strip()[:n]
            if v:
                clean[k] = v
        try:
            clean["qty"] = int(float(fields.get("qty") or 1))
        except (TypeError, ValueError):
            clean["qty"] = 1
        try:
            clean["price"] = float(fields.get("price") or 0)
        except (TypeError, ValueError):
            clean["price"] = 0.0
        ok, msg = store.wf_stock_in(wf_id, clean, by=by)
        return (200 if ok else 400), {"ok": ok, "message": msg,
                                      "error": "" if ok else msg}, NO_STORE

    if op == "finish":
        bad = _wf_stage_guard(store, rec, st, my_station)
        if bad:
            return 403, {"ok": False, "error": bad}, NO_STORE
        ok, msg = store.wf_finish(wf_id, by, note)
        return (200 if ok else 400), {"ok": ok, "message": msg,
                                      "error": "" if ok else msg}, NO_STORE

    return 400, {"ok": False, "error": "不支持的操作：%s" % op}, NO_STORE


def _wf_out(r):
    """把 store 的行转成手机端用的精简结构。"""
    return {
        "id": int(r.get("id") or 0),
        "no": r.get("no") or "",
        "title": r.get("title") or "",
        "kind": r.get("kind") or "",
        "target": r.get("target") or "",
        "stage": int(r.get("stage") or 0),
        "stage_name": r.get("stage_name") or "",
        "status": r.get("status") or "active",
        "urgent": int(r.get("urgent") or 0),
        "station": str(r.get("station") or ""),
        "note": r.get("note") or "",
        "handler": r.get("handler") or "",
        "days": int(r.get("days") or 0),
        "updated_at": str(r.get("updated_at") or "")[:16],
        "extra": r.get("extra") if isinstance(r.get("extra"), dict) else {},
    }


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
nav { display:flex; background:var(--card); border-top:1px solid var(--line);
      position:fixed; left:0; right:0; bottom:0; z-index:30;
      padding-bottom:env(safe-area-inset-bottom); }
nav button { flex:1; border:0; background:none; padding:7px 0 6px; font-size:11px;
             color:var(--mut); display:flex; flex-direction:column;
             align-items:center; gap:2px; }
nav button i { font-style:normal; font-size:17px; line-height:1; }
nav button.on { color:var(--acc); font-weight:600; }
main { padding:12px 12px 104px; }
.srch { display:flex; gap:8px; margin-bottom:10px; }
.srch input { flex:1; border:1px solid var(--line); border-radius:10px; padding:9px 12px;
              font-size:15px; background:var(--card); }
.srch button { border:0; border-radius:10px; background:var(--acc); color:#fff; padding:0 18px; font-size:15px; }
.chips { display:flex; gap:8px; overflow-x:auto; padding-bottom:2px; margin-bottom:10px; }
.chip { flex:0 0 auto; border:1px solid var(--line); background:var(--card); color:#5a6478;
        border-radius:16px; padding:6px 14px; font-size:13px; }
.chip.on { background:var(--acc); border-color:var(--acc); color:#fff; }
.hintline { color:var(--mut); font-size:12px; margin:2px 2px 8px; }
.row { display:flex; align-items:center; gap:10px; background:var(--card);
       border:1px solid var(--line); border-radius:12px; padding:11px 12px; margin-bottom:9px; }
.row:active { background:#eef4ff; }
.row.dim .rowt { color:#8a94a6; font-weight:500; }
.row.dim { background:#fafbfd; }
.rowmain { flex:1; min-width:0; }
.rowt { font-size:14px; font-weight:600; }
.rows { font-size:12px; color:var(--mut); margin-top:2px; overflow:hidden;
        text-overflow:ellipsis; white-space:nowrap; }
.rowright { text-align:right; }
.qty { font-size:15px; font-weight:600; }
.money { font-size:12px; color:var(--bad); }
.tag { display:inline-block; font-size:10px; border-radius:8px; padding:1px 6px; margin-left:5px;
       background:#eef2f8; color:#5a6478; vertical-align:middle; }
.tag.warn { background:#fff3dc; color:var(--warn); }
.tag.bad { background:#ffeceb; color:var(--bad); }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px;
        padding:14px; margin-bottom:12px; }
.cardh { font-size:14px; font-weight:600; margin-bottom:8px; }
.cardh b { float:right; }
.mut { color:var(--mut); font-weight:400; font-size:12px; }
.line { display:flex; align-items:center; justify-content:space-between; gap:10px;
        padding:9px 0; border-bottom:1px solid #f0f3f8; font-size:14px; }
.line:last-child { border-bottom:0; }
.line.tap:active { background:#f6f9ff; }
.line .acts { display:flex; gap:8px; }
.mini { border:1px solid var(--line); background:var(--card); border-radius:9px;
        padding:6px 10px; font-size:12px; color:var(--acc); }
.mini.danger { color:var(--bad); border-color:#ffd9d6; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:14px;
       padding:16px 14px; margin-bottom:12px; }
.kpil { font-size:12px; color:var(--mut); }
.kpiv { font-size:28px; font-weight:700; letter-spacing:.5px; }
.kpis { font-size:12px; color:var(--mut); margin-top:2px; }
.kpi2 { display:flex; gap:10px; margin-top:14px; border-top:1px dashed var(--line); padding-top:12px; }
.kpi2 > div { flex:1; }
.kpi2 b { display:block; font-size:17px; margin-top:2px; }
.ok { color:var(--ok); }
.bad { color:var(--bad); }
.warn { color:var(--warn); }
.seg { display:flex; background:#e9eef7; border-radius:10px; padding:3px; margin-bottom:12px; }
.seg button { flex:1; border:0; background:none; border-radius:8px; padding:8px 0;
              font-size:13px; color:#5a6478; }
.seg button.on { background:var(--card); color:var(--acc); font-weight:600; }
.rowlink { display:flex; align-items:center; justify-content:space-between;
           padding:12px 0; border-bottom:1px solid #f0f3f8; font-size:15px; }
.rowlink:last-child { border-bottom:0; }
.rowlink:active { background:#f6f9ff; }
.foot { text-align:center; color:var(--mut); font-size:11px; padding:10px 0 0; }
.empty { text-align:center; color:var(--mut); padding:36px 0; font-size:13px; }
.empty.small { padding:20px 0; }
.hide { display:none !important; }
#mask { position:fixed; inset:0; background:rgba(18,24,38,.42); z-index:60;
        display:flex; align-items:flex-end; }
#sheet { width:100%; max-height:88vh; overflow-y:auto; background:var(--card);
         border-radius:18px 18px 0 0; padding:14px 16px calc(20px + env(safe-area-inset-bottom)); }
#sheet h3 { font-size:15px; margin-bottom:8px; }
#shBack, #shClose { border:0; background:#eef2f8; color:#5a6478; border-radius:10px;
                    padding:5px 11px; font-size:13px; }
#shClose { float:right; }
.sum { background:#f7f9fd; border-radius:10px; padding:10px 12px; margin-bottom:12px; }
.sumt { font-size:15px; font-weight:600; }
.lbl { display:block; font-size:12px; color:var(--mut); margin:12px 0 5px; }
.inp { width:100%; border:1px solid var(--line); border-radius:10px; padding:10px 12px;
       font-size:15px; background:var(--card); }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:0 12px; }
.go { width:100%; border:0; border-radius:12px; background:var(--acc); color:#fff;
      padding:13px; font-size:16px; margin-top:16px; }
.go:disabled { background:#a9c4f2; }
.go.small { padding:10px; font-size:14px; margin-top:12px; }
.btns { display:flex; gap:10px; margin-top:4px; }
.btns .btn { flex:1; border:1px solid var(--line); background:var(--card); color:var(--txt);
             border-radius:12px; padding:12px 0; font-size:15px; }
.btns .btn.primary { background:var(--acc); border-color:var(--acc); color:#fff; }
.btns .btn.danger { color:var(--bad); border-color:#ffd9d6; }
.chk { display:flex; align-items:center; gap:8px; font-size:14px; margin-top:14px; }
.chk input { width:18px; height:18px; }
.stlist { max-height:52vh; overflow-y:auto; border:1px solid var(--line); border-radius:10px; }
.strow { display:flex; align-items:center; gap:10px; padding:9px 11px; border-bottom:1px solid #f0f3f8; }
.strow:last-child { border-bottom:0; }
.stmain { flex:1; min-width:0; }
.stinp { width:82px; border:1px solid var(--line); border-radius:9px; padding:7px 9px;
         font-size:15px; text-align:center; }
.stinp.diff { border-color:var(--warn); background:#fff8ec; }
#fab { position:fixed; right:18px; bottom:calc(86px + env(safe-area-inset-bottom));
       width:54px; height:54px; border-radius:27px; border:0; background:var(--acc);
       color:#fff; font-size:26px; line-height:1; box-shadow:0 6px 16px rgba(31,111,235,.35); z-index:20; }
#toast { position:fixed; left:50%; bottom:100px; transform:translateX(-50%); background:rgba(28,35,51,.92);
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
  <button data-p="items" class="on"><i>▦</i><span>库存</span></button>
  <button data-p="rec"><i>☰</i><span>记录</span></button>
  <button data-p="wf"><i>⇄</i><span>流程</span></button>
  <button data-p="stat"><i>◔</i><span>统计</span></button>
  <button data-p="me"><i>⚙</i><span>我的</span></button>
</nav>
<main>
  <div id="p_items">
    <div class="srch"><input id="kwItems" placeholder="搜编号 / 品牌 / 型号 / 货架"><button id="goItems">搜索</button></div>
    <div class="chips" id="chips">
      <button class="chip on" data-f="all">全部</button>
      <button class="chip" data-f="on">在售</button>
      <button class="chip" data-f="low">低库存</button>
      <button class="chip" data-f="sold">售完</button>
    </div>
    <div class="hintline" id="itemsHint"></div>
    <div id="listItems"><div class="empty">加载中…</div></div>
  </div>

  <div id="p_rec" style="display:none">
    <div class="seg" id="recSeg">
      <button class="on" data-r="sales">出售记录</button>
      <button data-r="returns">退货记录</button>
    </div>
    <div class="srch"><input id="kwSales" placeholder="搜编号 / 买家 / 备注"><button id="goSales">搜索</button></div>
    <div id="listSales"></div>
  </div>

  <div id="p_stat" style="display:none">
    <div id="statWrap"><div class="empty">加载中…</div></div>
  </div>

  <div id="p_wf" style="display:none">
    <div class="card" id="wfMe"></div>
    <div class="seg" id="wfSeg">
      <button class="on" data-s="active">进行中</button>
      <button data-s="done">已完成</button>
      <button data-s="cancelled">已取消</button>
    </div>
    <div class="chips" id="wfChips"></div>
    <div class="hintline" id="wfHint"></div>
    <div id="listWf"><div class="empty">加载中…</div></div>
  </div>

  <div id="p_me" style="display:none">
    <div class="card" id="permCard"></div>
    <div class="card">
      <div class="rowlink" id="btnStocktake"><div>盘点</div><div class="mut">盘点单 / 新建盘点 ›</div></div>
      <div class="rowlink" id="btnTrash"><div>回收站</div><div class="mut" id="trashCount">›</div></div>
    </div>
    <div class="card">
      <div class="rowlink" id="btnLogout"><div>退出登录</div><div class="mut">›</div></div>
    </div>
    <div class="foot">仓管家手机端 · 数据实时保存在电脑</div>
  </div>
</main>
<button id="fab">＋</button>
</div>

<div id="mask" class="hide">
  <div id="sheet">
    <button id="shClose">关闭</button>
    <button id="shBack">返回</button>
    <h3 id="shTitle"></h3>
    <div id="shBody"></div>
  </div>
</div>
<div id="toast"></div>

<script>
var $ = function(id){ return document.getElementById(id); };
var CAN_WRITE = false;
var ITEMS = [], FILTER = "all";
var SALES = [], RETURNS = [], STAT = null, CUST = [], STAT_RANGE = "today";
var REC_TAB = "sales";
var shStack = [];

function toast(msg, ms){
  var t = $("toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(function(){ t.style.display = "none"; }, ms || 2200);
}
function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"]/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; });
}
function fmt(v){
  var n = Number(v || 0);
  if (isNaN(n)) n = 0;
  return n.toFixed(2);
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
function post(path, body, cb){
  api(path, {method:"POST", body: JSON.stringify(body)}, cb);
}
/* ---- 弹层 ---- */
function sheet(title, render){
  shStack.push({t:title, r:render});
  paintSheet();
}
function paintSheet(){
  var s = shStack[shStack.length - 1];
  if (!s) { $("mask").className = "hide"; $("shBody").innerHTML = ""; return; }
  $("shTitle").textContent = s.t;
  $("shBack").style.display = shStack.length > 1 ? "inline-block" : "none";
  $("mask").className = "";
  $("shBody").innerHTML = "";
  s.r($("shBody"));
}
function sheetBack(){ shStack.pop(); paintSheet(); }
function sheetClose(){ shStack = []; paintSheet(); }
$("shClose").onclick = sheetClose;
$("shBack").onclick = sheetBack;
/* ---- 登录 ---- */
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
    renderPerm();
  });
}
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
    if (b.ok) { showApp(); } else { $("loginErr").textContent = b.error || "登录失败"; }
  })
  .catch(function(){ $("btnLogin").disabled = false; $("loginErr").textContent = "网络错误，请确认与电脑连着同一 WiFi"; });
};
$("code").addEventListener("keydown", function(e){ if (e.key === "Enter") $("btnLogin").click(); });
function logout(){
  api("/m/logout", {method:"POST"}, function(){ showLogin(); });
}
/* ---- 页签 ---- */
var pages = ["items", "rec", "wf", "stat", "me"];
var PAGE = "items";
function goPage(p){
  PAGE = p;
  pages.forEach(function(x){ $("p_" + x).style.display = (x === p) ? "" : "none"; });
  var bs = document.querySelectorAll("nav button");
  for (var i = 0; i < bs.length; i++) {
    bs[i].className = (bs[i].getAttribute("data-p") === p) ? "on" : "";
  }
  $("fab").style.display = (p === "items" || p === "wf") ? "" : "none";
  if (p === "items") loadItems();
  if (p === "rec") { loadRec(); }
  if (p === "wf") loadWF();
  if (p === "stat") loadStats();
  if (p === "me") { renderPerm(); refreshTrashCount(); }
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
    ITEMS = b.items || [];
    paintItems();
  });
}
function itemRow(r, i){
  var tags = "";
  if (r.sold_out) tags += '<span class="tag warn">售完</span>';
  if (r.low) tags += '<span class="tag bad">低库存</span>';
  if (r.ph) tags += '<span class="tag">📷</span>';
  return '<div class="row" data-i="' + i + '">'
    + '<div class="rowmain"><div class="rowt">' + esc(r.code) + tags + "</div>"
    + '<div class="rows">' + esc([r.brand, r.model].filter(Boolean).join(" ") || "-") + "</div>"
    + '<div class="rows">' + esc(r.shelf || "未填货架") + "</div></div>"
    + '<div class="rowright"><div class="qty">×' + esc(r.qty) + "</div>"
    + '<div class="money">¥' + esc(r.price || "0") + "</div></div></div>";
}
function paintItems(){
  var arr = [], i;
  for (i = 0; i < ITEMS.length; i++) {
    var r = ITEMS[i];
    if (FILTER === "on" && r.sold_out) continue;
    if (FILTER === "low" && !r.low) continue;
    if (FILTER === "sold" && !r.sold_out) continue;
    arr.push(r);
  }
  var lowN = 0, onN = 0;
  for (i = 0; i < ITEMS.length; i++) { if (ITEMS[i].low) lowN++; if (!ITEMS[i].sold_out) onN++; }
  $("itemsHint").textContent = "共 " + ITEMS.length + " 条 · 在售 " + onN + " · 低库存 " + lowN;
  if (!arr.length) { $("listItems").innerHTML = '<div class="empty">没有符合条件的商品</div>'; return; }
  var h = "";
  for (i = 0; i < arr.length; i++) h += itemRow(arr[i], i);
  $("listItems").innerHTML = h;
  var rows = document.querySelectorAll("#listItems .row");
  for (i = 0; i < rows.length; i++) {
    rows[i].onclick = function(){
      itemActions(arr[Number(this.getAttribute("data-i"))]);
    };
  }
}
$("goItems").onclick = loadItems;
$("kwItems").addEventListener("keydown", function(e){ if (e.key === "Enter") loadItems(); });
(function(){
  var cs = document.querySelectorAll("#chips .chip");
  for (var i = 0; i < cs.length; i++) cs[i].onclick = function(){
    FILTER = this.getAttribute("data-f");
    for (var j = 0; j < cs.length; j++) cs[j].className = "chip" + (cs[j] === this ? " on" : "");
    paintItems();
  };
})();
function itemActions(r){
  var h = '<div class="sum"><div class="sumt">' + esc(r.code) + "</div>"
    + '<div class="rows">' + esc([r.brand, r.model].filter(Boolean).join(" ") || "-") + "</div>"
    + '<div class="rows">库存 ' + esc(r.qty) + " 件 · 单价 ¥" + esc(r.price)
    + (r.shelf ? " · " + esc(r.shelf) : "") + "</div></div>"
    + '<div class="btns"><button class="btn primary" id="actSell">出售</button>'
    + '<button class="btn" id="actEdit">修改</button>'
    + '<button class="btn danger" id="actDel">删除</button></div>';
  sheet("商品 " + r.code, function(box){
    box.innerHTML = h;
    $("actSell").onclick = function(){
      if (!CAN_WRITE) { toast("只读模式：请先到「我的」申请录入权限"); return; }
      sellSheet(r);
    };
    $("actEdit").onclick = function(){ entrySheet(r); };
    $("actDel").onclick = function(){ delItem(r); };
  });
}
function sellSheet(r){
  var h = '<div class="sum"><div class="sumt">' + esc(r.code) + "</div>"
    + '<div class="rows">' + esc([r.brand, r.model].filter(Boolean).join(" "))
    + " · 库存 " + esc(r.qty) + "</div></div>"
    + '<label class="lbl">数量</label><input class="inp" id="slQty" type="number" inputmode="numeric" min="1" max="'
    + esc(r.qty) + '" value="1">'
    + '<label class="lbl">单价（元）</label><input class="inp" id="slPrice" type="number" inputmode="decimal" value="'
    + esc(r.price) + '">'
    + '<label class="lbl">买家（可选）</label><input class="inp" id="slBuyer" placeholder="客户名">'
    + '<label class="lbl">收款</label><div class="chips" id="slPaid">'
    + '<button class="chip on" data-v="1">已收款</button>'
    + '<button class="chip" data-v="0">挂账（计入应收）</button></div>'
    + '<label class="lbl">备注（可选）</label><input class="inp" id="slRemark">'
    + '<button class="go" id="slGo">确认出售</button>';
  sheet("出售", function(box){
    box.innerHTML = h;
    var paid = "1";
    var bs = document.querySelectorAll("#slPaid .chip");
    for (var i = 0; i < bs.length; i++) bs[i].onclick = function(){
      paid = this.getAttribute("data-v");
      for (var j = 0; j < bs.length; j++) bs[j].className = "chip" + (bs[j] === this ? " on" : "");
    };
    $("slGo").onclick = function(){
      $("slGo").disabled = true;
      post("/m/api/sell", {code: r.code, qty: $("slQty").value, price: $("slPrice").value,
        buyer: $("slBuyer").value.trim(), remark: $("slRemark").value.trim(), paid: paid},
        function(b){
          $("slGo").disabled = false;
          if (!b.ok) { toast(b.error || "登记失败", 3000); return; }
          toast(b.message || "已登记", 2800);
          sheetClose(); loadItems();
        });
    };
  });
}
function entrySheet(r){
  var editing = !!r, v = r || {};
  var h = '<label class="lbl">品牌</label><input class="inp" id="edBrand" value="' + esc(v.brand || "") + '">'
    + '<label class="lbl">品类</label><input class="inp" id="edCategory" value="' + esc(v.category || "") + '">'
    + '<label class="lbl">型号</label><input class="inp" id="edModel" value="' + esc(v.model || "") + '">'
    + '<label class="lbl">成色</label><input class="inp" id="edCondition" value="' + esc(v.condition || "") + '">'
    + '<div class="grid2"><div><label class="lbl">单价（元）</label><input class="inp" id="edPrice" type="number" inputmode="decimal" value="'
    + esc(v.price || "") + '"></div><div><label class="lbl">数量</label><input class="inp" id="edQty" type="number" inputmode="numeric" min="0" value="'
    + esc(v.qty == null ? 1 : v.qty) + '"></div></div>'
    + '<label class="lbl">货架</label><input class="inp" id="edShelf" value="' + esc(v.shelf || "") + '">'
    + '<label class="lbl">备注</label><input class="inp" id="edRemark" value="' + esc(v.remark || "") + '">'
    + '<button class="go" id="edGo">' + (editing ? "保存修改" : "保存入库") + "</button>";
  sheet(editing ? "修改 " + r.code : "新增入库", function(box){
    box.innerHTML = h;
    $("edGo").onclick = function(){
      var body = {brand: $("edBrand").value.trim(), category: $("edCategory").value.trim(),
                  model: $("edModel").value.trim(), condition: $("edCondition").value.trim(),
                  price: $("edPrice").value, qty: $("edQty").value,
                  shelf: $("edShelf").value.trim(), remark: $("edRemark").value.trim()};
      if (!CAN_WRITE) { toast("只读模式：请先向电脑申请录入权限"); return; }
      $("edGo").disabled = true;
      if (editing) {
        body.id = r.id;
        post("/m/api/update_all", body, function(b){
          $("edGo").disabled = false;
          if (!b.ok) { toast(b.error || "保存失败", 3000); return; }
          toast(b.message || "已保存", 2400); sheetClose(); loadItems();
        });
      } else {
        post("/m/api/add", body, function(b){
          $("edGo").disabled = false;
          if (!b.ok) { toast(b.error || "保存失败", 3000); return; }
          toast(b.message || "已入库", 2600); sheetClose(); loadItems();
        });
      }
    };
  });
}
/* ---- 制作流程（与电脑端同一个库，实时互通） ---- */
var WF = {stages:[], kinds:[], stations:[], counts:[], rows:[], status:"active", stage:-1,
          last:0, showAll:true, onlyMine:false};
var MYWF = {name:"", station:"", stage:-1, names:{}};
try { MYWF = Object.assign(MYWF, JSON.parse(localStorage.getItem("cgm_wf_my") || "{}")); } catch(e) {}
function saveMyWf(){ try { localStorage.setItem("cgm_wf_my", JSON.stringify(MYWF)); } catch(e) {} }
function wfRememberBy(w, by){   /* 每个节点各记各的经手人 */
  MYWF.name = by;
  try { MYWF.names = MYWF.names || {}; MYWF.names[String(w.stage)] = by; } catch(e) {}
  saveMyWf();
}
function wfMyBy(w){ return (MYWF.names && MYWF.names[w.stage]) || MYWF.name || w.handler || ""; }
function wfStageName(i){ return WF.stages[i] == null ? "节点" + (i + 1) : WF.stages[i]; }
function wfMyLabel(){ return MYWF.station || (MYWF.stage >= 0 ? wfStageName(MYWF.stage) : "未设置"); }
function wfExtraText(ex){
  var out = [];
  for (var k in ex) { if (ex[k]) out.push(k + "：" + ex[k]); }
  return out.join("，");
}
function loadWF(silent){
  if (!silent) $("listWf").innerHTML = '<div class="empty">加载中…</div>';
  api("/m/api/wf?q=stages", {}, function(b){
    if (!b.ok) { toast(b.error || "读取失败", 2600); return; }
    WF.stages = b.stages || []; WF.kinds = b.kinds || [];
    WF.stations = b.stations || [];
    WF.counts = b.counts || []; WF.last = b.last || 0;
    paintWfMe(); paintWfChips(); loadWFRows(silent);
  });
}
function paintWfMe(){
  var mine = MYWF.stage >= 0 ? wfStageName(MYWF.stage) : "未选择";
  $("wfMe").innerHTML = '<div class="line tap" id="wfMeTap"><div><div class="sumt">'
    + esc(wfMyLabel()) + '</div><div class="rows">负责节点：' + esc(mine)
    + " · 经手人：" + esc(MYWF.name || "未填") + "</div></div>"
    + '<div class="mut">修改 ›</div></div>';
  $("wfMeTap").onclick = wfMeSheet;
}
function paintWfChips(){
  var st = WF.showAll ? -1 : (WF.stage >= 0 ? WF.stage : MYWF.stage);
  var h = '<button class="chip' + (WF.onlyMine ? " on" : "") + '" data-st="mine">我的工位'
        + (MYWF.stage >= 0 ? "(" + (WF.counts[MYWF.stage] || 0) + ")" : "!" ) + "</button>"
        + '<button class="chip' + (WF.showAll ? " on" : "") + '" data-st="all">全部流程</button>';
  for (var i = 0; i < WF.stages.length; i++) {
    h += '<button class="chip' + (!WF.onlyMine && !WF.showAll && st === i ? " on" : "")
       + '" data-st="' + i + '">'
       + esc(WF.stages[i]) + "(" + (WF.counts[i] || 0) + ")</button>";
  }
  $("wfChips").innerHTML = h;
  var bs = document.querySelectorAll("#wfChips .chip");
  for (var j = 0; j < bs.length; j++) bs[j].onclick = function(){
    var v = this.getAttribute("data-st");
    if (v === "mine") { WF.onlyMine = true; WF.showAll = false; WF.stage = MYWF.stage; }
    else if (v === "all") { WF.onlyMine = false; WF.showAll = true; WF.stage = -1; }
    else { WF.onlyMine = false; WF.showAll = false; WF.stage = Number(v); }
    paintWfChips(); loadWFRows();
  };
}
function loadWFRows(silent){
  var st = WF.showAll ? -1 : (WF.stage >= 0 ? WF.stage : MYWF.stage);
  if (!silent) $("listWf").innerHTML = '<div class="empty">加载中…</div>';
  api("/m/api/wf?q=list&status=" + WF.status + "&stage=" + st
      + "&station=" + encodeURIComponent(MYWF.station || "")
      + "&mine_stage=" + MYWF.stage
      + (WF.onlyMine ? "&only=1" : ""), {}, function(b){
    if (!b.ok) { toast(b.error || "读取失败", 2600); return; }
    WF.rows = b.rows || [];
    paintWFRows();
  });
}
function paintWFRows(){
  if (!WF.rows.length) {
    $("listWf").innerHTML = '<div class="empty">'
      + (WF.status === "active" ? "这一站暂时没有制作单" : "没有记录") + "</div>";
    $("wfHint").textContent = "";
    return;
  }
  var h = "", mineN = 0;
  for (var i = 0; i < WF.rows.length; i++) {
    var r = WF.rows[i], tags = "";
    if (r.urgent) tags += '<span class="tag bad">加急</span>';
    if (r.status === "done") tags += '<span class="tag">已完成</span>';
    if (r.status === "cancelled") tags += '<span class="tag bad">已取消</span>';
    if (r.status === "active" && !r.mine) tags += '<span class="tag">别站·只看</span>';
    if (r.mine) mineN += 1;
    h += '<div class="row' + (r.mine || r.status !== "active" ? "" : " dim")
      + '" data-i="' + i + '"><div class="rowmain">'
      + '<div class="rowt">' + esc(r.no) + " " + esc(r.title)
      + '<span class="tag">' + esc(r.stage_name) + "</span>" + tags + "</div>"
      + '<div class="rows">' + esc([r.kind, r.target].filter(Boolean).join(" · ") || "—")
      + (r.extra && Object.keys(r.extra).length ? " · " + esc(wfExtraText(r.extra)) : "")
      + "</div>"
      + (r.note ? '<div class="rows">备注：' + esc(r.note) + "</div>" : "")
      + '<div class="rows">经手人 ' + esc(r.handler || "—")
      + (r.station ? " · 交给 " + esc(r.station) : "") + " · 停留 " + r.days + " 天</div>"
      + '</div><div class="rowright"><div class="mut">' + esc(r.updated_at || "") + "</div></div></div>";
  }
  $("listWf").innerHTML = h;
  var rows = document.querySelectorAll("#listWf .row");
  for (var j = 0; j < rows.length; j++) rows[j].onclick = function(){
    wfDetail(WF.rows[Number(this.getAttribute("data-i"))]);
  };
  $("wfHint").textContent = "共 " + WF.rows.length + " 张 · 可推进 " + mineN
    + " 张 · 灰色=别的工位（点开只看流程，不能推）";
}
/* 我的工位：工位名可自定义（如「制作标签A」「制作标签B」），绑定到某个节点，
   同一节点可以有多个人各用各的工位名，经手人按各自姓名留痕。 */
function wfMeSheet(){
  var h = '<div class="hintline">一个节点可以有多个人：把工位名写成「制作标签A」「制作标签B」，'
    + '分别绑定到同一个节点即可，推进时按各自姓名留痕。</div>'
    + '<label class="lbl">我的工位（名称由电脑端「工位设置」维护）</label>'
    + '<select class="inp" id="wfStPick">';
  for (var i = 0; i < WF.stations.length; i++) {
    h += '<option value="' + esc(WF.stations[i].name) + '"'
       + (MYWF.station === WF.stations[i].name ? " selected" : "") + ">"
       + esc(WF.stations[i].name) + "（" + esc(wfStageName(WF.stations[i].stage))
       + "）</option>";
  }
  h += '</select><label class="lbl">我的姓名（经手人）</label>'
    + '<input class="inp" id="wfStBy" value="' + esc(MYWF.name) + '" placeholder="如：张三">'
    + '<button class="go" id="wfStGo">保存工位</button>';
  sheet("我的工位", function(box){
    box.innerHTML = h;
    $("wfStGo").onclick = function(){
      MYWF.station = $("wfStPick").value;
      for (var i = 0; i < WF.stations.length; i++) {
        if (WF.stations[i].name === MYWF.station) MYWF.stage = WF.stations[i].stage;
      }
      MYWF.name = $("wfStBy").value.trim();
      saveMyWf(); sheetClose(); toast("工位已保存"); loadWF(true);
    };
  });
}
function wfDetail(r){
  api("/m/api/wf?q=detail&id=" + r.id, {}, function(b){
    if (!b.ok) { toast(b.error || "读取失败", 2600); return; }
    var w = b.wf, logs = b.logs || [], stages = b.stages || WF.stages;
    var last = stages.length - 1;
    var owner = w.station || "";
    var mine = w.status === "active" && MYWF.stage >= 0 && w.stage === MYWF.stage
      && (!owner || owner === MYWF.station);
    var h = '<div class="sum"><div class="sumt">' + esc(w.no) + " " + esc(w.title) + "</div>"
      + '<div class="rows">' + esc(w.kind || "—") + " · 关联 " + esc(w.target || "—") + "</div>"
      + '<div class="rows">当前：' + esc(w.stage_name) + "（第 " + (w.stage + 1) + " / "
      + stages.length + " 站）· 交给 " + esc(w.station || "该节点任意人")
      + " · 经手人 " + esc(w.handler || "—") + "</div>"
      + (w.note ? '<div class="rows">备注：' + esc(w.note) + "</div>" : "")
      + (Object.keys(w.extra || {}).length ? '<div class="rows">' + esc(wfExtraText(w.extra)) + "</div>" : "")
      + "</div>";
    if (w.status === "active") {
      if (!mine) {
        h += '<div class="hintline">这张单在「' + esc(w.stage_name) + "」"
          + (owner && owner !== MYWF.station ? "，指定交给「" + esc(owner) + "」" : "")
          + "，你的工位是「" + esc(wfMyLabel()) + "」"
          + (MYWF.stage < 0 ? "（请先设置我的工位）" : "：只能查看流程，不能推进")
          + "</div>";
      } else if (w.stage >= last) {
        h += '<div class="btns"><button class="btn primary" id="wfStock">入库</button>'
          + '<button class="btn" id="wfFinish">结单</button></div>';
      } else {
        h += '<div class="btns"><button class="btn primary" id="wfNext">推进到「'
          + esc(stages[w.stage + 1]) + '」</button>'
          + '<button class="btn" id="wfBack">退回</button></div>';
      }
      h += '<div class="btns"><button class="btn" id="wfUrg">'
        + (w.urgent ? "取消加急" : "标记加急") + "</button></div>";
    }
    h += '<div class="cardh" style="margin-top:14px">流转记录</div><div class="card" style="margin:0">';
    if (!logs.length) h += '<div class="empty small">暂无记录</div>';
    for (var i = logs.length - 1; i >= 0; i--) {
      h += '<div class="line"><div><div>' + esc(logs[i].action) + "：" + esc(logs[i].by || "—")
        + '</div><div class="rows">' + esc(logs[i].note || "") + '</div></div>'
        + '<div class="mut">' + esc(logs[i].at.slice(5, 16)) + "</div></div>";
    }
    h += "</div>";
    sheet("制作单 " + w.no, function(box){
      box.innerHTML = h;
      if ($("wfNext")) $("wfNext").onclick = function(){ wfMoveSheet(w, stages); };
      if ($("wfBack")) $("wfBack").onclick = function(){ wfBackSheet(w, stages); };
      if ($("wfStock")) $("wfStock").onclick = function(){ wfStockSheet(w); };
      if ($("wfFinish")) $("wfFinish").onclick = function(){ wfFinishSheet(w); };
      if ($("wfUrg")) $("wfUrg").onclick = function(){
        if (!MYWF.name) { toast("请先设置我的姓名"); return; }
        post("/m/api/wf", {op:"urgent", id:w.id, flag: w.urgent ? 0 : 1,
          by: MYWF.name, stage: MYWF.stage, station: MYWF.station}, function(b2){
          if (!b2.ok) { toast(b2.error || "操作失败", 2600); return; }
          toast(b2.message || "已更新"); sheetClose(); loadWF(true);
        });
      };
    });
  });
}
function wfStationOptions(stage, cur){
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
    + esc(wfMyBy(w)) + '">'
    + '<label class="lbl">备注（会带给下一站）</label><input class="inp" id="wfNote" value="">'
    + '<button class="go" id="wfGo">确认推进</button>';
  sheet("推进", function(box){
    box.innerHTML = h;
    $("wfGo").onclick = function(){
      var by = $("wfBy").value.trim();
      if (!by) { toast("请填写经手人"); return; }
      wfRememberBy(w, by);
      $("wfGo").disabled = true;
      post("/m/api/wf", {op:"move", id:w.id, by:by, stage: MYWF.stage, station: MYWF.station,
        to_station: $("wfTo").value,
        note: $("wfNote").value.trim()}, function(b2){
        $("wfGo").disabled = false;
        if (!b2.ok) { toast(b2.error || "推进失败", 3000); return; }
        toast(b2.message || "已推进", 2800); sheetClose(); loadWF(true);
      });
    };
  });
}
function wfBackSheet(w, stages){
  var h = '<div class="sum"><div class="sumt">' + esc(w.no) + "</div>"
    + '<div class="rows">退回到（可跨站，如质检退回制作标签）</div></div>'
    + '<label class="lbl">目标节点</label><select class="inp" id="wfTgt">';
  for (var i = 0; i < w.stage; i++) {
    h += '<option value="' + i + '"' + (i === w.stage - 1 ? " selected" : "") + ">"
       + esc(stages[i]) + "</option>";
  }
  h += '</select><label class="lbl">交给谁</label>'
    + '<select class="inp" id="wfTo2">' + wfStationOptions(w.stage - 1, "") + "</select>"
    + '<label class="lbl">经手人（必填）</label><input class="inp" id="wfBy2" value="'
    + esc(wfMyBy(w)) + '">'
    + '<label class="lbl">退回原因</label><input class="inp" id="wfNote2" value="">'
    + '<button class="go" id="wfGo2" style="background:#d4380d">确认退回</button>';
  sheet("退回", function(box){
    box.innerHTML = h;
    $("wfGo2").onclick = function(){
      var by = $("wfBy2").value.trim();
      if (!by) { toast("请填写经手人"); return; }
      wfRememberBy(w, by);
      $("wfGo2").disabled = true;
      post("/m/api/wf", {op:"back", id:w.id, by:by, stage: MYWF.stage, station: MYWF.station,
        to_station: $("wfTo2").value,
        target: $("wfTgt").value, note: $("wfNote2").value.trim()}, function(b2){
        $("wfGo2").disabled = false;
        if (!b2.ok) { toast(b2.error || "退回失败", 3000); return; }
        toast(b2.message || "已退回", 2800); sheetClose(); loadWF(true);
      });
    };
  });
}
function wfStockSheet(w){
  var h = '<div class="sum"><div class="sumt">' + esc(w.no) + "</div>"
    + '<div class="rows">入库后单据完成，照片会一起带到库存记录</div></div>'
    + '<label class="lbl">品牌</label><input class="inp" id="wsBrand">'
    + '<label class="lbl">品类</label><input class="inp" id="wsCat">'
    + '<label class="lbl">型号（必填）</label><input class="inp" id="wsModel" value="'
    + esc(wfModelHint(w)) + '">'
    + '<div class="grid2"><div><label class="lbl">数量</label><input class="inp" id="wsQty" type="number" inputmode="numeric" value="1"></div>'
    + '<div><label class="lbl">单价（元）</label><input class="inp" id="wsPrice" type="number" inputmode="decimal" value="0"></div></div>'
    + '<label class="lbl">货架</label><input class="inp" id="wsShelf">'
    + '<label class="lbl">经手人（必填）</label><input class="inp" id="wsBy" value="'
    + esc(wfMyBy(w)) + '">'
    + '<button class="go" id="wsGo">确认入库</button>';
  sheet("入库", function(box){
    box.innerHTML = h;
    $("wsGo").onclick = function(){
      var by = $("wsBy").value.trim(), model = $("wsModel").value.trim();
      if (!by) { toast("请填写经手人"); return; }
      if (!model) { toast("请填写型号"); return; }
      wfRememberBy(w, by);
      $("wsGo").disabled = true;
      post("/m/api/wf", {op:"stock", id:w.id, by:by, stage: MYWF.stage, station: MYWF.station,
        fields:{brand:$("wsBrand").value.trim(), category:$("wsCat").value.trim(),
                model:model, qty:$("wsQty").value, price:$("wsPrice").value,
                shelf:$("wsShelf").value.trim()}}, function(b2){
        $("wsGo").disabled = false;
        if (!b2.ok) { toast(b2.error || "入库失败", 3000); return; }
        toast(b2.message || "已入库", 3000); sheetClose(); loadWF(true);
      });
    };
  });
}
function wfModelHint(w){
  var ex = w.extra || {};
  for (var k in ex) { if (k.indexOf("型号") >= 0 && k.indexOf("原") < 0) return ex[k]; }
  return "";
}
function wfFinishSheet(w){
  var h = '<div class="sum"><div class="sumt">' + esc(w.no) + "</div>"
    + '<div class="rows">不新增库存，直接把单据结单（如报废）</div></div>'
    + '<label class="lbl">经手人（必填）</label><input class="inp" id="wfFBy" value="'
    + esc(wfMyBy(w)) + '">'
    + '<label class="lbl">备注</label><input class="inp" id="wfFNote">'
    + '<button class="go" id="wfFGo">确认结单</button>';
  sheet("结单", function(box){
    box.innerHTML = h;
    $("wfFGo").onclick = function(){
      var by = $("wfFBy").value.trim();
      if (!by) { toast("请填写经手人"); return; }
      wfRememberBy(w, by);
      $("wfFGo").disabled = true;
      post("/m/api/wf", {op:"finish", id:w.id, by:by, stage: MYWF.stage, station: MYWF.station,
        note: $("wfFNote").value.trim()}, function(b2){
        $("wfFGo").disabled = false;
        if (!b2.ok) { toast(b2.error || "结单失败", 3000); return; }
        toast(b2.message || "已结单", 2800); sheetClose(); loadWF(true);
      });
    };
  });
}
/* 发起制作（手机发起 → 电脑端刷新即见 → 电脑推进后手机自动刷） */
function wfCreateSheet(){
  if (MYWF.stage < 0) { toast("请先设置我的工位"); wfMeSheet(); return; }
  if (MYWF.stage !== 0) { toast("发起制作要用第一站（" + wfStageName(0) + "）对应的工位"); return; }
  var h = '<label class="lbl">事项（做什么，必填）</label><input class="inp" id="crTitle" placeholder="如：保德型号更换">'
    + '<label class="lbl">类型</label><select class="inp" id="crKind"><option value="">不选</option>';
  for (var i = 0; i < WF.kinds.length; i++) {
    h += '<option value="' + esc(WF.kinds[i].name) + '">' + esc(WF.kinds[i].name) + "</option>";
  }
  h += '</select><div id="crExtra"></div>'
    + '<label class="lbl">发给谁（第一站有多人时选）</label>'
    + '<select class="inp" id="crTo">' + wfStationOptions(0, MYWF.station) + "</select>"
    + '<label class="lbl">关联编号（可选）</label><input class="inp" id="crTarget">'
    + '<label class="lbl">备注（会带给下一站）</label><input class="inp" id="crNote">'
    + '<label class="lbl">经手人（必填）</label><input class="inp" id="crBy" value="'
    + esc(MYWF.name) + '">'
    + '<button class="go" id="crGo">发起并推送到「' + esc(wfStageName(0)) + '」</button>';
  sheet("发起制作", function(box){
    box.innerHTML = h;
    var paintExtra = function(){
      var name = $("crKind").value, box2 = $("crExtra"), out = "";
      for (var i = 0; i < WF.kinds.length; i++) {
        if (WF.kinds[i].name !== name) continue;
        var fs = WF.kinds[i].fields || [];
        for (var j = 0; j < fs.length; j++) {
          var f = fs[j], id = "crF" + j;
          out += '<label class="lbl">' + esc(f.label) + "</label>";
          if (f.options && f.options.length && f.multi) {
            out += '<div class="chips" id="' + id + '">';
            for (var k = 0; k < f.options.length; k++) {
              out += '<button class="chip" data-v="' + esc(f.options[k]) + '">'
                 + esc(f.options[k]) + "</button>";
            }
            out += "</div>";
          } else if (f.options && f.options.length) {
            out += '<select class="inp" id="' + id + '"><option value="">不选</option>';
            for (var m = 0; m < f.options.length; m++) {
              out += '<option value="' + esc(f.options[m]) + '">' + esc(f.options[m]) + "</option>";
            }
            out += "</select>";
          } else {
            out += '<input class="inp" id="' + id + '">';
          }
        }
      }
      box2.innerHTML = out;
      var chips = box2.querySelectorAll(".chip");
      for (var n = 0; n < chips.length; n++) chips[n].onclick = function(){
        this.className = this.className.indexOf("on") >= 0 ? "chip" : "chip on";
      };
    };
    $("crKind").onchange = paintExtra;
    $("crGo").onclick = function(){
      var title = $("crTitle").value.trim(), by = $("crBy").value.trim();
      if (!title) { toast("请填写事项"); return; }
      if (!by) { toast("请填写经手人"); return; }
      wfRememberBy({stage:0}, by);
      var extra = {}, kind = $("crKind").value;
      for (var i = 0; i < WF.kinds.length; i++) {
        if (WF.kinds[i].name !== kind) continue;
        var fs = WF.kinds[i].fields || [];
        for (var j = 0; j < fs.length; j++) {
          var f = fs[j], el = $("crF" + j);
          if (!el) continue;
          if (f.options && f.options.length && f.multi) {
            var vals = [], cs = el.querySelectorAll(".chip.on");
            for (var k = 0; k < cs.length; k++) vals.push(cs[k].getAttribute("data-v"));
            if (vals.length) extra[f.label] = vals.join("、");
          } else if (el.value) {
            extra[f.label] = el.value;
          }
        }
      }
      $("crGo").disabled = true;
      post("/m/api/wf", {op:"create", by:by, stage: MYWF.stage, station: MYWF.station, title:title,
        station: MYWF.station, to_station: $("crTo").value,
        kind:kind, target:$("crTarget").value.trim(), note:$("crNote").value.trim(),
        extra: extra}, function(b2){
        $("crGo").disabled = false;
        if (!b2.ok) { toast(b2.error || "发起失败", 3000); return; }
        toast(b2.message || "已发起", 3000); sheetClose(); WF.showAll = false;
        loadWF(true);
      });
    };
  });
}
setInterval(function(){ if (PAGE === "wf") loadWF(true); }, 5000);
(function(){
  var bs = document.querySelectorAll("#wfSeg button");
  for (var i = 0; i < bs.length; i++) bs[i].onclick = function(){
    WF.status = this.getAttribute("data-s");
    for (var j = 0; j < bs.length; j++) bs[j].className = (bs[j] === this) ? "on" : "";
    loadWFRows();
  };
})();
$("fab").onclick = function(){
  if (PAGE === "wf") { wfCreateSheet(); return; }
  if (!CAN_WRITE) { toast("只读模式：请先到「我的」申请录入权限"); return; }
  entrySheet(null);
};
function delItem(r){
  if (!CAN_WRITE) { toast("只读模式，不能删除"); return; }
  if (!confirm("把 " + r.code + " 移入回收站？之后可以恢复。")) return;
  post("/m/api/del", {id: r.id}, function(b){
    if (!b.ok) { toast(b.error || "删除失败", 3000); return; }
    toast(b.message || "已移入回收站"); sheetClose(); loadItems();
  });
}
/* ---- 记录 ---- */
function loadRec(){
  if (REC_TAB === "sales") loadSales(); else loadReturns();
}
function paintSales(){
  if (!SALES.length) { $("listSales").innerHTML = '<div class="empty">暂无出售记录</div>'; return; }
  var h = "";
  for (var i = 0; i < SALES.length; i++) {
    var r = SALES[i], tags = "";
    if (!r.paid) tags += '<span class="tag bad">挂账</span>';
    if (r.returned) tags += '<span class="tag warn">已退' + r.returned + "</span>";
    h += '<div class="row" data-i="' + i + '"><div class="rowmain">'
      + '<div class="rowt">' + esc(r.code) + tags + "</div>"
      + '<div class="rows">' + esc([r.brand, r.model].filter(Boolean).join(" ") || "-") + "</div>"
      + '<div class="rows">' + esc(r.sale_date || "-") + " · " + esc(r.buyer || "未填买家")
      + " · " + esc(r.out_type || "销售") + "</div></div>"
      + '<div class="rowright"><div class="qty">×' + esc(r.qty) + "</div>"
      + '<div class="money">¥' + esc(r.total) + "</div></div></div>";
  }
  $("listSales").innerHTML = h;
  var rows = document.querySelectorAll("#listSales .row");
  for (var j = 0; j < rows.length; j++) rows[j].onclick = function(){
    saleActions(SALES[Number(this.getAttribute("data-i"))]);
  };
}
function loadSales(){
  $("listSales").innerHTML = '<div class="empty">加载中…</div>';
  api("/m/api/sales?kw=" + encodeURIComponent($("kwSales").value.trim()), {}, function(b){
    if (!b.ok) { $("listSales").innerHTML = '<div class="empty">' + esc(b.error) + "</div>"; return; }
    SALES = b.sales || [];
    paintSales();
  });
}
function paintReturns(){
  if (!RETURNS.length) { $("listSales").innerHTML = '<div class="empty">暂无退货记录</div>'; return; }
  var h = "";
  for (var i = 0; i < RETURNS.length; i++) {
    var r = RETURNS[i];
    h += '<div class="row"><div class="rowmain">'
      + '<div class="rowt">' + esc(r.code) + '<span class="tag warn">退货</span>' + "</div>"
      + '<div class="rows">' + esc([r.brand, r.model].filter(Boolean).join(" ") || "-") + "</div>"
      + '<div class="rows">' + esc(r.return_date || "-") + " · " + esc(r.buyer || "未填买家")
      + (r.restock ? " · 已回库" : " · 未回库") + "</div></div>"
      + '<div class="rowright"><div class="qty">×' + esc(r.qty) + "</div>"
      + '<div class="money">退 ¥' + esc(r.refund) + "</div></div></div>";
  }
  $("listSales").innerHTML = h;
}
function loadReturns(){
  $("listSales").innerHTML = '<div class="empty">加载中…</div>';
  api("/m/api/returns?kw=" + encodeURIComponent($("kwSales").value.trim()), {}, function(b){
    if (!b.ok) { $("listSales").innerHTML = '<div class="empty">' + esc(b.error) + "</div>"; return; }
    RETURNS = b.returns || [];
    paintReturns();
  });
}
(function(){
  var bs = document.querySelectorAll("#recSeg button");
  for (var i = 0; i < bs.length; i++) bs[i].onclick = function(){
    REC_TAB = this.getAttribute("data-r");
    for (var j = 0; j < bs.length; j++) bs[j].className = (bs[j] === this) ? "on" : "";
    loadRec();
  };
})();
$("goSales").onclick = loadRec;
$("kwSales").addEventListener("keydown", function(e){ if (e.key === "Enter") loadRec(); });
function saleActions(r){
  var canRet = (String(r.out_type || "销售") === "销售") && Number(r.left || 0) > 0;
  var h = '<div class="sum"><div class="sumt">' + esc(r.code) + "</div>"
    + '<div class="rows">' + esc([r.brand, r.model].filter(Boolean).join(" ") || "-") + "</div>"
    + '<div class="rows">' + esc(r.sale_date || "-") + " · 卖出 " + esc(r.qty) + " 件 × ¥"
    + esc(r.price) + " = ¥" + esc(r.total) + "</div>"
    + '<div class="rows">买家 ' + esc(r.buyer || "未填") + " · "
    + (r.paid ? "已收款" : "挂账未收") + (r.returned ? " · 已退 " + r.returned + " 件" : "") + "</div></div>"
    + '<div class="btns">'
    + (canRet ? '<button class="btn primary" id="actRet">退货</button>' : "")
    + '<button class="btn danger" id="actUndo">撤销整笔</button></div>';
  sheet("出售记录", function(box){
    box.innerHTML = h;
    if (canRet) $("actRet").onclick = function(){
      if (!CAN_WRITE) { toast("只读模式：请先申请录入权限"); return; }
      returnSheet(r);
    };
    $("actUndo").onclick = function(){
      if (!CAN_WRITE) { toast("只读模式：请先申请录入权限"); return; }
      if (!confirm("撤销这笔出售？" + (r.out_type === "销售" ? "数量会加回库存。" : ""))) return;
      post("/m/api/sale_undo", {sale_id: r.id}, function(b){
        if (!b.ok) { toast(b.error || "撤销失败", 3000); return; }
        toast(b.message || "已撤销"); sheetClose(); loadRec(); loadItems();
      });
    };
  });
}
function returnSheet(r){
  var left = Number(r.left || 0);
  var h = '<div class="sum"><div class="sumt">' + esc(r.code) + "</div>"
    + '<div class="rows">卖出 ' + esc(r.qty) + " 件，可退 " + left + " 件</div></div>"
    + '<label class="lbl">退货数量</label><input class="inp" id="rtQty" type="number" inputmode="numeric" min="1" max="'
    + left + '" value="' + left + '">'
    + '<label class="lbl">退款金额（元）</label><input class="inp" id="rtRefund" type="number" inputmode="decimal" value="'
    + fmt(Number(r.price || 0) * left) + '">'
    + '<label class="chk"><input type="checkbox" id="rtRestock" checked> 货退回库存</label>'
    + '<button class="go" id="rtGo">确认退货</button>';
  sheet("退货", function(box){
    box.innerHTML = h;
    $("rtQty").oninput = function(){
      var q = Number($("rtQty").value || 0);
      $("rtRefund").value = fmt(Number(r.price || 0) * q);
    };
    $("rtGo").onclick = function(){
      $("rtGo").disabled = true;
      post("/m/api/return_sale", {sale_id: r.id, qty: $("rtQty").value,
        refund: $("rtRefund").value, restock: $("rtRestock").checked}, function(b){
          $("rtGo").disabled = false;
          if (!b.ok) { toast(b.error || "退货失败", 3000); return; }
          toast(b.message || "已退货", 3000); sheetClose(); loadRec(); loadItems();
        });
    };
  });
}
/* ---- 统计 ---- */
function loadStats(){
  $("statWrap").innerHTML = '<div class="empty">加载中…</div>';
  api("/m/api/stats?days=30", {}, function(b){
    if (!b.ok) { $("statWrap").innerHTML = '<div class="empty">' + esc(b.error) + "</div>"; return; }
    STAT = b; paintStats();
  });
  api("/m/api/customers", {}, function(b){
    if (b.ok) { CUST = b.customers || []; paintStats(); }
  });
}
function paintStats(){
  if (!STAT) return;
  var s = STAT[STAT_RANGE] || STAT.today;
  var label = STAT_RANGE === "today" ? "今日" : (STAT_RANGE === "month" ? "本月" : "近" + STAT.days + "天");
  var h = '<div class="seg" id="statSeg">'
    + '<button class="' + (STAT_RANGE === "today" ? "on" : "") + '" data-v="today">今日</button>'
    + '<button class="' + (STAT_RANGE === "month" ? "on" : "") + '" data-v="month">本月</button>'
    + '<button class="' + (STAT_RANGE === "range" ? "on" : "") + '" data-v="range">近30天</button></div>'
    + '<div class="kpi"><div class="kpil">' + label + '销售额</div>'
    + '<div class="kpiv">¥' + fmt(s.sales) + "</div>"
    + '<div class="kpis">实收 ¥' + fmt(s.amount)
    + (Number(s.refund) ? " · 退款 ¥" + fmt(s.refund) : "") + "</div>"
    + '<div class="kpi2"><div><span class="kpil">毛利</span><b class="'
    + (Number(s.profit) >= 0 ? "ok" : "bad") + '">¥' + fmt(s.profit) + "</b></div>"
    + '<div><span class="kpil">单数</span><b>' + s.orders + "</b></div>"
    + '<div><span class="kpil">件数</span><b>' + s.qty + "</b></div></div></div>";

  h += '<div class="card"><div class="cardh">库存概览</div><div class="line">'
    + "<span>品种 / 件数</span><b>" + STAT.stock.items + " 种 · " + STAT.stock.qty + " 件</b></div>"
    + '<div class="line"><span>按售价估算货值</span><b>¥' + fmt(STAT.stock.value) + "</b></div></div>";

  h += '<div class="card"><div class="cardh">低库存 <span class="mut">阈值 ≤' + STAT.thr + ' 件</span>'
    + "<b>" + STAT.low_count + " 项</b></div>";
  if (!STAT.low.length) h += '<div class="empty small">没有低库存商品</div>';
  else STAT.low.forEach(function(r){
    h += '<div class="line"><span>' + esc(r.code) + '<br><span class="mut">'
      + esc([r.brand, r.model].filter(Boolean).join(" ") || "-") + "</span></span>"
      + '<b class="bad">' + r.qty + " 件</b></div>";
  });
  h += "</div>";

  h += '<div class="card"><div class="cardh">应收（挂账）<b class="bad">¥' + fmt(STAT.unpaid.total) + "</b></div>";
  if (!STAT.unpaid.buyers.length) h += '<div class="empty small">没有未收款</div>';
  else STAT.unpaid.buyers.forEach(function(r){
    h += '<div class="line"><span>' + esc(r.name) + '<br><span class="mut">' + r.count
      + ' 笔未收</span></span><span class="acts"><b>¥' + fmt(r.amount) + "</b>"
      + '<button class="mini" data-b="' + esc(r.name) + '">结清</button></span></div>';
  });
  h += "</div>";

  if (STAT.top.length) {
    h += '<div class="card"><div class="cardh">本月利润榜 <span class="mut">按型号</span></div>';
    STAT.top.forEach(function(r){
      h += '<div class="line"><span>' + esc(r.model) + "</span><b class='"
        + (Number(r.profit) >= 0 ? "ok" : "bad") + "'>¥" + fmt(r.profit) + "</b></div>";
    });
    h += "</div>";
  }

  h += '<div class="card"><div class="cardh">客户 <span class="mut">累计消费</span></div>';
  if (!CUST.length) h += '<div class="empty small">还没有客户档案（电脑端可添加）</div>';
  else CUST.slice(0, 10).forEach(function(c){
    h += '<div class="line"><span>' + esc(c.name) + '<br><span class="mut">'
      + esc(c.phone || "未填电话") + " · " + c.count + " 笔</span></span>"
      + '<b>' + (Number(c.debt) ? '<span class="bad">欠 ¥' + fmt(c.debt) + "</span><br>" : "")
      + '<span class="mut">累计 ¥' + fmt(c.amount) + "</span></b></div>";
  });
  h += "</div>";

  $("statWrap").innerHTML = h;
  var segs = document.querySelectorAll("#statSeg button");
  for (var i = 0; i < segs.length; i++) segs[i].onclick = function(){
    STAT_RANGE = this.getAttribute("data-v");
    paintStats();
  };
  var settles = document.querySelectorAll("#statWrap button[data-b]");
  for (var k = 0; k < settles.length; k++) settles[k].onclick = function(){
    if (!CAN_WRITE) { toast("只读模式：请先申请录入权限"); return; }
    var who = this.getAttribute("data-b");
    if (!confirm("把「" + who + "」的挂账全部标记为已收款？")) return;
    post("/m/api/settle", {buyer: who}, function(b){
      if (!b.ok) { toast(b.error || "结清失败", 3000); return; }
      toast(b.message || "已结清", 2600); loadStats();
    });
  };
}
/* ---- 我的 ---- */
function renderPerm(){
  if (!$("permCard")) return;
  if (CAN_WRITE) {
    $("permCard").innerHTML = '<div class="cardh">录入权限</div>'
      + '<div class="rows">已授权：可新增、修改、出售、退货、盘点、删改回收站</div>';
    return;
  }
  $("permCard").innerHTML = '<div class="cardh">录入权限</div>'
    + '<div class="rows">当前只读：只能查看，不能改数据</div>'
    + '<button class="go small" id="btnAskMe">向电脑申请权限</button>';
  $("btnAskMe").onclick = function(){
    post("/m/api/request_write", {}, function(b){
      if (b.ok) { toast(b.already ? "已有录入权限" : "已向电脑发送申请，请主人在电脑上确认", 3200); refreshWho(); }
      else toast(b.error || "申请失败", 3000);
    });
  };
}
function refreshTrashCount(){
  api("/m/api/trash", {}, function(b){
    if (!b.ok) return;
    $("trashCount").textContent = (b.count ? b.count + " 条待处理 ›" : "空 ›");
  });
}
function trashSheet(){
  sheet("回收站", function(box){
    box.innerHTML = '<div class="empty small">加载中…</div>';
    api("/m/api/trash", {}, function(b){
      if (!b.ok) { box.innerHTML = '<div class="empty small">' + esc(b.error) + "</div>"; return; }
      if (!b.items.length) { box.innerHTML = '<div class="empty small">回收站是空的</div>'; return; }
      var h = '<div class="hintline">共 ' + b.count + " 条 · 恢复后回到库存</div>";
      b.items.forEach(function(r){
        h += '<div class="line"><span>' + esc(r.code) + '<br><span class="mut">'
          + esc([r.brand, r.model].filter(Boolean).join(" ") || "-") + " · "
          + esc(r.deleted_at || "") + "</span></span>"
          + '<span class="acts"><button class="mini" data-r="' + r.id + '">恢复</button>'
          + '<button class="mini danger" data-p="' + r.id + '">删除</button></span></div>';
      });
      box.innerHTML = h;
      var rs = box.querySelectorAll("button[data-r]");
      for (var i = 0; i < rs.length; i++) rs[i].onclick = function(){
        if (!CAN_WRITE) { toast("只读模式：请先申请录入权限"); return; }
        post("/m/api/restore", {ids: [Number(this.getAttribute("data-r"))]}, function(res){
          if (!res.ok) { toast(res.error || "恢复失败", 3000); return; }
          toast(res.message || "已恢复"); sheetClose(); trashSheet(); loadItems();
        });
      };
      var ps = box.querySelectorAll("button[data-p]");
      for (var k = 0; k < ps.length; k++) ps[k].onclick = function(){
        if (!CAN_WRITE) { toast("只读模式：请先申请录入权限"); return; }
        if (!confirm("彻底删除后无法恢复（照片也会删除），确定？")) return;
        post("/m/api/purge", {ids: [Number(this.getAttribute("data-p"))]}, function(res){
          if (!res.ok) { toast(res.error || "删除失败", 3000); return; }
          toast(res.message || "已彻底删除"); sheetClose(); trashSheet(); refreshTrashCount();
        });
      };
    });
  });
}
function stocktakeSheet(){
  sheet("盘点", function(box){
    box.innerHTML = '<div class="empty small">加载中…</div>';
    api("/m/api/stocktake?op=list", {}, function(b){
      if (!b.ok) { box.innerHTML = '<div class="empty small">' + esc(b.error) + "</div>"; return; }
      var h = '<button class="go" id="stNew">＋ 新建盘点</button>';
      if (!b.list.length) h += '<div class="empty small">还没有盘点单</div>';
      else b.list.forEach(function(s){
        h += '<div class="line tap" data-id="' + s.id + '"><span>' + esc(s.name)
          + '<br><span class="mut">' + esc(s.no) + " · "
          + (s.status === "done" ? "已完成" : "进行中") + " · " + s.count + " 条</span></span>"
          + "<b>" + (s.diff ? s.diff + ' <span class="warn">条差异</span>'
            : '<span class="mut">无差异</span>') + "</b></div>";
      });
      box.innerHTML = h;
      $("stNew").onclick = stocktakeNew;
      var ls = box.querySelectorAll(".line[data-id]");
      for (var i = 0; i < ls.length; i++) ls[i].onclick = function(){
        stocktakeDetail(this.getAttribute("data-id"));
      };
    });
  });
}
function stocktakeNew(){
  sheet("新建盘点", function(box){
    box.innerHTML = '<label class="lbl">名称（可选）</label><input class="inp" id="stName" placeholder="如 11月全盘">'
      + '<label class="lbl">品牌筛选（可选）</label><input class="inp" id="stBrand">'
      + '<label class="lbl">关键词（可选）</label><input class="inp" id="stKw" placeholder="编号 / 型号 / 品牌">'
      + '<label class="chk"><input type="checkbox" id="stOnly" checked> 只盘有货的</label>'
      + '<button class="go" id="stGo">生成盘点单</button>';
    $("stGo").onclick = function(){
      this.disabled = true;
      post("/m/api/stocktake", {op: "new", name: $("stName").value.trim(),
        brand: $("stBrand").value.trim(), kw: $("stKw").value.trim(),
        only_stock: $("stOnly").checked}, function(b){
          if (!b.ok) { toast(b.error || "生成失败", 3200); $("stGo").disabled = false; return; }
          toast(b.message || "已生成", 3000);
          sheetClose(); stocktakeSheet();
        });
    };
  });
}
function stocktakeDetail(id){
  sheet("盘点单", function(box){
    box.innerHTML = '<div class="empty small">加载中…</div>';
    api("/m/api/stocktake?op=detail&id=" + id, {}, function(b){
      if (!b.ok) { box.innerHTML = '<div class="empty small">' + esc(b.error) + "</div>"; return; }
      var draft = (b.head.status === "draft");
      var h = '<div class="sum"><div class="sumt">' + esc(b.head.name) + "</div>"
        + '<div class="rows">' + esc(b.head.no) + " · " + b.rows.length + " 条 · "
        + (draft ? "进行中，可改实盘数" : "已完成") + "</div></div>"
        + '<div class="stlist">';
      b.rows.forEach(function(r){
        h += '<div class="strow"><div class="stmain"><div class="rowt">' + esc(r.code) + "</div>"
          + '<div class="rows">' + esc(r.model || "-") + " · 账面 " + r.book + "</div></div>"
          + '<input class="stinp" type="number" inputmode="numeric" min="0" data-id="' + r.id
          + '" value="' + r.real + '"' + (draft ? "" : " disabled") + "></div>";
      });
      h += "</div>";
      if (draft) h += '<button class="go" id="stCommit">提交盘点（按实盘数改库存）</button>';
      box.innerHTML = h;
      var ins = box.querySelectorAll(".stinp");
      for (var i = 0; i < ins.length; i++) ins[i].onchange = function(){
        var el = this;
        post("/m/api/stocktake", {op: "set", row_id: el.getAttribute("data-id"),
          real_qty: el.value}, function(r){
            if (!r.ok) { toast(r.error || "保存失败", 3000); return; }
            el.style.borderColor = "#18a058";
            setTimeout(function(){ el.style.borderColor = ""; }, 800);
          });
      };
      if (draft) $("stCommit").onclick = function(){
        if (!confirm("提交后按实盘数改写库存，确定？")) return;
        post("/m/api/stocktake", {op: "commit", id: Number(b.head.id)}, function(r){
          if (!r.ok) { toast(r.error || "提交失败", 3200); return; }
          toast(r.message || "已提交", 3200); sheetClose(); loadItems();
        });
      };
    });
  });
}
$("btnStocktake").onclick = function(){ stocktakeSheet(); };
$("btnTrash").onclick = function(){ trashSheet(); };
$("btnLogout").onclick = function(){ if (confirm("退出登录？")) logout(); };
/* ---- 启动：有会话直接进应用 ---- */
api("/m/api/whoami", {}, function(b){ if (b.ok) showApp(); else showLogin(); });
</script>
</body>
</html>
"""
