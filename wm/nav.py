# -*- coding: utf-8 -*-
"""左侧功能导航：分组可折叠，替代顶部页签条。

v1.31 骨架改造：功能越来越多
一行工具栏和顶部页签都装不下。把页签换成左侧功能树：
  - Notebook 仍在（页签条用样式隐藏），select/index 等原有调用零改动
  - 本控件只负责「分组展示 + 点击切页 + 高亮当前页」
  - 分组可折叠（点组名收起/展开）
  - 新功能页通过 app.nav_add(group, page_idx, label) 挂进来

颜色全部取自 CLR_*（导入时求值）。主题热切换是整窗重建，
所以这里直接用常量即可，不走 bg=None 延迟取色那套。
"""

import tkinter as tk

from .constants import CLR_ACCENT, CLR_ACCENT_LT, CLR_BORDER, CLR_BORDER_LT, \
    CLR_CARD, CLR_MUTED, CLR_TEXT, CLR_TAB_HV


class FunctionNav(tk.Frame):
    """左侧功能导航面板。

    app 端约定：
        self.nav = FunctionNav(wrap, self, self.fam)
        self.nav.set_active(idx)   # 页签切换后同步高亮（_on_tab_changed 里调）
        self.nav_add(group, idx, label)  # 注册新功能页
    """

    def __init__(self, parent, app, fam):
        w = int(150 * getattr(app, "ui_scale", 1.0))
        tk.Frame.__init__(self, parent, bg=CLR_CARD, width=w,
                          highlightbackground=CLR_BORDER, highlightthickness=1)
        self.app = app
        self.fam = fam
        self.pack(side="left", fill="y")
        self.pack_propagate(False)

        # 分组定义：(组名, [(页码, 显示名), ...])；页码 = Notebook 页序
        self.groups = [
            ("库存管理", [(0, "库存列表")]),
            ("销售管理", [(1, "出售记录"), (2, "出库记录")]),
            ("数据报表", [(3, "数据分析"), (4, "手机数据")]),
            ("系统", [(5, "操作日志")]),
        ]
        self.expanded = set(g[0] for g in self.groups)
        self.active = 0
        self._item_lbls = {}     # page_idx -> Label
        self._arrow_lbls = {}    # 组名 -> ▾/▸ Label
        self._render()

    # ------------------------------------------------------------ 注册
    def add_item(self, group, idx, label):
        """注册新功能页（组不存在则追加到末尾）。"""
        for g in self.groups:
            if g[0] == group:
                g[1].append((idx, label))
                break
        else:
            self.groups.append((group, [(idx, label)]))
            self.expanded.add(group)
        self.expanded.add(group)
        self._render()

    # ------------------------------------------------------------ 切换
    def set_active(self, idx):
        self.active = idx
        self._style_items()

    def _open(self, idx):
        try:
            self.app.show_page(idx)
        except Exception:
            pass

    def _toggle(self, title):
        if title in self.expanded:
            self.expanded.discard(title)
        else:
            self.expanded.add(title)
        self._render()
        self._style_items()

    # ------------------------------------------------------------ 绘制
    def _render(self):
        for w in self.winfo_children():
            w.destroy()
        self._item_lbls.clear()
        self._arrow_lbls.clear()

        s = getattr(self.app, "ui_scale", 1.0)
        pad_row = max(6, int(7 * s))
        tk.Label(self, text="全部功能", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 11, "bold")).pack(anchor="w", padx=16,
                                                   pady=(14, 6))
        tk.Frame(self, bg=CLR_BORDER_LT, height=1).pack(fill="x", padx=14,
                                                        pady=(0, 4))

        for title, items in self.groups:
            open_ = title in self.expanded
            head = tk.Frame(self, bg=CLR_CARD, cursor="hand2")
            head.pack(fill="x")
            arrow = tk.Label(head, text="\u25BE" if open_ else "\u25B8",
                             bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9),
                             width=2)
            arrow.pack(side="left", padx=(14, 0), pady=pad_row)
            tk.Label(head, text=title, bg=CLR_CARD, fg=CLR_TEXT,
                     font=(self.fam, 10, "bold")).pack(side="left")
            def _hv(f, on, t=title):
                bg = CLR_TAB_HV if on else CLR_CARD
                f.configure(bg=bg)
                for c in f.winfo_children():
                    try:
                        c.configure(bg=bg)
                    except Exception:
                        pass
            for w in (head, arrow):
                w.bind("<Button-1>", lambda e, t=title: self._toggle(t))
                w.bind("<Enter>", lambda e, f=head: _hv(f, True))
                w.bind("<Leave>", lambda e, f=head: _hv(f, False))
            self._arrow_lbls[title] = arrow

            if not open_:
                continue
            for idx, label in items:
                lbl = tk.Label(self, text="　" + label, bg=CLR_CARD,
                               fg=CLR_TEXT, font=(self.fam, 10),
                               anchor="w", cursor="hand2")
                lbl.pack(fill="x")
                lbl.bind("<Button-1>", lambda e, i=idx: self._open(i))
                lbl.bind("<Enter>", self._on_item_enter)
                lbl.bind("<Leave>", self._on_item_leave)
                self._item_lbls[idx] = lbl

        self._style_items()

    def _on_item_enter(self, e):
        w = e.widget
        if self._page_of(w) != self.active:
            w.configure(bg=CLR_TAB_HV)

    def _on_item_leave(self, e):
        w = e.widget
        if self._page_of(w) != self.active:
            w.configure(bg=CLR_CARD)

    def _page_of(self, w):
        for idx, lbl in self._item_lbls.items():
            if lbl is w:
                return idx
        return None

    def _style_items(self):
        """高亮当前页：浅蓝底 + 蓝字加粗，其余恢复卡片底。"""
        for idx, lbl in self._item_lbls.items():
            on = (idx == self.active)
            lbl.configure(bg=CLR_ACCENT_LT if on else CLR_CARD,
                          fg=CLR_ACCENT if on else CLR_TEXT,
                          font=(self.fam, 10, "bold" if on else "normal"))
