# -*- coding: utf-8 -*-
"""屏幕自适应：桌面工作区、DPI 缩放、Win10 / Win11 差异、窗口与弹窗尺寸建议。

设计目标：同一份程序在笔记本（1366×768 / 1920×1080 高缩放）和台式大屏
（1920×1080 / 2560×1440）上都能完整显示，不被任务栏遮住、不因为 DPI
缩放而模糊或挤成一团。

纯计算函数（fit_window / fit_dialog / clamp_saved）不依赖 Tk，便于单元测试；
读取工作区、DPI、系统版本时任何异常都安全降级到保守默认值。
"""

import ctypes
import sys

BASE_W, BASE_H = 1440, 900          # 100% 缩放下的设计基准窗口
MIN_W, MIN_H = 1080, 660            # 最小可用尺寸（布局在这之上才完整）
COMPACT_W, COMPACT_H = 1280, 760    # 工作区小于此值视为小屏（笔记本），直接最大化
MAX_SCALE = 1.5                     # DPI 放大上限，再大只会让界面变笨重

SPI_GETWORKAREA = 0x0030
LOGPIXELSX = 88


# ------------------------------------------------------------ 系统信息
def os_build():
    """Windows 内部版本号；非 Windows 返回 0。"""
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def is_win11(build=None):
    """Win11 从内部版本 22000 开始；Win10 为 10240~19045。"""
    b = os_build() if build is None else int(build or 0)
    return b >= 22000


def dpi_scale():
    """系统 DPI / 96，按 0.25 档取整（1.0 / 1.25 / 1.5 …）。

    未开启 DPI 感知的进程会拿到虚拟化的 96，正好对应它实际的渲染比例。
    """
    try:
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        hdc = user32.GetDC(0)
        try:
            dpi = int(gdi32.GetDeviceCaps(hdc, LOGPIXELSX))
        finally:
            user32.ReleaseDC(0, hdc)
        if dpi:
            return max(1.0, min(MAX_SCALE, round(dpi / 96.0 * 4) / 4.0))
    except Exception:
        pass
    return 1.0


def work_area():
    """桌面工作区 (x, y, w, h)，已排除任务栏；取不到返回 None。

    注意：Win11 默认任务栏比 Win10 高，靠工作区取尺寸可以自动适配。
    """
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        r = RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
        if ok:
            w, h = r.right - r.left, r.bottom - r.top
            if w >= 640 and h >= 480:
                return int(r.left), int(r.top), int(w), int(h)
    except Exception:
        pass
    return None


def enable_dpi_awareness():
    """开启系统级 DPI 感知，避免高缩放笔记本上文字发虚。返回 1/0 表示级别。

    必须在创建 Tk 之前调用（main.py 里最先执行）。

    注意：刻意用「系统级」而不是「按显示器（per-monitor）」——
    Tk 8.6 在 per-monitor 模式下拖动改变窗口大小时内容会变白/消失（不重绘），
    系统级没有这个问题，清晰度在本屏（登录 DPI）下完全一样。
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # SYSTEM_AWARE
        return 1
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()           # 老系统等价接口
        return 1
    except Exception:
        return 0


def screen_metrics(root=None, scale=None, area=None, build=None):
    """汇总当前屏幕指标，供 fit_window / fit_dialog 使用。

    root 用于在取不到工作区时兜底（Tk 的屏幕尺寸）；
    其余参数可在测试里注入，不必依赖真实屏幕。
    """
    sw = sh = 0
    if root is not None:
        try:
            sw, sh = int(root.winfo_screenwidth()), int(root.winfo_screenheight())
        except Exception:
            sw = sh = 0
    wa = work_area() if area is None else area
    if wa:
        x, y, w, h = wa
    else:
        x, y = 0, 0
        w, h = (sw or 1920), (sh or 1080)
    sc = dpi_scale() if scale is None else float(scale)
    b = os_build() if build is None else int(build)
    return {"x": int(x), "y": int(y), "w": int(w), "h": int(h),
            "scale": float(sc), "build": b, "win11": b >= 22000}


# ------------------------------------------------------------ 尺寸计算
def ui_scale(m=None):
    """界面元素（行高、内边距、侧栏宽度）的缩放系数。"""
    sc = (m or {}).get("scale", dpi_scale())
    return max(1.0, min(MAX_SCALE, float(sc)))


def fit_window(m, saved=None, scale=None):
    """算出主窗口尺寸与位置。

    返回 dict：w, h, x, y, maxed(是否最大化), min_w, min_h, compact, scale

    · 小屏（工作区 < 1280×760）：直接最大化，保证工具栏、表格、分页都在屏幕内；
    · 大屏：基准 1440×900 按 DPI 放大，最多占工作区 94% × 92%；
    · saved：上次保存的 "宽x高"，超出当前屏幕时自动收缩而不是照搬。
    """
    sc = float(m.get("scale", 1.0) if scale is None else scale)
    sc = max(1.0, min(MAX_SCALE, sc))
    ww, wh = int(m["w"]), int(m["h"])
    compact = ww < COMPACT_W or wh < COMPACT_H
    # Win11 标题栏比 Win10 略高，垂直方向多留一点余量
    extra = 8 if m.get("win11") else 0
    max_w = max(640, int(ww * 0.94))
    max_h = max(480, int(wh * 0.92) - extra)

    w = min(int(BASE_W * sc), max_w)
    h = min(int(BASE_H * sc), max_h)
    w = min(max(w, min(int(MIN_W * sc), max_w)), max_w)
    h = min(max(h, min(int(MIN_H * min(sc, 1.2)), max_h)), max_h)

    min_w = min(int(MIN_W * sc), max_w)
    min_h = min(int(MIN_H * sc), max_h)

    # 恢复上次大小：只在当前屏幕放得下时采用（换机器/换分辨率不会跑出屏幕）
    if saved:
        size = str(saved).split("+")[0].strip().lower()
        if "x" in size:
            try:
                sw_, sh_ = [int(float(v)) for v in size.split("x")[:2]]
                if min_w <= sw_ <= max_w and min_h <= sh_ <= max_h:
                    w, h = sw_, sh_
            except Exception:
                pass

    if compact:
        w, h = ww, wh
    x = int(m["x"]) + max(0, (ww - w) // 2)
    y = int(m["y"]) + max(0, (wh - h) // 2)
    return {"w": int(w), "h": int(h), "x": int(x), "y": int(y),
            "maxed": bool(compact), "min_w": int(min_w), "min_h": int(min_h),
            "compact": bool(compact), "scale": sc}


def fit_dialog(size, m, scale=None):
    """把弹窗尺寸收进工作区（笔记本上 730 高的窗口会超屏）。"""
    sc = max(1.0, min(MAX_SCALE, float(m.get("scale", 1.0) if scale is None
                                       else scale)))
    w, h = int(size[0]), int(size[1])
    max_w = max(360, int(m["w"] * 0.94))
    max_h = max(280, int(m["h"] * 0.92) - (10 if m.get("win11") else 0))
    # 只收缩、不无故放大：下限取一个很小的值，避免把 300×200 的小弹窗撑大
    return (min(max(int(w * sc), 120), max_w),
            min(max(int(h * sc), 80), max_h))


def clamp_position(x, y, w, h, m, margin=8):
    """把窗口位置限制在工作区内，避免标题栏跑到屏幕外拉不回来。"""
    wx, wy = int(m["x"]), int(m["y"])
    ww, wh = int(m["w"]), int(m["h"])
    x = max(wx, min(int(x), wx + ww - int(w) - margin))
    y = max(wy, min(int(y), wy + wh - int(h) - margin))
    return int(x), int(y)


def apply_tk_scaling(root, scale=None):
    """让 Tk 的点字号按真实 DPI 渲染（DPI 感知后必须显式对齐）。"""
    sc = dpi_scale() if scale is None else float(scale)
    try:
        root.tk.call("tk", "scaling", max(1.0, min(MAX_SCALE, sc)) * 96.0 / 72.0)
    except Exception:
        pass
