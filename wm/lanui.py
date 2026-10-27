# -*- coding: utf-8 -*-
"""局域网共享窗口：一台电脑当主机，其他电脑连接；主机逐台授权是否可录入。"""

import os
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import segno
except ImportError:          # 二维码库缺失时只显示文字地址，不影响其他功能
    segno = None

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_DANGER,
                        CLR_MUTED, CLR_OK, CLR_TEXT, CLR_WARN, apply_window_icon,
                        center_window)
from .lan import DEFAULT_PORT, local_ips


class LanDialog(tk.Toplevel):
    """『数据 → 局域网共享』窗口。"""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.fam = app.fam
        self.title("局域网共享")
        self.configure(bg=CLR_BG)
        self.transient(master)
        apply_window_icon(self)
        self.resizable(False, False)
        self._build()
        # 窗口高度按实际内容计算（头部 + 卡片区 + 底部），1080p 上一屏显示完整；
        # 1366×768 笔记本上被屏幕限制时内容区自动出现滚动条，不会裁掉「关闭」按钮
        self.update_idletasks()
        need = (self.body.winfo_reqheight() + self._head.winfo_reqheight()
                + self._foot.winfo_reqheight() + 24)
        center_window(self, master, size=(760, max(760, need)), force=True)
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        app.lan_dlg = self
        self.refresh()

    # ------------------------------------------------------------ UI
    def _card(self, title, subtitle="", parent=None):
        card = tk.Frame(parent if parent is not None else self, bg=CLR_CARD,
                        highlightbackground=CLR_BORDER, highlightthickness=1)
        card.pack(fill="x", padx=12, pady=(8, 0))
        head = tk.Frame(card, bg=CLR_CARD)
        head.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(head, text=title, bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 11, "bold")).pack(side="left")
        # 当前正在使用的那一区，右上角挂一个高亮小标签
        card.badge = tk.Label(head, text="", bg=CLR_OK, fg="#FFFFFF",
                              font=(self.fam, 8))
        if subtitle:
            tk.Label(card, text=subtitle, bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.fam, 8), justify="left").pack(anchor="w", padx=14,
                                                              pady=(2, 6))
        return card

    def _build(self):
        self._head = head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                                     highlightthickness=1)
        head.pack(fill="x")
        tk.Label(head, text="局域网共享", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 13, "bold")).pack(side="left", padx=(16, 8), pady=10)
        self.lbl_state = tk.Label(head, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                                  font=(self.fam, 8))
        self.lbl_state.pack(side="left", pady=12)
        tk.Label(head, text="多台电脑共用同一份数据 · 适合同一局域网内的仓库",
                 bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 8)).pack(
            side="right", padx=16)

        # ---- 可滚动内容区（小屏时自动出滚动条，底部按钮永远可见）----
        area = tk.Frame(self, bg=CLR_BG)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg=CLR_BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.vsb.pack_forget()
        self.body = tk.Frame(self.canvas, bg=CLR_BG)
        self._cw = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._sync_scroll)
        self.canvas.bind("<Configure>", self._sync_scroll)
        for w in (self.canvas, self.body):
            w.bind("<MouseWheel>", self._on_wheel)

        # ---- ① 主机 ----
        host = self._card(
            "① 本机作为主机（数据放在这台电脑）",
            "主机随时可以录入。其他电脑连上后默认只能查看 / 导出，\n"
            "勾选「允许录入」后才可以新增、修改、出入库。", parent=self.body)
        self.host_badge = host.badge
        row = tk.Frame(host, bg=CLR_CARD)
        row.pack(fill="x", padx=14, pady=(0, 6))
        self.lbl_ips = tk.Label(row, text="", bg=CLR_CARD, fg=CLR_TEXT,
                                font=(self.fam, 10, "bold"), anchor="w")
        self.lbl_ips.pack(side="left")
        self.btn_copy = ttk.Button(row, text="复制地址", style="Ghost.TButton", width=9,
                                   command=self.copy_addr)
        self.btn_copy.pack(side="right")

        row2 = tk.Frame(host, bg=CLR_CARD)
        row2.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(row2, text="端口", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_port = tk.StringVar(value=str(DEFAULT_PORT))
        tk.Entry(row2, textvariable=self.var_port, width=7, font=(self.fam, 9),
                 relief="flat", highlightbackground=CLR_BORDER,
                 highlightthickness=1).pack(side="left", padx=(4, 12), ipady=2)
        tk.Label(row2, text="连接码", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_code = tk.StringVar()
        tk.Entry(row2, textvariable=self.var_code, width=9, font=(self.fam, 9),
                 relief="flat", highlightbackground=CLR_BORDER,
                 highlightthickness=1).pack(side="left", padx=(4, 6), ipady=2)
        self.btn_newcode = ttk.Button(row2, text="换一个", style="Ghost.TButton", width=7,
                                      command=self.new_code)
        self.btn_newcode.pack(side="left")

        row3 = tk.Frame(host, bg=CLR_CARD)
        row3.pack(fill="x", padx=14, pady=(0, 6))
        self.btn_host = ttk.Button(row3, text="开启共享", style="Accent.TButton",
                                   width=11, command=self.toggle_host)
        self.btn_host.pack(side="left")
        self.var_allow_new = tk.BooleanVar(value=False)
        self.cb_allow = ttk.Checkbutton(row3, text="新连接的电脑直接允许录入",
                                        variable=self.var_allow_new, style="TCheckbutton",
                                        command=self.toggle_default_allow)
        self.cb_allow.pack(side="left", padx=(12, 0))
        self.lbl_host_msg = tk.Label(host, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                     font=(self.fam, 8), anchor="w", justify="left")
        self.lbl_host_msg.pack(fill="x", padx=14, pady=(0, 8))

        # 已连接电脑
        tk.Label(host, text="已连接的电脑（双击一行切换「允许录入」）",
                 bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 8)).pack(
            anchor="w", padx=14)
        wrap = tk.Frame(host, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="x", padx=14, pady=(2, 4))
        cols = ("name", "ip", "last", "perm")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", height=3)
        for key, title, w in (("name", "电脑", 140), ("ip", "地址", 120),
                              ("last", "最近活动", 110), ("perm", "录入权限", 90)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, anchor="center")
        self.tree.pack(fill="x")
        self.tree.bind("<Double-1>", lambda e: self.toggle_client())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._sel_changed())
        self.lbl_clients = tk.Label(host, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                    font=(self.fam, 8))
        self.lbl_clients.pack(anchor="w", padx=14, pady=(0, 6))
        rowt = tk.Frame(host, bg=CLR_CARD)
        rowt.pack(fill="x", padx=14, pady=(0, 12))
        self.btn_kick = ttk.Button(rowt, text="移除连接", style="Ghost.TButton",
                                   width=9, state="disabled",
                                   command=self.kick_client)
        self.btn_kick.pack(side="right")
        self.btn_blk = ttk.Button(rowt, text="加入黑名单", style="Ghost.TButton",
                                  width=11, state="disabled",
                                  command=self.block_client)
        self.btn_blk.pack(side="right", padx=(0, 6))
        self.btn_blist = ttk.Button(rowt, text="黑名单管理", style="Ghost.TButton",
                                    width=11, state="disabled",
                                    command=self.manage_blocked)
        self.btn_blist.pack(side="left")

        # ---- ② 客户端 ----
        cli = self._card(
            "② 连接主机（本机作为客户端）",
            "填主机上显示的地址和连接码；本机不存副本，看到的就是主机当前数据。\n"
            "① 和 ② 选一个用即可：同一台电脑同时只能当其中一种。", parent=self.body)
        self.cli_badge = cli.badge
        rowc = tk.Frame(cli, bg=CLR_CARD)
        rowc.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(rowc, text="主机地址", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_host = tk.StringVar()
        tk.Entry(rowc, textvariable=self.var_host, width=16, font=(self.fam, 9),
                 relief="flat", highlightbackground=CLR_BORDER,
                 highlightthickness=1).pack(side="left", padx=(4, 10), ipady=2)
        tk.Label(rowc, text="端口", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_cport = tk.StringVar(value=str(DEFAULT_PORT))
        tk.Entry(rowc, textvariable=self.var_cport, width=6, font=(self.fam, 9),
                 relief="flat", highlightbackground=CLR_BORDER,
                 highlightthickness=1).pack(side="left", padx=(4, 10), ipady=2)
        tk.Label(rowc, text="连接码", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_ccode = tk.StringVar()
        tk.Entry(rowc, textvariable=self.var_ccode, width=9, font=(self.fam, 9),
                 relief="flat", highlightbackground=CLR_BORDER,
                 highlightthickness=1).pack(side="left", padx=(4, 0), ipady=2)

        # 历史连接：连接成功过的主机会自动记录，下拉选中即一键填入
        rowch = tk.Frame(cli, bg=CLR_CARD)
        rowch.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(rowch, text="历史连接", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.cb_hist = ttk.Combobox(rowch, state="readonly", width=30,
                                    font=(self.fam, 9))
        self.cb_hist.pack(side="left", padx=(6, 6))
        self.cb_hist.bind("<<ComboboxSelected>>", self._pick_history)
        ttk.Button(rowch, text="清空", style="Ghost.TButton", width=6,
                   command=self.clear_history).pack(side="left")

        rowc2 = tk.Frame(cli, bg=CLR_CARD)
        rowc2.pack(fill="x", padx=14, pady=(0, 4))
        self.btn_test = ttk.Button(rowc2, text="测试连接", style="Ghost.TButton",
                                   width=9, command=self.test_conn)
        self.btn_test.pack(side="left")
        self.btn_conn = ttk.Button(rowc2, text="连接", style="Accent.TButton",
                                   width=9, command=self.connect)
        self.btn_conn.pack(side="left", padx=(6, 0))
        self.btn_disconn = ttk.Button(rowc2, text="断开 / 回到本机", width=14,
                                      command=self.disconnect)
        self.btn_disconn.pack(side="left", padx=(6, 0))
        self.btn_ask = ttk.Button(rowc2, text="请求录入", style="Ghost.TButton",
                                  width=9, command=self.ask_write)
        self.btn_ask.pack(side="left", padx=(6, 0))
        self.lbl_cli_msg = tk.Label(cli, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                    font=(self.fam, 8), anchor="w", justify="left",
                                    wraplength=600)
        self.lbl_cli_msg.pack(fill="x", padx=14, pady=(0, 10))
        # 连接进度条：连接/测试期间显示流动条（连接在后台线程做，界面不卡）
        self.pb = ttk.Progressbar(cli, mode="indeterminate", maximum=100)
        self._conn_busy = False

        # ---- ③ 手机访问 ----
        ph = self._card(
            "③ 手机访问（手机 App 数据互通）",
            "手机安装《仓管家》App 后，首次打开把下面的地址填进去即可；\n"
            "手机和电脑要连同一个 WiFi，App 里输入连接码登录。", parent=self.body)
        self.ph_badge = ph.badge
        rowp = tk.Frame(ph, bg=CLR_CARD)
        rowp.pack(fill="x", padx=14, pady=(0, 6))
        self.lbl_phone_url = tk.Label(rowp, text="", bg=CLR_CARD, fg=CLR_TEXT,
                                      font=(self.fam, 11, "bold"), anchor="w")
        self.lbl_phone_url.pack(side="left")
        ttk.Button(rowp, text="复制地址", style="Ghost.TButton", width=9,
                   command=self.copy_phone_url).pack(side="right")
        rowq = tk.Frame(ph, bg=CLR_CARD)
        rowq.pack(fill="x", padx=14, pady=(0, 8))
        self.lbl_phone_msg = tk.Label(rowq, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                      font=(self.fam, 8), anchor="w", justify="left")
        self.lbl_phone_msg.pack(side="left", fill="x", expand=True)
        self.lbl_qr = tk.Label(rowq, text="", bg=CLR_CARD)
        self.lbl_qr.pack(side="right", padx=(6, 0))
        self._qr_img = None
        self._qr_path = None
        rowps = tk.Frame(ph, bg=CLR_CARD)
        rowps.pack(fill="x", padx=14, pady=(0, 10))
        self.lbl_phone_sessions = tk.Label(rowps, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                           font=(self.fam, 8))
        self.lbl_phone_sessions.pack(side="left")
        ttk.Button(rowps, text="手机全部下线", style="Ghost.TButton", width=12,
                   command=self.phones_offline).pack(side="right")

        # ---- 底部 ----
        self._foot = foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=10)
        ttk.Button(foot, text="关闭", width=10, command=self.destroy).pack(side="right")
        tk.Label(foot, text="提示：主机首次开启共享时，Windows 可能询问是否允许防火墙访问，请选择「允许」。",
                 bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 8)).pack(side="left")

    # ------------------------------------------------------------ 滚动
    def _sync_scroll(self, event=None):
        """内容比可视区高时才显示滚动条（小屏笔记本用）。"""
        try:
            self.body.update_idletasks()
            w = max(1, self.canvas.winfo_width())
            h = max(1, self.body.winfo_reqheight())
            self.canvas.itemconfigure(self._cw, width=w)
            self.canvas.configure(scrollregion=(0, 0, w, h))
            need = h > self.canvas.winfo_height() + 1
            shown = bool(self.vsb.winfo_ismapped())
            if need and not shown:
                self.vsb.pack(side="right", fill="y")
            elif not need and shown:
                self.vsb.pack_forget()
                self.canvas.yview_moveto(0)
        except Exception:
            pass

    def _on_wheel(self, event):
        try:
            if self.body.winfo_reqheight() > self.canvas.winfo_height() + 1:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return "break"
        except Exception:
            pass
        return None

    # ------------------------------------------------------------ 刷新
    @staticmethod
    def _badge(lbl, text, color):
        """卡片标题右侧的「当前角色」小标签，text 为空就隐藏。"""
        try:
            if text:
                lbl.configure(text=text, bg=color)
                if not lbl.winfo_manager():
                    lbl.pack(side="right")
            else:
                lbl.pack_forget()
        except Exception:
            pass

    def refresh(self):
        # 防重入：tree.delete 会触发 <<TreeviewSelect>>（清空选中），
        # 不加保护会和 _sel_changed 互相调用、无限递归卡死 Tk
        if getattr(self, "_in_refresh", False):
            return
        self._in_refresh = True
        try:
            self._do_refresh()
        finally:
            self._in_refresh = False

    def _do_refresh(self):
        st = self.app.lan_status()
        mode = st["mode"]
        text, color = {"off": ("本机独立使用", CLR_MUTED),
                       "host": ("正在共享（主机）", CLR_OK),
                       "client": ("已连接主机", CLR_ACCENT)}.get(mode, ("", CLR_MUTED))
        if mode == "client" and not st["can_write"]:
            text = "已连接主机 · 只读"
            color = CLR_WARN
        self.lbl_state.configure(text=text, bg=color)
        self.lbl_ips.configure(text="本机地址：%s" % "、".join(st["ips"]))
        if not self.var_port.get().strip():
            self.var_port.set(str(st["port"]))
        if not self.var_code.get().strip():
            self.var_code.set(st["code"])
        self.var_allow_new.set(bool(st["default_allow"]))
        # 客户端时「开启共享」直接置灰，防止误点顶掉当前连接（v1.11.2）
        in_client = mode == "client"
        self.btn_host.configure(text="停止共享" if st["running"] else "开启共享",
                                state="disabled" if in_client else "normal")
        self.cb_allow.configure(state="disabled" if in_client else "normal")
        self.btn_copy.configure(state="disabled" if in_client else "normal")
        self.btn_newcode.configure(state="disabled" if in_client else "normal")
        if mode == "host":
            self._badge(self.host_badge, "当前角色", CLR_OK)
        else:
            self._badge(self.host_badge, "", CLR_OK)
        if in_client:
            # 引导正确路径：先断开回本机，按钮才会亮起来
            self.lbl_host_msg.configure(
                text="本机当前是客户端（连的是 %s），本机数据暂未对外共享。"
                     "要当主机：请先在下方点「断开 / 回到本机」，再回来点「开启共享」。"
                     % (st.get("host") or "—"), fg=CLR_WARN)
        else:
            self.lbl_host_msg.configure(
                text=("共享中：端口 %s，连接码 %s。其他电脑在这里填：%s:%s"
                      % (st["port"], st["code"], st["ips"][0], st["port"]))
                if st["running"] else "未开启共享（开启后其他电脑才能连接本机）",
                fg=CLR_MUTED)

        # 客户端区回填
        if mode == "client" and st.get("host"):
            if not self.var_host.get().strip():
                self.var_host.set(st["host"])
            if not self.var_cport.get().strip():
                self.var_cport.set(str(st["port"]))
            if not self.var_ccode.get().strip():
                self.var_ccode.set(st["code"])
        self.btn_ask.configure(state="normal" if (mode == "client" and not st["can_write"])
                               else "disabled")
        self.btn_disconn.configure(state="normal" if mode != "off" else "disabled")
        if mode == "client":
            self._badge(self.cli_badge, "当前角色", CLR_ACCENT)
            self.lbl_cli_msg.configure(
                text="当前：客户端，连接 %s:%s · %s" % (
                    st["host"], st["port"], "可录入" if st["can_write"] else "只读（未授权）"),
                fg=CLR_OK if st["can_write"] else CLR_WARN)
        elif mode == "host":
            self._badge(self.cli_badge, "", CLR_ACCENT)
            self.lbl_cli_msg.configure(
                text="当前：主机模式（本机数据就是共享数据）。要改连其他主机的数据，"
                     "请先点「停止共享」——直接连接会停掉本机共享，已连上的电脑会断开。",
                fg=CLR_MUTED)
        else:
            self._badge(self.cli_badge, "", CLR_ACCENT)
            self.lbl_cli_msg.configure(text="当前：本机独立使用", fg=CLR_MUTED)

        # 已连接电脑（保留选中行，避免轮询刷新把选中冲掉、按钮莫名变灰）
        sel_keep = list(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        clients = st["clients"]
        import time
        now = time.time()
        for c in clients:
            ago = int(max(0, now - (c.get("last_seen") or 0)))
            when = "%d 秒前" % ago if ago < 60 else "%d 分钟前" % (ago // 60)
            self.tree.insert("", "end", iid=c["ip"],
                             values=(c.get("name") or "未知电脑", c["ip"], when,
                                     "允许" if c.get("allowed") else "只读"))
        if sel_keep:
            self._in_refresh = True
            try:
                keep = [i for i in sel_keep if self.tree.exists(i)]
                if keep:
                    self.tree.selection_set(keep)
            finally:
                self._in_refresh = False
        self.lbl_clients.configure(
            text="暂无电脑连接" if not clients else
            "共 %d 台；双击可切换录入权限" % len(clients))
        hosting = mode == "host" and st["running"]
        sel = self.tree.selection()
        self.btn_kick.configure(
            state="normal" if (hosting and sel) else "disabled")
        self.btn_blk.configure(
            state="normal" if (hosting and sel) else "disabled")
        self.btn_blist.configure(state="normal" if hosting else "disabled")
        self._refresh_phone(st)
        self.refresh_hist()

    # ------------------------------------------------------------ 手机端
    def _phone_url(self):
        ips = self.app.lan_status()["ips"]
        port = self.var_port.get().strip() or str(DEFAULT_PORT)
        return "http://%s:%s/m" % (ips[0], port)

    def _refresh_phone(self, st):
        """③ 手机访问区：地址、二维码、会话数。"""
        url = self._phone_url()
        self.lbl_phone_url.configure(text=url)
        srv = self.app.lan_server
        hosting = st["mode"] == "host" and st["running"]
        try:
            n = srv.mobile.count() if (hosting and srv) else 0
        except Exception:
            n = 0
        self.lbl_phone_sessions.configure(
            text=("手机在线：%d 台（会话 12 小时有效）" % n) if hosting
            else "开启共享后手机才能连上")
        if hosting:
            self.lbl_phone_msg.configure(
                text="App 首次使用：打开 App → 填上面地址 → 输入连接码。"
                     "手机默认只读，登记出售需主机授权。",
                fg=CLR_MUTED)
        else:
            self.lbl_phone_msg.configure(
                text="开启共享后，地址和二维码才会生效。", fg=CLR_MUTED)
        self._render_qr(url if hosting else "")

    def _render_qr(self, url):
        """手机扫一扫免手输地址（需要 segno；缺失时跳过）。"""
        if not segno or not url:
            self.lbl_qr.configure(text="", image="")
            self._qr_img = None
            return
        try:
            if self._qr_path and os.path.exists(self._qr_path):
                try:
                    os.remove(self._qr_path)
                except OSError:
                    pass
            fd, path = tempfile.mkstemp(prefix="cgm_qr_", suffix=".png")
            os.close(fd)
            segno.make(url).save(path, kind="png", scale=4, border=2)
            img = tk.PhotoImage(file=path)
            self._qr_img = img          # 防被垃圾回收
            self._qr_path = path
            self.lbl_qr.configure(image=img, text="")
        except Exception:
            self.lbl_qr.configure(text="", image="")
            self._qr_img = None

    def copy_phone_url(self):
        url = self._phone_url()
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            self.lbl_phone_msg.configure(text="已复制：%s（发给手机填进 App）" % url,
                                         fg=CLR_MUTED)
        except Exception as e:
            messagebox.showerror("复制失败", str(e), parent=self)

    def phones_offline(self):
        """把所有手机的会话踢下线（App 里要重新输连接码）。"""
        srv = self.app.lan_server
        if srv is None:
            return
        n = srv.mobile.count()
        if not n:
            messagebox.showinfo("手机全部下线", "当前没有手机在线", parent=self)
            return
        if messagebox.askyesno("手机全部下线",
                               "让 %d 台手机全部下线？\nApp 里需要重新输入连接码才能登录。" % n,
                               parent=self):
            srv.mobile.clear_all()
            self.refresh()

    # ------------------------------------------------------------ 动作
    def copy_addr(self):
        ips = self.app.lan_status()["ips"]
        port = self.var_port.get().strip() or str(DEFAULT_PORT)
        txt = "%s:%s" % (ips[0], port)
        try:
            self.clipboard_clear()
            self.clipboard_append(txt)
            self.lbl_host_msg.configure(text="已复制：%s（发给其他电脑填写）" % txt)
        except Exception as e:
            messagebox.showerror("复制失败", str(e), parent=self)

    def new_code(self):
        import random
        self.var_code.set("%06d" % random.randint(0, 999999))
        if self.app.lan_mode == "host":
            self.app.stop_lan_host()
            self.toggle_host()

    def toggle_host(self):
        st = self.app.lan_status()
        if st["mode"] == "client":
            # 客户端下按钮已置灰；万一被外部调用也直接拒绝，防止误断连接
            self.refresh()
            self.lbl_cli_msg.configure(
                text="⚠ 本机是客户端，不能直接开启共享。请先点「断开 / 回到本机」。",
                fg=CLR_DANGER)
            return
        if st["running"]:
            self.app.stop_lan_host()
            self.refresh()
            return
        code = self.var_code.get().strip()
        try:
            port = int(self.var_port.get().strip() or DEFAULT_PORT)
        except ValueError:
            messagebox.showwarning("端口", "端口请填数字", parent=self)
            return
        ok, msg = self.app.start_lan_host(port, code)
        if not ok:
            messagebox.showerror("开启共享失败", msg, parent=self)
        self.refresh()

    def toggle_default_allow(self):
        self.app.set_lan_default_allow(bool(self.var_allow_new.get()))
        self.refresh()

    def toggle_client(self):
        sel = self.tree.selection()
        if not sel:
            return
        ip = sel[0]
        cur = [c for c in self.app.lan_status()["clients"] if c["ip"] == ip]
        flag = not (cur and cur[0].get("explicit"))
        self.app.set_lan_allow(ip, flag)
        self.refresh()

    def _sel_changed(self):
        # 只切换按钮状态，不做全量 refresh——重建列表时 delete 会再触发本事件，
        # 全量 refresh 会引发事件风暴卡死 Tk（v1.11.4 实测）
        if getattr(self, "_in_refresh", False):
            return
        sel = bool(self.tree.selection())
        state = "normal" if sel else "disabled"
        for b in (self.btn_kick, self.btn_blk):
            if str(b.cget("state")) != state:
                b.configure(state=state)

    def _sel_client(self):
        """选中的已连接电脑：返回 (ip, name) 或 None。"""
        sel = self.tree.selection()
        if not sel:
            return None
        ip = sel[0]
        vals = self.tree.item(ip, "values")
        return ip, (vals[0] if vals else "")

    def kick_client(self):
        c = self._sel_client()
        if not c:
            return
        ip, name = c
        if not messagebox.askyesno(
                "移除连接",
                "确定移除 %s（%s）的连接吗？\n\n"
                "对方电脑会立即断开、自动回到本机数据，之后仍可重新连接。"
                % (name or "未知电脑", ip), parent=self, icon="warning"):
            return
        self.app.lan_kick_client(ip)
        self.refresh()

    def block_client(self):
        c = self._sel_client()
        if not c:
            return
        ip, name = c
        if not messagebox.askyesno(
                "加入黑名单",
                "确定把 %s（%s）加入黑名单吗？\n\n"
                "加入后这台电脑将无法再连接本机共享（连接码正确也不行），\n"
                "直到在「黑名单管理」里移出。" % (name or "未知电脑", ip),
                parent=self, icon="warning"):
            return
        self.app.lan_block_client(ip, name)
        self.refresh()

    def manage_blocked(self):
        win = tk.Toplevel(self)
        win.title("黑名单管理")
        win.configure(bg=CLR_BG)
        win.transient(self)
        win.resizable(False, False)
        apply_window_icon(win)
        win.grab_set()
        tk.Label(win, text="黑名单里的电脑无法连接本机共享（连接码正确也不行）。",
                 bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 9)).pack(
            anchor="w", padx=16, pady=(14, 6))
        cols = ("ip", "name")
        tv = ttk.Treeview(win, columns=cols, show="headings", height=8)
        for key, title, w in (("ip", "地址", 150), ("name", "电脑", 180)):
            tv.heading(key, text=title)
            tv.column(key, width=w, anchor="center")
        tv.pack(fill="both", expand=True, padx=16)

        def fill():
            tv.delete(*tv.get_children())
            for b in self.app.lan_blocked():
                tv.insert("", "end", iid=b["ip"],
                          values=(b["ip"], b.get("name") or "未知电脑"))

        fill()
        rowb = tk.Frame(win, bg=CLR_BG)
        rowb.pack(fill="x", padx=16, pady=10)

        def remove_sel():
            sel = tv.selection()
            if not sel:
                messagebox.showinfo("移出黑名单", "请先在列表里选中一台电脑。",
                                    parent=win)
                return
            self.app.lan_unblock(sel[0])
            fill()
            self.refresh()

        ttk.Button(rowb, text="移出黑名单", width=11,
                   command=remove_sel).pack(side="left")
        ttk.Button(rowb, text="关闭", width=9,
                   command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())
        center_window(win, self, size=(420, 360))

    # -------- 客户端
    def _fields(self):
        host = self.var_host.get().strip()
        try:
            port = int(self.var_cport.get().strip() or DEFAULT_PORT)
        except ValueError:
            return None, "端口请填数字"
        code = self.var_ccode.get().strip()
        if not host:
            return None, "请填写主机地址（如 192.168.1.10）"
        if not code:
            return None, "请填写主机上显示的连接码"
        return (host, port, code), ""

    def _async(self, fn, done):
        box = {}

        def work():
            try:
                box["value"] = fn()
            except Exception as e:
                box["error"] = e
            box["done"] = True
        threading.Thread(target=work, daemon=True).start()

        def poll():
            if box.get("done"):
                done(box)
            else:
                try:
                    self.after(120, poll)
                except tk.TclError:
                    pass
        self.after(120, poll)

    # -------- 进度条
    def _start_progress(self):
        """连接/测试期间显示流动进度条（探测在后台线程，界面保持响应）。"""
        try:
            self.pb.pack(fill="x", padx=14, pady=(0, 2), before=self.lbl_cli_msg)
            self.pb.start(14)
        except Exception:
            pass

    def _stop_progress(self):
        try:
            self.pb.stop()
            self.pb.pack_forget()
        except Exception:
            pass

    def _probe_async(self, f, busy_msg, done):
        """后台探测主机（超时 8 秒），期间锁按钮 + 显示进度条。"""
        if self._conn_busy:
            return
        self._conn_busy = True
        self.btn_conn.configure(state="disabled")
        self.btn_test.configure(state="disabled")
        self.lbl_cli_msg.configure(text=busy_msg, fg=CLR_MUTED)
        self._start_progress()
        from .remote import RemoteStore

        def go():
            rs = RemoteStore(f[0], f[1], f[2], self.app.lan_cfg.get("client_id") or "",
                             self.app.lan_cfg.get("client_name") or "", timeout=8)
            rs.ping()
            return rs

        def finish(box):
            self._conn_busy = False
            self._stop_progress()
            self.btn_conn.configure(state="normal")
            self.btn_test.configure(state="normal")
            done(box)
        self._async(go, finish)

    def _hist_entries(self):
        return [h for h in (self.app.lan_cfg.get("history") or [])
                if isinstance(h, dict) and str(h.get("host") or "")]

    def refresh_hist(self):
        """刷新「历史连接」下拉（最近连过的排最前）。"""
        import time as _t
        ents = self._hist_entries()
        vals = []
        for e in ents:
            try:
                when = _t.strftime("%m-%d %H:%M",
                                   _t.localtime(float(e.get("time") or 0)))
            except Exception:
                when = ""
            vals.append("%s:%s · 上次 %s" % (e.get("host"), e.get("port"), when))
        self.cb_hist["values"] = vals
        if vals:
            try:
                self.cb_hist.current(0)
                return
            except Exception:
                pass
        self.cb_hist.set("（暂无，连接成功后自动记录）")

    def _pick_history(self, event=None):
        idx = self.cb_hist.current()
        ents = self._hist_entries()
        if not (0 <= idx < len(ents)):
            return
        e = ents[idx]
        self.var_host.set(str(e.get("host") or ""))
        self.var_cport.set(str(e.get("port") or DEFAULT_PORT))
        self.var_ccode.set(str(e.get("code") or ""))
        self.lbl_cli_msg.configure(
            text="已填入历史连接 %s:%s，点「连接」即可（拿不准可先「测试连接」）。"
                 % (e.get("host"), e.get("port")), fg=CLR_MUTED)

    def clear_history(self):
        if not messagebox.askyesno("清空历史连接",
                                   "确定清空全部历史连接记录吗？\n\n"
                                   "（不影响当前连接）", parent=self):
            return
        self.app.lan_cfg["history"] = []
        self.app._save_lan_cfg()
        self.refresh_hist()

    def test_conn(self):
        f, err = self._fields()
        if err:
            self.lbl_cli_msg.configure(text="⚠ " + err, fg=CLR_DANGER)
            return

        def done(box):
            if "error" in box:
                self.lbl_cli_msg.configure(text="⚠ %s" % box["error"], fg=CLR_DANGER)
                return
            info = (box.get("value").last_ping if hasattr(box.get("value"),
                                                           "last_ping")
                    else (box.get("value") or {}))
            self.lbl_cli_msg.configure(
                text="连接成功：主机版本 %s · 仓库「%s」 · %s"
                     % (info.get("version"), info.get("warehouse") or "—",
                        "可录入" if info.get("can_write") else "只读（可在主机上授权）"),
                fg=CLR_OK)
        self._probe_async(f, "正在连接 %s:%s …" % (f[0], f[1]), done)

    def connect(self):
        f, err = self._fields()
        if err:
            self.lbl_cli_msg.configure(text="⚠ " + err, fg=CLR_DANGER)
            return
        if self.app.lan_mode == "host":
            # 主机 → 客户端：会停掉对别人的共享，先确认
            n = len(self.app.lan_status()["clients"])
            if not messagebox.askyesno(
                    "切换成客户端",
                    "本机正在作为主机共享%s。\n\n"
                    "连接其他主机会先停止本机共享，已连上的电脑会断开。\n\n"
                    "确定切换成客户端吗？" % ("（当前 %d 台电脑连着）" % n if n else ""),
                    parent=self, icon="warning"):
                return

        def done(box):
            if "error" in box:
                # 探测失败：进度条已收起，给出明确错误，界面不会卡
                self.lbl_cli_msg.configure(text="⚠ %s" % box["error"], fg=CLR_DANGER)
                return
            rs = box["value"]
            # 探测通过，读取主机数据期间继续显示进度条
            self.lbl_cli_msg.configure(text="已连通，正在读取主机数据 …", fg=CLR_MUTED)
            self._start_progress()
            try:
                ok, msg = self.app.connect_lan(f[0], f[1], f[2], probe=rs)
            finally:
                self._stop_progress()
            self.refresh()
            self.lbl_cli_msg.configure(
                text=("已连接：%s" % msg) if ok else ("⚠ %s" % msg),
                fg=CLR_OK if ok else CLR_DANGER)
        self._probe_async(f, "正在连接主机 %s:%s …（最长约 8 秒）" % (f[0], f[1]), done)

    def disconnect(self):
        ok, msg = self.app.disconnect_lan()
        self.refresh()
        self.lbl_cli_msg.configure(text=msg, fg=CLR_MUTED)

    def ask_write(self):
        self.app.ask_write_permission()
        self.refresh()

    def destroy(self):
        try:
            if getattr(self.app, "lan_dlg", None) is self:
                self.app.lan_dlg = None
        except Exception:
            pass
        try:
            if self._qr_path and os.path.exists(self._qr_path):
                os.remove(self._qr_path)
        except Exception:
            pass
        super().destroy()
