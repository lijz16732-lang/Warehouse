# -*- coding: utf-8 -*-
"""验证（v1.11.0）：局域网主机 / 客户端模式。

A. 数据层（不开界面）：主机服务 + 客户端代理
   1. 正确连接码才能连；错码被拒
   2. 默认只读：读接口正常，写接口被拒（PermissionDenied）
   3. 主机授权后：写成功，数据落在主机那一个库里
   4. 版本号 rev 会随写操作变化（客户端据此自动刷新）
   5. 危险/主机本地操作（backup_to）不允许远程调用
   6. 停掉服务后客户端明确报「连不上主机」

B. 界面：两个独立实例（主机 + 客户端）
   7. 主机开启后窗口标题带「共享主机」
   8. 客户端连上后顶部出现状态条，默认橙色只读
   9. 主机授权后变绿色可录入
   10. 主机新增数据 → 客户端 rev 变化并自动刷新到新数据
   11. 断开后回到本机数据、状态条消失
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from wm.lan import LanServer  # noqa: E402
from wm.remote import (HostUnreachable, PermissionDenied, RemoteError,  # noqa: E402
                       RemoteStore)
from wm.store import Store, blank_record  # noqa: E402

FAILS = []
PORT = 18765
CODE = "135790"


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


print("== A. 数据层 ==")
TMP = tempfile.mkdtemp(prefix="wm_lan_")
st = Store(os.path.join(TMP, "data", "warehouse.db"))
st.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                  "model": "M-%d" % i, "qty": 5, "price": 100.0}
                for i in range(1, 4)])
rev0 = st.revision()
srv = LanServer(lambda: st, lambda: "测试仓", CODE, PORT)
ok, msg = srv.start()
check("主机服务启动", ok, msg)

cli = RemoteStore("127.0.0.1", PORT, CODE, "t-client", "测试电脑")
info = cli.ping()
check("客户端能连上并读取状态", info.get("ok") and info.get("warehouse") == "测试仓", info)
check("主机版本号传给客户端", int(info.get("rev") or 0) == rev0, info.get("rev"))
check("默认只读", info.get("can_write") is False, info.get("can_write"))
check("读接口正常：all_records 3 条", len(cli.all_records()) == 3)
check("读接口正常：revision 一致", cli.revision() == rev0, cli.revision())

bad = RemoteStore("127.0.0.1", PORT, "000000", "t-bad", "错码电脑")
try:
    bad.ping()
    check("错误连接码被拒绝", False)
except RemoteError as e:
    check("错误连接码被拒绝", "连接码" in str(e), str(e))

try:
    cli.add_manual_sale(code="WL-X", brand="ABB", qty=1, price=50)
    check("未授权时写入被拒绝", False)
except PermissionDenied as e:
    check("未授权时写入被拒绝", "未授权" in str(e), str(e))

check("被拒后主机数据没变", len(st.list_sales()) == 0)

try:
    cli.backup_to(os.path.join(TMP, "x.db"))
    check("backup_to 不允许远程调用", False)
except RemoteError as e:
    check("backup_to 不允许远程调用", "主机上执行" in str(e), str(e))

# 主机授权（客户端 IP 是 127.0.0.1）
srv.allow("127.0.0.1", True)
info2 = cli.ping()
check("授权后可录入", info2.get("can_write") is True, info2.get("can_write"))
rev_before_write = cli.revision()
okw, msgw = cli.add_manual_sale(code="WL-0001", brand="ABB", model="M-1",
                                qty=2, price=150, buyer="张三")
check("授权后写入成功", okw, msgw)
check("数据落在主机库", len(st.list_sales()) == 1, len(st.list_sales()))
check("写入后 rev 增加", cli.revision() > rev_before_write,
      "%s -> %s" % (rev_before_write, cli.revision()))
check("客户端读到新记录", any(r["buyer"] == "张三" for r in cli.list_sales()))

srv.allow("127.0.0.1", False)
try:
    cli.add_manual_sale(code="WL-X2", brand="ABB", qty=1, price=1)
    check("收回授权后写入再次被拒", False)
except PermissionDenied:
    check("收回授权后写入再次被拒", True)

srv.stop()
dead = RemoteStore("127.0.0.1", PORT, CODE, "t-client", "测试电脑", timeout=2)
try:
    dead.ping()
    check("主机停止后明确报连不上", False)
except HostUnreachable as e:
    check("主机停止后明确报连不上", "连不上主机" in str(e), str(e))

print("== B. 界面：主机 + 客户端两个实例 ==")
import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402

# 测试里不弹窗：把 messagebox 全换成静默实现
wapp.messagebox.showwarning = lambda *a, **k: None
wapp.messagebox.showinfo = lambda *a, **k: None
wapp.messagebox.showerror = lambda *a, **k: None

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

TMP1 = tempfile.mkdtemp(prefix="wm_host_")
wapp.app_dir = lambda: TMP1
Store(os.path.join(TMP1, "data", "warehouse.db")).close()
root1 = tk.Tk()
host = wapp.App(root1)
host.store.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                          "model": "H-%d" % i, "qty": 9,
                                          "price": 88.0} for i in range(1, 6)])
host.load_data()
root1.geometry("1200x760+40+40")
root1.update()

ok, msg = host.start_lan_host(18766, "246810")
check("主机界面开启共享", ok and host.lan_mode == "host", msg)
check("主机标题带「共享主机」", "共享主机" in root1.title(), root1.title())

TMP2 = tempfile.mkdtemp(prefix="wm_client_")
wapp.app_dir = lambda: TMP2
Store(os.path.join(TMP2, "data", "warehouse.db")).close()
root2 = tk.Tk()
client = wapp.App(root2)
root2.geometry("1200x760+80+80")
root2.update()

ok, msg = client.connect_lan("127.0.0.1", 18766, "246810")
check("客户端连上主机", ok, msg)
check("客户端读到的就是主机数据", len(client.records) == 5,
      "%d vs %d" % (len(client.records), len(host.records)))
check("客户端窗口标题带「客户端」", "客户端" in root2.title(), root2.title())
bar_shown = bool(getattr(getattr(client, "lan_bar", None), "_shown", False))
check("客户端顶部出现状态条", bar_shown)
check("默认只读（can_write=False）", client.can_write is False)
check("状态条是只读文案", "只读" in client.lan_lbl.cget("text"),
      client.lan_lbl.cget("text"))
check("只读时拦截写入", client._guard_write() is True)

client_before = len(client.records)
host.store.insert_many([blank_record() | {"code": "WL-90001", "brand": "新增",
                                          "model": "NEW-1", "qty": 1, "price": 1.0}])
host.load_data()
info = client.store.ping()
client._on_lan_info(info)
root2.update()
check("主机新增后客户端自动刷新", len(client.records) == client_before + 1,
      "%d -> %d" % (client_before, len(client.records)))

host.set_lan_allow("127.0.0.1", True)
client.store.ping()
client._on_lan_info(client.store.ping())
root2.update()
check("主机授权后客户端变可录入", client.can_write is True)
check("状态条转绿（文案含可录入）", "可录入" in client.lan_lbl.cget("text"),
      client.lan_lbl.cget("text"))
ok, msg = client.store.add_manual_sale(code="WL-77777", brand="客户端录入",
                                       qty=1, price=20.0)
check("授权后客户端可写入", ok, msg)
check("主机能看到客户端写入的记录",
      any(r.get("brand") == "客户端录入" for r in host.store.list_sales()))

root1.update()
screenshot.capture_window("局域网共享", os.path.join(OUT, "lan_dialog.png")) \
    if False else None

ok, msg = client.disconnect_lan()
root2.update()
check("客户端断开回到本机", ok and client.lan_mode == "off", msg)
check("断开后状态条消失",
      not bool(getattr(getattr(client, "lan_bar", None), "_shown", False)))
check("断开后读的是本机库（0 条）", len(client.records) == 0, len(client.records))

host.stop_lan_host()
root1.destroy()
root2.destroy()
print("\n失败项：%s" % (FAILS or "无"))
sys.exit(1 if FAILS else 0)
