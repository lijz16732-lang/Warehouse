# -*- coding: utf-8 -*-
"""记录照片条：详情区一排缩略图，点开大图可翻看/删除，可多选添加照片。

数据一律走 store 的照片方法（photo_data 返回 base64），
主机本机与局域网客户端（RemoteStore 代理）行为一致。
"""

import base64
import hashlib
import io
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .constants import *          # noqa: F401,F403 —— CLR_* / apply_window_icon /
#                                    center_window（随调色板切换）
from .store import PHOTO_MAX

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:                 # 无 PIL 时降级为「文件名占位」
    HAS_PIL = False

THUMB = 72                        # 缩略图边长（px）


class PhotoStrip(tk.Frame):
    """kind="item"：主库存记录；kind="phone"：手机区商品。

    pending=True：新增记录还没有编号，照片暂存在内存里（pending_list），
    保存后由调用方取出逐张落盘（store.photo_add）。
    """

    def __init__(self, master, app, kind="item", pending=False):
        tk.Frame.__init__(self, master, bg=CLR_CARD)
        self.app = app
        self.kind = kind
        self.pending = bool(pending)
        self.pending_list = []        # [(name, raw_bytes)] 暂存区
        self.code = None
        self._imgs = {}               # name -> PhotoImage（防被 GC）
        self._cache = {}              # (code, name) -> PIL.Image（原图缓存）

        head = tk.Frame(self, bg=CLR_CARD)
        head.pack(fill="x", padx=12)
        self.lbl_cap = tk.Label(head, text="照片", bg=CLR_CARD, fg=CLR_MUTED,
                                font=(app.fam, 8))
        self.lbl_cap.pack(side="left")
        self.btn_add = ttk.Button(head, text="＋ 添加照片", style="Ghost.TButton",
                                  command=self.add_photos)
        self.btn_add.pack(side="right")

        self.bar = tk.Frame(self, bg=CLR_CARD)
        self.bar.pack(fill="x", padx=12, pady=(2, 6))
        self.set_code(None)

    # ------------------------------------------------------------ 数据
    def set_code(self, code):
        """切换当前记录（None = 未选中，显示提示）。"""
        if self.pending:
            self.code = "__pending__"
            self._render_pending()
            return
        self.code = code
        for w in self.bar.winfo_children():
            w.destroy()
        self._imgs.clear()
        if not code:
            try:
                self.btn_add.configure(state="disabled")
            except Exception:
                pass
            self.lbl_cap.configure(text="照片")
            tk.Label(self.bar, text="选中一条记录后可在这里添加 / 查看照片",
                     bg=CLR_CARD, fg=CLR_MUTED, font=(self.app.fam, 8)).pack(side="left")
            return
        try:
            self.btn_add.configure(state="normal")
        except Exception:
            pass
        names = []
        try:
            names = self.app.store.photos_list(self.kind, code) or []
        except Exception as e:
            tk.Label(self.bar, text="照片读取失败：%s" % str(e)[:60],
                     bg=CLR_CARD, fg=CLR_DANGER,
                     font=(self.app.fam, 8)).pack(side="left")
        self.lbl_cap.configure(text="照片 %d/%d" % (len(names), PHOTO_MAX))
        if not names:
            tk.Label(self.bar, text="暂无照片，点右上「＋ 添加照片」"
                            "（最多 %d 张，自动压缩）" % PHOTO_MAX,
                     bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.app.fam, 8)).pack(side="left")
            return
        for name in names:
            self._thumb(name)

    def _render_pending(self):
        """暂存模式：从 pending_list 渲染缩略图。"""
        for w in self.bar.winfo_children():
            w.destroy()
        self._imgs.clear()
        self.lbl_cap.configure(text="照片 %d/%d（保存记录后写入）"
                               % (len(self.pending_list), PHOTO_MAX))
        if not self.pending_list:
            tk.Label(self.bar, text="暂无照片，点右上「＋ 添加照片」"
                     "（最多 %d 张，自动压缩，保存后生效）" % PHOTO_MAX,
                     bg=CLR_CARD, fg=CLR_MUTED,
                     font=(self.app.fam, 8)).pack(side="left")
        for name, _raw in self.pending_list:
            self._thumb(name)

    def _bytes_of(self, name):
        """取照片原始字节（暂存 / 本机直接读；客户端经 RPC base64）。"""
        if self.pending:
            for n, raw in self.pending_list:
                if n == name:
                    return raw
            return None
        b64 = self.app.store.photo_data(self.kind, self.code, name)
        if not b64:
            return None
        try:
            return base64.b64decode(b64)
        except Exception:
            return None

    def _pil(self, name):
        key = (self.code, name)
        if key not in self._cache:
            raw = self._bytes_of(name)
            if not raw or not HAS_PIL:
                return None
            try:
                im = Image.open(io.BytesIO(raw))
                im.load()
                self._cache[key] = im
            except Exception:
                return None
        return self._cache.get(key)

    def _thumb(self, name):
        lbl = tk.Label(self.bar, bg=CLR_CARD, cursor="hand2")
        im = self._pil(name)
        if im is not None:
            th = im.copy()
            th.thumbnail((THUMB, THUMB))
            fg = ImageTk.PhotoImage(th)
            self._imgs[name] = fg
            lbl.configure(image=fg, width=THUMB, height=THUMB)
        else:
            lbl.configure(text="🖼\n%s" % name[:8], fg=CLR_MUTED, width=8, height=3,
                          font=(self.app.fam, 7), justify="center")
        lbl.pack(side="left", padx=(0, 6), pady=2)
        lbl.bind("<Button-1>", lambda e, n=name: self.view(n))

    # ------------------------------------------------------------ 操作
    def add_photos(self):
        """文件多选添加（自动压缩、内容去重、上限拦截）。"""
        paths = filedialog.askopenfilenames(
            parent=self, title="选择照片（可多选）",
            filetypes=[("图片", "*.jpg *.jpeg *.png"), ("所有文件", "*.*")])
        if not paths:
            return
        if self.pending:
            err = ""
            for p in paths:
                if len(self.pending_list) >= PHOTO_MAX:
                    err = "最多 %d 张照片" % PHOTO_MAX
                    break
                try:
                    with open(p, "rb") as f:
                        raw = f.read()
                except OSError as e:
                    err = str(e)[:100]
                    break
                md5 = hashlib.md5(raw).hexdigest()
                if any(md5 == m for m in
                       (hashlib.md5(r).hexdigest() for _n, r in self.pending_list)):
                    continue                     # 同内容去重
                base = os.path.basename(p) or "photo.jpg"
                name, i = base, 1
                while any(n == name for n, _r in self.pending_list):
                    stem, ext = os.path.splitext(base)
                    i += 1
                    name = "%s(%d)%s" % (stem, i, ext or ".jpg")
                self.pending_list.append((name, raw))
            self._render_pending()
            if err:
                messagebox.showwarning("添加照片", err, parent=self.winfo_toplevel())
            return
        if not self.code:
            return
        ok, err = 0, ""
        paths = list(paths)
        total = len(paths)
        # 进度窗：压缩大图较慢，逐张反馈避免“不知道有没有在存”
        prog = tk.Toplevel(self.winfo_toplevel())
        prog.title("添加照片")
        prog.configure(bg=CLR_BG)
        prog.resizable(False, False)
        prog.transient(self.winfo_toplevel())
        apply_window_icon(prog)
        lbl = tk.Label(prog, text="正在添加 1/%d" % total, bg=CLR_BG, fg=CLR_TEXT,
                       font=(self.app.fam, 10, "bold"))
        lbl.pack(padx=28, pady=(16, 4))
        bar = ttk.Progressbar(prog, length=280, maximum=total,
                              mode="determinate")
        bar.pack(padx=28, pady=(0, 6))
        lbl_name = tk.Label(prog, text="", bg=CLR_BG, fg=CLR_MUTED,
                            font=(self.app.fam, 8))
        lbl_name.pack(padx=28, pady=(0, 14))
        prog.withdraw()          # 先隐藏→定位→再显示，避免左上角闪一下
        center_window(prog, self.winfo_toplevel(), force=True)
        prog.deiconify()
        try:
            for i, p in enumerate(paths, 1):
                lbl.configure(text="正在添加 %d/%d" % (i, total))
                lbl_name.configure(text=os.path.basename(p))
                bar["value"] = i - 1
                prog.update_idletasks()
                prog.update()
                try:
                    with open(p, "rb") as f:
                        raw = f.read()
                    self.app.store.photo_add(self.kind, self.code,
                                             base64.b64encode(raw).decode("ascii"),
                                             os.path.basename(p))
                    ok += 1
                except Exception as e:
                    err = str(e)[:100]
                    break
        finally:
            bar["value"] = total
            prog.destroy()
        self.set_code(self.code)
        try:
            self.app._photo_codes_changed(self.kind, self.code)
        except Exception:
            pass
        if ok:
            self.app._status("已添加 %d 张照片（完成）" % ok)
        if err:
            messagebox.showwarning("添加照片", err, parent=self.winfo_toplevel())

    def view(self, name):
        """照片管理窗：缩略图网格，单击选中/取消，双击放大细看；
        可多选删除、多选保存、添加照片。"""
        if self.pending:
            names = [n for n, _r in self.pending_list]
        else:
            if not self.code:
                return
            try:
                names = list(self.app.store.photos_list(self.kind, self.code) or [])
            except Exception:
                names = []
        if name not in names:
            return
        win = tk.Toplevel(self.winfo_toplevel())
        win.title("%s · 照片" % self.code)
        win.configure(bg=CLR_BG)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        apply_window_icon(win)

        def _safe_target(folder, fname, used):
            """目标文件名：编号_原名，重名自动追加 (2)、(3)……"""
            stem, ext = os.path.splitext(fname)
            base = "%s_%s%s" % (self.code, stem, ext or ".jpg")
            target, i = base, 1
            while target in used or os.path.exists(os.path.join(folder, target)):
                i += 1
                target = "%s(%d)%s" % (os.path.splitext(base)[0], i,
                                       os.path.splitext(base)[1])
            used.add(target)
            return os.path.join(folder, target)

        sel = {}                      # name -> bool / BooleanVar
        held = {}                     # name -> PhotoImage（防 GC）

        def _on(n):
            v = sel[n]
            return v.get() if isinstance(v, tk.BooleanVar) else bool(v)

        def set_all(val):
            for n in names:
                v = sel[n]
                if isinstance(v, tk.BooleanVar):
                    v.set(val)
                else:
                    sel[n] = val
            repaint_all()

        tk.Label(win, text="单击图片选中 / 取消，双击放大细看",
                 bg=CLR_BG, fg=CLR_TEXT,
                 font=(self.app.fam, 10, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6))

        repaint_cells = None          # PIL 分支注入：重刷所有单元选中态
        build = None                  # 分支注入：增删后重建网格

        stat = tk.Label(win, text="", bg=CLR_BG, fg=CLR_MUTED,
                        font=(self.app.fam, 8))
        tip = tk.Label(win, text="", bg=CLR_BG, fg=CLR_DANGER,
                       font=(self.app.fam, 8))

        if not HAS_PIL:
            # 无 PIL 降级：文件名勾选列表
            box = tk.Frame(win, bg=CLR_BG)
            box.pack(padx=16, pady=(0, 8))

            def build():
                for w in box.winfo_children():
                    w.destroy()
                for n in names:
                    if n not in sel:
                        sel[n] = tk.BooleanVar(value=False)
                    tk.Checkbutton(box, text=n, variable=sel[n],
                                   bg=CLR_BG, fg=CLR_TEXT, anchor="w",
                                   font=(self.app.fam, 9),
                                   command=repaint_all).pack(anchor="w",
                                                             fill="x")
        else:
            COLS, TH, CW, CH = 4, 88, 110, 132
            outer = tk.Frame(win, bg=CLR_BG)
            outer.pack(padx=14, pady=(0, 4))
            cv = tk.Canvas(outer, bg=CLR_BG, highlightthickness=0,
                           width=COLS * CW)
            vs = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
            cv.configure(yscrollcommand=vs.set)
            vs.pack(side="right", fill="y")
            cv.pack(side="left")
            grid = tk.Frame(cv, bg=CLR_BG)
            cv.create_window((0, 0), window=grid, anchor="nw")
            grid.bind("<Configure>",
                      lambda e: cv.configure(scrollregion=cv.bbox("all")))

            def _wheel(e):
                cv.yview_scroll(-1 if e.delta > 0 else 1, "units")
            for w in (cv, grid):
                w.bind("<MouseWheel>", _wheel)

            cells = {}                # name -> (frame, cap)

            def short(n):
                stem, ext = os.path.splitext(n)
                s = stem if len(stem) <= 10 else stem[:9] + "…"
                return (s + ext)[:16]

            def paint(n):
                fr, cap = cells[n]
                if _on(n):
                    fr.configure(highlightbackground=CLR_ACCENT,
                                 highlightcolor=CLR_ACCENT)
                    cap.configure(text="✓ " + short(n), fg=CLR_ACCENT)
                else:
                    fr.configure(highlightbackground=CLR_BORDER,
                                 highlightcolor=CLR_BORDER)
                    cap.configure(text=short(n), fg=CLR_MUTED)

            def toggle(n):
                v = sel[n]
                if isinstance(v, tk.BooleanVar):
                    v.set(not v.get())
                else:
                    sel[n] = not v
                paint(n)
                repaint_all()          # 同步「已选 n 张」计数与按钮状态

            # 双击会先触发一次 <Button-1>：单击立即切换（响应快），
            # 双击时先把第一次单击的切换撤销回来再放大，保证「双击细看」
            # 不误改选中状态
            def click(n):
                toggle(n)

            def dblclick(n):
                toggle(n)             # 撤销双击吞掉的那次单击切换
                preview(n)

            def build():
                for w in grid.winfo_children():
                    w.destroy()
                held.clear()
                cells.clear()
                for n in list(sel):
                    if n not in names:
                        sel.pop(n)        # 删掉的照片不再保留选中态
                rows = (len(names) + COLS - 1) // COLS or 1
                cv.configure(height=min(rows, 4) * CH + 8)
                for i, n in enumerate(names):
                    sel.setdefault(n, False)      # 默认不选
                    fr = tk.Frame(grid, bg=CLR_CARD, highlightthickness=2,
                                  highlightbackground=CLR_BORDER,
                                  highlightcolor=CLR_BORDER, cursor="hand2")
                    fr.grid(row=i // COLS, column=i % COLS, padx=4, pady=4)
                    im = self._pil(n)
                    if im is not None:
                        th = im.copy()
                        th.thumbnail((TH, TH))
                        fg = ImageTk.PhotoImage(th)
                        held[n] = fg
                        lbl = tk.Label(fr, image=fg, bg=CLR_CARD,
                                       cursor="hand2")
                    else:
                        lbl = tk.Label(fr, text="🖼", bg=CLR_CARD,
                                       fg=CLR_MUTED, width=10, height=4,
                                       cursor="hand2")
                    lbl.pack(padx=2, pady=(2, 0))
                    cap = tk.Label(fr, text="", bg=CLR_CARD,
                                   font=(self.app.fam, 7))
                    cap.pack(pady=(0, 2))
                    cells[n] = (fr, cap)
                    for w in (fr, lbl, cap):
                        w.bind("<Button-1>", lambda e, nn=n: click(nn))
                        w.bind("<Double-Button-1>",
                               lambda e, nn=n: dblclick(nn))
                    paint(n)

            def repaint_cells():
                for n in names:
                    if n in cells:
                        paint(n)

            def preview(n):
                """双击放大细看：大图 + 左右翻页 + 删除/另存，Esc 关闭。"""
                pv = tk.Toplevel(win)
                pv.title(n)
                pv.configure(bg=CLR_BG)
                pv.transient(win)
                pv.grab_set()
                apply_window_icon(pv)
                idx = {"i": names.index(n)}
                held2 = {}
                lbl = tk.Label(pv, bg=CLR_BG)
                lbl.pack(expand=True, fill="both", padx=10, pady=(10, 0))
                cnt = tk.Label(pv, bg=CLR_BG, fg=CLR_MUTED,
                               font=(self.app.fam, 9))
                cnt.pack(pady=(4, 2))
                bar = tk.Frame(pv, bg=CLR_BG)
                bar.pack(pady=(2, 10))

                def pshow():
                    nn = names[idx["i"]]
                    im = self._pil(nn)
                    if im is not None:
                        sw = max(1, pv.winfo_screenwidth())
                        sh = max(1, pv.winfo_screenheight())
                        big = im.copy()
                        big.thumbnail((int(sw * 0.5), int(sh * 0.5)))
                        fg = ImageTk.PhotoImage(big)
                        held2["im"] = fg
                        lbl.configure(image=fg, text="")
                    else:
                        lbl.configure(image="", text="照片加载失败")
                    cnt.configure(text="%d / %d" % (idx["i"] + 1, len(names)))
                    bprev.configure(state="normal"
                                    if idx["i"] > 0 else "disabled")
                    bnext.configure(state="normal"
                                    if idx["i"] < len(names) - 1
                                    else "disabled")

                def pstep(d):
                    idx["i"] = max(0, min(len(names) - 1, idx["i"] + d))
                    pshow()

                def p_del():
                    nn = names[idx["i"]]
                    if not messagebox.askyesno(
                            "删除照片", "确定删除这张照片吗？", parent=pv):
                        return
                    if self.pending:
                        self.pending_list = [(x, r) for x, r in
                                             self.pending_list if x != nn]
                    else:
                        try:
                            self.app.store.photo_del(self.kind, self.code, nn)
                        except Exception as e:
                            messagebox.showerror("删除失败", str(e), parent=pv)
                            return
                        self._cache.pop((self.code, nn), None)
                        try:
                            self.app._photo_codes_changed(self.kind, self.code)
                        except Exception:
                            pass
                    names.remove(nn)
                    sel.pop(nn, None)
                    self.set_code(self.code)      # 底部缩略图同步
                    if not names:
                        pv.destroy()
                        win.destroy()
                        return
                    if build is not None:
                        build()
                    repaint_all()
                    idx["i"] = min(idx["i"], len(names) - 1)
                    pshow()

                def p_save():
                    """当前大图另存为图片文件（原图字节，不重新压缩）。"""
                    nn = names[idx["i"]]
                    stem, ext = os.path.splitext(nn)
                    default = "%s_%s%s" % (self.code, stem, ext or ".jpg")
                    path = filedialog.asksaveasfilename(
                        parent=pv, title="保存图片", initialfile=default,
                        defaultextension=ext or ".jpg",
                        filetypes=[("图片", "*.jpg *.jpeg *.png"),
                                   ("所有文件", "*.*")])
                    if not path:
                        return
                    raw = self._bytes_of(nn)
                    if not raw:
                        messagebox.showerror("保存图片", "照片数据读取失败",
                                             parent=pv)
                        return
                    try:
                        with open(path, "wb") as f:
                            f.write(raw)
                    except OSError as e:
                        messagebox.showerror("保存失败", str(e)[:100],
                                             parent=pv)
                        return
                    self.app._status("图片已保存：%s" % path)

                bprev = ttk.Button(bar, text="‹ 上一张",
                                   command=lambda: pstep(-1))
                bprev.pack(side="left", padx=4)
                ttk.Button(bar, text="删除这张", style="Danger.TButton",
                           command=p_del).pack(side="left", padx=4)
                bnext = ttk.Button(bar, text="下一张 ›",
                                   command=lambda: pstep(1))
                bnext.pack(side="left", padx=4)
                ttk.Button(bar, text="保存图片", style="Ghost.TButton",
                           command=p_save).pack(side="left", padx=4)
                pv.bind("<Escape>", lambda e: pv.destroy())
                pv.bind("<Left>", lambda e: pstep(-1))
                pv.bind("<Right>", lambda e: pstep(1))
                pv.withdraw()
                pshow()
                center_window(pv, win, force=True)
                pv.deiconify()

                # 大图在映射前创建 → 映射后可能不重绘（白屏），强制重设
                def _prep(_e=None):
                    fg = held2.get("im")
                    if fg is not None:
                        try:
                            lbl.configure(image=fg)
                        except Exception:
                            pass
                pv.bind("<Map>", _prep)
                pv.after(80, _prep)

            # 测试句柄：event_generate 模拟点击有假阳性，探针走程序化调用
            win._msel = {"sel": sel, "cells": cells, "paint": paint,
                         "click": click, "dblclick": dblclick}

            # 缩略图在窗口映射前创建 → 映射后部分系统不重绘（白块），
            # 与查看窗首帧白屏同根因：映射后强制重设一次图像
            def repaint_imgs(_e=None):
                for n in names:
                    fg = held.get(n)
                    if fg is None or n not in cells:
                        continue
                    lbl = cells[n][0].winfo_children()[0]
                    try:
                        lbl.configure(image=fg)
                    except Exception:
                        pass
            win.bind("<Map>", repaint_imgs)
            win.after(120, repaint_imgs)

        def repaint_all():
            k = sum(1 for n in names if _on(n))
            stat.configure(text="已选 %d / %d 张" % (k, len(names)))
            st = "normal" if k else "disabled"
            btn_del.configure(state=st)
            btn_save.configure(state=st)
            if repaint_cells is not None:
                repaint_cells()

        def do_del_multi():
            picked = [n for n in names if _on(n)]
            if not picked:
                tip.configure(text="请先单击选中要删除的照片")
                return
            if not messagebox.askyesno(
                    "删除照片", "确定删除选中的 %d 张照片吗？" % len(picked),
                    parent=win):
                return
            err, failed = "", []
            if self.pending:
                self.pending_list = [(nn, r) for nn, r in self.pending_list
                                     if nn not in picked]
            else:
                for n in picked:
                    try:
                        self.app.store.photo_del(self.kind, self.code, n)
                        self._cache.pop((self.code, n), None)
                    except Exception as e:
                        failed.append(n)
                        err = str(e)[:100]
                try:
                    self.app._photo_codes_changed(self.kind, self.code)
                except Exception:
                    pass
            for n in picked:
                if n in failed:
                    continue
                if n in names:
                    names.remove(n)
                sel.pop(n, None)
            self.set_code(self.code)          # 底部缩略图同步刷新
            if err:
                messagebox.showerror("删除失败", err, parent=win)
            if not names:
                win.destroy()
                return
            if build is not None:
                build()
            repaint_all()

        def do_save_multi():
            picked = [n for n in names if _on(n)]
            if not picked:
                tip.configure(text="请先单击选中要保存的照片")
                return
            folder = filedialog.askdirectory(
                parent=win, title="选择保存位置", mustexist=True)
            if not folder:
                return
            used = set()
            ok, err = 0, ""
            for n in picked:
                raw = self._bytes_of(n)
                if not raw:
                    err = "%s 数据读取失败" % n
                    continue
                try:
                    with open(_safe_target(folder, n, used), "wb") as f:
                        f.write(raw)
                    ok += 1
                except OSError as e:
                    err = str(e)[:100]
                    break
            if ok:
                self.app._status("已保存 %d 张图片到 %s" % (ok, folder))
            if err:
                messagebox.showwarning("多选保存", err, parent=win)

        def do_add():
            """窗口里直接补照片：关掉管理窗再走添加流程（完成后自动刷新）。"""
            win.destroy()
            self.add_photos()

        stat.pack(pady=(0, 2))
        brow = tk.Frame(win, bg=CLR_BG)
        brow.pack(pady=(0, 4))
        ttk.Button(brow, text="全选", style="Ghost.TButton",
                   command=lambda: set_all(True)).pack(side="left", padx=4)
        ttk.Button(brow, text="全不选", style="Ghost.TButton",
                   command=lambda: set_all(False)).pack(side="left", padx=4)
        tip.pack()
        frow = tk.Frame(win, bg=CLR_BG)
        frow.pack(pady=(4, 14))
        if not self.pending:
            ttk.Button(frow, text="添加照片", style="Ghost.TButton",
                       command=do_add).pack(side="left", padx=4)
        btn_del = ttk.Button(frow, text="删除选中", style="Danger.TButton",
                             command=do_del_multi)
        btn_del.pack(side="left", padx=4)
        btn_save = ttk.Button(frow, text="保存选中", style="Accent.TButton",
                              command=do_save_multi)
        btn_save.pack(side="left", padx=4)
        ttk.Button(frow, text="关闭", style="Ghost.TButton",
                   command=win.destroy).pack(side="left", padx=4)

        if build is not None:
            build()
        repaint_all()
        win.bind("<Escape>", lambda e: win.destroy())
        # 先隐藏→定位→再显示：映射后再居中会「先在左上角闪一下」
        win.withdraw()
        center_window(win, self.winfo_toplevel(), force=True)
        win.deiconify()
        win.lift()
        win.focus_force()

