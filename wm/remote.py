# -*- coding: utf-8 -*-
"""客户端数据层：把主机（局域网服务）的数据方法原样代理过来。

对上层 UI 来说它就是 Store：同名方法、同样返回 dict / 列表 / (ok, msg)。
区别只有两点：
  · 数据每次从主机实时取，本机不存副本，所以永远是主机当前的数据；
  · 主机未授权录入时，写方法会抛 PermissionDenied（UI 弹「只读模式」提示）。
"""

import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .lan import RPC_METHODS
from .store import Store

# 这些方法本地算就行，不必把整表数据传回来
_STATIC = ("stats", "sales_totals", "out_totals")


class RemoteError(RuntimeError):
    """主机返回的业务/协议错误。"""


class PermissionDenied(RemoteError):
    """主机未授权录入。"""


class HostUnreachable(RemoteError):
    """网络不通 / 主机没开服务。"""


class RemoteStore(object):
    stats = staticmethod(Store.stats)
    sales_totals = staticmethod(Store.sales_totals)
    out_totals = staticmethod(Store.out_totals)

    def __init__(self, host, port, code, client_id="", client_name="", timeout=20):
        self.host = str(host or "").strip()
        self.port = int(port or 8765)
        self.code = str(code or "").strip()
        self.client_id = client_id or ("%s-%s" % (socket.gethostname(), id(self)))
        self.client_name = (client_name or socket.gethostname())[:40]
        self.timeout = timeout
        self.base = "http://%s:%d" % (self.host, self.port)
        self.path = "%s:%d（局域网主机）" % (self.host, self.port)
        self.last_ping = {}
        self.can_write = False        # 由 ping() 更新
        self.warehouse = ""
        self.rev = 0

    # ------------------------------------------------------------ 基础
    def close(self):
        pass

    def __getattr__(self, name):
        if name.startswith("_") or name in ("host", "port", "code", "client_id",
                                            "client_name", "timeout", "base", "path",
                                            "last_ping", "can_write", "warehouse", "rev"):
            raise AttributeError(name)
        if name not in RPC_METHODS:
            raise AttributeError(name)

        def rpc(*args, **kwargs):
            return self._post(name, args, kwargs)
        return rpc

    # ------------------------------------------------------------ HTTP
    def _post(self, method, args, kwargs, path="/rpc"):
        payload = {"code": self.code, "id": self.client_id,
                   "name": self.client_name, "method": method,
                   "args": list(args),
                   "kwargs": {k: v for k, v in (kwargs or {}).items()
                              if not callable(v)}}
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8") or "{}")
            except Exception:
                body = {}
            msg = body.get("error") or ("主机返回错误 %d" % e.code)
            if e.code == 403:
                raise PermissionDenied(msg)
            raise RemoteError(msg)
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise HostUnreachable("连不上主机 %s：%s" % (self.base, e))
        except ValueError as e:
            raise RemoteError("主机返回的不是合法数据：%s" % e)
        if not body.get("ok"):
            raise RemoteError(body.get("error") or "主机返回未知错误")
        return body.get("result")

    def ping(self):
        """取主机状态（会顺便刷新 can_write / rev / 仓库名）。"""
        q = urlencode({"code": self.code, "id": self.client_id,
                       "name": self.client_name})
        req = urllib.request.Request(self.base + "/ping?" + q)
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, 6)) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8") or "{}")
            except Exception:
                body = {}
            if e.code == 401:
                raise RemoteError(body.get("error") or "连接码不正确")
            raise RemoteError(body.get("error") or ("主机返回错误 %d" % e.code))
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise HostUnreachable("连不上主机 %s：%s" % (self.base, e))
        if not body.get("ok"):
            raise RemoteError(body.get("error") or "主机返回未知错误")
        self.last_ping = body
        self.can_write = bool(body.get("can_write"))
        self.warehouse = str(body.get("warehouse") or "")
        self.rev = int(body.get("rev") or 0)
        return body

    def request_write(self):
        """请主机授权录入（主机上会弹窗询问）。"""
        return self._post("", (), {}, path="/request_write")
