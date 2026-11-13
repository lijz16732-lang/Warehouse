# -*- coding: utf-8 -*-
"""v1.39 探针：① 主机改客户端名（覆盖上报名、持久化）② 按设备汇总销售统计。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk

from wm import app as wapp
from wm.store import Store

PASS, FAIL = [], []


def chk(name, ok, extra=None):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name +
          ("  %r" % (extra,) if extra is not None and not ok else ""))


TMP = tempfile.mkdtemp(prefix="probe139_")
wapp.resolve_data_dir = lambda: TMP
DB = os.path.join(TMP, "warehouse.db")

root = tk.Tk()
app = wapp.App(root)
root.update()

# ---------- ① 销售数据：三个来源 ----------
r1 = app.store.all_records()[0] if app.store.all_records() else None
if r1 is None:
    app.store.insert_many([{"code": "WL-00001", "model": "M1", "qty": 10,
                     "price": 100}])
    r1 = app.store.all_records()[0]
app.store.add_purchase(r1["id"], 10, 50)          # 给点成本
with app.store.as_source("主机"):
    ok, msg = app.store.add_sale(r1["id"], 2, 120)
    chk("主机卖出", ok, msg)
with app.store.as_source("电脑·仓库A的电脑"):
    ok, msg = app.store.add_sale(r1["id"], 3, 130)
    chk("客户端A卖出", ok, msg)
with app.store.as_source("手机(192.168.1.9)"):
    ok, msg = app.store.add_manual_sale(code="MANUAL-1", qty=1, price=200, cost=100)
    chk("手机补录卖出", ok, msg)

data = app.store.sales_stats_by_src(0)
srcs = {r["src"]: r for r in data["rows"]}
chk("三个来源都在", set(srcs) == {"主机", "电脑·仓库A的电脑", "手机(192.168.1.9)"},
    list(srcs))
chk("主机行：1 笔 240 元", srcs.get("主机", {}).get("amount") == 240.0
    and srcs["主机"]["count"] == 1, srcs.get("主机"))
chk("客户端A行：390 元", srcs.get("电脑·仓库A的电脑", {}).get("amount") == 390.0)
t = data["total"]
chk("总计 3 笔 6 件 830 元", t["count"] == 3 and t["qty"] == 6
    and t["amount"] == 830.0, t)
chk("总计毛利 = 830 - 成本", t["profit"] == round(830.0 - t["cost"], 2), t)
chk("按销售额降序", [r["src"] for r in data["rows"]] ==
    ["电脑·仓库A的电脑", "主机", "手机(192.168.1.9)"],
    [r["src"] for r in data["rows"]])

d1 = app.store.sales_stats_by_src(1)
chk("近1天过滤不炸", isinstance(d1.get("rows"), list))

# ---------- ② 主机改客户端名 ----------
ok, msg = app.start_lan_host(port=18765)
chk("主机启动", ok, msg)
srv = app.lan_server
srv._touch("192.168.1.10", "DESKTOP-A1", "id-a")
srv._touch("192.168.1.11", "B-PC", "id-b")

ok, msg = app.lan_rename_client("192.168.1.10", "张三的电脑")
chk("改名成功", ok, msg)
names = {c["ip"]: c["name"] for c in srv.snapshot()}
chk("列表显示新名", names.get("192.168.1.10") == "张三的电脑", names)
# 客户端继续上报自己的电脑名 → 被覆盖
srv._touch("192.168.1.10", "DESKTOP-A1", "id-a")
names = {c["ip"]: c["name"] for c in srv.snapshot()}
chk("客户端上报名被覆盖", names.get("192.168.1.10") == "张三的电脑", names)
# 未改名的照常显示上报名
names = {c["ip"]: c["name"] for c in srv.snapshot()}
chk("未改名机器用上报名", names.get("192.168.1.11") == "B-PC", names)
# 改名已持久化到 lan_cfg
saved = app.lan_cfg.get("name_overrides") or {}
chk("改名已存配置", saved.get("192.168.1.10") == "张三的电脑", saved)

# 重启主机服务 → 覆盖名仍在
app.stop_lan_host()
root.update()
ok, msg = app.start_lan_host(port=18765)
chk("主机重启", ok, msg)
srv = app.lan_server
chk("重启后覆盖名还在", srv.name_overrides.get("192.168.1.10") == "张三的电脑",
    srv.name_overrides)
srv._touch("192.168.1.10", "DESKTOP-A1", "id-a")
names = {c["ip"]: c["name"] for c in srv.snapshot()}
chk("重启后新连接仍显示新名", names.get("192.168.1.10") == "张三的电脑", names)

# 空名/不存在 ip
ok, _ = app.lan_rename_client("192.168.1.10", "   ")
chk("空名被拒", not ok)
ok, _ = app.lan_rename_client("10.9.9.9", "X")
chk("未连接的 ip 被拒", not ok)

# ---------- ③ UI：面板按钮与统计弹窗 ----------
app.open_appearance("lan")
root.update()
win = app._settings_win


def walk(w, out_l):
    out_l.append(w)
    for c in w.winfo_children():
        walk(c, out_l)


ws = []
walk(win, ws)
panel = None
for w in ws:
    if w.winfo_class() == "Frame" and hasattr(w, "btn_sales"):
        panel = w
        break
chk("LanPanel 已嵌入", panel is not None)
chk("改名按钮存在", hasattr(panel, "btn_rename"))
chk("统计按钮存在", hasattr(panel, "btn_sales"))
root.update()
chk("统计按钮已点亮（主机模式）",
    str(panel.btn_sales.cget("state")) == "normal")

panel.show_sales_stats()
root.update()
dlg = None
for w in ws:
    pass
# 重新全树收集（Toplevel 可能嵌套在 panel 路径下）
tops = []
walk(root, tops)
dlgs = [w for w in tops if isinstance(w, tk.Toplevel)
        and "销售统计" in w.title()]
chk("统计弹窗打开", bool(dlgs))
if dlgs:
    import screenshot
    win.title("W M 139 探针")
    root.update()
    dlgs[0].title("W M 139 统计")
    root.update()
    screenshot.capture_window("W M 139 统计",
                              os.path.join(ROOT, ".tmpdbg", "stats139.png"))
    ws2 = []
    walk(dlgs[0], ws2)
    tvs = [w for w in ws2 if w.winfo_class() == "Treeview"]
    lbls = [w for w in ws2 if w.winfo_class() == "Label"]
    tv = tvs[0] if tvs else None
    if tv is not None:
        vals = [tv.item(i, "values") for i in tv.get_children()]
        srcs_ui = [v[0] for v in vals]
        chk("弹窗列出 3 个来源", set(srcs_ui) == {"主机", "电脑·仓库A的电脑",
                                                "手机(192.168.1.9)"}, srcs_ui)
        tot = [v for v in vals if v[0] == "手机(192.168.1.9)"]
        chk("手机行金额 200.00", tot and tot[0][3] == "200.00", tot)
    txts = [str(w.cget("text")) for w in lbls]
    chk("合计行显示 830 元", any("830.00" in t for t in txts), txts[-3:])
    dlgs[0].destroy()
    root.update()

app.stop_lan_host()
root.update()
root.destroy()
print("\n==== PASS %d / FAIL %d ====" % (len(PASS), len(FAIL)))
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
