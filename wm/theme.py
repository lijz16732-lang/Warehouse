# -*- coding: utf-8 -*-
"""ttk 主题：现代化浅色配色与控件样式。"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .constants import (CLR_ACCENT, CLR_ACCENT_DK, CLR_BG, CLR_BORDER, CLR_CARD,
                        CLR_DANGER, CLR_HEADER, CLR_HOVER_BG, CLR_HOVER_EDGE,
                        CLR_MUTED, CLR_OK, CLR_ROW_ALT, CLR_SEL, CLR_TEXT, CLR_WARN,
                        FONT_FALLBACK)


class RowHover:
    """鼠标划过整行高亮（Treeview 没有 hover 概念，用 tag 现挂现摘）。

    - 划过数据行 → 给该行追加 "hover" tag（保留原有斑马纹/下架/低库存 tag）
    - 表头、空白处、窗口外 → 不挂
    - 离开表格延迟 20ms 按鼠标真实位置判定（贴片之间移动会连环触发 Leave）
    - 滚动/重排后调用 sync()/reset() 跟上

    用法：
        self.hover = RowHover(self.tree, self.root)
        self.hover.on_change = self._on_hover_change   # 可选，行变化时通知
        self.hover.sync()   # 滚动后
        self.hover.reset()  # 行全部重建后
    """
    TAG = "hover"

    def __init__(self, tree, root, bg=CLR_HOVER_BG, edge=CLR_HOVER_EDGE):
        self.tree = tree
        self.root = root
        self.bg = bg
        self.edge = edge
        self.row = None            # 当前划过的行 iid
        self.on_change = None      # fn(old, new)
        self._job = None
        # 注意：Treeview 的 tag 优先级是「先创建的胜」，所以 RowHover 要在
        # 其他 tag（斑马纹/下架灰/低库存橙）之前创建，hover 才盖得住它们
        tree.tag_configure(self.TAG, background=bg)
        # 鼠标直接"跳"进控件时不产生 Motion（只有 Enter），所以两个都要挂
        tree.bind("<Motion>", self._on_motion, add="+")
        tree.bind("<Enter>", self._on_motion, add="+")
        tree.bind("<Leave>", self._on_leave, add="+")

    # ------------------------------------------------ 内部
    def row_at(self, x_root, y_root):
        """屏幕坐标 → 鼠标下方的数据行 iid（不在数据行上返回 None）。"""
        t = self.tree
        try:
            x = x_root - t.winfo_rootx()
            y = y_root - t.winfo_rooty()
            if x < 0 or y < 0 or x >= t.winfo_width() or y >= t.winfo_height():
                return None
            if t.identify_region(x, y) != "cell":
                return None            # 表头 / 空白处不高亮
            iid = t.identify_row(y)
        except Exception:
            return None
        return str(iid) if iid else None

    def _on_motion(self, event):
        self.set(self.row_at(event.x_root, event.y_root))

    def _on_leave(self, event=None):
        if self._job is not None:
            return
        try:
            self._job = self.root.after(20, self._after_leave)
        except Exception:
            self._job = None

    def _after_leave(self):
        self._job = None
        self.sync()

    # ------------------------------------------------ 对外
    def set(self, iid):
        """切换高亮行（保留行上原有的 tag）。"""
        if iid == self.row:
            return
        old, self.row = self.row, iid
        for r in (old, iid):
            if not r:
                continue
            try:
                if not self.tree.exists(r):
                    continue
                tags = [t for t in self.tree.item(r, "tags") if t != self.TAG]
                if r == iid:
                    tags.append(self.TAG)
                self.tree.item(r, tags=tuple(tags))
            except Exception:
                pass
        if self.on_change:
            try:
                self.on_change(old, iid)
            except Exception:
                pass

    def sync(self):
        """按鼠标当前真实位置重新认行（滚动/离开后行位置变了）。"""
        self._cancel_job()
        try:
            px, py = self.root.winfo_pointerxy()
        except Exception:
            return
        self.set(self.row_at(px, py))

    def reset(self):
        """行全部重建后调用：旧行 iid 作废，只清状态不动 tag。"""
        self._cancel_job()
        self.row = None

    def _cancel_job(self):
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None


def pick_font(root):
    fams = set(tkfont.families(root))
    for f in FONT_FALLBACK:
        if f in fams:
            return f
    return "TkDefaultFont"


def apply_theme(root):
    """应用全局主题，返回选中的字体族名。"""
    fam = pick_font(root)
    root.configure(bg=CLR_BG)

    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=fam, size=10)
        except Exception:
            pass
    try:
        tkfont.nametofont("TkFixedFont").configure(size=10)
    except Exception:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    def cfg(name, **kw):
        style.configure(name, **kw)

    base = dict(font=(fam, 10), background=CLR_BG, foreground=CLR_TEXT)

    cfg(".", **base)
    cfg("TFrame", background=CLR_BG)
    cfg("Card.TFrame", background=CLR_CARD)
    cfg("Toolbar.TFrame", background=CLR_CARD)
    cfg("Side.TFrame", background=CLR_CARD)
    cfg("Status.TFrame", background=CLR_CARD)

    cfg("TLabel", background=CLR_BG, foreground=CLR_TEXT, font=(fam, 10))
    cfg("Card.TLabel", background=CLR_CARD, foreground=CLR_TEXT)
    cfg("Muted.TLabel", background=CLR_CARD, foreground=CLR_MUTED, font=(fam, 9))
    cfg("SideMuted.TLabel", background=CLR_CARD, foreground=CLR_MUTED, font=(fam, 9))
    cfg("SideTitle.TLabel", background=CLR_CARD, foreground=CLR_TEXT, font=(fam, 10, "bold"))
    cfg("KpiTitle.TLabel", background=CLR_CARD, foreground=CLR_MUTED, font=(fam, 9))
    cfg("KpiValue.TLabel", background=CLR_CARD, foreground=CLR_TEXT, font=(fam, 19, "bold"))
    cfg("KpiSub.TLabel", background=CLR_CARD, foreground=CLR_MUTED, font=(fam, 8))

    # ---- 按钮 ----
    cfg("TButton", padding=(12, 6), font=(fam, 10), relief="flat",
        background="#FFFFFF", foreground=CLR_TEXT, borderwidth=1)
    style.map("TButton",
              background=[("pressed", "#E4EAF3"), ("active", "#F2F5FA")],
              bordercolor=[("!disabled", CLR_BORDER)])

    cfg("Accent.TButton", padding=(14, 6), font=(fam, 10, "bold"),
        background=CLR_ACCENT, foreground="#FFFFFF", borderwidth=0)
    style.map("Accent.TButton",
              background=[("pressed", CLR_ACCENT_DK), ("active", "#3B76F0"),
                          ("disabled", "#A9C1F2")],
              foreground=[("disabled", "#F3F6FF")])

    cfg("Ghost.TButton", padding=(10, 6), font=(fam, 10),
        background=CLR_CARD, foreground=CLR_ACCENT, borderwidth=0)
    style.map("Ghost.TButton",
              background=[("pressed", "#E8F0FE"), ("active", "#EFF5FF")],
              foreground=[("disabled", "#9DB5E8")])

    cfg("Danger.TButton", padding=(12, 6), font=(fam, 10),
        background="#FFFFFF", foreground=CLR_DANGER, borderwidth=1)
    style.map("Danger.TButton",
              background=[("pressed", "#FDE8E8"), ("active", "#FEF2F2")],
              bordercolor=[("!disabled", "#F5C2C2")])

    cfg("Ok.TButton", padding=(12, 6), font=(fam, 10),
        background="#FFFFFF", foreground=CLR_OK, borderwidth=1)
    style.map("Ok.TButton",
              background=[("pressed", "#DEF7EC"), ("active", "#F0FDF7")],
              bordercolor=[("!disabled", "#B5E3CE")])

    cfg("Link.TButton", padding=(4, 2), font=(fam, 9), background=CLR_CARD,
        foreground=CLR_ACCENT, borderwidth=0)
    style.map("Link.TButton", background=[("active", "#EFF5FF")])

    # ---- 输入控件 ----
    cfg("TEntry", padding=5, fieldbackground="#FFFFFF", foreground=CLR_TEXT,
        bordercolor=CLR_BORDER, lightcolor=CLR_BORDER, darkcolor=CLR_BORDER,
        insertcolor=CLR_ACCENT)
    style.map("TEntry", bordercolor=[("focus", CLR_ACCENT)])

    cfg("TCombobox", padding=4, fieldbackground="#FFFFFF", background="#FFFFFF",
        foreground=CLR_TEXT, arrowcolor=CLR_MUTED, bordercolor=CLR_BORDER,
        lightcolor=CLR_BORDER, darkcolor=CLR_BORDER)
    style.map("TCombobox",
              fieldbackground=[("readonly", "#FFFFFF"), ("disabled", "#F1F4F9")],
              bordercolor=[("focus", CLR_ACCENT), ("hover", "#B9C6DA")])
    root.option_add("*TCombobox*Listbox.font", (fam, 10))
    root.option_add("*TCombobox*Listbox.background", "#FFFFFF")
    root.option_add("*TCombobox*Listbox.foreground", CLR_TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", CLR_ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

    cfg("TCheckbutton", background=CLR_BG, foreground=CLR_TEXT, font=(fam, 10))
    style.map("TCheckbutton", background=[("active", CLR_BG)],
              indicatorcolor=[("selected", CLR_ACCENT), ("!selected", "#FFFFFF")])
    cfg("Card.TCheckbutton", background=CLR_CARD, foreground=CLR_TEXT, font=(fam, 10))
    style.map("Card.TCheckbutton", background=[("active", CLR_CARD)],
              indicatorcolor=[("selected", CLR_ACCENT), ("!selected", "#FFFFFF")])
    cfg("Card.TRadiobutton", background=CLR_CARD, foreground=CLR_TEXT, font=(fam, 10))
    style.map("Card.TRadiobutton", background=[("active", CLR_CARD)],
              indicatorcolor=[("selected", CLR_ACCENT), ("!selected", "#FFFFFF")])

    cfg("TNotebook", background=CLR_BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
    cfg("TNotebook.Tab", padding=(22, 9), font=(fam, 10), background="#E3E9F2",
        foreground=CLR_MUTED, borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", CLR_CARD), ("active", "#EDF1F8")],
              foreground=[("selected", CLR_ACCENT), ("active", CLR_TEXT)],
              expand=[("selected", (0, 0, 0, 0))])

    # ---- 表格 ----
    cfg("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground=CLR_TEXT,
        rowheight=30, font=(fam, 10), borderwidth=0)
    cfg("Treeview.Heading", background=CLR_HEADER, foreground="#41506B",
        font=(fam, 10, "bold"), relief="flat", padding=(6, 8), borderwidth=0)
    style.map("Treeview.Heading",
              background=[("active", "#E7EDF7")], relief=[("active", "flat")])
    style.map("Treeview",
              background=[("selected", CLR_SEL)],
              foreground=[("selected", CLR_TEXT)])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    cfg("TSeparator", background=CLR_BORDER)
    cfg("TProgressbar", background=CLR_ACCENT, troughcolor="#E6ECF5",
        bordercolor="#E6ECF5", lightcolor=CLR_ACCENT, darkcolor=CLR_ACCENT, thickness=6)

    cfg("TPanedwindow", background=CLR_BG)
    cfg("Sash", sashthickness=6, gripcount=0, background=CLR_BG)

    # 滚动条
    for orient in ("Vertical", "Horizontal"):
        cfg("%s.TScrollbar" % orient, background="#C6D0DE", troughcolor="#F4F7FB",
            bordercolor="#F4F7FB", arrowcolor=CLR_MUTED, relief="flat", borderwidth=0)
        style.map("%s.TScrollbar" % orient,
                  background=[("active", "#ADBACC"), ("pressed", "#96A6BC")])

    cfg("TSpinbox", padding=4, fieldbackground="#FFFFFF", bordercolor=CLR_BORDER,
        arrowcolor=CLR_MUTED)

    root.option_add("*Font", (fam, 10))
    root.option_add("*Menu.font", (fam, 10))
    root.option_add("*Menu.background", "#FFFFFF")
    root.option_add("*Menu.foreground", CLR_TEXT)
    root.option_add("*Menu.activeBackground", CLR_ACCENT)
    root.option_add("*Menu.activeForeground", "#FFFFFF")
    root.option_add("*Menu.borderWidth", 0)
    root.option_add("*Menu.relief", "solid")
    root.option_add("*Menu.activeBorderWidth", 0)
    root.option_add("*Menu.selectColor", "#FFFFFF")
    return fam


def dot_check(parent, text, variable, command=None, bg=None, fam=None, size=10):
    """圆点复选框：选中显示实心黑点 ●，未选中空心 ○。

    替代 ttk.Checkbutton 的「×」选中样式。点击切换 variable 并触发 command；
    variable 被程序修改时文字自动刷新（不触发 command）。返回 Label 控件。
    """
    bg = bg or CLR_BG
    dot_on, dot_off = "\u25CF", "\u25CB"   # ● ○
    lbl = tk.Label(parent, text=text, bg=bg, fg=CLR_MUTED,
                   font=(fam, size), cursor="hand2")

    def refresh(*_):
        on = bool(variable.get())
        lbl.configure(text=(dot_on if on else dot_off) + " " + text,
                      fg=CLR_TEXT if on else CLR_MUTED)

    def toggle(_e=None):
        variable.set(not variable.get())   # 触发 trace 自动刷新文字
        if command:
            command()

    variable.trace_add("write", refresh)
    lbl.bind("<Button-1>", toggle)
    refresh()
    return lbl


def make_menu(root, items):
    """构建右键菜单。items: [(label, command_or_None, 'sep')]"""
    m = tk.Menu(root, tearoff=0, font=(pick_font(root), 10))
    for it in items:
        if it == "sep" or (isinstance(it, tuple) and it[0] == "sep"):
            m.add_separator()
            continue
        label, cmd = it[0], it[1]
        if cmd is None:
            m.add_command(label=label, state="disabled")
        else:
            m.add_command(label=label, command=cmd)
    return m
