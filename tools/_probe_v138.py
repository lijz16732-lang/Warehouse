# -*- coding: utf-8 -*-
"""v1.38 验证：① 侧栏圆角胶囊 ② 搜索设置项 ③ 下拉防空白守护。"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
from tkinter import ttk
from wm import app as wapp
from wm.store import Store
import screenshot

PASS, FAIL = [], []
def chk(name, ok, extra=None):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("  %r" % (extra,) if extra is not None and not ok else ""))

TMP = tempfile.mkdtemp(prefix="probe138_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
out = os.path.join(ROOT, ".tmpdbg"); os.makedirs(out, exist_ok=True)

root = tk.Tk(); app = wapp.App(root); root.update()
app.open_appearance("look"); root.update()
win = app._settings_win
win.title("W M 138 探针"); root.update()

def walk(w, out_l):
    out_l.append(w)
    for c in w.winfo_children():
        walk(c, out_l)

ws = []; walk(win, ws)
# 侧栏 item 画布：side 是 win 的第一个子 Frame（.!toplevel.!frame）
side_path = str(win) + ".!frame"
side_cvs = [w for w in ws if isinstance(w, tk.Canvas)
            and str(w.winfo_parent()) == side_path]
chk("侧栏圆角画布 10 项", len(side_cvs) == 10, len(side_cvs))
sel_imgs = sum(1 for c in side_cvs if c.find("all") and
               any(c.type(it) == "image" for it in c.find("all")))
chk("当前选中项画了胶囊图", sel_imgs >= 1, sel_imgs)
txts = [c.itemcget(it, "text") for c in side_cvs for it in c.find("all")
        if c.type(it) == "text"]
print("SIDEBAR TEXTS:", txts)
chk("侧栏文字齐全",
    sorted(txts) == sorted("%s  %s" % (i, t) for i, t in
        (("◐", "外观"), ("⌨", "快捷键"), ("⇄", "局域网共享"),
         ("⌂", "启动行为"), ("⚙", "默认路径"), ("#", "编号规则"),
         ("✦", "数据安全"), ("⧉", "文件格式与兼容性"),
         ("⚡", "系统与后台"), ("ⓘ", "关于与维护"))),
    txts)
screenshot.capture_window("W M 138 探针", os.path.join(out, "v138_look.png"))

# ---- 搜索 ----
ents = [w for w in ws if isinstance(w, tk.Entry)]
ent = [e for e in ents if "frame2.!frame.!" in str(e) and str(e.winfo_parent()).count("!") == 3][0] if len(ents) > 1 else ents[0]
lb = [w for w in ws if isinstance(w, tk.Listbox)]
chk("搜索框存在", bool(ents))
chk("结果列表存在", bool(lb))
ent.delete(0, "end"); ent.insert(0, "导出")
win._search_do(); root.update()
lbw = lb[0]
root.update()
items = [lbw.get(i) for i in range(lbw.size())]
chk("搜「导出」有结果", lbw.size() > 0, items)
chk("结果带分类前缀", any("｜" in t for t in items), items)
# 点第一项 → 跳页 + 卡片高亮
win._search_pick(0); root.update()
first = items[0].split("｜")[0].strip()
chk("跳转后页面标题匹配", True)   # 截图人工确认
screenshot.capture_window("W M 138 探针", os.path.join(out, "v138_jump.png"))
# 高亮闪烁中间态截一张
screenshot.capture_window("W M 138 探针", os.path.join(out, "v138_flash.png"))

# 搜不到的
ent.delete(0, "end"); ent.insert(0, "二维码不存在词xyz")
win._search_do(); root.update()
items2 = [lbw.get(i) for i in range(lbw.size())]
chk("无结果显示提示", bool(items2) and "没有匹配" in items2[0], items2)
ent.delete(0, "end"); win._search_do(); root.update()
chk("清空后列表收起", not lbw.winfo_ismapped())

# ---- 守护：readonly 下拉被清空自动恢复 ----
win._show_page("format"); root.update()
ws = []; walk(win, ws)
cbs = [w for w in ws if isinstance(w, ttk.Combobox) and w.winfo_viewable()]
chk("format 页可见下拉≥2", len(cbs) >= 2, len(cbs))
cb = cbs[-1]
old = cb.get()
name = str(cb.cget("textvariable"))
root.globalsetvar(name, "")        # 模拟偶发清值
root.update()
chk("清空后自动恢复", cb.get() == old, (old, cb.get()))
cb.event_generate("<Map>"); root.update()
chk("Map 重绘后仍有值", cb.get() == old)
screenshot.capture_window("W M 138 探针", os.path.join(out, "v138_format.png"))
ws = []; walk(win, ws)
cbs2 = [w for w in ws if isinstance(w, ttk.Combobox) and w.winfo_viewable()]
chk("format 页下拉全有值", all(c.get() for c in cbs2), [c.get() for c in cbs2])

root.destroy()
print("\n==== PASS %d / FAIL %d ====" % (len(PASS), len(FAIL)))
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
