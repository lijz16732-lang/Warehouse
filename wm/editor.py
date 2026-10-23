# -*- coding: utf-8 -*-
"""新增 / 编辑记录弹窗。"""

import tkinter as tk
from tkinter import ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_DANGER,
                        CLR_MUTED, CLR_OK, CLR_TEXT, EDIT_ROWS, FIELD_LABEL,
                        FIELD_TYPE, LISTED_TEXT, apply_window_icon, center_window)

LISTED_OPTIONS = ["已上架", "未上架"]


class RecordDialog(tk.Toplevel):
    """模态编辑窗口。result 为 dict 或 None。"""

    def __init__(self, master, record=None, suggestions=None, title="编辑记录", fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.result = None
        self.fam = fam
        self.suggestions = suggestions or {}
        self.is_new = record is None
        rec = record or {}

        self.title(title)
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        self.vars = {}
        self._build(rec)
        self._center(master)

        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Control-Return>", lambda e: self._save())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.focus_force()

    # ------------------------------------------------------------ UI
    def _build(self, rec):
        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        head.pack(fill="x")
        tk.Label(head, text=("新增记录" if self.is_new else "编辑记录"), bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left", padx=16, pady=12)
        tk.Label(head, text="带 * 为建议填写项 · Ctrl+Enter 保存", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="right", padx=16)

        body = tk.Frame(self, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        self.text_widgets = {}
        body.columnconfigure(0, weight=0, minsize=62)
        body.columnconfigure(1, weight=1, minsize=215)
        body.columnconfigure(2, weight=0, minsize=62)
        body.columnconfigure(3, weight=1, minsize=215)
        for r, row_fields in enumerate(EDIT_ROWS):
            for c, key in enumerate(row_fields):
                if key is None:
                    continue
                col = c * 2
                lab = tk.Label(body, text=FIELD_LABEL[key], bg=CLR_BG, fg="#41506B",
                               font=(self.fam, 10), anchor="w")
                lab.grid(row=r, column=col, sticky="w",
                         padx=((0 if col == 0 else 20), 8), pady=6)
                if FIELD_TYPE[key] == "bool":
                    v = tk.StringVar(value=LISTED_TEXT.get(int(rec.get(key, 0) or 0), "未上架"))
                    self.vars[key] = v
                    cb = ttk.Combobox(body, textvariable=v, values=LISTED_OPTIONS,
                                      state="readonly", width=22, font=(self.fam, 10))
                    cb.grid(row=r, column=col + 1, sticky="w", pady=6)
                elif key == "remark":
                    txt = tk.Text(body, height=3, width=1, wrap="word", relief="solid",
                                  bd=1, highlightthickness=1, bg="#FFFFFF", fg=CLR_TEXT,
                                  insertbackground=CLR_ACCENT, font=(self.fam, 10),
                                  highlightbackground=CLR_BORDER, highlightcolor=CLR_ACCENT)
                    txt.insert("1.0", str(rec.get(key, "") or ""))
                    txt.grid(row=r, column=col + 1, columnspan=3, sticky="ew", pady=6)
                    self.text_widgets[key] = txt
                else:
                    v = tk.StringVar(value=self._fmt(rec.get(key)))
                    self.vars[key] = v
                    opts = self.suggestions.get(key) or []
                    # 品牌/品类/成色/货架：可输入也可下拉选（Combobox 不设 readonly
                    # 即允许手动输入新值，历史建议作为下拉选项）
                    if key in ("brand", "category", "condition", "shelf"):
                        cb = ttk.Combobox(body, textvariable=v, values=opts, width=24,
                                          font=(self.fam, 10))
                        cb.grid(row=r, column=col + 1, sticky="ew", pady=6)
                    else:
                        ent = ttk.Entry(body, textvariable=v, width=26, font=(self.fam, 10))
                        ent.grid(row=r, column=col + 1, sticky="ew", pady=6)

        # 提示
        tip = tk.Frame(self, bg=CLR_BG)
        tip.pack(fill="x", padx=16)
        self.msg = tk.Label(tip, text="", bg=CLR_BG, fg=CLR_DANGER, font=(self.fam, 9), anchor="w")
        self.msg.pack(fill="x")

        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="保存", style="Accent.TButton", width=10,
                   command=self._save).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10, command=self._cancel).pack(side="right", pady=12)
        ttk.Button(foot, text="清空", style="Ghost.TButton",
                   command=self._clear).pack(side="left", padx=16, pady=12)

    @staticmethod
    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        return str(v)

    def _center(self, master):
        center_window(self, master)

    # ------------------------------------------------------------ 行为
    def _clear(self):
        for key, var in self.vars.items():
            if FIELD_TYPE.get(key) == "bool":
                var.set("未上架")
            else:
                var.set("")
        for txt in self.text_widgets.values():
            txt.delete("1.0", "end")
        self.msg.configure(text="")

    def _validate(self):
        price = self.vars["price"].get().strip()
        if price:
            try:
                float(price.replace(",", ""))
            except ValueError:
                return "「价格」必须为数字，例如 199.9"
        qty = self.vars["qty"].get().strip()
        if qty:
            try:
                int(float(qty.replace(",", "")))
            except ValueError:
                return "「数量」必须为整数"
        return None

    def _save(self):
        err = self._validate()
        if err:
            self.msg.configure(text="⚠ " + err)
            return
        from .xlsxio import normalize_record
        raw = {}
        for key, var in self.vars.items():
            raw[key] = var.get()
        for key, txt in self.text_widgets.items():
            raw[key] = txt.get("1.0", "end").strip()
        self.result = normalize_record(raw)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_record(master, record=None, suggestions=None, title="编辑记录", fam="Microsoft YaHei UI"):
    dlg = RecordDialog(master, record, suggestions, title, fam)
    master.wait_window(dlg)
    return dlg.result
