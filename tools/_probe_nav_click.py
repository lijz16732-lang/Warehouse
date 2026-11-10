# -*- coding: utf-8 -*-
"""探针：点组名文字应能折叠/展开分组。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk

from wm.nav import FunctionNav


class FakeApp:
    ui_scale = 1.0

    def show_page(self, idx):
        print("show_page", idx)


root = tk.Tk()
root.geometry("200x400+100+100")
app = FakeApp()
nav = FunctionNav(root, app, "Microsoft YaHei")

fails = []


def find_title_lbl(title):
    # 组名 Label：文本等于组名的那个
    for w in nav.winfo_children():
        pass
    # 直接遍历所有后代
    stack = list(nav.winfo_children())
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if isinstance(w, tk.Label) and str(w.cget("text")) == title:
            return w
    return None


def click_title(title):
    # 每次重新找（_render 会销毁重建控件），模拟真实点击
    lbl = find_title_lbl(title)
    if lbl is None:
        fails.append("找不到组名 Label: " + title)
        return None
    seq = "<Button-1>"
    binding = lbl.bind(seq)
    if not binding:
        fails.append("%s 未绑定 <Button-1>" % title)
        return None
    root.update()
    e = tk.Event()
    e.widget = lbl
    e.x = e.y = 5
    lbl.event_generate("<Enter>")
    lbl.event_generate(seq, x=5, y=5)
    root.update()
    return lbl


root.update()
for t in ("库存管理", "销售管理", "数据报表", "系统"):
    if find_title_lbl(t) is None:
        fails.append("找不到组名 Label: " + t)
        continue
    before = t in nav.expanded
    click_title(t)
    after = t in nav.expanded
    if before == after:
        fails.append("点组名「%s」未切换（%s -> %s）" % (t, before, after))
    # 再点回来
    click_title(t)
    if (t in nav.expanded) != before:
        fails.append("点组名「%s」第二次未还原" % t)

root.destroy()
if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("PASS: 点组名文字可折叠/展开，4 个分组均验证")
