# -*- coding: utf-8 -*-
"""App 直接用 /m 页的模拟器联调服务端：临时库 + 已知连接码，专供真机/模拟器手动测试。

用法：./.venv310/Scripts/python.exe tools/_probe_app_m.py [端口]   （默认 17653，Ctrl+C 退出）
连接码 246810；默认允许录入（default_allow=True）。
"""
import os
import socket
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wm.lan import LanServer  # noqa: E402
from wm.store import Store  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 17653
tmp = tempfile.mkdtemp(prefix="probe_appm_")
st = Store(os.path.join(tmp, "t.db"))

# 造几条库存，界面有东西可看
for i in range(3):
    code = st.generate_codes(1)[0]
    st.insert({"code": code, "brand": "施耐德", "category": "断路器",
               "model": "S10MD-%d" % i, "price": 128.0 + i, "qty": 1 + i,
               "shelf": "%d排A-%d" % (i + 1, i + 1), "listed": 1, "remark": ""})

srv = LanServer(lambda: st, lambda: "主仓", "246810", PORT)
srv.default_allow = True          # 免审批：手机可直接录入
ok, msg = srv.start()
print("server:", msg)
print("tmp:", tmp)

ips = []
try:
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = info[4][0]
        if ip not in ips and not ip.startswith("127."):
            ips.append(ip)
except Exception:
    pass
print("connect base options:")
for ip in ips:
    print("   http://%s:%d/m" % (ip, PORT))

while True:
    time.sleep(3600)
