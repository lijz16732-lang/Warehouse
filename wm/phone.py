# -*- coding: utf-8 -*-
"""「手机数据」页（v1.18.0）：手机 App 同步上来的独立数据区。

· 手机同步的记录存 phone_items / phone_sales，不进主库存；
· 本页查看 / 搜索 / 删除 / 清空，可手动「转入库存」（生成电脑编号追加到主库存），
  也可一键导出 Excel（手机库存 + 手机出售记录 两个工作表）。
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_MUTED,
                        CLR_TEXT)
from .theme import RowHover

# (key, 标题, 宽度)
PHONE_ITEM_COLS = (
    ("code", "手机编号", 95), ("brand", "品牌", 110), ("category", "品类", 90),
    ("model", "型号", 150), ("condition", "成色", 70), ("qty", "数量", 60),
    ("price", "单价", 80), ("shelf", "货架", 90), ("remark", "备注", 130),
    ("state", "状态", 90), ("synced_at", "同步时间", 135),
)
PHONE_SALE_COLS = (
    ("sale_date", "日期", 130), ("code", "手机编号", 95), ("brand", "品牌", 100),
    ("category", "品类", 90), ("model", "型号", 140), ("qty", "数量", 55),
    ("price", "单价", 75), ("total", "合计", 85), ("buyer", "买家", 90),
    ("out_type", "类型", 65), ("remark", "备注", 150),
)
_LEFT = ("brand", "model", "remark", "shelf", "buyer")


class PhoneTab(ttk.Frame):
    """主窗口「手机数据」页签：手机库存 + 手机出售记录。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.item_rows = []
        self.sale_rows = []
        self._by_id = {}          # 各表格 iid → 记录
        self._kw_debounce = None
        self._build()

    # ------------------------------------------------------------ UI
    def _build(self):
        bar = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x")
        tk.Label(bar, text="手机数据", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left", padx=(16, 10), pady=12)
        self.lbl_wh = tk.Label(bar, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                               font=(self.fam, 9))
        self.lbl_wh.pack(side="left", pady=12)
        tk.Label(bar, text="手机 App 同步上来的数据单独放在这里，不影响主库存",
                 bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(10, 0), pady=12)
        ttk.Button(bar, text="导出 Excel", style="Accent.TButton",
                   command=self.export).pack(side="right", padx=(8, 16), pady=8)
        ttk.Button(bar, text="刷新", command=self.refresh_tab).pack(side="right", pady=8)
        ttk.Button(bar, text="清空手机数据", style="Danger.TButton",
                   command=self.clear_all).pack(side="right", padx=(0, 8), pady=8)
        ttk.Button(bar, text="删除选中", style="Danger.TButton",
                   command=self.delete_selected).pack(side="right", padx=(0, 8), pady=8)
        ttk.Button(bar, text="转入库存", style="Ok.TButton",
                   command=self.transfer_selected).pack(side="right", padx=(0, 8), pady=8)

        # 搜索条
        flt = tk.Frame(self, bg=CLR_BG)
        flt.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(flt, text="搜索", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_kw = tk.StringVar()
        e = ttk.Entry(flt, textvariable=self.var_kw, width=24, font=(self.fam, 10))
        e.pack(side="left", padx=(4, 0), ipady=2)
        e.bind("<KeyRelease>", self._debounce)
        ttk.Button(flt, text="重置", style="Ghost.TButton", width=6,
                   command=self.reset_filters).pack(side="left", padx=10)
        self.lbl_summary = tk.Label(flt, text="", bg=CLR_BG, fg=CLR_MUTED,
                                    font=(self.fam, 9))
        self.lbl_summary.pack(side="left", padx=(10, 0))

        # 子页签：手机库存 / 手机出售记录
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(8, 0))
        self.frm_items = ttk.Frame(self.nb)
        self.frm_sales = ttk.Frame(self.nb)
        self.nb.add(self.frm_items, text="  手机库存  ")
        self.nb.add(self.frm_sales, text="  手机出售记录  ")
        self.tree_items = self._make_tree(self.frm_items, PHONE_ITEM_COLS)
        self.tree_sales = self._make_tree(self.frm_sales, PHONE_SALE_COLS)

    def _make_tree(self, parent, cols_def):
        wrap = tk.Frame(parent, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=0, pady=10)
        cols = [c[0] for c in cols_def]
        tree = ttk.Treeview(wrap, columns=cols, show="headings",
                            selectmode="extended")
        vs = ttk.Scrollbar(wrap, orient="vertical", style="Vertical.TScrollbar",
                           command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        for key, title, w in cols_def:
            tree.heading(key, text=title)
            tree.column(key, width=w,
                        anchor="w" if key in _LEFT else "center",
                        stretch=(key in ("model", "remark", "brand")))
        # 滚动条先占位（pack 顺序坑：expand 的表格先 pack 会把滚动条挤掉）
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        tree.tag_configure("done", background="#F0F7F0")   # 已转入：淡绿底
        tree.tag_configure("odd", background="#F7FAFD")
        RowHover(tree, self.app.root)
        tree.bind("<Delete>", lambda e: self.delete_selected())
        return tree

    # ------------------------------------------------------------ 数据
    def _store(self):
        return self.app.store

    def refresh_tab(self):
        """切入本页 / 手机同步后调用。"""
        try:
            self.lbl_wh.configure(text="当前仓库：%s" % self.app.cur_wh()["name"])
        except Exception:
            pass
        self.refresh_rows()

    def refresh_rows(self):
        kw = self.var_kw.get().strip()
        try:
            self.item_rows = self._store().m_items(kw)
            self.sale_rows = self._store().m_sales(kw)
        except Exception as e:
            self.item_rows, self.sale_rows = [], []
            self.lbl_summary.configure(text="读取失败：%s" % e)
            return
        self._fill(self.tree_items, self.item_rows, PHONE_ITEM_COLS, self._item_state)
        self._fill(self.tree_sales, self.sale_rows, PHONE_SALE_COLS)
        self.lbl_summary.configure(text="库存 %d 条 · 出售记录 %d 条"
                                   % (len(self.item_rows), len(self.sale_rows)))

    @staticmethod
    def _item_state(r):
        return "已转入库存" if r.get("transferred") else "待转入"

    def _fill(self, tree, rows, cols_def, extra=None):
        tree.delete(*tree.get_children())
        self._by_id = {}
        for i, r in enumerate(rows):
            vals = []
            for key, _t, _w in cols_def:
                if extra and key == "state":
                    vals.append(extra(r))
                elif key == "qty":
                    vals.append("%d" % int(r.get(key) or 0))
                elif key in ("price", "total"):
                    vals.append("%.2f" % float(r.get(key) or 0))
                else:
                    vals.append("" if r.get(key) is None else str(r.get(key)))
            tags = []
            if extra and r.get("transferred"):
                tags.append("done")
            if i % 2 == 1:
                tags.append("odd")
            iid = tree.insert("", "end", values=vals, tags=tags)
            self._by_id[iid] = r

    def _debounce(self, _ev=None):
        if self._kw_debounce is not None:
            self.after_cancel(self._kw_debounce)
        self._kw_debounce = self.after(280, self.refresh_rows)

    def reset_filters(self):
        self.var_kw.set("")
        self.refresh_rows()

    # ------------------------------------------------------------ 动作
    def _sel_lids(self, tree):
        out = []
        for iid in tree.selection():
            r = self._by_id.get(iid)
            if r:
                out.append(int(r.get("lid") or 0))
        return [x for x in out if x > 0]

    def transfer_selected(self):
        lids = self._sel_lids(self.tree_items)
        if not lids:
            messagebox.showinfo("转入库存", "请先在「手机库存」里勾选要转入的记录。",
                                parent=self.root())
            return
        todo = [r for r in self.item_rows
                if int(r.get("lid") or 0) in lids and not r.get("transferred")]
        if not todo:
            messagebox.showinfo("转入库存", "选中的记录都已转入过主库存。",
                                parent=self.root())
            return
        if not messagebox.askyesno(
                "转入库存",
                "把选中的 %d 条手机记录转入主库存？\n\n"
                "· 会按电脑编号规则生成新编号（接着最大号排）\n"
                "· 原记录保留在手机数据里并标记「已转入」\n"
                "· 不影响主库存里已有的任何数据" % len(todo),
                parent=self.root()):
            return
        try:
            n, codes = self._store().m_transfer([int(r["lid"]) for r in todo])
        except Exception as e:
            messagebox.showerror("转入失败", str(e), parent=self.root())
            return
        self.refresh_rows()
        try:
            self.app.refresh_rows()
        except Exception:
            pass
        self._status("已转入 %d 条到主库存：%s" % (n, "、".join(codes[:5])
                                              + ("…" if len(codes) > 5 else "")))

    def delete_selected(self):
        tree = self.tree_items if self.nb.index(self.nb.select()) == 0 else self.tree_sales
        lids = self._sel_lids(tree)
        if not lids:
            messagebox.showinfo("删除", "请先选中要删除的行。", parent=self.root())
            return
        if not messagebox.askyesno(
                "删除手机数据",
                "删除选中的 %d 条手机数据？\n\n只删电脑上的手机数据副本，"
                "手机上的记录和主库存都不受影响。" % len(lids),
                parent=self.root()):
            return
        try:
            if tree is self.tree_items:
                for lid in lids:
                    self._store().m_del_item(lid)
            else:
                for lid in lids:
                    self._store().m_del_sale(lid)
        except Exception as e:
            messagebox.showerror("删除失败", str(e), parent=self.root())
            return
        self.refresh_rows()
        self._status("已删除 %d 条手机数据" % len(lids))

    def clear_all(self):
        if not self.item_rows and not self.sale_rows:
            messagebox.showinfo("清空手机数据", "当前没有手机数据。", parent=self.root())
            return
        if not messagebox.askyesno(
                "清空手机数据",
                "清空电脑上的全部手机数据（库存 %d 条 + 出售记录 %d 条）？\n\n"
                "· 只清电脑上的手机数据副本，主库存不受影响\n"
                "· 手机上的数据不受影响（但如果手机再次同步，会重新上传）"
                % (len(self.item_rows), len(self.sale_rows)),
                parent=self.root()):
            return
        try:
            self._store().m_clear()
        except Exception as e:
            messagebox.showerror("清空失败", str(e), parent=self.root())
            return
        self.refresh_rows()
        self._status("手机数据已清空")

    def export(self):
        if not self.item_rows and not self.sale_rows:
            messagebox.showinfo("无数据", "当前没有可导出的手机数据。", parent=self.root())
            return
        from . import xlsxio
        from datetime import datetime
        default = "手机数据_%s.xlsx" % datetime.now().strftime("%Y%m%d_%H%M")
        path = filedialog.asksaveasfilename(
            title="导出手机数据", parent=self.root(), defaultextension=".xlsx",
            initialfile=default, filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            xlsxio.export_phone_xlsx(path, self.item_rows, self.sale_rows)
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self.root())
            return
        self._status("已导出手机数据到 %s" % os.path.basename(path))
        if messagebox.askyesno("导出完成",
                               "已导出到：\n%s\n\n是否打开所在文件夹？" % path,
                               parent=self.root()):
            try:
                self.app._open_folder(os.path.dirname(path))
            except Exception:
                pass

    # ------------------------------------------------------------ 小工具
    def root(self):
        return self.app.root

    def _status(self, text):
        try:
            self.app._status(text)
        except Exception:
            pass
