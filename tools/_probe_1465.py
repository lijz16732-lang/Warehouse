# -*- coding: utf-8 -*-
"""v1.46.5 探针：表格底部半裁行的游离徽章/复选框修复。

复现路径：窗口调矮 → 滚动到某行被视口下缘裁掉一半 → redraw()。
断言：
1. 被裁行（bb[1]+bb[3] 超出视口）不出现在 pills/chks 贴片表里
2. 所有已放贴片整格都在视口内（y+h <= vh）
3. 完整可见行的贴片不受影响（数量 > 0）
4. 滚回顶部后无游离贴片、贴片数恢复
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk

import wm.app as wapp
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="wm_probe_1465_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP
st = Store(os.path.join(TMP, "warehouse.db"))
for i in range(1, 41):
    rec = blank_record()
    rec.update({"lid": i, "code": "WL-%05d" % i, "brand": "基恩士",
                "category": "传感器", "model": "FS-V%d" % i,
                "qty": 2, "price": 100.0, "listed": 0})
    st.insert(rec)
st.close()

ok = [0, 0]


def check(name, cond):
    ok[0] += 1
    if cond:
        ok[1] += 1
    print(("ok  " if cond else "FAIL") + " " + name)


try:
    ctypes.windll.user32.SetCursorPos(2, 2)
except Exception:
    pass

root = tk.Tk()
root.geometry("1200x520+40+40")
app = wapp.App(root)
app.nb.select(app.tab_inv)
app.load_data()
root.update_idletasks()
root.update()

tree = app.tree
decor = app.decor
vh = int(tree.winfo_height())


def clipped_iids():
    """视口下缘被裁的行 + 完整可见行集合。"""
    cut, full = [], []
    for iid in tree.get_children():
        bb = tree.bbox(str(iid))
        if not bb:
            continue
        if int(bb[1]) + int(bb[3]) > vh:
            cut.append(str(iid))
        elif int(bb[1]) >= int(app._head_height()):
            full.append(str(iid))
    return cut, full


# ---- 1 滚到某个半裁位置（逐步微调 yview 找到被裁行）----
found = None
for step in range(60):
    tree.yview_moveto(step / 200.0)
    root.update()
    decor.redraw()
    cut, full = clipped_iids()
    if cut and full:
        found = (cut, full)
        break
check("找到半裁行场景", found is not None)
cut, full = found if found else ([], [])
check("半裁行不画徽章", all(iid not in decor._pills for iid in cut))
check("半裁行不画复选框", all(iid not in decor._chks for iid in cut))

# ---- 2 已放贴片整格都在视口内 ----
bad = []
for iid, cv in list(decor._pills.items()):
    info = cv.place_info()
    if info and int(info["y"]) + int(cv.winfo_height()) > vh:
        bad.append(iid)
check("已放徽章都在视口内", not bad)
bad = []
for iid, cv in list(decor._chks.items()):
    info = cv.place_info()
    if info and int(info["y"]) + int(cv.winfo_height()) > vh:
        bad.append(iid)
check("已放复选框都在视口内", not bad)

# ---- 3 完整行的贴片不受影响 ----
n_pill = sum(1 for iid in full if iid in decor._pills)
n_chk = sum(1 for iid in full if iid in decor._chks)
check("完整行贴片正常（徽章 %d/复选框 %d）" % (n_pill, n_chk),
      n_pill > 0 and n_chk > 0)

# ---- 4 滚回顶部：被裁行（如有）同样不画贴片 ----
tree.yview_moveto(0)
root.update()
decor.redraw()
cut, full = clipped_iids()
check("顶部被裁行不画贴片（被裁 %d 行）" % len(cut),
      all(iid not in decor._pills and iid not in decor._chks for iid in cut))
check("顶部贴片数为正", len(decor._pills) > 0 and len(decor._chks) > 0)

print("%d/%d 项通过" % (ok[1], ok[0]))
root.destroy()
sys.exit(0 if ok[1] == ok[0] else 1)
