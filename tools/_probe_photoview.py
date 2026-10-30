# -*- coding: utf-8 -*-
"""复现照片查看窗「第一张白屏」：真实库副本 + 真实 PhotoStrip.view()。

打开查看窗 → 等待映射 → ImageGrab 截取图片区域 → 统计像素标准差：
stddev≈0 即白屏复现；再翻页对照（第二张是否正常），定位差异。
"""
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import io
import tkinter as tk

from PIL import Image, ImageGrab, ImageStat

from wm import constants  # noqa: F401  载入 CLR_*
from wm.photos import PhotoStrip
from wm.store import Store


class FakeApp(object):
    fam = "Microsoft YaHei"

    def _status(self, msg):
        print("[status]", msg)

    def _photo_codes_changed(self, kind, code):
        pass


def region_stats(lbl):
    x = lbl.winfo_rootx()
    y = lbl.winfo_rooty()
    w = lbl.winfo_width()
    h = lbl.winfo_height()
    im = ImageGrab.grab(bbox=(x, y, x + max(w, 10), y + max(h, 10)))
    return ImageStat.Stat(im.convert("L")).stddev[0]


def main():
    # 与真实 App 一致：开 DPI 感知（白屏只在真实 App 出现，优先怀疑 DPI）
    try:
        from wm.screen import enable_dpi_awareness
        enable_dpi_awareness()
        print("dpi awareness: on")
    except Exception as e:
        print("dpi awareness: off", e)
    src = r"D:\仓库管理工具\data\warehouse.db"
    tmpd = os.path.join(tempfile.gettempdir(), "probe_photoview")
    os.makedirs(tmpd, exist_ok=True)
    tmp = os.path.join(tmpd, "warehouse.db")
    shutil.copy(src, tmp)
    # 照片目录与库文件同级：photos/<库名>/item/<编号>/
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
    strip.set_code("WL-02053")
    root.update()

    names = app.store.photos_list("item", "WL-02053")
    print("photos:", len(names))

    strip.view(names[0])
    # 找到查看窗
    tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    win = tops[-1]
    win.update_idletasks()
    root.after(600, lambda: None)
    root.update()

    # 找查看窗里的图片 Label（bg==CLR_BG 且 expand）
    def find_lbl(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Label) and c.cget("image"):
                im_name = c.cget("image")
                try:
                    img = c.nametowidget(im_name) if str(im_name).startswith("pyimage") else None
                except Exception:
                    img = None
                yield c, im_name
            yield from find_lbl(c)
    lbls = list(find_lbl(win))
    print("labels with image:", len(lbls))
    if lbls:
        c, im_name = lbls[0]
        # PhotoImage 对象的宽高（Tk 侧数据是否在）
        try:
            pi = strip._imgs.get("__view__")
            print("view PhotoImage:", pi, "size=", pi.width() if pi else None)
        except Exception as e:
            print("pi err:", e)
        print("label image cfg:", im_name, "label size:", c.winfo_width(), c.winfo_height())
        sd = region_stats(c)
        print("首屏图片区域 stddev = %.1f  （<3 即白屏）" % sd)

    # 模拟翻页：直接再 view 第二张（窗口已映射时创建的 PhotoImage）
    win.destroy()
    root.update()
    strip.view(names[1])
    tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    win2 = tops[-1]
    win2.update_idletasks()
    root.after(600, lambda: None)
    root.update()
    lbls2 = list(find_lbl(win2))
    if lbls2:
        c2, _ = lbls2[0]
        sd2 = region_stats(c2)
        print("翻页后图片区域 stddev = %.1f" % sd2)

    root.destroy()


if __name__ == "__main__":
    main()
