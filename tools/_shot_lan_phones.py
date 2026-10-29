# -*- coding: utf-8 -*-
"""临时脚本：手机连接列表 UI 探针 —— 离线创建 LanDialog 截图验证布局。"""
import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import screenshot  # noqa: E402
from wm import lanui  # noqa: E402


class FakeApp(object):
    fam = "Microsoft YaHei"
    lan_mode = "host"
    lan_dlg = None
    lan_server = None
    lan_cfg = {}

    def lan_status(self):
        return {"mode": "host", "running": True, "ips": ["192.168.1.10"],
                "port": 8765, "code": "123456", "clients": [],
                "default_allow": False}

    def _refresh_lan_dialog(self):
        pass


class FakeSrv(object):
    class mobile(object):
        @staticmethod
        def count():
            return 2

        @staticmethod
        def sessions_info():
            return [{"ip": "192.168.1.35", "app": True,
                     "expires": 9e9, "last": 9e9 - 40},
                    {"ip": "192.168.1.36", "app": False,
                     "expires": 9e9, "last": 9e9 - 300}]

        @staticmethod
        def blocked_snapshot():
            return []


root = tk.Tk()
root.withdraw()
app = FakeApp()
app.lan_server = FakeSrv()
dlg = lanui.LanDialog(root, app)
dlg.update()
out = os.path.join(ROOT, ".tmpdbg", "lan_phones.png")
screenshot.capture_window("局域网", out)
print("saved", out, dlg.winfo_width(), dlg.winfo_height())
dlg.destroy()
root.destroy()
