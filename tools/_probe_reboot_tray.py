# -*- coding: utf-8 -*-
"""v1.47.1 托盘图标热切换不累积探针。

外观热切换走 _soft_reboot（原地重建），旧 App 必须停掉 Shell_NotifyIcon
托盘图标（NIM_DELETE），否则每次切主题任务栏就多一个图标。
用假 tray 对象记录 stop() 调用，验证：
1. _soft_reboot 会 stop 托盘并清空 self.tray；
2. on_close 同样会 stop（原有行为不回退）；
3. 无托盘时 reboot 不报错。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk
import wm.app as wapp
from wm.store import Store

TMP = tempfile.mkdtemp(prefix="wm_rtray_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()

ok = [0, 0]


def check(label, cond):
    ok[0] += 1
    ok[1] += bool(cond)
    print("  %-42s %s" % (label, "OK" if cond else "FAIL"))


class FakeTray(object):
    def __init__(self):
        self.stopped = 0

    def stop(self):
        self.stopped += 1


def shutdown(root):
    try:
        for _aid in root.tk.call("after", "info"):
            root.after_cancel(_aid)
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def boot():
    root = tk.Tk()
    root.withdraw()
    app = wapp.App(root)
    root.update()
    return root, app


# ---- 1 _soft_reboot 停托盘 ----
root, app = boot()
tr = FakeTray()
app.tray = tr
app._soft_reboot()
check("_soft_reboot 调 tray.stop()", tr.stopped == 1)
check("_soft_reboot 清空 self.tray", app.tray is None)
check("_soft_reboot 置位 _reboot", app._reboot is True)
check("_soft_reboot 置位 _stopped", app._stopped is True)
try:
    root.destroy()
except Exception:
    pass

# ---- 2 on_close 停托盘（关闭到托盘场景除外）----
root, app = boot()
app.settings["close_to_tray"] = False     # 真正退出
tr = FakeTray()
app.tray = tr
app.on_close()
check("on_close 调 tray.stop()", tr.stopped == 1)
try:
    root.destroy()
except Exception:
    pass

# ---- 3 无托盘时 reboot 不报错 ----
root, app = boot()
app.tray = None
try:
    app._soft_reboot()
    no_tray_ok = True
except Exception:
    no_tray_ok = False
check("无托盘时 _soft_reboot 不报错", no_tray_ok)
try:
    root.destroy()
except Exception:
    pass

print("PROBE REBOOT TRAY: %d/%d" % (ok[1], ok[0]))
