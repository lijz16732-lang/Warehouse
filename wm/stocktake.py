# -*- coding: utf-8 -*-
"""盘点单（v1.32.0）：按条件拍快照 → 填实盘数 → 提交后按实盘改库存。

流程刻意做成「先拍快照、再逐条填、最后一次性提交」：
盘点期间别人照常开单出库也不会把账面数带跑，提交时点的是快照里的数。
"""

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_LOW_BG,
                        CLR_MUTED, CLR_TEXT, CLR_WARN, apply_window_icon,
                        center_window)
from .sales import today

LIST_COLS = [("no", "单号", 130, "w"), ("name", "名称", 180, "w"),
             ("status", "状态", 68, "center"), ("count", "记录数", 70, "center"),
             ("diff", "差异条数", 78, "center"), ("diff_qty", "净差异(件)", 84, "center"),
             ("created_at", "创建时间", 130, "center"),
             ("done_at", "提交时间", 130, "center")]

ITEM_COLS = [("code", "编号", 120, "w"), ("brand", "品牌", 100, "center"),
             ("model", "型号", 150, "w"), ("shelf", "货架", 100, "center"),
             ("book_qty", "账面", 70, "center"), ("real_qty", "实盘", 70, "center"),
             ("diff", "差异", 70, "center"), ("note", "备注", 170, "w")]

STATUS_TEXT = {"draft": "进行中", "done": "已提交"}


class NewStocktakeDialog(tk.Toplevel):
    """选择盘点范围 → 生成盘点单。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.result = None
        self.title("新建盘点单")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x")
        tk.Label(head, text="新建盘点单", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left",
                                                   padx=16, pady=12)
        tk.Label(head, text="按条件把库存拍成快照，之后逐条填实盘数",
                 bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="right", padx=16)

        body = tk.Frame(self, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.columnconfigure(1, weight=1)

        self.vars = {}
        self.var_only = tk.BooleanVar(value=True)

        def row(i, label, key, values=None):
            tk.Label(body, text=label, bg=CLR_BG, fg="#41506B",
                     font=(self.fam, 10), anchor="w").grid(
                row=i, column=0, sticky="w", padx=(0, 10), pady=6)
            v = tk.StringVar(value="" if values is None else "全部")
            self.vars[key] = v
            if values is None:
                ttk.Entry(body, textvariable=v, width=28,
                          font=(self.fam, 10)).grid(row=i, column=1,
                                                    sticky="ew", pady=6)
            else:
                ttk.Combobox(body, textvariable=v, values=values,
                             state="readonly", width=26,
                             font=(self.fam, 10)).grid(row=i, column=1,
                                                       sticky="w", pady=6)

        row(0, "单据名称", "name")
        self.vars["name"].set("盘点 %s" % today())
        sug = self.app.suggestions()
        row(1, "品牌", "brand", ["全部"] + list(sug.get("brand") or []))
        row(2, "品类", "category", ["全部"] + list(sug.get("category") or []))
        row(3, "货架", "shelf", ["全部"] + list(sug.get("shelf") or []))
        row(4, "关键词", "kw")
        tk.Checkbutton(body, text="只盘有货的（库存 > 0）", variable=self.var_only,
                       bg=CLR_BG, fg=CLR_TEXT, activebackground=CLR_BG,
                       selectcolor="#FFFFFF", font=(self.fam, 9)).grid(
            row=5, column=1, sticky="w", pady=(4, 0))

        self.msg = tk.Label(body, text="", bg=CLR_BG, fg=CLR_WARN,
                            font=(self.fam, 9), anchor="w")
        self.msg.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="生成盘点单", style="Accent.TButton", width=12,
                   command=self._ok).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10,
                   command=self._cancel).pack(side="right", pady=12)

        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    def _ok(self):
        v = {k: (x.get() or "").strip() for k, x in self.vars.items()}
        try:
            st_id, msg = self.app.store.create_stocktake(
                v["name"], v["brand"], v["category"], v["shelf"], v["kw"],
                self.var_only.get())
        except Exception as e:
            self.msg.configure(text="⚠ %s" % e)
            return
        if not st_id:
            self.msg.configure(text="⚠ " + msg)
            return
        self.result = (st_id, msg)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class StocktakeDialog(tk.Toplevel):
    """填实盘数 + 提交。双击某行改数量。"""

    def __init__(self, master, app, st_id, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.st_id = int(st_id)
        self.detail = app.store.stocktake_detail(self.st_id) or {}
        self.rows_by_id = {}
        self.changed = False
        self.title("盘点单")
        self.configure(bg=CLR_BG)
        self.geometry("980x640")
        self.transient(master)
        apply_window_icon(self)

        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x")
        h = self.detail.get("head") or {}
        tk.Label(head, text=h.get("no") or "", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left",
                                                   padx=(16, 10), pady=12)
        self.lbl_status = tk.Label(head, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                                   font=(self.fam, 9))
        self.lbl_status.pack(side="left", pady=12)
        tk.Label(head, text=h.get("name") or "", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(10, 0), pady=12)

        flt = tk.Frame(self, bg=CLR_BG)
        flt.pack(fill="x", padx=16, pady=(10, 0))
        self.var_only_diff = tk.BooleanVar(value=False)
        tk.Checkbutton(flt, text="只看有差异的", variable=self.var_only_diff,
                       command=self.refresh_rows, bg=CLR_BG, fg=CLR_TEXT,
                       activebackground=CLR_BG, selectcolor="#FFFFFF",
                       font=(self.fam, 9)).pack(side="left")
        tk.Label(flt, text="提示：双击一行改实盘数；账面数不会自己变",
                 bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(14, 0))
        self.lbl_stat = tk.Label(flt, text="", bg=CLR_BG, fg=CLR_TEXT,
                                 font=(self.fam, 9, "bold"))
        self.lbl_stat.pack(side="right")

        wrap = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=10)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in ITEM_COLS],
                                 show="headings", selectmode="browse")
        vs = ttk.Scrollbar(wrap, orient="vertical",
                           style="Vertical.TScrollbar", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w, anchor in ITEM_COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=int(w * app.ui_scale), anchor=anchor,
                             stretch=(key in ("model", "note")))
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        # tag 优先级 = 创建先后：差异橙 > 斑马纹
        self.tree.tag_configure("diff", background=CLR_LOW_BG)
        self.tree.tag_configure("odd", background="#F7FAFD")
        self.tree.bind("<Double-1>", lambda e: self.edit_qty())

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 10))
        ttk.Button(foot, text="关闭", width=8,
                   command=self._close).pack(side="right")
        self.btn_commit = ttk.Button(foot, text="提交盘点（按实盘改库存）",
                                     style="Accent.TButton",
                                     command=self.commit)
        self.btn_commit.pack(side="right", padx=(0, 8))
        ttk.Button(foot, text="全部按账面", style="Ghost.TButton", width=10,
                   command=self.fill_book).pack(side="right", padx=(0, 8))
        ttk.Button(foot, text="改实盘数", style="Ghost.TButton", width=9,
                   command=self.edit_qty).pack(side="right", padx=(0, 8))

        self.refresh_rows()
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    # ------------------------------------------------------------ 数据
    def refresh_rows(self):
        self.detail = self.app.store.stocktake_detail(self.st_id) or {}
        head = self.detail.get("head") or {}
        rows = self.detail.get("rows") or []
        status = head.get("status") or "draft"
        self.lbl_status.configure(text=STATUS_TEXT.get(status, status))
        done = status == "done"
        self.btn_commit.configure(state="disabled" if done else "normal")
        self.tree.delete(*self.tree.get_children())
        self.rows_by_id = {}
        shown = 0
        for i, r in enumerate(rows):
            d = int(r.get("real_qty") or 0) - int(r.get("book_qty") or 0)
            if self.var_only_diff.get() and d == 0:
                continue
            iid = str(r["id"])
            self.rows_by_id[iid] = r
            tags = ["diff"] if d else (["odd"] if i % 2 else [])
            self.tree.insert("", "end", iid=iid, tags=tuple(tags), values=(
                r.get("code") or "", r.get("brand") or "",
                r.get("model") or "", r.get("shelf") or "",
                str(int(r.get("book_qty") or 0)), str(int(r.get("real_qty") or 0)),
                "%+d" % d if d else "0", r.get("note") or ""))
            shown += 1
        ndiff = sum(1 for r in rows
                    if int(r.get("real_qty") or 0) != int(r.get("book_qty") or 0))
        net = sum(int(r.get("real_qty") or 0) - int(r.get("book_qty") or 0)
                  for r in rows)
        self.lbl_stat.configure(
            text="共 %d 条 · 差异 %d 条 · 净变动 %+d 件（当前显示 %d 条）"
                 % (len(rows), ndiff, net, shown))

    # ------------------------------------------------------------ 操作
    def edit_qty(self):
        sel = self.tree.selection()
        if not sel:
            return
        rec = self.rows_by_id.get(str(sel[0]))
        if rec is None:
            return
        if (self.detail.get("head") or {}).get("status") == "done":
            messagebox.showinfo("盘点单", "这张盘点单已经提交，不能再改。",
                                parent=self)
            return
        cur = int(rec.get("real_qty") or 0)
        v = simpledialog.askinteger(
            "实盘数量",
            "%s %s\n账面 %d 件\n\n实盘数量："
            % (rec.get("code") or "", rec.get("model") or "",
               int(rec.get("book_qty") or 0)),
            initialvalue=cur, minvalue=0, parent=self)
        if v is None:
            return
        ok, msg = self.app.store.set_stocktake_qty(rec["id"], v)
        if not ok:
            messagebox.showwarning("实盘数量", msg, parent=self)
            return
        self.changed = True
        keep = str(sel[0])
        self.refresh_rows()
        if self.tree.exists(keep):
            self.tree.selection_set(keep)
            self.tree.see(keep)

    def fill_book(self):
        """把所有实盘数重置回账面（等于「没盘出错」，常用于先清空再重填）。"""
        if (self.detail.get("head") or {}).get("status") == "done":
            return
        if not messagebox.askyesno(
                "全部按账面", "把所有实盘数改回账面数吗？（差异会清零）",
                parent=self):
            return
        for r in self.detail.get("rows") or []:
            if int(r.get("real_qty") or 0) != int(r.get("book_qty") or 0):
                self.app.store.set_stocktake_qty(r["id"], int(r.get("book_qty") or 0))
        self.refresh_rows()

    def commit(self):
        ndiff = sum(1 for r in self.detail.get("rows") or []
                    if int(r.get("real_qty") or 0) != int(r.get("book_qty") or 0))
        if ndiff == 0:
            messagebox.showinfo("提交盘点",
                                "所有记录的实盘数都等于账面数，没有需要调整的。",
                                parent=self)
            return
        if not messagebox.askyesno(
                "提交盘点",
                "确认把 %d 条差异写回库存吗？\n\n"
                "提交后这张盘点单不能修改，库存以实盘数为准。" % ndiff,
                parent=self):
            return
        ok, msg = self.app.store.commit_stocktake(self.st_id)
        if not ok:
            messagebox.showwarning("提交盘点", msg, parent=self)
            return
        self.changed = True
        self.refresh_rows()
        self.app.load_data()
        self.app._status(msg)
        messagebox.showinfo("盘点完成", msg, parent=self)

    def _close(self):
        self.destroy()


class StocktakeTab(ttk.Frame):
    """盘点单列表页。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.rows = []
        self._by_id = {}
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x")
        tk.Label(bar, text="盘点单", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left",
                                                   padx=(16, 10), pady=12)
        self.lbl_wh = tk.Label(bar, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                               font=(self.fam, 9))
        self.lbl_wh.pack(side="left", pady=12)
        tk.Label(bar, text="先拍快照再填实盘，提交时按实盘数改库存并记盘盈盘亏",
                 bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(10, 0), pady=12)
        ttk.Button(bar, text="+ 新建盘点单", style="Accent.TButton",
                   command=self.new_stocktake).pack(side="right",
                                                    padx=(8, 16), pady=8)
        ttk.Button(bar, text="刷新", command=self.refresh_tab).pack(
            side="right", pady=8)

        wrap = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=10)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in LIST_COLS],
                                 show="headings", selectmode="browse")
        vs = ttk.Scrollbar(wrap, orient="vertical",
                           style="Vertical.TScrollbar", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w, anchor in LIST_COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=int(w * self.app.ui_scale),
                             anchor=anchor, stretch=(key == "name"))
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("diff", foreground=CLR_WARN)
        self.tree.tag_configure("done", foreground=CLR_MUTED)
        self.tree.bind("<Double-1>", lambda e: self.open_selected())

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 10))
        self.lbl_hint = tk.Label(foot, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=(self.fam, 9))
        self.lbl_hint.pack(side="left")
        ttk.Button(foot, text="删除草稿", style="Danger.TButton",
                   command=self.delete_selected).pack(side="right")
        ttk.Button(foot, text="打开盘点单", style="Accent.TButton",
                   command=self.open_selected).pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------ 数据
    def refresh_tab(self):
        try:
            self.lbl_wh.configure(text="当前仓库：%s" % self.app.cur_wh()["name"])
        except Exception:
            pass
        self.refresh_rows()

    def refresh_rows(self):
        try:
            self.rows = self.app.store.list_stocktakes()
        except Exception as e:
            self.rows = []
            self.lbl_hint.configure(text="读取盘点单失败：%s" % e)
            return
        self.tree.delete(*self.tree.get_children())
        self._by_id = {}
        for r in self.rows:
            iid = str(r["id"])
            self._by_id[iid] = r
            tags = []
            if r["status"] == "done":
                tags.append("done")
            elif r["diff"]:
                tags.append("diff")
            self.tree.insert("", "end", iid=iid, tags=tuple(tags), values=(
                r["no"], r["name"], STATUS_TEXT.get(r["status"], r["status"]),
                str(r["count"]), str(r["diff"]),
                "%+d" % r["diff_qty"] if r["diff_qty"] else "0",
                r["created_at"], r["done_at"]))
        draft = sum(1 for r in self.rows if r["status"] == "draft")
        self.lbl_hint.configure(
            text="共 %d 张盘点单（%d 张进行中）· 双击打开填写实盘数"
                 % (len(self.rows), draft))

    # ------------------------------------------------------------ 操作
    def new_stocktake(self):
        if self._guard():
            return
        dlg = NewStocktakeDialog(self.app.root, self.app, self.fam)
        self.app.root.wait_window(dlg)
        if not dlg.result:
            return
        st_id, msg = dlg.result
        self.refresh_rows()
        self.app._status(msg)
        self._open_dialog(st_id)

    def open_selected(self):
        sel = self.tree.selection()
        if not sel:
            self.lbl_hint.configure(text="请先选中一张盘点单")
            return
        self._open_dialog(int(sel[0]))

    def _open_dialog(self, st_id):
        dlg = StocktakeDialog(self.app.root, self.app, st_id, self.fam)
        self.app.root.wait_window(dlg)
        self.refresh_rows()

    def delete_selected(self):
        if self._guard():
            return
        sel = self.tree.selection()
        if not sel:
            return
        rec = self._by_id.get(str(sel[0]))
        if rec is None:
            return
        if rec["status"] == "done":
            messagebox.showinfo("删除盘点单",
                                "已提交的盘点单不能删除（库存已经按它改过了）。",
                                parent=self.app.root)
            return
        if not messagebox.askyesno("删除盘点单",
                                   "确定删除草稿「%s」吗？" % rec["name"],
                                   parent=self.app.root):
            return
        n = self.app.store.delete_stocktake(rec["id"])
        self.refresh_rows()
        self.app._status("已删除盘点单" if n == 1 else "删除失败")

    def _guard(self):
        try:
            return bool(self.app._guard_write())
        except Exception:
            return False
