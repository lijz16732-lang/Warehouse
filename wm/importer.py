# -*- coding: utf-8 -*-
"""XLSX 导入向导：工作表选择、表头行识别、字段映射预览、导入模式。"""

import os
import tkinter as tk
from tkinter import ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_DANGER,
                        CLR_MUTED, CLR_OK, CLR_TEXT, CLR_WARN, FIELD_KEYS,
                        FIELD_LABEL, FIELD_WIDTH, FIELD_TYPE, MODEL_BLANK,
                        apply_window_icon, center_window, is_blank_model, norm_model)
from .xlsxio import (detect_header_row, list_sheets, map_headers, read_xlsx,
                     rows_to_records)

MODE_APPEND = "append"
MODE_REPLACE = "replace"
MODE_MERGE = "merge"

MODE_TEXT = {
    MODE_APPEND: "追加导入",
    MODE_REPLACE: "覆盖全部",
    MODE_MERGE: "按型号合并",
}

MODE_HINT = {
    MODE_APPEND: "全部作为新记录加入，不做重复判断、不去重。",
    MODE_REPLACE: "先清空现有全部数据再导入（编号从 WL-00001 重新开始）；文件内自动去重。",
    MODE_MERGE: "与库中数据对比：型号已存在、或无型号但内容与库中完全相同 → 跳过不导入；其余才新增。",
}


class ImportDialog(tk.Toplevel):

    def __init__(self, master, path, fam="Microsoft YaHei UI", existing_models=None,
                 existing_blank=None):
        super().__init__(master)
        self.path = path
        self.fam = fam
        self.result = None
        self.headers = []
        self.rows = []
        self.mapping = {}
        self.unmapped = []
        self.records = []
        self.existing_models = existing_models or set()
        self.existing_blank = existing_blank or set()

        self.title("导入数据 - %s" % os.path.basename(path))
        self.configure(bg=CLR_BG)
        self.transient(master)
        apply_window_icon(self)
        self.minsize(880, 620)

        self.var_sheet = tk.StringVar()
        self.var_hrow = tk.IntVar(value=1)
        self.var_mode = tk.StringVar(value=MODE_MERGE)

        self._build()
        self._load_sheets()
        self._center(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda e: self._cancel())
        self.grab_set()

    # ------------------------------------------------------------ UI
    def _build(self):
        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        head.pack(fill="x")
        tk.Label(head, text="导入 XLSX 数据", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left", padx=16, pady=12)
        tk.Label(head, text=os.path.basename(self.path), bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")

        # 选项条
        opt = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        opt.pack(fill="x")
        inner = tk.Frame(opt, bg=CLR_CARD)
        inner.pack(fill="x", padx=16, pady=10)

        tk.Label(inner, text="工作表", bg=CLR_CARD, fg="#41506B",
                 font=(self.fam, 10)).pack(side="left")
        self.cb_sheet = ttk.Combobox(inner, textvariable=self.var_sheet, width=18,
                                     state="readonly", font=(self.fam, 10))
        self.cb_sheet.pack(side="left", padx=(8, 20))
        self.cb_sheet.bind("<<ComboboxSelected>>", lambda e: self._reload())

        tk.Label(inner, text="表头行", bg=CLR_CARD, fg="#41506B",
                 font=(self.fam, 10)).pack(side="left")
        self.sp_hrow = ttk.Spinbox(inner, from_=1, to=100, width=5,
                                   textvariable=self.var_hrow, font=(self.fam, 10),
                                   command=self._on_spin)
        self.sp_hrow.pack(side="left", padx=(8, 20))
        self.sp_hrow.bind("<Return>", lambda e: self._on_spin())
        self.sp_hrow.bind("<FocusOut>", lambda e: self._on_spin())

        ttk.Button(inner, text="自动识别表头", style="Ghost.TButton",
                   command=lambda: self._reload(auto=True)).pack(side="left")

        self.lbl_stat = tk.Label(inner, text="", bg=CLR_CARD, fg=CLR_ACCENT,
                                 font=(self.fam, 9, "bold"))
        self.lbl_stat.pack(side="right")

        mid = tk.Frame(self, bg=CLR_BG)
        mid.pack(fill="both", expand=True, padx=12, pady=12)

        # 左：字段映射（可手动调整）
        left = tk.Frame(mid, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        left.pack(side="left", fill="y")
        tk.Label(left, text="字段映射（可手动修改）", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        tk.Label(left, text="自动识别结果不对时，直接改下拉框即可", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 8)).pack(anchor="w", padx=14, pady=(0, 6))
        map_wrap = tk.Frame(left, bg=CLR_CARD)
        map_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.map_inner = tk.Frame(map_wrap, bg=CLR_CARD)
        self.map_inner.pack(fill="both", expand=True)
        self.field_vars = {}
        self._map_lock = False

        # 右：预览
        right = tk.Frame(mid, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(right, text="数据预览（前 8 行）", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 10, "bold")).pack(anchor="w", padx=14, pady=(12, 6))

        wrap = tk.Frame(right, bg=CLR_CARD)
        wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.preview = ttk.Treeview(wrap, show="headings", height=12)
        vs = ttk.Scrollbar(wrap, orient="vertical", style="Vertical.TScrollbar",
                           command=self.preview.yview)
        hs = ttk.Scrollbar(right, orient="horizontal", style="Horizontal.TScrollbar",
                           command=self.preview.xview)
        self.preview.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.preview.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        hs.pack(fill="x", padx=8, pady=(0, 8))
        self.preview.tag_configure("odd", background="#F7FAFD")
        self.preview.tag_configure("dup", background="#FFF6E5")
        self.preview.tag_configure("warn", background="#FDECEC")

        # 模式 + 底部
        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        f1 = tk.Frame(foot, bg=CLR_CARD)
        f1.pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(f1, text="导入方式", bg=CLR_CARD, fg="#41506B",
                 font=(self.fam, 10)).pack(side="left", padx=(0, 12))
        for text, val in (("按「型号」合并（重复则跳过，不重复才新增）", MODE_MERGE),
                          ("追加导入", MODE_APPEND),
                          ("覆盖全部（先清空现有数据）", MODE_REPLACE)):
            ttk.Radiobutton(f1, text=text, value=val, variable=self.var_mode,
                            style="Card.TRadiobutton", takefocus=False,
                            command=self._on_mode_change).pack(side="left", padx=(0, 14))

        f15 = tk.Frame(foot, bg=CLR_CARD)
        f15.pack(fill="x", padx=16, pady=(2, 0))
        self.lbl_hint = tk.Label(f15, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                 font=(self.fam, 9), anchor="w")
        self.lbl_hint.pack(side="left")
        self.lbl_safe = tk.Label(
            f15, text="按型号合并只新增，不改动、不删除库中已有记录",
            bg=CLR_CARD, fg=CLR_OK, font=(self.fam, 9))
        self.lbl_safe.pack(side="right")

        self.lbl_msg = tk.Label(foot, text="", bg=CLR_CARD, fg=CLR_DANGER,
                                font=(self.fam, 9), anchor="w", justify="left")
        self.lbl_msg.pack(fill="x", padx=16)

        f2 = tk.Frame(foot, bg=CLR_CARD)
        f2.pack(fill="x", padx=16, pady=(4, 12))
        self.btn_ok = ttk.Button(f2, text="开始导入", style="Accent.TButton", width=12,
                                 command=self._ok)
        self.btn_ok.pack(side="right", padx=(8, 0))
        ttk.Button(f2, text="取消", width=10, command=self._cancel).pack(side="right")

    def _on_mode_change(self):
        self._mode_touched = True
        self._render_preview()
        self._refresh_hint()

    def _center(self, master):
        self.update_idletasks()
        w, h = max(880, self.winfo_reqwidth()), max(620, self.winfo_reqheight())
        self.geometry("%dx%d" % (w, h))
        # 这里的宽高已经是控件实际请求尺寸（已含 DPI 缩放），不能再按 DPI 放大
        center_window(self, master, size=(w, h), design=False)

    # ------------------------------------------------------------ 数据
    def _load_sheets(self):
        try:
            names = list_sheets(self.path)
        except Exception as e:
            self.lbl_msg.configure(text="无法读取文件：%s" % e)
            return
        self.cb_sheet["values"] = names
        if names:
            self.var_sheet.set(names[0])
        self._cur_sheet = self.var_sheet.get()
        self._spin_touched = False
        self._reload(auto=True)

    def _on_spin(self):
        self._spin_touched = True
        self._reload(auto=False)

    def _reload(self, auto=False):
        sheet = self.var_sheet.get() or None
        if auto or sheet != getattr(self, "_cur_sheet", None):
            self._spin_touched = False
        self._cur_sheet = sheet
        use_auto = not self._spin_touched
        try:
            hrow = None if use_auto else max(1, int(self.var_hrow.get()))
        except Exception:
            hrow = None
        try:
            headers, rows, meta = read_xlsx(self.path, sheet, hrow)
        except Exception as e:
            self.lbl_msg.configure(text="解析失败：%s" % e)
            return
        self.headers, self.rows = headers, rows
        if use_auto and meta.get("header_row"):
            self.var_hrow.set(meta["header_row"])
        self.mapping = map_headers(headers)
        self.records, self.mapping, self.unmapped = rows_to_records(
            headers, rows, dict(self.mapping))
        # 识别到「型号」列时，默认用「按型号合并」，避免重复录入
        if (not getattr(self, "_mode_touched", False)
                and "model" in set(self.mapping.values())):
            self.var_mode.set(MODE_MERGE)
        self._build_mapping_panel()
        self._render_preview()
        self.lbl_stat.configure(
            text="读取到 %d 行有效数据 · 匹配 %d/%d 个字段"
                 % (len(self.records), len(set(self.mapping.values())), len(FIELD_KEYS)))
        self._refresh_hint()

    # ------------------------------------------------------------ 重复判断
    def _dup_stats(self):
        """按型号与库中数据比对，返回 (跳过条数, 新增条数)。

        跳过 = 型号在库中已存在；或无型号但内容与库中已有无型号记录完全相同；
        或同一文件里已出现过（不会改动库中原记录）。
        """
        from .store import _content_key
        seen, seen_ck, dup, new = set(), set(), 0, 0
        for r in self.records:
            if is_blank_model(r.get("model")):
                ck = _content_key(r)
                if ck in self.existing_blank or ck in seen_ck:
                    dup += 1
                else:
                    new += 1
                seen_ck.add(ck)
                continue
            k = norm_model(r.get("model"))
            if k in self.existing_models or k in seen:
                dup += 1
            else:
                new += 1
            seen.add(k)
        return dup, new

    def _refresh_hint(self):
        mode = self.var_mode.get()
        model_ok = "model" in set(self.mapping.values())
        hint = MODE_HINT.get(mode, "")
        msg, color = "", CLR_DANGER
        if not self.records:
            msg = "⚠ 未读取到任何数据行，请确认工作表 / 表头行 / 字段映射是否正确。"
        elif mode == MODE_MERGE and not model_ok:
            hint = ""
            msg, color = "⚠ 没有识别到「型号」列，无法判断重复，将按追加导入处理。", CLR_WARN
        else:
            dup, new = self._dup_stats()
            if mode == MODE_MERGE:
                hint += "　本次导入：新增 %d 条 · 跳过重复 %d 条。" % (new, dup)
            else:
                if mode == MODE_REPLACE:
                    from .store import dedupe_records
                    kept, removed = dedupe_records(self.records)
                    hint += "　本次导入：加入 %d 条 · 文件内去重 %d 条。" % (len(kept), removed)
                else:
                    hint += "　本次导入：加入 %d 条（不去重）。" % len(self.records)
            no_code = sum(1 for r in self.records if not str(r.get("code") or "").strip())
            if no_code:
                msg, color = ("ℹ %d 行没有编号，导入时会自动生成编号（接着现有编号往下排）。"
                              % no_code), CLR_ACCENT
        self.lbl_hint.configure(text=hint)
        self.lbl_msg.configure(text=msg, fg=color)

    # ------------------------------------------------------------ 映射面板
    def _col_names(self):
        names = []
        for i, h in enumerate(self.headers):
            t = str(h).strip() if h is not None else ""
            names.append(t if t else "第%d列" % (i + 1))
        return names

    def _build_mapping_panel(self):
        for w in self.map_inner.winfo_children():
            w.destroy()
        self.field_vars = {}
        col_names = self._col_names()
        choices = ["（不导入）"] + col_names
        rev = {v: i for i, v in self.mapping.items()}
        col_count = {}
        for f in self.mapping.values():
            col_count[f] = col_count.get(f, 0) + 1
        for k in FIELD_KEYS:
            row = tk.Frame(self.map_inner, bg=CLR_CARD)
            row.pack(fill="x", pady=2)
            lbl = FIELD_LABEL[k] + ("（合并%d列）" % col_count[k]
                                    if col_count.get(k, 0) > 1 else "")
            tk.Label(row, text=lbl, bg=CLR_CARD, fg=CLR_TEXT,
                     font=(self.fam, 9), width=7, anchor="w").pack(side="left")
            var = tk.StringVar()
            if k in rev:
                var.set(col_names[rev[k]] if rev[k] < len(col_names) else "（不导入）")
            else:
                var.set("（不导入）")
            cb = ttk.Combobox(row, textvariable=var, values=choices, state="readonly",
                              width=18, font=(self.fam, 9))
            cb.pack(side="left", fill="x", expand=True)
            cb.bind("<<ComboboxSelected>>", lambda e: self._on_map_change())
            self.field_vars[k] = var
        self._last_pick = {k: var.get() for k, var in self.field_vars.items()}

    def _on_map_change(self):
        if self._map_lock:
            return
        self._map_lock = True
        try:
            col_names = self._col_names()
            cur = {k: self.field_vars[k].get() for k in FIELD_KEYS}
            last = getattr(self, "_last_pick", None) or {}
            # 刚被用户改动的字段优先保留所选列
            order = ([k for k in FIELD_KEYS if cur.get(k) != last.get(k)]
                     + [k for k in FIELD_KEYS if cur.get(k) == last.get(k)])
            picked = dict(cur)
            owner = {}
            for k in order:
                v = picked[k]
                if v == "（不导入）" or v is None:
                    picked[k] = None
                    continue
                if v in owner:
                    # 同一列只能给一个字段：优先级低的这个字段自己置为「不导入」
                    self.field_vars[k].set("（不导入）")
                    picked[k] = None
                else:
                    owner[v] = k
            mapping = {}
            for k, v in picked.items():
                if v is not None and v in col_names:
                    mapping[col_names.index(v)] = k
            self.records, self.mapping, self.unmapped = rows_to_records(
                self.headers, self.rows, mapping)
            self._last_pick = {k: self.field_vars[k].get() for k in FIELD_KEYS}
            self._render_preview()
            self.lbl_stat.configure(
                text="读取到 %d 行有效数据 · 匹配 %d/%d 个字段"
                     % (len(self.records), len(set(self.mapping.values())), len(FIELD_KEYS)))
            self._refresh_hint()
        finally:
            self._map_lock = False

    def _render_preview(self):
        merge_mode = self.var_mode.get() == MODE_MERGE
        cols = [k for k in FIELD_KEYS if k in set(self.mapping.values())]
        self.preview.delete(*self.preview.get_children())
        shown = ["STATUS"] + cols if merge_mode else cols
        self.preview["columns"] = shown
        if merge_mode:
            self.preview.heading("STATUS", text="重复判断")
            self.preview.column("STATUS", width=96, anchor="center", stretch=False)
        for k in cols:
            self.preview.heading(k, text=FIELD_LABEL[k])
            self.preview.column(k, width=max(80, int(FIELD_WIDTH[k] * 0.95)),
                                anchor="center" if FIELD_TYPE[k] in ("bool",) else "w",
                                stretch=False)
        from .xlsxio import normalize_record
        from .constants import LISTED_TEXT
        seen = set()
        for i, raw in enumerate(self.records[:8]):
            tags = ("odd",) if i % 2 else ()
            vals = []
            if merge_mode:
                status, tag = self._status_of(raw, seen)
                vals.append(status)
                if tag:
                    tags = tags + (tag,)
            rec = normalize_record(raw)
            for k in cols:
                v = rec.get(k)
                if FIELD_TYPE[k] == "bool":
                    vals.append(LISTED_TEXT.get(int(v), "未上架"))
                elif FIELD_TYPE[k] == "money":
                    vals.append("%.2f" % float(v or 0))
                else:
                    vals.append(v)
            self.preview.insert("", "end", values=vals, tags=tags)

    def _status_of(self, rec, seen):
        """判断预览行在「按型号合并」下的处理方式。

        规则：型号已存在 → 跳过（不改动库中原记录）；无型号但内容与库中已有
        无型号记录完全相同 → 跳过；其余 → 新增。
        """
        m = rec.get("model")
        if is_blank_model(m):
            from .store import _content_key
            ck = _content_key(rec)
            if ck in self.existing_blank:
                return "跳过（内容相同）", "dup"
            if ck in seen:
                return "文件内重复", "warn"
            seen.add(ck)
            return "新增（无型号）", ""
        k = norm_model(m)
        if k in self.existing_models:
            return "跳过（已存在）", "dup"
        if k in seen:
            return "文件内重复", "warn"
        seen.add(k)
        return "新增", "new"

    # ------------------------------------------------------------ 动作
    def _ok(self):
        if not self.records:
            self.lbl_msg.configure(text="⚠ 没有可导入的数据。")
            return
        mode = self.var_mode.get()
        if mode == MODE_MERGE and "model" not in set(self.mapping.values()):
            mode = MODE_APPEND
        if mode == MODE_REPLACE:
            from tkinter import messagebox
            if not messagebox.askyesno(
                    "确认覆盖",
                    "覆盖导入会先清空现有全部数据。\n"
                    "编号计数器同时归零，重新从 WL-00001 开始编号。\n"
                    "清空前会自动备份一份到 data\\backups（可随时找回）。\n\n确定继续吗？",
                    parent=self):
                return
        dup, new = self._dup_stats()
        self.result = {
            "mode": mode,
            "records": self.records,
            "mapping": self.mapping,
            "sheet": self.var_sheet.get(),
            "total_rows": len(self.rows),
            "dup": dup,
            "new": new,
        }
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_import(master, path, fam="Microsoft YaHei UI", existing_models=None,
               existing_blank=None):
    dlg = ImportDialog(master, path, fam, existing_models=existing_models,
                       existing_blank=existing_blank)
    master.wait_window(dlg)
    return dlg.result
