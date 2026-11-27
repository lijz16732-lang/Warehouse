# -*- coding: utf-8 -*-
"""探针：手机数据页贴片上的 Ctrl/Shift 多选 + Ctrl+A（v1.45.2）。

背景：手机数据页悬停的蓝色单元格贴片（CellHover）盖住格子吞掉点击，
转发回 tree 时丢了 state 修饰键 → Ctrl/Shift+点击被当成普通点击，
extended 多选被冲掉。v1.45.2 在 CellHover._forward 补转发 state。

断言（全部走真实链路：事件打到贴片 lbl → _forward → tree）：
1) Ctrl+点贴片 = 加选该行（保留已选）
2) 再 Ctrl+点同一格 = 取消该行（toggle）
3) Shift+点 = 从焦点行加选一片（区间）
4) 普通+点 = 恢复单选（旧行为不变）
5) Ctrl+A / Ctrl+Shift+A？ —— <Control-a> 与 <Control-A> 都绑全选
用法：.venv310/Scripts/python.exe tools/_probe_phone_modselect.py
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402

import wm.app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_phms_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP

st = Store(os.path.join(TMP, "warehouse.db"))
ITEMS = [
    (1, "APP-0001", "西门子", "驱动器", "全新", "S10MD", 1, 1200),
    (2, "APP-0002", "施耐德", "断路器", "9成新", "GV2ME08", 2, 260),
    (3, "APP-0003", "欧姆龙", "传感器", "全新", "E3Z-D61", 8, 120),
    (4, "APP-0004", "基恩士", "放大器", "全新", "FS-V11", 5, 880),
    (5, "APP-0005", "三菱", "PLC", "9成新", "FX3U", 3, 1500),
]
for lid, code, b, cat, cond, m, q, p in ITEMS:
    rec = blank_record()
    rec.update({"lid": lid, "code": code, "brand": b, "category": cat,
                "condition": cond, "model": m, "qty": q, "price": p})
    st.m_upsert_item(rec)      # 手机区数据
st.close()

try:                            # 探针铁律：指针移开，防悬停贴片/轮询干扰
    ctypes.windll.user32.SetCursorPos(2, 2)
except Exception:
    pass

root = tk.Tk()
root.geometry("1200x800+20+20")     # 真显形：贴片链路要用 bbox/winfo_rootx
app = wapp.App(root)
tab = app.tab_phone
app.nb.select(tab)
tab.refresh_tab()
root.update()

tree = tab.tree_items
ch = tab._cell_hovers[tree]
kids = [str(i) for i in tree.get_children()]
r0, r1, r2, r3, r4 = kids[:5]

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print("  ok  %s" % name)
    else:
        print("  FAIL %s -> %r" % (name, detail))


def sel():
    return [str(i) for i in tree.selection()]


def press_via_patch(iid, state):
    """真实链路：把贴片盖在该行第一格上，向 lbl 发一次 Button-1。"""
    bb = tree.bbox(iid, "#1")
    assert bb, "bbox 取不到 %s" % iid
    bx, by, bw, bh = bb
    ch.lbl.place(x=bx, y=by, width=bw, height=bh)
    root.update()
    ch.lbl.event_generate("<Button-1>", x=6, y=6, state=state,
                          rootx=ch.lbl.winfo_rootx() + 6,
                          rooty=ch.lbl.winfo_rooty() + 6)
    root.update()
    ch.hide()
    root.update()


def main():
    chk("手机库存表 5 行", len(kids) == 5, kids)

    # ① 普通+点贴片 = 单选该行（旧行为不变）
    tree.selection_set([r0, r1])
    press_via_patch(r3, 0)
    chk("普通点贴片 = 单选该行", sel() == [r3], str(sel()))

    # ② Ctrl+点 = 加选
    tree.selection_set([r0, r1])
    tree.focus(r1)
    press_via_patch(r3, 0x0004)
    chk("Ctrl+点贴片 = 加选该行", set(sel()) == {r0, r1, r3}, str(sel()))

    # ③ 再 Ctrl+点同一格 = 取消该行
    press_via_patch(r3, 0x0004)
    chk("Ctrl+再点 = 取消该行", set(sel()) == {r0, r1}, str(sel()))

    # ④ Shift+点 = 从焦点行加选一片
    tree.selection_set([r1])
    tree.focus(r1)
    press_via_patch(r4, 0x0001)
    chk("Shift+点 = 区间加选 r1..r4",
        set(sel()) == {r1, r2, r3, r4}, str(sel()))

    # ⑤ Ctrl+A 全选（真按键事件走 <Control-a> 绑定）
    tree.selection_remove(*kids)
    tree.focus(r0)
    tree.focus_set()
    tree.event_generate("<Control-a>")
    root.update()
    chk("Ctrl+A = 全选", set(sel()) == set(kids), str(sel()))
    tree.selection_remove(*kids)
    tree.event_generate("<Control-A>")     # 大写（CapsLock/Shift+A）
    root.update()
    chk("Ctrl+Shift+A(大写) = 全选", set(sel()) == set(kids), str(sel()))

    # ⑥ 修饰键转发落到了 tree：state 字段已随 _forward 传递
    tsrc = open(os.path.join(ROOT, "wm", "theme.py"), encoding="utf-8").read()
    chk("CellHover._forward 转发 state",
        '"state": int(getattr(e, "state"' in tsrc)

    root.destroy()
    print("\n%d 项通过，%d 项失败" % (PASS, 0 if PASS else 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
