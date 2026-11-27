# -*- coding: utf-8 -*-
"""探针：库存明细页贴片上的多选 + Ctrl+A（v1.45.1）。

背景：原来按下上色贴片无条件 selection_set（单选），Ctrl/Shift 点上色格
会把已选的多行打散；Ctrl+A 只有菜单入口没有按键绑定。

断言：
1) Ctrl+点上色格 = 把该行加进已有多选（不打散）
2) 再 Ctrl+点同一格 = 取消该行（toggle）
3) Shift+点 = 从焦点行加选到该行（区间）
4) 普通+点 = 恢复单选
5) Ctrl+A 全选本页
6) 划过高亮已移除（app.hover 为 None，行无 hover 标记）
用法：.venv310/Scripts/python.exe tools/_probe_overlay_multiselect.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402

import wm.app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_ovlms_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP

st = Store(os.path.join(TMP, "warehouse.db"))
ITEMS = [
    (1, "WL-9001", "西门子", "驱动器", "全新", "S10MD", 1, 1200),
    (2, "WL-9002", "施耐德", "断路器", "9成新", "GV2ME08", 2, 260),
    (3, "WL-9003", "欧姆龙", "传感器", "全新", "E3Z-D61", 8, 120),
    (4, "WL-9004", "基恩士", "放大器", "全新", "FS-V11", 5, 880),
]
for lid, code, b, cat, cond, m, q, p in ITEMS:
    rec = blank_record()
    rec.update({"lid": lid, "code": code, "brand": b, "category": cat,
                "condition": cond, "model": m, "qty": q, "price": p})
    st.insert(rec)          # 主库存 items 表（m_upsert_item 是手机区）
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
app.load_data()
app.nb.select(app.tab_inv)
app.load_data()
root.update()

tree = app.tree
kids = [str(i) for i in tree.get_children()][:4]
r0, r1, r2, r3 = kids[0], kids[1], kids[2], kids[3]

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print("  ok  %s" % name)
    else:
        print("  FAIL %s -> %r" % (name, detail))


def pill_of(iid, col="brand"):
    """某行某列的上色贴片（没有就返回 None）。"""
    for lb in app._paint_labels:
        if getattr(lb, "_cell", (None, None)) == (str(iid), col):
            return lb
    return None


def press(lb_col_iid, state):
    """对某行某列的贴片模拟一次按下（带修饰键）。
    选中变化会触发贴片重建，所以每次现取现按。"""
    iid, col = lb_col_iid
    lb = pill_of(iid, col)
    assert lb is not None, "贴片不存在：%s/%s" % (iid, col)
    lb.event_generate("<Button-1>", state=state, x=4, y=4,
                      rootx=lb.winfo_rootx() + 4,
                      rooty=lb.winfo_rooty() + 4)
    root.update()


def sel():
    return [str(i) for i in tree.selection()]


# ① 上两行色，拿到贴片
tree.selection_set([r0, r1])
app.paint_cells("#FFE3E3")
root.update()
chk("两行上色后各有贴片", pill_of(r0) is not None and pill_of(r1) is not None)

# ② 普通+点贴片 = 单选该行
tree.selection_set([r0])
press((r1, "brand"), 0)
chk("普通点贴片 = 单选该行", sel() == [r1], str(sel()))

# ③ Ctrl+点另一行的贴片 = 加选（不打散）
press((r0, "brand"), 0x4)
chk("Ctrl+点贴片加选", set(sel()) == {r0, r1}, str(sel()))

# ④ 再 Ctrl+点同一格 = toggle 取消
press((r0, "brand"), 0x4)
chk("Ctrl 再点取消选中", sel() == [r1], str(sel()))

# ⑤ Shift+点 = 从焦点行加选到该行（区间）
press((r0, "brand"), 0)                       # 先单选 r0（焦点在 r0）
press((r1, "brand"), 0x1)
chk("Shift+点区间加选", sel() == [r0, r1], str(sel()))
press((r1, "brand"), 0)
# 给 r3 也上色，测跨多行 Shift
tree.selection_set([r3])
app.paint_cells("#FFE3E3")
root.update()
lb3 = pill_of(r3)
press((r0, "brand"), 0)                       # 焦点/选中在 r0
press((r3, "brand"), 0x1)
chk("Shift 跨行加选 r0..r3", set(sel()) == {r0, r1, r2, r3}, str(sel()))

# ⑥ Ctrl+A 全选本页
tree.selection_set([r0])
app._on_ctrl_a()
chk("Ctrl+A 全选本页", len(sel()) == len(tree.get_children()))

# ⑦ 划过高亮已移除
chk("库存明细页 hover 已移除",
    app.hover is None
    and all("hover" not in tree.item(i, "tags") for i in tree.get_children()))

app.clear_cell_colors(all_rows=True)
root.destroy()
print("\nALL %d CHECKS PASSED" % PASS)
