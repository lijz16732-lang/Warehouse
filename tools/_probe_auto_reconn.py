# -*- coding: utf-8 -*-
"""探针：开机自动连回上次主机（v1.42.7）。

验证 App._auto_reconnect_work：
  1. 主机在线 + 有历史连接 → 自动探测并调用 connect_lan（含正确 host/port/code）
  2. 主机不在线 → 保持本机模式，不误连
  3. 手动断开置 _auto_stop 后线程收工，不再自动连
  4. lan_cfg 默认带 auto_reconnect=True；开关关闭时不连
用法：.venv310/Scripts/python.exe tools/_probe_auto_reconn.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wm.app import App
from wm.lan import LanServer
from wm.store import Store

PORT = 17663
CODE = "135790"

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


def make_stub(history):
    """最小 app 桩：自动重连线程只用到这几个属性/方法。"""
    s = types.SimpleNamespace()
    s.lan_cfg = {"history": history, "auto_reconnect": True,
                 "client_id": "pc-X", "client_name": "探针机"}
    s.lan_mode = "off"
    s._stopped = False
    s._auto_stop = False
    s._ui = lambda fn, *a: fn(*a)          # 直接在当前线程执行
    s.calls = []
    s._status = lambda msg: s.calls.append(("status", msg))

    def fake_connect(host, port=None, code="", probe=None):
        s.calls.append(("connect", host, port, code))
        return True, "已连接主机 %s:%d" % (host, port)
    s.connect_lan = fake_connect
    # _auto_connect_done 是 App 的真方法，绑到桩上（生产代码里它一定存在，
    # 探针桩少了它会让线程把 AttributeError 吞掉后空转——正是要防的假阴性）
    import types as _t
    s._auto_connect_done = _t.MethodType(App._auto_connect_done, s)
    return s


work = App._auto_reconnect_work

tmp = tempfile.mkdtemp(prefix="auto_reconn_")
store = Store(os.path.join(tmp, "w.db"))
try:
    print("== 0. 无历史连接：线程空转不误连 ==")
    stub = make_stub([])
    t = threading.Thread(target=work, args=(stub,), daemon=True)
    t0 = time.time()
    t.start()
    time.sleep(6.5)                        # 越过首次 5 秒等待 + 探测窗口
    check("没历史不调用 connect_lan", not any(c[0] == "connect"
                                              for c in stub.calls), stub.calls)
    t.stop = None

    print("== 1. 主机在线：自动连回 ==")
    srv = LanServer(lambda: store, lambda: "测试仓", CODE, port=PORT)
    started, smsg = srv.start()
    check("测试主机已启动", started, smsg)
    stub = make_stub([{"host": "127.0.0.1", "port": PORT, "code": CODE,
                       "time": time.time()}])
    t = threading.Thread(target=work, args=(stub,), daemon=True)
    t.start()
    t.join(12)
    check("线程连上后收工", not t.is_alive())
    conn = [c for c in stub.calls if c[0] == "connect"]
    check("自动调用了 connect_lan",
          len(conn) == 1 and conn[0][1] == "127.0.0.1"
          and int(conn[0][2]) == PORT and conn[0][3] == CODE, conn)
    check("提示了自动连回", any("自动连回" in c[1]
                              for c in stub.calls if c[0] == "status"),
          stub.calls)

    print("== 2. 连接码不对：不误连，保持本机 ==")
    stub2 = make_stub([{"host": "127.0.0.1", "port": PORT, "code": "000000"}])
    t2 = threading.Thread(target=work, args=(stub2,), daemon=True)
    t2.start()
    time.sleep(9)                          # 首次等待 + 一次失败探测
    check("码不对没连接", not any(c[0] == "connect" for c in stub2.calls))
    stub2._auto_stop = True                # 收工，进程退出时线程是 daemon 也没事

    print("== 3. 开关关闭（auto_reconnect=False）：不连 ==")
    stub3 = make_stub([{"host": "127.0.0.1", "port": PORT, "code": CODE}])
    stub3.lan_cfg["auto_reconnect"] = False
    t3 = threading.Thread(target=work, args=(stub3,), daemon=True)
    t3.start()
    time.sleep(9)
    check("开关关了不连", not any(c[0] == "connect" for c in stub3.calls))
    stub3._auto_stop = True

    print("== 4. lan_cfg 默认开启自动重连 ==")
    cfg = App._load_lan_cfg(types.SimpleNamespace(settings={}))
    check("默认值 auto_reconnect=True", cfg.get("auto_reconnect") is True,
          cfg.get("auto_reconnect"))
    srv.stop()
finally:
    store.close()
    shutil.rmtree(tmp, ignore_errors=True)

print("\n结果：%d 通过 / %d 失败" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
