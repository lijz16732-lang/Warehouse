# -*- coding: utf-8 -*-
"""纯 Canvas 自绘图表控件（无第三方依赖，随窗口自适应）。"""

import tkinter as tk
from tkinter import ttk

from .constants import (CLR_ACCENT, CLR_BORDER, CLR_BORDER_LT, CLR_CARD,
                        CLR_HEAD_FG, CLR_HEADER, CLR_MUTED, CLR_OK, CLR_TEXT,
                        PALETTE)


def _rounded(canvas, x1, y1, x2, y2, r, fill):
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    if x2 - x1 <= 1 or y2 - y1 <= 1:
        return None
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, fill=fill, outline=fill)


class _ChartBase(tk.Canvas):
    """图表基类：负责标题、空数据占位与重绘调度。"""

    def __init__(self, master, title="", height=230, bg=CLR_CARD, **kw):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0,
                         height=height, **kw)
        self._title = title
        self._subtitle = ""
        self._data = []
        self._font_family = "Microsoft YaHei UI"
        self.bind("<Configure>", lambda e: self.redraw())

    def set_font_family(self, fam):
        self._font_family = fam

    def set_data(self, data, title=None, subtitle=None):
        self._data = list(data or [])
        if title is not None:
            self._title = title
        self._subtitle = subtitle or ""
        self.redraw()

    # --- 供子类使用 ---
    def _draw_header(self, w):
        f = self._font_family
        self.create_text(16, 15, anchor="w", text=self._title,
                         fill=CLR_TEXT, font=(f, 11, "bold"))
        if self._subtitle:
            self.create_text(16 + self._text_w(self._title, (f, 11, "bold")) + 10, 16,
                             anchor="w", text=self._subtitle, fill=CLR_MUTED, font=(f, 9))
        self.create_line(16, 34, w - 16, 34, fill=CLR_BORDER_LT)
        return 48

    def _text_w(self, text, font):
        try:
            import tkinter.font as tkfont
            return tkfont.Font(font=font).measure(text)
        except Exception:
            return len(text) * 12

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        top = self._draw_header(w)
        if not self._data:
            self.create_text(w / 2, (top + h) / 2, text="暂无数据", fill=CLR_MUTED,
                             font=(self._font_family, 10))
            return
        self._draw(w, h, top)

    def _draw(self, w, h, top):
        raise NotImplementedError


class HBarChart(_ChartBase):
    """横向条形图，适合品牌/品类/货架 TOP 排行。"""

    def __init__(self, master, title="", height=250, show_pct=False, **kw):
        super().__init__(master, title=title, height=height, **kw)
        self.show_pct = show_pct

    def _draw(self, w, h, top):
        f = self._font_family
        items = self._data[:12]
        total = sum(v for _, v in items) or 1
        label_w, value_w = 96, 74
        area_x = 16 + label_w
        area_r = w - 16 - value_w
        if area_r - area_x < 40:
            return
        avail = h - top - 14
        row_h = max(16.0, min(34.0, avail / len(items)))
        bar_h = min(16.0, row_h * 0.58)
        vmax = max(v for _, v in items) or 1

        for i, (label, value) in enumerate(items):
            cy = top + row_h * i + row_h / 2.0
            color = PALETTE[i % len(PALETTE)]
            # 标签
            lab = label if len(label) <= 9 else label[:8] + "…"
            self.create_text(area_x - 12, cy, anchor="e", text=lab,
                             fill=CLR_HEAD_FG, font=(f, 9))
            # 轨道
            _rounded(self, area_x, cy - bar_h / 2 + 1, area_r, cy + bar_h / 2 - 1,
                     bar_h / 2 - 1, CLR_HEADER)
            # 条
            bw = max(5.0, (area_r - area_x) * value / float(vmax))
            _rounded(self, area_x, cy - bar_h / 2, area_x + bw, cy + bar_h / 2,
                     bar_h / 2, color)
            # 数值
            txt = str(value)
            if self.show_pct:
                txt = "%s  %.1f%%" % (value, value / float(total) * 100)
            self.create_text(area_r + 12, cy, anchor="w", text=txt,
                             fill=CLR_TEXT, font=(f, 9, "bold"))


class VBarChart(_ChartBase):
    """纵向柱状图，适合价格区间等序列分布。"""

    def _draw(self, w, h, top):
        f = self._font_family
        items = self._data[:12]
        pad_l, pad_r, pad_b = 40, 22, 34
        cw = w - pad_l - pad_r
        ch = h - top - pad_b
        if cw < 40 or ch < 30:
            return
        vmax = max(v for _, v in items) or 1

        # 网格线
        for i in range(5):
            y = top + ch * i / 4.0
            self.create_line(pad_l, y, pad_l + cw, y, fill=CLR_BORDER_LT)
            self.create_text(pad_l - 8, y, anchor="e",
                             text="%d" % round(vmax * (4 - i) / 4.0),
                             fill=CLR_MUTED, font=(f, 8))

        slot = cw / len(items)
        bw = min(46.0, slot * 0.56)
        for i, (label, value) in enumerate(items):
            cx = pad_l + slot * i + slot / 2.0
            bh = (ch) * value / float(vmax)
            bh = max(3.0, bh)
            color = PALETTE[i % len(PALETTE)]
            _rounded(self, cx - bw / 2, top + ch - bh, cx + bw / 2, top + ch,
                     min(6, bw / 3), color)
            self.create_text(cx, top + ch - bh - 11, text=str(value),
                             fill=CLR_TEXT, font=(f, 9, "bold"))
            lab = label if len(label) <= 8 else label[:7] + "…"
            self.create_text(cx, top + ch + 14, text=lab, fill=CLR_MUTED, font=(f, 9))


class DonutChart(_ChartBase):
    """环形图 + 图例，适合占比类分布。"""

    def _draw(self, w, h, top):
        f = self._font_family
        items = self._data[:8]
        others = self._data[8:]
        if others:
            items = items + [("其他", sum(v for _, v in others))]
        total = sum(v for _, v in items) or 1

        legend_w = min(220, max(150, w * 0.42))
        cx_area = w - 16 - legend_w
        cy = top + (h - top) / 2.0
        r_out = min(cx_area / 2.0 - 14, (h - top) / 2.0 - 14)
        if r_out < 26:
            return
        cx = 16 + cx_area / 2.0
        r_in = r_out * 0.58

        # 用扇形拼接 + 挖孔画环。
        # 不用 style="arc" 粗描边：Tk 在部分尺寸/缩放下会把近整圆的
        # 描边弧渲染错位（图例与图形颜色对不上）。
        start = 90.0
        for i, (label, value) in enumerate(items):
            extent = -360.0 * value / float(total)
            color = PALETTE[i % len(PALETTE)]
            self.create_arc(cx - r_out, cy - r_out, cx + r_out, cy + r_out,
                            start=start - 0.4, extent=extent - 0.4,
                            style="pieslice", fill=color, outline=color)
            start += extent
        self.create_oval(cx - r_in, cy - r_in, cx + r_in, cy + r_in,
                         fill=CLR_CARD, outline=CLR_CARD)

        self.create_text(cx, cy - 9, text="%d" % total, fill=CLR_TEXT,
                         font=(f, 17, "bold"))
        self.create_text(cx, cy + 12, text="合计", fill=CLR_MUTED, font=(f, 8))

        # 图例
        lx = cx + r_out + 20
        row_h = min(24.0, max(16.0, (h - top - 12) / float(len(items))))
        ly = cy - row_h * len(items) / 2.0
        for i, (label, value) in enumerate(items):
            y = ly + row_h * i + row_h / 2.0
            color = PALETTE[i % len(PALETTE)]
            _rounded(self, lx, y - 4, lx + 9, y + 5, 3, color)
            lab = label if len(label) <= 8 else label[:7] + "…"
            self.create_text(lx + 15, y, anchor="w", text=lab, fill=CLR_HEAD_FG, font=(f, 9))
            self.create_text(w - 16, y, anchor="e",
                             text="%d  %.1f%%" % (value, value / float(total) * 100),
                             fill=CLR_TEXT, font=(f, 9, "bold"))


class ProgressStat(tk.Canvas):
    """上架率进度条（用于 KPI 卡下方）。"""

    def __init__(self, master, height=8, bg=CLR_CARD, **kw):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, height=height, **kw)
        self._pct = 0.0
        self._color = CLR_OK
        self.bind("<Configure>", lambda e: self._draw())

    def set_value(self, pct, color=CLR_OK):
        self._pct = max(0.0, min(100.0, float(pct)))
        self._color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 2 or h <= 2:
            return
        _rounded(self, 0, 0, w, h, h / 2.0, "#EDF1F7")
        bw = max(h, w * self._pct / 100.0)
        _rounded(self, 0, 0, bw, h, h / 2.0, self._color)


class KpiCard(tk.Frame):
    """指标卡：左侧色条 + 标题 + 大数值 + 副标题（可带进度条）。"""

    def __init__(self, master, title, value="—", sub="", color=CLR_ACCENT,
                 bg=None, show_bar=False):
        bg = bg or CLR_CARD
        super().__init__(master, bg=bg, highlightbackground=CLR_BORDER,
                         highlightthickness=1, bd=0)
        self._color = color
        self._bg = bg

        strip = tk.Frame(self, bg=color, width=4)
        strip.pack(side="left", fill="y")

        inner = tk.Frame(self, bg=bg)
        inner.pack(side="left", fill="both", expand=True, padx=(14, 12), pady=(10, 10))

        top = tk.Frame(inner, bg=bg)
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=8, height=8, bg=bg, highlightthickness=0, bd=0)
        self.dot.create_oval(0, 1, 7, 8, fill=color, outline=color)
        self.dot.pack(side="left", pady=(4, 0), padx=(0, 6))
        self.lbl_title = tk.Label(top, text=title, bg=bg, fg=CLR_MUTED,
                                  font=("Microsoft YaHei UI", 9))
        self.lbl_title.pack(side="left")

        self.lbl_value = tk.Label(inner, text=value, bg=bg, fg=CLR_TEXT,
                                  font=("Microsoft YaHei UI", 18, "bold"), anchor="w")
        self.lbl_value.pack(fill="x", pady=(2, 0))

        self.lbl_sub = tk.Label(inner, text=sub, bg=bg, fg=CLR_MUTED,
                                font=("Microsoft YaHei UI", 8), anchor="w")
        self.lbl_sub.pack(fill="x")

        self.bar = None
        if show_bar:
            self.bar = ProgressStat(inner, height=7, bg=bg)
            self.bar.pack(fill="x", pady=(6, 0))

    def set_font_family(self, fam):
        self.lbl_title.configure(font=(fam, 9))
        self.lbl_value.configure(font=(fam, 18, "bold"))
        self.lbl_sub.configure(font=(fam, 8))

    def update_value(self, value=None, sub=None, pct=None, color=None):
        if value is not None:
            self.lbl_value.configure(text=value)
        if sub is not None:
            self.lbl_sub.configure(text=sub)
        if color is not None:
            self._color = color
            self.dot.itemconfigure(1, fill=color, outline=color)
        if self.bar is not None and pct is not None:
            self.bar.set_value(pct, color or self._color)


class ScrollFrame(ttk.Frame):
    """可滚动容器：把内容放进 .body。"""

    def __init__(self, master, bg=None, **kw):
        bg = bg or CLR_BG
        super().__init__(master, **kw)
        self._bg = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", style="Vertical.TScrollbar",
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda e: self._wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._wheel(False))
        self.body.bind("<Enter>", lambda e: self._wheel(True))
        self.body.bind("<Leave>", lambda e: self._wheel(False))

    def _on_body(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _wheel(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception:
            pass
