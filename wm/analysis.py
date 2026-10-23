# -*- coding: utf-8 -*-
"""数据分析页：KPI 指标 + 多维度图表 + 统计报表导出。"""

import tkinter as tk
from tkinter import ttk

from .charts import DonutChart, HBarChart, KpiCard, ScrollFrame, VBarChart
from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_CYAN,
                        CLR_MUTED, CLR_OK, CLR_PURPLE, CLR_TEXT, CLR_WARN)


def money(v):
    v = float(v or 0)
    if abs(v) >= 1e8:
        return "%.2f亿" % (v / 1e8)
    if abs(v) >= 1e4:
        return "%.2f万" % (v / 1e4)
    return "%.2f" % v


def num(v):
    return "{:,}".format(int(v or 0))


class AnalysisTab(ttk.Frame):

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self._scope = tk.StringVar(value="filtered")
        self._build()
        self._last_scope = None

    # ------------------------------------------------------------ UI
    def _build(self):
        bar = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        bar.pack(fill="x")

        tk.Label(bar, text="数据分析", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left", padx=(16, 10), pady=12)

        self.lbl_wh = tk.Label(bar, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                               font=(self.fam, 9))
        self.lbl_wh.pack(side="left", pady=12)

        for text, val in (("当前筛选结果", "filtered"), ("全部数据", "all")):
            ttk.Radiobutton(bar, text=text, value=val, variable=self._scope,
                            style="Card.TRadiobutton", command=self.refresh,
                            takefocus=False).pack(side="left", padx=(0, 14))

        ttk.Button(bar, text="导出统计报表", style="Accent.TButton",
                   command=self.app.export_stats).pack(side="right", padx=(8, 16), pady=8)
        ttk.Button(bar, text="刷新", command=self.refresh).pack(side="right", pady=8)

        self.scroll = ScrollFrame(self, bg=CLR_BG)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.body

        # ---- KPI ----
        self.kpi_wrap = tk.Frame(body, bg=CLR_BG)
        self.kpi_wrap.pack(fill="x", padx=14, pady=(14, 0))
        for i in range(5):
            self.kpi_wrap.columnconfigure(i, weight=1, uniform="kpi")

        self.kpi = {
            "total": KpiCard(self.kpi_wrap, "记录数 / SKU", "0", "0 个品牌",
                             CLR_ACCENT),
            "qty": KpiCard(self.kpi_wrap, "库存总数量", "0", "件", CLR_CYAN),
            "value": KpiCard(self.kpi_wrap, "库存总价值", "¥0", "按 价格×数量 估算",
                             CLR_PURPLE),
            "listed": KpiCard(self.kpi_wrap, "上架率", "0%", "0 / 0 已上架",
                              CLR_OK, show_bar=True),
            "avg": KpiCard(self.kpi_wrap, "平均价格", "¥0", "0 个有效报价",
                           CLR_WARN),
        }
        for i, key in enumerate(["total", "qty", "value", "listed", "avg"]):
            card = self.kpi[key]
            card.set_font_family(self.fam)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))

        # ---- 图表 ----
        grid = tk.Frame(body, bg=CLR_BG)
        grid.pack(fill="both", expand=True, padx=14, pady=14)
        grid.columnconfigure(0, weight=1, uniform="ch")
        grid.columnconfigure(1, weight=1, uniform="ch")

        def card_chart(r, c, cls, title, height, **kw):
            card = tk.Frame(grid, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                            highlightthickness=1)
            card.grid(row=r, column=c, sticky="nsew",
                      padx=(0 if c == 0 else 12, 0), pady=(0 if r == 0 else 12, 0))
            ch = cls(card, title, height=height, **kw)
            ch.set_font_family(self.fam)
            ch.pack(fill="both", expand=True)
            return ch

        self.c_brand = card_chart(0, 0, HBarChart, "品牌分布 TOP10", 264, show_pct=True)
        self.c_cat = card_chart(0, 1, DonutChart, "品类占比", 264)
        self.c_cond = card_chart(1, 0, HBarChart, "成色分布", 250, show_pct=True)
        self.c_price = card_chart(1, 1, VBarChart, "价格区间分布（元）", 250)
        self.c_shelf = card_chart(2, 0, HBarChart, "货架占用 TOP10", 250)
        self.c_listed = card_chart(2, 1, DonutChart, "上架 / 未上架", 250)

    # ------------------------------------------------------------ 数据
    def refresh(self):
        records = self.app.records_for_analysis(self._scope.get())
        stats = self.app.store.stats(records)
        scope = "当前筛选结果" if self._scope.get() == "filtered" else "全部数据"
        self._last_scope = scope
        try:
            self.lbl_wh.configure(text=" 当前仓库：%s " % self.app.cur_wh()["name"])
        except Exception:
            pass

        self.kpi["total"].update_value(
            num(stats["total"]),
            "%d 品牌 · %d 品类" % (stats["brand_count"], stats["category_count"]))
        self.kpi["qty"].update_value(num(stats["total_qty"]), "件商品在库")
        self.kpi["value"].update_value("¥" + money(stats["total_value"]),
                                       "最高单价 ¥" + money(stats["max_price"]))
        self.kpi["listed"].update_value(
            "%.1f%%" % stats["listed_rate"],
            "%s / %s 已上架" % (num(stats["listed"]), num(stats["total"])),
            pct=stats["listed_rate"],
            color=CLR_OK if stats["listed_rate"] >= 50 else CLR_WARN)
        self.kpi["avg"].update_value("¥" + money(stats["avg_price"]),
                                     "最低 ¥" + money(stats["min_price"]))

        self.c_brand.set_data([(k, v) for k, v, _ in stats["brands"]],
                              subtitle="共 %d 个品牌" % stats["brand_count"])
        self.c_cat.set_data([(k, v) for k, v, _ in stats["categories"]],
                            subtitle="共 %d 个品类" % stats["category_count"])
        self.c_cond.set_data([(k, v) for k, v, _ in stats["conditions"]])
        self.c_price.set_data(stats["price_dist"])
        self.c_shelf.set_data([(k, v) for k, v, _ in stats["shelves"]],
                              subtitle="共 %d 个货架" % stats["shelf_count"])
        self.c_listed.set_data([("已上架", stats["listed"]), ("未上架", stats["unlisted"])])
        return stats

    @property
    def scope_text(self):
        return self._last_scope or "全部数据"
