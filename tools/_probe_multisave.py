# -*- coding: utf-8 -*-
"""验证照片管理窗（缩略图网格直开）：真实库副本 + 真实 PhotoStrip.view()。

断言：网格单元数 = 照片数、默认不选、单击选中、双击预览且不改选中、
多选删除（真实删库+底部条同步）、保存选中落盘字节一致、全选联动。
"""
import os
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import tkinter as tk
from tkinter import ttk

from wm import constants  # noqa: F401  载入 CLR_*
from wm import photos as photos_mod
from wm.photos import PhotoStrip
from wm.store import Store


class FakeApp(object):
    fam = "Microsoft YaHei"

    def _status(self, msg):
        print("[status]", msg)

    def _photo_codes_changed(self, kind, code):
        print("[codes_changed]", kind, code)


def find_btns(w):
    for c in w.winfo_children():
        if isinstance(c, ttk.Button):
            yield c
        yield from find_btns(c)


def get_btn(w, text):
    for b in find_btns(w):
        if b.cget("text") == text:
            return b
    return None


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
    n0 = len(names)
    print("photos:", n0)
    assert n0 >= 3, "至少需要 3 张照片才能完整验证"

    # 点 📷 直接打开管理窗（不再有单独的大图查看窗）
    strip.view(names[0])
    win = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    win.update_idletasks()
    time.sleep(0.4)
    root.update()
    assert win.title() == "%s · 照片" % code, "窗口标题异常: %s" % win.title()

    ms = win._msel
    cells = list(ms["cells"].keys())
    print("cells:", len(cells))
    assert len(cells) == n0, "网格单元数量与照片数不符"
    for n in names:
        fr, cap = ms["cells"][n]
        assert fr.cget("highlightbackground") == constants.CLR_BORDER, \
            "默认应不选中"

    def stat_text():
        for w in win.winfo_children():
            if isinstance(w, tk.Label) and str(w.cget("text")).startswith("已选"):
                return w.cget("text")
        return ""

    assert "0 / %d" % n0 in stat_text(), "默认计数应为 0: %s" % stat_text()

    # 单击选中第一张
    ms["click"](names[0])
    time.sleep(0.35)
    root.update()
    fr0, cap0 = ms["cells"][names[0]]
    assert fr0.cget("highlightbackground") == constants.CLR_ACCENT, \
        "单击后应选中"
    assert "1 / %d" % n0 in stat_text(), "计数应为 1"

    # 双击第二张 → 放大预览，选中状态不变
    ms["dblclick"](names[1])
    time.sleep(0.1)
    root.update()
    pvs = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
    assert pvs, "双击未打开预览窗"
    pv = pvs[-1]
    cnts = [w.cget("text") for w in pv.winfo_children()
            if isinstance(w, tk.Label) and not w.cget("image")]
    assert any("2 / %d" % n0 in t for t in cnts), "预览计数错误: %s" % cnts
    assert ms["sel"][names[1]] is False, "双击不应改变选中状态"
    print("preview ok:", [t for t in cnts if "/" in t])
    pv.destroy()
    time.sleep(0.1)
    root.update()

    # 多选删除：再加选第二张 → 点「删除选中」→ 确认框 mock 通过
    ms["click"](names[1])
    time.sleep(0.35)
    root.update()
    orig_ask = photos_mod.messagebox.askyesno
    photos_mod.messagebox.askyesno = lambda *a, **kw: True
    try:
        get_btn(win, "删除选中").invoke()
    finally:
        photos_mod.messagebox.askyesno = orig_ask
    time.sleep(0.1)
    root.update()
    left = app.store.photos_list("item", code)
    print("after delete:", len(left))
    assert len(left) == n0 - 2, "删除后库中照片数应为 %d" % (n0 - 2)
    assert names[0] not in left and names[1] not in left, "删除的照片不对"
    assert len(ms["cells"]) == n0 - 2, "网格未重建"
    # 底部缩略图条同步刷新
    strip_names = app.store.photos_list("item", code)
    assert strip_names == left, "底部条数据与库不一致"

    # 全选 → 保存选中（mock 选目录）→ 字节一致
    get_btn(win, "全选").invoke()
    root.update()
    outdir = os.path.join(tmpd, "out")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    photos_mod.filedialog.askdirectory = lambda **kw: outdir
    get_btn(win, "保存选中").invoke()
    root.update()
    import base64 as _b64
    saved = os.listdir(outdir)
    print("saved files:", len(saved))
    assert len(saved) == n0 - 2, "落盘数量应为剩余照片数"
    saved_stems = set()
    for fname in saved:
        with open(os.path.join(outdir, fname), "rb") as f:
            disk = f.read()
        hit = None
        for n in left:
            raw = app.store.photo_data("item", code, n)
            if raw and disk == _b64.b64decode(raw):
                hit = n
                break
        assert hit, "找不到与 %s 字节一致的照片" % fname
        assert hit not in saved_stems, "同一张被保存两次"
        saved_stems.add(hit)
    assert saved_stems == set(left), "落盘集合与剩余照片不一致"
    print("bytes match: True")

    win.destroy()
    root.destroy()
    print("PROBE OK")


if __name__ == "__main__":
    main()
