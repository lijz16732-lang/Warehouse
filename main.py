# -*- coding: utf-8 -*-
"""仓管家 · 仓库管理系统 —— 程序入口。"""

import os
import sys


def _bootstrap():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def main():
    _bootstrap()
    # 开启 DPI 感知：Win10/Win11 笔记本常见 125%/150% 缩放，不开启会整窗发虚。
    # 必须在创建任何 Tk 窗口之前调用。
    try:
        from wm.screen import enable_dpi_awareness
        enable_dpi_awareness()
    except Exception:
        pass
    # 主题（浅色/深色）必须在导入界面模块之前应用：各界面模块用
    # from-import 把颜色常量绑定进自己的命名空间，导入后就改不动了。
    # settings.json 在数据目录里，这里用同样的解析逻辑提前读一次。
    try:
        import json
        from wm import constants as C
        with open(os.path.join(C.resolve_data_dir(), "settings.json"),
                  encoding="utf-8") as f:
            _st = json.load(f)
        C.apply_palette(_st.get("ui_theme") or "light")
    except Exception:
        from wm import constants as C
        C.apply_palette("light")
    # Windows 任务栏正确显示程序图标（tkinter 默认用 python 启动器图标分组）
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "canguanjia.warehouse.manager")
    except Exception:
        pass
    try:
        from wm.app import App
    except Exception as e:  # 启动失败时给出可读提示
        import tkinter.messagebox as mb
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        mb.showerror("启动失败", "程序无法启动：\n%s" % e)
        return 1

    import tkinter as tk
    root = tk.Tk()
    try:
        # 先设图标再构建界面，避免窗口/任务栏闪现默认图标
        try:
            if getattr(sys, "_MEIPASS", None):
                cand = os.path.join(sys._MEIPASS, "assets", "app.ico")
                if os.path.exists(cand):
                    root.iconbitmap(cand)
            else:
                ico = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "assets", "app.ico")
                if os.path.exists(ico):
                    root.iconbitmap(ico)
        except Exception:
            pass
        App(root)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            import tkinter.messagebox as mb
            mb.showerror("启动失败", "初始化界面时出错：\n%s" % e)
        except Exception:
            pass
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
