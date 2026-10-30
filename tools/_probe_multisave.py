# -*- coding: utf-8 -*-
"""验证照片查看窗「多选保存」：真实库副本 + 真实 PhotoStrip.view()。

打开查看窗 → 点「多选保存」按钮 → 断言弹窗出现、勾选项数量 = 照片数、
全选/全不选联动正常；不真正写盘（保存走 askdirectory 人工路径）。
"""
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import tkinter as tk
from tkinter import ttk

from wm import constants  # noqa: F401  载入 CLR_*
from wm.photos import PhotoStrip
from wm.store import Store


class FakeApp(object):
    fam = "Microsoft YaHei"

    def _status(self, msg):
        print("[status]", msg)

    def _photo_codes_changed(self, kind, code):
        pass


def main():
    src = r"D:\仓库管理工具\data\warehouse.db"
    tmpd = os.path.join(tempfile.gettempdir(), "probe_multisave")
    os.makedirs(tmpd, exist_ok=True)
    tmp = os.path.join(tmpd, "warehouse.db")
    shutil.copy(src, tmp)
    psrc = r"D:\仓库管理工具\data\photos\warehouse"
    pdst = os.path.join(tmpd, "photos", "warehouse")
    if os.path.isdir(psrc) and not os.path.isdir(pdst):
        shutil.copytree(psrc, pdst)
    app = FakeApp()
    app.store = Store(tmp)

    root = tk.Tk()
    root.geometry("900x700+50+50")
    strip = PhotoStrip(root, app, kind="item")
    strip.pack(fill="both", expand=True)
    code = "WL-02053"
    strip.set_code(code)
    root.update()

    names = app.store.photos_list("item", code)
    print("photos:", len(names))
    assert names, "该记录无照片，无法验证"

    strip.view(names[0])
    tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    win = tops[-1]
    root.update()

    # 在查看窗按钮行里找「多选保存」并点击
    def find_btns(w):
        for c in w.winfo_children():
            if isinstance(c, ttk.Button):
                yield c
            yield from find_btns(c)
    btn = None
    for b in find_btns(win):
        if b.cget("text") == "多选保存":
            btn = b
    assert btn is not None, "查看窗里没有「多选保存」按钮"
    btn.invoke()
    root.update()

    # dlg 的父级是 win（transient(win)），在 win 的子 Toplevel 里找
    sub = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
    assert sub, "多选保存弹窗没有打开"
    dlg = sub[-1]
    checks = []

    def find_checks(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Checkbutton):
                checks.append(c)
            find_checks(c)
    find_checks(dlg)
    print("checkbox count:", len(checks))
    assert len(checks) == len(names), "勾选项数量与照片数不符"
    def var_of(c):
        return bool(dlg.tk.globalgetvar(str(c.cget("variable"))))
    assert all(var_of(c) for c in checks), "默认应全选"

    # 全不选 → 按钮文字变化联动（点「全不选」再检查变量）
    for b in find_btns(dlg):
        if b.cget("text") == "全不选":
            b.invoke()
    all_off = all(not var_of(c) for c in checks)
    for b in find_btns(dlg):
        if b.cget("text") == "全选":
            b.invoke()
    all_on = all(var_of(c) for c in checks)
    print("全不选:", all_off, "全选:", all_on)
    assert all_off and all_on, "全选/全不选联动失效"

    # 端到端落盘：mock 选目录 → 点「保存」→ 校验文件数与字节一致
    import tkinter.filedialog as _fd
    outdir = os.path.join(tmpd, "out")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    from wm import photos as _photos_mod
    _photos_mod.filedialog.askdirectory = lambda **kw: outdir
    save_btn = None
    for b in find_btns(dlg):
        if b.cget("text") == "保存":
            save_btn = b
    save_btn.invoke()
    root.update()
    saved = os.listdir(outdir)
    print("saved files:", len(saved), saved[:3])
    assert len(saved) == len(names), "落盘数量与照片数不符"
    for n, fname in zip(names, sorted(saved)):
        raw = app.store.photo_data("item", code, n)
        import base64 as _b64
        with open(os.path.join(outdir, fname), "rb") as f:
            disk = f.read()
        assert disk == _b64.b64decode(raw), "文件字节与原图不一致: %s" % fname
    print("bytes match: True")

    dlg.destroy()
    win.destroy()
    root.destroy()
    print("PROBE OK")


if __name__ == "__main__":
    main()
