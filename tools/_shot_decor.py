# -*- coding: utf-8 -*-
"""探针：v1.31.1 表格网格线 + 上架开关（对齐断言 + 截图）。"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.editor import RecordDialog  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

tmp = tempfile.mkdtemp(prefix="wm_shot_decor_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()
root = tk.Tk()
app = wapp.App(root)
rows = []
for i, brand in enumerate(["ABB", "西门子", "三菱", "施耐德", "台达",
                           "欧姆龙", "汇川", "正泰"], start=1):
    rec = blank_record()
    rec.update({"code": "WL-%05d" % i, "brand": brand, "category": "变频器",
                "model": "M%d" % i, "condition": "全新", "price": 88.0 + i,
                "qty": 5, "shelf": "6排A-3", "listed": 1 if i % 3 else 0,
                "remark": "网格线对齐测试"})
    rows.append(rec)
app.store.insert_many(rows)
app.load_data()
root.update()
root.update_idletasks()
root.update()


def shot(name):
    root.update_idletasks()
    root.update()
    screenshot.capture_window("仓管家 · 仓库管理系统", os.path.join(OUT, name))


ok = True


def chk(label, cond, extra=""):
    global ok
    print(("  [PASS] " if cond else "  [FAIL] ") + label + ("" if cond else "  " + str(extra)))
    if not cond:
        ok = False


print("== 1. 网格线与开关数量 ==")
t = app.tree
kids = t.get_children()
decor = app.decor
chk("覆盖层已创建", decor is not None)
chk("每行都有开关贴片", len(decor._pills) == len(kids),
    "%d/%d" % (len(decor._pills), len(kids)))
nonempty = [(i, t.set(i, "listed")) for i in kids if t.set(i, "listed")]
chk("上架列不显示文字（只有开关）", not nonempty, nonempty[:3])

print("== 2. 开关与单元格对齐 ==")
bad = []
for iid in kids:
    cv = decor._pills.get(str(iid))
    bb = t.bbox(str(iid), column="listed")
    if cv is None or not bb:
        bad.append((iid, "no pill/bbox"))
        continue
    info = cv.place_info()
    got = tuple(int(float(info[k])) for k in ("x", "y", "width", "height"))
    if got != tuple(int(v) for v in bb):
        bad.append((iid, got, tuple(bb)))
chk("开关位置 = bbox", not bad, bad[:3])

print("== 3. 竖线位置 ==")
disp = t["displaycolumns"]
if not disp or list(disp) == ["#all"] or disp == "all":
    disp = list(t["columns"])
widths = [int(t.column(c, "width")) for c in disp]
vs = [f for f in decor._v if f.place_info()]
xs = sorted(int(float(f.place_info()["x"])) for f in vs)
expect = []
acc = 0
for w in widths:
    acc += w
    expect.append(acc)
expect = [x for x in expect if 2 < x < int(t.winfo_width()) - 1]
chk("竖线覆盖列边界", len(vs) == len(expect), "%d vs %d" % (len(vs), len(expect)))
chk("竖线像素对齐", xs == expect, (xs, expect))

print("== 4. 悬停底色跟随 ==")
first_on = [i for i in kids if app.by_id[str(i)].get("listed")][0]
# 探针窗口可能被其他窗口遮挡，真实鼠标不一定落进来 → 直接驱动 hover 状态
app.hover.set(str(first_on))
root.update()
root.update_idletasks()
root.update()
cv = decor._pills.get(str(first_on))
chk("悬停行开关底色 = 悬停底色", cv is not None and cv["bg"] == app.hover.bg,
    (cv["bg"] if cv else None, app.hover.bg))
shot("decor_hover.png")
app.hover.set(None)
root.update()

print("== 5. 单击开关切换（就地更新，不重载） ==")
rec_id = int(first_on)
before = [r for r in app.store.all_records() if r["id"] == rec_id][0]["listed"]
cv = decor._pills.get(str(first_on))
cv.event_generate("<Button-1>", x=5, y=5)
root.update()
after_rec = [r for r in app.store.all_records() if r["id"] == rec_id][0]
chk("数据库已切换", int(after_rec["listed"]) != int(before),
    (before, after_rec["listed"]))
chk("选中/滚动未丢", t.exists(first_on))
txt = t.set(first_on, "listed")
chk("单元格不再显示上架文字（开关即状态）", txt == "", txt)
chk("下架行带 unlisted tag",
    ("unlisted" in t.item(first_on, "tags")) == (not int(after_rec["listed"])),
    t.item(first_on, "tags"))

print("== 6. 横向滚动后重新贴合 ==")
app._tree_xview("moveto", 0.35)
root.update()
root.update_idletasks()
root.update()
bad = []
for iid in t.get_children():
    cv = decor._pills.get(str(iid))
    bb = t.bbox(str(iid), column="listed")
    if cv is None:
        continue
    info = cv.place_info()
    got = tuple(int(float(info[k])) for k in ("x", "y", "width", "height"))
    if bb and got != tuple(int(v) for v in bb):
        bad.append((iid, got, tuple(bb)))
chk("滚动后开关仍对齐", not bad, bad[:3])
app._tree_xview("moveto", 0.0)
root.update()
shot("decor_inv.png")

print("== 7. 编辑弹窗里的开关 ==")
rec = app.store.all_records()[0]
dlg = RecordDialog(root, dict(rec), app.suggestions(), "编辑记录", app.fam, app=app)
root.update()
root.update_idletasks()
root.update()
tgl = [w for w in dlg.winfo_children()]


def find_toggle(w):
    from wm.toggle import Toggle
    for c in w.winfo_children():
        if isinstance(c, Toggle):
            return c
        got = find_toggle(c)
        if got is not None:
            return got
    return None


tg = find_toggle(dlg)
chk("弹窗里有开关控件", tg is not None)
chk("开关初始态与记录一致",
    tg is not None and tg.is_on() == bool(int(rec.get("listed") or 0)),
    (None if tg is None else tg.is_on(), rec.get("listed")))
if tg is not None:
    tg.event_generate("<Button-1>", x=5, y=5)
    root.update()
    chk("单击后变量翻转",
        dlg.vars["listed"].get() == ("未上架" if int(rec.get("listed") or 0) else "已上架"),
        dlg.vars["listed"].get())
    dlg.update_idletasks()
    root.update()
    screenshot.capture_window("编辑记录", os.path.join(OUT, "decor_editor.png"))
    tg.event_generate("<Button-1>", x=5, y=5)
    root.update()
chk("保存结果可解析", dlg._validate() is None)
dlg._cancel()
root.update()

print()
print("ALL OK" if ok else "HAS FAILURES")
root.destroy()
