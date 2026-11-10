# -*- coding: utf-8 -*-
"""客户管理（v1.32.0）：客户档案 + 按出售记录汇总的累计消费。

客户与出售记录按「姓名」对应（历史数据里 buyer 就是名字），
所以不用迁移老数据：新建一个同名客户，历史成交立刻统计进来。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_MUTED,
                        CLR_TEXT, CLR_WARN, apply_window_icon, center_window)

COLS = [("name", "客户", 130, "w"), ("phone", "电话", 120, "center"),
        ("level", "级别", 66, "center"), ("count", "成交笔数", 78, "center"),
        ("qty", "累计件数", 78, "center"), ("amount", "累计消费(元)", 110, "e"),
        ("last", "最近成交", 96, "center"), ("address", "地址", 170, "w"),
        ("note", "备注", 150, "w")]

LEVELS = ["", "普通", "VIP", "金牌", "同行", "待开发"]


class CustomerDialog(tk.Toplevel):
    """新增 / 编辑客户。result 为 dict 或 None。"""

    def __init__(self, master, rec=None, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.result = None
        self.fam = fam
        self.is_new = rec is None
        r = rec or {}
        self.title("新增客户" if self.is_new else "编辑客户")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        self.vars = {}
        body = tk.Frame(self, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)
        body.columnconfigure(1, weight=1)
        rows = [("name", "客户名称 *"), ("phone", "电话"),
                ("level", "级别"), ("address", "地址"), ("note", "备注")]
        for i, (key, label) in enumerate(rows):
            tk.Label(body, text=label, bg=CLR_BG, fg="#41506B",
                     font=(self.fam, 10), anchor="w").grid(
                row=i, column=0, sticky="w", padx=(0, 10), pady=6)
            v = tk.StringVar(value=str(r.get(key) or ""))
            self.vars[key] = v
            if key == "level":
                cb = ttk.Combobox(body, textvariable=v, values=LEVELS,
                                  width=22, font=(self.fam, 10))
                cb.grid(row=i, column=1, sticky="w", pady=6)
            else:
                ttk.Entry(body, textvariable=v, width=26,
                          font=(self.fam, 10)).grid(row=i, column=1,
                                                    sticky="ew", pady=6)
        self.msg = tk.Label(self, text="", bg=CLR_BG, fg=CLR_WARN,
                            font=(self.fam, 9), anchor="w")
        self.msg.pack(fill="x", padx=18)

        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="保存", style="Accent.TButton", width=10,
                   command=self._ok).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10,
                   command=self._cancel).pack(side="right", pady=12)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    def _ok(self):
        name = self.vars["name"].get().strip()
        if not name:
            self.msg.configure(text="⚠ 客户名称不能为空")
            return
        self.result = {k: v.get().strip() for k, v in self.vars.items()}
        self.result["id"] = None
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_customer(master, rec=None, fam="Microsoft YaHei UI"):
    dlg = CustomerDialog(master, rec, fam)
    master.wait_window(dlg)
    return dlg.result


class CustomerTab(ttk.Frame):
    """客户列表页。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.rows = []
        self._by_id = {}
        self._build()

    # ------------------------------------------------------------ UI
    def _build(self):
        bar = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x")
        tk.Label(bar, text="客户管理", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left",
                                                   padx=(16, 10), pady=12)
        self.lbl_wh = tk.Label(bar, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                               font=(self.fam, 9))
        self.lbl_wh.pack(side="left", pady=12)
        tk.Label(bar, text="按客户姓名对应出售记录，累计消费实时统计",
                 bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(10, 0), pady=12)

        ttk.Button(bar, text="+ 新增客户", style="Accent.TButton",
                   command=self.add_customer).pack(side="right",
                                                   padx=(8, 16), pady=8)
        ttk.Button(bar, text="从出售记录导入", style="Ghost.TButton",
                   command=self.import_buyers).pack(side="right", pady=8)
        ttk.Button(bar, text="刷新", command=self.refresh_tab).pack(
            side="right", padx=(0, 8), pady=8)

        flt = tk.Frame(self, bg=CLR_BG)
        flt.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(flt, text="搜索", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        self.var_kw = tk.StringVar()
        e = tk.Entry(flt, textvariable=self.var_kw, width=22,
                     font=(self.fam, 10), relief="solid", bd=1)
        e.pack(side="left", padx=(4, 10), ipady=2)
        e.bind("<KeyRelease>", lambda ev: self._debounce())
        ttk.Button(flt, text="重置", style="Ghost.TButton", width=6,
                   command=self.reset_kw).pack(side="left")
        self._job = None

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
                             anchor=anchor, stretch=(key in ("address", "note")))
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("odd", background="#F7FAFD")
        self.tree.tag_configure("vip", foreground=CLR_ACCENT)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 10))
        self.lbl_hint = tk.Label(foot, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=(self.fam, 9))
        self.lbl_hint.pack(side="left")
        ttk.Button(foot, text="删除选中", style="Danger.TButton",
                   command=self.delete_selected).pack(side="right")
        ttk.Button(foot, text="编辑", style="Ghost.TButton", width=6,
                   command=self.edit_selected).pack(side="right", padx=(0, 8))

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
                self.root.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(260, self.refresh_rows)

    def reset_kw(self):
        self.var_kw.set("")
        self.refresh_rows()

    def refresh_rows(self):
        try:
            self.rows = self.app.store.list_customers(self.var_kw.get())
        except Exception as e:
            self.rows = []
            self.lbl_hint.configure(text="读取客户失败：%s" % e)
            return
        self.tree.delete(*self.tree.get_children())
        self._by_id = {}
        for i, r in enumerate(self.rows):
            iid = str(r["id"])
            self._by_id[iid] = r
            tags = []
            if i % 2:
                tags.append("odd")
            if (r.get("level") or "") in ("VIP", "金牌"):
                tags.append("vip")
            self.tree.insert("", "end", iid=iid, tags=tuple(tags), values=(
                r["name"], r["phone"], r["level"], str(r["count"]),
                str(r["qty"]), "%.2f" % r["amount"], r["last"],
                r["address"], r["note"]))
        total = sum(r["amount"] for r in self.rows)
        self.lbl_hint.configure(
            text="共 %d 个客户 · 累计消费合计 %.2f 元 · 双击可编辑"
                 % (len(self.rows), total))

    # ------------------------------------------------------------ 操作
    def add_customer(self):
        if self._guard():
            return
        out = ask_customer(self.app.root, None, self.fam)
        if not out:
            return
        ok, msg = self.app.store.add_customer(
            out["name"], out.get("phone"), out.get("address"),
            out.get("level"), out.get("note"))
        if not ok:
            messagebox.showwarning("新增客户", msg, parent=self.app.root)
            return
        self.app.load_data()          # 顶部统计跟着变
        self.refresh_rows()
        self.app._status(msg)

    def edit_selected(self):
        if self._guard():
            return
        sel = self.tree.selection()
        if len(sel) != 1:
            self.lbl_hint.configure(text="请先选中一个客户再编辑")
            return
        rec = self._by_id.get(str(sel[0]))
        if rec is None:
            return
        out = ask_customer(self.app.root, rec, self.fam)
        if not out:
            return
        ok, msg = self.app.store.update_customer(
            rec["id"], out["name"], out.get("phone"), out.get("address"),
            out.get("level"), out.get("note"))
        if not ok:
            messagebox.showwarning("保存客户", msg, parent=self.app.root)
            return
        self.refresh_rows()
        self.app._status("已保存客户：%s" % out["name"])

    def delete_selected(self):
        if self._guard():
            return
        sel = self.tree.selection()
        if not sel:
            self.lbl_hint.configure(text="请先选中要删除的客户")
            return
        names = "、".join(self._by_id[str(i)]["name"] for i in sel[:3])
        if not messagebox.askyesno(
                "确认删除",
                "确定删除 %d 个客户吗？\n\n%s%s\n\n"
                "只删客户档案，历史出售记录不受影响。"
                % (len(sel), names, "…" if len(sel) > 3 else ""),
                parent=self.app.root):
            return
        n = sum(self.app.store.delete_customer(int(i)) for i in sel)
        self.refresh_rows()
        self.app._status("已删除 %d 个客户" % n)

    def import_buyers(self):
        if self._guard():
            return
        try:
            n = self.app.store.import_buyers()
        except Exception as e:
            messagebox.showerror("导入客户", "导入失败：\n%s" % e,
                                 parent=self.app.root)
            return
        self.refresh_rows()
        if n:
            self.app._status("已从出售记录导入 %d 个客户" % n)
        else:
            messagebox.showinfo("导入客户",
                                "没有新的买家可导入（已存在的都跳过了）。",
                                parent=self.app.root)

    def _guard(self):
        """只读模式下拦下写操作。"""
        try:
            return bool(self.app._guard_write())
        except Exception:
            return False
