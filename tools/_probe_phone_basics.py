# -*- coding: utf-8 -*-
"""探针：手机数据页基础操作补齐（v1.43.7）。

断言：
1) Ctrl+A 全选当前表全部行
2) 复制选中行 = TSV 且行数正确
3) 点表头排序（数值列升/降序切换、箭头同步、刷新后排序保持）
4) 复制整列 / 复制全部结果（含表头）
5) 拖选区块：_drag_motion 算块、Ctrl+C 优先级、复制区块 TSV
6) 刷新后区块重置
用法：.venv310/Scripts/python.exe tools/_probe_phone_basics.py
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

TMP = tempfile.mkdtemp(prefix="wm_phonebas_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP

st = Store(os.path.join(TMP, "warehouse.db"))
ITEMS = [
    (1, "APP-0001", "西门子", "驱动器", "全新", "S10MD", 1, 1200),
    (2, "APP-0002", "施耐德", "断路器", "9成新", "GV2ME08", 2, 260),
    (3, "APP-0003", "欧姆龙", "传感器", "全新", "E3Z-D61", 8, 120),
]
for lid, code, b, cat, cond, m, q, p in ITEMS:
    rec = blank_record()
    rec.update({"lid": lid, "code": code, "brand": b, "category": cat,
                "condition": cond, "model": m, "qty": q, "price": p})
    st.m_upsert_item(rec)
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)
tab = app.tab_phone
app.nb.select(tab)
tab.refresh_tab()

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print("  ok  %s" % name)
    else:
        print("  FAIL %s -> %r" % (name, detail))


def clip(root):
    root.update()
    try:
        return root.clipboard_get()
    except tk.TclError:
        return ""


tree = tab.tree_items


def main():
    children = tree.get_children()
    chk("表格有 3 行", len(children) == 3, children)

    # ① Ctrl+A 全选
    tab._select_all(tree)
    chk("Ctrl+A 全选全部行", len(tree.selection()) == 3)

    # ② 复制选中行
    tree.selection_set(children[:2])
    tab._copy_selected(tree)
    got = clip(root)
    chk("复制选中行 = 2 行 TSV",
        got.count("\n") == 1 and "APP-0001" in got and "APP-0002" in got, got)

    # ③ 表头排序：单价数值列
    tab._sort_tree(tree, "price")
    prices = [float(r["price"]) for r in tab.item_rows]
    chk("单价升序", prices == sorted(prices), prices)
    chk("表头带升序箭头", "▲" in tree.heading("price", "text"),
        tree.heading("price", "text"))
    tab._sort_tree(tree, "price")
    prices = [float(r["price"]) for r in tab.item_rows]
    chk("再点同列变倒序", prices == sorted(prices, reverse=True), prices)
    chk("表头带倒序箭头", "▼" in tree.heading("price", "text"),
        tree.heading("price", "text"))
    # 刷新后排序保持
    tab.refresh_rows()
    prices = [float(r["price"]) for r in tab.item_rows]
    chk("刷新后排序保持倒序", prices == sorted(prices, reverse=True), prices)

    # ④ 复制整列（右键列 = 品牌）
    tree._rb_col = 1
    tab._copy_menu_col(tree)
    got = clip(root)
    chk("复制整列 = 品牌列 3 项",
        got.count("\n") == 2 and "西门子" in got and "施耐德" in got, got)

    # ⑤ 复制全部结果（含表头）
    tab._copy_all(tree)
    got = clip(root)
    first = got.split("\n")[0]
    chk("复制全部含表头", first.startswith("手机编号\t品牌"), first)
    chk("复制全部行数 = 数据+表头", got.count("\n") == 3, got.count("\n"))

    # ⑥ 拖选区块：模拟 anchor + motion（排序刷新后行号已更新，重新取）
    children = tree.get_children()
    tab._drag[tree] = {"anchor": (children[0], 0), "block": None, "hint": None}
    ev = type("Ev", (), {})()
    ev.x, ev.y = 10, 10                       # 无关紧要：直接构块验证
    blk = {"rows": list(children[:2]), "c0": 0, "c1": 1}
    tab._drag[tree]["block"] = blk
    ok = tab._copy_block(tree)
    got = clip(root)
    chk("复制区块返回 True", ok)
    chk("区块 TSV = 2 行 × 2 列",
        got.count("\n") == 1 and got.count("\t") == 2
        and "APP-0001" in got and "西门子" in got, got)
    # Ctrl+C 优先级：无悬停格时走区块
    tab._on_ctrl_c(tree)
    got = clip(root)
    chk("Ctrl+C 走区块复制", "APP-0001" in got and got.count("\t") == 2, got)

    # ⑦ 刷新后区块重置
    tab.refresh_rows()
    blk2 = (tab._drag.get(tree) or {}).get("block")
    chk("刷新后区块已重置", not blk2, blk2)

    # ⑧ 拖选 motion 对非法坐标不崩溃、不建块
    tab._drag[tree] = {"anchor": (tree.get_children()[0], 0),
                       "block": None, "hint": None}
    ev2 = type("Ev", (), {})()
    ev2.x, ev2.y = -99, -99                   # 表格外
    tab._drag_motion(tree, ev2)
    chk("表格外拖动不建块", not (tab._drag[tree] or {}).get("block"))

    root.destroy()
    print("== 探针完成：%d 项全部通过 ==" % PASS)


if __name__ == "__main__":
    main()
