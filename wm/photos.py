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
        """大图查看窗：左右翻页、删除、Esc 关闭。"""
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

        state = {"idx": names.index(name)}
        lbl = tk.Label(win, bg=CLR_BG)
        lbl.pack(expand=True, fill="both", padx=8, pady=(8, 0))
        lbl_cnt = tk.Label(win, bg=CLR_BG, fg=CLR_MUTED, font=(self.app.fam, 9))
        lbl_cnt.pack(pady=(4, 2))
        row = tk.Frame(win, bg=CLR_BG)
        row.pack(pady=(2, 10))

        def show():
            n = names[state["idx"]]
            im = self._pil(n)
            if im is not None:
                sw = max(1, win.winfo_screenwidth())
                sh = max(1, win.winfo_screenheight())
                big = im.copy()
                big.thumbnail((int(sw * 0.55), int(sh * 0.55)))
                fg = ImageTk.PhotoImage(big)
                # 查看窗自己持有引用（关键）：从表格 📷 打开时，Treeview 类绑定
                # 会在实例绑定之后再次触发选中 → set_code 清空 self._imgs，
                # 只挂 _imgs 的 PhotoImage 被回收 → 首屏白屏、翻页才恢复
                win._held_img = fg
                self._imgs["__view__"] = fg
                lbl.configure(image=fg, text="")
            else:
                lbl.configure(image="", text="照片加载失败")
            lbl_cnt.configure(text="%d / %d" % (state["idx"] + 1, len(names)))
            for w in row.winfo_children():
                w.destroy()
            ttk.Button(row, text="‹ 上一张",
                       state="normal" if state["idx"] > 0 else "disabled",
                       command=lambda: step(-1)).pack(side="left", padx=4)
            ttk.Button(row, text="删除这张", style="Danger.TButton",
                       command=do_del).pack(side="left", padx=4)
            ttk.Button(row, text="下一张 ›",
                       state="normal" if state["idx"] < len(names) - 1 else "disabled",
                       command=lambda: step(1)).pack(side="left", padx=4)
            ttk.Button(row, text="保存图片", style="Ghost.TButton",
                       command=do_save).pack(side="left", padx=4)
            ttk.Button(row, text="多选保存", style="Ghost.TButton",
                       command=do_save_multi).pack(side="left", padx=4)
            if not self.pending:
                ttk.Button(row, text="添加照片", style="Ghost.TButton",
                           command=do_add).pack(side="left", padx=4)

        def do_save():
            """把当前照片另存为图片文件（原图字节，不重新压缩）。"""
            n = names[state["idx"]]
            stem, ext = os.path.splitext(n)
            default = "%s_%s%s" % (self.code, stem, ext or ".jpg")
            path = filedialog.asksaveasfilename(
                parent=win, title="保存图片", initialfile=default,
                defaultextension=ext or ".jpg",
                filetypes=[("图片", "*.jpg *.jpeg *.png"), ("所有文件", "*.*")])
            if not path:
                return
            raw = self._bytes_of(n)
            if not raw:
                messagebox.showerror("保存图片", "照片数据读取失败", parent=win)
                return
            try:
                with open(path, "wb") as f:
                    f.write(raw)
            except OSError as e:
                messagebox.showerror("保存失败", str(e)[:100], parent=win)
                return
            self.app._status("图片已保存：%s" % path)

        def _safe_target(folder, name, used):
            """目标文件名：编号_原名，重名自动追加 (2)、(3)……"""
            stem, ext = os.path.splitext(name)
            base = "%s_%s%s" % (self.code, stem, ext or ".jpg")
            target, i = base, 1
            while target in used or os.path.exists(os.path.join(folder, target)):
                i += 1
                target = "%s(%d)%s" % (os.path.splitext(base)[0], i,
                                       os.path.splitext(base)[1])
            used.add(target)
            return os.path.join(folder, target)

        def do_save_multi():
            """多选保存：缩略图单击选中/取消，双击放大细看，批量写出原图。"""
            if not names:
                return
            dlg = tk.Toplevel(win)
            dlg.title("多选保存")
            dlg.configure(bg=CLR_BG)
            dlg.resizable(False, False)
            dlg.transient(win)
            dlg.grab_set()
            apply_window_icon(dlg)

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

            if not HAS_PIL:
                # 无 PIL 降级：退回文件名勾选列表
                tk.Label(dlg, text="勾选要保存的照片（默认全选）：",
                         bg=CLR_BG, fg=CLR_TEXT,
                         font=(self.app.fam, 10, "bold")).pack(
                    anchor="w", padx=16, pady=(14, 6))
                box = tk.Frame(dlg, bg=CLR_BG)
                box.pack(padx=16, pady=(0, 8))
                for n in names:
                    v = tk.BooleanVar(value=True)
                    sel[n] = v
                    tk.Checkbutton(box, text=n, variable=v, bg=CLR_BG, fg=CLR_TEXT,
                                   anchor="w", font=(self.app.fam, 9),
                                   command=repaint_all).pack(anchor="w", fill="x")
            else:
                tk.Label(dlg, text="单击图片选中 / 取消，双击放大（默认全选）：",
                         bg=CLR_BG, fg=CLR_TEXT,
                         font=(self.app.fam, 10, "bold")).pack(
                    anchor="w", padx=14, pady=(12, 6))

                COLS, TH, CW, CH = 4, 88, 110, 132
                rows = (len(names) + COLS - 1) // COLS
                outer = tk.Frame(dlg, bg=CLR_BG)
                outer.pack(padx=14, pady=(0, 4))
                cv = tk.Canvas(outer, bg=CLR_BG, highlightthickness=0,
                               width=COLS * CW,
                               height=min(rows, 4) * CH + 8)
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

                def preview(n):
                    """双击放大细看：大图 + 左右翻页，Esc 关闭。"""
                    pv = tk.Toplevel(dlg)
                    pv.title(n)
                    pv.configure(bg=CLR_BG)
                    pv.transient(dlg)
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
                        bprev.configure(state="normal" if idx["i"] > 0 else "disabled")
                        bnext.configure(state="normal"
                                        if idx["i"] < len(names) - 1 else "disabled")

                    def pstep(d):
                        idx["i"] = max(0, min(len(names) - 1, idx["i"] + d))
                        pshow()

                    bprev = ttk.Button(bar, text="‹ 上一张",
                                       command=lambda: pstep(-1))
                    bprev.pack(side="left", padx=4)
                    bnext = ttk.Button(bar, text="下一张 ›",
                                       command=lambda: pstep(1))
                    bnext.pack(side="left", padx=4)
                    pv.bind("<Escape>", lambda e: pv.destroy())
                    pv.bind("<Left>", lambda e: pstep(-1))
                    pv.bind("<Right>", lambda e: pstep(1))
                    pv.withdraw()
                    pshow()
                    center_window(pv, dlg, force=True)
                    pv.deiconify()

                def short(n):
                    stem, ext = os.path.splitext(n)
                    s = stem if len(stem) <= 10 else stem[:9] + "…"
                    return (s + ext)[:16]

                cells = {}                # name -> (frame, cap)

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

                # 双击会吞掉第二次 <Button-1>：单击延迟生效，双击先取消待定
                # 切换再放大，保证「双击细看」不会误改选中状态
                pend = {}             # name -> after id

                def click(n):
                    def do():
                        pend.pop(n, None)
                        toggle(n)
                    pend[n] = dlg.after(260, do)

                def dblclick(n):
                    if n in pend:
                        try:
                            dlg.after_cancel(pend[n])
                        except Exception:
                            pass
                        pend.pop(n, None)
                    preview(n)

                for i, n in enumerate(names):
                    sel[n] = True
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
                        lbl = tk.Label(fr, image=fg, bg=CLR_CARD, cursor="hand2")
                    else:
                        lbl = tk.Label(fr, text="🖼", bg=CLR_CARD, fg=CLR_MUTED,
                                       width=10, height=4, cursor="hand2")
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

                # 测试句柄：event_generate 模拟点击有假阳性，探针走程序化调用
                dlg._msel = {"sel": sel, "cells": cells, "paint": paint,
                             "click": click, "dblclick": dblclick}

                # 缩略图在窗口映射前创建 → 映射后部分系统不重绘（白块），
                # 与查看窗首帧白屏同根因：映射后强制重设一次图像
                def repaint_imgs(_e=None):
                    for n in names:
                        fg = held.get(n)
                        if fg is None:
                            continue
                        lbl = cells[n][0].winfo_children()[0]
                        try:
                            lbl.configure(image=fg)
                        except Exception:
                            pass
                dlg.bind("<Map>", repaint_imgs)
                dlg.after(120, repaint_imgs)

            stat = tk.Label(dlg, text="", bg=CLR_BG, fg=CLR_MUTED,
                            font=(self.app.fam, 8))

            def repaint_all():
                if HAS_PIL and all(not isinstance(sel[n], tk.BooleanVar)
                                   for n in names):
                    for n in names:
                        paint(n)      # noqa: F821（HAS_PIL 分支内定义）
                stat.configure(text="已选 %d / %d 张"
                               % (sum(1 for n in names if _on(n)), len(names)))

            stat.pack(pady=(0, 2))
            brow = tk.Frame(dlg, bg=CLR_BG)
            brow.pack(pady=(0, 4))
            ttk.Button(brow, text="全选", style="Ghost.TButton",
                       command=lambda: set_all(True)).pack(side="left", padx=4)
            ttk.Button(brow, text="全不选", style="Ghost.TButton",
                       command=lambda: set_all(False)).pack(side="left", padx=4)
            tip = tk.Label(dlg, text="", bg=CLR_BG, fg=CLR_DANGER,
                           font=(self.app.fam, 8))
            tip.pack()

            def confirm():
                picked = [n for n in names if _on(n)]
                if not picked:
                    tip.configure(text="请至少选中一张照片")
                    return
                folder = filedialog.askdirectory(
                    parent=dlg, title="选择保存位置", mustexist=True)
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
                dlg.destroy()
                if ok:
                    self.app._status("已保存 %d 张图片到 %s" % (ok, folder))
                if err:
                    messagebox.showwarning("多选保存", err, parent=win)

            frow = tk.Frame(dlg, bg=CLR_BG)
            frow.pack(pady=(4, 14))
            ttk.Button(frow, text="取消", style="Ghost.TButton",
                       command=dlg.destroy).pack(side="left", padx=4)
            ttk.Button(frow, text="保存", style="Accent.TButton",
                       command=confirm).pack(side="left", padx=4)
            repaint_all()
            dlg.withdraw()
            center_window(dlg, win, force=True)
            dlg.deiconify()

        def step(d):
            state["idx"] = max(0, min(len(names) - 1, state["idx"] + d))
            show()

        def do_add():
            """查看窗里直接补照片：关掉查看窗再走添加流程。"""
            win.destroy()
            self.add_photos()

        def do_del():
            n = names[state["idx"]]
            if not messagebox.askyesno("删除照片", "确定删除这张照片吗？", parent=win):
                return
            if self.pending:
                self.pending_list = [(nn, r) for nn, r in self.pending_list if nn != n]
                names.pop(state["idx"])
                self.set_code(self.code)
                if not names:
                    win.destroy()
                    return
                state["idx"] = min(state["idx"], len(names) - 1)
                show()
                return
            try:
                self.app.store.photo_del(self.kind, self.code, n)
            except Exception as e:
                messagebox.showerror("删除失败", str(e), parent=win)
                return
            try:
                self.app._photo_codes_changed(self.kind, self.code)
            except Exception:
                pass
            self._cache.pop((self.code, n), None)
            names.pop(state["idx"])
            self.set_code(self.code)         # 底部缩略图同步刷新
            if not names:
                win.destroy()
                return
            state["idx"] = min(state["idx"], len(names) - 1)
            show()

        win.bind("<Escape>", lambda e: win.destroy())
        # 先隐藏→定位→再显示：映射后再居中会「先在左上角闪一下」
        win.withdraw()
        show()
        center_window(win, self.winfo_toplevel(), force=True)
        win.deiconify()
        win.lift()
        win.focus_force()

        # 首帧图像在窗口映射前就设置好了，部分系统映射后不会自动重绘，
        # 表现为「第一张打开老是白屏、翻页后正常」。映射后强制重设一次图像。
        def _repaint(_e=None):
            fg = getattr(win, "_held_img", None) or self._imgs.get("__view__")
            if fg is not None:
                try:
                    lbl.configure(image=fg)
                except Exception:
                    pass
        win.bind("<Map>", _repaint)
        win.after(80, _repaint)
