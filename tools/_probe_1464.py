# -*- coding: utf-8 -*-
"""v1.46.4 探针：表尾单行条（汇总 + 数字分页）+ 侧栏数字角标。

验证点：
1. 汇总统计与数字分页在同一行（_pager_frame 下同时有 lbl_sum_* 与 _pages_frame）
2. 旧「首页/上一页/下一页/末页」按钮已移除；lbl_page 文字条已移除
3. 多页时出现 ‹ 1 2 3 › 数字页钮，当前页为 PageBtn 主动态（无手型光标）
4. 点数字页钮能翻页；省略号「…」在页数多时出现
5. 侧栏角标：库存列表=记录总数；无手机数据/客户应收/进行中流程时无角标
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk

import wm.app as wapp
from wm.imgbtn import PageBtn
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="wm_probe_1464_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP
st = Store(os.path.join(TMP, "warehouse.db"))
for i in range(1, 13):
    rec = blank_record()
    rec.update({"lid": i, "code": "WL-%05d" % i, "brand": "基恩士",
                "category": "传感器", "model": "FS-V%d" % i,
                "qty": 2, "price": 100.0 + i})
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
root.geometry("1280x820+20+20")
app = wapp.App(root)
app.nb.select(app.tab_inv)
app.load_data()
root.update_idletasks()
root.update()

from wm import constants as C

# ---- 1 单行条结构 ----
check("汇总标签与分页容器同条", app.lbl_sum_hit.master is app._pages_frame.master)
check("lbl_page 文字条已移除", not hasattr(app, "lbl_page"))

# ---- 2 旧按钮移除 / 数字页钮出现 ----
texts = []
for w in app._pages_frame.winfo_children():
    texts.append(getattr(w, "_text", w.cget("text")))
check("数字页钮 1 出现（单页）", "1" in texts)
check("无「首页/末页」旧按钮", not any("首页" in t or "末页" in t for t in texts))

# ---- 3 多页：每页 6 条 → 2 页 ----
app._set_page_size("6")
root.update()
texts = [getattr(w, "_text", w.cget("text"))
         for w in app._pages_frame.winfo_children()]
check("3 页出现 ‹ 1 2 3 ›", texts == ["‹", "1", "2", "›"])
btns = [w for w in app._pages_frame.winfo_children() if isinstance(w, PageBtn)]
cur = [b for b in btns if b._active]
check("当前页只有一颗主动态", len(cur) == 1 and cur[0]._text == "1")
check("主动态无手型光标", cur[0].cget("cursor") == "arrow")
check("非当前页有手型光标", any(b.cget("cursor") == "hand2" for b in btns))

# ---- 4 点页钮翻页 ----
target = [b for b in btns if b._text == "2"][0]
target.invoke()
root.update()
check("点「2」翻到第 2 页", app.page == 2)
cur = [b for b in app._pages_frame.winfo_children()
       if isinstance(b, PageBtn) and b._active]
check("主动态跟随到 2", len(cur) == 1 and cur[0]._text == "2")

# ---- 5 省略号：每页 1 条 → 12 页 ----
app._set_page_size("1")
root.update()
texts = [getattr(w, "_text", w.cget("text"))
         for w in app._pages_frame.winfo_children()]
check("12 页含 … 省略号", "…" in texts and "12" in texts)

# ---- 6 侧栏角标 ----
nav = app.nav
check("库存列表角标=记录总数 12", nav._badges.get(0) == "12")
idx_phone = app.nb.index(app.tab_phone)
idx_wf = app.nb.index(app.tab_workflow)
idx_cust = app.nb.index(app.tab_customer)
check("手机数据无角标（无待转入）", not nav._badges.get(idx_phone))
check("制作流程无角标（无进行中）", not nav._badges.get(idx_wf))
check("客户管理无角标（无应收）", not nav._badges.get(idx_cust))
bdg = nav._badge_lbls[0]
check("角标胶囊配色（当前页白底蓝字）", bdg.cget("bg") == C.CLR_SIDE_ON
      and bdg.cget("fg") == C.CLR_ACCENT)
check("汇总仍在同条（翻页不丢）", app.lbl_sum_hit.winfo_exists()
      and app.lbl_sum_hit.master is app._pages_frame.master)

print("%d/%d 项通过" % (ok[1], ok[0]))
root.destroy()
sys.exit(0 if ok[1] == ok[0] else 1)
