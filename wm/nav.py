# -*- coding: utf-8 -*-
"""左侧功能导航：深蓝专业风，分组可折叠，替代顶部页签条。

v1.31 骨架改造：功能越来越多
一行工具栏和顶部页签都装不下。把页签换成左侧功能树：
  - Notebook 仍在（页签条用样式隐藏），select/index 等原有调用零改动
  - 本控件只负责「分组展示 + 点击切页 + 高亮当前页」
  - 分组可折叠（点组名收起/展开）
  - 新功能页通过 app.nav_add(group, page_idx, label) 挂进来

v1.46.0 专业版换装：
  - 深蓝底（CLR_SIDE_*，浅色主题下侧栏也保持深底——主流 ERP 布局）
  - 顶部品牌区（Logo 块 + 程序名 + 版本号）
  - 分组标题改小号灰字；导航项带图标
  - 角标：nav.set_badge(idx, 文本或 None)（如低库存预警数）
  - 底部局域网共享状态：nav.set_lan(ok, 文本)

颜色全部取自 CLR_*（导入时求值）。主题热切换是整窗重建，
所以这里直接用常量即可，不走 bg=None 延迟取色那套。
"""

import tkinter as tk

from .constants import APP_VERSION, CLR_ACCENT, CLR_SIDE_BG, CLR_SIDE_GRP, \
    CLR_SIDE_HV, CLR_SIDE_LINE, CLR_SIDE_ON, CLR_SIDE_TXT

# 导航项图标（按显示名映射；未登记的用实心小方点，视觉不突兀）
ICONS = {
    "库存列表": "▤", "盘点单": "☑", "制作流程": "⚒",
    "出售记录": "¥", "出库记录": "➤", "客户管理": "☺", "销售退货": "↩",
    "数据分析": "▨", "销售利润表": "∑",
    "手机数据": "✆", "操作日志": "☰", "设置": "⚙",
}


class FunctionNav(tk.Frame):
    """左侧功能导航面板。

    app 端约定：
        self.nav = FunctionNav(wrap, self, self.fam)
        self.nav.set_active(idx)   # 页签切换后同步高亮（_on_tab_changed 里调）
        self.nav_add(group, idx, label)  # 注册新功能页
        self.nav.set_badge(idx, "6")     # 角标（None=清除）
        self.nav.set_lan(True, "已连接 · 2 台在线")
    """

    def __init__(self, parent, app, fam):
        w = int(182 * getattr(app, "ui_scale", 1.0))
        tk.Frame.__init__(self, parent, bg=CLR_SIDE_BG, width=w,
                          highlightbackground=CLR_SIDE_LINE, highlightthickness=1)
        self.app = app
        self.fam = fam
        self.pack(side="left", fill="y")
        self.pack_propagate(False)

        # 分组定义：(组名, [(页码, 显示名), ...])；页码 = Notebook 页序
        # 页码为 None 的项是「命令项」（如设置弹窗），不占 Notebook 页码
        self.groups = [
            ("库存管理", [(0, "库存列表")]),
            ("销售管理", [(1, "出售记录"), (2, "出库记录")]),
            ("数据报表", [(3, "数据分析"), (4, "手机数据")]),
            ("系统", [(5, "操作日志")]),
        ]
        self.expanded = set(g[0] for g in self.groups)
        self.active = 0
        self._item_lbls = {}     # page_idx -> 文字 Label（_page_of 用）
        self._item_rows = {}     # page_idx -> 整行 Frame（配色用）
        self._badge_lbls = {}    # page_idx -> 角标 Label
        self._badges = {}        # page_idx -> 文本
        self._cmds = {}          # 命令项显示名 -> 回调（add_command 注册）
        self._lbl_lan = None
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
        self._style_items()

    def add_command(self, group, label, cb):
        """注册命令项（v1.46.1）：如「设置」弹窗，不占 Notebook 页码。

        渲染上与普通导航项一致；点击直接调 cb，不参与高亮/角标。
        """
        self._cmds[label] = cb
        for g in self.groups:
            if g[0] == group:
                g[1].append((None, label))
                break
        else:
            self.groups.append((group, [(None, label)]))
            self.expanded.add(group)
        self.expanded.add(group)
        self._render()
        self._style_items()

    # ------------------------------------------------------------ 对外接口
    def set_active(self, idx):
        self.active = idx
        self._style_items()

    def set_badge(self, idx, text):
        """设置某页角标（None/空 = 清除）。已渲染时原地更新。"""
        if text:
            self._badges[idx] = str(text)
        else:
            self._badges.pop(idx, None)
        lbl = self._badge_lbls.get(idx)
        if lbl is not None and lbl.winfo_exists():
            self._apply_badge(lbl, idx)

    def set_lan(self, ok, text):
        """底部局域网共享状态（app 在开/关共享后调用）。"""
        if self._lbl_lan is None or not self._lbl_lan.winfo_exists():
            return
        if ok:
            self._lbl_lan.configure(
                text="● " + text, fg="#4ADE80")
        else:
            self._lbl_lan.configure(text="○ " + text, fg=CLR_SIDE_GRP)

    # ------------------------------------------------------------ 切换
    def _open(self, idx):
        try:
            self.app.show_page(idx)
        except Exception:
            pass

    def _run_cmd(self, cb):
        """命令项点击（设置弹窗等）；失败不打断导航。"""
        try:
            if callable(cb):
                cb()
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
    def _apply_badge(self, lbl, idx):
        txt = self._badges.get(idx)
        if txt:
            lbl.configure(text=txt, fg="#FCA5A5")
        else:
            lbl.configure(text="", fg=CLR_SIDE_TXT)

    def _render(self):
        for w in self.winfo_children():
            w.destroy()
        self._item_lbls.clear()
        self._item_rows.clear()
        self._badge_lbls.clear()
        self._lbl_lan = None

        s = getattr(self.app, "ui_scale", 1.0)
        pad_row = max(6, int(7 * s))

        # ---- 品牌区 ----
        brand = tk.Frame(self, bg=CLR_SIDE_BG)
        brand.pack(fill="x", padx=14, pady=(14, 4))
        mark = tk.Label(brand, text="仓", bg=CLR_ACCENT, fg="#FFFFFF",
                        font=(self.fam, 12, "bold"), width=2,
                        padx=int(6 * s), pady=int(3 * s))
        mark.pack(side="left")
        name = tk.Frame(brand, bg=CLR_SIDE_BG)
        name.pack(side="left", padx=(9, 0))
        tk.Label(name, text="仓管家", bg=CLR_SIDE_BG, fg=CLR_SIDE_ON,
                 font=(self.fam, 12, "bold"), anchor="w").pack(anchor="w")
        tk.Label(name, text="v%s" % APP_VERSION, bg=CLR_SIDE_BG,
                 fg=CLR_SIDE_GRP, font=(self.fam, 8), anchor="w").pack(anchor="w")
        tk.Frame(self, bg=CLR_SIDE_LINE, height=1).pack(fill="x", padx=12,
                                                        pady=(10, 2))

        for title, items in self.groups:
            open_ = title in self.expanded
            head = tk.Frame(self, bg=CLR_SIDE_BG, cursor="hand2")
            head.pack(fill="x")
            arrow = tk.Label(head, text="\u25BE" if open_ else "\u25B8",
                             bg=CLR_SIDE_BG, fg=CLR_SIDE_GRP,
                             font=(self.fam, 8), width=2)
            arrow.pack(side="left", padx=(12, 0), pady=pad_row)
            ttl = tk.Label(head, text=title, bg=CLR_SIDE_BG, fg=CLR_SIDE_GRP,
                           font=(self.fam, 9, "bold"))
            ttl.pack(side="left")

            def _hv(f, on):
                bg = CLR_SIDE_HV if on else CLR_SIDE_BG
                f.configure(bg=bg)
                for c in f.winfo_children():
                    try:
                        c.configure(bg=bg)
                    except Exception:
                        pass
            # 组名文字、箭头、整行都响应点击（Tk 点击不冒泡，须逐个绑）
            for w in (head, arrow, ttl):
                w.bind("<Button-1>", lambda e, t=title: self._toggle(t))
                w.bind("<Enter>", lambda e, f=head: _hv(f, True))
                w.bind("<Leave>", lambda e, f=head: _hv(f, False))

            if not open_:
                continue
            for idx, label in items:
                row = tk.Frame(self, bg=CLR_SIDE_BG, cursor="hand2")
                row.pack(fill="x", padx=6)
                ic = tk.Label(row, text=ICONS.get(label, "▪"),
                              bg=CLR_SIDE_BG, fg=CLR_SIDE_TXT,
                              font=(self.fam, 10), width=2)
                ic.pack(side="left", pady=pad_row)
                lbl = tk.Label(row, text=label, bg=CLR_SIDE_BG,
                               fg=CLR_SIDE_TXT, font=(self.fam, 10),
                               anchor="w", cursor="hand2")
                lbl.pack(side="left", fill="x", expand=True)
                bdg = tk.Label(row, text="", bg=CLR_SIDE_BG, fg=CLR_SIDE_TXT,
                               font=(self.fam, 8))
                bdg.pack(side="right", padx=(0, 6))

                if idx is None:
                    # 命令项（设置等弹窗入口）：点击调回调，悬停只做行高亮
                    cb = self._cmds.get(label)

                    def _hv2(f, on):
                        bg = CLR_SIDE_HV if on else CLR_SIDE_BG
                        f.configure(bg=bg)
                        for c in f.winfo_children():
                            try:
                                c.configure(bg=bg)
                            except Exception:
                                pass

                    for w in (row, ic, lbl, bdg):
                        w.bind("<Button-1>", lambda e, c=cb: self._run_cmd(c))
                        w.bind("<Enter>", lambda e, f=row: _hv2(f, True))
                        w.bind("<Leave>", lambda e, f=row: _hv2(f, False))
                    continue

                self._apply_badge(bdg, idx)
                for w in (row, ic, lbl, bdg):
                    w.bind("<Button-1>", lambda e, i=idx: self._open(i))
                for w in (row, ic, lbl, bdg):
                    w.bind("<Enter>", lambda e, i=idx: self._on_item_enter(i))
                    w.bind("<Leave>", lambda e, i=idx: self._on_item_leave(i))
                self._item_lbls[idx] = lbl
                self._item_rows[idx] = row
                self._badge_lbls[idx] = bdg

        # ---- 底部：局域网共享状态 ----
        tk.Frame(self, bg=CLR_SIDE_LINE, height=1).pack(fill="x", padx=12,
                                                        pady=(8, 0))
        self._lbl_lan = tk.Label(self, text="○ 共享未开启", bg=CLR_SIDE_BG,
                                 fg=CLR_SIDE_GRP, font=(self.fam, 8),
                                 anchor="w")
        self._lbl_lan.pack(fill="x", padx=14, pady=(6, 10))

        self._style_items()

    def _on_item_enter(self, idx):
        if idx != self.active:
            self._paint(idx, CLR_SIDE_HV, CLR_SIDE_ON)

    def _on_item_leave(self, idx):
        if idx != self.active:
            self._paint(idx, CLR_SIDE_BG, CLR_SIDE_TXT)

    def _paint(self, idx, bg, fg):
        row = self._item_rows.get(idx)
        lbl = self._item_lbls.get(idx)
        bdg = self._badge_lbls.get(idx)
        for w in (row, lbl, bdg):
            if w is not None and w.winfo_exists():
                try:
                    w.configure(bg=bg)
                except tk.TclError:
                    pass
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(fg=fg)
        # 图标与文字同色（图标 = 行内除文字/角标外的第一个 Label）
        if row is not None and row.winfo_exists():
            for c in row.winfo_children():
                if c is lbl or c is bdg:
                    continue
                if isinstance(c, tk.Label):
                    try:
                        c.configure(bg=bg, fg=fg)
                    except tk.TclError:
                        pass
                    break

    def _page_of(self, w):
        for idx, lbl in self._item_lbls.items():
            if lbl is w:
                return idx
        return None

    def _style_items(self):
        """高亮当前页：实心主题蓝底 + 白字加粗（深蓝侧栏上的胶囊式高亮）。"""
        for idx, lbl in self._item_lbls.items():
            on = (idx == self.active)
            row = self._item_rows.get(idx)
            bdg = self._badge_lbls.get(idx)
            bg = CLR_ACCENT if on else CLR_SIDE_BG
            fg = CLR_SIDE_ON if on else CLR_SIDE_TXT
            for w in (row, lbl, bdg):
                if w is not None and w.winfo_exists():
                    try:
                        w.configure(bg=bg)
                    except tk.TclError:
                        pass
            lbl.configure(fg=fg,
                          font=(self.fam, 10, "bold" if on else "normal"))
            # 图标跟随同色（在 _item_rows 的子控件里找第一个非文字 Label）
            if row is not None and row.winfo_exists():
                for c in row.winfo_children():
                    if c is not lbl and c is not bdg and isinstance(c, tk.Label):
                        try:
                            c.configure(bg=bg, fg=fg)
                        except tk.TclError:
                            pass
                        break
