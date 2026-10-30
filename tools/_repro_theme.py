# -*- coding: utf-8 -*-
"""验证 v1.24.1 外观热切换：深色界面 → _soft_reboot → 浅色界面原地重建。

模拟用户操作：深色模式下打开设置选浅色点「应用外观」。
全程不另起进程，验证 main() 循环重建路径 + 调色板生效。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk
from wm import constants as C


def boot(theme_check_tag):
    """按 settings.json 调色板建一个 App（与 main() 一致）。返回 (root, app)。"""
    import json
    try:
        with open(os.path.join(C.resolve_data_dir(), "settings.json"),
                  encoding="utf-8") as f:
            st = json.load(f)
        C.apply_palette(st.get("ui_theme") or "light")
    except Exception:
        C.apply_palette("light")
    root = tk.Tk()
    from wm.app import App
    app = App(root)
    print("[%s] App built, UI_THEME=%s CLR_BG=%s" % (theme_check_tag, C.UI_THEME, C.CLR_BG))
    return root, app


# ---- 第一段：深色启动 ----
root1, app1 = boot("phase1")
assert C.UI_THEME == "dark", "phase1 应为深色"

# 模拟在设置对话框里选了浅色并点「应用外观」
def simulate_apply():
    print("[phase1] user applies light theme -> _soft_reboot()")
    app1.settings["ui_theme"] = "light"
    app1._save_settings()
    app1._soft_reboot()

root1.after(1200, simulate_apply)
root1.mainloop()                       # _soft_reboot 会结束这个 mainloop
try:                                   # 与 main.py 一致：销毁前取消残留定时任务
    for _aid in root1.tk.call("after", "info"):
        root1.after_cancel(_aid)
except Exception:
    pass
root1.destroy()
print("[phase1] mainloop exited cleanly, _reboot =", app1._reboot)

# ---- 第二段：main() 循环重建（浅色）----
root2, app2 = boot("phase2")
assert C.UI_THEME == "light", "phase2 应为浅色"
print("[phase2] root bg =", repr(str(root2.cget("bg"))), " C.CLR_BG =", C.CLR_BG)
assert str(root2.cget("bg")).lower() == C.CLR_BG.lower(), "新窗口背景应为浅色"

def finish():
    app2.on_close()                    # 正常退出路径

root2.after(1200, finish)
root2.mainloop()
print("[phase2] closed normally, _reboot =", app2._reboot)
assert not app2._reboot
print("REPRO_OK: 深色→浅色原地重建成功，无报错")
