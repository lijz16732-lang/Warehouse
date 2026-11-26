# -*- coding: utf-8 -*-
"""局域网主机服务（主机/客户端模式）。

数据只有主机这一份：主机本地照常操作 SQLite，其它电脑通过 HTTP 连过来读写，
所以不存在“同步冲突”，谁看到的就是主机当前的数据。

权限：
  · 所有请求都要带连接码（防同网段陌生设备连入）；
  · 读接口默认放行 —— 其它电脑可以查看、导出；
  · 写接口默认拒绝 —— 主机在「局域网共享」里逐台勾选「允许录入」后才可写；
  · 客户端点「请求录入」会在主机上弹窗询问。
"""

import hmac
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .audit import AccessLog
from .constants import APP_NAME, APP_VERSION
from .mobile import (MobileService, _token_from, handle_add, handle_coltitles,
                     handle_logout, handle_m_item, handle_m_sale, handle_page,
                     handle_request_write, handle_sales, handle_sell,
                     handle_update_all, handle_whoami, handle_items,
                     handle_photos, handle_photo_get, handle_photo_add,
                     handle_photo_check,
                     handle_photo_del, handle_return_sale, handle_sale_undo,
                     handle_stats, handle_customers, handle_trash,
                     handle_del_item, handle_restore, handle_purge,
                     handle_stocktake, handle_returns, handle_settle,
                     handle_wf)
from .store import Store

DEFAULT_PORT = 8765

# Store 的公开方法都允许走远程（个别有安全风险的除外）
RPC_METHODS = {n for n in dir(Store) if not n.startswith("_")}
RPC_METHODS.discard("close")

# 只读方法：不需要授权
READ_METHODS = {
    "all_records", "count", "distinct", "find_by_code", "generate_codes",
    "m_items", "m_sales",
    "get_meta", "get_num", "list_sales", "sales_brands", "out_types_used",
    "buyer_names", "sale_addresses", "buyer_address_map", "buyer_stats",
    "list_purchases", "purchase_totals", "list_deleted", "deleted_count",
    "duplicate_models", "model_keys", "blank_content_keys",
    "sales_totals", "out_totals", "stats", "revision",
    "sales_stats_by_src",
    # v1.34.0 自定义列题（读）；只读客户端也要能读到列题才能显示表格
    "col_titles",
    "photos_list", "photo_data", "photo_codes",
    # v1.32.0 客户 / 退货 / 利润 / 盘点（只读查询）
    "list_customers", "list_returns", "returns_total", "returnable_qty",
    "profit_rows", "list_stocktakes", "stocktake_detail",
    # v1.42.1 制作流程（只读）：各工位电脑要看得到当前流转到哪一步
    "wf_stages", "wf_list", "wf_counts", "wf_logs", "wf_stamp", "wf_one",
}
WRITE_METHODS = RPC_METHODS - READ_METHODS
# 这些操作和主机本地文件有关，客户端不准调用
BLOCKED_METHODS = {"backup_to", "photos_dir", "photo_path"}
# 制作流程：不对「允许录入」做授权，各工位电脑直接可用；
# 能推哪一站由各电脑在制作流程页自己选的「本机工位」决定（见 _wf_stage_error）。
WF_METHODS = {"wf_create", "wf_advance", "wf_back", "wf_cancel",
              "wf_resume", "wf_delete", "wf_set_target", "wf_stock_in",
              "wf_finish", "wf_set_urgent"}
# 入库照片：制作单（kind="wf"）的增删照片不受「允许录入」限制
WF_PHOTO_METHODS = {"photo_add", "photo_del", "photos_list", "photo_data"}
# 推进一步：必须与绑定的工位一致
WF_MOVE_METHODS = {"wf_advance", "wf_back"}


def _wf_photo_call(args, kwargs):
    """这次照片调用是不是作用在制作单（kind="wf"）上。"""
    kind = (kwargs or {}).get("kind")
    if kind is None and args:
        kind = args[0]
    return str(kind or "") == "wf"


def local_ips():
    """本机在局域网里的 IPv4 地址列表（最常见的那个排最前）。"""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))          # 不会真的发包
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips or ["127.0.0.1"]


class LanServer(object):
    """主机端的 HTTP 服务（后台线程跑，关窗口时 stop）。"""

    def __init__(self, get_store, get_warehouse, code, port=DEFAULT_PORT,
                 on_event=None):
        self.get_store = get_store
        self.get_warehouse = get_warehouse
        self.code = str(code or "")
        self.port = int(port or DEFAULT_PORT)
        self.on_event = on_event or (lambda *a, **k: None)
        self.clients = {}          # ip -> {name, id, allowed, stage, last_seen, requests}
        self.name_overrides = {}   # ip -> 主机指定的显示名（覆盖客户端上报名）
        self.default_allow = False  # 新连接电脑默认是否可录入
        self.phone_access = True    # 允许手机访问（设置里可关，关后 /m 全部 403）
        self.blocked = {}          # 黑名单：ip -> {name, time}（持久保存在主机配置里）
        self.kicked = {}           # 被移除连接：ip -> 到期时间（短暂拒绝，防 4 秒轮询立刻重连）
        self.stage_reqs = {}       # 工位变更申请：ip -> {stage, status, name, ts}
        self._lock = threading.Lock()
        self.httpd = None
        self._thread = None
        self.last_error = ""
        self.mobile = MobileService()   # 手机端：会话与手机专用接口
        self._access = None             # 访问日志（懒加载，见 audit_log）

    # ------------------------------------------------------------ 生命周期
    def start(self):
        if self.httpd is not None:
            return True, "主机服务已在运行（端口 %d）" % self.port
        try:
            self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), _make_handler(self))
        except OSError as e:
            self.last_error = str(e)
            self.httpd = None
            return False, "无法监听端口 %d：%s" % (self.port, e)
        self.httpd.daemon_threads = True
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        kwargs={"poll_interval": 0.3},
                                        name="lan-server", daemon=True)
        self._thread.start()
        return True, "主机服务已开启（端口 %d）" % self.port

    def stop(self):
        h, self.httpd = self.httpd, None
        if h is not None:
            try:
                h.shutdown()
                h.server_close()
            except Exception:
                pass
        self.clients.clear()
        self.mobile.clear_all()     # 手机端会话随共享一起下线
        self.on_event("clients", None)

    @property
    def running(self):
        return self.httpd is not None

    # ------------------------------------------------------------ 权限
    def can_write(self, ip):
        with self._lock:
            c = self.clients.get(ip)
            return bool(self.default_allow or (c and c.get("allowed")))

    def allow(self, ip, flag):
        with self._lock:
            c = self.clients.setdefault(ip, {"name": "", "id": "", "allowed": False,
                                             "last_seen": 0.0, "requests": 0})
            c["allowed"] = bool(flag)
        self.on_event("clients", None)

    def set_default_allow(self, flag):
        self.default_allow = bool(flag)
        self.on_event("clients", None)

    # ---- 工位变更申请（v1.42.2）：选定后锁定，再改要主机点头
    def request_stage(self, ip, stage, name=""):
        """客户端申请改成某个工位；主机窗口会弹窗询问。"""
        try:
            idx = int(stage)
        except (TypeError, ValueError):
            idx = -1
        with self._lock:
            self.stage_reqs[ip] = {"stage": idx, "status": "pending",
                                   "name": name or "未知电脑", "ts": time.time()}
        self.on_event("stage_req", {"ip": ip, "stage": idx,
                                    "name": name or "未知电脑"})
        return True

    def answer_stage(self, ip, ok):
        """主机点「同意 / 不同意」。"""
        with self._lock:
            r = self.stage_reqs.get(ip)
            if r is None:
                return False
            r["status"] = "ok" if ok else "no"
            r["ts"] = time.time()
        return True

    def stage_result(self, ip):
        """客户端轮询结果：pending / ok / no（没有申请过返回空状态）。"""
        with self._lock:
            r = self.stage_reqs.get(ip)
            if r is None:
                return {"status": "", "stage": -1}
            return {"status": str(r.get("status") or ""),
                    "stage": int(r.get("stage", -1))}

    def rename_client(self, ip, name):
        """主机改某台客户端的显示名（覆盖客户端上报的名字）。返回是否成功。"""
        name = str(name or "").strip()[:20]
        if not name:
            return False
        with self._lock:
            if ip not in self.clients:
                return False
            self.clients[ip]["name"] = name
            self.name_overrides[ip] = name
        self.on_event("clients", None)
        return True

    def set_phone_access(self, flag):
        self.phone_access = bool(flag)
        self.on_event("clients", None)

    # -------------------------------------------------------- 移除 / 黑名单
    def kick(self, ip):
        """移除连接：把这台电脑踢下线（对方会自动断开，之后仍可重新连接）。"""
        with self._lock:
            self.clients.pop(ip, None)
            self.kicked[ip] = time.time() + 60.0
        self.on_event("clients", None)

    def block(self, ip, name=""):
        """加入黑名单：不再接受这台电脑的任何连接（直到移出黑名单）。"""
        with self._lock:
            self.clients.pop(ip, None)
            self.blocked[ip] = {"name": name or "", "time": time.time()}
        self.on_event("clients", None)

    def unblock(self, ip):
        """移出黑名单。"""
        with self._lock:
            self.blocked.pop(ip, None)
        self.on_event("clients", None)

    def set_blocked(self, items):
        """启动共享时恢复黑名单（items: [{ip, name, time}]）。"""
        with self._lock:
            self.blocked = {
                str(i.get("ip") or ""): {"name": str(i.get("name") or ""),
                                         "time": float(i.get("time") or 0.0)}
                for i in (items or []) if str(i.get("ip") or "")}

    def blocked_snapshot(self):
        with self._lock:
            return [{"ip": ip, "name": b.get("name") or "",
                     "time": b.get("time") or 0}
                    for ip, b in sorted(self.blocked.items())]

    # ------------------------------------------------------------ 访问日志
    def access_log(self):
        """懒加载访问日志：日志目录跟着数据库走（<data>/logs）。"""
        if self._access is None:
            try:
                st = self.get_store()
                root = os.path.join(os.path.dirname(os.path.abspath(st.path)),
                                    "logs")
                self._access = AccessLog(root)
            except Exception:
                return None
        return self._access

    def audit_log(self, ip, method, path, status):
        """记一条访问日志（《网络安全法》第 23 条：留存不少于六个月）。"""
        try:
            log = self.access_log()
            if log is not None:
                log.write(ip, method, path, status)
        except Exception:
            pass

    def _gate(self, ip):
        """黑名单 / 被移除检查：返回 (http_code, body) 或 None。"""
        with self._lock:
            if ip in self.blocked:
                return 403, {"ok": False, "blocked": True,
                             "error": "本机已被主机加入黑名单，无法连接（请联系主机移出黑名单）"}
            k = self.kicked.get(ip)
            if k is not None:
                if time.time() <= k:
                    return 403, {"ok": False, "kicked": True,
                                 "error": "主机已移除本机的连接，请重新连接"}
                del self.kicked[ip]
        return None

    def snapshot(self):
        with self._lock:
            items = []
            for ip, c in self.clients.items():
                try:
                    st = int(c.get("stage", -1))
                except (TypeError, ValueError):
                    st = -1
                items.append({"ip": ip, "name": c.get("name") or "未知电脑",
                              "id": c.get("id") or "",
                              "allowed": bool(self.default_allow or c.get("allowed")),
                              "explicit": bool(c.get("allowed")),
                              "stage": st,
                              "last_seen": c.get("last_seen") or 0,
                              "requests": c.get("requests") or 0})
        items.sort(key=lambda x: -x["last_seen"])
        return items

    def _touch(self, ip, name="", cid=""):
        now = time.time()
        with self._lock:
            c = self.clients.get(ip)
            new = c is None
            if new:
                c = {"name": "", "id": "", "allowed": False, "stage": -1,
                     "last_seen": 0.0, "requests": 0}
                self.clients[ip] = c
            if ip in self.name_overrides:
                c["name"] = self.name_overrides[ip]   # 主机改过名，以主机为准
            elif name:
                c["name"] = name
            if cid:
                c["id"] = cid
            c["last_seen"] = now
        if new:
            self.on_event("clients", None)
        return c

    # ------------------------------------------------------------ 请求处理
    def info_for(self, ip):
        store = self.get_store()
        try:
            rev = store.revision()
        except Exception:
            rev = 0
        try:
            wh = self.get_warehouse() or ""
        except Exception:
            wh = ""
        return {"ok": True, "app": APP_NAME, "version": APP_VERSION,
                "warehouse": wh, "rev": rev,
                "can_write": self.can_write(ip),
                "default_allow": self.default_allow,
                "port": self.port}

    def handle_rpc(self, ip, payload):
        """返回 (http_code, 响应体)。"""
        gate = self._gate(ip)
        if gate:
            return gate
        code = str(payload.get("code") or "")
        if not self._code_ok(code):
            return 401, {"ok": False, "error": "连接码不正确", "need_code": True}
        method = str(payload.get("method") or "")
        self._touch(ip, str(payload.get("name") or ""), str(payload.get("id") or ""))
        if method not in RPC_METHODS:
            return 400, {"ok": False, "error": "不支持的操作：%s" % method}
        if method in BLOCKED_METHODS:
            return 400, {"ok": False, "error": "该操作只能在主机上执行"}
        args = payload.get("args") or []
        kwargs = payload.get("kwargs") or {}
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            return 400, {"ok": False, "error": "参数格式不正确"}
        # 制作流程不需要「允许录入」授权；各电脑在制作流程页自己选工位，
        # 只能推进停在自己这一站的单（这里做服务端校验，主机界面同样受约束）
        if method in WF_METHODS:
            try:
                claimed = int(payload.get("wf_stage", -1))
            except (TypeError, ValueError):
                claimed = -1
            with self._lock:
                c = self.clients.get(ip)
                if c is not None:
                    c["stage"] = claimed      # 让主机列表能看到各电脑选的工位
            err = self._wf_stage_error(claimed, method, args, kwargs,
                                       station=str(payload.get("wf_station") or ""))
            if err:
                return 403, {"ok": False, "stage_denied": True, "error": err}
        elif method in WRITE_METHODS and not self.can_write(ip):
            if not (method in WF_PHOTO_METHODS and _wf_photo_call(args, kwargs)):
                return 403, {"ok": False, "readonly": True,
                             "error": "主机未授权本机录入（只读模式）"}
        try:
            store = self.get_store()
            with self._lock:
                cname = (self.clients.get(ip) or {}).get("name") or ""
            src = ("电脑·%s" % cname) if cname else ("电脑(%s)" % ip)
            with store.as_source(src):
                result = getattr(store, method)(*args, **kwargs)
        except TypeError as e:
            return 400, {"ok": False, "error": "参数不匹配：%s" % e}
        except Exception as e:
            return 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        return 200, {"ok": True, "result": result}

    def _wf_stage_error(self, st, method, args, kwargs, station=""):
        """工位校验：电脑只能推进停在自己这一站的单。

        st 由客户端在每次请求里上报（制作流程页顶部的「本机工位」）。
        v1.42.3 起「不限」只留给主机：客户端上报 -1 说明还没选工位，
        直接拒绝，避免任何一台工位电脑都能替别人推进。
        """
        if st < 0:
            return ("本机还没选工位，请先在制作流程页右上角选择你负责的节点"
                    "（「不限」只在主机上可用）")
        store = self.get_store()
        try:
            stages = store.wf_stages()
        except Exception:
            stages = []

        def sname(i):
            return stages[i] if 0 <= i < len(stages) else ("节点%d" % (i + 1))

        if method == "wf_create":
            if st != 0:
                return "本机是「%s」工位，不能发起制作单" % sname(st)
            return ""
        if method == "wf_stock_in":
            # 入库：单据必须已经到最后一步；由最后一站或倒数第二站（刚推进来的）操作
            wf_id = kwargs.get("wf_id")
            if wf_id is None and args:
                wf_id = args[0]
            try:
                rec = store.wf_one(int(wf_id))
            except Exception:
                rec = None
            if not rec:
                return "制作单不存在"
            last = max(0, len(stages) - 1)
            if int(rec.get("stage") or 0) != last:
                return "该单还没到「%s」，不能入库" % sname(last)
            if st not in (last, last - 1):
                return ("本机是「%s」工位，入库只能由「%s」或「%s」操作"
                        % (sname(st), sname(max(0, last - 1)), sname(last)))
            return ""
        if method == "wf_finish":
            # 结单（不新增库存）：单据必须到最后一步，且由最后一站操作
            wf_id = kwargs.get("wf_id")
            if wf_id is None and args:
                wf_id = args[0]
            try:
                rec = store.wf_one(int(wf_id))
            except Exception:
                rec = None
            if not rec:
                return "制作单不存在"
            last = max(0, len(stages) - 1)
            if int(rec.get("stage") or 0) != last:
                return "该单还没到「%s」，不能结单" % sname(last)
            if st != last:
                return ("本机是「%s」工位，结单请由「%s」操作"
                        % (sname(st), sname(last)))
            return ""
        if method == "wf_set_urgent":
            return ""              # 标加急 / 取消加急：任何工位都可以
        if method not in WF_MOVE_METHODS:
            return ("本机是「%s」工位，只能推进本站的单，"
                    "取消 / 删除请到主机上操作" % sname(st))
        wf_id = kwargs.get("wf_id")
        if wf_id is None and args:
            wf_id = args[0]
        try:
            rec = store.wf_one(int(wf_id))
        except Exception:
            rec = None
        if not rec:
            return "制作单不存在"
        cur = int(rec.get("stage") or 0)
        if cur != st:
            return ("该单现在在「%s」，本机负责「%s」，只能在本站操作"
                    % (sname(cur), sname(st)))
        owner = str(rec.get("station") or "")
        if owner and owner != (station or ""):
            return ("这张单指定交给「%s」工位，本机工位是「%s」，不能接"
                    % (owner, station or sname(st)))
        return ""

    def _code_ok(self, code):
        try:
            return hmac.compare_digest(str(code), str(self.code))
        except Exception:
            return False


def _make_handler(srv):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CangGuanJia/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        # ---------------------------------------------------- 工具
        def _client_ip(self):
            return self.client_address[0]

        def _send(self, http_code, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            srv.audit_log(self._client_ip(), self.command,
                          urlparse(self.path).path, http_code)
            try:
                self.send_response(http_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                pass

        def _send_full(self, http_code, body, extra_headers=()):
            """body 为 dict（发 JSON）或 bytes（Content-Type 由 extra_headers 给出）。"""
            srv.audit_log(self._client_ip(), self.command,
                          urlparse(self.path).path, http_code)
            try:
                if isinstance(body, dict):
                    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                    ctype = "application/json; charset=utf-8"
                else:
                    data = body
                    ctype = ""
                self.send_response(http_code)
                if ctype:
                    self.send_header("Content-Type", ctype)
                for k, v in extra_headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                pass

        def _query(self):
            q = parse_qs(urlparse(self.path).query)
            return {k: (v[0] if v else "") for k, v in q.items()}

        # ---------------------------------------------------- GET /ping /m
        def do_GET(self):
            path = urlparse(self.path).path
            if not (path.startswith("/ping") or path == "/m" or path == "/m/"
                    or path.startswith("/m/api/") or path.startswith("/stage_result")):
                return self._send(404, {"ok": False, "error": "not found"})
            ip = self._client_ip()
            gate = srv._gate(ip)
            if gate:
                return self._send(*gate)
            if (path == "/m" or path == "/m/" or path.startswith("/m/api/")) \
                    and not srv.phone_access:
                return self._send(403, {"ok": False,
                                        "error": "主机已关闭手机访问"})
            if path == "/m" or path == "/m/":
                return self._send_full(*handle_page())
            if path.startswith("/m/api/"):
                # 手机端：会话 Cookie 鉴权（黑名单已在上面 _gate 拦过）
                token = _token_from(self.headers)
                q = self._query()
                if path.startswith("/m/api/whoami"):
                    return self._send_full(*handle_whoami(srv, ip, token))
                if path.startswith("/m/api/items"):
                    return self._send_full(*handle_items(srv, ip, token, q))
                if path.startswith("/m/api/sales"):
                    return self._send_full(*handle_sales(srv, ip, token, q))
                if path.startswith("/m/api/stats"):
                    return self._send_full(*handle_stats(srv, ip, token, q))
                if path.startswith("/m/api/returns"):
                    return self._send_full(*handle_returns(srv, ip, token, q))
                if path.startswith("/m/api/customers"):
                    return self._send_full(*handle_customers(srv, ip, token, q))
                if path.startswith("/m/api/trash"):
                    return self._send_full(*handle_trash(srv, ip, token, q))
                if path.startswith("/m/api/stocktake"):
                    return self._send_full(*handle_stocktake(srv, ip, token, q))
                if path.startswith("/m/api/coltitles"):
                    return self._send_full(*handle_coltitles(srv, ip, token))
                if path.startswith("/m/api/wf"):
                    return self._send_full(*handle_wf(srv, ip, token, q))
                if path.startswith("/m/api/photos"):
                    return self._send_full(*handle_photos(srv, ip, token, q))
                if path.startswith("/m/api/photo_get"):
                    return self._send_full(*handle_photo_get(srv, ip, token, q))
                return self._send(404, {"ok": False, "error": "not found"})
            # 工位变更申请的结果（客户端轮询）
            if path.startswith("/stage_result"):
                q = self._query()
                if not srv._code_ok(q.get("code", "")):
                    return self._send(401, {"ok": False, "error": "连接码不正确"})
                res = srv.stage_result(ip)
                return self._send(200, {"ok": True, "status": res["status"],
                                        "stage": res["stage"]})
            # /ping（电脑客户端 4 秒轮询）
            q = self._query()
            if not srv._code_ok(q.get("code", "")):
                return self._send(401, {"ok": False, "error": "连接码不正确",
                                        "need_code": True})
            srv._touch(ip, q.get("name", ""), q.get("id", ""))
            info = srv.info_for(ip)
            info["clients"] = len(srv.clients)
            return self._send(200, info)

        # ---------------------------------------------------- POST /rpc /m
        def do_POST(self):
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except Exception:
                length = 0
            if length <= 0 or length > 64 * 1024 * 1024:
                return self._send(400, {"ok": False, "error": "请求体为空或过大"})
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as e:
                return self._send(400, {"ok": False, "error": "请求不是合法 JSON：%s" % e})
            ip = self._client_ip()
            gate = srv._gate(ip)
            if gate:
                return self._send(*gate)
            if (path == "/m/login" or path == "/m/logout"
                    or path.startswith("/m/api/")) and not srv.phone_access:
                return self._send(403, {"ok": False,
                                        "error": "主机已关闭手机访问"})
            if path == "/m/login":
                code, body, hdrs = srv.mobile.login(
                    ip, str((payload or {}).get("code") or ""), srv._code_ok,
                    app_mode=bool((payload or {}).get("app")))
                if code == 200:
                    srv.on_event("clients", None)   # 手机登录 → 主机弹窗即时刷新在线列表
                return self._send_full(code, body, hdrs)
            if path == "/m/logout":
                token = _token_from(self.headers)
                return self._send_full(*handle_logout(srv, ip, token))
            if path.startswith("/m/api/"):
                token = _token_from(self.headers)
                st_ = srv.get_store()
                with st_.as_source("手机(%s)" % ip):
                    if path.startswith("/m/api/sell"):
                        return self._send_full(*handle_sell(srv, ip, token, payload))
                    if path.startswith("/m/api/return_sale"):
                        return self._send_full(*handle_return_sale(srv, ip, token, payload))
                    if path.startswith("/m/api/sale_undo"):
                        return self._send_full(*handle_sale_undo(srv, ip, token, payload))
                    if path.startswith("/m/api/del"):
                        return self._send_full(*handle_del_item(srv, ip, token, payload))
                    if path.startswith("/m/api/restore"):
                        return self._send_full(*handle_restore(srv, ip, token, payload))
                    if path.startswith("/m/api/purge"):
                        return self._send_full(*handle_purge(srv, ip, token, payload))
                    if path.startswith("/m/api/stocktake"):
                        return self._send_full(*handle_stocktake(srv, ip, token, None, payload))
                    if path.startswith("/m/api/settle"):
                        return self._send_full(*handle_settle(srv, ip, token, payload))
                    if path.startswith("/m/api/add"):
                        return self._send_full(*handle_add(srv, ip, token, payload))
                    if path.startswith("/m/api/update_all"):
                        return self._send_full(*handle_update_all(srv, ip, token, payload))
                    if path.startswith("/m/api/request_write"):
                        return self._send_full(*handle_request_write(srv, ip, token))
                    if path.startswith("/m/api/m_item"):
                        return self._send_full(*handle_m_item(srv, ip, token, payload))
                    if path.startswith("/m/api/m_sale"):
                        return self._send_full(*handle_m_sale(srv, ip, token, payload))
                    if path.startswith("/m/api/coltitles"):
                        return self._send_full(*handle_coltitles(srv, ip, token, payload))
                    if path.startswith("/m/api/wf"):
                        return self._send_full(*handle_wf(srv, ip, token, None,
                                                          payload))
                    if path.startswith("/m/api/photo_check"):
                        return self._send_full(*handle_photo_check(
                            srv, ip, token, payload))
                    if path.startswith("/m/api/photo_add"):
                        return self._send_full(*handle_photo_add(srv, ip, token, payload))
                    if path.startswith("/m/api/photo_del"):
                        return self._send_full(*handle_photo_del(srv, ip, token, payload))
                return self._send(404, {"ok": False, "error": "not found"})
            if path.startswith("/request_write"):
                if not srv._code_ok(str(payload.get("code") or "")):
                    return self._send(401, {"ok": False, "error": "连接码不正确"})
                name = str(payload.get("name") or "") or "未知电脑"
                c = srv._touch(ip, name, str(payload.get("id") or ""))
                if srv.can_write(ip):
                    return self._send(200, {"ok": True, "already": True})
                with srv._lock:
                    c["requests"] = int(c.get("requests") or 0) + 1
                srv.on_event("request", {"ip": ip, "name": name})
                return self._send(200, {"ok": True})
            if path.startswith("/request_stage"):
                if not srv._code_ok(str(payload.get("code") or "")):
                    return self._send(401, {"ok": False, "error": "连接码不正确"})
                name = str(payload.get("name") or "") or "未知电脑"
                srv._touch(ip, name, str(payload.get("id") or ""))
                srv.request_stage(ip, payload.get("stage", -1), name)
                return self._send(200, {"ok": True})
            if not path.startswith("/rpc"):
                return self._send(404, {"ok": False, "error": "not found"})
            http_code, body = srv.handle_rpc(ip, payload or {})
            return self._send(http_code, body)

    return Handler
