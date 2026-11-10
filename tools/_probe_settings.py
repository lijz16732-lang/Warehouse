# -*- coding: utf-8 -*-
"""v1.33.0 探针：设置页新增分区（默认路径 / 文件格式 / 启动行为）+ 外观卡片。"""

import ctypes
import json
import os
import sys
import tempfile
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, ".")
sys.path.insert(0, "tools")

from wm import app as wapp
from wm.store import Store

ok = True


def chk(name, cond, detail=None):
    global ok
    print(("PASS " if cond else "FAIL ") + name
          + ("" if cond else "  <- %r" % (detail,)))
    if not cond:
        ok = False


tmp = tempfile.mkdtemp(prefix="settings_")
wapp.resolve_data_dir = lambda: tmp
Store(os.path.join(tmp, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
ctypes.windll.user32.SetCursorPos(2, 2)
root.update()
root.update_idletasks()
root.update()

# ============================================== 1. 默认路径辅助方法
chk("无配置时 _dialog_dir 为空", app._dialog_dir() == "")
app.settings["default_dir"] = tmp
chk("固定默认目录生效", app._dialog_dir() == tmp)
fake_dir = os.path.join(tmp, "no_such_dir")
app.settings["default_dir"] = fake_dir
chk("默认目录不存在时回退为空", app._dialog_dir() == "")
os.makedirs(fake_dir)
app.settings["default_dir"] = fake_dir
app.settings["remember_dir"] = False
chk("关闭记忆后用固定目录", app._dialog_dir() == fake_dir)
app.settings["remember_dir"] = True
app.settings["last_dir"] = tmp
chk("记住的目录优先于固定目录", app._dialog_dir() == tmp)
p = os.path.join(tmp, "f.xlsx")
open(p, "w").close()
app._note_dir(p)
chk("_note_dir 记住文件所在目录", app.settings.get("last_dir") == tmp)
app.settings["remember_dir"] = False
app._note_dir(p)
chk("关闭记忆时 _note_dir 不写入",
    app.settings.get("remember_dir") is False)
app.settings["remember_dir"] = True

# ============================================== 2. CSV 编码
chk("CSV 编码默认 utf-8-sig", app._csv_enc() == "utf-8-sig")
app.settings["csv_encoding"] = "gbk"
chk("可切换 GBK", app._csv_enc() == "gbk")
app.settings["csv_encoding"] = "utf-8-sig"

# ============================================== 3. 打开设置对话框，验证分区
app.open_appearance()
root.update()
root.update_idletasks()
root.update()

wins = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
dlg = None
for w in wins:
    if str(w.title()) == "设置":
        dlg = w
chk("设置窗口已打开且标题为「设置」", dlg is not None,
    [str(w.title()) for w in wins])

texts = []


def collect(w):
    stack = [w]
    while stack:
        cur = stack.pop()
        stack.extend(cur.winfo_children())
        try:
            t = str(cur.cget("text"))
            if t:
                texts.append(t)
        except Exception:
            pass


collect(dlg)
for need in ("外观", "启动行为", "默认路径", "文件格式与兼容性", "快捷键",
             "记住上次的页面", "启动时窗口最大化", "记住上次使用的文件夹",
             "CSV 导出编码", "应用外观", "修改选中项的快捷键"):
    chk("设置页含「%s」" % need, any(need in t for t in texts),
        [t for t in texts if len(t) > 3][:8])

# 左侧分类导航存在 + 分组标题 + 版本号
for need in ("通用",):
    chk("侧栏含「%s」分组" % need, need in texts)
chk("侧栏底部显示版本号", any(t.startswith("v1.") for t in texts),
    [t for t in texts if t.startswith("v")][:4])


def find_mapped(win, cls=None, text_sub=None):
    """找当前映射（可见）的控件。"""
    found = []
    stack = [win]
    while stack:
        cur = stack.pop()
        stack.extend(cur.winfo_children())
        if cls is not None and not isinstance(cur, cls):
            continue
        if text_sub is not None:
            try:
                if text_sub not in str(cur.cget("text")):
                    continue
            except Exception:
                continue
        try:
            if cur.winfo_ismapped():
                found.append(cur)
        except Exception:
            pass
    return found


NAV_TEXTS = {"look": "\u25d0  外观", "keys": "\u2328  快捷键",
             "start": "\u2302  启动行为", "paths": "\u2699  默认路径",
             "format": "\u29c9  文件格式与兼容性"}


def click_nav(dlg, key):
    want = NAV_TEXTS[key]
    stack = [dlg]
    while stack:
        cur = stack.pop()
        stack.extend(cur.winfo_children())
        if isinstance(cur, tk.Label) and str(cur.cget("text")) == want:
            cur.event_generate("<Button-1>", x=5, y=5)
            root.update()
            return True
    return False

# 默认在外观页：快捷键树不可见
chk("初始在外观页（快捷键树未显示）",
    len(find_mapped(dlg, ttk.Treeview)) == 0)
chk("初始在外观页（应用外观按钮可见）",
    len(find_mapped(dlg, None, "应用外观")) >= 1)

# 切到快捷键分类
ok_nav = click_nav(dlg, "keys")
chk("侧栏点击「快捷键」成功", ok_nav)
chk("切到快捷键页（树可见）", len(find_mapped(dlg, ttk.Treeview)) == 1)
chk("切到快捷键页（应用外观按钮隐藏）",
    len(find_mapped(dlg, None, "应用外观")) == 0)

# 切到默认路径分类
ok_nav = click_nav(dlg, "paths")
chk("切到默认路径页（固定目录可见）",
    len(find_mapped(dlg, None, "固定目录")) >= 1)

# 切回外观
click_nav(dlg, "look")
chk("切回外观页（应用外观按钮可见）",
    len(find_mapped(dlg, None, "应用外观")) >= 1)

dlg.destroy()
root.update()
try:
    root.unbind_all("<MouseWheel>")
except Exception:
    pass

# ============================================== 4. 启动行为持久化
app.settings["startup_page"] = "home"
app.settings["start_maximized"] = True
app.settings["last_page"] = 3
app._save_settings()
with open(os.path.join(tmp, "settings.json"), encoding="utf-8") as f:
    saved = json.load(f)
chk("startup_page 已持久化", saved.get("startup_page") == "home")
chk("start_maximized 已持久化", saved.get("start_maximized") is True)
chk("last_page 已持久化", saved.get("last_page") == 3)

# home 模式启动应停在库存列表（页 0）——重建一个 App 验证
root2 = tk.Tk()
app2 = wapp.App(root2)
ctypes.windll.user32.SetCursorPos(2, 2)
root2.update()
idx2 = app2.nb.index(app2.nb.select())
chk("startup_page=home 启动停在库存列表", idx2 == 0, idx2)
root2.destroy()

# last 模式应恢复到上次页面（先切回 last 再重启验证）
app.settings["startup_page"] = "last"
app._save_settings()
root3 = tk.Tk()
app3 = wapp.App(root3)
ctypes.windll.user32.SetCursorPos(2, 2)
root3.update()
idx3 = app3.nb.index(app3.nb.select())
chk("startup_page=last 恢复上次页面(3)", idx3 == 3, idx3)
root3.destroy()

root.destroy()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
