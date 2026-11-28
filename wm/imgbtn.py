# -*- coding: utf-8 -*-
"""抗锯齿圆角按钮（v1.46.1，设计稿同款：8px 圆角 + 1px 边框）。

Tk/ttk 在 clam 下的按钮边框是方角且颜色很浅，跟设计稿差距明显；
这里用 PIL 4× 超采样把「圆角边框底 + 居中文字」渲染成图片交给
tk.Label，悬停换 hover 底色图，点击触发 command——外观上就是一颗
带轮廓的现代按钮。
"""

from PIL import Image, ImageDraw, ImageFont, ImageTk
import tkinter as tk

_SS = 4          # 超采样倍数

_FONT_FILES = [  # (粗体?, 文件名)，微软雅黑 Windows 必有
    (False, "C:/Windows/Fonts/msyh.ttc"),
    (True, "C:/Windows/Fonts/msyhbd.ttc"),
    (False, "C:/Windows/Fonts/simhei.ttf"),
]


def _load_font(bold, px):
    for want_bold, path in _FONT_FILES:
        if want_bold != bold:
            continue
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded(w, h, radius, fill, outline, owidth):
    W, H = w * _SS, h * _SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=radius * _SS,
                        fill=fill, outline=outline, width=owidth * _SS)
    return im.resize((w, h), Image.LANCZOS)


def _with_text(base, text, color, bold, px):
    im = base.copy()
    d = ImageDraw.Draw(im)
    f = _load_font(bold, px)
    try:
        box = d.textbbox((0, 0), text, font=f)
        tw, th = box[2] - box[0], box[3] - box[1]
        ox, oy = box[0], box[1]
    except AttributeError:            # 老 PIL 兜底
        tw, th = d.textsize(text, font=f)
        ox = oy = 0
    d.text(((im.width - tw) / 2 - ox, (im.height - th) / 2 - oy),
           text, font=f, fill=color)
    return im


def make_button_pair(text, w, h, fam_pt, scale, kind,
                     card, border, text_fg, hover_bg, accent, accent_dk):
    """渲染 (normal, hover) 两张按钮 PhotoImage。kind: outline / accent。"""
    px = max(9, int(round(fam_pt * 96 / 72 * scale)))
    if kind == "accent":
        n = _rounded(w, h, 8, accent, None, 0)
        hov = _rounded(w, h, 8, accent_dk, None, 0)
        fg, bold = "#FFFFFF", True
    else:
        n = _rounded(w, h, 8, card, border, 1)
        hov = _rounded(w, h, 8, hover_bg, border, 1)
        fg, bold = text_fg, False
    return (ImageTk.PhotoImage(_with_text(n, text, fg, bold, px)),
            ImageTk.PhotoImage(_with_text(hov, text, fg, bold, px)))


class ImgBtn(tk.Label):
    """图片按钮：悬停换 hover 图，点击触发 command。"""

    def __init__(self, master, app, text, command, kind="outline",
                 width=None, height=32):
        from . import constants as C
        self._cmd = command
        self._kind = kind
        self._app = app
        self._text = text
        self._bh_px = height
        self._bw_px = width or 0
        self._imgs = None
        self._kw = dict(kind=kind, card=C.CLR_CARD, border=C.CLR_BORDER,
                        text_fg=C.CLR_TEXT, hover_bg=C.CLR_TAB_HV,
                        accent=C.CLR_ACCENT, accent_dk=C.CLR_ACCENT_DK)
        tk.Label.__init__(self, master, bg=C.CLR_CARD, cursor="hand2")
        self._render()
        self.bind("<Enter>", lambda e: self._set(1))
        self.bind("<Leave>", lambda e: self._set(0))
        self.bind("<Button-1>", self._click)

    def _render(self):
        s = float(getattr(self._app, "ui_scale", 1.0) or 1.0)
        w = int(self._bw_px * s) if self._bw_px else None
        h = int(self._bh_px * s)
        if w:
            self._imgs = make_button_pair(self._text, w, h,
                                          10, s, **self._kw)
            self.configure(image=self._imgs[0])
        else:
            # 未指定宽度时按文字宽度补 padding 先占位（图片后续再换）
            self.configure(text=self._text)

    def _set(self, hover):
        if self._imgs:
            self.configure(image=self._imgs[1 if hover else 0])

    def _click(self, _e=None):
        if self._cmd:
            self._cmd()
