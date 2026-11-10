# -*- coding: utf-8 -*-
"""v1.34.0 新设置探针：自动备份 / 数据文件夹 / 手机访问开关 / 列标题改名 / 权限。

全部用临时数据目录，不碰真实库。
"""
import ctypes
import json
import os
import sys
import tempfile
import time
import tkinter as tk
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wm import app as wapp                    # noqa: E402
from wm.lan import LanServer                  # noqa: E402
from wm.store import Store                    # noqa: E402

TMP = tempfile.mkdtemp(prefix="probe134_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

fails = []


def chk(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok:
        fails.append(name)


root = tk.Tk()
app = wapp.App(root)
ctypes.windll.user32.SetCursorPos(2, 2)
root.update(); root.update_idletasks(); root.update()

# ================================================== 1. 自动备份
bak_dir = os.path.join(os.path.dirname(os.path.abspath(app.db_path)), "backups")
# 1a. 关闭开关 → 不备份
app.settings["auto_backup"] = False
app.settings["last_auto_backup"] = 0
app._startup_auto_backup()
chk("关闭自动备份不产生文件", not os.path.isdir(bak_dir)
    or not [n for n in os.listdir(bak_dir) if n.startswith("启动备份_")])

# 1b. 每天频率 + last=0 → 立即备份
app.settings["auto_backup"] = True
app.settings["auto_backup_freq"] = "daily"
app._startup_auto_backup()
baks = [n for n in os.listdir(bak_dir) if n.startswith("启动备份_")]
chk("触发一次启动备份", len(baks) == 1, str(baks))
chk("记录 last_auto_backup", app.settings.get("last_auto_backup", 0) > 0)

# 1c. 刚备份过 → 不重复
t = app.settings["last_auto_backup"]
app._startup_auto_backup()
baks = [n for n in os.listdir(bak_dir) if n.startswith("启动备份_")]
chk("周期内不重复备份", len(baks) == 1 and app.settings["last_auto_backup"] == t)

# 1d. 每周频率 + 8 天前 → 触发（sleep 1.1s 避免与上一份同秒重名）
app.settings["auto_backup_freq"] = "weekly"
app.settings["last_auto_backup"] = time.time() - 8 * 86400
time.sleep(1.1)
app._startup_auto_backup()
chk("每周频率到期触发", len([n for n in os.listdir(bak_dir)
                             if n.startswith("启动备份_")]) == 2)

# 1e. 保留份数清理：keep=2，造 4 份
app.settings["auto_backup_keep"] = 2
for i in range(3):
    p = os.path.join(bak_dir, "启动备份_2026010%d_000000.db" % (i + 1))
    with open(p, "w") as f:
        f.write("x")
    os.utime(p, (time.time() - 100000 + i * 1000,) * 2)
app.settings["last_auto_backup"] = time.time() - 9 * 86400
app._startup_auto_backup()
baks = sorted(n for n in os.listdir(bak_dir) if n.startswith("启动备份_"))
chk("超出保留份数自动清理", len(baks) == 2, str(baks))

# ================================================== 2. 手机访问开关（真实 HTTP）
srv = LanServer(lambda: app.store, lambda: "测试仓", "123456", port=0)
ok, _msg = srv.start()
chk("测试主机服务启动", ok and srv.running)
port = srv.httpd.server_address[1]


def http_get(path):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d%s" % (port, path), timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


srv.phone_access = False
code, body = http_get("/m")
chk("关闭手机访问 → /m 403", code == 403 and "手机访问" in body,
    "%s %s" % (code, body[:60]))
code, body = http_get("/m/api/whoami")
chk("关闭手机访问 → /m/api 403", code == 403, str(code))
code, body = http_get("/ping?code=123456")
chk("关闭手机访问不影响电脑 /ping", code == 200, str(code))

srv.phone_access = True
code, body = http_get("/m")
chk("开启手机访问 → /m 正常", code == 200, str(code))

srv.stop()

# ================================================== 3. 列标题改名
from wm.store import blank_record            # noqa: E402

rows = []
for i in range(5):
    r = blank_record()
    r.update({"code": "WL-%05d" % i, "brand": "B%d" % i, "category": "C",
              "model": "M%d" % i, "condition": "全新", "price": 1.0, "qty": 1,
              "shelf": "1排A-1", "listed": 0, "remark": "x"})
    rows.append(r)
app.store.insert_many(rows)
app.load_data()
root.update()
tree = app.tree
kids = tree.get_children()
chk("库存表有数据行", bool(kids))


def heading_text(col):
    return tree.heading(col, "text")


# 3a. 右键表头菜单包含改名项
class E:
    pass


e = E()
bbox = tree.bbox(kids[0], "brand")
chk("brand 列可见", bool(bbox))
e.x = tree.winfo_rootx() + bbox[0] + 10 - tree.winfo_rootx()
e.y = 8
e.x_root = tree.winfo_rootx() + bbox[0] + 10
e.y_root = tree.winfo_rooty() + 8
# 直接测内部逻辑：_heading_col_at + 菜单内容
col = app._heading_col_at(bbox[0] + 10)
chk("表头命中 brand 列", col == "brand", str(col))
app.settings["col_rename"] = True
m = None
# 用固定坐标弹出会被真实指针打断，改为直接验证菜单项构造逻辑：
titles = app.store.col_titles()
chk("初始无自定义标题", "brand" not in titles, str(titles))

# 3b. 对话框改名
app._rename_col_dialog("brand")
root.update()
dlgs = [w for w in root.winfo_children()
        if isinstance(w, tk.Toplevel) and w.title() == "修改列标题"]
chk("改名对话框打开", len(dlgs) == 1)
if dlgs:
    d = dlgs[0]
    ents = [w for w in d.winfo_children() if isinstance(w, tk.Entry)]
    chk("对话框有输入框(默认填当前标题)", len(ents) == 1
        and ents[0].get() == "品牌", ents[0].get() if ents else "")
    ents[0].delete(0, "end")
    ents[0].insert(0, "厂家")
    for w in d.winfo_children():
        if isinstance(w, ttk.Button) if False else False:
            pass
    # 找「保存」按钮
    import tkinter.ttk as ttk
    btn = None
    stack = [d]
    while stack:
        c = stack.pop()
        stack.extend(c.winfo_children())
        if isinstance(c, ttk.Button) and str(c.cget("text")) == "保存":
            btn = c
    chk("找到保存按钮", btn is not None)
    btn.invoke()
    root.update()
    chk("改名后 store 记录生效", app.store.col_titles().get("brand") == "厂家",
        str(app.store.col_titles()))
    chk("表头文字更新", "厂家" in heading_text("brand"), heading_text("brand"))

# 3c. 恢复默认
app._reset_col_title("brand")
root.update()
chk("恢复默认后无自定义", "brand" not in app.store.col_titles())
chk("恢复默认表头还原", heading_text("brand").startswith("品牌"),
    heading_text("brand"))

# 3d. 开关关闭 → 菜单不含改名项
app.settings["col_rename"] = False
titles = app.store.col_titles()
app.store.set_col_titles({"brand": "厂家"})
app._setup_columns()
root.update()
# 重新右键：菜单构造分支受开关控制 —— 直接断言菜单源码行为
from unittest import mock                    # noqa: E402
captured = {}


def fake_popup(self, x, y):
    ents = []
    for i in range(self.index("end") + 1):
        if self.type(i) == "separator":
            ents.append("---")
            continue
        try:
            ents.append(self.entrycget(i, "label"))
        except Exception:
            ents.append("?")
    captured["entries"] = ents
    return None


with mock.patch("tkinter.Menu.tk_popup", fake_popup):
    app._show_col_menu(10, 10, col="brand")
chk("开关关闭 → 表头菜单无改名项",
    not any("列标题" in s for s in captured.get("entries", [])),
    str(captured.get("entries")))
app.store.set_col_titles({"brand": ""})
app.settings["col_rename"] = True

# ================================================== 4. 设置页新分类/控件
app.open_appearance()
root.update(); root.update_idletasks(); root.update()
dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][0]
root.update()


def click_nav(text):
    stack = [dlg]
    while stack:
        cur = stack.pop()
        stack.extend(cur.winfo_children())
        if isinstance(cur, tk.Label) and str(cur.cget("text")).endswith("  " + text):
            cur.event_generate("<Button-1>", x=5, y=5)
            root.update(); root.update_idletasks(); root.update()
            return True
    return False


def all_widgets(win):
    out = []
    stack = [win]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(cur.winfo_children())
    return out


import tkinter.ttk as ttk                    # noqa: E402


def btn_texts(win):
    out = []
    for w in all_widgets(win):
        if isinstance(w, (ttk.Button, tk.Button, tk.Label)) and w.winfo_viewable():
            try:
                out.append(str(w.cget("text")))
            except Exception:
                pass
    return out


chk("侧栏切到「数据安全」", click_nav("数据安全"))
texts = btn_texts(dlg)
for need in ("自动备份", "数据文件夹", "备份频率", "打开数据文件夹",
             "打开备份文件夹", "保留最近"):
    chk("数据安全页含「%s」" % need, any(need in t for t in texts))

chk("侧栏切到「外观」", click_nav("外观"))
cb_col = [w for w in all_widgets(dlg)
          if isinstance(w, (tk.Checkbutton, ttk.Checkbutton))
          and "列标题" in str(w.cget("text")) and w.winfo_viewable()]
chk("外观页有列标题开关", len(cb_col) == 1)

# 局域网页手机访问开关
chk("侧栏切到「局域网共享」", click_nav("局域网共享"))
cb_ph = [w for w in all_widgets(dlg)
         if isinstance(w, (tk.Checkbutton, ttk.Checkbutton))
         and "允许手机访问" in str(w.cget("text")) and w.winfo_viewable()]
chk("局域网页有手机访问开关", len(cb_ph) == 1, str(len(cb_ph)))
# 开关联动：关掉 → lan_cfg 记录 + lan_status 反映
cb_ph[0].invoke()
root.update()
chk("关闭手机访问写入配置",
    app.lan_cfg.get("phone_access") is False
    and app.lan_status()["phone_access"] is False)
cb_ph[0].invoke()
root.update()
chk("重开手机访问写回", app.lan_cfg.get("phone_access") is True)

print("RESULT", "ALL PASS" if not fails else "FAIL: %s" % fails)
dlg.destroy()
root.destroy()
sys.exit(1 if fails else 0)
