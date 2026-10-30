# -*- coding: utf-8 -*-
"""全局常量：字段定义、导入表头别名、配色与字体。"""

import os
import re
import sys
import unicodedata

APP_NAME = "仓管家 · 仓库管理系统"
APP_SHORT = "仓管家"
APP_VERSION = "1.24.1"


def app_icon_path():
    """返回 app.ico 的绝对路径；找不到返回 None。兼容源码运行与 PyInstaller 打包。"""
    if getattr(sys, "_MEIPASS", None):
        cand = os.path.join(sys._MEIPASS, "assets", "app.ico")
        if os.path.exists(cand):
            return cand
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(os.path.dirname(here), "assets", "app.ico")
    if os.path.exists(cand):
        return cand
    return None


def apply_window_icon(win):
    """给 Toplevel 弹窗设置程序图标（Windows 下弹窗不会可靠继承主窗口图标）。"""
    try:
        p = app_icon_path()
        if p:
            win.iconbitmap(p)
    except Exception:
        pass


def center_window(win, master=None, size=None, vertical_ratio=0.34, design=True,
                  force=False):
    """把窗口居中到主窗口（master），master 不可用时退回屏幕居中。

    - size: (宽, 高) 时按该尺寸摆放；否则用窗口自身请求尺寸（不改变大小）
    - vertical_ratio: 垂直位置比例，0.5 为正居中，略小于 0.5 视觉上更舒服
    - design: size 是否为「设计像素」。True 时按 DPI 缩放放大（弹窗写的是 100% 下的尺寸），
      传控件请求尺寸的调用方应传 False，避免二次放大
    - force: True 时强制把 size 写进 geometry。默认 False 时若尺寸没被 DPI 放大或
      屏幕收缩（scale=1.0 且装得下），只摆位置、让内容自动撑高（导入向导等窗口
      依赖这一点）；内部带滚动区的固定尺寸窗口（如局域网共享）需要 force=True

    居中基准是「桌面工作区」而不是整块屏幕：Win10 / Win11 任务栏高度不同，
    用工作区才不会让 730 高的弹窗压到任务栏下面或被裁掉。
    """
    try:
        win.update_idletasks()
        given = size is not None
        if given:
            w, h = int(size[0]), int(size[1])
        else:
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
            if w <= 1 or h <= 1:
                w, h = win.winfo_width(), win.winfo_height()

        from .screen import clamp_position, fit_dialog, screen_metrics
        m = screen_metrics(win)
        sc = m["scale"] if (given and design) else 1.0
        fw, fh = fit_dialog((w, h), m, scale=sc)

        base = master if master is not None else getattr(win, "master", None)
        bx = by = None
        bw = bh = 0
        try:
            if base is not None and base.winfo_exists():
                base.update_idletasks()
                bw, bh = base.winfo_width(), base.winfo_height()
                if bw <= 1 or bh <= 1:  # 主窗口尚未映射时用请求尺寸兜底
                    bw, bh = base.winfo_reqwidth(), base.winfo_reqheight()
                bx, by = base.winfo_rootx(), base.winfo_rooty()
        except Exception:
            bx = by = None

        if bx is None or bw <= 1 or bh <= 1:  # 没有可用主窗口 → 工作区居中
            x = m["x"] + (m["w"] - fw) // 2
            y = m["y"] + max(0, (m["h"] - fh) // 2 - int(m["h"] * 0.03))
        else:
            x = bx + (bw - fw) // 2
            y = by + int((bh - fh) * vertical_ratio)

        x, y = clamp_position(x, y, fw, fh, m)
        if force or (fw, fh) != (w, h):
            # 只有尺寸被 DPI 放大或被屏幕收缩时才改大小；否则只摆位置，
            # 让内容继续自动撑高（导入向导、批量编辑等窗口依赖这一点）
            win.geometry("%dx%d+%d+%d" % (fw, fh, x, y))
        else:
            win.geometry("+%d+%d" % (x, y))
    except Exception:
        pass

# --------------------------------------------------------------------------
# 字段定义 (key, 中文名, 类型, 默认列宽, 对齐, 是否可参与筛选)
# 类型: text / money / int / bool
# --------------------------------------------------------------------------
FIELDS = [
    ("code",      "编号",    "text",  140, "w",      True),
    ("brand",     "品牌",    "text",  120, "center", True),
    ("category",  "品类",    "text",  110, "center", True),
    ("model",     "型号",    "text",  150, "w",      False),
    ("condition", "成色",    "text",   95, "center", True),
    ("price",     "价格",    "money", 100, "e",      False),
    ("qty",       "数量",    "int",    80, "e",      False),
    ("shelf",     "货架",    "text",  110, "center", True),
    ("listed",    "上架状态", "bool",  100, "center", True),
    ("remark",    "备注",    "text",  260, "w",      False),
]

FIELD_KEYS    = [f[0] for f in FIELDS]
FIELD_LABEL   = {f[0]: f[1] for f in FIELDS}
FIELD_TYPE    = {f[0]: f[2] for f in FIELDS}
FIELD_WIDTH   = {f[0]: f[3] for f in FIELDS}
FIELD_ANCHOR  = {f[0]: f[4] for f in FIELDS}
FILTER_FIELDS = [f[0] for f in FIELDS if f[5]]

# 编辑弹窗中的字段分组（每行两个）
EDIT_ROWS = [
    ["code", "brand"],
    ["category", "model"],
    ["condition", "price"],
    ["qty", "shelf"],
    ["listed", None],
    ["remark"],
]

# --------------------------------------------------------------------------
# 导入时的表头别名（大小写、空格、括号单位都会被归一化后匹配）
# --------------------------------------------------------------------------
# 同一字段多列导入时的合并分隔符（如多货架：6排A-3 / 7排A-1）
MULTI_SEP = " / "

HEADER_ALIASES = {
    "code": ["编号", "商品编号", "货号", "编码", "商品编码", "款号", "序号", "sku", "code", "id", "no"],
    "brand": ["品牌", "牌子", "brand", "厂商", "牌"],
    "category": ["品类", "类目", "类别", "分类", "商品类目", "商品分类", "category", "type", "class"],
    "model": ["型号", "商品型号", "产品型号", "规格型号", "型号规格", "物料型号", "型号代码",
              "规格", "款式", "model", "spec", "version", "版本"],
    "condition": ["成色", "成色等级", "新旧程度", "新旧", "成色描述", "condition", "grade", "level"],
    "price": ["价格", "单价", "单格", "售价", "零售价", "销售价", "金额", "标价", "价格元", "price", "amount", "cost"],
    "qty": ["数量", "库存", "库存数量", "库存数", "件数", "数目", "qty", "quantity", "stock", "num"],
    "shelf": ["货架", "货架号", "货位", "储位", "库位", "仓位", "位置", "shelf", "location", "bin"],
    "listed": ["是否上架", "上架状态", "上架", "是否已上架", "在售状态", "销售状态", "状态", "listed",
               "onsale", "on_sale", "isshelf"],
    "remark": ["备注", "备注信息", "说明", "描述", "附注", "其他", "remark", "remarks", "note", "memo", "comment"],
}

# 上架状态的文本表达
LISTED_TRUE  = {"是", "y", "yes", "true", "1", "已上架", "上架", "在售", "在架", "上", "√", "✓", "有"}
LISTED_FALSE = {"否", "n", "no", "false", "0", "未上架", "下架", "已下架", "停售", "下", "×", "x", "无"}

LISTED_TEXT = {1: "已上架", 0: "未上架"}

# --------------------------------------------------------------------------
# 出库类型（登记出库时选择）
#   只有「销售」计入销售额 / 成本 / 利润 / 买家统计；
#   其余类型（报废、损耗、退货、借出、赠送、调拨、其他）只扣减库存并留痕，
#   金额字段留 0，不计入任何销售额口径。
# --------------------------------------------------------------------------
OUT_TYPE_SALE = "销售"
OUT_TYPES = ["销售", "报废", "损耗", "退货", "借出", "赠送", "调拨", "其他"]
# 各类型在界面上的补充说明
OUT_TYPE_HINT = {
    "销售": "正常卖出：计销售额、成本与利润",
    "报废": "损坏无法再售：只扣库存，不计销售额",
    "损耗": "丢失/自然损耗：只扣库存，不计销售额",
    "退货": "退回上游供应商：只扣库存，不计销售额",
    "借出": "借出待还：只扣库存，不计销售额",
    "赠送": "赠品/内部领用：只扣库存，不计销售额",
    "调拨": "调往其它仓/门店：只扣库存，不计销售额",
    "其他": "其它出库：只扣库存，不计销售额",
}

# --------------------------------------------------------------------------
# 「型号」匹配（导入时用它判断是否重复）
# --------------------------------------------------------------------------
# 这些值视为「没有型号」，不参与重复判定，一律作为新记录导入
MODEL_BLANK = {"", "-", "--", "---", "—", "/", "\\", "无", "无型号", "暂无", "未知",
               "待定", "待确认", "n/a", "na", "none", "null", "nil", "0", "无规格"}


def norm_model(value):
    """型号归一化：全角转半角、去首尾与中间多余空格、转小写。

    用于「是否重复」的比较，不改变原始文本（显示/导出仍用原值）。
    例：「ABB  PFEA111」与「abb pfea111」视为同一型号。
    """
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def is_blank_model(value):
    """判断是否属于「空型号」（不参与重复判定）。"""
    return norm_model(value) in MODEL_BLANK

# --------------------------------------------------------------------------
# 配色（浅色/深色两套调色板，启动时按 settings.json 的 ui_theme 应用；
# 切换主题需重启程序 —— Tk 控件颜色在构建时写死，热切换需重建全部界面）
# --------------------------------------------------------------------------
_PALETTE_LIGHT = {
    "CLR_BG":        "#EFF3F9",
    "CLR_CARD":      "#FFFFFF",
    "CLR_BORDER":    "#DCE3ED",
    "CLR_BORDER_LT": "#E9EEF5",
    "CLR_TEXT":      "#1F2A37",
    "CLR_MUTED":     "#6B7A8F",
    "CLR_HEAD_FG":   "#41506B",
    "CLR_ACCENT":    "#2563EB",
    "CLR_ACCENT_DK": "#1D4ED8",
    "CLR_ACCENT_LT": "#E8F0FE",
    "CLR_OK":        "#0E9F6E",
    "CLR_WARN":      "#F59E0B",
    "CLR_DANGER":    "#E02424",
    "CLR_PURPLE":    "#8B5CF6",
    "CLR_CYAN":      "#0891B2",
    "CLR_ROW_ALT":   "#F7FAFD",
    "CLR_SEL":       "#D8E6FE",
    "CLR_HEADER":    "#F3F6FB",
    "CLR_HEADER_HV": "#E7EDF7",
    "CLR_INPUT":     "#FFFFFF",
    "CLR_MENU_BG":   "#FFFFFF",
    "CLR_TAB_HV":    "#EDF1F8",
    "CLR_TROUGH":    "#E6ECF5",
    "CLR_SB":        "#C6D0DE",
    "CLR_SB_TR":     "#F4F7FB",
    "CLR_SB_HV":     "#ADBACC",
    "CLR_SB_PR":     "#96A6BC",
    "CLR_UNLISTED_BG": "#F1F3F7",
    "CLR_UNLISTED_FG": "#667085",
    "CLR_LOW_BG":    "#FFF3E2",
    "CLR_LOW_FG":    "#B54708",
    # 鼠标划过整行高亮（比选中色浅，避免与系统选中混淆）
    "CLR_HOVER_BG":  "#E9F1FF",
    "CLR_HOVER_EDGE": "#9CC0FF",
}

_PALETTE_DARK = {
    "CLR_BG":        "#141822",
    "CLR_CARD":      "#1B202B",
    "CLR_BORDER":    "#2A3140",
    "CLR_BORDER_LT": "#242B38",
    "CLR_TEXT":      "#E8ECF4",
    "CLR_MUTED":     "#7D8798",
    "CLR_HEAD_FG":   "#AAB3C5",
    "CLR_ACCENT":    "#3B82F6",
    "CLR_ACCENT_DK": "#2563EB",
    "CLR_ACCENT_LT": "#22304A",
    "CLR_OK":        "#2FB344",
    "CLR_WARN":      "#F0A132",
    "CLR_DANGER":    "#E5484D",
    "CLR_PURPLE":    "#A78BFA",
    "CLR_CYAN":      "#22D3EE",
    "CLR_ROW_ALT":   "#171C26",
    "CLR_SEL":       "#22304A",
    "CLR_HEADER":    "#1F2530",
    "CLR_HEADER_HV": "#242B38",
    "CLR_INPUT":     "#161B25",
    "CLR_MENU_BG":   "#1B202B",
    "CLR_TAB_HV":    "#242B38",
    "CLR_TROUGH":    "#242B38",
    "CLR_SB":        "#39435A",
    "CLR_SB_TR":     "#1B202B",
    "CLR_SB_HV":     "#4A5670",
    "CLR_SB_PR":     "#5A688A",
    "CLR_UNLISTED_BG": "#1F2530",
    "CLR_UNLISTED_FG": "#7D8798",
    "CLR_LOW_BG":    "#3A2C12",
    "CLR_LOW_FG":    "#F0A132",
    "CLR_HOVER_BG":  "#22304A",
    "CLR_HOVER_EDGE": "#3B6BC7",
}

def apply_palette(theme):
    """把调色板写入模块全局（light / dark）。返回实际应用的主题名。

    各界面模块用 `from .constants import *` 把颜色绑进了自己的命名空间，
    所以这里要把新值同步进所有已导入的 wm 模块副本，否则同进程内热切换
    主题时，重建的界面仍会拿旧颜色（老版本靠重启 exe 重新导入掩盖）。
    """
    p = _PALETTE_DARK if str(theme) == "dark" else _PALETTE_LIGHT
    names = list(p) + ["UI_THEME"]
    vals = dict(p)
    vals["UI_THEME"] = "dark" if str(theme) == "dark" else "light"
    for k in names:
        globals()[k] = vals[k]
    import sys as _sys
    for m in list(_sys.modules.values()):
        if m is None or not getattr(m, "__name__", "").startswith("wm."):
            continue
        for k in names:
            if hasattr(m, k):
                setattr(m, k, vals[k])
    return vals["UI_THEME"]


apply_palette("light")

PALETTE = ["#2563EB", "#0E9F6E", "#F59E0B", "#8B5CF6", "#EC4899",
           "#0891B2", "#F97316", "#64748B", "#84CC16", "#EF4444",
           "#14B8A6", "#A855F7"]

# 字体大小档位（settings.json font_scale，重启生效；乘在 UI 缩放系数上）
FONT_SCALES = [("小", 0.85), ("标准", 1.0), ("大", 1.15), ("特大", 1.3)]


def app_dir():
    """程序所在目录（PyInstaller 打包后 = exe 目录；源码运行 = 项目根）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_data_dir():
    """数据目录：优先 程序目录/data（便携），不可写退回 APPDATA。"""
    base = app_dir()
    for cand in (os.path.join(base, "data"),
                 os.path.join(os.environ.get("APPDATA", base), "WarehouseManager")):
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".wtest")
            with open(probe, "w") as f:
                f.write("1")
            os.remove(probe)
            return cand
        except Exception:
            continue
    return base

# --------------------------------------------------------------------------
# 字体
# --------------------------------------------------------------------------
FONT_FAMILY = "Microsoft YaHei UI"
FONT_FALLBACK = ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "Segoe UI", "SimHei")

FONT_BASE   = 10
FONT_SMALL  = 9
FONT_TITLE  = 15
FONT_KPI    = 22
FONT_MONO   = 10
