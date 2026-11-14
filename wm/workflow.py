# -*- coding: utf-8 -*-
"""制作流程（v1.42.0）：发起制作 → 制作标签 → 贴标签 → 质检 → 入库。

- 节点名称可自定义（设置弹窗，2~12 个，存 meta["workflow_stages"]）
- 每一步流转（发起 / 推进 / 退回 / 取消）都必须填写操作人姓名，
  姓名会记住（settings["wf_name"]），下次自动带出
- 流转全程留痕（workflow_logs），双击单据可看完整时间线
- 推进到最后一个节点（默认「入库」）时：可上传入库照片、填写货架等
  入库信息，勾选「同时新增库存」会自动生成编号写入库存表，
  照片一并带到库存记录上
"""

import time
import tkinter as tk
from tkinter import messagebox, ttk, simpledialog

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_MUTED,
                        CLR_TEXT, CLR_WARN, apply_window_icon, center_window,
                        guard_combobox)
from .photos import PhotoStrip

def fmt_extra(extra, limit=48):
    """把附加字段 dict 拼成一句短文本（列表列 / 弹窗摘要用）。"""
    if not isinstance(extra, dict) or not extra:
        return ""
    txt = "；".join("%s:%s" % (k, v) for k, v in extra.items())
    return txt if len(txt) <= limit else txt[:limit - 1] + "…"


COLS = [("no", "单号", 84, "center"),
        ("urgent", "加急", 52, "center"),
        ("title", "事项", 180, "w"),
        ("kind", "类型", 92, "center"),
        ("target", "关联编号", 96, "center"),
        ("photo", "照片", 44, "center"),
        ("extra", "附加信息", 160, "w"),
        ("stage_name", "当前节点", 88, "center"),
        ("handler", "经手人", 76, "center"),
        ("days", "停留(天)", 66, "center"),
        ("updated_at", "最近更新", 132, "center"),
        ("note", "备注", 150, "w")]


class NameBox(tk.Frame):
    """流程条：每个节点一个胶囊（节点名 + 在办数），点按过滤列表。"""

    def __init__(self, master, tab):
        super().__init__(master, bg=CLR_BG)
        self.tab = tab
        self.sel = -1          # -1 = 全部节点；>=0 = 只看该节点
        self.inner = tk.Frame(self, bg=CLR_BG)
        self.inner.pack(anchor="w", padx=16, pady=(8, 0))

    def render(self, counts):
        for w in self.inner.winfo_children():
            w.destroy()
        stages = counts["stages"]
        items = [("全部", sum(counts["counts"]) + 0, -1)]
        for i, name in enumerate(stages):
            items.append(("%s %d" % (name, counts["counts"][i]), counts["counts"][i], i))
        for text, _n, idx in items:
            on = (self.sel == idx)
            chip = tk.Label(
                self.inner, text=text, padx=12, pady=5,
                bg=(CLR_ACCENT if on else CLR_CARD),
                fg=("#FFFFFF" if on else CLR_TEXT),
                font=(self.tab.fam, 9, "bold" if on else "normal"),
                highlightbackground=CLR_BORDER, highlightthickness=1, cursor="hand2")
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda e, i=idx: self.pick(i))
            if idx < len(stages) - 1 + 0 and idx >= 0:
                tk.Label(self.inner, text="→", bg=CLR_BG, fg=CLR_MUTED,
                         font=(self.tab.fam, 10)).pack(side="left", padx=2)
        for text, key in (("已完成 %d" % counts["done"], "done"),
                          ("已取消 %d" % counts["cancelled"], "cancelled")):
            on = (self.tab.var_status.get() == key)
            chip = tk.Label(
                self.inner, text=text, padx=10, pady=5,
                bg=(CLR_ACCENT if on else CLR_CARD),
                fg=("#FFFFFF" if on else CLR_MUTED),
                font=(self.tab.fam, 9), highlightbackground=CLR_BORDER,
                highlightthickness=1, cursor="hand2")
            chip.pack(side="left", padx=(10, 0))
            chip.bind("<Button-1>", lambda e, k=key: self.pick_status(k))

    def pick(self, idx):
        self.sel = idx
        self.tab.var_status.set("active")
        self.tab.refresh_rows()

    def pick_status(self, key):
        self.sel = -1
        self.tab.var_status.set("" if self.tab.var_status.get() == key else key)
        self.tab.refresh_rows()


class NewWfDialog(tk.Toplevel):
    """发起制作。result = dict 或 None。

    类型决定要填什么：每个类型可带附加字段（普通输入 / 下拉选项），
    定义在 meta["workflow_kinds"]（「类型设置」弹窗里维护）。
    """

    def __init__(self, master, tab):
        super().__init__(master)
        self.result = None
        self.tab = tab
        self.fam = tab.fam
        self._master = master
        self.title("发起制作")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        # 底部按钮栏最先占位（附加字段行数会变，空间不足时保住按钮）
        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="发起", style="Accent.TButton", width=10,
                   command=self._ok).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10,
                   command=self.destroy).pack(side="right", pady=12)

        body = tk.Frame(self, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)
        body.columnconfigure(1, weight=1)
        last_name = str(tab.app.settings.get("wf_name") or "")
        self.kinds = tab.app.store.wf_kinds()

        rows = [("by", "你的名字 *"), ("title", "事项 *"),
                ("kind", "类型"), ("target", "关联编号"), ("note", "备注")]
        self.vars = {}
        for i, (key, label) in enumerate(rows):
            tk.Label(body, text=label, bg=CLR_BG, fg="#41506B",
                     font=(self.fam, 10), anchor="w").grid(
                row=i, column=0, sticky="w", padx=(0, 10), pady=6)
            v = tk.StringVar(value=last_name if key == "by" else "")
            self.vars[key] = v
            if key == "kind":
                cb = ttk.Combobox(body, textvariable=v,
                                  values=[k["name"] for k in self.kinds],
                                  width=26, font=(self.fam, 10), state="readonly")
                if self.kinds:
                    cb.current(0)
                cb.bind("<<ComboboxSelected>>", self._on_kind)
                cb.grid(row=i, column=1, sticky="w", pady=6)
            else:
                e = ttk.Entry(body, textvariable=v, width=28, font=(self.fam, 10))
                e.grid(row=i, column=1, sticky="ew", pady=6)
                if key == "by" and not last_name:
                    e.focus_set()

        # 类型附加字段区（随类型切换重建）
        self.extra_frm = tk.Frame(body, bg=CLR_BG)
        self.extra_frm.grid(row=len(rows), column=0, columnspan=2, sticky="ew")
        self.extra_widgets = []

        tk.Label(body, text="流程：%s" % " → ".join(tab.app.store.wf_stages()),
                 bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 9), anchor="w"
                 ).grid(row=len(rows) + 1, column=0, columnspan=2,
                        sticky="w", pady=(8, 0))

        self.msg = tk.Label(self, text="", bg=CLR_BG, fg=CLR_WARN,
                            font=(self.fam, 9), anchor="w")
        self.msg.pack(fill="x", padx=18)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()
        self._on_kind()

    def _on_kind(self, _e=None):
        """按所选类型重建附加字段（原型号/更换后型号/标签种类…）。"""
        name = self.vars["kind"].get()
        defs = next((k["fields"] for k in self.kinds if k["name"] == name), [])
        for w in self.extra_frm.winfo_children():
            w.destroy()
        self.extra_widgets = []
        self.extra_multi = {}       # label -> [(选项, BooleanVar), ...]
        for j, f in enumerate(defs):
            tk.Label(self.extra_frm, text=f["label"] + " *", bg=CLR_BG,
                     fg="#41506B", font=(self.fam, 10), anchor="w").grid(
                row=j, column=0, sticky="w", padx=(0, 10), pady=6)
            if f.get("options") and f.get("multi"):
                # 多选：一行勾选框，可同时勾多项，值用「、」连接
                frm = tk.Frame(self.extra_frm, bg=CLR_BG)
                picks = []
                for opt in f["options"]:
                    v = tk.BooleanVar(value=False)
                    ttk.Checkbutton(frm, text=opt, variable=v).pack(
                        side="left", padx=(0, 12))
                    picks.append((opt, v))
                self.extra_multi[f["label"]] = picks
                frm.grid(row=j, column=1, sticky="w", pady=6)
                self.extra_widgets.append((f["label"], frm))
            elif f.get("options"):
                w = ttk.Combobox(self.extra_frm, values=f["options"], width=26,
                                 font=(self.fam, 10), state="readonly")
                w.current(0)
                w.grid(row=j, column=1, sticky="ew", pady=6)
                self.extra_widgets.append((f["label"], w))
            else:
                w = ttk.Entry(self.extra_frm, width=28, font=(self.fam, 10))
                w.grid(row=j, column=1, sticky="ew", pady=6)
                self.extra_widgets.append((f["label"], w))
        self._refit()

    def _refit(self):
        """附加字段行数变化后重算窗口高度并保持居中。"""
        try:
            if not self.winfo_ismapped():
                return
            self.update_idletasks()
            center_window(self, self._master, force=True)
        except Exception:
            pass

    def _ok(self):
        d = {k: v.get().strip() for k, v in self.vars.items()}
        if not d["by"]:
            self.msg.configure(text="⚠ 请填写你的名字（每个节点都要留名）")
            return
        if not d["title"]:
            self.msg.configure(text="⚠ 请填写事项内容，例如：修复 WL-00012 外壳划痕")
            return
        extra = {}
        multi = getattr(self, "extra_multi", {})
        for label, w in self.extra_widgets:
            if label in multi:
                val = "、".join(opt for opt, v in multi[label] if v.get())
                if not val:
                    self.msg.configure(
                        text="⚠ 请至少勾选一个「%s」（该类型需要）" % label)
                    return
            else:
                val = w.get().strip()
                if not val:
                    self.msg.configure(text="⚠ 请填写「%s」（该类型需要）" % label)
                    return
            extra[label] = val
        if extra:
            d["_extra"] = extra
        self.result = d
        self.tab.remember_name(d["by"])
        self.destroy()


class FlowDialog(tk.Toplevel):
    """推进 / 退回 / 入库。ask 名字 + 备注。

    v1.42.8 起单据推进到最后一站（入库）不再立即结束，而是停在入库站；
    在入库站再点「推进」打开的即是入库窗口（填库存信息 / 直接结单）。
    """

    def __init__(self, master, tab, rec, forward):
        super().__init__(master)
        self.result = None          # (by, note, stock_rec 或 None, target)
        self.tab = tab
        self.rec = rec
        self.forward = forward
        self.fam = tab.fam

        stages = tab.app.store.wf_stages()
        st = int(rec.get("stage") or 0)
        new_stage = st + 1 if forward else max(0, st - 1)
        # 单据已停在最后一站（入库）：这个弹窗就是「执行入库」
        self.at_last = forward and st == len(stages) - 1

        if self.at_last:
            self.title("%s ▸ 完成结单" % stages[-1])
        elif forward:
            self.title("推进 ▸ %s" % rec["stage_name"])
        else:
            self.title("退回 ◂ %s" % rec["stage_name"])
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        # 底栏和提示最先 pack（side=bottom 优先占位）：添加照片后内容变高，
        # 窗口空间不足时 Tk 会裁掉后 pack 的控件——按钮栏必须保住
        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="确定", style="Accent.TButton", width=10,
                   command=self._ok).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10,
                   command=self.destroy).pack(side="right", pady=12)
        self.msg = tk.Label(self, text="", bg=CLR_BG, fg=CLR_WARN,
                            font=(self.fam, 9), anchor="w")
        self.msg.pack(fill="x", padx=18, side="bottom")

        body = tk.Frame(self, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)
        body.columnconfigure(1, weight=1)

        tk.Label(body, text="单据：%s %s" % (rec["no"], rec["title"]),
                 bg=CLR_BG, fg=CLR_TEXT, font=(self.fam, 10, "bold")
                 ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row = 1
        ex = fmt_extra(rec.get("extra"), limit=60)
        if ex:
            tk.Label(body, text="附加：" + ex, bg=CLR_BG, fg=CLR_MUTED,
                     font=(self.fam, 9), anchor="w").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 6))
            row += 1

        tk.Label(body, text="目标节点", bg=CLR_BG, fg="#41506B",
                 font=(self.fam, 10), anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=6)
        if self.at_last:
            tk.Label(body, text="%s（最后一步）——确认后单据完成"
                     % stages[-1],
                     bg=CLR_BG, fg=CLR_ACCENT,
                     font=(self.fam, 10, "bold"), anchor="w").grid(
                row=row, column=1, sticky="w", pady=6)
        elif forward:
            tk.Label(body, text="%s（第 %d / %d 站）" % (
                        stages[new_stage], new_stage + 1, len(stages)),
                     bg=CLR_BG, fg=CLR_ACCENT,
                     font=(self.fam, 10, "bold"), anchor="w").grid(
                row=row, column=1, sticky="w", pady=6)
            if new_stage == len(stages) - 1:
                tk.Label(body, text="推进后单据停在「%s」站，由该站的人完成收尾"
                         % stages[-1],
                         bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 8),
                         anchor="w").grid(row=row + 1, column=0,
                                          columnspan=2, sticky="w")
        else:
            # 跨站退回：质检 / 入库发现问题，可直接退回到任何更早的节点
            # （如「制作标签」），不必一站一站退
            tk.Label(body, text="退回到哪一站？发现问题直接退给对应的节点",
                     bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 8),
                     anchor="w").grid(row=row + 1, column=0, columnspan=2,
                                      sticky="w")
            self.var_target = tk.StringVar(value=stages[new_stage])
            cb = ttk.Combobox(body, textvariable=self.var_target, width=18,
                              state="readonly", font=(self.fam, 10),
                              values=[stages[i] for i in range(st)])
            cb.grid(row=row, column=1, sticky="w", pady=6)
            if st == 0:
                cb.configure(state="disabled")
            cb.bind("<<ComboboxSelected>>",
                    lambda e: self._fill_stations(
                        self.tab.app.store.wf_stages().index(
                            self.var_target.get())))
        row += 1

        # 交给谁：同一节点有多人时（如「制作标签A」「制作标签B」）可指定工位，
        # 不指定就是该节点的公共池，谁都能接
        self.var_station = tk.StringVar()
        self.cb_station = None
        if not self.at_last:
            tk.Label(body, text="交给谁", bg=CLR_BG, fg="#41506B",
                     font=(self.fam, 10), anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=6)
            self.cb_station = ttk.Combobox(
                body, textvariable=self.var_station, width=18,
                state="readonly", font=(self.fam, 10))
            self.cb_station.grid(row=row, column=1, sticky="w", pady=6)
            self._fill_stations(new_stage)
            tk.Label(body, text="该节点有多个人时，选具体工位就只推给他/她",
                     bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 8),
                     anchor="w").grid(row=row + 1, column=0,
                                      columnspan=2, sticky="w")
            row += 2

        tk.Label(body, text="你的名字 *", bg=CLR_BG, fg="#41506B",
                 font=(self.fam, 10), anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=6)
        self.var_by = tk.StringVar(
            value=str(tab.app.settings.get("wf_name") or ""))
        e = ttk.Entry(body, textvariable=self.var_by, width=26,
                      font=(self.fam, 10))
        e.grid(row=row, column=1, sticky="ew", pady=6)
        if not self.var_by.get():
            e.focus_set()
        row += 1

        tk.Label(body, text="备注", bg=CLR_BG, fg="#41506B",
                 font=(self.fam, 10), anchor="w").grid(
            row=row, column=0, sticky="nw", padx=(0, 10), pady=6)
        self.var_note = tk.StringVar()
        ttk.Entry(body, textvariable=self.var_note, width=34,
                  font=(self.fam, 10)).grid(row=row, column=1, sticky="ew", pady=6)
        row += 1

        # 在入库站（最后节点）执行入库：可把商品写进库存，或直接结单
        self.stock_vars = {}
        self._stock_widgets = []
        if self.at_last:
            # 「更换后型号」自动带进入库的型号框
            pre_model = ""
            ex = rec.get("extra")
            if isinstance(ex, dict):
                for k, v in ex.items():
                    if "型号" in k and "原" not in k:
                        pre_model = str(v)
                        break
            self.var_stock = tk.BooleanVar(value=True)
            ck = ttk.Checkbutton(body, text="把该商品新增到库存"
                                 "（不勾选 = 直接结单，不新增库存）",
                                 variable=self.var_stock,
                                 command=self._toggle_stock)
            ck.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
            grid = tk.Frame(body, bg=CLR_BG)
            grid.grid(row=row + 1, column=0, columnspan=2, sticky="ew")
            for c in range(4):
                grid.columnconfigure(c, weight=1 if c % 2 else 0)
            fields = [("brand", "品牌"), ("category", "品类"), ("model", "型号"),
                      ("condition", "成色"), ("qty", "数量"), ("price", "单价"),
                      ("shelf", "货架")]
            for i, (key, label) in enumerate(fields):
                r, c = divmod(i, 2)
                tk.Label(grid, text=label, bg=CLR_BG, fg="#41506B",
                         font=(self.fam, 9), anchor="w").grid(
                    row=r, column=c * 2, sticky="w", padx=(0, 4), pady=4)
                v = tk.StringVar(value="1" if key == "qty"
                                 else (pre_model if key == "model" else ""))
                self.stock_vars[key] = v
                ent = tk.Entry(grid, textvariable=v, width=14,
                               font=(self.fam, 9), relief="solid", bd=1)
                ent.grid(row=r, column=c * 2 + 1, sticky="ew", pady=4, padx=(0, 10))
                self._stock_widgets += [ent]
            self._toggle_stock()

            # 入库照片：留证 + 新库存时一并带入库存记录
            box = tk.Frame(body, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                           highlightthickness=1)
            box.grid(row=row + 2, column=0, columnspan=2, sticky="ew",
                     pady=(10, 2))
            tk.Label(box, text="%s照片（可多选；新增库存时会一并带到库存记录）"
                     % stages[-1],
                     bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9), anchor="w"
                     ).pack(fill="x", padx=12, pady=(8, 0))
            self.photo_strip = PhotoStrip(box, tab.app, kind="wf",
                                          on_change=self._refit)
            self.photo_strip.pack(fill="x", pady=(0, 6))
            self.photo_strip.set_code(rec.get("no") or "")
            try:                  # 照片条 + 双列字段需要更宽的空间
                self.minsize(480, 1)
            except Exception:
                pass

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    def _refit(self):
        """照片增删后内容变高：窗口跟着长高并保持居中（按钮永远可见）。"""
        try:
            self.update_idletasks()
            if self.winfo_reqheight() > self.winfo_height() + 2:
                center_window(self, self.master, force=True)
        except Exception:
            pass

    def _toggle_stock(self):
        state = "normal" if self.var_stock.get() else "disabled"
        for w in self._stock_widgets:
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _fill_stations(self, stage):
        """目标节点的工位下拉：任意人 + 该节点的各个具名工位。"""
        try:
            names = [x["name"] for x in self.tab.app.store.wf_stations()
                     if x["stage"] == int(stage)]
        except Exception:
            names = []
        try:
            self.cb_station.configure(values=["该节点任意人"] + names)
            self.var_station.set("该节点任意人")
        except Exception:
            pass

    def _ok(self):
        by = self.var_by.get().strip()
        if not by:
            self.msg.configure(text="⚠ 请填写你的名字（每个节点都要留名）")
            return
        stock_rec = None
        if self.at_last and self.var_stock.get():
            stock_rec = {k: v.get().strip() for k, v in self.stock_vars.items()}
            try:
                if int(float(stock_rec.get("qty") or 1)) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                self.msg.configure(text="⚠ 数量必须是大于 0 的整数")
                return
            if not stock_rec.get("model"):
                self.msg.configure(text="⚠ 入库需要至少填写「型号」")
                return
        target = None
        if not self.forward:
            try:                       # 跨站退回：把选中的节点名换回序号
                target = self.tab.app.store.wf_stages().index(
                    self.var_target.get())
            except (ValueError, AttributeError):
                target = None
        station = ""
        try:
            choice = self.var_station.get()
            if choice and choice != "该节点任意人":
                station = choice
        except Exception:
            station = ""
        self.result = (by, self.var_note.get().strip(), stock_rec, target,
                       station)
        self.tab.remember_name(by)
        self.destroy()


class StagesDialog(tk.Toplevel):
    """编辑节点名称（2~12 个）。"""

    def __init__(self, master, tab):
        super().__init__(master)
        self.tab = tab
        self.fam = tab.fam
        self.title("流程节点设置")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        # 底部按钮栏最先 pack（side=bottom 优先占位）：节点行变多、窗口
        # 高度不够时 Tk 会裁掉后 pack 的控件，按钮栏必须保住
        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="保存", style="Accent.TButton", width=10,
                   command=self._ok).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10,
                   command=self.destroy).pack(side="right", pady=12)

        tk.Label(self, text="按顺序填写各节点名称（可增删改名），例："
                            "发起制作 → 制作标签 → 贴标签 → 质检 → 入库",
                 bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 9), anchor="w"
                 ).pack(fill="x", padx=18, pady=(14, 6))

        self.rows = tk.Frame(self, bg=CLR_BG)
        self.rows.pack(fill="x", padx=18)
        self._entries = []
        for name in tab.app.store.wf_stages():
            self._add_row(name)

        btns = tk.Frame(self, bg=CLR_BG)
        btns.pack(fill="x", padx=18, pady=8)
        ttk.Button(btns, text="＋ 添加节点", style="Ghost.TButton", width=11,
                   command=lambda: self._add_row("")).pack(side="left")

        self.msg = tk.Label(self, text="", bg=CLR_BG, fg=CLR_WARN,
                            font=(self.fam, 9), anchor="w")
        self.msg.pack(fill="x", padx=18)

        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    def _add_row(self, name):
        if len(self._entries) >= 12:
            return
        r = tk.Frame(self.rows, bg=CLR_BG)
        r.pack(fill="x", pady=3)
        idx = len(self._entries) + 1
        tk.Label(r, text="%d." % idx, bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9), width=3).pack(side="left")
        e = tk.Entry(r, font=(self.fam, 10), relief="solid", bd=1, width=24)
        e.pack(side="left", ipady=2)
        e.insert(0, str(name))
        ttk.Button(r, text="✕", width=3, style="Ghost.TButton",
                   command=lambda: self._del_row(r)).pack(side="left", padx=(6, 0))
        self._entries.append((r, e))
        self._refit()

    def _del_row(self, row):
        if len(self._entries) <= 2:
            self.msg.configure(text="⚠ 至少保留 2 个节点")
            return
        self._entries = [(r, e) for (r, e) in self._entries if r is not row]
        row.destroy()
        for i, (_r, e) in enumerate(self._entries, 1):
            e.master.winfo_children()[0].configure(text="%d." % i)
        self._refit()

    def _refit(self):
        """节点行数变化后重算窗口高度并保持居中。

        窗口高度在打开时定死，之后加行内容变高，而底部按钮栏在 pack
        顺序里排在最后，空间不足时会被整个挤出窗外（保存按钮看不见）。
        """
        try:
            if not self.winfo_ismapped():
                return
            self.update_idletasks()
            center_window(self, self.tab, force=True)
        except Exception:
            pass

    def _ok(self):
        names = [e.get().strip() for _r, e in self._entries]
        ok, msg = self.tab.app.store.wf_set_stages(names)
        if not ok:
            self.msg.configure(text="⚠ " + msg)
            return
        self.destroy()
        messagebox.showinfo("制作流程", msg, parent=self.tab)


class StationsDialog(tk.Toplevel):
    """工位设置：一个节点可以有多个人（如「制作标签A」「制作标签B」）。

    推送时可以指定交给哪个工位；同名工位才算「同一个人/同一张桌子」。
    """

    def __init__(self, master, tab):
        super().__init__(master)
        self.tab = tab
        self.fam = tab.fam
        self.title("工位设置")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="保存", style="Accent.TButton", width=10,
                   command=self._ok).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10,
                   command=self.destroy).pack(side="right", pady=12)

        tk.Label(self, text="一个节点可以有多个人：比如节点「制作标签」，"
                            "可以配置「制作标签A」「制作标签B」两个工位，"
                            "推送时选择交给谁。",
                 bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 9), anchor="w",
                 wraplength=460, justify="left"
                 ).pack(fill="x", padx=18, pady=(14, 6))

        self.stages = list(tab.app.store.wf_stages())
        self.rows = tk.Frame(self, bg=CLR_BG)
        self.rows.pack(fill="x", padx=18)
        self._entries = []
        for st in tab.app.store.wf_stations():
            self._add_row(st["name"], st["stage"])

        btns = tk.Frame(self, bg=CLR_BG)
        btns.pack(fill="x", padx=18, pady=8)
        ttk.Button(btns, text="＋ 添加工位", style="Ghost.TButton", width=11,
                   command=lambda: self._add_row("", 0)).pack(side="left")

        self.msg = tk.Label(self, text="", bg=CLR_BG, fg=CLR_WARN,
                            font=(self.fam, 9), anchor="w")
        self.msg.pack(fill="x", padx=18)

        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    def _add_row(self, name, stage):
        if len(self._entries) >= 60:
            return
        r = tk.Frame(self.rows, bg=CLR_BG)
        r.pack(fill="x", pady=3)
        tk.Label(r, text="工位名", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        e = tk.Entry(r, font=(self.fam, 10), relief="solid", bd=1, width=18)
        e.pack(side="left", padx=(6, 10), ipady=2)
        e.insert(0, str(name))
        tk.Label(r, text="节点", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")
        var = tk.StringVar(value=self.stages[int(stage)]
                           if 0 <= int(stage) < len(self.stages) else
                           (self.stages[0] if self.stages else ""))
        cb = ttk.Combobox(r, textvariable=var, values=self.stages,
                          state="readonly", width=14, font=(self.fam, 10))
        cb.pack(side="left", padx=(6, 10))
        ttk.Button(r, text="✕", width=3, style="Ghost.TButton",
                   command=lambda: self._del_row(r)).pack(side="left")
        self._entries.append((r, e, var))
        self._refit()

    def _del_row(self, row):
        if len(self._entries) <= 1:
            self.msg.configure(text="⚠ 至少保留 1 个工位")
            return
        self._entries = [x for x in self._entries if x[0] is not row]
        row.destroy()
        self._refit()

    def _refit(self):
        try:
            if not self.winfo_ismapped():
                return
            self.update_idletasks()
            center_window(self, self.tab, force=True)
        except Exception:
            pass

    def _ok(self):
        items = []
        for _r, e, var in self._entries:
            name = e.get().strip()
            if not name:
                continue
            try:
                stage = self.stages.index(var.get())
            except ValueError:
                stage = 0
            items.append({"name": name, "stage": stage})
        ok, msg = self.tab.app.store.wf_set_stations(items)
        if not ok:
            self.msg.configure(text="⚠ " + msg)
            return
        self.destroy()
        messagebox.showinfo("制作流程", msg, parent=self.tab)
        self.tab.refresh_tab()


class KindsDialog(tk.Toplevel):
    """编辑制作类型及其附加字段。

    每个类型：名称 + 若干附加字段；字段 = 名称 +（可选）下拉选项，
    选项用「、」或逗号分隔，如：外箱标、机身标、配件标。
    """

    def __init__(self, master, tab):
        super().__init__(master)
        self.tab = tab
        self.fam = tab.fam
        self.title("制作类型设置")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        apply_window_icon(self)

        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="保存", style="Accent.TButton", width=10,
                   command=self._ok).pack(side="right", padx=(8, 16), pady=12)
        ttk.Button(foot, text="取消", width=10,
                   command=self.destroy).pack(side="right", pady=12)

        tk.Label(self, text="类型决定发起时要填什么：每个类型可加专属字段，"
                            "选项用「、」分隔就是下拉框",
                 bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 9), anchor="w"
                 ).pack(fill="x", padx=18, pady=(14, 6))

        mid = tk.Frame(self, bg=CLR_BG)
        mid.pack(fill="both", expand=True, padx=18)
        # 左：类型列表
        left = tk.Frame(mid, bg=CLR_BG)
        left.pack(side="left", fill="y")
        self.lb = tk.Listbox(left, width=14, height=10, font=(self.fam, 10),
                             relief="solid", bd=1, highlightthickness=0,
                             exportselection=False)
        self.lb.pack(fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda e: self._load_kind())
        ttk.Button(left, text="＋ 添加类型", style="Ghost.TButton", width=11,
                   command=self._add_kind).pack(fill="x", pady=(6, 0))
        ttk.Button(left, text="删除类型", style="Ghost.TButton", width=11,
                   command=self._del_kind).pack(fill="x", pady=(4, 0))

        # 右：当前类型的名称 + 字段表
        right = tk.Frame(mid, bg=CLR_BG)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        rown = tk.Frame(right, bg=CLR_BG)
        rown.pack(fill="x")
        tk.Label(rown, text="类型名称", bg=CLR_BG, fg="#41506B",
                 font=(self.fam, 10)).pack(side="left", padx=(0, 8))
        self.var_name = tk.StringVar()
        ttk.Entry(rown, textvariable=self.var_name, width=18,
                  font=(self.fam, 10)).pack(side="left")

        cols = ("label", "options", "multi")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=6)
        self.tree.heading("label", text="字段名称")
        self.tree.heading("options", text="下拉选项（、分隔，留空=普通输入框）")
        self.tree.heading("multi", text="多选")
        self.tree.column("label", width=120, anchor="w")
        self.tree.column("options", width=200, anchor="w")
        self.tree.column("multi", width=52, anchor="center")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))

        brow = tk.Frame(right, bg=CLR_BG)
        brow.pack(fill="x", pady=(6, 0))
        ttk.Button(brow, text="＋ 添加字段", style="Ghost.TButton", width=11,
                   command=self._add_field).pack(side="left")
        ttk.Button(brow, text="删除字段", style="Ghost.TButton", width=9,
                   command=self._del_field).pack(side="left", padx=(6, 0))
        tk.Label(brow, text="双击单元格可直接改；「多选」双击在 是/否 间切换",
                 bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 9)).pack(side="right")
        self.tree.bind("<Double-1>", self._edit_cell)

        self.msg = tk.Label(self, text="", bg=CLR_BG, fg=CLR_WARN,
                            font=(self.fam, 9), anchor="w")
        self.msg.pack(fill="x", padx=18, pady=(4, 0))

        self.kinds = [dict(k, fields=[dict(f) for f in k.get("fields") or []])
                      for k in tab.app.store.wf_kinds()]
        self._loading = False
        self._fill_list()
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    # ---- 左侧列表
    def _fill_list(self):
        self.lb.delete(0, "end")
        for k in self.kinds:
            self.lb.insert("end", k["name"])
        if self.kinds:
            self.lb.selection_set(0)
        self._load_kind()

    def _cur(self):
        sel = self.lb.curselection()
        return sel[0] if sel else None

    def _load_kind(self):
        # 切换前先把上一个类型在名称框里改的名字存回去
        if not self._loading and getattr(self, "_last_idx", None) is not None:
            try:
                name = self.var_name.get().strip()
                if (name and 0 <= self._last_idx < len(self.kinds)):
                    self.kinds[self._last_idx]["name"] = name
            except Exception:
                pass
        self._loading = True
        try:
            i = self._cur()
            self.tree.delete(*self.tree.get_children())
            if i is None:
                self.var_name.set("")
                self._last_idx = None
                return
            k = self.kinds[i]
            self.var_name.set(k["name"])
            self._last_idx = i
            for f in k["fields"]:
                self.tree.insert("", "end", values=(
                    f["label"], "、".join(f.get("options") or []),
                    "是" if (f.get("options") and f.get("multi")) else ""))
        finally:
            self._loading = False

    def _add_kind(self):
        if len(self.kinds) >= 20:
            self.msg.configure(text="⚠ 类型最多 20 个")
            return
        self.kinds.append({"name": "新类型", "fields": []})
        self.lb.insert("end", "新类型")
        self.lb.selection_clear(0, "end")
        self.lb.selection_set("end")
        self._load_kind()
        self.var_name.set("新类型")

    def _del_kind(self):
        i = self._cur()
        if i is None:
            return
        if len(self.kinds) <= 1:
            self.msg.configure(text="⚠ 至少保留 1 个类型")
            return
        del self.kinds[i]
        self._fill_list()

    # ---- 右侧字段表
    def _add_field(self):
        i = self._cur()
        if i is None:
            return
        if len(self.kinds[i]["fields"]) >= 8:
            self.msg.configure(text="⚠ 每个类型最多 8 个字段")
            return
        self.tree.insert("", "end", values=("新字段", "", ""))
        self._stash_fields()

    def _del_field(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.tree.delete(sel[0])
        self._stash_fields()

    def _stash_fields(self):
        """把表格里的编辑内容写回内存（改名/改选项都走这里）。"""
        i = self._cur()
        if i is None:
            return
        fields = []
        for iid in self.tree.get_children():
            v = self.tree.item(iid, "values")
            label = str(v[0] if len(v) > 0 else "").strip()
            if not label:
                continue
            raw = str(v[1] if len(v) > 1 else "")
            opts = [s.strip() for s in raw.replace("，", "、").replace(",", "、")
                    .split("、") if s.strip()]
            fd = {"label": label, "options": opts}
            if opts and len(v) > 2 and str(v[2]).strip() == "是":
                fd["multi"] = True
            fields.append(fd)
        self.kinds[i]["fields"] = fields

    def _edit_cell(self, e):
        """双击单元格 → 原地 Entry 编辑（字段名 / 选项）；多选列双击直接切换。"""
        if self._loading:
            return
        iid = self.tree.identify_row(e.y)
        col = self.tree.identify_column(e.x)
        if not iid:
            return
        if col == "#3":
            cur = str(self.tree.set(iid, "multi")).strip()
            self.tree.set(iid, "multi", "" if cur == "是" else "是")
            self._stash_fields()
            return
        if col not in ("#1", "#2"):
            return
        x, y, w, h = self.tree.bbox(iid, col)
        v = self.tree.set(iid, "label" if col == "#1" else "options")
        e2 = ttk.Entry(self.tree, font=(self.fam, 9))
        e2.place(x=x, y=y, width=w, height=h)
        e2.insert(0, v)
        e2.focus_set()

        def save(_ev=None):
            val = e2.get().strip()
            self.tree.set(iid, "label" if col == "#1" else "options", val)
            e2.destroy()
            self._stash_fields()
            # 字段名同步刷新左侧无操作；类型名在保存时统一读取
        e2.bind("<Return>", save)
        e2.bind("<FocusOut>", save)

    def _collect(self):
        """读当前选中类型的名称（附加字段已在编辑时随手 stash）。"""
        i = self._cur()
        if i is not None:
            name = self.var_name.get().strip()
            if name:
                self.kinds[i]["name"] = name
        return self.kinds

    def _ok(self):
        kinds = self._collect()
        ok, msg = self.tab.app.store.wf_set_kinds(kinds)
        if not ok:
            self.msg.configure(text="⚠ " + msg)
            return
        self.destroy()
        messagebox.showinfo("制作流程", msg, parent=self.tab)


class DetailDialog(tk.Toplevel):
    """单据详情 + 流转时间线（只读）。"""

    def __init__(self, master, tab, rec):
        super().__init__(master)
        self.fam = tab.fam
        self.title("制作单 %s" % rec["no"])
        self.configure(bg=CLR_BG)
        self.transient(master)
        apply_window_icon(self)

        # 底栏最先 pack：添加照片后内容变高，窗口空间不足时
        # Tk 会裁掉后 pack 的控件——关闭按钮必须保住
        foot = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="关闭", width=10,
                   command=self.destroy).pack(side="right", padx=(8, 16), pady=12)

        stages = tab.app.store.wf_stages()
        ex = rec.get("extra")
        ex_lines = ("\n" + "\n".join("%s：%s" % (k, v) for k, v in ex.items())
                    if isinstance(ex, dict) and ex else "")
        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x")
        info = ("事项：%s%s      类型：%s      关联：%s\n当前节点：%s（第 %d / %d 站）"
                "      交给：%s      经手人：%s      状态：%s\n备注：%s%s"
                % (rec["title"], "  🔥加急" if int(rec.get("urgent") or 0) else "",
                   rec.get("kind") or "—", rec.get("target") or "—",
                   rec["stage_name"], int(rec.get("stage") or 0) + 1, len(stages),
                   rec.get("station") or "该节点任意人",
                   rec.get("handler") or "—",
                   {"active": "进行中", "done": "已完成",
                    "cancelled": "已取消"}.get(rec.get("status"), rec.get("status")),
                   rec.get("note") or "—", ex_lines))
        tk.Label(head, text=info, bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 10), justify="left", anchor="w"
                 ).pack(fill="x", padx=16, pady=12)

        # 入库照片（这里也能补拍 / 看大图；入库时上传的就是这一组）
        ph = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                      highlightthickness=1)
        ph.pack(fill="x")
        self.photo_strip = PhotoStrip(ph, tab.app, kind="wf",
                                      on_change=self._refit)
        self.photo_strip.pack(fill="x", pady=(0, 6))
        self.photo_strip.set_code(rec.get("no") or "")

        body = tk.Frame(self, bg=CLR_BG)
        body.pack(fill="both", expand=True)
        txt = tk.Text(body, width=64, height=14, font=(self.fam, 10), bd=0,
                      bg=CLR_BG, fg=CLR_TEXT, wrap="word", state="disabled")
        txt.pack(fill="both", expand=True, padx=16, pady=12)
        logs = tab.app.store.wf_logs(int(rec["id"]))
        lines = []
        for i, g in enumerate(reversed(logs), 1):
            lines.append("%s   [%s] %s：%s" % (
                str(g.get("at") or "")[:19], g["action_name"],
                g.get("by") or "—", g.get("note") or ""))
            if i < len(logs):
                lines.append("   │")
        txt.configure(state="normal")
        txt.insert("1.0", "\n".join(lines) or "（暂无流转记录）")
        txt.configure(state="disabled")

        self.bind("<Escape>", lambda e: self.destroy())
        center_window(self, master, force=True)
        self.grab_set()
        self.focus_force()

    def _refit(self):
        """照片增删后内容变高：窗口跟着长高并保持居中（按钮永远可见）。"""
        try:
            self.update_idletasks()
            if self.winfo_reqheight() > self.winfo_height() + 2:
                center_window(self, self.master, force=True)
        except Exception:
            pass


class WorkflowTab(ttk.Frame):
    """制作流程页。"""

    def __init__(self, master, app, fam="Microsoft YaHei UI"):
        super().__init__(master)
        self.app = app
        self.fam = fam
        self.rows = []
        self._by_id = {}
        self.var_status = tk.StringVar(value="active")
        self._build()

    # ------------------------------------------------------------ UI
    def _build(self):
        bar = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x")
        tk.Label(bar, text="制作流程", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left",
                                                   padx=(16, 10), pady=12)
        self.lbl_wh = tk.Label(bar, text="", bg=CLR_ACCENT, fg="#FFFFFF",
                               font=(self.fam, 9))
        self.lbl_wh.pack(side="left", pady=12)
        self.lbl_flow = tk.Label(bar, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                 font=(self.fam, 9))
        self.lbl_flow.pack(side="left", padx=(10, 0), pady=12)
        ttk.Button(bar, text="＋ 发起制作", style="Accent.TButton",
                   command=self.new_wf).pack(side="right", padx=(8, 16), pady=8)
        ttk.Button(bar, text="节点设置", style="Ghost.TButton",
                   command=self.edit_stages).pack(side="right", pady=8)
        ttk.Button(bar, text="工位设置", style="Ghost.TButton",
                   command=self.edit_stations).pack(side="right", pady=8)
        ttk.Button(bar, text="类型设置", style="Ghost.TButton",
                   command=self.edit_kinds).pack(side="right", pady=8)
        ttk.Button(bar, text="刷新", command=self.refresh_tab).pack(
            side="right", padx=(0, 8), pady=8)
        # 本机工位：这台电脑负责哪一站（多台电脑协作时各选各的）
        self.var_stage = tk.StringVar(value="不限")
        self.cb_stage = guard_combobox(ttk.Combobox(
            bar, textvariable=self.var_stage, state="readonly", width=9,
            values=["不限"], font=(self.fam, 9)))
        self.cb_stage.pack(side="right", padx=(0, 10), pady=8)
        self.cb_stage.bind("<<ComboboxSelected>>", self._pick_stage)
        tk.Label(bar, text="本机工位", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="right", padx=(0, 4), pady=12)

        self.flow = NameBox(self, self)
        self.flow.pack(fill="x")

        flt = tk.Frame(self, bg=CLR_BG)
        flt.pack(fill="x", padx=16, pady=(8, 0))
        self.var_kw = tk.StringVar()
        e = tk.Entry(flt, textvariable=self.var_kw, width=22,
                     font=(self.fam, 10), relief="solid", bd=1)
        e.pack(side="left", ipady=2)
        e.bind("<KeyRelease>", lambda ev: self._debounce())
        ttk.Button(flt, text="重置", style="Ghost.TButton", width=6,
                   command=self.reset_kw).pack(side="left", padx=(6, 0))
        # 工位固定的同时也要看得见整条流程：默认列全部在办单，
        # 只有停在本机工位的单能推进；勾上就只看自己这站
        self.var_only_mine = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="只看本站", variable=self.var_only_mine,
                        command=self.refresh_rows).pack(side="left",
                                                       padx=(12, 0))
        self._job = None

        wrap = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=10)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in COLS],
                                 show="headings", selectmode="browse")
        vs = ttk.Scrollbar(wrap, orient="vertical",
                           style="Vertical.TScrollbar", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        for key, title, w, anchor in COLS:
            # 表头锚点跟随列锚点：左对齐列表头也靠左，避免「表头飘中间、
            # 内容贴左边」的错位感（事项/备注这类宽列尤其明显）
            self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(key, width=int(w * self.app.ui_scale),
                             anchor=anchor,
                             stretch=(key in ("title", "note")))
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        # tag 优先级 = 创建先后（先创建优先）：已取消 > 已完成 > 加急 > 别站 > 临近超时 > 斑马纹
        self.tree.tag_configure("cancelled", foreground="#98A2B3")
        self.tree.tag_configure("done", foreground="#0E9F6E")
        self.tree.tag_configure("urgent", foreground="#D92D20")
        self.tree.tag_configure("other", foreground="#98A2B3")
        self.tree.tag_configure("stale", foreground=CLR_WARN)
        self.tree.tag_configure("odd", background="#F7FAFD")
        self.tree.bind("<Double-1>", lambda e: self.show_detail())
        self.tree.bind("<<TreeviewSelect>>",
                       lambda e: self._sync_urgent_btn())

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 10))
        self.lbl_hint = tk.Label(foot, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=(self.fam, 9), anchor="w")
        # expand+fill：提示文字再长也只占剩余空间，不会把右侧按钮挤出窗口
        self.lbl_hint.pack(side="left", fill="x", expand=True)
        ttk.Button(foot, text="删除", style="Danger.TButton", width=6,
                   command=self.delete_selected).pack(side="right")
        self.btn_urgent = ttk.Button(foot, text="加急", style="Ghost.TButton",
                                     width=5, command=self.toggle_urgent)
        self.btn_urgent.pack(side="right", padx=(0, 8))
        ttk.Button(foot, text="取消制作", style="Ghost.TButton", width=9,
                   command=self.cancel_selected).pack(side="right", padx=(0, 8))
        ttk.Button(foot, text="流转记录", style="Ghost.TButton", width=9,
                   command=self.show_detail).pack(side="right", padx=(0, 8))
        self.btn_back = ttk.Button(foot, text="◂ 退回", style="Ghost.TButton",
                                   width=7,
                                   command=lambda: self.move_selected(False))
        self.btn_back.pack(side="right", padx=(0, 8))
        self.btn_adv = ttk.Button(foot, text="推进 ▸", style="Accent.TButton",
                                  width=7,
                                  command=lambda: self.move_selected(True))
        self.btn_adv.pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------ 辅助
    def remember_name(self, name):
        self.app.settings["wf_name"] = str(name).strip()
        try:
            self.app._save_settings()
        except Exception:
            pass

    def _debounce(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(260, self.refresh_rows)

    def reset_kw(self):
        self.var_kw.set("")
        self.refresh_rows()

    # ------------------------------------------------------------ 数据
    def refresh_tab(self):
        try:
            self.lbl_wh.configure(text="当前仓库：%s" % self.app.cur_wh()["name"])
        except Exception:
            pass
        try:
            stages = self.app.store.wf_stages()
            self.lbl_flow.configure(
                text="%s，每一步都要填写操作人姓名" % " → ".join(stages))
        except Exception:
            pass
        self._sync_stage_picker()
        self.refresh_rows()

    def _is_client(self):
        """本机是不是连别人主机的客户端（客户机必须绑定具体工位）。"""
        return getattr(self.app, "lan_mode", "") == "client"

    def _sync_stage_picker(self):
        """下拉列出全部工位（工位名，可同节点多人如「制作标签A/B」）。

        「不限」只留给主机（统筹用）；客户机只能选具体工位，
        避免任何一台工位电脑都能替别人推进。
        """
        try:
            stations = self.app.store.wf_stations()
        except Exception:
            stations = []
        names = [s["name"] for s in stations]
        try:
            self.cb_stage.configure(
                values=(list(names) if self._is_client()
                        else ["不限"] + list(names)))
        except Exception:
            pass
        try:
            if self.app.settings.get("wf_my_station") in names:
                self.var_stage.set(self.app.settings.get("wf_my_station"))
            elif self._is_client():
                self.var_stage.set("请选择…")     # 客户机还没绑定工位
            else:
                self.var_stage.set("不限")
        except Exception:
            pass

    def _my_station(self):
        """本机工位名（空 = 不限）。"""
        name = str(self.app.settings.get("wf_my_station") or "").strip()
        try:
            names = [s["name"] for s in self.app.store.wf_stations()]
        except Exception:
            names = []
        if name and name in names:
            return name
        # 老版本只存了节点序号：映射到该节点的第一个工位
        try:
            idx = int(self.app.settings.get("wf_my_stage", -1))
        except (TypeError, ValueError):
            idx = -1
        if idx >= 0:
            try:
                for s in self.app.store.wf_stations():
                    if s["stage"] == idx:
                        return s["name"]
            except Exception:
                pass
        return ""

    def _stage_ready(self):
        """客户机必须先绑定工位才能动流程（「不限」只给主机）。"""
        if not self._is_client() or self._my_stage() >= 0:
            return True
        messagebox.showinfo(
            "本机工位",
            "请先在页面右上角「本机工位」里选择你负责的节点，"
            "之后才能操作制作流程。", parent=self)
        return False

    def _stage_locked(self):
        return bool(self.app.settings.get("wf_stage_locked"))

    def _pick_stage(self, _e=None):
        """选工位：第一次直接定下来并锁定，之后要改必须主机同意。"""
        choice = self.var_stage.get()
        try:
            names = [x["name"] for x in self.app.store.wf_stations()]
        except Exception:
            names = []
        idx = self.app.store.wf_station_stage(choice) if choice in names else -1
        label = choice if choice in names else "不限"
        if label == (self._my_station() or "不限"):
            return
        st_name = choice if choice in names else ""
        if not self._stage_locked():
            self._apply_stage(idx, st_name)
            messagebox.showinfo(
                "本机工位",
                "本机工位已定为「%s」，之后固定不变，只能推进停在这一站的单。\n\n"
                "以后要换工位，需要主机同意。" % label, parent=self)
            return
        if getattr(self.app, "lan_mode", "") != "client":
            if not messagebox.askyesno(
                    "更改工位",
                    "把本机工位改为「%s」？\n\n本机就是主机，改完立即生效。"
                    % label, parent=self):
                self._sync_stage_picker()
                return
            self._apply_stage(idx, st_name)
            return
        self._ask_host_stage(idx)

    def _apply_stage(self, idx, station=None):
        """写入本机工位并锁定；客户端模式下随请求上报主机做校验。"""
        idx = int(idx)
        if station is not None:
            self.app.settings["wf_my_station"] = str(station)
        self.app.settings["wf_my_stage"] = idx
        self.app.settings["wf_stage_locked"] = True
        try:
            self.app._save_settings()
        except Exception:
            pass
        try:
            if getattr(self.app, "lan_mode", "") == "client":
                self.app.store.wf_stage = idx
                # 工位名一并上报：主机按「指定交给谁」校验能不能接
                self.app.store.wf_station = str(
                    self.app.settings.get("wf_my_station") or "")
        except Exception:
            pass
        self._sync_stage_picker()
        self.refresh_rows()

    def _ask_host_stage(self, idx):
        """客户端改工位：向主机发申请，等主机在它自己的窗口里点同意。"""
        label = self._stage_name(idx) if idx >= 0 else "不限"
        try:
            self.app.store.request_stage(idx)
        except Exception as e:
            messagebox.showwarning("更改工位", "申请没能发到主机：%s" % e,
                                   parent=self)
            self._sync_stage_picker()
            return
        try:
            self.cb_stage.configure(state="disabled")
        except Exception:
            pass
        self.lbl_hint.configure(
            text="已向主机申请把本机工位改为「%s」，等待主机同意…" % label)
        self._wait_stage(idx, time.time() + 60)

    def _wait_stage(self, idx, deadline):
        try:
            st = str(self.app.store.stage_result().get("status") or "")
        except Exception:
            st = ""
        if st == "ok":
            self._apply_stage(idx)
            self._unlock_picker()
            messagebox.showinfo(
                "更改工位", "主机已同意，本机工位现在是「%s」。"
                % (self._stage_name(idx) if idx >= 0 else "不限"), parent=self)
            return
        if st == "no":
            self._sync_stage_picker()
            self._unlock_picker()
            messagebox.showinfo("更改工位", "主机没有同意这次更改，工位保持不变。",
                                parent=self)
            return
        if time.time() >= deadline:
            self._sync_stage_picker()
            self._unlock_picker()
            messagebox.showinfo(
                "更改工位", "主机暂时没有响应，工位保持不变。\n可以稍后再试。",
                parent=self)
            return
        try:
            self.after(1000, lambda: self._wait_stage(idx, deadline))
        except Exception:
            pass

    def _unlock_picker(self):
        try:
            self.cb_stage.configure(state="readonly")
        except Exception:
            pass
        self.refresh_rows()

    def refresh_rows(self):
        try:
            status = self.var_status.get() or "active"
            # v1.43.1：工位固定 ≠ 只看本站——默认列全部在办单，
            # 哪一站走到哪一步都看得见，只是别站的单不能推进
            mine_st = self._my_station() if self.var_only_mine.get() else ""
            if self.flow.sel >= 0 and status == "active":
                rows = [r for r in self.app.store.wf_list(
                            "active", self.var_kw.get(), station=mine_st)
                        if int(r.get("stage") or 0) == self.flow.sel]
                counts = self.app.store.wf_counts()
            else:
                rows = self.app.store.wf_list(status, self.var_kw.get(),
                                              station=mine_st)
                counts = self.app.store.wf_counts()
        except Exception as e:
            self.rows = []
            self.lbl_hint.configure(text="读取制作单失败：%s" % e)
            return
        self.rows = rows
        try:                              # 有入库照片的单打个记号
            ph_codes = self.app.store.photo_codes("wf")
        except Exception:
            ph_codes = set()
        self.flow.render(counts)
        prev = self.tree.focus()           # 刷新后恢复选中（加急按钮跟着变）
        self.tree.delete(*self.tree.get_children())
        self._by_id = {}
        for i, r in enumerate(self.rows):
            self._by_id[int(r["id"])] = r
            tags = []
            if r.get("status") == "cancelled":
                tags.append("cancelled")
            elif r.get("status") == "done":
                tags.append("done")
            elif int(r.get("urgent") or 0):
                tags.append("urgent")
            elif not self._can_move(r):
                tags.append("other")      # 停在别的工位：只读
            elif int(r.get("days") or 0) >= 3:
                tags.append("stale")
            if i % 2 == 0:
                tags.append("odd")
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["no"], "🔥" if int(r.get("urgent") or 0) else "",
                r["title"], r.get("kind") or "", r.get("target") or "",
                "📷" if (r.get("no") or "") in ph_codes else "",
                fmt_extra(r.get("extra")), r["stage_name"],
                r.get("handler") or "", r.get("days") or 0,
                r.get("updated_at") or "", r.get("note") or ""), tags=tags)
        if prev and int(prev) in self._by_id:
            self.tree.selection_set(prev)
            self.tree.focus(prev)
        n = len(rows)
        doable = sum(1 for r in rows if self._can_move(r))
        mine = self._my_stage()
        stamp = ("已固定" if self._stage_locked()
                 else "首次选择后固定")
        hint = "本机工位：%s（%s） · 共 %d 张 · 本站可推进 %d 张 · 双击看流转" % (
            (self._my_station() + "·" + self._stage_name(mine))
            if mine >= 0
            else ("未选（请先选择你的工位）" if self._is_client() else "不限"),
            stamp, n, doable if mine >= 0 else n)
        if self.var_only_mine.get():
            hint += " · 只看本站"
        self._hint_base = hint
        self._sync_urgent_btn()

    def _sync_urgent_btn(self):
        """加急按钮跟随选中行状态：加急单显示「取消加急」。"""
        try:
            iid = self.tree.focus()
            rec = self._by_id.get(int(iid))
            urgent = rec is not None and int(rec.get("urgent") or 0)
            self.btn_urgent.configure(text="取消加急" if urgent else "加急",
                                      width=9 if urgent else 5)
        except Exception:
            pass
        self._sync_action_btns()

    def _can_move(self, rec, forward=True):
        """这张单能不能由本机推进/退回（看不到 ≠ 能推，看得到 ≠ 能推）。

        工位固定后：单据停在别的站，或者已经指定交给同站的另一个人，
        都只能查看流转记录，不能替别人推进。
        """
        if rec is None:
            return False
        if forward and rec.get("status") != "active":
            return False
        mine = self._my_stage()
        if mine < 0:
            return True                    # 主机「不限」：哪一站的单都能推
        if int(rec.get("stage") or 0) != mine:
            return False
        owner = str(rec.get("station") or "")
        return (not owner) or owner == (self._my_station() or "")

    def _sync_action_btns(self):
        """推进/退回只对「停在本机这一站」的单可用，别站的单只读。

        同时把「为什么不能推」写在提示行里，避免用户点了没反应。
        """
        try:
            iid = self.tree.focus()
            rec = self._by_id.get(int(iid)) if iid else None
            ok_adv = self._can_move(rec)
            ok_back = self._can_move(rec, forward=False)
            for btn, on in ((self.btn_adv, ok_adv), (self.btn_back, ok_back)):
                try:
                    if on:
                        btn.state(["!disabled"])
                    else:
                        btn.state(["disabled"])
                except Exception:
                    pass
            base = getattr(self, "_hint_base", "")
            note = ""
            if rec is not None and not ok_adv:
                owner = str(rec.get("station") or "")
                if rec.get("status") != "active":
                    note = " · 选中单已%s，只能查看" % (
                        "完成" if rec.get("status") == "done" else "取消")
                elif self._my_stage() < 0:
                    note = " · 选中单在「%s」（本机不限，可直接推进）" % (
                        rec.get("stage_name") or "?")
                elif owner and owner != (self._my_station() or ""):
                    note = " · 选中单指定交给「%s」，只能查看" % owner
                else:
                    note = " · 选中单在「%s」，本机只读" % (
                        rec.get("stage_name") or "?")
            self.lbl_hint.configure(text=base + note)
        except Exception:
            pass

    def _selected(self):
        iid = self.tree.focus()
        if not iid:
            messagebox.showinfo("制作流程", "请先在列表中选中一张制作单",
                                parent=self)
            return None
        return self._by_id.get(int(iid))

    def toggle_urgent(self):
        """把选中的单据标记 / 取消加急（各工位都可以标）。"""
        rec = self._selected()
        if not rec:
            return
        flag = not int(rec.get("urgent") or 0)
        by = (self.app.settings.get("wf_name") or "").strip()
        if not by:
            by = simpledialog.askstring(
                "加急", "请填写你的名字（操作人）：", parent=self) or ""
            by = by.strip()
            if not by:
                return
            self.remember_name(by)
        ok, msg = self.app.store.wf_set_urgent(int(rec["id"]), flag, by)
        if not ok:
            messagebox.showerror("制作流程", msg, parent=self)
            return
        self.refresh_rows()

    # ------------------------------------------------------------ 动作
    def _my_stage(self):
        """本机工位对应的节点下标（-1 = 没选/不限）。"""
        st = self._my_station()
        if not st:
            return -1
        try:
            return int(self.app.store.wf_station_stage(st))
        except Exception:
            return -1

    def _stage_name(self, idx):
        try:
            stages = self.app.store.wf_stages()
            if 0 <= idx < len(stages):
                return stages[idx]
        except Exception:
            pass
        return "节点%d" % (idx + 1)

    def new_wf(self):
        if not self._stage_ready():
            return
        mine = self._my_stage()
        if mine > 0:
            messagebox.showinfo(
                "制作流程",
                "本机是「%s」工位，只负责推进本站的制作单。\n\n"
                "发起制作单请在第一个工位（%s）的电脑上操作。"
                % (self._stage_name(mine), self._stage_name(0)), parent=self)
            return
        dlg = NewWfDialog(self, self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        d = dlg.result
        wf_id, no = self.app.store.wf_create(
            d["title"], kind=d.get("kind"), target=d.get("target"),
            note=d.get("note"), by=d.get("by"), extra=d.get("_extra"))
        if not wf_id:
            messagebox.showwarning("发起制作", no, parent=self)
            return
        self.refresh_rows()

    def move_selected(self, forward):
        rec = self._selected()
        if rec is None:
            return
        if not self._stage_ready():
            return
        if rec.get("status") == "cancelled" and forward:
            messagebox.showinfo("制作流程", "该单已取消，请先在「已取消」列表里恢复",
                                parent=self)
            return
        if forward and rec.get("status") == "done":
            messagebox.showinfo(
                "制作流程",
                "该单已完成。如需重新处理，请在「已完成」列表里退回重开。",
                parent=self)
            return
        mine = self._my_stage()
        if mine >= 0 and int(rec.get("stage") or 0) != mine:
            messagebox.showinfo(
                "制作流程",
                "该单现在在「%s」，本机负责「%s」，只能在本站操作。\n\n"
                "整条流程都能看：双击这张单选「流转记录」即可查看走到哪一步。"
                % (rec.get("stage_name") or "?", self._stage_name(mine)),
                parent=self)
            return
        owner = str(rec.get("station") or "")
        if owner and mine >= 0 and owner != (self._my_station() or ""):
            messagebox.showinfo(
                "制作流程",
                "这张单指定交给「%s」，本机工位是「%s」，不能替别人接。"
                % (owner, self._my_station() or self._stage_name(mine)),
                parent=self)
            return
        dlg = FlowDialog(self, self, rec, forward)
        self.wait_window(dlg)
        if not dlg.result:
            return
        by, note, stock_rec, target, station = dlg.result
        if forward and getattr(dlg, "at_last", False):
            # 单据已停在最后一站：这一步是「执行入库 / 结单」，不再是推进
            if stock_rec is not None:
                ok, msg = self.app.store.wf_stock_in(int(rec["id"]),
                                                     stock_rec, by=by)
            else:
                ok, msg = self.app.store.wf_finish(int(rec["id"]), by, note)
        elif forward:
            ok, msg = self.app.store.wf_advance(int(rec["id"]), by, note,
                                                station=station)
        else:
            ok, msg = self.app.store.wf_back(int(rec["id"]), by, note,
                                             target=target, station=station)
        if not ok:
            messagebox.showwarning("制作流程", msg, parent=self)
            return
        if stock_rec:
            self._do_stock(rec, stock_rec, by)
        if msg:
            messagebox.showinfo("制作流程", msg, parent=self)
        self.refresh_rows()

    def _do_stock(self, rec, stock_rec, by):
        """推进到入库时顺带新增库存（型号必填、数量默认 1、照片带过去）。"""
        try:
            ok, msg = self.app.store.wf_stock_in(int(rec["id"]), stock_rec, by=by)
        except Exception as e:
            messagebox.showerror("入库", "自动新增库存失败：%s" % e, parent=self)
            return
        if not ok:
            messagebox.showwarning("入库", msg, parent=self)
            return
        self.app._status(msg)

    def cancel_selected(self):
        rec = self._selected()
        if rec is None:
            return
        if not self._stage_ready():
            return
        if self._my_stage() >= 0:
            messagebox.showinfo(
                "制作流程",
                "本机是「%s」工位，只能推进本站的单；\n取消 / 恢复请到主机上操作。"
                % self._stage_name(self._my_stage()), parent=self)
            return
        if rec.get("status") == "cancelled":
            if not messagebox.askyesno(
                    "恢复制作", "该单已取消，要恢复为进行中吗？", parent=self):
                return
            by = str(self.app.settings.get("wf_name") or "")
            ok, msg = self.app.store.wf_resume(int(rec["id"]), by)
            if not ok:
                messagebox.showwarning("制作流程", msg, parent=self)
            self.refresh_rows()
            return
        if not messagebox.askyesno(
                "取消制作", "确定取消「%s」吗？\n（可在「已取消」里恢复）"
                % rec["title"], parent=self):
            return
        by = str(self.app.settings.get("wf_name") or "")
        ok, msg = self.app.store.wf_cancel(int(rec["id"]), by)
        if not ok:
            messagebox.showwarning("制作流程", msg, parent=self)
        self.refresh_rows()

    def delete_selected(self):
        rec = self._selected()
        if rec is None:
            return
        if not self._stage_ready():
            return
        if self._my_stage() >= 0:
            messagebox.showinfo(
                "制作流程",
                "本机是「%s」工位，只能推进本站的单；\n删除请到主机上操作。"
                % self._stage_name(self._my_stage()), parent=self)
            return
        if not messagebox.askyesno(
                "删除制作单", "删除后流转记录一并清除，不可恢复。\n"
                "确定删除「%s」吗？" % rec["title"], parent=self):
            return
        self.app.store.wf_delete(int(rec["id"]))
        self.refresh_rows()

    def show_detail(self):
        rec = self._selected()
        if rec is None:
            return
        DetailDialog(self, self, rec)

    def edit_stages(self):
        if self.app._guard_write():
            return
        StagesDialog(self, self)
        self.refresh_tab()

    def edit_kinds(self):
        if self.app._guard_write():
            return
        KindsDialog(self, self)

    def edit_stations(self):
        """工位设置：一个节点可配多个工位（多人共站）。"""
        if self.app._guard_write():
            return
        StationsDialog(self, self)
