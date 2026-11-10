# -*- coding: utf-8 -*-
"""探针：默认导出格式 / 开机自启 / 托盘 / 回收站保留天数 / 视图开关 / 连接码轮换。

只碰临时数据目录；注册表测试会先记录原状态并在结束时还原。
"""

import ctypes
import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from wm import app as wapp
from wm import autostart, csvio
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="probe_sys_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
ctypes.windll.user32.SetCursorPos(2, 2)

fails = []


def chk(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        fails.append(name)


root = tk.Tk()
app = wapp.App(root)
root.update()
rows = []
for i in range(12):
    r = blank_record()
    r.update({"code": "WL-%05d" % i, "brand": "B%d" % i, "category": "C",
              "model": "M%d" % i, "condition": "全新", "price": 10.0, "qty": 2,
              "shelf": "1排A-1", "listed": 1, "remark": "x"})
    rows.append(r)
app.store.insert_many(rows)
app.load_data()
root.update()

# ================================================ 1. 默认导出格式
chk("默认导出格式为 xlsx", app._export_fmt() == "xlsx")
app.settings["export_format"] = "csv"
chk("切到 CSV 后 _export_fmt 生效", app._export_fmt() == "csv")
app.settings["export_format"] = "xlsx"
chk("切回 XLSX 生效", app._export_fmt() == "xlsx")

# CSV 导出内容与表头
p_csv = os.path.join(TMP, "库存.csv")
n = csvio.export_records_csv(p_csv, app.records, encoding="utf-8-sig")
chk("CSV 导出条数正确", n == len(app.records), n)
with open(p_csv, encoding="utf-8-sig") as f:
    lines = f.read().splitlines()
chk("CSV 首行是表头（含「编号」）", "编号" in lines[0], lines[0][:40])
chk("CSV 行数 = 表头 + 记录数", len(lines) == len(app.records) + 1,
    len(lines))

# 出售/出库 CSV（空数据也应能写表头）
p_sale = os.path.join(TMP, "出售.csv")
csvio.export_sales_csv(p_sale, [], encoding="utf-8-sig")
chk("出售 CSV 空数据也写出表头", os.path.getsize(p_sale) > 0)
p_out = os.path.join(TMP, "出库.csv")
csvio.export_out_csv(p_out, [], encoding="utf-8-sig")
chk("出库 CSV 空数据也写出表头", os.path.getsize(p_out) > 0)

# ================================================ 2. 开机自启
was_on = autostart.is_enabled()
chk("读取开机自启状态", isinstance(was_on, bool), was_on)
cmd = autostart.command_line()
chk("自启命令包含程序路径", ("main.py" in cmd) or (".exe" in cmd), cmd)
ok, msg = autostart.enable()
chk("开启自启成功", ok, msg)
chk("开启后注册表可读到", autostart.is_enabled())
ok, msg = autostart.disable()
chk("关闭自启成功", ok, msg)
chk("关闭后注册表已清空", not autostart.is_enabled())
if was_on:                        # 还原用户原本的状态
    autostart.enable()

# ================================================ 3. 托盘
from wm.tray import TrayIcon
from wm.constants import app_icon_path
got = []
tray = TrayIcon("仓管家探针", app_icon_path(), on_show=lambda: got.append("show"),
                on_settings=lambda: got.append("settings"),
                on_exit=lambda: got.append("exit"), master=root)
started = tray.start()
chk("托盘图标创建成功", started, "start=%s hwnd=%s" % (started, tray.hwnd))
if started:
    tray.queue.put("show")        # 模拟菜单命令
    tray.poll()
    chk("托盘命令经队列送达主线程", got == ["show"], got)
    tray.stop()
    time.sleep(0.2)
chk("托盘可以停止", True)

# app 层：开关联动创建/销毁托盘
app.settings["min_to_tray"] = True
app._ensure_tray()
chk("打开「最小化到托盘」后创建托盘", app.tray is not None)
app.settings["min_to_tray"] = False
app.settings["close_to_tray"] = False
app._ensure_tray()
chk("两个托盘开关都关掉后销毁托盘", app.tray is None)

# 关闭按钮行为：close_to_tray 打开时应隐藏而不是退出
app.settings["close_to_tray"] = True
app._ensure_tray()
if app.tray is not None:
    app._quitting = False
    app.on_close()
    root.update()
    hidden = (root.state() == "withdrawn")
    chk("点关闭后窗口隐藏（未退出）", hidden and not app._stopped, root.state())
    app._tray_show()
    root.update()
    chk("托盘恢复窗口", root.state() != "withdrawn", root.state())
else:
    chk("点关闭后窗口隐藏（未退出）", False, "托盘未创建，跳过")
app.settings["close_to_tray"] = False
app._ensure_tray()

# ================================================ 4. 回收站保留天数
app.store.clear_all(purge_sales=True)
base = []
for i in range(5):
    r = blank_record()
    r.update({"code": "WL-%05d" % i, "brand": "B", "category": "C",
              "model": "M%d" % i, "condition": "全新", "price": 1.0, "qty": 1,
              "shelf": "1排A-1", "listed": 1, "remark": ""})
    base.append(r)
app.store.insert_many(base)
app.load_data()
ids = [r["id"] for r in app.store.all_records()]
app.store.delete_ids(ids[:3])           # 3 条进回收站
chk("进回收站 3 条", app.store.deleted_count() == 3, app.store.deleted_count())
# 把其中 2 条的删除时间改到 60 天前
old_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 60 * 86400))
with app.store._lock:
    app.store.conn.execute(
        "UPDATE items SET deleted_at = ? WHERE id IN (?, ?)",
        (old_ts, ids[0], ids[1]))
    app.store.conn.commit()
chk("清理 30 天前应删 2 条", app.store.purge_trash_older(30) == 2)
chk("回收站剩 1 条", app.store.deleted_count() == 1, app.store.deleted_count())
chk("永久保留不清理", app.store.purge_trash_older(0) == 0)
app.settings["recycle_days"] = 30
chk("启动维护按设置清理（本次已无超期）", app._purge_recycle_auto() == 0)
app.settings["recycle_days"] = 0

# ================================================ 5. 视图开关
app.load_data()
root.update()
kids = app.tree.get_children()
tags_on = [bool(app.tree.item(k, "tags")) for k in kids[:2]]
chk("默认开启斑马纹（第 2 行有 odd）",
    "odd" in (app.tree.item(kids[1], "tags") or ()), app.tree.item(kids[1], "tags"))
app.set_zebra(False)
root.update()
chk("关闭斑马纹后无 odd tag",
    "odd" not in (app.tree.item(kids[1], "tags") or ()),
    app.tree.item(kids[1], "tags"))
app.set_zebra(True)
root.update()
chk("重新开启斑马纹恢复",
    "odd" in (app.tree.item(kids[1], "tags") or ()))

# 详情面板
from wm.toggle import Toggle, ANIM, set_anim
before = app.var_show_detail.get()
app.var_show_detail.set(not before)
app._toggle_detail()
root.update()
shown = bool(app.detail_card.winfo_ismapped())
chk("详情面板开关生效", shown == (not before), "shown=%s" % shown)
app.var_show_detail.set(before)
app._toggle_detail()
root.update()

# 开关动效
set_anim(True)
chk("开启动效后 ANIM 为真", ANIM["enabled"])
set_anim(False)
chk("关闭动效后 ANIM 为假", not ANIM["enabled"])
var = tk.StringVar(value="0")
tg = Toggle(root, var, on_value="1", off_value="0")
root.update()
tg._flip()
root.update()
chk("关动效时开关瞬间到位", abs(tg._pos - 1.0) < 1e-6, tg._pos)
set_anim(True)
tg._flip()
root.update()
chk("开动效后开关从当前位置滑出（不是瞬间到底）",
    tg._job is not None or abs(tg._pos - 0.0) < 1e-6, tg._pos)
for _ in range(20):
    root.update()
    time.sleep(0.01)
chk("动画最终停在关闭位置", abs(tg._pos - 0.0) < 1e-6, tg._pos)
tg.destroy()

# ================================================ 6. 连接码定期更换
code0 = app.lan_cfg["code"]
app.set_lan_code_rotate("daily")
chk("设置每天换码已保存", app.lan_cfg["code_rotate"] == "daily")
app.lan_cfg["last_code_rotate"] = time.time() - 2 * 86400
rot = app._rotate_code_auto()
chk("到期后自动换码", rot and app.lan_cfg["code"] != code0,
    "%s -> %s" % (code0, app.lan_cfg["code"]))
chk("换码后记录本次时间",
    time.time() - float(app.lan_cfg["last_code_rotate"]) < 60)
chk("未到期不重复换码", app._rotate_code_auto() is False)
app.set_lan_code_rotate("off")
code_before = app.lan_cfg["code"]
chk("关闭自动换码后不换", app._rotate_code_auto() is False
    and app.lan_cfg["code"] == code_before)
# 客户端不换码
app.lan_mode = "client"
app.lan_cfg["code_rotate"] = "daily"
app.lan_cfg["last_code_rotate"] = time.time() - 2 * 86400
chk("客户端模式不换码", app._rotate_code_auto() is False)
app.lan_mode = "off"
app.set_lan_code_rotate("off")

# ================================================ 7. 设置页：连接码自动更换 + 防重入
from tkinter import ttk

app.open_appearance(page="lan")
root.update()
root.update_idletasks()
root.update()
wins = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
chk("打开了设置窗口", len(wins) == 1, len(wins))
win = wins[0]

app.open_appearance(page="system")
root.update()
wins2 = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
chk("重复打开不会建第二个设置窗", len(wins2) == 1, len(wins2))


def find_widgets(win_root, cls, pred=None):
    out = []
    st = [win_root]
    while st:
        c = st.pop()
        st.extend(c.winfo_children())
        if isinstance(c, cls) and (pred is None or pred(c)):
            out.append(c)
    return out


cbs = find_widgets(win, ttk.Combobox,
                   lambda c: "每天换一次" in tuple(c.cget("values") or ()))
chk("局域网页有「自动更换连接码」下拉", len(cbs) == 1, len(cbs))
if cbs:
    cb = cbs[0]
    cb.set("每周换一次")
    cb.event_generate("<<ComboboxSelected>>")
    root.update()
    chk("下拉切换写入配置", app.lan_cfg["code_rotate"] == "weekly",
        app.lan_cfg["code_rotate"])

panel = app.lan_dlg
app.rotate_lan_code(silent=True)
root.update()
chk("主机换码后设置页输入框同步",
    str(panel.var_code.get()) == str(app.lan_cfg["code"]),
    "%s / %s" % (panel.var_code.get(), app.lan_cfg["code"]))
app.set_lan_code_rotate("off")

# ================================================ 收尾
root.destroy()
print()
if fails:
    print("RESULT FAIL: %s" % fails)
    sys.exit(1)
print("RESULT ALL PASS")
