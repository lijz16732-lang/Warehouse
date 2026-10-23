# -*- coding: utf-8 -*-
"""登记出售 / 登记出库弹窗 + 出售记录页 + 出库记录（总览）页。

出库语义：登记后从库存数量里扣减；扣到 0 时记录保留并标记「已售完」。
撤销一笔出库会把数量加回库存。

两个页面口径不同、互不混淆：
· 出售记录页：只看「销售」出库，含销售额 / 成本 / 利润 / 买家 / 趋势 / 销售目标；
· 出库记录页：总览全部出库（销售出库 + 非销售出库，都是减库存），
  统一按「库存减少价值（成本单价 × 数量）」统计，不出现销售口径字段。
报废、损耗、退货、借出、赠送、调拨、其他只扣库存并留痕（淡黄底标出）。
"""

import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .charts import HBarChart, ProgressStat, VBarChart
from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_DANGER,
                        CLR_MUTED, CLR_OK, CLR_TEXT, CLR_WARN, OUT_TYPE_HINT,
                        OUT_TYPE_SALE, OUT_TYPES, apply_window_icon, center_window)
from .theme import RowHover, dot_check

TARGET_KEY = "monthly_target"        # 月度销售目标（存库 meta，随仓库独立）


def today():
    import datetime
    return datetime.date.today().strftime("%Y-%m-%d")


def money(v):
    return "{:,.2f}".format(float(v or 0))


def _entry(parent, var, width=16, fam="Microsoft YaHei UI"):
    e = tk.Entry(parent, textvariable=var, width=width, font=(fam, 10),
                 relief="flat", highlightbackground=CLR_BORDER, highlightthickness=1)
    return e


class SaleDialog(tk.Toplevel):
    """登记出库弹窗。

    mode="sale"：登记出售 —— 填数量、售价、买家，计入销售额（out_type=销售）；
    mode="out" ：登记出库 —— 选类型（报废/损耗/退货/借出/赠送/调拨/其他）、
                 填数量与原因/去向，只扣库存，不涉及任何金额与买家。

    result = {out_type, qty, price, buyer, address, sale_date, remark} 或 None。
    """

    def __init__(self, master, record, fam="Microsoft YaHei UI", buyers=None,
                 mode="sale", addr_map=None):
        super().__init__(master)
        self.result = None
        self.fam = fam
        self.mode = "out" if mode == "out" else "sale"
        self.is_out = self.mode == "out"
        self.record = dict(record or {})
        self.stock = int(self.record.get("qty") or 0)
        self.buyers = list(buyers or [])
        self.addr_map = dict(addr_map or {})          # 买家 → 最近用过的收货地址
        self.addr_pool = list(dict.fromkeys(self.addr_map.values()))  # 历史地址补全
        self.title("登记出库" if self.is_out else "登记出售")
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

    # ------------------------------------------------------------ UI
    def _build(self):
        rec = self.record
        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x", padx=12, pady=(12, 8))
        tk.Label(head, text="登记出库" if self.is_out else "登记出售",
                 bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        name = " · ".join([x for x in (rec.get("code"), rec.get("brand"),
                                       rec.get("model")) if x]) or "（无编号记录）"
        tk.Label(head, text=name, bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 10)).pack(anchor="w", padx=16, pady=(2, 0))
        cost = float(rec.get("cost") or 0)
        tk.Label(head, text="当前库存 %d 件 · 原单价 %.2f 元 · 成本单价 %s · 货架 %s"
                           % (self.stock, float(rec.get("price") or 0),
                              ("%.2f 元" % cost) if cost > 0 else "未登记",
                              rec.get("shelf") or "未填写"),
                 bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9)).pack(
            anchor="w", padx=16, pady=(2, 12))

        body = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        body.pack(fill="x", padx=12)
        grid = tk.Frame(body, bg=CLR_CARD)
        grid.pack(fill="x", padx=16, pady=12)

        self.var_type = tk.StringVar(
            value=(OUT_TYPES[1] if len(OUT_TYPES) > 1 else "其他")
            if self.is_out else OUT_TYPE_SALE)
        self.var_qty = tk.StringVar(value=str(self.stock or 1))
        self.var_price = tk.StringVar(value="%.2f" % float(rec.get("price") or 0))
        self.var_date = tk.StringVar(value=today())
        self.var_buyer = tk.StringVar()
        self.var_addr = tk.StringVar()
        self.var_remark = tk.StringVar()

        if self.is_out:
            rows = (("出库类型", self.var_type, 12,
                     OUT_TYPE_HINT.get(self.var_type.get(), "")),
                    ("出库数量", self.var_qty, 10, "件（最多 %d 件）" % self.stock),
                    ("出库日期", self.var_date, 14, "格式 2026-10-07"),
                    ("原因/去向", self.var_remark, 22, "选填，如 屏幕碎裂 / 退回供货商"))
        else:
            rows = (("出售数量", self.var_qty, 10, "件（最多 %d 件）" % self.stock),
                    ("出售单价", self.var_price, 10, "元/件"),
                    ("出售日期", self.var_date, 14, "格式 2026-10-07"),
                    ("买家/客户", self.var_buyer, 22, "选填，可从历史买家选择"),
                    ("收货地址", self.var_addr, 22, "选填，发货/收货地址，可从历史地址选择"),
                    ("备注", self.var_remark, 22, "选填"))
        self.hints = {}
        for i, (label, var, w, hint) in enumerate(rows):
            tk.Label(grid, text=label, bg=CLR_CARD, fg=CLR_TEXT,
                     font=(self.fam, 10), width=9, anchor="w").grid(
                row=i, column=0, sticky="w", pady=4)
            if label == "出库类型":
                e = ttk.Combobox(grid, textvariable=var,
                                 values=[t for t in OUT_TYPES if t != OUT_TYPE_SALE],
                                 state="readonly", width=w, font=(self.fam, 10))
                e.bind("<<ComboboxSelected>>", lambda ev: self._apply_type())
            elif label == "买家/客户" and self.buyers:
                e = ttk.Combobox(grid, textvariable=var, values=self.buyers,
                                 width=w + 2, font=(self.fam, 10))
                # 选中历史买家时，如果地址还空着就带出该买家上次的地址
                e.bind("<<ComboboxSelected>>", lambda ev: self._fill_addr())
            elif label == "收货地址" and self.addr_pool:
                e = ttk.Combobox(grid, textvariable=var, values=self.addr_pool,
                                 width=w + 2, font=(self.fam, 10))
            else:
                e = _entry(grid, var, w, self.fam)
            e.grid(row=i, column=1, sticky="w", ipady=3)
            e.bind("<KeyRelease>", lambda ev: self._refresh_total())
            hl = tk.Label(grid, text=hint, bg=CLR_CARD, fg=CLR_MUTED,
                          font=(self.fam, 8))
            hl.grid(row=i, column=2, sticky="w", padx=(8, 0))
            self.hints[label] = hl
            if label in ("出库数量", "出售数量"):
                self.ent_qty = e
            elif label == "出售单价":
                self.ent_price = e
            elif label == "买家/客户":
                self.ent_buyer = e

        self.lbl_total = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_ACCENT,
                                  font=(self.fam, 11, "bold"))
        self.lbl_total.pack(anchor="w", padx=16, pady=(0, 4))
        self.lbl_msg = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_DANGER,
                                font=(self.fam, 9), anchor="w", justify="left")
        self.lbl_msg.pack(fill="x", padx=16, pady=(0, 10))

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=12)
        self.btn_ok = ttk.Button(foot, text="确认出库" if self.is_out else "确认出售",
                                 style="Accent.TButton", width=12, command=self._ok)
        self.btn_ok.pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="取消", width=10, command=self._cancel).pack(side="right")
        if self.is_out:
            self._apply_type()
        else:
            self._refresh_total()

    def _fill_addr(self):
        """选中历史买家后自动带出其最近一次收货地址（只在地址为空时填充）。"""
        try:
            if (self.var_addr.get() or "").strip():
                return
            a = self.addr_map.get((self.var_buyer.get() or "").strip())
            if a:
                self.var_addr.set(a)
        except Exception:
            pass

    def _apply_type(self):
        """出库模式：切换类型时更新说明与合计文案。"""
        try:
            self.hints["出库类型"].configure(
                text=OUT_TYPE_HINT.get(self.var_type.get(), ""))
        except Exception:
            pass
        self._refresh_total()

    def _read_qty_price(self):
        try:
            qty = int(round(float(self.var_qty.get().strip() or 0)))
        except (TypeError, ValueError):
            qty = None
        try:
            price = float(self.var_price.get().strip() or 0)
        except (TypeError, ValueError):
            price = None
        return qty, price

    def _refresh_total(self):
        qty, price = self._read_qty_price()
        if qty is None:
            self.lbl_total.configure(text="请填写正确的出库数量", fg=CLR_DANGER)
            return
        left = max(0, self.stock - qty)
        if self.is_out:
            self.lbl_total.configure(
                text="%s出库：%d 件（不产生销售额，库存剩余 %d 件）"
                     % (self.var_type.get() or "非销售", qty, left), fg=CLR_WARN)
            return
        if price is None:
            self.lbl_total.configure(text="合计：请填写正确的数量与单价", fg=CLR_DANGER)
            return
        self.lbl_total.configure(text="合计金额：%.2f 元（剩余库存 %d 件）"
                                      % (qty * price, left),
                                 fg=CLR_ACCENT)

    # ------------------------------------------------------------ 动作
    def _warn(self, msg):
        self.lbl_msg.configure(text="⚠ " + msg)

    def _ok(self):
        out_type = OUT_TYPE_SALE if not self.is_out else (
            self.var_type.get() or "其他")
        qty, price = self._read_qty_price()
        if qty is None:
            return self._warn("出库数量请填写数字")
        if qty <= 0:
            return self._warn("出库数量必须大于 0")
        if qty > self.stock:
            return self._warn("出库数量不能超过当前库存（%d 件）" % self.stock)
        if self.is_out:
            price = 0.0
        else:
            if price is None or price < 0:
                return self._warn("出售单价请填写不小于 0 的数字")
        date = (self.var_date.get() or "").strip()
        if not re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", date):
            return self._warn("出库日期格式应为 2026-10-07 这样")
        y, m, d = [int(x) for x in date.split("-")]
        self.result = {"out_type": out_type, "qty": qty, "price": price,
                       "sale_date": "%04d-%02d-%02d" % (y, m, d),
                       "buyer": (self.var_buyer.get() or "").strip()
                       if not self.is_out else "",
                       "address": (self.var_addr.get() or "").strip()
                       if not self.is_out else "",
                       "remark": (self.var_remark.get() or "").strip()}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_sale(master, record, fam="Microsoft YaHei UI", buyers=None, mode="sale",
             addr_map=None):
    """打开登记弹窗：mode="sale" 登记出售；mode="out" 登记出库。返回表单结果或 None。"""
    dlg = SaleDialog(master, record, fam, buyers, mode, addr_map)
    master.wait_window(dlg)
    return dlg.result


class ManualSaleDialog(tk.Toplevel):
    """手动登记一条出售记录（不用先在库存里选货）。

    · 只写出售记录，不扣减库存 —— 适合补录系统外的成交（老货 / 代发 / 库存早已清掉）；
    · 编号填了库里已有的编号时，自动带出品牌 / 品类 / 型号 / 货架 / 成本单价（都可改）；
    · 成本单价只用于算利润，留空按 0 计。

    result = {code, brand, category, model, shelf, qty, price, cost,
              buyer, address, sale_date, remark} 或 None。
    """

    def __init__(self, master, fam="Microsoft YaHei UI", buyers=None,
                 addr_map=None, items=None):
        super().__init__(master)
        self.result = None
        self.fam = fam
        self.buyers = list(buyers or [])
        self.addr_map = dict(addr_map or {})
        self.addr_pool = list(dict.fromkeys(self.addr_map.values()))
        self.items = {}
        for r in (items or []):
            c = str(r.get("code") or "").strip()
            if c and c not in self.items:
                self.items[c] = r
        self.row_frames = {}
        self.title("手动登记出售")
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

    # ------------------------------------------------------------ UI
    def _build(self):
        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x", padx=12, pady=(12, 8))
        tk.Label(head, text="手动登记出售", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(head, text="不用先在库存里选货，直接手填一条出售记录",
                 bg=CLR_CARD, fg=CLR_TEXT, font=(self.fam, 10)).pack(
            anchor="w", padx=16, pady=(2, 0))
        tk.Label(head, text="只写出售记录，不扣减库存（要扣库存请在库存页选中商品登记出售）",
                 bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9)).pack(
            anchor="w", padx=16, pady=(2, 12))

        body = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        body.pack(fill="x", padx=12)
        grid = tk.Frame(body, bg=CLR_CARD)
        grid.pack(fill="x", padx=16, pady=(12, 0))

        self.var_code = tk.StringVar()
        self.var_brand = tk.StringVar()
        self.var_category = tk.StringVar()
        self.var_model = tk.StringVar()
        self.var_shelf = tk.StringVar()
        self.var_qty = tk.StringVar(value="1")
        self.var_price = tk.StringVar()
        self.var_cost = tk.StringVar()
        self.var_date = tk.StringVar(value=today())
        self.var_buyer = tk.StringVar()
        self.var_addr = tk.StringVar()
        self.var_remark = tk.StringVar()

        codes = sorted(self.items.keys())
        self._row(grid, "code", "商品编号", self.var_code, 14,
                  "选填，填已有编号可自动带出商品信息", kind="combo_edit",
                  values=codes, on_select=self._fill_from_code)
        self._row(grid, "brand", "品牌", self.var_brand, 14, "选填")
        self._row(grid, "category", "品类", self.var_category, 14, "选填")
        self._row(grid, "model", "型号", self.var_model, 20, "选填，如 SM-1234")
        self._row(grid, "shelf", "货架", self.var_shelf, 14, "选填")
        self._row(grid, "qty", "出售数量", self.var_qty, 10, "件")
        self._row(grid, "price", "出售单价", self.var_price, 10, "元/件")
        self._row(grid, "cost", "成本单价", self.var_cost, 10,
                  "选填，用于算利润；留空按 0 计")
        self._row(grid, "date", "出售日期", self.var_date, 14, "格式 2026-10-07")
        if self.buyers:
            self._row(grid, "buyer", "买家/客户", self.var_buyer, 22,
                      "选填，可从历史买家选择", kind="combo_edit",
                      values=self.buyers, on_select=self._fill_addr)
        else:
            self._row(grid, "buyer", "买家/客户", self.var_buyer, 22, "选填")
        if self.addr_pool:
            self._row(grid, "address", "收货地址", self.var_addr, 22,
                      "选填，可从历史地址选择", kind="combo_edit",
                      values=self.addr_pool)
        else:
            self._row(grid, "address", "收货地址", self.var_addr, 22, "选填")
        self._row(grid, "remark", "备注", self.var_remark, 22, "选填")

        self.lbl_note = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_WARN,
                                 font=(self.fam, 9), anchor="w", justify="left",
                                 wraplength=520)
        self.lbl_note.pack(fill="x", padx=16, pady=(4, 0))
        self.lbl_total = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_ACCENT,
                                  font=(self.fam, 11, "bold"), anchor="w",
                                  justify="left", wraplength=520)
        self.lbl_total.pack(fill="x", padx=16, pady=(0, 4))
        self.lbl_msg = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_DANGER,
                                font=(self.fam, 9), anchor="w", justify="left",
                                wraplength=520)
        self.lbl_msg.pack(fill="x", padx=16, pady=(0, 10))

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=12)
        ttk.Button(foot, text="确认登记", style="Accent.TButton", width=12,
                   command=self._ok).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="取消", width=10, command=self._cancel).pack(side="right")
        self._refresh_total()

    def _row(self, parent, key, label, var, w, hint, kind="entry", values=None,
             on_select=None):
        fr = tk.Frame(parent, bg=CLR_CARD)
        tk.Label(fr, text=label, bg=CLR_CARD, fg=CLR_TEXT, font=(self.fam, 10),
                 width=9, anchor="w").pack(side="left")
        if kind == "combo":
            e = ttk.Combobox(fr, textvariable=var, values=values or [],
                             state="readonly", width=w, font=(self.fam, 10))
        elif kind == "combo_edit":
            e = ttk.Combobox(fr, textvariable=var, values=values or [], width=w,
                             font=(self.fam, 10))
        else:
            e = _entry(fr, var, w, self.fam)
        e.pack(side="left", ipady=3)
        e.bind("<KeyRelease>", lambda ev: self._refresh_total())
        if on_select is not None:
            e.bind("<<ComboboxSelected>>", lambda ev: on_select())
        tk.Label(fr, text=hint, bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 8)).pack(side="left", padx=(8, 0))
        self.row_frames[key] = fr
        if key == "qty":
            self.ent_qty = e
        elif key == "price":
            self.ent_price = e
        elif key == "code":
            self.ent_code = e
            # 手打编号也要能带出商品信息：失焦时再试一次（下拉选择走 on_select）
            e.bind("<FocusOut>", lambda ev: self._fill_from_code())
        fr.pack(fill="x", pady=3)
        return e

    def _fill_from_code(self):
        """编号命中库存里的商品 → 空着的品牌/品类/型号/货架/成本自动补齐（不覆盖已填）。"""
        code = (self.var_code.get() or "").strip()
        rec = self.items.get(code) or self.items.get(code.upper())
        if not rec:
            self.lbl_note.configure(text="")
            return
        for var, key in ((self.var_brand, "brand"), (self.var_category, "category"),
                         (self.var_model, "model"), (self.var_shelf, "shelf")):
            if not (var.get() or "").strip() and rec.get(key):
                var.set(str(rec.get(key) or ""))
        if not (self.var_cost.get() or "").strip():
            c = float(rec.get("cost") or 0) or float(rec.get("price") or 0)
            if c > 0:
                self.var_cost.set("%.2f" % c)
        self.lbl_note.configure(
            text="编号 %s 在库存中存在（现有 %d 件）：手动登记不会扣它的库存"
                 % (code, int(rec.get("qty") or 0)))
        self._refresh_total()

    def _fill_addr(self):
        try:
            if (self.var_addr.get() or "").strip():
                return
            a = self.addr_map.get((self.var_buyer.get() or "").strip())
            if a:
                self.var_addr.set(a)
        except Exception:
            pass

    def _refresh_total(self):
        try:
            qty = int(float((self.var_qty.get() or "").strip() or 0))
        except (TypeError, ValueError):
            qty = 0
        try:
            p = float((self.var_price.get() or "").strip() or 0)
            c = float((self.var_cost.get() or "").strip() or 0)
        except (TypeError, ValueError):
            self.lbl_total.configure(text="出售单价 / 成本单价请填写不小于 0 的数字",
                                     fg=CLR_DANGER)
            return
        amount = qty * p
        profit = amount - qty * c
        self.lbl_total.configure(
            text="%d 件 × %.2f 元 = 销售额 %.2f 元 · 成本 %.2f 元 · 利润 %.2f 元"
                 % (qty, p, amount, qty * c, profit),
            fg=CLR_ACCENT)

    def _warn(self, msg):
        self.lbl_msg.configure(text="⚠ " + msg)

    # ------------------------------------------------------------ 动作
    def _ok(self):
        self.lbl_msg.configure(text="")
        try:
            qty = int(float((self.var_qty.get() or "").strip() or 0))
        except (TypeError, ValueError):
            return self._warn("出售数量请填写整数")
        if qty <= 0:
            return self._warn("出售数量必须大于 0")
        try:
            price = float((self.var_price.get() or "").strip() or 0)
            cost = float((self.var_cost.get() or "").strip() or 0)
        except (TypeError, ValueError):
            return self._warn("出售单价 / 成本单价请填写不小于 0 的数字")
        if price < 0 or cost < 0:
            return self._warn("单价不能小于 0")
        code = (self.var_code.get() or "").strip()
        brand = (self.var_brand.get() or "").strip()
        model = (self.var_model.get() or "").strip()
        if not (code or brand or model):
            return self._warn("请至少填写商品编号、品牌、型号中的一项")
        date = (self.var_date.get() or "").strip()
        if date:
            if not re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", date):
                return self._warn("出售日期格式应为 2026-10-07 这样")
            y, m, d = [int(x) for x in date.split("-")]
            date = "%04d-%02d-%02d" % (y, m, d)
        self.result = {
            "code": code, "brand": brand,
            "category": (self.var_category.get() or "").strip(),
            "model": model, "shelf": (self.var_shelf.get() or "").strip(),
            "qty": qty, "price": price, "cost": cost,
            "buyer": (self.var_buyer.get() or "").strip(),
            "address": (self.var_addr.get() or "").strip(),
            "sale_date": date,
            "remark": (self.var_remark.get() or "").strip(),
        }
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_manual_sale(master, fam="Microsoft YaHei UI", buyers=None, addr_map=None,
                    items=None):
    """打开「手动登记出售」弹窗，返回表单结果或 None。"""
    dlg = ManualSaleDialog(master, fam, buyers, addr_map, items)
    master.wait_window(dlg)
    return dlg.result


class OutTypeDialog(tk.Toplevel):
    """修改出库记录的类型（典型场景：出库去维修 → 修好后卖掉了）。

    单选一条：可改成任意类型；改成「销售」时补填售价 / 买家 / 收货地址 / 日期 / 备注。
    多选多条：只允许在非销售类型之间批量纠正（改销售必须一次一条，因为要填金额）。

    改类型不会动库存 —— 这笔出库登记时已经扣过一次，不会重复扣减。

    result = {out_type, price, buyer, address, sale_date, remark, batch} 或 None。
    """

    def __init__(self, master, rows, fam="Microsoft YaHei UI", buyers=None,
                 addr_map=None):
        super().__init__(master)
        self.result = None
        self.fam = fam
        self.rows = [dict(r) for r in (rows or [])]
        self.multi = len(self.rows) > 1
        self.one = self.rows[0] if self.rows else {}
        self.qty = int(self.one.get("qty") or 0)
        self.cur_type = str(self.one.get("out_type") or OUT_TYPE_SALE)
        self.buyers = list(buyers or [])
        self.addr_map = dict(addr_map or {})
        self.addr_pool = list(dict.fromkeys(self.addr_map.values()))
        self.row_frames = {}
        self.hints = {}
        self.title("修改出库类型")
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

    # ------------------------------------------------------------ UI
    def _build(self):
        one = self.one
        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x", padx=12, pady=(12, 8))
        tk.Label(head, text="修改出库类型", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        if self.multi:
            name = "已选中 %d 条出库记录（批量只改类型，不动金额与备注）" % len(self.rows)
        else:
            name = " · ".join([x for x in (one.get("code"), one.get("brand"),
                                           one.get("model")) if x]) or "（无编号记录）"
        tk.Label(head, text=name, bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 10)).pack(anchor="w", padx=16, pady=(2, 0))
        if self.multi:
            kinds = {}
            for r in self.rows:
                t = str(r.get("out_type") or OUT_TYPE_SALE)
                kinds[t] = kinds.get(t, 0) + 1
            sub = "合计 %d 件 · 类型分布：%s" % (
                sum(int(r.get("qty") or 0) for r in self.rows),
                "、".join("%s %d 笔" % kv for kv in kinds.items()))
        else:
            sub = "出库数量 %d 件 · 当前类型：%s · 出库日期 %s" % (
                self.qty, self.cur_type, one.get("sale_date") or "未填")
        tk.Label(head, text=sub, bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(anchor="w", padx=16, pady=(2, 0))
        tk.Label(head, text="改类型不会重复扣减库存（这笔出库登记时已经扣过一次）",
                 bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9)).pack(
            anchor="w", padx=16, pady=(2, 12))

        body = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        body.pack(fill="x", padx=12)
        grid = tk.Frame(body, bg=CLR_CARD)
        grid.pack(fill="x", padx=16, pady=12)

        types = list(OUT_TYPES) if not self.multi else \
            [t for t in OUT_TYPES if t != OUT_TYPE_SALE]
        default_type = self.cur_type if self.cur_type in types else (
            OUT_TYPE_SALE if OUT_TYPE_SALE in types else types[0])
        self.var_type = tk.StringVar(value=default_type)
        self.var_price = tk.StringVar(
            value=("%.2f" % float(one.get("price") or 0))
            if float(one.get("price") or 0) > 0 else "")
        self.var_buyer = tk.StringVar(value=str(one.get("buyer") or ""))
        self.var_addr = tk.StringVar(value=str(one.get("address") or ""))
        self.var_date = tk.StringVar(value=str(one.get("sale_date") or today()))
        self.var_remark = tk.StringVar(value=str(one.get("remark") or ""))

        self._row(grid, "type", "新类型", self.var_type, 14,
                  OUT_TYPE_HINT.get(default_type, ""), kind="combo", values=types,
                  on_select=self._apply_type)
        self._row(grid, "price", "出售单价", self.var_price, 12, "元/件",
                  on_key=self._refresh_total)
        if self.buyers:
            self._row(grid, "buyer", "买家/客户", self.var_buyer, 24,
                      "选填，可从历史买家选择", kind="combo", values=self.buyers,
                      on_select=self._fill_addr)
        else:
            self._row(grid, "buyer", "买家/客户", self.var_buyer, 24, "选填")
        if self.addr_pool:
            self._row(grid, "address", "收货地址", self.var_addr, 24,
                      "选填，发货/收货地址", kind="combo", values=self.addr_pool)
        else:
            self._row(grid, "address", "收货地址", self.var_addr, 24, "选填")
        self._row(grid, "date", "出库日期", self.var_date, 14, "格式 2026-10-07")
        self._row(grid, "remark", "原因/去向", self.var_remark, 24,
                  "选填，如 屏幕碎裂 / 已修好卖出", on_key=self._refresh_total)

        self.lbl_total = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_ACCENT,
                                  font=(self.fam, 11, "bold"), anchor="w",
                                  justify="left", wraplength=520)
        self.lbl_total.pack(fill="x", padx=16, pady=(0, 4))
        self.lbl_msg = tk.Label(body, text="", bg=CLR_CARD, fg=CLR_DANGER,
                                font=(self.fam, 9), anchor="w", justify="left",
                                wraplength=520)
        self.lbl_msg.pack(fill="x", padx=16, pady=(0, 10))

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=12)
        ttk.Button(foot, text="确认修改", style="Accent.TButton", width=12,
                   command=self._ok).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="取消", width=10, command=self._cancel).pack(side="right")
        self._apply_type()

    def _row(self, parent, key, label, var, w, hint, kind="entry", values=None,
             on_select=None, on_key=None):
        """一行表单；返回输入控件。行整行 Frame 便于按类型显隐。"""
        fr = tk.Frame(parent, bg=CLR_CARD)
        tk.Label(fr, text=label, bg=CLR_CARD, fg=CLR_TEXT, font=(self.fam, 10),
                 width=9, anchor="w").pack(side="left")
        if kind == "combo":
            e = ttk.Combobox(fr, textvariable=var, values=values or [],
                             state="readonly", width=w, font=(self.fam, 10))
        elif kind == "combo_edit":
            e = ttk.Combobox(fr, textvariable=var, values=values or [], width=w,
                             font=(self.fam, 10))
        else:
            e = _entry(fr, var, w, self.fam)
        e.pack(side="left", ipady=3)
        if on_select is not None:
            e.bind("<<ComboboxSelected>>", lambda ev: on_select())
        if on_key is not None:
            e.bind("<KeyRelease>", lambda ev: on_key())
        hl = tk.Label(fr, text=hint, bg=CLR_CARD, fg=CLR_MUTED,
                      font=(self.fam, 8))
        hl.pack(side="left", padx=(8, 0))
        self.hints[key] = hl
        self.row_frames[key] = fr
        if key == "price":
            self.ent_price = e
        fr.pack(fill="x", pady=3)          # 先放上，_apply_type 再按需隐藏
        return e

    def _fill_addr(self):
        try:
            if (self.var_addr.get() or "").strip():
                return
            a = self.addr_map.get((self.var_buyer.get() or "").strip())
            if a:
                self.var_addr.set(a)
        except Exception:
            pass

    def _show_rows(self):
        """按当前类型显示/隐藏各行（销售专属行只在改销售时出现）。"""
        is_sale = self.var_type.get() == OUT_TYPE_SALE
        order = ["type", "price", "buyer", "address", "date", "remark"]
        show = {"type": True,
                "price": is_sale and not self.multi,
                "buyer": is_sale and not self.multi,
                "address": is_sale and not self.multi,
                "date": not self.multi,
                "remark": not self.multi}
        for k in order:
            fr = self.row_frames.get(k)
            if fr is None:
                continue
            if not show.get(k):
                fr.pack_forget()
                continue
            nxt = None
            for k2 in order[order.index(k) + 1:]:
                fr2 = self.row_frames.get(k2)
                if show.get(k2) and fr2 is not None and fr2.winfo_manager() == "pack":
                    nxt = fr2
                    break
            if nxt is not None:
                fr.pack(fill="x", pady=3, before=nxt)
            else:
                fr.pack(fill="x", pady=3)

    def _apply_type(self):
        try:
            self.hints["type"].configure(
                text=OUT_TYPE_HINT.get(self.var_type.get(), ""))
        except Exception:
            pass
        self._show_rows()
        self._refresh_total()

    def _refresh_total(self):
        t = self.var_type.get()
        if t == OUT_TYPE_SALE:
            try:
                p = float(self.var_price.get().strip() or 0)
            except (TypeError, ValueError):
                self.lbl_total.configure(text="出售单价请填写不小于 0 的数字",
                                         fg=CLR_DANGER)
                return
            self.lbl_total.configure(
                text="改为「销售」：%d 件 × %.2f 元 = 合计 %.2f 元（计入销售额与利润）"
                     % (self.qty, p, self.qty * p), fg=CLR_ACCENT)
            return
        if self.multi:
            self.lbl_total.configure(
                text="批量修改：把选中的 %d 笔都改为「%s」（不计销售额，库存不变）"
                     % (len(self.rows), t), fg=CLR_WARN)
        else:
            self.lbl_total.configure(
                text="改为「%s」：不计销售额，售价与买家、地址会被清空，库存不变" % t,
                fg=CLR_WARN)

    # ------------------------------------------------------------ 动作
    def _warn(self, msg):
        self.lbl_msg.configure(text="⚠ " + msg)

    def _ok(self):
        t = self.var_type.get() or OUT_TYPE_SALE
        is_sale = (t == OUT_TYPE_SALE)
        price = 0.0
        if is_sale:
            try:
                price = float(self.var_price.get().strip() or 0)
            except (TypeError, ValueError):
                return self._warn("出售单价请填写不小于 0 的数字")
            if price < 0:
                return self._warn("出售单价不能小于 0")
        date = (self.var_date.get() or "").strip()
        if not self.multi and date:
            if not re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", date):
                return self._warn("出库日期格式应为 2026-10-07 这样")
            y, m, d = [int(x) for x in date.split("-")]
            date = "%04d-%02d-%02d" % (y, m, d)
        self.result = {
            "out_type": t,
            "price": price,
            "buyer": (self.var_buyer.get() or "").strip() if is_sale else "",
            "address": (self.var_addr.get() or "").strip() if is_sale else "",
            "sale_date": date if not self.multi else "",
            "remark": (self.var_remark.get() or "").strip() if not self.multi
            else None,
            "batch": self.multi,
        }
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_out_type(master, rows, fam="Microsoft YaHei UI", buyers=None, addr_map=None):
    """打开「修改出库类型」弹窗，返回表单结果或 None。"""
    dlg = OutTypeDialog(master, rows, fam, buyers, addr_map)
    master.wait_window(dlg)
    return dlg.result


# ==========================================================================
# 出售记录页（只看销售） / 出库记录页（总览全部出库，含销售）
# ==========================================================================
SALE_COLS = (("sale_date", "出售日期", 100),
             ("code", "编号", 110), ("brand", "品牌", 130),
             ("category", "品类", 90), ("model", "型号", 150),
             ("qty", "数量", 60), ("price", "售价", 80),
             ("total", "总额", 95), ("profit", "利润", 90),
             ("buyer", "买家/客户", 110), ("address", "收货地址", 190),
             ("shelf", "货架", 120), ("remark", "备注", 160))

# 左对齐更易读的文本列（其余列居中）
LEFT_COLS = ("remark", "address")

# 出库总览页：含全部出库类型（销售 + 非销售），统一用「库存减少价值」口径，
# 不含售价/销售额/利润/买家等销售字段，避免与出售记录混淆
OUT_COLS = (("sale_date", "出库日期", 100), ("out_type", "类型", 80),
            ("code", "编号", 110), ("brand", "品牌", 130),
            ("category", "品类", 90), ("model", "型号", 150),
            ("qty", "数量", 60), ("cost", "成本单价", 90),
            ("cost_total", "成本合计", 90), ("shelf", "货架", 120),
            ("remark", "原因/去向", 200))


class SalesTab(ttk.Frame):
    """记录页：mode="sale" 出售记录（只看销售）；mode="out" 出库记录（总览全部出库）。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI", mode="sale"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.mode = "out" if mode == "out" else "sale"
        self.is_out = self.mode == "out"
        self.rows = []
        self._build()

    # ------------------------------------------------------------ UI
    def _build(self):
        is_out = self.is_out
        bar = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x")
        tk.Label(bar, text="出库记录" if is_out else "出售记录",
                 bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left", padx=(16, 10), pady=12)
        self.lbl_wh = tk.Label(bar, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                               font=(self.fam, 9))
        self.lbl_wh.pack(side="left", pady=12)
        if is_out:
            tk.Label(bar, text="总览全部出库流水（销售出库 + 非销售出库，都是减库存）",
                     bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.fam, 9)).pack(side="left", padx=(10, 0), pady=12)
        ttk.Button(bar, text="导出出库记录" if is_out else "导出出售记录",
                   style="Accent.TButton",
                   command=self.export).pack(side="right", padx=(8, 16), pady=8)
        ttk.Button(bar, text="刷新", command=self.refresh_tab).pack(side="right", pady=8)
        if not is_out:
            # 手动补录：不选库存商品，直接手填一条出售记录（不扣库存）
            ttk.Button(bar, text="+ 登记出售", style="Ghost.TButton",
                       command=self.manual_add).pack(side="right", padx=(0, 8), pady=8)
        if is_out:
            ttk.Button(bar, text="+ 登记出库", style="Ghost.TButton",
                       command=self.app.out_stock_selected).pack(
                side="right", padx=(0, 8), pady=8)
        else:
            self.btn_trend = ttk.Button(bar, text="显示趋势图", style="Ghost.TButton",
                                        command=self._toggle_trend)
            self.btn_trend.pack(side="right", padx=(0, 8), pady=8)
            ttk.Button(bar, text="买家管理", style="Ghost.TButton",
                       command=self.manage_buyers).pack(side="right", padx=(0, 8), pady=8)

        # 筛选条
        flt = tk.Frame(self, bg=CLR_BG)
        flt.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(flt, text="日期", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_start = tk.StringVar()
        self.var_end = tk.StringVar()
        for var, ph in ((self.var_start, "起"), (self.var_end, "止")):
            e = _entry(flt, var, 11, self.fam)
            e.pack(side="left", padx=(4, 2), ipady=2)
            e.bind("<KeyRelease>", lambda ev: self._debounce())
            tk.Label(flt, text=ph, bg=CLR_BG, fg=CLR_MUTED,
                     font=(self.fam, 8)).pack(side="left", padx=(0, 6))
        tk.Label(flt, text="品牌", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(6, 4))
        self.var_brand = tk.StringVar(value="全部")
        # 品牌可手动输入（不区分大小写包含匹配），也可从历史品牌下拉选择
        self.cb_brand = ttk.Combobox(flt, textvariable=self.var_brand, values=["全部"],
                                     width=14, font=(self.fam, 9))
        self.cb_brand.pack(side="left")
        self.cb_brand.bind("<<ComboboxSelected>>", lambda e: self.refresh_rows())
        self.cb_brand.bind("<KeyRelease>", lambda e: self._debounce())
        if is_out:
            # 出库页总览全部出库，类型筛选含「销售」与各非销售类型
            tk.Label(flt, text="类型", bg=CLR_BG, fg=CLR_MUTED,
                     font=(self.fam, 9)).pack(side="left", padx=(10, 4))
            self.var_type = tk.StringVar(value="全部")
            self.cb_type = ttk.Combobox(flt, textvariable=self.var_type,
                                        values=["全部"] + list(OUT_TYPES),
                                        state="readonly", width=8, font=(self.fam, 9))
            self.cb_type.pack(side="left")
            self.cb_type.bind("<<ComboboxSelected>>", lambda e: self.refresh_rows())
        else:
            self.var_type = tk.StringVar(value="全部")
            self.cb_type = None
        tk.Label(flt, text="搜索", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(10, 4))
        self.var_kw = tk.StringVar()
        e = _entry(flt, self.var_kw, 18, self.fam)
        e.pack(side="left", ipady=2)
        e.bind("<KeyRelease>", lambda ev: self._debounce())
        ttk.Button(flt, text="重置", style="Ghost.TButton", width=6,
                   command=self.reset_filters).pack(side="left", padx=10)
        for text, cb in (("本月", self._this_month), ("今天", self._today_only)):
            ttk.Button(flt, text=text, style="Ghost.TButton", width=6,
                       command=cb).pack(side="left", padx=(0, 4))

        # 合计卡片
        cards = tk.Frame(self, bg=CLR_BG)
        cards.pack(fill="x", padx=16, pady=(10, 0))
        self.kpi = {}
        if is_out:
            kpi_def = (("count", "出库笔数"), ("qty", "出库件数"),
                       ("cost", "成本价值(元)"),
                       ("split", "其中销售 / 非销售"))
        else:
            kpi_def = (("count", "销售笔数"), ("qty", "销售件数"),
                       ("amount", "销售额(元)"), ("cost", "成本(元)"),
                       ("profit", "利润(元)"))
        for key, title in kpi_def:
            card = tk.Frame(cards, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                            highlightthickness=1)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(card, text=title, bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.fam, 9)).pack(anchor="w", padx=12, pady=(8, 0))
            lbl = tk.Label(card, text="0", bg=CLR_CARD, fg=CLR_TEXT,
                           font=(self.fam, 13, "bold"))
            lbl.pack(anchor="w", padx=12, pady=(0, 8))
            self.kpi[key] = lbl

        # ---- 本月销售目标（仅出售页）----
        if not is_out:
            tgt = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                           highlightthickness=1)
            tgt.pack(fill="x", padx=16, pady=(10, 0))
            row = tk.Frame(tgt, bg=CLR_CARD)
            row.pack(fill="x", padx=12, pady=(8, 4))
            tk.Label(row, text="本月销售目标", bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.fam, 9)).pack(side="left")
            self.lbl_target = tk.Label(row, text="", bg=CLR_CARD, fg=CLR_TEXT,
                                       font=(self.fam, 10, "bold"))
            self.lbl_target.pack(side="left", padx=(10, 0))
            ttk.Button(row, text="设置目标", style="Ghost.TButton",
                       command=self.set_target).pack(side="right")
            self.bar_target = ProgressStat(tgt, height=10, bg=CLR_CARD)
            self.bar_target.pack(fill="x", padx=12, pady=(0, 10))

        # ---- 趋势图（仅出售页；默认隐藏，点「显示趋势图」展开）----
        self.trend = tk.Frame(self, bg=CLR_BG)
        if not is_out:
            g = tk.Frame(self.trend, bg=CLR_BG)
            g.pack(fill="x")
            self.c_month = VBarChart(g, "近 12 个月销售额（元）", height=200)
            self.c_month.set_font_family(self.fam)
            self.c_month.pack(side="left", fill="both", expand=True)
            self.c_brand2 = HBarChart(g, "品牌销售额 TOP10（元）", height=200)
            self.c_brand2.set_font_family(self.fam)
            self.c_brand2.pack(side="left", fill="both", expand=True, padx=(10, 0))

        # 表格
        wrap = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=10)
        self.table_wrap = wrap
        cols = [c[0] for c in (OUT_COLS if is_out else SALE_COLS)]
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        vs = ttk.Scrollbar(wrap, orient="vertical", style="Vertical.TScrollbar",
                           command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w in (OUT_COLS if is_out else SALE_COLS):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w,
                             anchor="w" if key in LEFT_COLS else "center",
                             stretch=(key in ("brand", "model", "remark", "address")))
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        # tag 优先级 = 创建先后（先创建的先胜）：鼠标划过 > 非销售黄底 > 斑马纹
        self.hover = RowHover(self.tree, self.app.root)
        self.tree.tag_configure("other", background="#FFF7E6")   # 非销售出库：淡黄底
        self.tree.tag_configure("odd", background="#F7FAFD")     # 斑马纹优先级最低
        self.tree.bind("<Double-1>", lambda e: self.undo_selected())
        # 复制：拖选区块 / Ctrl+C / 右键菜单（与库存页一致的用法）
        self._drag_anchor = None      # (行 iid, 列下标)
        self._drag_block = None       # {"rows": [iid...], "c0": 起始列, "c1": 结束列}
        self._cell_key = cols[0]
        self._by_id = {}
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<B1-Motion>", self._on_drag)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_end)
        self.tree.bind("<Button-3>", self.on_right_click)
        self.tree.bind("<Control-c>", self._on_ctrl_c)

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 10))
        self.lbl_hint = tk.Label(foot, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=(self.fam, 9))
        self.lbl_hint.pack(side="left")
        ttk.Button(foot, text="撤销选中出售（数量加回库存）" if not is_out
                   else "撤销选中出库（数量加回库存）", style="Danger.TButton",
                   command=self.undo_selected).pack(side="right")
        ttk.Button(foot, text="修改类型", style="Ghost.TButton", width=9,
                   command=self.change_type).pack(side="right", padx=(0, 8))
        # 拖选即复制开关（与库存页共用同一个设置）
        try:
            dot_check(foot, "拖选即复制", self.app.var_drag_copy,
                      command=self.app._save_drag_copy, bg=CLR_BG,
                      fam=self.fam, size=9).pack(side="right", padx=(0, 12))
        except Exception:
            pass

        # 恢复上次的趋势图展开状态（仅出售页）
        if not is_out:
            try:
                if self.app.settings.get("sale_trend"):
                    self.trend.pack(fill="x", padx=16, pady=(10, 0), before=self.table_wrap)
                    self.btn_trend.configure(text="隐藏趋势图")
            except Exception:
                pass

    # ------------------------------------------------------------ 取值
    def cols_def(self):
        return OUT_COLS if self.is_out else SALE_COLS

    def col_keys(self):
        return [c[0] for c in self.cols_def()]

    def col_titles(self):
        return {c[0]: c[1] for c in self.cols_def()}

    @staticmethod
    def row_values(r, cols_def):
        """一行在表格里的显示值（复制时与界面完全一致）。"""
        values = []
        for key, _t, _w in cols_def:
            if key == "qty":
                values.append("%d" % int(r.get("qty") or 0))
            elif key in ("price", "total"):
                values.append("%.2f" % float(r.get(key) or 0))
            elif key == "cost":                       # 出库页：成本单价
                values.append("%.2f" % float(r.get("cost") or 0))
            elif key == "cost_total":                 # 出库页：成本合计
                values.append("%.2f" % (float(r.get("cost") or 0)
                                        * int(r.get("qty") or 0)))
            elif key == "profit":
                p = float(r.get("total") or 0) - float(r.get("cost") or 0) * int(r.get("qty") or 0)
                values.append("%.2f" % p)
            elif key == "out_type":
                values.append(str(r.get("out_type") or OUT_TYPE_SALE))
            else:
                values.append(str(r.get(key) or ""))
        return values

    def row_map(self):
        """行 iid → 记录。"""
        return self._by_id

    # ------------------------------------------------------------ 数据
    def refresh_tab(self):
        """切入本页时调用：刷新仓库徽章与列表。"""
        try:
            self.lbl_wh.configure(text="当前仓库：%s" % self.app.cur_wh()["name"])
        except Exception:
            pass
        self.refresh_rows()

    # ------------------------------------------------------------ 趋势 / 目标
    def _toggle_trend(self):
        if self.trend.winfo_ismapped():
            self.trend.pack_forget()
            self.btn_trend.configure(text="显示趋势图")
        else:
            self.trend.pack(fill="x", padx=16, pady=(10, 0), before=self.table_wrap)
            self.btn_trend.configure(text="隐藏趋势图")
            self.refresh_trend()
        try:
            self.app.settings["sale_trend"] = bool(self.trend.winfo_ismapped())
            self.app._save_settings()
        except Exception:
            pass

    def refresh_trend(self):
        st = self.app.store
        monthly = st.monthly_sales(12)
        # 横轴统一用「N月」：近 12 个月窗口里 11/12 月必然是去年，不会与今年混淆；
        # 具体年份在副标题的统计区间里体现（如 2025-11 ~ 2026-10）。
        labels = ["%d月" % int(k.split("-")[1]) for k, _v in monthly]
        self.c_month.set_data([(lab, v) for lab, (_k, v) in zip(labels, monthly)],
                              subtitle="近 12 个月（%s ~ %s）销售额合计 ¥%s"
                                       % (monthly[0][0], monthly[-1][0],
                                          money(sum(v for _k, v in monthly))))
        bs = st.brand_sales(10)
        self.c_brand2.set_data([(b, amt) for b, amt, _p in bs],
                               subtitle="共 %d 个品牌有销售" % len(bs))

    def refresh_target(self):
        st = self.app.store
        target = st.get_num(TARGET_KEY, 0)
        cur = st.month_sales_amount()
        if target <= 0:
            self.lbl_target.configure(
                text="本月已售 ¥%s（未设置目标）" % money(cur["amount"]), fg=CLR_TEXT)
            self.bar_target.set_value(0, CLR_ACCENT)
            return
        pct = cur["amount"] / float(target) * 100.0
        self.lbl_target.configure(
            text="本月已售 ¥%s / 目标 ¥%s（%.1f%%），还差 ¥%s"
                 % (money(cur["amount"]), money(target), pct,
                    money(max(0.0, target - cur["amount"]))),
            fg=(CLR_OK if pct >= 100 else (CLR_WARN if pct >= 60 else CLR_ACCENT)))
        self.bar_target.set_value(min(100.0, pct),
                                  CLR_OK if pct >= 100 else CLR_ACCENT)

    def set_target(self):
        from .extras import ask_name
        cur = self.app.store.get_num(TARGET_KEY, 0)
        v = ask_name(self.app.root, "设置本月销售目标",
                     "请输入本月销售目标金额（元）：", "%.0f" % cur if cur else "",
                     self.fam)
        if v is None:
            return
        v = str(v).strip().replace(",", "").replace("¥", "")
        try:
            val = float(v or 0)
        except ValueError:
            messagebox.showwarning("设置目标", "请填写数字金额。", parent=self.app.root)
            return
        if val < 0:
            messagebox.showwarning("设置目标", "目标金额不能为负数。", parent=self.app.root)
            return
        self.app.store.set_meta(TARGET_KEY, val)
        self.refresh_target()
        self.app._status("本月销售目标已设为 ¥%s" % money(val)
                         if val else "已清除本月销售目标")

    def manage_buyers(self):
        from .extras import BuyerDialog
        BuyerDialog(self.app, self.fam)

    def _debounce(self):
        if getattr(self, "_after", None):
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
        self._after = self.after(300, self.refresh_rows)

    def _this_month(self):
        d = today()
        self.var_start.set(d[:8] + "01")
        self.var_end.set(d)
        self.refresh_rows()

    def _today_only(self):
        d = today()
        self.var_start.set(d)
        self.var_end.set(d)
        self.refresh_rows()

    def reset_filters(self):
        self.var_start.set("")
        self.var_end.set("")
        self.var_kw.set("")
        self.var_brand.set("全部")
        self.var_type.set("全部")
        self.refresh_rows()

    def refresh_rows(self):
        st = self.app.store
        # 出库页 = 总览全部出库（含销售）；出售页 = 只看销售
        scope = "" if self.is_out else "sale"
        self.rows = st.list_sales(self.var_start.get().strip(),
                                  self.var_end.get().strip(),
                                  self.var_brand.get(), self.var_kw.get(),
                                  self.var_type.get(), scope)
        vals = ["全部"] + st.sales_brands()
        self.cb_brand["values"] = vals
        if self.var_brand.get() not in vals:
            self.var_brand.set("全部")
        cols_def = OUT_COLS if self.is_out else SALE_COLS
        self.tree.delete(*self.tree.get_children())
        self._by_id = {str(r["id"]): r for r in self.rows}
        self._drag_anchor = None
        self._drag_block = None
        if getattr(self, "hover", None):
            self.hover.reset()      # 行全部重建，划过标记作废
        n_sale = sum(1 for r in self.rows
                     if (r.get("out_type") or OUT_TYPE_SALE) == OUT_TYPE_SALE)
        if self.is_out:
            t = st.out_totals(self.rows)
            n_other = t["count"] - n_sale
            self.kpi["count"].configure(text="%d" % t["count"])
            self.kpi["qty"].configure(text="%d" % t["qty"])
            self.kpi["cost"].configure(text=money(t["cost"]))
            self.kpi["split"].configure(text="%d / %d 笔" % (n_sale, n_other))
            type_bits = " · ".join("%s %d 件" % (k, v)
                                   for k, v in sorted(t["by_type"].items(),
                                                      key=lambda kv: -kv[1]))
            self.lbl_hint.configure(
                text="共 %d 笔出库（销售 %d 笔 · 非销售 %d 笔）· %s"
                     " · 双击一行可撤销（数量加回库存）· 拖选单元格可复制 / 右键更多复制方式"
                     % (t["count"], n_sale, n_other, type_bits or "暂无出库"))
        else:
            t = st.sales_totals(self.rows)
            self.kpi["count"].configure(text="%d" % t["count"])
            self.kpi["qty"].configure(text="%d" % t["qty"])
            self.kpi["amount"].configure(text=money(t["amount"]))
            self.kpi["cost"].configure(text=money(t["cost"]))
            self.kpi["profit"].configure(text=money(t["profit"]),
                                         fg=(CLR_OK if t["profit"] >= 0 else CLR_DANGER))
            self.lbl_hint.configure(
                text="共 %d 笔出售记录 · 双击一行可撤销（数量加回库存）"
                     " · 拖选单元格可复制 / 右键更多复制方式" % len(self.rows))
        for i, r in enumerate(self.rows):
            values = self.row_values(r, cols_def)
            tags = ["odd"] if i % 2 else []
            if (r.get("out_type") or OUT_TYPE_SALE) != OUT_TYPE_SALE:
                tags.append("other")   # 非销售出库：淡黄底，与销售出库区分
            self.tree.insert("", "end", iid=str(r["id"]), values=values, tags=tuple(tags))
        self.refresh_target() if not self.is_out else None
        if not self.is_out and self.trend.winfo_ismapped():
            self.refresh_trend()

    # ------------------------------------------------------------ 复制
    def _status(self, msg):
        try:
            self.app._status(msg)
        except Exception:
            pass

    def _clip(self, text, msg="已复制到剪贴板"):
        if not text:
            self._status("没有可复制的内容")
            return
        try:
            root = self.app.root
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update_idletasks()
            self._status("%s（%d 个字符）" % (msg, len(text)))
        except Exception as e:
            self._status("复制失败：%s" % e)

    def _tsv(self, rows, keys=None):
        """复制为 TSV：纯数据、不带表头，可直接粘贴进 Excel。"""
        cols_def = self.cols_def()
        keys = keys or [c[0] for c in cols_def]
        idx = {c[0]: i for i, c in enumerate(cols_def)}
        lines = []
        for r in rows:
            vals = self.row_values(r, cols_def)
            lines.append("\t".join(vals[idx[k]].replace("\t", " ").replace("\n", " ")
                                   for k in keys if k in idx))
        return "\n".join(lines)

    def _selected_rows(self):
        return [self._by_id[i] for i in self.tree.selection() if i in self._by_id]

    def _focused_row(self):
        return self._by_id.get(str(self.tree.focus()))

    def _cell_key_of(self, idx):
        keys = self.col_keys()
        return keys[idx] if 0 <= idx < len(keys) else keys[0]

    def copy_block(self, silent=True):
        """复制鼠标拖选出来的单元格区块。"""
        blk = self._drag_block
        if not blk:
            if not silent:
                self._status("没有选中区块")
            return
        keys = self.col_keys()[blk["c0"]:blk["c1"] + 1]
        rows = [self._by_id[i] for i in blk["rows"] if i in self._by_id]
        if not rows:
            self._status("选中的内容已不在当前列表")
            return
        self._clip(self._tsv(rows, keys),
                   "已复制选中区块（%d 行 × %d 列）" % (len(rows), len(keys)))

    def copy_cell(self):
        r = self._focused_row()
        if not r:
            self._status("请先点击要复制的单元格")
            return
        cols_def = self.cols_def()
        idx = {c[0]: i for i, c in enumerate(cols_def)}
        key = self._cell_key if self._cell_key in idx else cols_def[0][0]
        title = self.col_titles().get(key, key)
        self._clip(self.row_values(r, cols_def)[idx[key]], "已复制「%s」" % title)

    def copy_row(self):
        r = self._focused_row() or (self._selected_rows() or [None])[0]
        if not r:
            self._status("请先选中一行")
            return
        cols_def = self.cols_def()
        vals = self.row_values(r, cols_def)
        lines = ["%s：%s" % (c[1], vals[i]) for i, c in enumerate(cols_def)]
        self._clip("\n".join(lines), "已复制整行")

    def copy_column(self):
        cols_def = self.cols_def()
        idx = {c[0]: i for i, c in enumerate(cols_def)}
        key = self._cell_key if self._cell_key in idx else cols_def[0][0]
        rows = self._selected_rows() or self.rows
        vals = [self.row_values(r, cols_def)[idx[key]] for r in rows]
        self._clip("\n".join(vals),
                   "已复制「%s」列 %d 项" % (self.col_titles().get(key, key), len(vals)))

    def copy_selected(self):
        rows = self._selected_rows()
        if not rows:
            self._status("请先选中要复制的行")
            return
        self._clip(self._tsv(rows), "已复制 %d 行" % len(rows))

    def copy_all(self):
        if not self.rows:
            self._status("没有可复制的数据")
            return
        self._clip(self._tsv(self.rows), "已复制全部筛选结果 %d 行" % len(self.rows))

    def copy_with_header(self):
        """表头 + 当前列表全部行（便于直接粘贴成带标题的表格）。"""
        if not self.rows:
            self._status("没有可复制的数据")
            return
        head = "\t".join(c[1] for c in self.cols_def())
        self._clip(head + "\n" + self._tsv(self.rows),
                   "已复制表头 + %d 行" % len(self.rows))

    def copy_shortcut(self):
        """供全局 Ctrl+C 调用（在输入框里按 Ctrl+C 不会走到这里）。"""
        self._on_ctrl_c()

    # ------------------------------------------------- 鼠标 / 键盘交互
    def _cell_at(self, x, y):
        """返回 (行 iid, 列下标)；不在数据单元格上时返回 (None, None)。"""
        if self.tree.identify_region(x, y) != "cell":
            return None, None
        iid = self.tree.identify_row(y)
        if not iid:
            return None, None
        colid = self.tree.identify_column(x)
        try:
            idx = int(str(colid).replace("#", "")) - 1
        except ValueError:
            return None, None
        if not (0 <= idx < len(self.col_keys())):
            return None, None
        return iid, idx

    def _row_span(self, iid_a, iid_b):
        kids = list(self.tree.get_children(""))
        try:
            i, j = kids.index(iid_a), kids.index(iid_b)
        except ValueError:
            return [iid_b]
        return kids[min(i, j):max(i, j) + 1]

    def _drag_copy_on(self):
        try:
            return bool(self.app.var_drag_copy.get())
        except Exception:
            return True

    def _on_click(self, event):
        self._drag_anchor = None
        self._drag_block = None
        iid, idx = self._cell_at(event.x, event.y)
        if iid is not None:
            self._drag_anchor = (iid, idx)
            self._cell_key = self._cell_key_of(idx)

    def _on_drag(self, event):
        """按住左键划过单元格：记录选区（行区间 × 列区间）。"""
        if not self._drag_anchor:
            return
        iid, idx = self._cell_at(event.x, event.y)
        if iid is None:
            return
        a_iid, a_idx = self._drag_anchor
        if iid == a_iid and idx == a_idx:
            return
        rows = self._row_span(a_iid, iid)
        c0, c1 = min(a_idx, idx), max(a_idx, idx)
        self._drag_block = {"rows": rows, "c0": c0, "c1": c1}
        titles = self.col_titles()
        self._status("已选中区块：%d 行 × %d 列（%s ~ %s）%s" % (
            len(rows), c1 - c0 + 1,
            titles.get(self._cell_key_of(c0), ""), titles.get(self._cell_key_of(c1), ""),
            "，松开鼠标即复制" if self._drag_copy_on() else "，按 Ctrl+C 复制"))

    def _on_drag_end(self, _event=None):
        self._drag_anchor = None
        if not self._drag_block:
            return
        if self._drag_copy_on():
            self.copy_block(silent=False)

    def _on_ctrl_c(self, _event=None):
        """Ctrl+C：有拖选区块就复制区块，否则复制选中行。"""
        if self._drag_block:
            self.copy_block()
        else:
            self.copy_selected()
        return "break"

    def on_right_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if iid and str(iid) not in self.tree.selection():
            self.tree.selection_set(str(iid))
        self.tree.focus(iid)
        self._on_click(event)
        sel = self.tree.selection()
        title = self.col_titles().get(self._cell_key, self._cell_key)
        blk = self._drag_block
        m = tk.Menu(self.app.root, tearoff=0)
        if blk:
            keys = self.col_keys()[blk["c0"]:blk["c1"] + 1]
            m.add_command(
                label="复制框选区块（%d 行 × %d 列）" % (len(blk["rows"]), len(keys)),
                command=self.copy_block)
        m.add_command(label="复制单元格（%s）" % title, command=self.copy_cell)
        m.add_command(label="复制整行（字段: 值）", command=self.copy_row)
        m.add_command(label="复制选中行（%d 行 · 可直接粘贴 Excel）" % len(sel),
                      command=self.copy_selected)
        m.add_command(label="复制「%s」整列" % title, command=self.copy_column)
        m.add_command(label="复制全部筛选结果（%d 行）" % len(self.rows),
                      command=self.copy_all)
        m.add_separator()
        m.add_command(label="复制表头 + 全部行（%d 行）" % len(self.rows),
                      command=self.copy_with_header)
        m.add_separator()
        m.add_command(
            label="修改选中记录的类型…（如 出库维修 → 修好卖出）",
            command=self.change_type, state="normal" if sel else "disabled")
        m.add_command(label="撤销选中%s（数量加回库存）" % ("出库" if self.is_out else "出售"),
                      command=self.undo_selected,
                      state="normal" if sel else "disabled")
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    # ------------------------------------------------------------ 动作
    def manual_add(self):
        """手动登记一条出售记录：不用先选库存商品，只写记录、不扣库存。"""
        st = self.app.store
        try:
            buyers = st.buyer_names()
            addr_map = st.buyer_address_map()
            items = st.all_records()
        except Exception:
            buyers, addr_map, items = [], {}, []
        before = len(self.rows)
        data = ask_manual_sale(self.app.root, self.fam, buyers=buyers,
                               addr_map=addr_map, items=items)
        if not data:
            return
        ok, msg = st.add_manual_sale(**data)
        if not ok:
            messagebox.showerror("手动登记出售", msg, parent=self.app.root)
            return
        self.refresh_rows()
        try:
            self.app._on_sale_changed()
        except Exception:
            pass
        if len(self.rows) <= before:
            # 新记录被当前日期/品牌/关键词筛选挡住了，提示一下
            msg += "（当前筛选条件下不显示，点「重置」即可看到）"
        self._status(msg)

    def change_type(self):
        """修改选中出库记录的类型（例：出库去维修 → 修好后卖掉）。

        只改类型与金额口径，不动库存（这笔出库当初已经扣过一次）。
        """
        rows = self._selected_rows()
        if not rows:
            r = self._focused_row()
            rows = [r] if r else []
        if not rows:
            self._status("请先选中要修改类型的记录")
            return
        st = self.app.store
        try:
            buyers = st.buyer_names()
            addr_map = st.buyer_address_map()
        except Exception:
            buyers, addr_map = [], {}
        data = ask_out_type(self.app.root, rows, self.fam,
                            buyers=buyers, addr_map=addr_map)
        if not data:
            return
        if data.get("batch"):
            n, msg = st.update_sale_types([r["id"] for r in rows], data["out_type"])
            if n <= 0:
                messagebox.showerror("修改出库类型", msg, parent=self.app.root)
                return
        else:
            ok, msg = st.update_sale_type(rows[0]["id"], data["out_type"],
                                          data["price"], data["buyer"],
                                          data["address"], remark=data["remark"],
                                          sale_date=data["sale_date"])
            if not ok:
                messagebox.showerror("修改出库类型", msg, parent=self.app.root)
                return
        self.app.load_data()
        self.app._on_sale_changed()
        self._status(msg)

    def undo_selected(self):
        label = "出库" if self.is_out else "出售"
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("撤销" + label,
                                "请先在列表中选择要撤销的%s记录。" % label,
                                parent=self.app.root)
            return
        # 手动补录的记录不关联库存，撤销不会加回任何数量
        manual = [i for i in sel if not (self._by_id.get(str(i)) or {}).get("item_id")]
        all_manual = len(manual) == len(sel)
        if all_manual:
            tip = ("这些是手动补录的记录，不关联库存，撤销只删除记录（不可恢复）。")
        else:
            tip = "数量会加回对应商品的库存（记录被删除，不可恢复）。"
            if manual:
                tip += "\n其中 %d 笔是手动补录记录，不涉及库存。" % len(manual)
        if not messagebox.askyesno(
                "撤销" + label,
                "撤销选中的 %d 笔%s记录？\n\n%s" % (len(sel), label, tip),
                parent=self.app.root, icon="warning"):
            return
        n = 0
        for iid in sel:
            ok, _ = self.app.store.delete_sale(int(iid))
            n += 1 if ok else 0
        self.refresh_rows()
        self.app.load_data()
        self.app._status("已撤销 %d 笔%s%s" % (n, label,
                                              "（手动补录，库存不变）" if all_manual
                                              else "，数量已加回库存"))

    def export(self):
        if not self.rows:
            messagebox.showinfo("导出出库记录" if self.is_out else "导出出售记录",
                                "当前筛选范围内没有%s记录。"
                                % ("出库" if self.is_out else "出售"),
                                parent=self.app.root)
            return
        if self.is_out:
            from .xlsxio import export_out_xlsx as _do_export
        else:
            from .xlsxio import export_sales_xlsx as _do_export
        try:
            wh = self.app.cur_wh()["name"]
        except Exception:
            wh = ""
        if not (self.var_start.get().strip() or self.var_end.get().strip()):
            scope = "全部"
        else:
            scope = "%s~%s" % (self.var_start.get().strip() or "开始",
                               self.var_end.get().strip() or "至今")
        label = "出库记录" if self.is_out else "出售记录"
        path = filedialog.asksaveasfilename(
            title="导出" + label, parent=self.app.root, defaultextension=".xlsx",
            initialfile="%s_%s_%s.xlsx" % (label, wh, scope.replace("~", "_至_")),
            filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            _do_export(path, self.rows, "%s · 范围：%s" % (wh, scope))
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self.app.root)
            return
        if messagebox.askyesno("导出完成", "已导出 %d 笔%s记录到：\n%s\n\n是否打开所在文件夹？"
                                           % (len(self.rows), label, path),
                               parent=self.app.root):
            try:
                os.startfile(os.path.dirname(path))
            except Exception:
                pass
