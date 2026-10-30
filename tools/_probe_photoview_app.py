# -*- coding: utf-8 -*-
"""用真实 App 复现「点📷后查看窗第一张白屏」。

流程与用户操作一致：App 实例（真实库副本+照片）→ 表格选中 WL-02053 →
_open_record_photos → 截取查看窗图片区域算像素标准差（<3 即白屏）。
同时检查 strip._imgs['__view__'] 是否还活着（怀疑被 set_code 清掉）。
"""
import os
import shutil
import sys
import tempfile
import tkinter as tk

from PIL import Image, ImageGrab, ImageStat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
import wm.constants as wconst  # noqa: E402
from wm.store import Store  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_pv_")
wapp.app_dir = lambda: TMP
wconst.app_dir = lambda: TMP      # resolve_data_dir 用的是 constants 里的 app_dir

# 库 + 照片树都放进 TMP/data/（照片目录与库文件同级：photos/<库名>/item/<编号>/）
os.makedirs(os.path.join(TMP, "data"), exist_ok=True)
import sqlite3  # noqa: E402
_dbsrc = sqlite3.connect(r"D:\仓库管理工具\data\warehouse.db")
_dst = sqlite3.connect(os.path.join(TMP, "data", "warehouse.db"))
_dbsrc.backup(_dst)
_dst.close()
_dbsrc.close()
psrc = r"D:\仓库管理工具\data\photos\warehouse"
pdst = os.path.join(TMP, "data", "photos", "warehouse")
shutil.copytree(psrc, pdst)

root = tk.Tk()
app = wapp.App(root)
app.load_data()
root.update()

recs_all = app.store.all_records()
print("records:", len(recs_all),
      "codes:", [r.get("code") for r in recs_all[:5]],
      "path:", app.store.path)
rec = next((r for r in recs_all if r.get("code") == "WL-02053"), None)
if rec is None:
    raise SystemExit("WL-02053 not in copied db")
print("WL-02053 found, strip code before =", app.photo_strip.code)

# 模拟点 📷：先选中行（触发 <<TreeviewSelect>> → _update_detail → set_code），
# 再打开照片查看 —— 与 _on_click 中的顺序一致
kids = app.tree.get_children()
print("tree rows:", len(kids))
target_iid = None
for iid, r in list(app.by_id.items()):
    if r.get("code") == "WL-02053":
        target_iid = str(iid)
        break
print("target iid:", target_iid, "in tree:", target_iid in kids)
# 模拟用户两步：①点行选中（详情区照片条 set_code）②点 📷 打开查看窗
app.photo_strip.set_code("WL-02053")
root.update()
print("strip code after set_code =", app.photo_strip.code)

app._open_record_photos(rec)
root.update()

tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
win = tops[-1]
win.update_idletasks()
root.after(500, lambda: None)
root.update()

# 找查看窗里带 image 的 Label
def find_img_lbls(w, out):
    for c in w.winfo_children():
        try:
            if isinstance(c, tk.Label) and c.cget("image"):
                out.append(c)
        except Exception:
            pass
        find_img_lbls(c, out)

lbls = []
find_img_lbls(win, lbls)
print("image labels in viewer:", len(lbls))
pi = app.photo_strip._imgs.get("__view__")
print("__view__ alive:", pi is not None,
      "size=", pi.width() if pi else None)
if lbls:
    c = lbls[0]
    try:
        c.update_idletasks()
        # 复现杀手场景：查看窗打开后，Treeview 类绑定再次触发选中 → set_code
        # （修复前这一步会把 __view__ PhotoImage 清掉 → 白屏）
        app.photo_strip.set_code("WL-02053")
        root.update()
        root.after(300, lambda: None)
        root.update()
        x, y = c.winfo_rootx(), c.winfo_rooty()
        w, h = c.winfo_width(), c.winfo_height()
        print("label geom:", w, h)
        print("__view__ alive after set_code:", app.photo_strip._imgs.get("__view__") is not None)
        print("win._held_img alive:", getattr(win, "_held_img", None) is not None)
        if w > 5 and h > 5:
            im = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            sd = ImageStat.Stat(im.convert("L")).stddev[0]
            print("set_code 后图片区域 stddev = %.1f （<3 即白屏）" % sd)
    except Exception as e:
        print("grab err:", e)

screenshot.shot(root, os.path.join(ROOT, ".tmpdbg", "pv_app.png"))
root.after(200, root.destroy)
root.mainloop()
print("done")
