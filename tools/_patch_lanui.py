# -*- coding: utf-8 -*-
"""一次性补丁：lanui.py 加 rename_client / show_sales_stats。"""
p = 'wm/lanui.py'
s = open(p, encoding='utf-8').read()

subs = [
    ("from tkinter import messagebox, ttk",
     "from tkinter import messagebox, simpledialog, ttk"),
    ('    def show_access_log(self):', 'SPLIT_HERE'),
]

for a, b in subs:
    assert a in s, a[:60]
    s = s.replace(a, b)

methods = '''    def rename_client(self):
        """主机改选中客户端的显示名（覆盖客户端上报的名字，重启后仍生效）。"""
        c = self._sel_client()
        if not c:
            return
        ip, name = c
        new = simpledialog.askstring(
            "改名", "给 %s（%s）换个显示名：\\n\\n改名后对方自己上报的电脑名将不再使用。"
            % (name or "未知电脑", ip), initialvalue=name or "", parent=self)
        if new is None:
            return
        new = (new or "").strip()
        if not new:
            messagebox.showwarning("改名", "名字不能为空。", parent=self)
            return
        ok, msg = self.app.lan_rename_client(ip, new)
        if not ok:
            messagebox.showerror("改名", msg, parent=self)
        self.refresh()

    def show_sales_stats(self):
        """按来源（主机 / 各台电脑 / 手机）汇总销售数据。"""
        srv = getattr(self.app, "lan_server", None)
        if srv is None or not srv.running():
            return
        win = tk.Toplevel(self)
        win.title("销售统计（按设备）")
        win.configure(bg=CLR_BG)
        center_window(win, 560, 380)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        apply_window_icon(win)

        top = tk.Frame(win, bg=CLR_BG)
        top.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(top, text="统计范围", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        var_days = tk.StringVar(value="全部")
        box = ttk.Combobox(top, textvariable=var_days, state="readonly",
                           width=10, values=("今天", "近7天", "近30天", "全部"))
        box.pack(side="left", padx=(6, 0))
        lbl_total = tk.Label(win, text="", bg=CLR_BG, fg=CLR_TEXT,
                             font=(self.fam, 10, "bold"), anchor="w",
                             justify="left")
        lbl_total.pack(fill="x", padx=14, pady=(2, 4))

        wrap = tk.Frame(win, bg=CLR_BG, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        cols = ("src", "count", "qty", "amount", "cost", "profit")
        tv = ttk.Treeview(wrap, columns=cols, show="headings")
        for key, title, w in (("src", "来源设备", 170), ("count", "笔数", 60),
                              ("qty", "件数", 60), ("amount", "销售额", 90),
                              ("cost", "成本", 80), ("profit", "毛利", 80)):
            tv.heading(key, text=title)
            tv.column(key, width=w, anchor="center")
        tv.pack(fill="both", expand=True)

        DAYS = {"今天": 1, "近7天": 7, "近30天": 30, "全部": 0}

        def fill():
            d = DAYS.get(var_days.get(), 0)
            data = self.app.lan_sales_stats(d)
            tv.delete(*tv.get_children())
            t = data.get("total") or {}
            lbl_total.configure(
                text="合计：销售 %d 笔 / %d 件 · 销售额 ¥%.2f · 毛利 ¥%.2f"
                     % (t.get("count") or 0, t.get("qty") or 0,
                        t.get("amount") or 0.0, t.get("profit") or 0.0))
            rows = data.get("rows") or []
            if not rows:
                tv.insert("", "end", values=("暂无销售记录", "", "", "", "", ""))
                return
            for r in rows:
                tv.insert("", "end", values=(
                    r.get("src") or "未知来源", r.get("count") or 0,
                    r.get("qty") or 0,
                    "%.2f" % (r.get("amount") or 0.0),
                    "%.2f" % (r.get("cost") or 0.0),
                    "%.2f" % (r.get("profit") or 0.0)))

        box.bind("<<ComboboxSelected>>", lambda _e: fill())
        fill()
        # 弹窗打开期间主机端继续卖出 → 3 秒自动刷新
        aid = [None]

        def tick():
            if not win.winfo_exists():
                return
            try:
                fill()
            except Exception:
                pass
            aid[0] = win.after(3000, tick)

        tick()
        win.bind("<Escape>", lambda _e: win.destroy())

'''

s = s.replace('SPLIT_HERE', methods + '    def show_access_log(self):')
open(p, 'w', encoding='utf-8').write(s)
print('methods ok')
