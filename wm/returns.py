# -*- coding: utf-8 -*-
"""销售退货（v1.32.0）：按出售记录登记退货，可选把货退回库存。

一个口径：退货冲减原单 —— 利润表里该笔的实收和成本都会同步减掉，
所以「卖出去又退回来」的货不会虚增利润，也不会凭空产生库存。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_MUTED,
                        CLR_ROW_ALT, CLR_TEXT, CLR_WARN,
                        apply_window_icon, center_window)
from .sales import money, today

COLS = [("return_date", "退货日期", 96, "center"), ("code", "编号", 120, "w"),
        ("brand", "品牌", 100, "center"), ("model", "型号", 140, "w"),
        ("qty", "退货数量", 78, "center"), ("refund", "退款(元)", 96, "e"),
        ("cost", "成本单价", 88, "e"), ("restock", "退回库存", 78, "center"),
        ("buyer", "客户", 100, "w"), ("remark", "备注", 160, "w")]


class ReturnDialog(tk.Toplevel):
    """选一笔出售 → 填退货数量/退款 → 确认。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.store = app.store
        self.result = None
        self._rows = []
        self._sel = None
        self.title("登记销售退货")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x")
        tk.Label(head, text="登记销售退货", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left",
                                                   padx=16, pady=12)
        tk.Label(head, text="① 选原出售记录　② 填退货数量　③ 确认",
                 bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="right", padx=16)

        body = tk.Frame(self, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)

        # ---- 搜索 + 出售记录列表 ----
        sf = tk.Frame(body, bg=CLR_BG)
        sf.pack(fill="x")
        tk.Label(sf, text="搜索编号 / 型号 / 客户", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_kw = tk.StringVar()
        e = tk.Entry(sf, textvariable=self.var_kw, width=24,
                     font=(self.fam, 10), relief="solid", bd=1)
        e.pack(side="left", padx=(6, 0), ipady=2)
        e.bind("<KeyRelease>", lambda ev: self._load_sales())
        e.focus_set()

        wrap = tk.Frame(body, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, pady=(6, 10))
        cols = ("date", "code", "brand", "model", "qty", "left", "price", "buyer")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 height=9, selectmode="browse")
        vs = ttk.Scrollbar(wrap, orient="vertical",
                           style="Vertical.TScrollbar", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w in (("date", "出售日期", 90), ("code", "编号", 110),
                              ("brand", "品牌", 90), ("model", "型号", 130),
                              ("qty", "卖出", 56), ("left", "可退", 56),
                              ("price", "单价", 76), ("buyer", "客户", 90)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, anchor="center")
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_pick())

        # ---- 表单 ----
        form = tk.Frame(body, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        form.pack(fill="x")
        inner = tk.Frame(form, bg=CLR_CARD)
        inner.pack(fill="x", padx=12, pady=10)
        self.lbl_pick = tk.Label(inner, text="尚未选择出售记录", bg=CLR_CARD,
                                 fg=CLR_MUTED, font=(self.fam, 9), anchor="w")
        self.lbl_pick.grid(row=0, column=0, columnspan=4, sticky="w",
                           pady=(0, 8))

        self.var_qty = tk.StringVar()
        self.var_refund = tk.StringVar()
        self.var_date = tk.StringVar(value=today())
        self.var_remark = tk.StringVar()
        self.var_restock = tk.BooleanVar(value=True)

        def field(r, c, label, var, width=12):
            tk.Label(inner, text=label, bg=CLR_CARD, fg=CLR_TEXT,
                     font=(self.fam, 9)).grid(row=r, column=c, sticky="e",
                                              padx=(0 if c == 0 else 14, 6),
                                              pady=4)
            ent = tk.Entry(inner, textvariable=var, width=width,
                           font=(self.fam, 10), relief="solid", bd=1)
            ent.grid(row=r, column=c + 1, sticky="w", pady=4)
            return ent

        self.ent_qty = field(1, 0, "退货数量", self.var_qty, 10)
        field(1, 2, "退款金额", self.var_refund, 12)
        field(2, 0, "退货日期", self.var_date, 10)
        tk.Checkbutton(inner, text="把货退回库存（库存 +退货数量）",
                       variable=self.var_restock, bg=CLR_CARD, fg=CLR_TEXT,
                       activebackground=CLR_CARD, selectcolor="#FFFFFF",
                       font=(self.fam, 9)).grid(row=2, column=2,
                                                columnspan=2, sticky="w")
        field(3, 0, "备注", self.var_remark, 40)
        self.var_qty.trace_add("write", lambda *_: self._sync_refund())

        self.msg = tk.Label(body, text="", bg=CLR_BG, fg=CLR_WARN,
                            font=(self.fam, 9), anchor="w")
        self.msg.pack(fill="x")

        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="确认退货", style="Accent.TButton", width=11,
                   command=self._ok).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10,
                   command=self._cancel).pack(side="right", pady=12)

        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._load_sales()
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    # ------------------------------------------------------------ 列表
    def _load_sales(self):
        kw = self.var_kw.get().strip()
        try:
            rows = self.store.list_sales(scope="sale", kw=kw)
        except Exception as e:
            rows = []
            self.msg.configure(text="读取出售记录失败：%s" % e)
        # 只留还有可退数量的
        out = []
        for r in rows[:300]:
            left = self.store.returnable_qty(r["id"])
            if left > 0:
                out.append((r, left))
        self._rows = out
        self.tree.delete(*self.tree.get_children())
        for r, left in out:
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r.get("sale_date") or "", r.get("code") or "",
                r.get("brand") or "", r.get("model") or "",
                int(r.get("qty") or 0), left,
                "%.2f" % float(r.get("price") or 0), r.get("buyer") or ""))

    def _on_pick(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = str(sel[0])
        pair = [p for p in self._rows if str(p[0]["id"]) == iid]
        if not pair:
            return
        rec, left = pair[0]
        self._sel = (rec, left)
        self.lbl_pick.configure(
            text="已选：%s  %s %s · 卖出 %d 件 · 单价 %.2f 元 · 可退 %d 件"
                 % (rec.get("code") or "", rec.get("brand") or "",
                    rec.get("model") or "", int(rec.get("qty") or 0),
                    float(rec.get("price") or 0), left),
            fg=CLR_TEXT)
        self.var_qty.set(str(left))
        self._sync_refund()

    def _sync_refund(self):
        if not self._sel:
            return
        rec, _left = self._sel
        try:
            q = int(float(self.var_qty.get() or 0))
        except ValueError:
            return
        price = float(rec.get("price") or 0)
        self.var_refund.set("%.2f" % (price * max(0, q)))

    # ------------------------------------------------------------ 提交
    def _ok(self):
        if not self._sel:
            self.msg.configure(text="⚠ 请先在上面选一条出售记录")
            return
        rec, left = self._sel
        try:
            q = int(float(self.var_qty.get() or 0))
        except ValueError:
            self.msg.configure(text="⚠ 退货数量必须是整数")
            return
        if q <= 0 or q > left:
            self.msg.configure(text="⚠ 退货数量要在 1 ~ %d 之间" % left)
            return
        try:
            refund = float(self.var_refund.get() or 0)
        except ValueError:
            self.msg.configure(text="⚠ 退款金额必须是数字")
            return
        try:
            ok, msg = self.store.add_return(
                rec["id"], q, refund, self.var_restock.get(),
                self.var_date.get().strip(), self.var_remark.get().strip())
        except Exception as e:
            ok, msg = False, str(e)
        if not ok:
            self.msg.configure(text="⚠ " + msg)
            return
        self.result = msg
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_return(master, app, fam="Microsoft YaHei UI"):
    dlg = ReturnDialog(master, app, fam)
    master.wait_window(dlg)
    return dlg.result


class ReturnTab(ttk.Frame):
    """销售退货记录页。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.rows = []
        self._by_id = {}
        self._job = None
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x")
        tk.Label(bar, text="销售退货", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left",
                                                   padx=(16, 10), pady=12)
        self.lbl_wh = tk.Label(bar, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                               font=(self.fam, 9))
        self.lbl_wh.pack(side="left", pady=12)
        tk.Label(bar, text="退货会冲减原出售记录的利润；勾了「退回库存」的会把货加回库存",
                 bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(10, 0), pady=12)
        ttk.Button(bar, text="+ 登记退货", style="Accent.TButton",
                   command=self.new_return).pack(side="right",
                                                 padx=(8, 16), pady=8)
        ttk.Button(bar, text="刷新", command=self.refresh_tab).pack(
            side="right", pady=8)

        flt = tk.Frame(self, bg=CLR_BG)
        flt.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(flt, text="日期", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_start = tk.StringVar()
        self.var_end = tk.StringVar()
        for var, ph in ((self.var_start, "起"), (self.var_end, "止")):
            e = tk.Entry(flt, textvariable=var, width=11, font=(self.fam, 10),
                         relief="solid", bd=1)
            e.pack(side="left", padx=(4, 2), ipady=2)
            e.bind("<KeyRelease>", lambda ev: self._debounce())
            tk.Label(flt, text=ph, bg=CLR_BG, fg=CLR_MUTED,
                     font=(self.fam, 8)).pack(side="left", padx=(0, 6))
        tk.Label(flt, text="搜索", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(8, 4))
        self.var_kw = tk.StringVar()
        e = tk.Entry(flt, textvariable=self.var_kw, width=20,
                     font=(self.fam, 10), relief="solid", bd=1)
        e.pack(side="left", ipady=2)
        e.bind("<KeyRelease>", lambda ev: self._debounce())
        ttk.Button(flt, text="本月", style="Ghost.TButton", width=6,
                   command=self._this_month).pack(side="left", padx=(10, 4))
        ttk.Button(flt, text="重置", style="Ghost.TButton", width=6,
                   command=self.reset_filters).pack(side="left")

        cards = tk.Frame(self, bg=CLR_BG)
        cards.pack(fill="x", padx=16, pady=(10, 0))
        self.kpi = {}
        for key, title in (("count", "退货笔数"), ("qty", "退货件数"),
                           ("refund", "退款合计(元)"), ("cost", "退回成本(元)")):
            card = tk.Frame(cards, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                            highlightthickness=1)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(card, text=title, bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.fam, 9)).pack(anchor="w", padx=12, pady=(8, 0))
            lbl = tk.Label(card, text="0", bg=CLR_CARD, fg=CLR_TEXT,
                           font=(self.fam, 13, "bold"))
            lbl.pack(anchor="w", padx=12, pady=(0, 8))
            self.kpi[key] = lbl

        wrap = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=10)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in COLS],
                                 show="headings", selectmode="extended")
        vs = ttk.Scrollbar(wrap, orient="vertical",
                           style="Vertical.TScrollbar", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w, anchor in COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=int(w * self.app.ui_scale),
                             anchor=anchor, stretch=(key in ("model", "remark")))
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("keep", background=CLR_ROW_ALT)   # 未退回库存

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 10))
        self.lbl_hint = tk.Label(foot, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=(self.fam, 9))
        self.lbl_hint.pack(side="left")
        ttk.Button(foot, text="撤销选中退货", style="Danger.TButton",
                   command=self.undo_selected).pack(side="right")

    # ------------------------------------------------------------ 数据
    def refresh_tab(self):
        try:
            self.lbl_wh.configure(text="当前仓库：%s" % self.app.cur_wh()["name"])
        except Exception:
            pass
        self.refresh_rows()

    def _debounce(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(280, self.refresh_rows)

    def _this_month(self):
        d = today()
        self.var_start.set(d[:8] + "01")
        self.var_end.set(d)
        self.refresh_rows()

    def reset_filters(self):
        self.var_start.set("")
        self.var_end.set("")
        self.var_kw.set("")
        self.refresh_rows()

    def refresh_rows(self):
        start = self.var_start.get().strip()
        end = self.var_end.get().strip()
        try:
            self.rows = self.app.store.list_returns(start, end,
                                                    self.var_kw.get())
            t = self.app.store.returns_total(start, end)
        except Exception as e:
            self.rows, t = [], {}
            self.lbl_hint.configure(text="读取退货记录失败：%s" % e)
            return
        self.tree.delete(*self.tree.get_children())
        self._by_id = {}
        for i, r in enumerate(self.rows):
            iid = str(r["id"])
            self._by_id[iid] = r
            restock = "是" if int(r.get("restock") or 0) else "否"
            self.tree.insert("", "end", iid=iid,
                             tags=() if int(r.get("restock") or 0) else ("keep",),
                             values=(r.get("return_date") or "",
                                     r.get("code") or "", r.get("brand") or "",
                                     r.get("model") or "",
                                     str(int(r.get("qty") or 0)),
                                     "%.2f" % float(r.get("refund") or 0),
                                     "%.2f" % float(r.get("cost") or 0),
                                     restock, r.get("buyer") or "",
                                     r.get("remark") or ""))
        for key in ("count", "qty"):
            self.kpi[key].configure(text=str(t.get(key, 0)))
        for key in ("refund", "cost"):
            self.kpi[key].configure(text=money(t.get(key, 0)))
        self.lbl_hint.configure(
            text="共 %d 笔退货 · 双击可撤销 ·「退回库存=否」表示只退钱没回货"
                 % len(self.rows))

    # ------------------------------------------------------------ 操作
    def new_return(self):
        if self._guard():
            return
        msg = ask_return(self.app.root, self.app, self.fam)
        if not msg:
            return
        self.app.load_data()
        self.refresh_rows()
        self.app._status(msg)

    def undo_selected(self):
        if self._guard():
            return
        sel = self.tree.selection()
        if not sel:
            self.lbl_hint.configure(text="请先选中要撤销的退货记录")
            return
        names = "、".join((self._by_id[str(i)].get("code") or "")
                         for i in sel[:3])
        if not messagebox.askyesno(
                "撤销退货",
                "确定撤销选中的 %d 笔退货吗？\n\n%s%s\n\n"
                "已退回库存的货会再扣回去（库存不足会拦下），"
                "利润表也会同步恢复。"
                % (len(sel), names, "…" if len(sel) > 3 else ""),
                parent=self.app.root):
            return
        n, err = 0, ""
        for iid in sel:
            ok, msg = self.app.store.delete_return(int(iid))
            if ok:
                n += 1
            else:
                err = msg
        self.app.load_data()
        self.refresh_rows()
        if err:
            messagebox.showwarning("撤销退货", err, parent=self.app.root)
        self.app._status("已撤销 %d 笔退货" % n)

    def _guard(self):
        try:
            return bool(self.app._guard_write())
        except Exception:
            return False
