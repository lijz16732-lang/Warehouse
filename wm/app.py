# -*- coding: utf-8 -*-
"""主窗口：库存管理 + 数据分析。"""

import json
import math
import os
import queue
import random
import socket
import sqlite3
import sys
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk

from . import screen, xlsxio
from .analysis import AnalysisTab
from .phone import PhoneTab
from .sales import SalesTab, ask_sale
from .constants import (APP_NAME, APP_SHORT, APP_VERSION, CLR_ACCENT, CLR_BG,
                        CLR_BORDER, CLR_BORDER_LT, CLR_CARD, CLR_DANGER,
                        CLR_HOVER_EDGE, CLR_MUTED,
                        CLR_OK, CLR_TEXT, CLR_WARN, FIELD_ANCHOR, FIELD_KEYS,
                        FIELD_LABEL, FIELD_TYPE, FIELD_WIDTH, LISTED_TEXT,
                        MULTI_SEP, apply_window_icon, center_window,
                        is_blank_model)
from .editor import ask_record
from .extras import (BatchEditDialog, BuyerDialog, PurchaseListDialog,
                     RecycleBinDialog, ask_name, ask_purchase)
from .importer import MODE_APPEND, MODE_MERGE, MODE_REPLACE, MODE_TEXT, ask_import
from .xlsxio import normalize_record
from .store import Store, dedupe_records
from .lan import DEFAULT_PORT, LanServer, local_ips
from .remote import HostUnreachable, PermissionDenied, RemoteError, RemoteStore
from .theme import RowHover, apply_theme, dot_check

PAGE_SIZES = ["100", "200", "500", "1000", "全部"]


def shelf_parts(value):
    """把货架值按多货架分隔符拆成单个货架位列表（无分隔符时返回原值单元素）。"""
    return [p.strip() for p in str(value or "").split(MULTI_SEP) if p.strip()]


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_data_dir():
    base = app_dir()
    for cand in (os.path.join(base, "data"),
                 os.path.join(os.environ.get("APPDATA", base), "WarehouseManager")):
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".wtest")
            with open(probe, "w") as f:
                f.write("1")
            os.remove(probe)
            return cand
        except Exception:
            continue
    return base


class App(object):

    def __init__(self, root):
        self.root = root
        self.data_dir = resolve_data_dir()
        self.settings_path = os.path.join(self.data_dir, "settings.json")
        self.settings = self._load_settings()
        self.warehouses = self._normalize_warehouses()
        self.wh_index = self._clamp_wh(self.settings.get("current_wh", 0))
        self.db_path = os.path.join(self.data_dir, self.warehouses[self.wh_index]["file"])

        # ---- 局域网共享（主机 / 客户端）----
        self.lan_cfg = self._load_lan_cfg()
        self.lan_mode = "off"          # off / host / client
        self.lan_server = None
        self._remote_wh = ""
        self._lan_rev = 0
        self._lan_busy = False
        self._lan_pending = False
        self._lan_error = ""           # 启动时连不上主机的提示（界面建好后弹）
        self.can_write = True
        self.store = self._open_store()

        root.title("%s  v%s · %s" % (APP_NAME, APP_VERSION,
                                     self.warehouses[self.wh_index]["name"]))
        # 屏幕自适应（笔记本 / 台式机、Win10 / Win11、高 DPI 全覆盖）
        self.screen_metrics = screen.screen_metrics(root)
        self.ui_scale = screen.ui_scale(self.screen_metrics)
        screen.apply_tk_scaling(root, self.ui_scale)
        self.fam = apply_theme(root, scale=self.ui_scale)
        self._set_icon()

        # 全局：所有下拉框选完即清除文字选中底色（筛选/编辑/导入映射等）。
        # 顺序很重要：必须先 selection_clear() 再把焦点移走——
        #   · 只 clear 不移焦点 → Windows 上显示文本会消失（渲染 bug）
        #   · 只移焦点 → 残留浅蓝的"未激活选中"底色
        #   · 先 clear 后移焦点 → 文字正常、无任何选中底色
        def _cb_no_sel_highlight(e):
            w = e.widget
            w.selection_clear()
            w.winfo_toplevel().focus_set()
        root.bind_class("TCombobox", "<<ComboboxSelected>>", _cb_no_sel_highlight)

        # 状态
        self.records = []
        self.filtered = []
        self.by_id = {}
        self.page = 1
        self.page_size = self.settings.get("page_size", 200)
        self.sort_key = None
        self.sort_desc = False
        self.visible_cols = list(self.settings.get("visible_cols") or FIELD_KEYS)
        self._cell_col = FIELD_KEYS[0]
        self.low_threshold = int(self.settings.get("low_stock_threshold", 3) or 3)

        # 鼠标拖选区块（表格内划过即选中，松开可自动复制）
        self.var_drag_copy = tk.BooleanVar(value=bool(self.settings.get("drag_copy", True)))
        self._drag_anchor = None      # (行 iid, 列下标)
        self._drag_block = None       # {"rows": [iid...], "c0": 起始列, "c1": 结束列}
        self._block_preview = None    # 详情区正在预览的区块
        # 手动上色：单元格颜色 + 贴片控件（随仓库保存，见 meta.cell_colors）
        self.cell_colors = {}
        self._paint_labels = []
        self._scroll_job = None       # 滚动后重画贴片的 idle 任务
        self._head_h = 0              # 表头高度（内容区上沿，用来裁剪贴片）
        self.hover = None             # 鼠标划过整行高亮（建表格时创建）

        self._ui_queue = queue.Queue()
        self._stopped = False
        self._busy = False
        self._debounce = None

        self._build_menubar()
        self._build()
        self.load_data(first=True)
        self._apply_geometry()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(80, self._pump)
        self._bind_shortcuts()

        # ---- 局域网：恢复上次的主机状态 / 显示客户端状态条 ----
        root.report_callback_exception = self._report_callback_exception
        if self.lan_mode == "host":
            ok, msg = self.start_lan_host(self.lan_cfg.get("port"),
                                          self.lan_cfg.get("code"))
            if not ok:
                self.lan_mode = "off"
                self.lan_cfg["mode"] = "off"
                self._save_lan_cfg()
                self._status("主机服务启动失败：%s" % msg)
        elif self.lan_mode == "client":
            self._status("已连接主机 %s:%s（%s）"
                         % (self.lan_cfg.get("host"), self.lan_cfg.get("port"),
                            "可录入" if self.can_write else "只读"))
        self._update_lan_ui()
        self._lan_last_ok = True
        root.after(2000, self._lan_tick)
        if self._lan_error:
            err, self._lan_error = self._lan_error, ""
            root.after(300, lambda: messagebox.showwarning("连不上主机", err,
                                                          parent=self.root))

    # ============================================================ 基础
    def _set_icon(self):
        try:
            ico = os.path.join(app_dir(), "assets", "app.ico")
            if getattr(sys, "_MEIPASS", None):
                cand = os.path.join(sys._MEIPASS, "assets", "app.ico")
                if os.path.exists(cand):
                    ico = cand
            if os.path.exists(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass

    def _load_settings(self):
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self):
        try:
            s = dict(self.settings)
            s["page_size"] = getattr(self, "page_size", 200)
            s["visible_cols"] = getattr(self, "visible_cols", list(FIELD_KEYS))
            if getattr(self, "warehouses", None):
                s["warehouses"] = [dict(w) for w in self.warehouses]
                s["current_wh"] = self.wh_index
            if getattr(self, "lan_cfg", None):
                s["lan"] = dict(self.lan_cfg)
            try:
                s["geometry"] = self.root.geometry()
                s["maxed"] = (self.root.state() == "zoomed")
            except Exception:
                pass
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------ 局域网配置
    def _load_lan_cfg(self):
        """局域网设置（存在本机 settings.json 里，每台电脑各用各的）。"""
        cfg = dict(self.settings.get("lan") or {})
        cfg.setdefault("mode", "off")           # off / host / client
        cfg.setdefault("port", DEFAULT_PORT)
        cfg.setdefault("host", "")
        cfg.setdefault("default_allow", False)
        cfg.setdefault("client_name", socket.gethostname()[:40])
        cfg.setdefault("client_id", "%s-%04d" % (socket.gethostname(),
                                                random.randint(1000, 9999)))
        if not str(cfg.get("code") or "").strip():
            cfg["code"] = "%06d" % random.randint(0, 999999)
        return cfg

    def _save_lan_cfg(self):
        self.settings["lan"] = dict(self.lan_cfg)
        self._save_settings()

    def _add_lan_history(self, host, port, code):
        """连接成功的主机记入历史（同地址去重置顶，最多 8 条），供「历史连接」下拉用。

        存在本机 settings.json 里，不会同步给其他电脑。
        """
        hist = [h for h in (self.lan_cfg.get("history") or [])
                if isinstance(h, dict) and str(h.get("host") or "")]
        hist = [h for h in hist
                if str(h.get("host") or "") != str(host)
                or int(h.get("port") or 0) != int(port)]
        hist.insert(0, {"host": str(host), "port": int(port),
                        "code": str(code or ""), "time": time.time()})
        self.lan_cfg["history"] = hist[:8]

    def _open_store(self):
        """按局域网设置打开数据层：客户端连主机，其余情况用本机数据库。"""
        cfg = self.lan_cfg
        mode = str(cfg.get("mode") or "off")
        if mode == "client" and cfg.get("host"):
            try:
                rs = RemoteStore(cfg.get("host"), cfg.get("port") or DEFAULT_PORT,
                                 cfg.get("code") or "", cfg.get("client_id") or "",
                                 cfg.get("client_name") or "")
                info = rs.ping()
            except Exception as e:
                cfg["mode"] = "off"
                self._save_lan_cfg()
                self._lan_error = (
                    "连不上主机 %s:%s\n\n%s\n\n已切回本机数据。主机开机后，"
                    "可在「数据 → 局域网共享」里重新连接。"
                    % (cfg.get("host"), cfg.get("port"), e))
                return Store(self.db_path)
            self.lan_mode = "client"
            self.can_write = bool(info.get("can_write"))
            self._remote_wh = str(info.get("warehouse") or "主机数据")
            self._lan_rev = int(info.get("rev") or 0)
            self.db_path = rs.path
            return rs
        if mode == "host":
            self.lan_mode = "host"
        return Store(self.db_path)

    # ---------------------------------------------------------- 多仓库
    def _normalize_warehouses(self):
        """读取仓库列表；老版本 settings 没有时自动迁移为单一「主仓库」。"""
        out = []
        ws = self.settings.get("warehouses")
        if isinstance(ws, list):
            for w in ws:
                if not isinstance(w, dict):
                    continue
                name = str(w.get("name") or "").strip()[:20]
                if not name:
                    continue
                fname = os.path.basename(str(w.get("file") or "").strip())
                if not fname.lower().endswith(".db"):
                    fname = "warehouse_%d.db" % (len(out) + 1)
                out.append({"name": name, "file": fname})
        if not out:
            out = [{"name": "主仓库", "file": "warehouse.db"}]
        return out

    def _clamp_wh(self, idx):
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = 0
        if not 0 <= idx < len(self.warehouses):
            idx = 0
        return idx

    def wh_names(self):
        if self.lan_mode == "client" and self._remote_wh:
            return [self._remote_wh]
        return [w["name"] for w in self.warehouses]

    def cur_wh(self):
        if self.lan_mode == "client" and self._remote_wh:
            return {"name": self._remote_wh, "file": ""}
        return self.warehouses[self.wh_index]

    def _persist_wh(self):
        self.settings["warehouses"] = [dict(w) for w in self.warehouses]
        self.settings["current_wh"] = self.wh_index
        self._save_settings()

    def _free_wh_file(self):
        """挑一个既不在仓库列表、磁盘上也（连同 -wal/-shm）不存在的文件名。

        移除仓库时文件会保留在磁盘上，新仓库绝不能复用旧文件，
        否则新建的仓会带着被移除仓库的旧数据。
        """
        used = {w["file"] for w in self.warehouses}
        i = 2
        while True:
            f = "warehouse_%d.db" % i
            p = os.path.join(self.data_dir, f)
            if f not in used and not os.path.exists(p) \
                    and not os.path.exists(p + "-wal") \
                    and not os.path.exists(p + "-shm"):
                return f
            i += 1

    def add_warehouse(self, name, copy_from_current=False):
        """新建仓库（独立数据库）。返回 (ok, 提示)。copy=True 时复制当前仓全部数据。"""
        name = (name or "").strip()[:20]
        if not name:
            return False, "仓库名称不能为空"
        if name in self.wh_names():
            return False, "已存在同名仓库：%s" % name
        if self._busy:
            return False, "后台任务进行中，请稍后再试"
        fname = self._free_wh_file()
        path = os.path.join(self.data_dir, fname)
        try:
            if copy_from_current:
                self.store.backup_to(path)
            else:
                Store(path).close()
        except Exception as e:
            return False, "创建失败：%s" % e
        self.warehouses.append({"name": name, "file": fname})
        self._persist_wh()
        self._refresh_wh_ui()
        return True, path

    def rename_warehouse(self, idx, name):
        name = (name or "").strip()[:20]
        if not 0 <= idx < len(self.warehouses):
            return False, "仓库不存在"
        if not name:
            return False, "仓库名称不能为空"
        if name in self.wh_names() and idx != self.wh_index:
            return False, "已存在同名仓库：%s" % name
        self.warehouses[idx]["name"] = name
        self._persist_wh()
        self._refresh_wh_ui()
        return True, name

    def remove_warehouse(self, idx):
        """把仓库从列表移除（数据库文件保留在磁盘上，可手动找回）。"""
        if len(self.warehouses) <= 1:
            return False, "至少要保留一个仓库"
        if not 0 <= idx < len(self.warehouses):
            return False, "仓库不存在"
        if self._busy:
            return False, "后台任务进行中，请稍后再试"
        w = self.warehouses.pop(idx)
        if idx < self.wh_index:
            self.wh_index -= 1
        elif idx == self.wh_index:
            self._apply_warehouse(0)
        self._persist_wh()
        self._refresh_wh_ui()
        return True, os.path.join(self.data_dir, w["file"])

    def switch_warehouse(self, idx):
        """切换到第 idx 个仓库。返回 (ok, 提示)。"""
        if self.lan_mode == "client":
            return False, "客户端不能切换仓库，请在主机上切换（这边会自动跟随）"
        if not 0 <= idx < len(self.warehouses):
            return False, "仓库不存在"
        if idx == self.wh_index:
            return True, self.cur_wh()["name"]
        if self._busy:
            return False, "后台任务进行中，请稍后再试"
        self._apply_warehouse(idx)
        return True, self.cur_wh()["name"]

    def _apply_warehouse(self, idx):
        self.wh_index = idx
        wh = self.warehouses[idx]
        self._persist_wh()
        try:
            self.store.close()
        except Exception:
            pass
        self.db_path = os.path.join(self.data_dir, wh["file"])
        self.store = Store(self.db_path)
        # 换库后清空旧视图状态：筛选、排序、翻页、拖选区块、详情
        for k in self.f_vars:
            self.f_vars[k].set("全部")
        self.var_kw.set("")
        self.var_pmin.set("")
        self.var_pmax.set("")
        self.sort_key = None
        self.sort_desc = False
        self.page = 1
        self._drag_anchor = None
        self._drag_block = None
        self._block_preview = None
        self.detail_txt.delete("1.0", "end")
        self.lbl_detail_title.configure(text="未选中记录")
        self.load_data()
        self._refresh_wh_ui()
        self._on_sale_changed()

    def _refresh_wh_ui(self):
        try:
            self.var_wh.set(self.cur_wh()["name"])
            self.cb_wh["values"] = self.wh_names()
            self._update_db_label()
        except Exception:
            pass

    def _update_db_label(self):
        """状态栏的数据来源 + 窗口标题（区分本机 / 主机 / 客户端）。"""
        try:
            if self.lan_mode == "client":
                txt = "数据源：%s（主机）" % self.store.path
            elif self.lan_mode == "host":
                txt = "数据文件：%s · 共享主机端口 %s" % (
                    self.db_path, self.lan_cfg.get("port", DEFAULT_PORT))
            else:
                txt = "数据文件：%s" % self.db_path
            self.lbl_db.configure(text=txt)
        except Exception:
            pass
        try:
            suffix = {"host": " · 共享主机", "client": " · 客户端"}.get(self.lan_mode, "")
            self.root.title("%s  v%s · %s%s" % (APP_NAME, APP_VERSION,
                                               self.cur_wh()["name"], suffix))
        except Exception:
            pass

    def _on_wh_selected(self, _ev=None):
        idx = self.wh_names().index(self.var_wh.get()) \
            if self.var_wh.get() in self.wh_names() else self.wh_index
        ok, msg = self.switch_warehouse(idx)
        if not ok:
            messagebox.showwarning("切换仓库", msg, parent=self.root)
            self.var_wh.set(self.cur_wh()["name"])
        else:
            self._status("已切换到仓库「%s」，共 %d 条记录" % (msg, len(self.records)))

    def _wh_count_of(self, fname):
        """快速读某个仓库文件的记录数（只读方式，失败显示 ?）。"""
        try:
            path = os.path.join(self.data_dir, fname)
            conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"),
                                   uri=True, timeout=3)
            try:
                return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            finally:
                conn.close()
        except Exception:
            return None

    def manage_warehouses(self):
        """仓库管理对话框（卡片式）：新建 / 复制 / 切换 / 重命名 / 移除。"""
        if self.lan_mode == "client":
            messagebox.showinfo("仓库管理",
                                "客户端不能新建 / 切换仓库，请在主机上操作。\n"
                                "主机切换仓库后，这边会自动跟随。",
                                parent=self.root)
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("仓库管理")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.configure(bg=CLR_BG)
        apply_window_icon(dlg)
        W = 470

        # ---- 头部 ----
        head = tk.Frame(dlg, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x", padx=12, pady=(12, 8))
        tk.Label(head, text="仓库管理", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 13, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(head, text="每个仓库一套独立数据、独立编号（各自从 WL-00001 开始）",
                 bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9)).pack(anchor="w",
                                                                     padx=16, pady=(2, 10))

        # ---- 新建区 ----
        mk = tk.Frame(dlg, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                      highlightthickness=1)
        mk.pack(fill="x", padx=12)
        row = tk.Frame(mk, bg=CLR_CARD)
        row.pack(fill="x", padx=16, pady=12)
        tk.Label(row, text="新仓库名称", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 10)).pack(side="left", padx=(0, 8))
        var_name = tk.StringVar()
        ent = tk.Entry(row, textvariable=var_name, width=16, font=(self.fam, 10),
                       relief="flat", highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        ent.pack(side="left", ipady=3)

        def act_add(copy):
            ok, msg = self.add_warehouse(var_name.get(), copy_from_current=copy)
            if not ok:
                messagebox.showerror("新建仓库", msg, parent=dlg)
                return
            var_name.set("")
            rebuild()
            self._status("已新建仓库，数据文件：%s" % os.path.basename(msg))

        ttk.Button(row, text="新建", style="Accent.TButton",
                   command=lambda: act_add(False)).pack(side="left", padx=(10, 0))
        ttk.Button(row, text="复制当前仓新建", style="Ghost.TButton",
                   command=lambda: act_add(True)).pack(side="left", padx=(6, 0))

        # ---- 仓库卡片列表 ----
        listwrap = tk.Frame(dlg, bg=CLR_BG)
        listwrap.pack(fill="both", expand=True, padx=12, pady=8)
        canvas = tk.Canvas(listwrap, bg=CLR_BG, highlightthickness=0)
        vs = ttk.Scrollbar(listwrap, orient="vertical", command=canvas.yview)
        lst = tk.Frame(canvas, bg=CLR_BG)
        lst.bind("<Configure>",
                 lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=lst, anchor="nw", width=W - 48)
        canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win, width=e.width - 0))
        # 滚轮
        def _wheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120), "units")
        canvas.bind_all("<MouseWheel>", _wheel)

        def rebuild():
            for c in lst.winfo_children():
                c.destroy()
            n = len(self.warehouses)
            for i, w in enumerate(self.warehouses):
                card = tk.Frame(lst, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                                highlightthickness=1)
                card.pack(fill="x", pady=(0 if i == 0 else 8, 0))
                inner = tk.Frame(card, bg=CLR_CARD)
                inner.pack(fill="x", padx=14, pady=10)
                is_cur = (i == self.wh_index)
                # 左侧：名称 + 文件信息
                left = tk.Frame(inner, bg=CLR_CARD)
                left.pack(side="left", fill="x", expand=True)
                nrow = tk.Frame(left, bg=CLR_CARD)
                nrow.pack(anchor="w")
                tk.Label(nrow, text=w["name"], bg=CLR_CARD,
                         fg=CLR_ACCENT if is_cur else CLR_TEXT,
                         font=(self.fam, 11, "bold")).pack(side="left")
                if is_cur:
                    tk.Label(nrow, text=" 当前 ", bg=CLR_ACCENT, fg="#FFFFFF",
                             font=(self.fam, 8)).pack(side="left", padx=(8, 0))
                cnt = self._wh_count_of(w["file"])
                cnt_txt = "%d 条记录" % cnt if cnt is not None else "记录数未知"
                tk.Label(left, text="%s · %s" % (cnt_txt, w["file"]),
                         bg=CLR_CARD, fg=CLR_MUTED,
                         font=(self.fam, 8)).pack(anchor="w", pady=(2, 0))
                # 右侧：操作按钮
                right = tk.Frame(inner, bg=CLR_CARD)
                right.pack(side="right")
                if not is_cur:
                    def do_switch(idx=i):
                        ok, msg = self.switch_warehouse(idx)
                        if not ok:
                            messagebox.showwarning("切换仓库", msg, parent=dlg)
                        else:
                            self._status("已切换到仓库「%s」" % msg)
                        rebuild()
                    ttk.Button(right, text="切换", style="Ghost.TButton", width=5,
                               command=do_switch).pack(side="left", padx=2)

                def do_rename(idx=i):
                    name = simpledialog.askstring(
                        "重命名仓库", "新名称：", parent=dlg,
                        initialvalue=self.warehouses[idx]["name"])
                    if name is None:
                        return
                    ok, msg = self.rename_warehouse(idx, name)
                    if not ok:
                        messagebox.showerror("重命名仓库", msg, parent=dlg)
                    else:
                        rebuild()

                def do_remove(idx=i):
                    w2 = self.warehouses[idx]
                    if not messagebox.askyesno(
                            "移除仓库",
                            "把「%s」从仓库列表中移除？\n\n"
                            "数据库文件 %s 会保留在磁盘上，不会删除，"
                            "之后可在数据目录手动找回。"
                            % (w2["name"], w2["file"]), parent=dlg,
                            icon="warning"):
                        return
                    ok, msg = self.remove_warehouse(idx)
                    if not ok:
                        messagebox.showerror("移除仓库", msg, parent=dlg)
                    else:
                        rebuild()

                ttk.Button(right, text="重命名", style="Ghost.TButton", width=6,
                           command=do_rename).pack(side="left", padx=2)
                ttk.Button(right, text="移除", style="Danger.TButton", width=5,
                           command=do_remove).pack(side="left", padx=2)
            dlg.geometry("")  # 让窗口自适应内容高度
            dlg.update_idletasks()

        rebuild()

        foot = tk.Frame(dlg, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(foot, text="切换也可用顶部工具栏「仓库」下拉；移除只从列表去掉，\n"
                            "数据文件保留在数据目录，可随时手动找回。",
                 bg=CLR_BG, fg="#9AA7BA", font=(self.fam, 8),
                 justify="left").pack(side="left")
        ttk.Button(foot, text="关闭", command=dlg.destroy).pack(side="right")
        # 居中显示（跟随主窗口）
        center_window(dlg, self.root)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", lambda: (canvas.unbind_all("<MouseWheel>"),
                                                  dlg.destroy()))
        dlg.wait_window()
        try:
            canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _apply_geometry(self):
        """按当前屏幕自适应窗口尺寸（笔记本小屏直接最大化，大屏居中 1440×900）。

        · 用「桌面工作区」而不是整块屏幕 → 不会被 Win10/Win11 任务栏遮住；
        · 上次保存的尺寸只在当前屏幕放得下时采用，换机器不会跑出屏幕；
        · 最小尺寸随屏幕收缩，1366×768 笔记本也能拉满使用。
        """
        m = getattr(self, "screen_metrics", None) or screen.screen_metrics(self.root)
        fit = screen.fit_window(m, saved=self.settings.get("geometry"))
        self.root.minsize(fit["min_w"], fit["min_h"])
        if fit["maxed"] or (self.settings.get("maxed") and not fit["compact"]):
            try:
                self.root.state("zoomed")
                return
            except Exception:
                pass
        self.root.geometry("%dx%d+%d+%d" % (fit["w"], fit["h"],
                                            fit["x"], fit["y"]))

    # ============================================================ 菜单
    def _build_menubar(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="导入 XLSX…", accelerator="Ctrl+I", command=self.do_import)
        fm.add_command(label="导出 XLSX（当前结果）…", accelerator="Ctrl+S", command=self.do_export)
        fm.add_command(label="导出 XLSX（全部数据）…", command=lambda: self.do_export(all_data=True))
        fm.add_command(label="导出统计报表…", command=self.export_stats)
        fm.add_separator()
        fm.add_command(label="生成导入模板…", command=self.save_template)
        fm.add_command(label="打开数据目录", command=self.open_data_dir)
        fm.add_separator()
        fm.add_command(label="退出", command=self.on_close)
        m.add_cascade(label="文件", menu=fm)

        em = tk.Menu(m, tearoff=0)
        em.add_command(label="新增记录", accelerator="Ctrl+N", command=self.add_record)
        em.add_command(label="编辑选中", accelerator="Ctrl+E", command=self.edit_selected)
        em.add_command(label="删除选中", accelerator="Delete", command=self.delete_selected)
        em.add_separator()
        em.add_command(label="批量修改字段…", accelerator="Ctrl+B", command=self.batch_edit)
        em.add_command(label="批量上架", command=lambda: self.set_listed(1))
        em.add_command(label="批量下架", command=lambda: self.set_listed(0))
        em.add_separator()
        em.add_command(label="采购入库…", accelerator="Ctrl+P", command=self.purchase_in)
        em.add_command(label="登记出售…", accelerator="Ctrl+D", command=self.sell_selected)
        em.add_command(label="登记出库…", accelerator="Ctrl+U", command=self.out_stock_selected)
        em.add_separator()
        em.add_command(label="全选本页", accelerator="Ctrl+A", command=self.select_all)
        em.add_command(label="复制选中行", accelerator="Ctrl+C", command=self.copy_selected)
        m.add_cascade(label="编辑", menu=em)

        vm = tk.Menu(m, tearoff=0)
        self.var_show_detail = tk.BooleanVar(value=bool(self.settings.get("show_detail", True)))
        vm.add_checkbutton(label="显示详情面板", variable=self.var_show_detail,
                           command=self._toggle_detail)
        vm.add_command(label="列显示设置…", command=lambda: self._show_col_menu(
            self.toolbar_anchor_x, 40))
        vm.add_separator()
        for ps in PAGE_SIZES:
            vm.add_command(label="每页 %s 条" % ps, command=lambda p=ps: self._set_page_size(p))
        vm.add_separator()
        vm.add_command(label="刷新数据", accelerator="F5", command=lambda: self.load_data())
        m.add_cascade(label="视图", menu=vm)

        dm = tk.Menu(m, tearoff=0)
        dm.add_command(label="仓库管理…", command=self.manage_warehouses)
        dm.add_command(label="局域网共享（多台电脑共用一份数据）…",
                       command=self.open_lan)
        dm.add_separator()
        dm.add_command(label="导入 XLSX（按型号合并）…", command=self.do_import)
        dm.add_separator()
        dm.add_command(label="按型号检查重复…", command=self.check_duplicates)
        dm.add_command(label="按型号去重（清理库内重复）…", command=self.dedupe_duplicates)
        dm.add_separator()
        dm.add_command(label="采购记录…", command=self.open_purchases)
        dm.add_command(label="买家管理…", command=self.open_buyers)
        dm.add_separator()
        dm.add_command(label="低库存阈值设置…", command=self.set_low_stock)
        self.var_low_hl = tk.BooleanVar(value=False)
        dm.add_checkbutton(label="低库存橙色高亮", variable=self.var_low_hl,
                           command=self.toggle_low_hl)
        # 下架（未上架）行灰显：一眼区分下架货，默认开启
        self.var_unlisted_hl = tk.BooleanVar(value=True)
        dm.add_checkbutton(label="下架行灰显", variable=self.var_unlisted_hl,
                           command=self.toggle_unlisted_hl)
        self.var_low_only = tk.BooleanVar(value=False)
        dm.add_checkbutton(label="只看低库存", variable=self.var_low_only,
                           command=self.apply_filters)
        dm.add_separator()
        dm.add_command(label="清除全部单元格颜色（本仓库）",
                       command=lambda: self.clear_cell_colors(all_rows=True))
        dm.add_separator()
        dm.add_command(label="回收站…", command=self.open_recycle)
        dm.add_separator()
        dm.add_command(label="重新载入数据库", command=lambda: self.load_data())
        dm.add_command(label="清空全部数据…", command=self.clear_all)
        m.add_cascade(label="数据", menu=dm)

        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="使用说明", command=self.show_help)
        hm.add_command(label="关于", command=self.show_about)
        m.add_cascade(label="帮助", menu=hm)

        self.root.configure(menu=m)

    # ============================================================ 布局
    def _build(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        self.tab_inv = ttk.Frame(self.nb)
        self.tab_ana = AnalysisTab(self.nb, self, self.fam)
        self.tab_sales = SalesTab(self.nb, self, self.fam)
        self.tab_out = SalesTab(self.nb, self, self.fam, mode="out")
        self.tab_phone = PhoneTab(self.nb, self, self.fam)
        # 顺序：库存管理 | 出售记录 | 出库记录 | 数据分析 | 手机数据
        self.nb.add(self.tab_inv, text="  库存管理  ")
        self.nb.add(self.tab_sales, text="  出售记录  ")
        self.nb.add(self.tab_out, text="  出库记录  ")
        self.nb.add(self.tab_ana, text="  数据分析  ")
        self.nb.add(self.tab_phone, text="  手机数据  ")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

    def _sep(self, parent):
        s = ttk.Separator(parent, orient="vertical")
        s.pack(side="left", fill="y", padx=8, pady=10)
        return s

    def _build_toolbar(self):
        bar = tk.Frame(self.tab_inv, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=CLR_CARD)
        inner.pack(fill="x", padx=12, pady=8)
        self.toolbar_anchor_x = 40

        # 右侧搜索先 pack（side=right）：窗口不够宽时优先保住搜索框，
        # 被挤掉的是最左侧后 pack 的按钮而不是搜索框。
        sbox = tk.Frame(inner, bg=CLR_CARD)
        sbox.pack(side="right")
        tk.Label(sbox, text="搜索", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(0, 6))
        self.var_kw = tk.StringVar()
        ent = ttk.Entry(sbox, textvariable=self.var_kw, width=18, font=(self.fam, 10))
        ent.pack(side="left")
        ent.bind("<KeyRelease>", lambda e: self._debounce_apply())
        ent.bind("<Return>", lambda e: self.apply_filters())
        ttk.Button(sbox, text="重置", style="Ghost.TButton", width=5,
                   command=self.reset_filters).pack(side="left", padx=(8, 0))
        self.entry_search = ent

        # 按钮统一给显式 width：不设 width 时 ttk 在本机会渲染成固定 ~118px，
        # 按钮一多整条工具栏就超出窗口（搜索框被挤没）。
        # 仓库切换（多套数据库，每个仓独立数据与编号）
        tk.Label(inner, text="仓库", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=(0, 6))
        self.var_wh = tk.StringVar(value=self.cur_wh()["name"])
        self.cb_wh = ttk.Combobox(inner, textvariable=self.var_wh, width=11,
                                  state="readonly", font=(self.fam, 10))
        self.cb_wh["values"] = self.wh_names()
        self.cb_wh.pack(side="left")
        self.cb_wh.bind("<<ComboboxSelected>>", self._on_wh_selected)
        ttk.Button(inner, text="管理", style="Ghost.TButton", width=5,
                   command=self.manage_warehouses).pack(side="left", padx=(6, 0))
        self._sep(inner)

        ttk.Button(inner, text="导入 XLSX", style="Accent.TButton", width=9,
                   command=self.do_import).pack(side="left")
        ttk.Button(inner, text="导出", width=5,
                   command=self.do_export).pack(side="left", padx=(8, 0))
        self._sep(inner)
        ttk.Button(inner, text="＋ 新增", width=7,
                   command=self.add_record).pack(side="left")
        ttk.Button(inner, text="编辑", width=5,
                   command=self.edit_selected).pack(side="left", padx=(8, 0))
        ttk.Button(inner, text="删除", style="Danger.TButton", width=5,
                   command=self.delete_selected).pack(side="left", padx=(8, 0))
        self._sep(inner)
        ttk.Button(inner, text="批量上架", style="Ok.TButton", width=9,
                   command=lambda: self.set_listed(1)).pack(side="left")
        ttk.Button(inner, text="批量下架", width=9,
                   command=lambda: self.set_listed(0)).pack(side="left", padx=(8, 0))
        self._sep(inner)
        ttk.Button(inner, text="采购入库", width=9,
                   command=self.purchase_in).pack(side="left")
        ttk.Button(inner, text="登记出售", style="Accent.TButton", width=9,
                   command=self.sell_selected).pack(side="left", padx=(8, 0))
        # 「登记出库」不进工具栏（空间不足会挤掉后面的按钮）：
        # 入口在「出库记录」页的「+ 登记出库」按钮、编辑菜单、右键菜单与 Ctrl+U
        self._sep(inner)
        ttk.Button(inner, text="批量修改", width=9,
                   command=self.batch_edit).pack(side="left")

        # 侧栏筛选 + 表格
    def _build_body(self):
        body = tk.Frame(self.tab_inv, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=0, pady=8)

        # ---- 侧栏 ----
        side = tk.Frame(body, bg=CLR_CARD, width=int(228 * self.ui_scale),
                        highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        tk.Label(side, text="筛选条件", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 11, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Frame(side, bg=CLR_BORDER_LT, height=1).pack(fill="x", padx=16, pady=(6, 10))

        self.f_vars = {}
        self.f_combos = {}
        labels = {"brand": "品牌", "category": "品类", "condition": "成色",
                  "shelf": "货架", "listed": "上架状态"}
        for key in ("brand", "category", "condition", "shelf", "listed"):
            tk.Label(side, text=labels[key], bg=CLR_CARD, fg="#41506B",
                     font=(self.fam, 9)).pack(anchor="w", padx=16, pady=(6, 2))
            var = tk.StringVar(value="全部")
            # 品牌/品类/成色/货架允许手动输入（输入即筛，包含匹配）；
            # 上架状态是固定枚举，保持只读
            editable = key != "listed"
            cb = ttk.Combobox(side, textvariable=var, values=["全部"],
                              state="normal" if editable else "readonly",
                              font=(self.fam, 9))
            cb.pack(fill="x", padx=16)
            cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
            if editable:
                cb.bind("<KeyRelease>", lambda e: self.apply_filters())
            self.f_vars[key] = var
            self.f_combos[key] = cb

        # 低库存快捷筛选（阈值在「数据 → 低库存阈值设置」里调整）
        low_row = tk.Frame(side, bg=CLR_CARD)
        low_row.pack(fill="x", padx=16, pady=(10, 0))
        dot_check(low_row, "只看低库存", self.var_low_only,
                  command=self.apply_filters, bg=CLR_CARD,
                  fam=self.fam, size=9).pack(side="left")
        self.lbl_low = tk.Label(low_row, text="", bg=CLR_CARD, fg=CLR_WARN,
                                font=(self.fam, 8))
        self.lbl_low.pack(side="left", padx=(4, 0))

        # 低库存提醒是否橙色高亮（关掉后表格保持清爽，筛选/统计仍然可用）
        dot_check(side, "低库存橙色高亮", self.var_low_hl,
                  command=self.toggle_low_hl, bg=CLR_CARD,
                  fam=self.fam, size=9).pack(anchor="w", padx=16, pady=(2, 0))
        # 下架（未上架）行灰显：淡灰底 + 灰字，与「已上架」一眼区分
        dot_check(side, "下架行灰显", self.var_unlisted_hl,
                  command=self.toggle_unlisted_hl, bg=CLR_CARD,
                  fam=self.fam, size=9).pack(anchor="w", padx=16, pady=(2, 0))

        tk.Label(side, text="价格区间（元）", bg=CLR_CARD, fg="#41506B",
                 font=(self.fam, 9)).pack(anchor="w", padx=16, pady=(12, 2))
        pf = tk.Frame(side, bg=CLR_CARD)
        pf.pack(fill="x", padx=16)
        self.var_pmin = tk.StringVar()
        self.var_pmax = tk.StringVar()
        e1 = ttk.Entry(pf, textvariable=self.var_pmin, width=8, font=(self.fam, 9))
        e1.pack(side="left")
        tk.Label(pf, text="—", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left", padx=4)
        e2 = ttk.Entry(pf, textvariable=self.var_pmax, width=8, font=(self.fam, 9))
        e2.pack(side="left")
        for e in (e1, e2):
            e.bind("<KeyRelease>", lambda ev: self._debounce_apply())
            e.bind("<Return>", lambda ev: self.apply_filters())

        btns = tk.Frame(side, bg=CLR_CARD)
        btns.pack(fill="x", padx=16, pady=(14, 6))
        ttk.Button(btns, text="应用筛选", style="Accent.TButton",
                   command=self.apply_filters).pack(fill="x")
        ttk.Button(btns, text="重置", command=self.reset_filters).pack(fill="x", pady=(6, 0))

        tk.Frame(side, bg=CLR_BORDER_LT, height=1).pack(fill="x", padx=16, pady=(12, 8))
        self.lbl_side = tk.Label(side, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                 font=(self.fam, 9), justify="left", anchor="w")
        self.lbl_side.pack(fill="x", padx=16)

        # ---- 主区 ----
        main = tk.Frame(body, bg=CLR_BG)
        main.pack(side="left", fill="both", expand=True, padx=(10, 0))

        table_card = tk.Frame(main, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                              highlightthickness=1)
        table_card.pack(fill="both", expand=True)

        tbar = tk.Frame(table_card, bg=CLR_CARD)
        tbar.pack(fill="x", padx=10, pady=(8, 6))
        self.lbl_table_title = tk.Label(tbar, text="库存明细", bg=CLR_CARD, fg=CLR_TEXT,
                                        font=(self.fam, 10, "bold"))
        self.lbl_table_title.pack(side="left")
        self.lbl_hint = tk.Label(tbar, text="提示：双击编辑 · 鼠标划过高亮整行 · 拖选单元格即选中 · 右键可复制或「区域上色」",
                                 bg=CLR_CARD, fg="#9AA7BA", font=(self.fam, 8))
        self.lbl_hint.pack(side="right")
        dot_check(tbar, "拖选即复制", self.var_drag_copy,
                  command=self._save_drag_copy, bg=CLR_CARD,
                  fam=self.fam, size=9).pack(side="right", padx=(0, 12))

        tw = tk.Frame(table_card, bg=CLR_CARD)
        tw.pack(fill="both", expand=True, padx=10)
        self.tree = ttk.Treeview(tw, show="headings", selectmode="extended")
        vs = ttk.Scrollbar(tw, orient="vertical", style="Vertical.TScrollbar",
                           command=self._tree_yview)
        hs = ttk.Scrollbar(table_card, orient="horizontal", style="Horizontal.TScrollbar",
                           command=self._tree_xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        # 先给滚动条占位，再让表格伸展：反过来的话窗口一缩小，
        # 表格会把滚动条挤没（pack 按顺序分配空间）
        vs.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        hs.pack(side="bottom", fill="x", padx=10, pady=(0, 6), before=tw)

        # Treeview 的 tag 优先级由「创建先后」决定（先创建的先胜，与 tags 列表顺序无关），
        # 所以要按下面的优先级从高到低依次创建：
        #   鼠标划过 > 下架灰 > 低库存橙 > 斑马纹
        # 划过高亮最先建，才能盖住下架灰/低库存橙/斑马纹（v1.10.7）
        self.hover = RowHover(self.tree, self.root)
        self.hover.on_change = self._on_hover_change
        # 下架（未上架）：淡灰底 + 灰字，与已上架一眼区分
        self.tree.tag_configure("unlisted", background="#F1F3F7", foreground="#667085")
        self.tree.tag_configure("low", background="#FFF3E2", foreground="#B54708")
        self.tree.tag_configure("oos", foreground="#B54708")
        self.tree.tag_configure("sold", foreground="#98A2B3")
        # 斑马纹放最后：优先级最低，不会压住上面的底色
        self.tree.tag_configure("odd", background="#F7FAFD")

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<B1-Motion>", self._on_drag)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_end)
        self.tree.bind("<Button-3>", self.on_right_click)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Control-c>", self._on_ctrl_c)
        # 滚动/改变尺寸/键盘上下移动后，上色贴片要重新贴合单元格
        # 滚轮自己做主（见 _on_wheel）：Tk 自带滚动在实例绑定之后执行，
        # 交给它滚动的话贴片会停在滚动前的像素位置，颜色看起来就"没了"
        self.tree.bind("<MouseWheel>", self._on_wheel)
        self.tree.bind("<Configure>", lambda e: self._after_scroll_soon(), add="+")
        self.tree.bind("<KeyPress>", lambda e: self._after_scroll_soon(), add="+")
        self.tree.bind("<KeyRelease>", lambda e: self._after_scroll_soon(), add="+")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._after_scroll_soon(), add="+")

        self._build_pager(table_card)
        self._build_detail(main)

    def _tree_yview(self, *args):
        """滚动条回调：滚动后让上色贴片跟着单元格走。"""
        self.tree.yview(*args)
        self._after_scroll()

    def _tree_xview(self, *args):
        self.tree.xview(*args)
        self._after_scroll()

    def _build_pager(self, parent):
        p = tk.Frame(parent, bg=CLR_CARD)
        p.pack(fill="x", padx=10, pady=(0, 8))
        self.lbl_page = tk.Label(p, text="", bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9))
        self.lbl_page.pack(side="left")

        r = tk.Frame(p, bg=CLR_CARD)
        r.pack(side="right")
        self.var_psize = tk.StringVar(value=("全部" if not self.page_size else str(self.page_size)))
        cb = ttk.Combobox(r, textvariable=self.var_psize, values=PAGE_SIZES, width=6,
                          state="readonly", font=(self.fam, 9))
        cb.pack(side="right", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._set_page_size(self.var_psize.get()))
        tk.Label(r, text="每页", bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9)).pack(side="right")

        for text, cmd in (("末页 »", lambda: self.goto_page(10 ** 9)),
                          ("下一页 ›", lambda: self.goto_page(self.page + 1)),
                          ("‹ 上一页", lambda: self.goto_page(self.page - 1)),
                          ("« 首页", lambda: self.goto_page(1))):
            ttk.Button(r, text=text, style="Ghost.TButton", width=7,
                       command=cmd).pack(side="right", padx=2)

    def _build_detail(self, parent):
        self.detail_card = tk.Frame(parent, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                                    highlightthickness=1)
        head = tk.Frame(self.detail_card, bg=CLR_CARD)
        head.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(head, text="记录详情", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 10, "bold")).pack(side="left")
        self.lbl_detail_title = tk.Label(head, text="未选中记录", bg=CLR_CARD, fg=CLR_MUTED,
                                         font=(self.fam, 9))
        self.lbl_detail_title.pack(side="left", padx=10)
        ttk.Button(head, text="复制本条", style="Ghost.TButton",
                   command=self.copy_detail).pack(side="right")
        ttk.Button(head, text="复制为 JSON", style="Ghost.TButton",
                   command=self.copy_detail_json).pack(side="right", padx=(0, 6))

        self.detail_txt = tk.Text(self.detail_card, height=6, relief="flat", bd=0,
                                  bg=CLR_CARD, fg=CLR_TEXT, font=(self.fam, 9),
                                  wrap="word", padx=12, pady=6, cursor="arrow",
                                  selectbackground=CLR_ACCENT, selectforeground="#FFFFFF")
        self.detail_txt.pack(fill="both", expand=True)
        try:  # 制表位：让框选区块的列对齐显示
            self.detail_txt.configure(tabs=("3c", "13c", "24c", "35c", "45c",
                                            "55c", "65c", "75c"))
        except tk.TclError:
            pass
        self.detail_txt.tag_configure("k", foreground="#6B7A8F")
        self.detail_txt.tag_configure("v", foreground=CLR_TEXT)
        self.detail_txt.bind("<Key>", self._readonly_key)
        dm = tk.Menu(self.detail_txt, tearoff=0)
        dm.add_command(label="复制选中内容", command=self.copy_detail_selection)
        dm.add_command(label="复制全部内容", command=self.copy_detail)
        self._detail_menu = dm
        self.detail_txt.bind("<Button-3>", lambda e: dm.tk_popup(e.x_root, e.y_root))

        if self.var_show_detail.get():
            self.detail_card.pack(fill="x", pady=(10, 0))
            self.detail_card.pack_configure(ipady=2)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(fill="x", side="bottom")
        inner = tk.Frame(bar, bg=CLR_CARD)
        inner.pack(fill="x", padx=12, pady=4)
        self.lbl_status = tk.Label(inner, text="就绪", bg=CLR_CARD, fg=CLR_MUTED,
                                   font=(self.fam, 9), anchor="w")
        self.lbl_status.pack(side="left")
        self.pbar = ttk.Progressbar(inner, mode="indeterminate", length=140)
        self.lbl_db = tk.Label(inner, text="数据文件：%s" % self.db_path, bg=CLR_CARD,
                               fg="#9AA7BA", font=(self.fam, 8))
        self.lbl_db.pack(side="right", padx=(0, 16))

    # ============================================================ 数据
    def load_data(self, first=False):
        try:
            self.records = self.store.all_records()
        except Exception as e:
            messagebox.showerror("读取失败", "无法读取数据库：\n%s" % e, parent=self.root)
            self.records = []
        self._load_prefs()
        self._reload_choices()
        self.apply_filters(keep_page=first)
        self._status("已载入 %d 条记录" % len(self.records))

    def _load_prefs(self):
        """读取随仓库保存的偏好（低库存阈值、高亮开关、月度销售目标）。"""
        self.low_threshold = int(self.store.get_num("low_stock_threshold", 3))
        # 手动上色的单元格（随仓库保存在 meta 里）
        self.cell_colors = self._load_cell_colors()
        try:
            self.var_low_hl.set(bool(int(self.store.get_num("low_stock_highlight", 0))))
        except Exception:
            pass
        try:
            self.var_unlisted_hl.set(bool(int(self.store.get_num("unlisted_shade", 1))))
        except Exception:
            pass
        try:
            self.lbl_low.configure(text="≤%d 件" % self.low_threshold)
        except Exception:
            pass

    def _reload_choices(self):
        mapping = {
            "brand": self.store.distinct("brand"),
            "category": self.store.distinct("category"),
            "condition": self.store.distinct("condition"),
            "shelf": self.store.distinct("shelf"),
        }
        for key, vals in mapping.items():
            cur = self.f_vars[key].get()
            opts = ["全部"] + list(vals)
            self.f_combos[key]["values"] = opts
            if cur not in opts:
                self.f_vars[key].set("全部")
        self.lst_values = ["全部", "已上架", "未上架", "已售完"]
        self.f_combos["listed"]["values"] = self.lst_values

    def _debounce_apply(self):
        if self._debounce:
            try:
                self.root.after_cancel(self._debounce)
            except Exception:
                pass
        self._debounce = self.root.after(320, self.apply_filters)

    def apply_filters(self, keep_page=False):
        kw = (self.var_kw.get() or "").strip().lower()
        f = {k: self.f_vars[k].get() for k in self.f_vars}
        try:
            pmin = float(self.var_pmin.get()) if self.var_pmin.get().strip() else None
        except ValueError:
            pmin = None
        try:
            pmax = float(self.var_pmax.get()) if self.var_pmax.get().strip() else None
        except ValueError:
            pmax = None

        low_only = bool(getattr(self, "var_low_only", None) and self.var_low_only.get())
        thr = int(getattr(self, "low_threshold", 3) or 0)
        # 品牌/品类/成色/货架：手动输入也支持（不区分大小写包含匹配，空或「全部」= 不过滤）
        ftext = {}
        for fkey in ("brand", "category", "condition", "shelf"):
            v = (f[fkey] or "").strip().lower()
            ftext[fkey] = v if v and v != "全部" else None
        out = []
        for r in self.records:
            if low_only:
                if int(r.get("sold_out") or 0):
                    continue
                if thr <= 0 or int(r.get("qty") or 0) > thr:
                    continue
            if ftext["brand"] and ftext["brand"] not in str(r.get("brand") or "").lower():
                continue
            if ftext["category"] and ftext["category"] not in str(r.get("category") or "").lower():
                continue
            if ftext["condition"] and ftext["condition"] not in str(r.get("condition") or "").lower():
                continue
            # 多货架记录（「6排A-3 / 7排A-1」）按拆分后的任一货架位命中
            if ftext["shelf"] and not any(
                    ftext["shelf"] in p.lower() for p in shelf_parts(r.get("shelf"))):
                continue
            if f["listed"] != "全部":
                sold = int(r.get("sold_out") or 0)
                if f["listed"] == "已售完":
                    if not sold:
                        continue
                else:
                    want = 1 if f["listed"] == "已上架" else 0
                    if sold or int(r.get("listed") or 0) != want:
                        continue
            price = float(r.get("price") or 0)
            if pmin is not None and price < pmin:
                continue
            if pmax is not None and price > pmax:
                continue
            if kw:
                blob = " ".join(str(r.get(k) or "") for k in
                                ("code", "brand", "category", "model",
                                 "condition", "shelf", "remark")).lower()
                if kw not in blob:
                    continue
            out.append(r)

        self.filtered = self._sort(out)
        if not keep_page:
            self.page = 1
        self.render_page()
        self._update_side_stats()

    def _sort(self, rows):
        if not self.sort_key:
            return rows
        key = self.sort_key
        t = FIELD_TYPE[key]

        def kf(r):
            v = r.get(key)
            if t in ("money", "int", "bool"):
                try:
                    return float(v or 0)
                except (TypeError, ValueError):
                    return 0.0
            return str(v or "").lower()

        try:
            return sorted(rows, key=kf, reverse=self.sort_desc)
        except Exception:
            return rows

    def _set_page_size(self, val):
        self.page_size = 0 if str(val) == "全部" else int(val)
        self.var_psize.set(str(val))
        self.page = 1
        self.render_page()

    def goto_page(self, p):
        self.page = max(1, int(p))
        self.render_page()
        self.tree.yview_moveto(0)

    def _goto_last_page(self):
        """跳到最后一页并滚到底部（默认升序时，最新/新增的记录在末尾）。"""
        self.page = 10 ** 9
        self.render_page()          # render_page 内部会把页码钳制到有效范围
        self.tree.yview_moveto(1.0)

    def _focus_record(self, rid):
        """定位到指定记录：必要时翻到它所在的页，然后选中并滚动可见。"""
        iid = str(rid)
        if iid in self.by_id:
            self.tree.selection_set(iid)
            self.tree.see(iid)
            return True
        ids = [str(r["id"]) for r in self.filtered]
        if iid not in ids:
            return False
        if self.page_size:
            self.page = ids.index(iid) // self.page_size + 1
            self.render_page()
        iid = str(rid)
        if iid in self.by_id:
            self.tree.selection_set(iid)
            self.tree.see(iid)
            return True
        return False

    # ------------------------------------------------------------ 渲染
    def _cols(self):
        return [c for c in FIELD_KEYS if c in self.visible_cols]

    def _setup_columns(self):
        cols = self._cols()
        if list(self.tree["columns"]) != cols:
            self.tree["columns"] = cols
        titles = self.store.col_titles()      # 手机端/电脑端共享的自定义列题
        for c in cols:
            arrow = ""
            if self.sort_key == c:
                arrow = " ▼" if self.sort_desc else " ▲"
            elif self.sort_key is None and c == "code":
                arrow = " ▲"      # 默认按编号升序
            self.tree.heading(c, text=(titles.get(c) or FIELD_LABEL[c]) + arrow,
                              command=lambda cc=c: self.sort_column(cc))
            self.tree.column(c, width=int(FIELD_WIDTH[c] * self.ui_scale),
                             minwidth=int(60 * self.ui_scale),
                             anchor=FIELD_ANCHOR[c], stretch=(c in ("remark",)))

    @staticmethod
    def fmt(field, rec):
        v = rec.get(field)
        t = FIELD_TYPE[field]
        if t == "bool":
            if int(rec.get("sold_out") or 0):
                return "已售完"
            return LISTED_TEXT.get(int(v or 0), "未上架")
        if t == "money":
            return "%.2f" % float(v or 0)
        if t == "int":
            return str(int(v or 0))
        return "" if v is None else str(v)

    def render_page(self):
        self._setup_columns()
        # 重新渲染后原有的框选区块已失效，清掉避免复制到错行
        self._drag_anchor = None
        self._drag_block = None
        self._block_preview = None
        # 行全部重建，划过的高亮（挂在旧行上）作废
        if self.hover:
            self.hover.reset()
        self.tree.delete(*self.tree.get_children())
        total = len(self.filtered)
        size = self.page_size or total or 1
        pages = max(1, int(math.ceil(total / float(size)))) if total else 1
        self.page = min(max(1, self.page), pages)
        start = 0 if not self.page_size else (self.page - 1) * self.page_size
        end = total if not self.page_size else start + self.page_size
        cols = self._cols()
        self.by_id = {}
        hl = self._low_hl_on()
        un_hl = self._unlisted_hl_on()
        for i, rec in enumerate(self.filtered[start:end]):
            rid = str(rec["id"])
            self.by_id[rid] = rec
            tags = ["odd"] if i % 2 else []
            if int(rec.get("sold_out") or 0):
                tags.append("sold")          # 已售完：灰显
            else:
                # 下架灰显（后加的 low/oos 会覆盖灰底，低库存橙色优先）
                if un_hl and not int(rec.get("listed") or 0):
                    tags.append("unlisted")
                if hl:
                    q = int(rec.get("qty") or 0)
                    thr = int(getattr(self, "low_threshold", 0) or 0)
                    if q == 0:
                        tags.append("oos")
                    elif 0 < thr and q <= thr:
                        tags.append("low")   # 低库存：橙色底提醒补货
            self.tree.insert("", "end", iid=rid,
                             values=[self.fmt(c, rec) for c in cols], tags=tuple(tags))
        self.lbl_page.configure(
            text="共 %d 条记录 · 第 %d/%d 页 · 本页 %d 条（勾选/多选后可批量操作）"
                 % (total, self.page, pages, max(0, end - start)))
        self._update_detail()
        self._paint_overlays()

    def sort_column(self, col):
        if self.sort_key == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = col, False
        self.filtered = self._sort(self.filtered)
        self.render_page()

    def _update_side_stats(self):
        total = len(self.records)
        shown = len(self.filtered)
        listed = sum(1 for r in self.filtered if int(r.get("listed") or 0))
        qty = sum(int(r.get("qty") or 0) for r in self.filtered)
        val = sum(float(r.get("price") or 0) * int(r.get("qty") or 0) for r in self.filtered)
        thr = int(getattr(self, "low_threshold", 0) or 0)
        # 与「只看低库存」筛选口径一致：排除已售完，数量为 0（缺货）也计入
        low = sum(1 for r in self.filtered
                  if not int(r.get("sold_out") or 0)
                  and int(r.get("qty") or 0) <= thr) if thr > 0 else 0
        self.lbl_side.configure(
            text="命中 %s / %s 条\n已上架 %s 条\n库存合计 %s 件\n货值 ¥%s%s"
                 % ("{:,}".format(shown), "{:,}".format(total), "{:,}".format(listed),
                    "{:,}".format(qty), "{:,.2f}".format(val),
                    ("\n低库存 %d 条" % low) if low else ""))

    # ------------------------------------------------------------ 选中
    def _selected_records(self):
        out = []
        for iid in self.tree.selection():
            r = self.by_id.get(str(iid))
            if r:
                out.append(r)
        return out

    def on_select(self, _e=None):
        self._update_detail()

    def _update_detail(self):
        blk = self._block_preview
        if blk:
            rows = [i for i in blk["rows"] if i in self.by_id]
            if rows:
                blk["rows"] = rows
                self._render_block_detail(blk)
                return
            self._block_preview = None
        recs = self._selected_records()
        self.detail_txt.configure(state="normal")
        self.detail_txt.delete("1.0", "end")
        if not recs:
            self.lbl_detail_title.configure(text="未选中记录")
            self.detail_txt.insert("end", "在上方表格中单击任意一行查看完整字段，内容可直接选中复制。\n",
                                   "k")
            self.detail_txt.insert("end", "在表格里按住鼠标左键划过若干单元格即可框选区块，"
                                          "松开鼠标自动复制，内容同时显示在这里。", "k")
        elif len(recs) == 1:
            r = recs[0]
            self.lbl_detail_title.configure(
                text="%s  ·  %s" % (r.get("code") or "无编号", r.get("brand") or ""))
            for k in FIELD_KEYS:
                self.detail_txt.insert("end", "%s：" % FIELD_LABEL[k], "k")
                self.detail_txt.insert("end", "%s\n" % self.fmt(k, r), "v")
        else:
            self.lbl_detail_title.configure(text="已选中 %d 条记录" % len(recs))
            self.detail_txt.insert("end", "多选 %d 条记录：\n" % len(recs), "k")
            for r in recs[:40]:
                self.detail_txt.insert(
                    "end", "· %s | %s | ¥%s × %s\n" % (
                        r.get("code") or "-", r.get("brand") or "-",
                        self.fmt("price", r), self.fmt("qty", r)), "v")
            if len(recs) > 40:
                self.detail_txt.insert("end", "… 其余 %d 条略\n" % (len(recs) - 40), "k")

    def _render_block_detail(self, blk):
        """把鼠标框选的区块显示在详情区（这里的文字同样可以用鼠标拖选复制）。"""
        cols = self._cols()
        sel = cols[blk["c0"]:blk["c1"] + 1]
        recs = [self.by_id[i] for i in blk["rows"] if i in self.by_id]
        self.detail_txt.configure(state="normal")
        self.detail_txt.delete("1.0", "end")
        self.lbl_detail_title.configure(
            text="已框选 %d 行 × %d 列（鼠标可在此拖选复制）" % (len(recs), len(sel)))
        self.detail_txt.insert("end", "编号：" + "　".join(
            "%s" % (r.get("code") or "-") for r in recs[:6]) +
            ("　…共 %d 条" % len(recs) if len(recs) > 6 else "") + "\n", "k")
        self.detail_txt.insert("end", "\t".join(FIELD_LABEL[c] for c in sel) + "\n", "k")
        for r in recs[:60]:
            self.detail_txt.insert("end", "\t".join(
                self.fmt(c, r).replace("\t", " ").replace("\n", " ") for c in sel) + "\n", "v")
        if len(recs) > 60:
            self.detail_txt.insert("end", "… 其余 %d 行略\n" % (len(recs) - 60), "k")
        if blk.get("copied"):
            self.detail_txt.insert("end", "内容已复制到剪贴板，可直接粘贴进 Excel。\n", "k")
        else:
            self.detail_txt.insert("end", "按 Ctrl+C 复制整块内容，"
                                          "或直接用鼠标在此拖选后复制。\n", "k")
        self.detail_txt.see("1.0")

    def _readonly_key(self, event):
        if (event.state & 0x4) and event.keysym.lower() in ("c", "a", "x"):
            return None
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End",
                            "Prior", "Next", "Shift_L", "Shift_R",
                            "Control_L", "Control_R"):
            return None
        return "break"

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())
        self._update_detail()

    # ============================================================ 复制
    def _clip(self, text, msg="已复制到剪贴板"):
        if not text:
            self._status("没有可复制的内容")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
            self._status("%s（%d 个字符）" % (msg, len(text)))
        except Exception as e:
            self._status("复制失败：%s" % e)

    def _tsv(self, records, cols=None):
        """复制为 TSV（纯数据，不带表头行，可直接粘贴进 Excel）。"""
        cols = cols or self._cols()
        lines = []
        for r in records:
            lines.append("\t".join(self.fmt(c, r).replace("\t", " ").replace("\n", " ")
                                   for c in cols))
        return "\n".join(lines)

    def copy_selected(self):
        recs = self._selected_records()
        if not recs:
            self._status("请先选中要复制的行")
            return
        self._clip(self._tsv(recs), "已复制 %d 行" % len(recs))

    def copy_cell(self):
        col = self._cell_col if self._cell_col in self._cols() else self._cols()[0]
        iid = self.tree.focus()
        rec = self.by_id.get(str(iid))
        if not rec:
            self._status("请先点击要复制的单元格")
            return
        self._clip(self.fmt(col, rec), "已复制「%s」" % FIELD_LABEL[col])

    def copy_row(self):
        iid = self.tree.focus()
        rec = self.by_id.get(str(iid))
        if not rec:
            recs = self._selected_records()
            rec = recs[0] if recs else None
        if not rec:
            self._status("请先选中一行")
            return
        lines = ["%s：%s" % (FIELD_LABEL[k], self.fmt(k, rec)) for k in FIELD_KEYS]
        self._clip("\n".join(lines), "已复制整行")

    def copy_column(self):
        col = self._cell_col if self._cell_col in self._cols() else self._cols()[0]
        recs = self._selected_records() or self.filtered
        self._clip("\n".join(self.fmt(col, r) for r in recs),
                   "已复制「%s」列 %d 项" % (FIELD_LABEL[col], len(recs)))

    def copy_all(self):
        if not self.filtered:
            self._status("没有可复制的数据")
            return
        self._clip(self._tsv(self.filtered), "已复制全部筛选结果 %d 行" % len(self.filtered))

    def copy_block(self, silent=True):
        """复制鼠标拖选出来的单元格区块（可直接粘贴进 Excel）。"""
        blk = self._drag_block or self._block_preview
        if not blk:
            if not silent:
                self._status("没有选中区块")
            return
        cols = self._cols()
        sel = cols[blk["c0"]:blk["c1"] + 1]
        recs = [self.by_id[i] for i in blk["rows"] if i in self.by_id]
        if not recs:
            self._status("选中的内容已不在当前页")
            return
        self._clip(self._tsv(recs, sel),
                   "已复制选中区块（%d 行 × %d 列）" % (len(recs), len(sel)))
        blk["copied"] = True
        self._block_preview = blk
        self._update_detail()

    def copy_detail(self):
        recs = self._selected_records()
        if not recs:
            self._clip(self.detail_txt.get("1.0", "end").strip(), "已复制详情内容")
            return
        if len(recs) == 1:
            r = recs[0]
            self._clip("\n".join("%s：%s" % (FIELD_LABEL[k], self.fmt(k, r)) for k in FIELD_KEYS),
                       "已复制本条记录")
        else:
            self._clip(self._tsv(recs), "已复制 %d 条记录" % len(recs))

    def copy_detail_json(self):
        recs = self._selected_records()
        if not recs:
            self._status("请先选中一行")
            return
        data = recs[0] if len(recs) == 1 else recs
        payload = {k: data.get(k) for k in FIELD_KEYS} if len(recs) == 1 else \
            [{k: r.get(k) for k in FIELD_KEYS} for r in data]
        self._clip(json.dumps(payload, ensure_ascii=False, indent=2), "已复制 JSON")

    def copy_detail_selection(self):
        try:
            sel = self.detail_txt.get("sel.first", "sel.last")
        except tk.TclError:
            sel = self.detail_txt.get("1.0", "end").strip()
        self._clip(sel, "已复制选中内容")

    # ============================================================ 事件
    def _cell_at(self, x, y):
        """把鼠标坐标换算成 (行 iid, 列下标)；不在数据单元格上则返回 (None, None)。"""
        if self.tree.identify_region(x, y) != "cell":
            return None, None
        iid = self.tree.identify_row(y)
        col = self.tree.identify_column(x)
        try:
            idx = int(str(col).replace("#", "")) - 1
        except (TypeError, ValueError):
            return None, None
        cols = self._cols()
        if iid and 0 <= idx < len(cols):
            return str(iid), idx
        return None, None

    def _row_span(self, iid_a, iid_b):
        """按表格当前显示顺序返回 a、b 两行之间的全部行 iid。"""
        children = self.tree.get_children()
        try:
            i = children.index(iid_a)
            j = children.index(iid_b)
        except ValueError:
            return [iid_b]
        return list(children[min(i, j):max(i, j) + 1])

    def _on_click(self, event, reset_block=True):
        # 记录拖选起点（每次按下都重置上一次的区块选择）
        # reset_block=False 用于右键：右键坐标落在框选区块内时要保住区块，
        # 否则「框选→右键上色」会退化成只给选中行上色
        if reset_block:
            self._drag_anchor = None
            self._drag_block = None
            self._block_preview = None
        iid, idx = self._cell_at(event.x, event.y)
        if iid is not None:
            self._drag_anchor = (iid, idx)
        if self.tree.identify_region(event.x, event.y) == "cell":
            cols = self._cols()
            if 0 <= idx < len(cols):
                self._cell_col = cols[idx]

    def _in_drag_block(self, x, y):
        """右键坐标是否落在当前框选区块内（是则右键不该打散区块）。"""
        blk = self._drag_block or self._block_preview
        if not blk or not blk.get("rows"):
            return False
        iid, idx = self._cell_at(x, y)
        if iid is None:
            return False
        return (str(iid) in [str(r) for r in blk["rows"]]
                and blk["c0"] <= idx <= blk["c1"])

    def _on_drag(self, event):
        """鼠标按住划过单元格：记录选区（行区间 × 列区间）。"""
        if not self._drag_anchor:
            # 按下时落在贴片等控件上、锚点丢失：用当前格子补一个锚点
            iid0, idx0 = self._cell_at(event.x, event.y)
            if iid0 is None:
                return
            self._drag_anchor = (iid0, idx0)
        iid, idx = self._cell_at(event.x, event.y)
        if iid is None:
            return
        a_iid, a_idx = self._drag_anchor
        if iid == a_iid and idx == a_idx:
            return
        rows = self._row_span(a_iid, iid)
        c0, c1 = min(a_idx, idx), max(a_idx, idx)
        self._drag_block = {"rows": rows, "c0": c0, "c1": c1}
        cols = self._cols()
        self._status("已选中区块：%d 行 × %d 列（%s ~ %s）%s" % (
            len(rows), c1 - c0 + 1, FIELD_LABEL[cols[c0]], FIELD_LABEL[cols[c1]],
            "，松开鼠标即复制" if self.var_drag_copy.get() else "，按 Ctrl+C 复制"))

    def _on_drag_end(self, _event=None):
        self._drag_anchor = None
        if not self._drag_block:
            return
        if self.var_drag_copy.get():
            self.copy_block(silent=False)
        else:
            self._drag_block["copied"] = False
            self._block_preview = self._drag_block
            self._update_detail()

    def _on_ctrl_c(self, _event=None):
        if self._drag_block:
            self.copy_block()
        else:
            self.copy_selected()
        return "break"

    def _copy_shortcut(self, _event=None):
        """全局 Ctrl+C：按当前标签页把表格内容复制到剪贴板。

        焦点在输入框 / 文本框里时直接放行（走系统自带的文本复制）。
        库存页表格自己有绑定并会中断事件，不会重复复制。
        """
        try:
            w = self.root.focus_get()
        except Exception:
            w = None
        if isinstance(w, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox)):
            return None
        try:
            idx = self.nb.index(self.nb.select())
        except Exception:
            return None
        if idx == 1:
            self.tab_sales.copy_shortcut()
        elif idx == 2:
            self.tab_out.copy_shortcut()
        elif idx == 0 and w is not self.tree:
            self._on_ctrl_c()
        return "break"

    def _save_drag_copy(self):
        self.settings["drag_copy"] = bool(self.var_drag_copy.get())
        self._save_settings()

    def on_double(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        rec = self.by_id.get(str(iid))
        if not rec:
            return
        col = self._cell_col
        if col == "listed":
            m = tk.Menu(self.root, tearoff=0)
            for text, val in (("已上架", 1), ("未上架", 0)):
                m.add_command(
                    label=text,
                    command=lambda v=val: self._set_one_listed(rec, v))
            m.tk_popup(event.x_root, event.y_root)
            return
        self.edit_record(rec)

    def _set_one_listed(self, rec, val):
        self.store.set_listed([rec["id"]], val)
        rec["listed"] = val
        iid = str(rec["id"])
        self.render_page()
        if iid in self.tree.get_children():
            self.tree.selection_set(iid)
            self.tree.see(iid)
        self._status("已设为「%s」：%s" % (LISTED_TEXT[val], rec.get("code") or ""))

    def on_right_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "heading":
            self._show_col_menu(event.x_root, event.y_root)
            return
        if region != "cell":
            return
        iid = self.tree.identify_row(event.y)
        keep_block = self._in_drag_block(event.x, event.y)
        if iid and str(iid) not in self.tree.selection() and not keep_block:
            self.tree.selection_set(str(iid))
        self.tree.focus(iid)
        self._on_click(event, reset_block=not keep_block)
        self._update_detail()

        recs = self._selected_records()
        n = len(recs)
        one = recs[0] if n == 1 else None
        m = tk.Menu(self.root, tearoff=0)
        blk = self._drag_block or self._block_preview
        if blk:
            bcols = self._cols()
            bsel = bcols[blk["c0"]:blk["c1"] + 1]
            m.add_command(label="复制框选区块（%d 行 × %d 列）" % (len(blk["rows"]), len(bsel)),
                          command=self.copy_block)
        m.add_command(label="复制单元格（%s）" % FIELD_LABEL.get(self._cell_col, ""),
                      command=self.copy_cell)
        m.add_command(label="复制整行（字段: 值）", command=self.copy_row)
        m.add_command(label="复制选中行（%d 行 · 可直接粘贴 Excel）" % n, command=self.copy_selected)
        m.add_command(label="复制「%s」整列" % FIELD_LABEL.get(self._cell_col, ""),
                      command=self.copy_column)
        m.add_command(label="复制全部筛选结果（%d 行）" % len(self.filtered), command=self.copy_all)
        m.add_separator()
        # ---- 手动上色 / 取消颜色（框选区块优先，否则作用于选中行）----
        targets = self._paint_targets()
        if blk:
            tlabel = "框选区块（%d 行 × %d 列）" % (len(blk["rows"]),
                                                  blk["c1"] - blk["c0"] + 1)
        else:
            tlabel = "选中 %d 行（整行）" % n if n else "请先框选或选中行"
        pm = tk.Menu(m, tearoff=0)
        for name, colr in self.PAINT_COLORS:
            pm.add_command(label="■ %s" % name, background=colr, foreground="#33404F",
                           command=lambda c=colr: self.paint_cells(c))
        pm.add_separator()
        pm.add_command(label="自定义颜色…", command=self.pick_cell_color,
                       state="normal" if targets else "disabled")
        pm.add_separator()
        pm.add_command(label="取消选区颜色（%d 个单元格）" % len(targets),
                       command=self.clear_cell_colors,
                       state="normal" if targets else "disabled")
        pm.add_command(label="取消全部颜色…（本仓库所有页）",
                       command=lambda: self.clear_cell_colors(all_rows=True),
                       state="normal" if self.cell_colors else "disabled")
        m.add_cascade(label="区域上色 · %s" % tlabel, menu=pm,
                      state="normal" if targets else "disabled")
        m.add_separator()
        m.add_command(label="采购入库…", command=self.purchase_in,
                      state="normal" if one else "disabled")
        m.add_command(label="登记出售…", command=self.sell_selected,
                      accelerator="Ctrl+D")
        m.add_command(label="登记出库…", command=self.out_stock_selected,
                      accelerator="Ctrl+U",
                      state="normal" if one else "disabled")
        m.add_command(label="编辑该记录", command=self.edit_selected,
                      state="normal" if one else "disabled")
        m.add_command(label="批量修改字段…（%d 行）" % n, command=self.batch_edit,
                      state="normal" if n else "disabled")
        m.add_command(label="上架", command=lambda: self.set_listed(1))
        m.add_command(label="下架", command=lambda: self.set_listed(0))
        m.add_separator()
        m.add_command(label="删除选中（%d · 可回收）" % n, command=self.delete_selected,
                      state="normal" if n else "disabled")
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _show_col_menu(self, x, y):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="显示全部列", command=self._show_all_cols)
        m.add_separator()
        for k in FIELD_KEYS:
            v = tk.BooleanVar(value=k in self.visible_cols)
            m.add_checkbutton(label=FIELD_LABEL[k], variable=v,
                              command=lambda kk=k, vv=v: self._toggle_col(kk, vv.get()))
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _toggle_col(self, key, on):
        if on and key not in self.visible_cols:
            self.visible_cols = [c for c in FIELD_KEYS if c in self.visible_cols + [key]]
        elif not on and key in self.visible_cols:
            if len(self.visible_cols) <= 1:
                return
            self.visible_cols = [c for c in self.visible_cols if c != key]
        self.render_page()
        self._save_settings()

    def _show_all_cols(self):
        self.visible_cols = list(FIELD_KEYS)
        self.render_page()
        self._save_settings()

    def _toggle_detail(self):
        if self.var_show_detail.get():
            self.detail_card.pack(fill="x", pady=(10, 0))
        else:
            self.detail_card.pack_forget()
        self.settings["show_detail"] = self.var_show_detail.get()
        self._save_settings()

    def _on_tab_changed(self, _e=None):
        try:
            idx = self.nb.index(self.nb.select())
            # 标签顺序：0 库存管理 / 1 出售记录 / 2 出库记录 / 3 数据分析 / 4 手机数据
            if idx == 1:
                self.tab_sales.refresh_tab()
            elif idx == 2:
                self.tab_out.refresh_tab()
            elif idx == 3:
                self.tab_ana.refresh()
            elif idx == 4:
                self.tab_phone.refresh_tab()
        except Exception:
            pass

    # ============================================================ CRUD
    def suggestions(self):
        return {"brand": self.store.distinct("brand"),
                "category": self.store.distinct("category"),
                "condition": self.store.distinct("condition"),
                "shelf": self.store.distinct("shelf")}

    def add_record(self):
        if self._guard_write():
            return
        rec = ask_record(self.root, None, self.suggestions(), "新增记录", self.fam)
        if not rec:
            return
        if not rec.get("code"):
            rec["code"] = self.store.generate_codes(1)[0]
        rid = self.store.insert(rec)
        self.load_data()
        # 升序排列时新记录在末尾，主动定位过去让用户看到
        if not self._focus_record(rid):
            self._goto_last_page()
        self._status("已新增记录：%s" % (rec.get("code") or ""))

    def edit_selected(self):
        if self._guard_write():
            return
        recs = self._selected_records()
        if not recs:
            self._status("请先选中要编辑的记录")
            return
        if len(recs) > 1:
            self._status("一次只能编辑一条，请单选")
            return
        self.edit_record(recs[0])

    def edit_record(self, rec):
        out = ask_record(self.root, rec, self.suggestions(), "编辑记录", self.fam)
        if not out:
            return
        if not out.get("code"):
            out["code"] = self.store.generate_codes(1)[0]
        self.store.update(rec["id"], out)
        cur = self.tree.selection()
        self.load_data()
        if cur:
            self._focus_record(cur[0])      # 排序字段变化时也能定位回原记录
        self._status("已保存：%s" % (out.get("code") or ""))

    def delete_selected(self):
        if self._guard_write():
            return
        recs = self._selected_records()
        if not recs:
            self._status("请先选中要删除的记录")
            return
        names = "、".join((r.get("code") or "无编号") for r in recs[:3])
        if not messagebox.askyesno(
                "确认删除",
                "确定删除选中的 %d 条记录吗？\n\n%s%s\n\n"
                "删除的记录会先进「回收站」，可随时恢复（数据 → 回收站）。"
                % (len(recs), names, "…" if len(recs) > 3 else ""), parent=self.root):
            return
        n = self.store.delete_ids([r["id"] for r in recs])
        self.load_data()
        self._status("已删除 %d 条记录（可在「数据 → 回收站」恢复）" % n)

    def set_listed(self, val):
        recs = self._selected_records()
        if not recs:
            self._status("请先选中记录")
            return
        n = self.store.set_listed([r["id"] for r in recs], val)
        self.load_data()
        self._status("已%s %d 条记录" % ("上架" if val else "下架", n))

    # ------------------------------------------------------------ 登记出库
    def sell_selected(self):
        """登记一笔出库：扣减库存；「销售」计金额，其它类型只扣库存并留痕。"""
        if self._guard_write():
            return
        recs = self._selected_records()
        if not recs:
            self._status("请先选中要出库的记录")
            return
        if len(recs) > 1:
            self._status("请只选中一行再登记出库")
            return
        rec = recs[0]
        if int(rec.get("qty") or 0) <= 0:
            messagebox.showinfo("登记出库",
                                "「%s」当前库存为 0，无法出库。"
                                % (rec.get("code") or "无编号"), parent=self.root)
            return
        data = ask_sale(self.root, rec, self.fam, buyers=self.store.buyer_names(),
                        addr_map=self.store.buyer_address_map())
        if not data:
            return
        ok, msg = self.store.add_sale(rec["id"], data["qty"], data["price"],
                                      data["buyer"], data["sale_date"], data["remark"],
                                      data.get("out_type"), data.get("address", ""))
        if not ok:
            messagebox.showerror("登记出库失败", msg, parent=self.root)
            return
        self.load_data()
        self._on_sale_changed()
        self._status(msg)

    def _on_sale_changed(self):
        """出库数据变化后同步出售记录页与出库记录页。"""
        try:
            self.tab_sales.refresh_rows()
        except Exception:
            pass
        try:
            self.tab_out.refresh_rows()
        except Exception:
            pass

    # ------------------------------------------------------------ 登记出库（非销售）
    def out_stock_selected(self):
        """登记一笔非销售出库（报废/损耗/退货/借出/赠送/调拨/其他），只扣库存。"""
        if self._guard_write():
            return
        recs = self._selected_records()
        if not recs:
            self._status("请先选中要出库的记录")
            return
        if len(recs) > 1:
            self._status("请只选中一行再登记出库")
            return
        rec = recs[0]
        if int(rec.get("qty") or 0) <= 0:
            messagebox.showinfo("登记出库",
                                "「%s」当前库存为 0，无法出库。"
                                % (rec.get("code") or "无编号"), parent=self.root)
            return
        data = ask_sale(self.root, rec, self.fam, mode="out")
        if not data:
            return
        ok, msg = self.store.add_sale(rec["id"], data["qty"], data["price"],
                                      data["buyer"], data["sale_date"], data["remark"],
                                      data.get("out_type"))
        if not ok:
            messagebox.showerror("登记出库失败", msg, parent=self.root)
            return
        self.load_data()
        self._on_sale_changed()
        self._status(msg)

    # ------------------------------------------------------------ 采购入库
    def purchase_in(self):
        """登记一笔采购入库：增加库存数量并更新成本单价。"""
        if self._guard_write():
            return
        recs = self._selected_records()
        if not recs:
            self._status("请先选中要入库的记录")
            return
        if len(recs) > 1:
            self._status("请只选中一行再登记采购")
            return
        rec = recs[0]
        data = ask_purchase(self.root, rec, self.fam)
        if not data:
            return
        ok, msg = self.store.add_purchase(rec["id"], data["qty"], data["unit_cost"],
                                          data["supplier"], data["purchase_date"],
                                          data["remark"])
        if not ok:
            messagebox.showerror("采购入库失败", msg, parent=self.root)
            return
        self.load_data()
        self._status(msg)

    def open_purchases(self):
        PurchaseListDialog(self, self.fam)

    # ------------------------------------------------------------ 买家
    def open_buyers(self):
        BuyerDialog(self, self.fam)

    # ------------------------------------------------------------ 回收站
    def open_recycle(self):
        RecycleBinDialog(self, self.fam)

    # ------------------------------------------------------------ 批量修改
    def batch_edit(self):
        """选中多行后统一修改若干字段。"""
        if self._guard_write():
            return
        recs = self._selected_records()
        if not recs:
            self._status("请先选中要批量修改的记录")
            return
        dlg = BatchEditDialog(self, self.fam)
        self.root.wait_window(dlg.win)
        if not dlg.result:
            return
        ids = [r["id"] for r in recs]
        n = self.store.batch_update(ids, dlg.result)
        keep = list(self.tree.selection())
        self.load_data()
        try:
            self.tree.selection_set([i for i in keep if i in self.by_id])
        except Exception:
            pass
        names = "、".join(FIELD_LABEL.get(k, k) for k in dlg.result)
        self._status("已批量修改 %d 条记录的：%s" % (n, names))

    # ------------------------------------------------------------ 低库存
    def _low_hl_on(self):
        """低库存橙色高亮是否开启（默认不高亮，避免一打开满屏橙色）。"""
        try:
            return bool(self.var_low_hl.get())
        except Exception:
            return False

    def toggle_low_hl(self):
        """切换低库存橙色高亮，选择随仓库保存。关掉后筛选与统计仍然可用。"""
        on = self._low_hl_on()
        val = 1 if on else 0
        self.store.set_meta("low_stock_highlight", val)
        self.settings["low_stock_highlight"] = val
        self._save_settings()
        self.render_page()
        self._status("低库存橙色高亮已%s" % ("开启" if on else "关闭"))

    # ------------------------------------------------- 下架（未上架）灰显
    def _unlisted_hl_on(self):
        """下架行灰显是否开启（默认开启，方便一眼区分没上架的货）。"""
        try:
            return bool(self.var_unlisted_hl.get())
        except Exception:
            return True

    def toggle_unlisted_hl(self):
        """切换下架行灰显（淡灰底 + 灰字），选择随仓库保存。"""
        on = self._unlisted_hl_on()
        val = 1 if on else 0
        self.store.set_meta("unlisted_shade", val)
        self.settings["unlisted_shade"] = val
        self._save_settings()
        self.render_page()
        self._status("下架行灰显已%s" % ("开启" if on else "关闭"))

    # ------------------------------------------------- 手动区域上色 / 取消颜色
    # 说明：Tk 的 Treeview 只能整行着色（tag 作用于整行），做不到单个单元格上色。
    # 这里用「贴片」方案：对用户上过色的单元格，在表格上方按单元格 bbox 放一个
    # 同位置、同字号的 Label（底色 = 用户选的颜色，文字 = 单元格内容），
    # 于是可以像 Excel 一样给任意「行 × 列」区域上色；表格本身不动，
    # 排序 / 分页 / 拖选复制 / 右键菜单全部照旧。
    PAINT_COLORS = (("淡红", "#FFD9D9"), ("淡橙", "#FFE7CC"), ("淡黄", "#FFF6C2"),
                    ("淡绿", "#D8F2D8"), ("淡青", "#CFF0F5"), ("淡蓝", "#D6E4FF"),
                    ("淡紫", "#E6DBFF"), ("淡灰", "#E9ECF1"))

    def _load_cell_colors(self):
        """读取本仓库保存的单元格颜色：{"记录id": {"列名": "#RRGGBB"}}。"""
        try:
            raw = self.store.get_meta("cell_colors", "") or ""
            data = json.loads(raw) if str(raw).strip() else {}
            if isinstance(data, dict):
                out = {}
                for k, v in data.items():
                    if isinstance(v, dict) and v:
                        out[str(k)] = {str(kk): str(vv) for kk, vv in v.items()}
                return out
        except Exception:
            pass
        return {}

    def _save_cell_colors(self):
        try:
            self.store.set_meta("cell_colors",
                                json.dumps(self.cell_colors, ensure_ascii=False))
        except Exception:
            pass

    def _paint_targets(self):
        """要上色/取消颜色的单元格：优先鼠标框选的区块，否则用选中的整行。"""
        cols = self._cols()
        blk = self._drag_block or self._block_preview
        cells = []
        if blk and blk.get("rows"):
            sel = cols[blk["c0"]:blk["c1"] + 1]
            for iid in blk["rows"]:
                if str(iid) in self.by_id:
                    cells.extend((str(iid), c) for c in sel)
            return cells
        for iid in self.tree.selection():
            if str(iid) in self.by_id:
                cells.extend((str(iid), c) for c in cols)
        return cells

    def paint_cells(self, color):
        """给框选区块（或选中行）上色，颜色随仓库永久保存。"""
        cells = self._paint_targets()
        if not cells:
            self._status("请先用鼠标框选要上色的单元格，或先选中若干行")
            return
        rows, colset = set(), set()
        for iid, key in cells:
            self.cell_colors.setdefault(str(iid), {})[key] = color
            rows.add(iid)
            colset.add(key)
        self._save_cell_colors()
        self._paint_overlays()
        self._update_detail()
        self._status("已给 %d 行 × %d 列（%d 个单元格）上色"
                     % (len(rows), len(colset), len(cells)))

    def clear_cell_colors(self, all_rows=False):
        """取消颜色：默认只清框选区块/选中行；all_rows=True 清空全部。"""
        if all_rows:
            n = sum(len(v) for v in self.cell_colors.values())
            self.cell_colors = {}
            self._save_cell_colors()
            self._paint_overlays()
            self._status("已取消全部单元格颜色（共 %d 个）" % n)
            return
        cells = self._paint_targets()
        if not cells:
            self._status("请先框选要取消颜色的单元格，或先选中若干行")
            return
        n = 0
        for iid, key in cells:
            row = self.cell_colors.get(str(iid))
            if row and key in row:
                row.pop(key, None)
                n += 1
            if row is not None and not row:
                self.cell_colors.pop(str(iid), None)
        self._save_cell_colors()
        self._paint_overlays()
        self._update_detail()
        self._status("已取消 %d 个单元格的颜色" % n)

    def pick_cell_color(self):
        """自定义颜色：打开系统取色器，给框选区块上色。"""
        from tkinter import colorchooser
        cur = "#FFD9D9"
        cells = self._paint_targets()
        if cells:
            cur = self.cell_colors.get(cells[0][0], {}).get(cells[0][1], cur)
        try:
            rgb = colorchooser.askcolor(color=cur, parent=self.root,
                                        title="选择单元格颜色")
        except Exception:
            return
        if rgb and rgb[1]:
            self.paint_cells(rgb[1])

    def _forget_overlays(self):
        for lb in self._paint_labels:
            try:
                lb.destroy()
            except Exception:
                pass
        self._paint_labels = []

    # ------------------------------------------------ 鼠标划过整行高亮（v1.10.7）
    def _on_hover_change(self, old, new):
        """划过的是上色行：贴片盖住了背景色，改描边作为划过提示（不重建贴片）。"""
        if self._row_has_paint(old) or self._row_has_paint(new):
            self._update_hover_outline()

    def _row_has_paint(self, iid):
        return bool(iid and self.cell_colors.get(str(iid)))

    def _update_hover_outline(self):
        """划过/离开上色行时只改描边，不重建贴片（鼠标下的控件被销毁会抖）。"""
        sel = set(self.tree.selection())
        for lb in self._paint_labels:
            rid = getattr(lb, "_row_iid", None)
            if rid is None or rid in sel:
                continue                      # 选中行由选中描边负责
            try:
                if rid == self.hover.row:
                    lb.configure(highlightthickness=1,
                                 highlightbackground=CLR_HOVER_EDGE,
                                 highlightcolor=CLR_HOVER_EDGE)
                else:
                    lb.configure(highlightthickness=0)
            except Exception:
                pass

    def _on_wheel(self, event):
        """滚轮：自己滚 + 立刻重画贴片（返回 break，避免 Tk 再滚一次）。

        Tk 的类绑定滚动发生在实例绑定之后，只挂重画钩子的话，贴片永远停在
        滚动前的像素位置；上色行滚出可视区后 `_paint_labels` 归零，
        再滚回来也不会重画 → 上色数据"颜色没了"（v1.10.6 修复）。
        """
        try:
            step = -1 if int(getattr(event, "delta", 0) or 0) > 0 else 1
            self.tree.yview_scroll(step, "units")
        except Exception:
            return None
        self._after_scroll()
        return "break"

    def _after_scroll_soon(self):
        """把重画推迟到本轮事件处理结束（idle）——避开类绑定/选中动作在后的情况。"""
        if self._scroll_job is not None:
            return
        try:
            self._scroll_job = self.root.after_idle(self._do_scroll_job)
        except Exception:
            self._scroll_job = None

    def _do_scroll_job(self):
        self._scroll_job = None
        self._after_scroll()

    def _has_paintable(self):
        """当前页是否有已上色的单元格（滚出可视区也算，滚回来要能重画）。"""
        if not self.cell_colors or not self.by_id:
            return False
        try:
            cols = self._cols()
        except Exception:
            return False
        for iid, row in self.cell_colors.items():
            if str(iid) in self.by_id and any(k in cols for k in row):
                return True
        return False

    def _after_scroll(self):
        """滚动/尺寸变化后重新贴合贴片。

        注意：判据必须是"这一页有没有上色单元格"，不能是"当前有没有贴片"——
        上色行滚出可视区后贴片为 0，用贴片数量当开关会让颜色再也回不来。
        """
        if self.hover:
            self.hover.sync()       # 行位置变了，划过的高亮要跟着换行
        if self._has_paintable():
            self._paint_overlays()
        elif self._paint_labels:
            self._forget_overlays()

    def _head_height(self):
        """表头高度：表格滚到顶时第一行 bbox 的 y 就是内容区上沿。"""
        try:
            if self.tree.yview()[0] <= 0.0:
                kids = self.tree.get_children()
                if kids:
                    bb = self.tree.bbox(kids[0])
                    if bb:
                        self._head_h = int(bb[1])
        except Exception:
            pass
        return int(self._head_h or 0)

    def _paint_overlays(self):
        """把已上色的单元格用同位置贴片画出来（只画当前页）。"""
        self._forget_overlays()
        if not self.cell_colors:
            return
        try:
            if not self.tree.winfo_exists() or not self.by_id:
                return
            font = ttk.Style().lookup("Treeview", "font") or (self.fam, 10)
        except Exception:
            font = (self.fam, 10)
        cols = self._cols()
        sel = set(self.tree.selection())
        head_h = self._head_height()
        for iid, row in self.cell_colors.items():
            rec = self.by_id.get(str(iid))
            if rec is None:
                continue
            for key, color in row.items():
                if key not in cols:
                    continue
                try:
                    bbox = self.tree.bbox(str(iid), column=key)
                except Exception:
                    bbox = None
                if not bbox or int(bbox[2]) <= 1 or int(bbox[3]) <= 1:
                    continue
                if int(bbox[1]) < head_h:
                    continue   # 半行被表头压住：不画，免得贴片盖到表头上
                is_sel = str(iid) in sel
                lb = tk.Label(self.tree, text=self.fmt(key, rec), bg=color,
                              fg=CLR_TEXT, font=font,
                              anchor=FIELD_ANCHOR.get(key, "center"),
                              bd=0, highlightthickness=0)
                if is_sel:
                    # 所在行被选中：蓝描边 + 加粗，避免贴片盖住系统选中高亮看不出选中
                    lb.configure(highlightthickness=2,
                                 highlightbackground=CLR_ACCENT,
                                 highlightcolor=CLR_ACCENT)
                    lb.configure(font=tkfont.Font(font=font, weight="bold"))
                elif str(iid) == self.hover.row:
                    # 划过的行：贴片盖住了背景色，用淡蓝描边代替整行高亮
                    lb.configure(highlightthickness=1,
                                 highlightbackground=CLR_HOVER_EDGE,
                                 highlightcolor=CLR_HOVER_EDGE)
                lb.place(x=int(bbox[0]), y=int(bbox[1]),
                         width=int(bbox[2]), height=int(bbox[3]))
                lb._row_iid = str(iid)     # 划过时按行改描边（不重建贴片）
                self._bind_overlay_events(lb)
                self._paint_labels.append(lb)

    def _bind_overlay_events(self, lb):
        """贴片也要能拖选 / 双击 / 右键 / 滚轮，否则鼠标经过上色格子就断了。"""
        def _map(event):
            tree = self.tree
            ev = type("Ev", (), {})()
            ev.x = event.x_root - tree.winfo_rootx()
            ev.y = event.y_root - tree.winfo_rooty()
            ev.x_root = event.x_root
            ev.y_root = event.y_root
            return ev

        def _press(event):
            ev = _map(event)
            # 按下贴片时同步选中该行：与普通格子的行为一致，
            # 且拖选区块万一没形成时，「按选中行上色」也不会落到别的行上
            iid, _idx = self._cell_at(ev.x, ev.y)
            if iid:
                try:
                    self.tree.selection_set(iid)
                    self.tree.focus(iid)
                except Exception:
                    pass
            self._on_click(ev)
        lb.bind("<Button-1>", _press)
        lb.bind("<B1-Motion>", lambda e: self._on_drag(_map(e)))
        lb.bind("<ButtonRelease-1>", lambda e: self._on_drag_end(_map(e)))
        lb.bind("<Double-1>", lambda e: self.on_double(_map(e)))
        lb.bind("<Button-3>", lambda e: self.on_right_click(_map(e)))
        # 鼠标停在上色格子上滚轮：由贴片接管，滚动后重画（否则滚不动）
        lb.bind("<MouseWheel>", self._on_wheel)
        # 划过贴片时把整行高亮维持在贴片所在行（贴片挡住了 tree 的 Motion/Enter）
        lb.bind("<Motion>", self.hover._on_motion)
        lb.bind("<Enter>", self.hover._on_motion)
        lb.bind("<Leave>", self.hover._on_leave)

    def set_low_stock(self):
        cur = int(getattr(self, "low_threshold", 3) or 0)
        v = ask_name(self.root, "低库存阈值设置",
                     "请输入低库存阈值（数量 ≤ 该值的记录可用「低库存」筛出，\n"
                     "开启高亮后还会橙色提醒；高亮开关在左侧筛选区或「数据」菜单）：",
                     str(cur), self.fam)
        if v is None:
            return
        try:
            val = int(float(str(v).strip() or 0))
        except ValueError:
            messagebox.showwarning("低库存阈值", "请填写整数。", parent=self.root)
            return
        if val < 0:
            messagebox.showwarning("低库存阈值", "阈值不能为负数。", parent=self.root)
            return
        self.low_threshold = val
        self.store.set_meta("low_stock_threshold", val)
        self.settings["low_stock_threshold"] = val
        self._save_settings()
        self._load_prefs()
        self.apply_filters()
        self._status("低库存阈值已设为 %d 件" % val)

    def _auto_backup(self, tag):
        """清空/覆盖前自动备份当前数据库，返回备份路径（失败返回 None）。"""
        if self.lan_mode == "client":
            return None        # 客户端没有本地库，备份由主机负责
        try:
            bak_dir = os.path.join(os.path.dirname(self.db_path), "backups")
            os.makedirs(bak_dir, exist_ok=True)
            path = os.path.join(bak_dir, "自动备份_%s_%s_%s.db"
                                % (self.cur_wh()["name"], tag,
                                   datetime.now().strftime("%Y%m%d_%H%M%S")))
            self.store.backup_to(path)
            return path
        except Exception:
            return None

    def clear_all(self):
        if self._guard_write():
            return
        if not messagebox.askyesno(
                "危险操作",
                "将删除数据库中的全部 %d 条记录（连同出库记录）。\n\n"
                "清空后编号计数器会归零，下一次导入将从 WL-00001 重新开始编号。\n"
                "清空前会自动备份一份到 data\\backups（可随时找回）。\n\n确定继续吗？"
                % len(self.records), parent=self.root, icon="warning"):
            return
        if not messagebox.askyesno("再次确认", "真的要清空全部数据吗？", parent=self.root,
                                   icon="warning"):
            return
        bak = self._auto_backup("清空前")
        self.store.clear_all(purge_sales=True)
        self.load_data()
        self._on_sale_changed()
        if bak:
            self._status("已清空全部数据，编号将从 WL-00001 重新开始 · 已备份到 %s"
                         % os.path.basename(bak))
        else:
            self._status("已清空全部数据，编号将从 WL-00001 重新开始")

    # ============================================================ 重复检查
    def dedupe_duplicates(self):
        """一键清理库中重复：相同型号/相同内容只保留最早一条。"""
        preview = self.store.dedupe_db(dry_run=True)
        if preview["deleted"] == 0:
            messagebox.showinfo("按型号去重", "库中没有重复记录，无需清理。", parent=self.root)
            return
        if not messagebox.askyesno(
                "按型号去重",
                "检测到 %d 条重复记录（%d 组）。\n\n"
                "将只保留每组最早录入的一条，其余删除，此操作不可撤销。\n"
                "建议先「导出 XLSX（全部数据）」备份。\n\n确定继续吗？"
                % (preview["deleted"], preview["groups"]),
                parent=self.root, icon="warning"):
            return
        res = self.store.dedupe_db()
        self.load_data()
        msg = "去重完成：已删除 %d 条重复记录（%d 组），每组保留最早一条。" % (
            res["deleted"], res["groups"])
        messagebox.showinfo("去重完成", msg, parent=self.root)
        self._status("已去重：删除 %d 条重复记录" % res["deleted"])

    def check_duplicates(self):
        """按型号列出库中重复录入的记录（只读，可复制）。"""
        dups = self.store.duplicate_models()
        win = tk.Toplevel(self.root)
        win.title("按型号检查重复")
        win.configure(bg=CLR_BG)
        win.transient(self.root)
        apply_window_icon(win)
        center_window(win, self.root, size=(760, 520))

        head = tk.Frame(win, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x")
        tk.Label(head, text="按「型号」检查重复", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 12, "bold")).pack(side="left", padx=16, pady=12)
        tk.Label(head,
                 text="共 %d 个型号存在重复（合计 %d 条记录）"
                      % (len(dups), sum(d[1] for d in dups)),
                 bg=CLR_CARD, fg=CLR_MUTED, font=(self.fam, 9)).pack(side="left")

        bar = tk.Frame(win, bg=CLR_BG)
        bar.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(bar, text="可在此手动处理重复项；或用菜单「数据 → 按型号去重」一键清理"
                           "（每组保留最早一条）。",
                 bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 9)).pack(side="left")

        wrap = tk.Frame(win, bg=CLR_CARD, highlightbackground=CLR_BORDER, highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=14, pady=10)
        cols = ("model", "n", "codes", "brand", "price", "shelf", "listed")
        heads = ("型号", "重复条数", "编号", "品牌", "价格", "货架", "上架状态")
        tree = ttk.Treeview(wrap, columns=cols, show="headings")
        vs = ttk.Scrollbar(wrap, orient="vertical", style="Vertical.TScrollbar",
                           command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        for c, h, w in zip(cols, heads, (190, 80, 150, 130, 90, 120, 90)):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor="center" if c != "model" else "w",
                        stretch=(c in ("model", "codes")))
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        lines = []
        for model, n, rows in dups:
            codes = "、".join(str(r.get("code") or "") for r in rows)
            r0 = rows[0]
            tree.insert("", "end", values=(
                model, n, codes, r0.get("brand") or "", "%.2f" % float(r0.get("price") or 0),
                r0.get("shelf") or "", LISTED_TEXT.get(int(r0.get("listed") or 0), "")))
            lines.append("%s\t%d\t%s" % (model, n, codes))

        foot = tk.Frame(win, bg=CLR_BG)
        foot.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(foot, text="复制内容可直接粘贴进 Excel", bg=CLR_BG, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="left")

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append("型号\t重复条数\t编号\n" + "\n".join(lines))
            self._status("重复型号列表已复制")

        if not dups:
            tk.Label(wrap, text="没有发现重复型号，数据很干净。", bg=CLR_CARD,
                     fg=CLR_OK, font=(self.fam, 11)).pack(pady=40)
        ttk.Button(foot, text="复制列表", style="Ghost.TButton", command=copy,
                   width=10).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="关闭", width=10, command=win.destroy).pack(side="right")
        center_window(win, self.root, size=(760, 520))
        win.bind("<Escape>", lambda e: win.destroy())

    # ============================================================ 导入导出
    def do_import(self):
        if self._guard_write():
            return
        path = filedialog.askopenfilename(
            title="选择要导入的 Excel 文件", parent=self.root,
            filetypes=[("Excel 工作簿", "*.xlsx *.xlsm"), ("所有文件", "*.*")])
        if not path:
            return
        res = ask_import(self.root, path, self.fam,
                         existing_models=self.store.model_keys(),
                         existing_blank=self.store.blank_content_keys())
        if not res:
            return
        mode = res["mode"]
        records = res["records"]

        def fill_codes(items):
            """给没有编号的行补上自动编号（一次生成，避免重号）。"""
            missing = [r for r in items if not str(r.get("code") or "").strip()]
            if missing:
                codes = iter(self.store.generate_codes(len(missing)))
                for r in missing:
                    r["code"] = next(codes)
            return len(missing)

        self._run_bg(lambda: self._import_work(mode, records),
                     lambda r, e: self._import_done(res, r, e),
                     "正在导入 %d 条数据…" % len(records))

    def _fill_codes(self, store, items):
        """给没有编号的行补上自动编号（一次生成，避免重号）。"""
        missing = [r for r in items if not str(r.get("code") or "").strip()]
        if missing:
            codes = iter(store.generate_codes(len(missing)))
            for r in missing:
                r["code"] = next(codes)
        return len(missing)

    def _import_work(self, mode, records, store=None):
        """执行导入的核心逻辑（后台线程可调用，不弹任何对话框）。

        返回 dict: mode / added / skipped / merged(文件内去重条数) / auto / note
        """
        store = store or self.store
        # 统一类型转换（数量「1+1」→ 2、价格千分位、是否上架等），
        # 否则原始字符串到 _vals 的 int(float(v)) 会异常变 0
        records = [normalize_record(r) for r in records]
        dedup_n = 0
        recs = records
        if mode == MODE_REPLACE:
            # 覆盖导入：文件内按型号去重（相同型号/相同内容只保留一条）
            # 追加导入不去重，原样全部写入
            recs, dedup_n = dedupe_records(records)
        if mode == MODE_MERGE:
            if not any(not is_blank_model(r.get("model")) for r in recs):
                auto = self._fill_codes(store, recs)
                n = store.insert_many(recs)
                return {"mode": MODE_APPEND, "added": n, "skipped": 0,
                        "merged": dedup_n, "auto": auto,
                        "note": "数据中没有「型号」列，已按追加导入处理。"}
            out = store.merge_many(recs, "model")
            out["mode"] = MODE_MERGE
            out["merged"] = out.get("merged", 0) + dedup_n
            return out
        if mode == MODE_REPLACE:
            # 覆盖导入：先备份、再清空数据并重置编号计数器，从 WL-00001 重新编号
            bak = self._auto_backup("覆盖导入前")
            store.clear_all()
            auto = self._fill_codes(store, recs)
            n = store.insert_many(recs)
            return {"mode": mode, "added": n, "skipped": 0,
                    "merged": dedup_n, "auto": auto,
                    "backup": bak}
        auto = self._fill_codes(store, recs)
        n = store.insert_many(recs)
        return {"mode": mode, "added": n, "skipped": 0,
                "merged": dedup_n, "auto": auto}

    def _import_done(self, res, result, err):
        self._end_busy()
        if err:
            messagebox.showerror("导入失败", str(err), parent=self.root)
            return
        self.load_data()
        if result.get("added"):
            # 升序排列时新增记录在末尾，主动翻到最后一页
            self._goto_last_page()
        rm = result["mode"]
        if rm == MODE_MERGE:
            txt = "新增 %d 条，跳过重复 %d 条（库中原记录未改动）" % (
                result["added"], result.get("skipped", 0))
        elif rm == MODE_REPLACE:
            txt = "覆盖导入 %d 条" % result["added"]
        else:
            txt = "追加导入 %d 条" % result["added"]
        msg = "导入完成\n\n工作表：%s\n方式：%s\n结果：%s" % (
            res["sheet"], MODE_TEXT[rm], txt)
        if result.get("merged"):
            msg += ("\n\n文件内共有 %d 条重复数据（相同型号或相同内容），已去重，只保留一条。"
                    % result["merged"])
        if result.get("auto"):
            msg += "\n\n已为 %d 条无编号记录自动生成编号。" % result["auto"]
        if result.get("backup"):
            msg += "\n\n覆盖前已自动备份到：\n%s" % result["backup"]
        if result.get("note"):
            msg += "\n\n提示：%s" % result["note"]
        messagebox.showinfo("导入完成", msg, parent=self.root)
        self._status(txt)

    def do_export(self, all_data=False):
        recs = self.records if all_data else self.filtered
        if not recs:
            messagebox.showinfo("无数据", "当前没有可导出的数据。", parent=self.root)
            return
        default = "库存数据_%s.xlsx" % datetime.now().strftime("%Y%m%d_%H%M")
        path = filedialog.asksaveasfilename(
            title="导出为 XLSX", parent=self.root, defaultextension=".xlsx",
            initialfile=default, filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        self._run_bg(lambda: xlsxio.export_xlsx(path, recs),
                     lambda r, e: self._export_done(r, e, path, len(recs)),
                     "正在导出…")

    def _export_done(self, _r, err, path, n):
        self._end_busy()
        if err:
            messagebox.showerror("导出失败", str(err), parent=self.root)
            return
        self._status("已导出 %d 条到 %s" % (n, os.path.basename(path)))
        if messagebox.askyesno("导出完成", "已导出 %d 条记录到：\n%s\n\n是否打开所在文件夹？"
                                           % (n, path), parent=self.root):
            self._open_folder(os.path.dirname(path))

    def export_stats(self):
        self.tab_ana.refresh()
        recs = self.records_for_analysis(self.tab_ana._scope.get())
        if not recs:
            messagebox.showinfo("无数据", "当前范围内没有可统计的数据。", parent=self.root)
            return
        default = "库存统计报表_%s_%s.xlsx" % (self.cur_wh()["name"],
                                              datetime.now().strftime("%Y%m%d_%H%M"))
        path = filedialog.asksaveasfilename(
            title="导出统计报表", parent=self.root, defaultextension=".xlsx",
            initialfile=default, filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        stats = self.store.stats(recs)
        scope = self.tab_ana.scope_text

        def work():
            return xlsxio.export_stats_xlsx(path, recs, stats, scope)

        self._run_bg(work, lambda r, e: self._export_done(r, e, path, len(recs)),
                     "正在生成统计报表…")

    def save_template(self):
        path = filedialog.asksaveasfilename(
            title="保存导入模板", parent=self.root, defaultextension=".xlsx",
            initialfile="仓库导入模板.xlsx", filetypes=[("Excel 工作簿", "*.xlsx")])
        if not path:
            return
        try:
            xlsxio.write_template(path)
            self._status("模板已保存到 %s" % os.path.basename(path))
            if messagebox.askyesno("模板已生成", "导入模板已保存到：\n%s\n\n是否立即打开？" % path,
                                   parent=self.root):
                self._open_file(path)
        except Exception as e:
            messagebox.showerror("生成失败", str(e), parent=self.root)

    # ============================================================ 分析
    def records_for_analysis(self, scope):
        return self.records if scope == "all" else self.filtered

    # ============================================================ 后台
    def _run_bg(self, work, done, busy_text="处理中…"):
        if self._busy:
            self._status("已有任务在执行，请稍候…")
            return
        self._busy = True
        try:
            self.pbar.pack(side="right", padx=(10, 0))
            self.pbar.start(12)
        except Exception:
            pass
        self._status(busy_text)

        def runner():
            try:
                result = work()
                self._ui(done, result, None)
            except Exception as e:
                self._ui(done, None, e)

        threading.Thread(target=runner, daemon=True).start()

    def _end_busy(self):
        self._busy = False
        try:
            self.pbar.stop()
            self.pbar.pack_forget()
        except Exception:
            pass

    def _ui(self, fn, *args):
        self._ui_queue.put((fn, args))

    def _pump(self):
        if self._stopped:
            return
        for _ in range(200):
            try:
                fn, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:
                pass
        try:
            self.root.after(80, self._pump)
        except tk.TclError:
            self._stopped = True

    # ============================================================ 杂项
    def _status(self, text):
        if threading.current_thread() is not threading.main_thread():
            self._ui(self._status, text)
            return
        try:
            self.lbl_status.configure(text="%s  ·  %s" % (datetime.now().strftime("%H:%M:%S"), text))
        except Exception:
            pass

    def reset_filters(self):
        for k in self.f_vars:
            self.f_vars[k].set("全部")
        self.var_kw.set("")
        self.var_pmin.set("")
        self.var_pmax.set("")
        self.apply_filters()

    def _open_folder(self, path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system('open "%s"' % path)
            else:
                os.system('xdg-open "%s"' % path)
        except Exception:
            pass

    def open_data_dir(self):
        self._open_folder(self.data_dir)

    def _open_file(self, path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system('open "%s"' % path)
            else:
                os.system('xdg-open "%s"' % path)
        except Exception as e:
            messagebox.showerror("打开失败", str(e), parent=self.root)

    def _bind_shortcuts(self):
        b = self.root.bind
        b("<Control-i>", lambda e: self.do_import())
        b("<Control-s>", lambda e: self.do_export())
        b("<Control-n>", lambda e: self.add_record())
        b("<Control-e>", lambda e: self.edit_selected())
        b("<Control-d>", lambda e: self.sell_selected())
        b("<Control-u>", lambda e: self.out_stock_selected())
        b("<Control-b>", lambda e: self.batch_edit())
        b("<Control-p>", lambda e: self.purchase_in())
        # Ctrl+C：库存页/出售页/出库页都复制表格内容（输入框里仍是普通文本复制）
        b("<Control-c>", self._copy_shortcut)
        b("<Control-f>", lambda e: self.entry_search.focus_set())
        b("<F5>", lambda e: self.load_data())

    def show_help(self):
        """使用说明：独立窗口（左目录 + 可滚动正文 + 搜索），避免 messagebox 截断。"""
        from .help import HelpDialog, help_sections
        HelpDialog(self.root, help_sections(self.db_path), self.fam, APP_VERSION)

    def show_about(self):
        messagebox.showinfo(
            "关于",
            "%s\n版本 %s\n\n纯本地运行的仓库管理工具，数据保存在本机 SQLite 数据库，\n"
            "不联网、不上传，支持 Excel 导入导出与多维数据分析。\n\n数据目录：\n%s"
            % (APP_NAME, APP_VERSION, self.data_dir), parent=self.root)

    # ============================================================ 局域网共享
    def open_lan(self):
        """打开「局域网共享」窗口（主机开关 / 连接主机 / 授权录入）。"""
        from .lanui import LanDialog
        LanDialog(self.root, self)

    def lan_status(self):
        srv = self.lan_server
        return {
            "mode": self.lan_mode,
            "port": int(self.lan_cfg.get("port") or DEFAULT_PORT),
            "code": str(self.lan_cfg.get("code") or ""),
            "host": str(self.lan_cfg.get("host") or ""),
            "ips": local_ips(),
            "running": bool(srv and srv.running),
            "clients": srv.snapshot() if srv else [],
            "default_allow": (srv.default_allow if srv
                              else bool(self.lan_cfg.get("default_allow"))),
            "can_write": bool(self.can_write),
            "client_name": str(self.lan_cfg.get("client_name") or ""),
        }

    # ------------------------------------------------------------ 顶部状态条
    def _lan_bar_widgets(self):
        if getattr(self, "lan_bar", None) is None:
            bar = tk.Frame(self.root, bg="#FFF4E5",
                           highlightbackground=CLR_BORDER, highlightthickness=1)
            lbl = tk.Label(bar, text="", bg="#FFF4E5", fg="#B54708",
                           font=(self.fam, 9), anchor="w")
            lbl.pack(side="left", padx=12, pady=5)
            btn_set = ttk.Button(bar, text="局域网设置", style="Ghost.TButton",
                                 width=11, command=self.open_lan)
            btn_set.pack(side="right", padx=(0, 10), pady=4)
            btn_req = ttk.Button(bar, text="请求录入", style="Ghost.TButton",
                                 width=9, command=self.ask_write_permission)
            btn_req.pack(side="right", padx=(0, 6), pady=4)
            self.lan_bar, self.lan_lbl = bar, lbl
            self.btn_lan_req, self.btn_lan_set = btn_req, btn_set
            bar._shown = False
        return self.lan_bar

    def _update_lan_ui(self, kind="auto", err=""):
        """客户端模式显示顶部状态条：绿色=可录入 / 橙色=只读 / 红色=断线。"""
        self._update_db_label()
        bar = self._lan_bar_widgets()
        if self.lan_mode != "client":
            if getattr(bar, "_shown", False):
                bar.pack_forget()
                bar._shown = False
            return
        if kind == "auto":
            kind = "ok" if self.can_write else "readonly"
        colors = {"ok": ("#E8F7EE", "#067647"),
                  "readonly": ("#FFF4E5", "#B54708"),
                  "lost": ("#FDECEC", "#B42318")}
        bg, fg = colors.get(kind, colors["readonly"])
        host = self.lan_cfg.get("host") or ""
        if kind == "lost":
            text = "与主机 %s 断开：%s（当前显示的是最后一次读取的数据）" % (
                host, err or "网络不通")
        elif kind == "ok":
            text = "已连接主机 %s · 仓库「%s」 · 可录入" % (
                host, self.cur_wh()["name"])
        else:
            text = "只读模式 · 已连接主机 %s · 主机未授权本机录入（可查看、导出）" % host
        try:
            bar.configure(bg=bg)
            self.lan_lbl.configure(text=text, bg=bg, fg=fg)
        except Exception:
            pass
        if kind == "readonly":
            self.btn_lan_req.pack(side="right", padx=(0, 6), pady=4)
        else:
            self.btn_lan_req.pack_forget()
        if not getattr(bar, "_shown", False):
            try:
                bar.pack(fill="x", before=self.nb)
                bar._shown = True
            except Exception:
                pass

    def ask_write_permission(self):
        """客户端：请主机授权录入。"""
        if self.lan_mode != "client":
            return
        if self.can_write:
            messagebox.showinfo("录入权限", "本机已经可以录入了。", parent=self.root)
            return
        try:
            self.store.request_write()
        except HostUnreachable as e:
            messagebox.showerror("连接失败", str(e), parent=self.root)
            return
        except Exception as e:
            messagebox.showerror("请求失败", str(e), parent=self.root)
            return
        self._status("已向主机发送录入请求")
        messagebox.showinfo("请求已发送",
                            "已通知主机。\n请在主机电脑上点「允许」，本机随后会自动变为可录入。",
                            parent=self.root)

    # ------------------------------------------------------------ 主机
    def start_lan_host(self, port=None, code=None):
        if self.lan_mode == "client":
            ok, msg = self.disconnect_lan()
            if not ok:
                return False, msg
        port = int(port or self.lan_cfg.get("port") or DEFAULT_PORT)
        code = str(code or self.lan_cfg.get("code") or "").strip()
        if len(code) < 4:
            return False, "连接码至少 4 位"
        if self.lan_server:
            self.stop_lan_host()
        srv = LanServer(lambda: self.store, lambda: self.cur_wh()["name"],
                        code, port, on_event=self._lan_event)
        ok, msg = srv.start()
        if not ok:
            return False, msg
        srv.default_allow = bool(self.lan_cfg.get("default_allow"))
        srv.set_blocked(self.lan_cfg.get("blocked") or [])
        self.lan_server = srv
        self.lan_mode = "host"
        self.lan_cfg.update({"mode": "host", "port": port, "code": code})
        self._save_lan_cfg()
        self._update_lan_ui()
        self._refresh_lan_dialog()
        self._status("局域网主机已开启：端口 %d，其他电脑用连接码 %s 连接"
                     % (port, code))
        return True, "主机服务已开启（端口 %d）" % port

    def stop_lan_host(self):
        if self.lan_server:
            self.lan_server.stop()
            self.lan_server = None
        if self.lan_mode == "host":
            self.lan_mode = "off"
            self.lan_cfg["mode"] = "off"
            self._save_lan_cfg()
        self._update_lan_ui()
        self._refresh_lan_dialog()
        return True, "已停止共享"

    def set_lan_allow(self, ip, flag):
        if self.lan_server:
            self.lan_server.allow(ip, flag)
        self._refresh_lan_dialog()

    def set_lan_default_allow(self, flag):
        self.lan_cfg["default_allow"] = bool(flag)
        self._save_lan_cfg()
        if self.lan_server:
            self.lan_server.set_default_allow(flag)

    # ---- 主机：移除连接 / 黑名单（v1.11.4）
    def lan_kick_client(self, ip):
        """移除连接：踢下线，对方之后仍可重新连接。"""
        if self.lan_server:
            self.lan_server.kick(ip)
            self._refresh_lan_dialog()
        return True, "已移除该电脑的连接"

    def lan_block_client(self, ip, name=""):
        """加入黑名单：持久拒绝该电脑连接（直到移出黑名单）。"""
        if self.lan_server:
            self.lan_server.block(ip, name)
        else:
            lst = [b for b in (self.lan_cfg.get("blocked") or [])
                   if b.get("ip") != ip]
            lst.append({"ip": ip, "name": name or "", "time": time.time()})
            self.lan_cfg["blocked"] = lst
        self.lan_cfg["blocked"] = (
            self.lan_server.blocked_snapshot() if self.lan_server
            else self.lan_cfg.get("blocked") or [])
        self._save_lan_cfg()
        return True, "已加入黑名单"

    def lan_unblock(self, ip):
        """移出黑名单。"""
        if self.lan_server:
            self.lan_server.unblock(ip)
        self.lan_cfg["blocked"] = [b for b in (self.lan_cfg.get("blocked") or [])
                                   if b.get("ip") != ip]
        self._save_lan_cfg()
        self._refresh_lan_dialog()
        return True, "已移出黑名单"

    def lan_blocked(self):
        srv = self.lan_server
        return srv.blocked_snapshot() if srv else list(self.lan_cfg.get("blocked") or [])

    # ------------------------------------------------------------ 客户端
    def connect_lan(self, host, port=None, code="", probe=None):
        """连接到主机（热切换，不用重启程序）。

        probe：可选。弹窗里已在后台线程 ping 成功的 RemoteStore，
        直接复用，避免在界面线程再做一次网络探测（那会卡住窗口）。
        """
        host = str(host or "").strip()
        host = host.replace("http://", "").replace("/", "")
        if ":" in host:
            host, _, p = host.partition(":")
            port = port or p
        port = int(port or DEFAULT_PORT)
        code = str(code or "").strip()
        if not host:
            return False, "请填写主机地址（如 192.168.1.10）"
        if not code:
            return False, "请填写主机上显示的连接码"
        try:
            if probe is not None:
                rs = probe
                info = getattr(rs, "last_ping", None) or rs.ping()
            else:
                rs = RemoteStore(host, port, code,
                                 self.lan_cfg.get("client_id") or "",
                                 self.lan_cfg.get("client_name") or "")
                info = rs.ping()
        except Exception as e:
            return False, str(e)
        old = self.store
        if self.lan_server:
            self.lan_server.stop()
            self.lan_server = None
        try:
            old.close()
        except Exception:
            pass
        self.store = rs
        self.lan_mode = "client"
        self.can_write = bool(info.get("can_write"))
        self._remote_wh = str(info.get("warehouse") or "主机数据")
        self._lan_rev = int(info.get("rev") or 0)
        self.db_path = rs.path
        self.lan_cfg.update({"mode": "client", "host": host,
                             "port": port, "code": code})
        self._add_lan_history(host, port, code)
        self._save_lan_cfg()
        self._reload_all()
        self._update_lan_ui()
        self._refresh_lan_dialog()
        self._status("已连接主机 %s:%d（%s）"
                     % (host, port, "可录入" if self.can_write else "只读"))
        return True, "已连接主机 %s:%d" % (host, port)

    def disconnect_lan(self):
        """断开主机/停止共享，切回本机数据。"""
        if self.lan_mode == "off":
            return True, "当前已经是本机模式"
        if self.lan_server:
            self.lan_server.stop()
            self.lan_server = None
        try:
            self.store.close()
        except Exception:
            pass
        self.lan_mode = "off"
        self.can_write = True
        self._remote_wh = ""
        self._lan_rev = 0
        self.lan_cfg["mode"] = "off"
        self._save_lan_cfg()
        self.db_path = os.path.join(self.data_dir,
                                    self.warehouses[self.wh_index]["file"])
        self.store = Store(self.db_path)
        self._reload_all()
        self._update_lan_ui()
        self._refresh_lan_dialog()
        self._status("已切回本机数据")
        return True, "已切回本机数据"

    # ------------------------------------------------------------ 客户端轮询
    def _lan_tick(self):
        if self._stopped:
            return
        if self.lan_mode == "host" and getattr(self, "lan_dlg", None) is not None:
            try:
                if self.lan_dlg.winfo_viewable():
                    self._refresh_lan_dialog()   # 主机模式弹窗也轮询（在线列表/最近活动保鲜）
            except Exception:
                pass
        if self.lan_mode == "client" and not self._lan_busy:
            self._lan_busy = True

            def work():
                try:
                    info = self.store.ping()
                    self._ui(self._on_lan_info, info)
                except Exception as e:
                    self._ui(self._on_lan_error, str(e))
                finally:
                    self._lan_busy = False
            threading.Thread(target=work, daemon=True,
                             name="lan-poll").start()
        elif self.lan_mode == "client" and self._lan_pending:
            if self.root.grab_current() is None:
                self._lan_pending = False
                self._reload_from_host()
        try:
            self.root.after(4000, self._lan_tick)
        except tk.TclError:
            pass

    def _on_lan_info(self, info):
        if self.lan_mode != "client":
            return
        self._lan_kick_seen = False     # 连接恢复正常，被踢标记复位
        wh = str(info.get("warehouse") or "")
        if wh and wh != self._remote_wh:
            self._remote_wh = wh
            self._refresh_wh_ui()
        was = self.can_write
        self.can_write = bool(info.get("can_write"))
        if was != self.can_write:
            self._status("主机已%s本机录入权限" % ("授予" if self.can_write else "收回"))
        self._lan_last_ok = True
        rev = int(info.get("rev") or 0)
        if rev and rev != self._lan_rev:
            self._lan_rev = rev
            if self.root.grab_current() is not None:
                self._lan_pending = True
            else:
                self._reload_from_host()
        self._update_lan_ui("ok" if self.can_write else "readonly")

    def _on_lan_error(self, err):
        if self.lan_mode != "client":
            return
        # 断线时不要刷屏：状态条一直显示红字，状态栏只在第一次提示
        if getattr(self, "_lan_last_ok", True):
            self._status("与主机断开：%s" % err)
        self._lan_last_ok = False
        self._update_lan_ui("lost", err)
        # 被主机移除连接 / 加入黑名单：本机自动断开回本地模式，只弹一次
        if ("黑名单" in err or "移除本机的连接" in err) \
                and not getattr(self, "_lan_kick_seen", False):
            self._lan_kick_seen = True
            self._status(err)
            try:
                messagebox.showwarning("与主机断开", err, parent=self.root)
            except Exception:
                pass
            self._ui(self._on_lan_kicked)

    def _on_lan_kicked(self):
        if self.lan_mode != "client":
            return
        self.disconnect_lan()
        messagebox.showinfo("已回到本机数据",
                            "主机已移除本机的连接，已自动切回本机数据。\n"
                            "如需再次共享，请重新连接主机。", parent=self.root)

    def _reload_from_host(self):
        """主机数据变了：重新读一遍（保留筛选与页码）。"""
        if self.lan_mode != "client":
            return
        try:
            self.load_data()
            self.tab_sales.refresh_rows()
            self.tab_out.refresh_rows()
            self.tab_phone.refresh_rows()
            self._status("已同步主机最新数据")
        except Exception as e:
            self._status("同步失败：%s" % e)
        self._update_lan_ui("ok" if self.can_write else "readonly")

    def _reload_all(self):
        """整体重载（切换本机/主机后）：清掉旧视图状态再读。"""
        for k in getattr(self, "f_vars", {}):
            try:
                self.f_vars[k].set("全部")
            except Exception:
                pass
        try:
            self.var_kw.set("")
            self.var_pmin.set("")
            self.var_pmax.set("")
        except Exception:
            pass
        self.sort_key = None
        self.sort_desc = False
        self.page = 1
        self._drag_anchor = None
        self._drag_block = None
        self._block_preview = None
        self.load_data(first=True)
        try:
            self.tab_sales.refresh_tab()
            self.tab_out.refresh_tab()
        except Exception:
            pass
        try:
            self.tab_ana.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------ 主机事件
    def _lan_event(self, kind, payload):
        """由主机服务线程调用：转到 UI 线程处理。"""
        if kind == "request" and payload:
            self._ui(self._on_lan_write_request, payload)
        else:
            self._ui(self._refresh_lan_dialog)

    def _on_lan_write_request(self, payload):
        name = payload.get("name") or "未知电脑"
        ip = payload.get("ip") or ""
        ans = messagebox.askyesno(
            "局域网录入请求",
            "%s（%s）请求录入权限。\n\n"
            "允许后，这台电脑可以新增 / 修改 / 出入库（数据仍然是这一份）。\n"
            "是否允许？" % (name, ip), parent=self.root, icon="question")
        if self.lan_server:
            self.lan_server.allow(ip, ans)
        self._status("已%s %s 的录入请求" % ("允许" if ans else "拒绝", name))
        self._refresh_lan_dialog()

    def _refresh_lan_dialog(self):
        dlg = getattr(self, "lan_dlg", None)
        if dlg is not None:
            try:
                if dlg.winfo_exists():
                    dlg.refresh()
            except Exception:
                pass

    # ------------------------------------------------------------ 只读保护
    def _guard_write(self):
        """客户端且未授权时，写入动作先给个明确提示。返回 True = 已拦下。"""
        if self.lan_mode != "client" or self.can_write:
            return False
        messagebox.showwarning(
            "只读模式",
            "本机当前是只读模式：主机没有授权本机录入。\n\n"
            "可以查看、筛选、导出；如果要录入，点顶部「请求录入」，\n"
            "或请主机在「局域网共享」窗口里勾选本机「允许录入」。",
            parent=self.root)
        return True

    def _report_callback_exception(self, exc, val, tb):
        """兜底：写操作被主机拒绝时给出人话提示，而不是一堆 traceback。"""
        if isinstance(val, PermissionDenied):
            messagebox.showwarning(
                "只读模式",
                "主机拒绝了这次操作：未授权本机录入。\n\n"
                "点顶部「请求录入」，或请主机在「局域网共享」里授权。",
                parent=self.root)
            return
        traceback.print_exception(exc, val, tb)
        try:
            messagebox.showerror("操作失败", "%s: %s" % (exc.__name__, val),
                                 parent=self.root)
        except Exception:
            pass

    def on_close(self):
        self._stopped = True
        if self.lan_server:
            try:
                self.lan_server.stop()
            except Exception:
                pass
            self.lan_server = None
        self._save_settings()
        try:
            self.store.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()
    return 0
