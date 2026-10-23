# -*- coding: utf-8 -*-
"""扩展功能对话框：回收站 / 批量修改字段 / 采购入库 / 采购记录 / 买家管理。

这些对话框都以 App 为上下文（读取 app.store、app.records），
统一使用 constants 里的配色与居中、图标工具，保证与主界面风格一致。
"""

import os
import re
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_DANGER,
                        CLR_MUTED, CLR_OK, CLR_TEXT, CLR_WARN, FIELD_KEYS,
                        FIELD_LABEL, FIELD_TYPE, FIELD_WIDTH,
                        apply_window_icon, center_window)
from .theme import dot_check


def today():
    return datetime.now().strftime("%Y-%m-%d")


def money(v):
    return "{:,.2f}".format(float(v or 0))


def _entry(parent, var, width=16, fam="Microsoft YaHei UI"):
    return tk.Entry(parent, textvariable=var, width=width, font=(fam, 10),
                    relief="flat", highlightbackground=CLR_BORDER, highlightthickness=1)


def _card(master, pad=(0, 0)):
    f = tk.Frame(master, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                 highlightthickness=1)
    f.pack(fill="x", padx=pad[0], pady=pad[1])
    return f


def _shell(master, title, subtitle, size=None, fam="Microsoft YaHei UI"):
    """统一的弹窗外壳：图标 + 头部卡片 + 居中。返回 (win, body)。"""
    win = tk.Toplevel(master)
    win.title(title)
    win.configure(bg=CLR_BG)
    win.transient(master)
    apply_window_icon(win)
    head = tk.Frame(win, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                    highlightthickness=1)
    head.pack(fill="x")
    tk.Label(head, text=title, bg=CLR_CARD, fg=CLR_TEXT,
             font=(fam, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
    tk.Label(head, text=subtitle, bg=CLR_CARD, fg=CLR_MUTED,
             font=(fam, 9)).pack(anchor="w", padx=16, pady=(2, 10))
    body = tk.Frame(win, bg=CLR_BG)
    body.pack(fill="both", expand=True)
    win.bind("<Escape>", lambda e: win.destroy())
    return win, body


# ==========================================================================
# 回收站
# ==========================================================================
RECYCLE_COLS = (("deleted_at", "删除时间", 150), ("code", "编号", 110),
                ("brand", "品牌", 120), ("category", "品类", 90),
                ("model", "型号", 150), ("qty", "数量", 60),
                ("price", "价格", 80), ("shelf", "货架", 120))


class RecycleBinDialog(object):
    """删除回收站：查看 / 恢复 / 彻底删除。"""

    def __init__(self, app, fam="Microsoft YaHei UI"):
        self.app = app
        self.fam = fam
        self.rows = []
        self.win, body = _shell(app.root, "回收站",
                                "被删除的记录会先进这里，可随时恢复；彻底删除后无法找回。",
                                fam=fam)

        bar = tk.Frame(body, bg=CLR_BG)
        bar.pack(fill="x", padx=14, pady=(10, 0))
        self.lbl_info = tk.Label(bar, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=(fam, 9))
        self.lbl_info.pack(side="left")

        wrap = tk.Frame(body, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=14, pady=10)
        cols = [c[0] for c in RECYCLE_COLS]
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="extended")
        vs = ttk.Scrollbar(wrap, orient="vertical", style="Vertical.TScrollbar",
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w in RECYCLE_COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, minwidth=60,
                             anchor="center" if key != "model" else "w",
                             stretch=(key in ("model", "brand")))
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("odd", background="#F7FAFD")
        self.tree.bind("<Double-1>", lambda e: self.restore())

        foot = tk.Frame(body, bg=CLR_BG)
        foot.pack(fill="x", padx=14, pady=(0, 12))
        ttk.Button(foot, text="关闭", width=10,
                   command=self.win.destroy).pack(side="right")
        ttk.Button(foot, text="清空回收站", style="Danger.TButton",
                   command=self.purge_all).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="彻底删除选中", style="Danger.TButton",
                   command=self.purge).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="恢复选中", style="Accent.TButton",
                   command=self.restore).pack(side="right")
        tk.Label(foot, text="双击一行可直接恢复", bg=CLR_BG, fg=CLR_MUTED,
                 font=(fam, 9)).pack(side="left")

        center_window(self.win, app.root, size=(880, 520))
        self.refresh()

    def refresh(self):
        st = self.app.store
        self.rows = st.list_deleted()
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rows):
            vals = []
            for key, _t, _w in RECYCLE_COLS:
                if key == "qty":
                    vals.append(str(int(r.get("qty") or 0)))
                elif key == "price":
                    vals.append("%.2f" % float(r.get("price") or 0))
                else:
                    vals.append(str(r.get(key) or ""))
            self.tree.insert("", "end", iid=str(r["id"]), values=vals,
                             tags=("odd",) if i % 2 else ())
        self.lbl_info.configure(
            text="回收站中共 %d 条记录（恢复后回到库存列表，编号保持不变）" % len(self.rows))

    def _sel(self):
        return [int(i) for i in self.tree.selection()]

    def restore(self):
        ids = self._sel()
        if not ids:
            messagebox.showinfo("回收站", "请先选择要恢复的记录。", parent=self.win)
            return
        n = self.app.store.restore_ids(ids)
        self.refresh()
        self.app.load_data()
        self.app._status("已从回收站恢复 %d 条记录" % n)

    def purge(self):
        ids = self._sel()
        if not ids:
            messagebox.showinfo("回收站", "请先选择要彻底删除的记录。", parent=self.win)
            return
        if not messagebox.askyesno(
                "彻底删除", "将永久删除选中的 %d 条记录，无法恢复。\n\n确定继续吗？" % len(ids),
                parent=self.win, icon="warning"):
            return
        n = self.app.store.purge_ids(ids)
        self.refresh()
        self.app._status("已彻底删除 %d 条记录" % n)

    def purge_all(self):
        cnt = self.app.store.deleted_count()
        if cnt == 0:
            messagebox.showinfo("回收站", "回收站已经是空的。", parent=self.win)
            return
        if not messagebox.askyesno(
                "清空回收站", "将永久删除回收站里的全部 %d 条记录，无法恢复。\n\n确定继续吗？"
                % cnt, parent=self.win, icon="warning"):
            return
        n = self.app.store.purge_all_deleted()
        self.refresh()
        self.app._status("已清空回收站（%d 条）" % n)


# ==========================================================================
# 批量修改字段
# ==========================================================================
class BatchEditDialog(object):
    """选中多行后，一次统一修改若干字段（勾选要改的字段并填新值）。"""

    # 可批量修改的字段（编号除外）
    FIELDS = [k for k in FIELD_KEYS if k != "code"]

    def __init__(self, app, fam="Microsoft YaHei UI"):
        self.app = app
        self.fam = fam
        self.result = None
        self.n = len(app._selected_records())
        self.win, body = _shell(
            app.root, "批量修改字段",
            "已选中 %d 条记录：勾选要修改的字段并填写新值，未勾选的字段保持原样。" % self.n,
            fam=fam)
        self.win.resizable(False, False)

        sug = app.suggestions()
        card = _card(body, pad=(14, 10))
        grid = tk.Frame(card, bg=CLR_CARD)
        grid.pack(fill="x", padx=16, pady=12)
        grid.columnconfigure(1, weight=1)

        self.use = {}
        self.vars = {}
        self.widgets = {}
        r = 0
        for k in self.FIELDS:
            uv = tk.BooleanVar(value=False)
            self.use[k] = uv
            dot_check(grid, FIELD_LABEL[k], uv,
                      command=lambda kk=k: self._toggle(kk),
                      bg=CLR_CARD, fam=fam, size=9).grid(
                row=r, column=0, sticky="w", pady=3)
            t = FIELD_TYPE[k]
            v = tk.StringVar()
            self.vars[k] = v
            if t == "bool":
                w = ttk.Combobox(grid, textvariable=v, values=["已上架", "未上架"],
                                 state="disabled", width=14, font=(fam, 9))
            elif t == "money":
                w = _entry(grid, v, 16, fam)
            elif t == "int":
                w = _entry(grid, v, 16, fam)
            else:
                opts = sug.get(k) or []
                w = ttk.Combobox(grid, textvariable=v, values=opts,
                                 state="disabled", width=24, font=(fam, 9))
            w.grid(row=r, column=1, sticky="w", padx=(10, 0), ipady=2)
            self.widgets[k] = w
            r += 1

        self.lbl_msg = tk.Label(body, text="", bg=CLR_BG, fg=CLR_DANGER,
                                font=(fam, 9), anchor="w", justify="left")
        self.lbl_msg.pack(fill="x", padx=16)

        foot = tk.Frame(body, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=12)
        ttk.Button(foot, text="应用到 %d 条记录" % self.n, style="Accent.TButton",
                   command=self._ok).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="取消", width=10,
                   command=self.win.destroy).pack(side="right")
        tk.Frame(foot, bg=CLR_BG, height=1).pack()

        center_window(self.win, app.root)
        self.win.grab_set()

    def _toggle(self, key):
        w = self.widgets[key]
        on = self.use[key].get()
        if isinstance(w, ttk.Combobox):
            w.configure(state="normal" if (on and FIELD_TYPE[key] == "text")
                         else ("readonly" if on else "disabled"))
        else:
            w.configure(state="normal" if on else "disabled")

    def _ok(self):
        out = {}
        for k in self.FIELDS:
            if not self.use[k].get():
                continue
            raw = (self.vars[k].get() or "").strip()
            t = FIELD_TYPE[k]
            if t == "bool":
                if raw not in ("已上架", "未上架"):
                    return self._warn("「%s」请选择 已上架 / 未上架" % FIELD_LABEL[k])
                out[k] = 1 if raw == "已上架" else 0
            elif t == "money":
                try:
                    out[k] = float(raw or 0)
                except ValueError:
                    return self._warn("「%s」请填写数字" % FIELD_LABEL[k])
            elif t == "int":
                try:
                    out[k] = int(round(float(raw or 0)))
                except ValueError:
                    return self._warn("「%s」请填写整数" % FIELD_LABEL[k])
            else:
                if k == "code":
                    continue
                out[k] = raw
        if not out:
            return self._warn("请至少勾选一个要修改的字段")
        self.result = out
        self.win.destroy()

    def _warn(self, msg):
        self.lbl_msg.configure(text="⚠ " + msg)


# ==========================================================================
# 采购入库
# ==========================================================================
class PurchaseDialog(tk.Toplevel):
    """登记一笔采购入库：增加库存、更新成本单价。result = dict 或 None。"""

    def __init__(self, master, record, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.result = None
        self.fam = fam
        self.record = dict(record or {})
        self.stock = int(self.record.get("qty") or 0)
        self.old_cost = float(self.record.get("cost") or 0)
        self.title("采购入库")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)
        self._build()
        center_window(self, master)
        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Return>", lambda e: self._ok())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.ent_qty.focus_set()
        self.ent_qty.selection_range(0, "end")

    def _build(self):
        rec = self.record
        head = _card(self, pad=(12, (12, 8)))
        tk.Label(head, text="采购入库", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        name = " · ".join([x for x in (rec.get("code"), rec.get("brand"),
                                       rec.get("model")) if x]) or "（无编号记录）"
        tk.Label(head, text=name, bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 10)).pack(anchor="w", padx=16, pady=(2, 0))
        tk.Label(head, text="当前库存 %d 件 · 当前成本单价 %.2f 元"
                           % (self.stock, self.old_cost),
                 bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9)).pack(
            anchor="w", padx=16, pady=(2, 12))

        body = _card(self, pad=(12, 0))
        grid = tk.Frame(body, bg=CLR_CARD)
        grid.pack(fill="x", padx=16, pady=12)

        self.var_qty = tk.StringVar(value="1")
        self.var_cost = tk.StringVar(value="%.2f" % self.old_cost)
        self.var_date = tk.StringVar(value=today())
        self.var_supplier = tk.StringVar()
        self.var_remark = tk.StringVar()

        rows = (("采购数量", self.var_qty, 10, "件"),
                ("采购单价", self.var_cost, 10, "元/件（进货成本）"),
                ("采购日期", self.var_date, 14, "格式 2026-10-07"),
                ("供应商", self.var_supplier, 22, "选填"),
                ("备注", self.var_remark, 22, "选填"))
        for i, (label, var, w, hint) in enumerate(rows):
            tk.Label(grid, text=label, bg=CLR_CARD, fg=CLR_TEXT,
                     font=(self.fam, 10), width=9, anchor="w").grid(
                row=i, column=0, sticky="w", pady=4)
            e = _entry(grid, var, w, self.fam)
            e.grid(row=i, column=1, sticky="w", ipady=3)
            e.bind("<KeyRelease>", lambda ev: self._refresh())
            tk.Label(grid, text=hint, bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.fam, 8)).grid(row=i, column=2, sticky="w", padx=(8, 0))
            if label == "采购数量":
                self.ent_qty = e

        self.lbl_total = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_ACCENT,
                                  font=(self.fam, 11, "bold"))
        self.lbl_total.pack(anchor="w", padx=16, pady=(0, 4))
        self.lbl_msg = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_DANGER,
                                font=(self.fam, 9), anchor="w", justify="left")
        self.lbl_msg.pack(fill="x", padx=16, pady=(0, 10))

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=12)
        ttk.Button(foot, text="确认入库", style="Accent.TButton", width=12,
                   command=self._ok).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="取消", width=10, command=self._cancel).pack(side="right")
        self._refresh()

    def _read(self):
        try:
            qty = int(round(float(self.var_qty.get().strip() or 0)))
        except (TypeError, ValueError):
            qty = None
        try:
            cost = float(self.var_cost.get().strip() or 0)
        except (TypeError, ValueError):
            cost = None
        return qty, cost

    def _refresh(self):
        qty, cost = self._read()
        if qty is None or cost is None:
            self.lbl_total.configure(text="合计：请填写正确的数量与单价", fg=CLR_DANGER)
            return
        old_q = max(0, self.stock)
        new_q = old_q + qty
        new_avg = ((old_q * self.old_cost + qty * cost) / new_q) if new_q > 0 else cost
        self.lbl_total.configure(
            text="合计金额：%.2f 元   →   库存 %d → %d 件，成本单价 %.2f → %.2f 元"
                 % (qty * cost, self.stock, new_q, self.old_cost, new_avg),
            fg=CLR_ACCENT)

    def _warn(self, msg):
        self.lbl_msg.configure(text="⚠ " + msg)

    def _ok(self):
        qty, cost = self._read()
        if qty is None:
            return self._warn("采购数量请填写数字")
        if qty <= 0:
            return self._warn("采购数量必须大于 0")
        if cost is None or cost < 0:
            return self._warn("采购单价请填写不小于 0 的数字")
        date = (self.var_date.get() or "").strip()
        if not re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", date):
            return self._warn("采购日期格式应为 2026-10-07 这样")
        y, m, d = [int(x) for x in date.split("-")]
        self.result = {"qty": qty, "unit_cost": cost,
                       "purchase_date": "%04d-%02d-%02d" % (y, m, d),
                       "supplier": (self.var_supplier.get() or "").strip(),
                       "remark": (self.var_remark.get() or "").strip()}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_purchase(master, record, fam="Microsoft YaHei UI"):
    dlg = PurchaseDialog(master, record, fam)
    master.wait_window(dlg)
    return dlg.result


# ==========================================================================
# 采购记录
# ==========================================================================
PURCH_COLS = (("purchase_date", "采购日期", 100), ("code", "编号", 110),
              ("brand", "品牌", 120), ("model", "型号", 150),
              ("qty", "数量", 60), ("unit_cost", "进价", 85),
              ("total", "金额", 95), ("supplier", "供应商", 110),
              ("remark", "备注", 150))


class PurchaseListDialog(object):
    """采购记录：筛选 + 合计 + 撤销 + 导出。"""

    def __init__(self, app, fam="Microsoft YaHei UI"):
        self.app = app
        self.fam = fam
        self.rows = []
        self.win, body = _shell(app.root, "采购记录",
                                "采购入库会同步增加库存数量并更新成本单价（移动加权平均）。",
                                fam=fam)

        flt = tk.Frame(body, bg=CLR_BG)
        flt.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(flt, text="日期", bg=CLR_BG, fg=CLR_MUTED,
                 font=(fam, 9)).pack(side="left")
        self.var_start = tk.StringVar()
        self.var_end = tk.StringVar()
        for var, ph in ((self.var_start, "起"), (self.var_end, "止")):
            e = _entry(flt, var, 11, fam)
            e.pack(side="left", padx=(4, 2), ipady=2)
            e.bind("<KeyRelease>", lambda ev: self.refresh())
            tk.Label(flt, text=ph, bg=CLR_BG, fg=CLR_MUTED,
                     font=(fam, 8)).pack(side="left", padx=(0, 6))
        tk.Label(flt, text="搜索", bg=CLR_BG, fg=CLR_MUTED,
                 font=(fam, 9)).pack(side="left", padx=(10, 4))
        self.var_kw = tk.StringVar()
        e = _entry(flt, self.var_kw, 18, fam)
        e.pack(side="left", ipady=2)
        e.bind("<KeyRelease>", lambda ev: self.refresh())

        self.lbl_sum = tk.Label(body, text="", bg=CLR_BG, fg=CLR_TEXT,
                                font=(fam, 10, "bold"))
        self.lbl_sum.pack(anchor="w", padx=14, pady=(8, 0))

        wrap = tk.Frame(body, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=14, pady=10)
        cols = [c[0] for c in PURCH_COLS]
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="extended")
        vs = ttk.Scrollbar(wrap, orient="vertical", style="Vertical.TScrollbar",
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w in PURCH_COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, minwidth=60,
                             anchor="center" if key != "model" else "w",
                             stretch=(key in ("model", "supplier", "remark")))
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("odd", background="#F7FAFD")

        foot = tk.Frame(body, bg=CLR_BG)
        foot.pack(fill="x", padx=14, pady=(0, 12))
        ttk.Button(foot, text="关闭", width=10,
                   command=self.win.destroy).pack(side="right")
        ttk.Button(foot, text="导出 XLSX", command=self.export).pack(side="right",
                                                                     padx=(8, 0))
        ttk.Button(foot, text="撤销选中采购", style="Danger.TButton",
                   command=self.undo).pack(side="right", padx=(8, 0))
        tk.Label(foot, text="撤销会把采购数量从库存中扣回并重算成本单价",
                 bg=CLR_BG, fg=CLR_MUTED, font=(fam, 9)).pack(side="left")

        center_window(self.win, app.root, size=(920, 560))
        self.refresh()

    def refresh(self):
        st = self.app.store
        self.rows = st.list_purchases(self.var_start.get().strip(),
                                      self.var_end.get().strip(),
                                      self.var_kw.get())
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rows):
            vals = []
            for key, _t, _w in PURCH_COLS:
                if key == "qty":
                    vals.append(str(int(r.get("qty") or 0)))
                elif key in ("unit_cost", "total"):
                    vals.append("%.2f" % float(r.get(key) or 0))
                else:
                    vals.append(str(r.get(key) or ""))
            self.tree.insert("", "end", iid=str(r["id"]), values=vals,
                             tags=("odd",) if i % 2 else ())
        t = st.purchase_totals(self.rows)
        self.lbl_sum.configure(
            text="共 %d 笔采购 · %d 件 · 采购金额 ¥%s · 平均进价 ¥%s"
                 % (t["count"], t["qty"], money(t["amount"]), money(t["avg"])))

    def undo(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("采购记录", "请先选择要撤销的采购记录。", parent=self.win)
            return
        if not messagebox.askyesno(
                "撤销采购",
                "撤销选中的 %d 笔采购？\n\n库存数量会相应扣回，成本单价会重新计算。"
                % len(sel), parent=self.win, icon="warning"):
            return
        n = 0
        for iid in sel:
            ok, _ = self.app.store.delete_purchase(int(iid))
            n += 1 if ok else 0
        self.refresh()
        self.app.load_data()
        self.app._status("已撤销 %d 笔采购" % n)

    def export(self):
        if not self.rows:
            messagebox.showinfo("采购记录", "当前范围内没有采购记录。", parent=self.win)
            return
        from .xlsxio import export_purchases_xlsx
        try:
            wh = self.app.cur_wh()["name"]
        except Exception:
            wh = ""
        path = filedialog.asksaveasfilename(
            title="导出采购记录", parent=self.win, defaultextension=".xlsx",
            initialfile="采购记录_%s_%s.xlsx" % (wh, datetime.now().strftime("%Y%m%d")),
            filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            export_purchases_xlsx(path, self.rows, wh)
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self.win)
            return
        if messagebox.askyesno("导出完成", "已导出 %d 笔采购记录到：\n%s\n\n是否打开所在文件夹？"
                                           % (len(self.rows), path), parent=self.win):
            try:
                os.startfile(os.path.dirname(path))
            except Exception:
                pass


# ==========================================================================
# 买家管理
# ==========================================================================
BUYER_COLS = (("buyer", "买家/客户", 160), ("count", "购买笔数", 90),
              ("qty", "购买件数", 90), ("amount", "消费金额(元)", 120),
              ("profit", "贡献利润(元)", 120), ("last", "最近购买", 110))


class BuyerDialog(object):
    """买家管理：查看消费统计、重命名（改名到已有买家即合并）。"""

    def __init__(self, app, fam="Microsoft YaHei UI"):
        self.app = app
        self.fam = fam
        self.rows = []
        self.win, body = _shell(app.root, "买家管理",
                                "按买家汇总消费情况；重命名到已有买家名称即可合并两个买家。",
                                fam=fam)

        self.lbl_sum = tk.Label(body, text="", bg=CLR_BG, fg=CLR_TEXT,
                                font=(fam, 10, "bold"))
        self.lbl_sum.pack(anchor="w", padx=14, pady=(12, 0))

        wrap = tk.Frame(body, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=14, pady=10)
        cols = [c[0] for c in BUYER_COLS]
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="browse")
        vs = ttk.Scrollbar(wrap, orient="vertical", style="Vertical.TScrollbar",
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w in BUYER_COLS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, minwidth=60,
                             anchor="w" if key == "buyer" else "center",
                             stretch=(key == "buyer"))
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("odd", background="#F7FAFD")
        self.tree.bind("<Double-1>", lambda e: self.rename())

        foot = tk.Frame(body, bg=CLR_BG)
        foot.pack(fill="x", padx=14, pady=(0, 12))
        ttk.Button(foot, text="关闭", width=10,
                   command=self.win.destroy).pack(side="right")
        ttk.Button(foot, text="重命名 / 合并", style="Accent.TButton",
                   command=self.rename).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="清空该买家标记", style="Danger.TButton",
                   command=self.clear).pack(side="right", padx=(8, 0))
        tk.Label(foot, text="双击一行可直接重命名", bg=CLR_BG, fg=CLR_MUTED,
                 font=(fam, 9)).pack(side="left")

        center_window(self.win, app.root, size=(820, 500))
        self.refresh()

    def refresh(self):
        self.rows = self.app.store.buyer_stats()
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rows):
            self.tree.insert("", "end", iid=r["buyer"], values=(
                r["buyer"], r["count"], r["qty"], money(r["amount"]),
                money(r["profit"]), r["last"]), tags=("odd",) if i % 2 else ())
        amt = sum(r["amount"] for r in self.rows)
        self.lbl_sum.configure(
            text="共 %d 位买家 · 累计消费 ¥%s · 累计利润 ¥%s"
                 % (len(self.rows), money(amt), money(sum(r["profit"] for r in self.rows))))

    def _sel_name(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def rename(self):
        old = self._sel_name()
        if not old:
            messagebox.showinfo("买家管理", "请先选择一位买家。", parent=self.win)
            return
        dlg = _NameDialog(self.win, "重命名买家", "把「%s」改为（输入已有买家名即合并）：" % old,
                          old, self.fam, self.app.store.buyer_names())
        self.win.wait_window(dlg)
        if not dlg.result:
            return
        n = self.app.store.rename_buyer(old, dlg.result)
        self.refresh()
        self.app._on_sale_changed()
        self.app._status("已重命名买家「%s」→「%s」（%d 笔）" % (old, dlg.result, n))

    def clear(self):
        name = self._sel_name()
        if not name:
            messagebox.showinfo("买家管理", "请先选择一位买家。", parent=self.win)
            return
        if not messagebox.askyesno(
                "清空买家标记",
                "把「%s」名下所有出售记录的买家字段清空？\n\n（出售记录本身保留）" % name,
                parent=self.win, icon="warning"):
            return
        n = self.app.store.clear_buyer(name)
        self.refresh()
        self.app._on_sale_changed()
        self.app._status("已清空买家「%s」标记（%d 笔）" % (name, n))


class _NameDialog(tk.Toplevel):
    """通用「输入一个新名称」小对话框（带历史值下拉）。"""

    def __init__(self, master, title, prompt, initial="", fam="Microsoft YaHei UI",
                 values=None):
        super().__init__(master)
        self.result = None
        self.fam = fam
        self.title(title)
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)
        tk.Label(self, text=prompt, bg=CLR_BG, fg=CLR_TEXT,
                 font=(fam, 10), wraplength=360, justify="left").pack(
            anchor="w", padx=16, pady=(14, 6))
        self.var = tk.StringVar(value=initial or "")
        cb = ttk.Combobox(self, textvariable=self.var, values=list(values or []),
                          width=28, font=(fam, 10))
        cb.pack(fill="x", padx=16)
        cb.focus_set()
        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=14)
        ttk.Button(foot, text="确定", style="Accent.TButton", width=10,
                   command=self._ok).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="取消", width=10, command=self.destroy).pack(side="right")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        center_window(self, master)
        self.grab_set()

    def _ok(self):
        v = (self.var.get() or "").strip()
        if not v:
            return
        self.result = v
        self.destroy()


def ask_name(master, title, prompt, initial="", fam="Microsoft YaHei UI", values=None):
    dlg = _NameDialog(master, title, prompt, initial, fam, values)
    master.wait_window(dlg)
    return dlg.result
