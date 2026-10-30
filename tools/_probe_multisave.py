# -*- coding: utf-8 -*-
"""验证照片查看窗「多选保存」缩略图版：真实库副本 + 真实 PhotoStrip.view()。

断言：缩略图单元数量 = 照片数、默认全选、单击切换选中、双击打开放大预览、
取消一张后保存落盘数量与字节正确。
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

    # dlg 是 win 的子 Toplevel
    sub = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
    assert sub, "多选保存弹窗没有打开"
    dlg = sub[-1]
    dlg.update_idletasks()
    root.update()

    # 找缩略图单元：带 highlightthickness 的 Frame（选中态用边框色表达）
    cells = []

    def find_cells(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Frame) and int(c.cget("highlightthickness")) == 2:
                cells.append(c)
            find_cells(c)
    find_cells(dlg)
    print("cell count:", len(cells))
    assert len(cells) == len(names), "缩略图单元数量与照片数不符"
    for c in cells:
        assert c.cget("highlightbackground") == constants.CLR_ACCENT, \
            "默认应全选（边框应为选中色）"

    # 程序化交互句柄（event_generate 模拟点击有假阳性，不可靠）
    import time
    ms = dlg._msel
    sel, cells_map = ms["sel"], ms["cells"]
    fr0, cap0 = cells_map[names[0]]

    # 单击第一张 → 260ms 后取消选中（边框变普通色、✓ 消失）
    ms["click"](names[0])
    time.sleep(0.35)
    root.update()
    assert fr0.cget("highlightbackground") == constants.CLR_BORDER, \
        "单击后应取消选中"
    assert not cap0.cget("text").startswith("✓"), "取消选中后不应有 ✓"

    # 再单击 → 恢复选中
    ms["click"](names[0])
    time.sleep(0.35)
    root.update()
    assert fr0.cget("highlightbackground") == constants.CLR_ACCENT, \
        "再次单击应恢复选中"

    # 双击第二张 → 立即打开放大预览窗，且不改变选中状态（待定切换被取消）
    ms["dblclick"](names[1])
    time.sleep(0.1)
    root.update()
    sub2 = [w for w in dlg.winfo_children() if isinstance(w, tk.Toplevel)]
    assert sub2, "双击未打开放大预览窗"
    pv = sub2[-1]
    pv_img_labels = [w for w in pv.winfo_children() if isinstance(w, tk.Label)
                     and w.cget("image")]
    assert pv_img_labels, "预览窗没有大图"
    cnt_lbls = [w for w in pv.winfo_children() if isinstance(w, tk.Label)
                and not w.cget("image")]
    assert any("2 / %d" % len(names) in w.cget("text") for w in cnt_lbls), \
        "预览窗计数错误: %s" % [w.cget("text") for w in cnt_lbls]
    print("preview ok:", [w.cget("text") for w in cnt_lbls])
    assert sel[names[1]] is True, "双击不应改变选中状态"
    pv.destroy()
    root.update()

    # 取消第一张（程序化单击，260ms 生效）→ 保存 → 落盘数量 = 照片数 - 1
    ms["click"](names[0])
    time.sleep(0.35)
    root.update()
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
    assert len(saved) == len(names) - 1, "落盘数量应为照片数-1"

    import base64 as _b64
    saved_stems = set()
    for fname in saved:
        with open(os.path.join(outdir, fname), "rb") as f:
            disk = f.read()
        hit = None
        for n in names:
            raw = app.store.photo_data("item", code, n)
            if raw and disk == _b64.b64decode(raw):
                hit = n
                break
        assert hit, "找不到与 %s 字节一致的照片" % fname
        assert hit not in saved_stems, "同一张被保存两次: %s" % hit
        saved_stems.add(hit)
    assert saved_stems == set(names[1:]), "被取消的那张不应落盘"
    print("bytes match: True（取消的那张未落盘）")

    dlg.destroy()
    win.destroy()
    root.destroy()
    print("PROBE OK")


if __name__ == "__main__":
    main()
