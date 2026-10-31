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
from .photos import PhotoStrip
from .theme import CellHover, RowHover

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
# 对齐与主库存表格一致（constants.FIELD_ANCHOR）：品牌/品类/成色/货架居中，
# 价格/数量等数字靠右，文字列靠左 —— 否则和主表格并排看会感觉「数据位置怪」
_PHONE_ANCHOR = {"code": "w", "brand": "center", "category": "center",
                 "model": "w", "condition": "center", "price": "e",
                 "qty": "e", "shelf": "center", "remark": "w",
                 "state": "center", "synced_at": "center",
                 "sale_date": "center", "total": "e", "buyer": "center",
                 "out_type": "center"}
_LEFT = ("brand", "model", "remark", "shelf", "buyer")   # 可横向拉伸的列

# 行颜色标记色板（右键 → 标记颜色）：先注册的 tag 优先级高（Treeview 规则），
# 颜色标记需盖过「已转入」淡绿和斑马纹，故在 done/odd 之前 tag_configure
_MARK_COLORS = (
    ("红", "#FADBD8"), ("橙", "#FAE5C3"), ("黄", "#FCF3CF"),
    ("绿", "#D5F5E3"), ("蓝", "#D4E6F1"), ("紫", "#E8DAEF"),
    ("灰", "#E5E7E9"),
)


class PhoneTab(ttk.Frame):
    """主窗口「手机数据」页签：手机库存 + 手机出售记录。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.item_rows = []
        self.sale_rows = []
        self._maps = {}           # tree → {iid: 记录}（两表各自独立，防覆盖）
        self._hovers = {}         # tree → RowHover（划过行高亮）
        self._cell_hovers = {}    # tree → CellHover（划过单元格"选中"高亮）
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
        self.tree_items = self._make_tree(self.frm_items, PHONE_ITEM_COLS,
                                          is_items=True)
        self.tree_sales = self._make_tree(self.frm_sales, PHONE_SALE_COLS)
        # 照片改为点表格 📷 直接弹大图查看窗（v1.26.5）：
        # 不再在页面底部嵌照片条。PhotoStrip 仅作不显示的操作载体
        # （view / add_photos 都挂在它上面，不 pack 不占版面）
        self.photo_strip = PhotoStrip(self.frm_items, self.app, kind="phone")
        self.tree_items.bind("<Button-1>", self._on_items_click, add="+")

    def _on_items_click(self, ev):
        """手机库存表：点 📷 指示列 → 直接打开该记录的照片查看窗。"""
        tree = self.tree_items
        try:
            if tree.identify_region(ev.x, ev.y) != "cell":
                return
            cidx = int(str(tree.identify_column(ev.x)).replace("#", "")) - 1
        except (TypeError, ValueError):
            return
        if cidx != len(PHONE_ITEM_COLS):      # 📷 列在所有数据列之后
            return
        row = tree.identify_row(ev.y)
        rec = (self._maps.get(tree) or {}).get(str(row))
        code = (rec or {}).get("code")
        if not code:
            return
        try:
            names = list(self._store().photos_list("phone", code) or [])
        except Exception:
            names = []
        self.photo_strip.set_code(code)
        if names:
            self.photo_strip.view(names[0])
        else:
            # 暂无照片：直接进入添加流程（与库存页能力一致）
            self.app._status("「%s」暂无照片：可直接选择图片添加" % code)
            self.photo_strip.add_photos()

    def _make_tree(self, parent, cols_def, is_items=False):
        wrap = tk.Frame(parent, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=0, pady=10)
        cols = [c[0] for c in cols_def]
        if is_items:
            cols = cols + ["_photos"]      # 末尾：照片指示列（📷）
        tree = ttk.Treeview(wrap, columns=cols, show="headings",
                            selectmode="extended")
        vs = ttk.Scrollbar(wrap, orient="vertical", style="Vertical.TScrollbar",
                           command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        for key, title, w in cols_def:
            anc = _PHONE_ANCHOR.get(key, "center")
            tree.heading(key, text=title, anchor=anc)
            tree.column(key, width=w, anchor=anc,
                        stretch=(key in ("model", "remark", "brand")))
        if is_items:
            tree.heading("_photos", text="📷")
            tree.column("_photos", width=42, minwidth=36, anchor="center",
                        stretch=False)
        # 滚动条先占位（pack 顺序坑：expand 的表格先 pack 会把滚动条挤掉）
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        for _name, _hex in _MARK_COLORS:     # 颜色标记优先级最高
            tree.tag_configure("mark_%s" % _hex.lstrip("#"),
                               background=_hex)
        tree.tag_configure("done", background="#F0F7F0")   # 已转入：淡绿底
        tree.tag_configure("odd", background="#F7FAFD")
        self._hovers[tree] = RowHover(tree, self.app.root)
        self._cell_hovers[tree] = CellHover(tree)   # 划过单元格"选中"式高亮
        tree.bind("<Delete>", lambda e: self.delete_selected())
        # 划过高亮行上 Ctrl+C：复制鼠标所指单元格（不在表格上则复制选中行）
        tree.bind("<Control-c>", lambda e, t=tree: self._copy_hover(t))
        # 右键菜单：复制 / 删除选中 / 转入库存（仅手机库存表）
        menu = tk.Menu(tree, tearoff=0)
        menu.add_command(label="复制此格",
                         command=lambda t=tree: self._copy_menu_cell(t))
        menu.add_command(label="复制整行",
                         command=lambda t=tree: self._copy_menu_row(t))
        menu.add_separator()
        menu.add_command(label="删除选中", command=self.delete_selected)
        if is_items:
            menu.add_command(label="转入库存", command=self.transfer_selected)
        if is_items:
            mkind = "item"
        else:
            mkind = "sale"
        cmenu = tk.Menu(menu, tearoff=0)
        for _name, _hex in _MARK_COLORS:
            cmenu.add_command(
                label=_name, command=lambda h=_hex, k=mkind, t=tree:
                self.mark_color(t, k, h))
        cmenu.add_separator()
        cmenu.add_command(
            label="自定义颜色…", command=lambda k=mkind, t=tree:
            self.mark_color(t, k, None))
        cmenu.add_command(
            label="取消标记", command=lambda k=mkind, t=tree:
            self.mark_color(t, k, ""))
        menu.add_cascade(label="标记颜色", menu=cmenu)
        menu.add_command(label="刷新", command=self.refresh_rows)

        def _popup(ev):
            tree._rb_x, tree._rb_y = ev.x, ev.y   # 右键位置（复制此格用）
            # 空白处右键也弹菜单（此时保留原有选中，不动选择）
            iid = tree.identify_row(ev.y)
            if iid and iid not in tree.selection():
                tree.selection_set(iid)      # 右键落在未选中的行：改为只选该行
                tree.focus(iid)
            try:
                # 没有选中行时「删除选中/转入库存」灰掉，避免点了才提示
                has_sel = bool(tree.selection())
                for _i in range(menu.index("end") + 1):
                    if (menu.type(_i) == "command"
                            and menu.entrycget(_i, "label") in ("删除选中", "转入库存")):
                        menu.entryconfigure(
                            _i, state="normal" if has_sel else "disabled")
                menu.tk_popup(ev.x_root, ev.y_root)
            finally:
                menu.grab_release()
            return "break"

        tree.bind("<Button-3>", _popup)
        if is_items:
            self._ctx_items = menu
        else:
            self._ctx_sales = menu
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
        self._fill(self.tree_items, self.item_rows, PHONE_ITEM_COLS,
                   self._item_state,
                   photo_codes=self._store().photo_codes("phone"),
                   kind="item")
        self._fill(self.tree_sales, self.sale_rows, PHONE_SALE_COLS,
                   kind="sale")
        self.lbl_summary.configure(text="库存 %d 条 · 出售记录 %d 条"
                                   % (len(self.item_rows), len(self.sale_rows)))

    @staticmethod
    def _item_state(r):
        return "已转入库存" if r.get("transferred") else "待转入"

    def _fill(self, tree, rows, cols_def, extra=None, photo_codes=None,
              kind=None):
        tree.delete(*tree.get_children())
        mapping = {}                       # 每个 tree 独立映射（共用会互相覆盖）
        self._maps[tree] = mapping
        colors = self._store().m_colors() if kind else {}
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
            if photo_codes is not None:
                vals.append("📷" if (r.get("code") or "") in photo_codes else "")
            tags = []
            ckey = "%s:%s" % (kind, int(r.get("lid") or 0)) if kind else ""
            cval = colors.get(ckey)
            if cval:
                tags.append("mark_%s" % cval.lstrip("#"))
            if extra and r.get("transferred"):
                tags.append("done")
            if i % 2 == 1:
                tags.append("odd")
            iid = tree.insert("", "end", values=vals, tags=tags)
            mapping[iid] = r

    def mark_color(self, tree, kind, color=None):
        """给选中行标记颜色（color=None 打开取色器；"" 取消标记）。"""
        mapping = self._maps.get(tree) or {}
        sels = tree.selection()
        if not sels:
            messagebox.showinfo("标记颜色", "请先选中要标记的行。",
                                parent=self.root())
            return
        if color is None:                  # 自定义：系统取色器
            try:
                from tkinter import colorchooser
                picked = colorchooser.askcolor(
                    color="#FCF3CF", title="选择标记颜色",
                    parent=self.root())
                color = picked[1] if picked and picked[1] else ""
            except Exception:
                color = ""
            if not color:
                return                     # 取色器被取消 → 不改动
        keys = []
        for iid in sels:
            r = mapping.get(iid)
            if r and r.get("lid"):
                keys.append("%s:%d" % (kind, int(r["lid"])))
        if not keys:
            return
        try:
            for k in keys:
                self._store().m_set_color(k, color)
        except Exception as e:
            messagebox.showerror("标记失败", str(e), parent=self.root())
            return
        self.refresh_rows()
        if color:
            self._status("已标记 %d 行颜色" % len(keys))
        else:
            self._status("已取消 %d 行的颜色标记" % len(keys))

    def _debounce(self, _ev=None):
        if self._kw_debounce is not None:
            self.after_cancel(self._kw_debounce)
        self._kw_debounce = self.after(280, self.refresh_rows)

    def reset_filters(self):
        self.var_kw.set("")
        self.refresh_rows()

    # ------------------------------------------------------------ 动作
    def _sel_lids(self, tree):
        mapping = self._maps.get(tree) or {}
        out = []
        for iid in tree.selection():
            r = mapping.get(iid)
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

    # ------------------------------------------------------------ 复制
    def _clip(self, text):
        r = self.root()
        r.clipboard_clear()
        r.clipboard_append(text)

    def _cell_text(self, tree, x, y):
        """(x, y) 处单元格文本；不在数据单元格上返回 None。"""
        try:
            if tree.identify_region(x, y) != "cell":
                return None
            row = tree.identify_row(y)
            cidx = int(str(tree.identify_column(x)).replace("#", "")) - 1
        except (TypeError, ValueError):
            return None
        if not row or cidx < 0:
            return None
        vals = tree.item(row, "values")
        if cidx >= len(vals):
            return None
        return str(vals[cidx])

    def _copy_hover(self, tree):
        """Ctrl+C：划过高亮行上 → 复制鼠标所指单元格；否则复制选中行。"""
        hv = self._hovers.get(tree)
        iid = hv.row if hv else None
        px, py = tree.winfo_pointerxy()
        x, y = px - tree.winfo_rootx(), py - tree.winfo_rooty()
        if iid and tree.identify_row(y) == iid:
            text = self._cell_text(tree, x, y)
            if text:
                self._clip(text)
                self._status("已复制：%s" % text[:60])
                return
        sels = tree.selection()
        if sels:
            lines = ["\t".join(str(v) for v in tree.item(s, "values"))
                     for s in sels]
            self._clip("\n".join(lines))
            self._status("已复制 %d 行" % len(sels))

    def _copy_menu_cell(self, tree):
        x = getattr(tree, "_rb_x", None)
        y = getattr(tree, "_rb_y", None)
        if x is None:
            return
        text = self._cell_text(tree, x, y)
        if text:
            self._clip(text)
            self._status("已复制：%s" % text[:60])

    def _copy_menu_row(self, tree):
        x = getattr(tree, "_rb_x", None)
        y = getattr(tree, "_rb_y", None)
        if x is None:
            return
        row = tree.identify_row(y) if y is not None else None
        if not row:
            sels = tree.selection()
            row = sels[0] if sels else None
        if row:
            vals = tree.item(row, "values")
            self._clip("\t".join(str(v) for v in vals))
            self._status("已复制整行")

    # ------------------------------------------------------------ 小工具
    def root(self):
        return self.app.root

    def _status(self, text):
        try:
            self.app._status(text)
        except Exception:
            pass
