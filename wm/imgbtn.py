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


def make_chip(text, bg, border, fg, fam_pt, scale):
    """筛选回显小胶囊（设计稿 fchip 同款）：文字 + ✕，整张点击可移除筛选。"""
    px = max(9, int(round(fam_pt * 96 / 72 * scale)))
    f = _load_font(False, px)
    label = text + "  ✕"
    try:
        box = ImageDraw.Draw(Image.new("RGB", (8, 8))).textbbox((0, 0), label, font=f)
        tw, th = box[2] - box[0], box[3] - box[1]
        ox, oy = box[0], box[1]
    except AttributeError:
        tw, th = ImageDraw.Draw(Image.new("RGB", (8, 8))).textsize(label, font=f)
        ox = oy = 0
    h = max(int(26 * scale), th + int(8 * scale))
    w = tw + int(24 * scale)
    im = _rounded(w, h, h // 2, bg, border, 1)
    d = ImageDraw.Draw(im)
    d.text((int(12 * scale) - ox, (h - th) / 2 - oy), label, font=f, fill=fg)
    return ImageTk.PhotoImage(im)


class Chip(tk.Label):
    """筛选回显胶囊。command 在点击整颗时触发（通常是移除该筛选）。"""

    def __init__(self, master, app, text, command):
        from . import constants as C
        self._cmd = command
        self._app = app
        self._text = text
        self._img = None
        tk.Label.__init__(self, master, bg=C.CLR_CARD, cursor="hand2")
        self._render()
        self.bind("<Button-1>", lambda e: self._cmd())

    def _render(self):
        from . import constants as C
        s = float(getattr(self._app, "ui_scale", 1.0) or 1.0)
        self._img = make_chip(self._text, C.CLR_ACCENT_LT, C.CLR_BORDER,
                              C.CLR_ACCENT, 9, s)
        self.configure(image=self._img)

    def refresh(self):
        """换行/重排后重建（颜色可能随主题变）。"""
        self._render()

    def _click(self):
        if self._cmd:
            self._cmd()


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
        from . import constants as C
        s = float(getattr(self._app, "ui_scale", 1.0) or 1.0)
        h = int(self._bh_px * s)
        if not self._bw_px:
            # v1.46.3 自动宽度：按文字实宽 + 左右 padding（工具栏一批按钮统一用）
            px = max(9, int(round(10 * 96 / 72 * s)))
            f = _load_font(self._kind == "accent", px)
            try:
                box = ImageDraw.Draw(Image.new("RGB", (8, 8))).textbbox(
                    (0, 0), self._text, font=f)
                tw = box[2] - box[0]
            except AttributeError:
                tw = ImageDraw.Draw(Image.new("RGB", (8, 8))).textsize(
                    self._text, font=f)[0]
            self._bw_px = int((tw + 28) / s)
        w = int(self._bw_px * s)
        self._imgs = make_button_pair(self._text, w, h, 10, s, **self._kw)
        self.configure(image=self._imgs[0])

    def _set(self, hover):
        if self._imgs:
            self.configure(image=self._imgs[1 if hover else 0])

    def _click(self, _e=None):
        if self._cmd:
            self._cmd()

    def invoke(self):
        """探针/快捷路径用：模拟点击。"""
        self._click()


class PageBtn(tk.Label):
    """分页数字/箭头小方钮（v1.46.4，设计稿同款）：当前页蓝底白字。"""

    def __init__(self, master, app, text, command, active=False, w=30, h=26):
        from . import constants as C
        self._cmd = command
        self._text = text          # 探针用：页码/箭头文字
        self._active = active
        self._imgs = None
        tk.Label.__init__(self, master, bg=C.CLR_CARD,
                          cursor=("arrow" if active else "hand2"))
        s = float(getattr(app, "ui_scale", 1.0) or 1.0)
        kind = "accent" if active else "outline"
        self._imgs = make_button_pair(
            text, int(w * s), int(h * s), 9, s, kind,
            card=C.CLR_CARD, border=C.CLR_BORDER, text_fg=C.CLR_TEXT,
            hover_bg=C.CLR_TAB_HV, accent=C.CLR_ACCENT,
            accent_dk=C.CLR_ACCENT_DK)
        self.configure(image=self._imgs[0])
        if not active:
            self.bind("<Enter>", lambda e: self.configure(image=self._imgs[1]))
            self.bind("<Leave>", lambda e: self.configure(image=self._imgs[0]))
            self.bind("<Button-1>", lambda e: self._cmd())

    def invoke(self):
        """探针/快捷路径用：模拟点击。"""
        self._cmd()


class RoundEntry(tk.Canvas):
    """圆角搜索框（v1.46.3，设计稿同款）：胶囊边框 + 内嵌无边框 Entry。

    空值且未聚焦时显示灰字 placeholder；聚焦时边框变品牌蓝。
    """

    def __init__(self, master, app, textvariable=None, width=230, height=30,
                 placeholder="", bg=None, on_change=None, on_return=None):
        from . import constants as C
        self._app = app
        self._on_change = on_change
        self._on_return = on_return
        s = float(getattr(app, "ui_scale", 1.0) or 1.0)
        w = int(width * s)
        h = int(height * s)
        self._w_px, self._h_px = w, h
        base = bg or C.CLR_CARD
        tk.Canvas.__init__(self, master, width=w, height=h, bg=base,
                           highlightthickness=0)
        self._img_n = ImageTk.PhotoImage(
            _rounded(w, h, h // 2, C.CLR_INPUT, C.CLR_BORDER, 1))
        self._img_f = ImageTk.PhotoImage(
            _rounded(w, h, h // 2, C.CLR_INPUT, C.CLR_ACCENT, 1))
        self._border = self.create_image(0, 0, image=self._img_n, anchor="nw")
        self.var = textvariable or tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, bd=0,
                              bg=C.CLR_INPUT, fg=C.CLR_TEXT,
                              insertbackground=C.CLR_TEXT,
                              selectbackground=C.CLR_ACCENT,
                              selectforeground="#FFFFFF",
                              font=(app.fam, 10), highlightthickness=0)
        pad = int(14 * s)
        self.create_window(pad, h // 2, window=self.entry, anchor="w",
                           width=w - 2 * pad)
        # 占位灰字：Tk 的内嵌窗口永远盖住 canvas 图形项，所以占位要用
        # Label 窗口 + lift 到 Entry 之上（点它时把焦点交给输入框）
        self._ph_lbl = tk.Label(self, text=placeholder, bg=C.CLR_INPUT,
                                fg=C.CLR_MUTED, font=(app.fam, 9),
                                cursor="xterm")
        self._ph_lbl.place(x=pad, y=h // 2, anchor="w")
        self._ph_lbl.lift(self.entry)
        self._ph_lbl.bind("<Button-1>", lambda e: self.entry.focus_set())
        self._sync_ph()
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<FocusIn>", lambda e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._set_focus(False))
        self.entry.bind("<Return>", self._on_ret)

    # ---- 对外接口（与 ttk.Entry 兼容的最小集）----
    def focus_set(self):
        self.entry.focus_set()

    def select_range(self, a, b):
        self.entry.select_range(a, b)

    def _on_key(self, _e=None):
        self._sync_ph()
        if self._on_change:
            self._on_change()

    def _on_ret(self, _e=None):
        if self._on_return:
            self._on_return()

    def _set_focus(self, on):
        self.itemconfigure(self._border, image=self._img_f if on else self._img_n)
        if not on:
            self._sync_ph()

    def _sync_ph(self):
        has = bool(self.var.get())
        focused = self.entry is self.focus_get()
        if has or focused:
            self._ph_lbl.place_forget()
        else:
            self._ph_lbl.place(x=int(14 / max(0.1, float(
                getattr(self._app, "ui_scale", 1.0) or 1.0))), y=0,
                anchor="w", rely=0.5)
            self._ph_lbl.lift(self.entry)
