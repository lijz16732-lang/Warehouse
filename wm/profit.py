# -*- coding: utf-8 -*-
"""销售利润表（v1.32.0）：按笔/按维度看销售额、成本、毛利与毛利率。

口径（与退货一致）：
    实收   = 销售额 - 退款
    净成本 = 成本 - 退回部分成本
    毛利   = 实收 - 净成本
所以退过货的订单利润会同步下降，报表不会虚高。
"""

import csv
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_DANGER,
                        CLR_MUTED, CLR_OK, CLR_TEXT, CLR_WARN)
from .sales import money, today

GROUPS = [("sale", "逐笔明细"), ("brand", "按品牌"), ("category", "按品类"),
          ("model", "按型号"), ("month", "按月份")]
GROUP_LABEL = dict(GROUPS)

DETAIL_COLS = [("date", "出售日期", 92, "center"), ("code", "编号", 110, "w"),
               ("brand", "品牌", 90, "center"), ("category", "品类", 84, "center"),
               ("model", "型号", 130, "w"), ("buyer", "客户", 90, "w"),
               ("qty", "数量", 56, "center"), ("rq", "退货", 56, "center"),
               ("amount", "实收(元)", 96, "e"), ("refund", "退款(元)", 88, "e"),
               ("cost", "成本(元)", 92, "e"), ("profit", "毛利(元)", 96, "e"),
               ("margin", "毛利率", 74, "e")]

SUM_COLS = [("key", "维度", 190, "w"), ("count", "笔数", 70, "center"),
            ("qty", "销量", 70, "center"), ("amount", "实收(元)", 104, "e"),
            ("refund", "退款(元)", 92, "e"), ("cost", "成本(元)", 100, "e"),
            ("profit", "毛利(元)", 104, "e"), ("margin", "毛利率", 80, "e")]


def aggregate(rows, key):
    """按维度汇总（key 为 brand/category/model/month）。"""
    acc = {}
    for r in rows:
        k = (r.get("date") or "")[:7] if key == "month" else (r.get(key) or "")
        k = k or "（空）"
        a = acc.setdefault(k, {"key": k, "count": 0, "qty": 0, "amount": 0.0,
                               "refund": 0.0, "cost": 0.0, "profit": 0.0})
        a["count"] += 1
        a["qty"] += int(r.get("qty") or 0)
        a["amount"] += float(r.get("amount") or 0)
        a["refund"] += float(r.get("refund") or 0)
        a["cost"] += float(r.get("cost") or 0)
        a["profit"] += float(r.get("profit") or 0)
    out = []
    for a in acc.values():
        a["amount"] = round(a["amount"], 2)
        a["refund"] = round(a["refund"], 2)
        a["cost"] = round(a["cost"], 2)
        a["profit"] = round(a["profit"], 2)
        a["margin"] = round(a["profit"] / a["amount"] * 100, 2) if a["amount"] else 0.0
        out.append(a)
    if key == "month":
        out.sort(key=lambda x: x["key"])
    else:
        out.sort(key=lambda x: -x["profit"])
    return out


class ProfitTab(ttk.Frame):
    """销售利润报表页。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.rows = []
        self.view = []            # 当前表格展示的行
        self._job = None
        self.var_group = tk.StringVar(value="brand")
        self._build()

    # ------------------------------------------------------------ UI
    def _build(self):
        bar = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x")
        tk.Label(bar, text="销售利润表", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left",
                                                   padx=(16, 10), pady=12)
        self.lbl_wh = tk.Label(bar, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                               font=(self.fam, 9))
        self.lbl_wh.pack(side="left", pady=12)
        tk.Label(bar, text="实收扣退款、成本扣退回部分，退货不会虚增利润",
                 bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(10, 0), pady=12)
        ttk.Button(bar, text="导出报表", style="Accent.TButton",
                   command=self.export).pack(side="right",
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
        tk.Label(flt, text="品牌", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(8, 4))
        self.var_brand = tk.StringVar(value="全部")
        self.cb_brand = ttk.Combobox(flt, textvariable=self.var_brand,
                                     values=["全部"], width=14,
                                     font=(self.fam, 9))
        self.cb_brand.pack(side="left")
        self.cb_brand.bind("<<ComboboxSelected>>", lambda e: self.refresh_rows())
        tk.Label(flt, text="搜索", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(8, 4))
        self.var_kw = tk.StringVar()
        e = tk.Entry(flt, textvariable=self.var_kw, width=16,
                     font=(self.fam, 10), relief="solid", bd=1)
        e.pack(side="left", ipady=2)
        e.bind("<KeyRelease>", lambda ev: self._debounce())
        for text, cb in (("本月", self._this_month), ("今年", self._this_year)):
            ttk.Button(flt, text=text, style="Ghost.TButton", width=6,
                       command=cb).pack(side="left", padx=(8, 4))
        ttk.Button(flt, text="重置", style="Ghost.TButton", width=6,
                   command=self.reset_filters).pack(side="left")

        # 维度切换 + KPI
        cards = tk.Frame(self, bg=CLR_BG)
        cards.pack(fill="x", padx=16, pady=(10, 0))
        self.kpi = {}
        for key, title in (("amount", "实收合计(元)"), ("cost", "净成本(元)"),
                           ("profit", "毛利(元)"), ("margin", "毛利率"),
                           ("refund", "退款(元)")):
            card = tk.Frame(cards, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                            highlightthickness=1)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(card, text=title, bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.fam, 9)).pack(anchor="w", padx=12, pady=(8, 0))
            lbl = tk.Label(card, text="0", bg=CLR_CARD, fg=CLR_TEXT,
                           font=(self.fam, 13, "bold"))
            lbl.pack(anchor="w", padx=12, pady=(0, 8))
            self.kpi[key] = lbl

        gbar = tk.Frame(self, bg=CLR_BG)
        gbar.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(gbar, text="查看方式", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(0, 8))
        for val, label in GROUPS:
            ttk.Radiobutton(gbar, text=label, value=val,
                            variable=self.var_group, style="Card.TRadiobutton",
                            command=self.refresh_rows,
                            takefocus=False).pack(side="left", padx=(0, 10))

        wrap = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=10)
        self.wrap = wrap
        self.tree = ttk.Treeview(wrap, show="headings", selectmode="extended")
        vs = ttk.Scrollbar(wrap, orient="vertical",
                           style="Vertical.TScrollbar", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("loss", foreground=CLR_DANGER)
        self.tree.tag_configure("odd", background="#F7FAFD")

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 10))
        self.lbl_hint = tk.Label(foot, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=(self.fam, 9))
        self.lbl_hint.pack(side="left")

    # ------------------------------------------------------------ 数据
    def refresh_tab(self):
        try:
            self.lbl_wh.configure(text="当前仓库：%s" % self.app.cur_wh()["name"])
        except Exception:
            pass
        self.cb_brand.configure(values=["全部"] + self.app.store.sales_brands())
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

    def _this_year(self):
        d = today()
        self.var_start.set(d[:5] + "01-01")
        self.var_end.set(d)
        self.refresh_rows()

    def reset_filters(self):
        self.var_start.set("")
        self.var_end.set("")
        self.var_brand.set("全部")
        self.var_kw.set("")
        self.refresh_rows()

    def refresh_rows(self):
        try:
            self.rows = self.app.store.profit_rows(
                self.var_start.get().strip(), self.var_end.get().strip(),
                self.var_brand.get(), self.var_kw.get())
        except Exception as e:
            self.rows = []
            self.lbl_hint.configure(text="读取销售数据失败：%s" % e)
            return
        group = self.var_group.get()
        self.view = (self.rows if group == "sale"
                     else aggregate(self.rows, group))
        self._fill_table(group)
        self._fill_kpi()

    def _fill_kpi(self):
        amount = sum(r["amount"] for r in self.rows)
        cost = sum(r["cost"] for r in self.rows)
        profit = sum(r["profit"] for r in self.rows)
        refund = sum(r["refund"] for r in self.rows)
        margin = (profit / amount * 100) if amount else 0.0
        self.kpi["amount"].configure(text=money(amount))
        self.kpi["cost"].configure(text=money(cost))
        self.kpi["profit"].configure(
            text=money(profit), fg=CLR_DANGER if profit < 0 else CLR_OK)
        self.kpi["margin"].configure(
            text="%.1f%%" % margin,
            fg=CLR_DANGER if margin < 0 else (CLR_WARN if margin < 10 else CLR_OK))
        self.kpi["refund"].configure(text=money(refund))
        self.lbl_hint.configure(
            text="共 %d 笔销售 · 毛利 %s 元 · 毛利率 %.1f%%（实收 - 净成本）"
                 % (len(self.rows), money(profit), margin))

    def _fill_table(self, group):
        cols = DETAIL_COLS if group == "sale" else SUM_COLS
        keys = [c[0] for c in cols]
        if list(self.tree["columns"]) != keys:
            self.tree.configure(columns=keys)
            for key, title, w, anchor in cols:
                self.tree.heading(key, text=title)
                self.tree.column(key, width=int(w * self.app.ui_scale),
                                 anchor=anchor,
                                 stretch=(key in ("model", "key")))
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.view):
            tags = []
            if i % 2:
                tags.append("odd")
            if float(r.get("profit") or 0) < 0:
                tags.append("loss")
            if group == "sale":
                values = (r["date"], r["code"], r["brand"], r["category"],
                          r["model"], r["buyer"], str(r["qty"]), str(r["rq"]),
                          "%.2f" % r["amount"], "%.2f" % r["refund"],
                          "%.2f" % r["cost"], "%.2f" % r["profit"],
                          "%.1f%%" % r["margin"])
            else:
                values = (r["key"], str(r["count"]), str(r["qty"]),
                          "%.2f" % r["amount"], "%.2f" % r["refund"],
                          "%.2f" % r["cost"], "%.2f" % r["profit"],
                          "%.1f%%" % r["margin"])
            self.tree.insert("", "end", tags=tuple(tags), values=values)

    # ------------------------------------------------------------ 导出
    def export(self):
        if not self.view:
            messagebox.showinfo("导出报表", "当前条件下没有可导出的数据。",
                                parent=self.app.root)
            return
        group = self.var_group.get()
        cols = DETAIL_COLS if group == "sale" else SUM_COLS
        try:
            wh = self.app.cur_wh()["name"]
        except Exception:
            wh = ""
        scope = "%s_%s" % (self.var_start.get().strip() or "开始",
                           self.var_end.get().strip() or "至今")
        path = filedialog.asksaveasfilename(
            title="导出销售利润表", parent=self.app.root, defaultextension=".csv",
            initialdir=self.app._dialog_dir(),
            initialfile="销售利润_%s_%s_%s.csv"
                        % (GROUP_LABEL.get(group, ""), wh, scope),
            filetypes=[("CSV 表格", "*.csv")])
        if not path:
            return
        self.app._note_dir(path)
        try:
            with open(path, "w", encoding=self.app._csv_enc(), newline="") as f:
                wr = csv.writer(f)
                wr.writerow([c[1] for c in cols])
                for r in self.view:
                    if group == "sale":
                        wr.writerow([r["date"], r["code"], r["brand"],
                                     r["category"], r["model"], r["buyer"],
                                     r["qty"], r["rq"], r["amount"],
                                     r["refund"], r["cost"], r["profit"],
                                     "%.2f%%" % r["margin"]])
                    else:
                        wr.writerow([r["key"], r["count"], r["qty"],
                                     r["amount"], r["refund"], r["cost"],
                                     r["profit"], "%.2f%%" % r["margin"]])
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self.app.root)
            return
        if messagebox.askyesno(
                "导出完成",
                "已导出 %d 行到：\n%s\n\n是否打开所在文件夹？"
                % (len(self.view), path), parent=self.app.root):
            try:
                os.startfile(os.path.dirname(path))
            except Exception:
                pass
