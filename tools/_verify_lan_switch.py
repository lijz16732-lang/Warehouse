# -*- coding: utf-8 -*-
"""验证（v1.11.2）：客户端下禁止开启共享（按钮置灰），主机→客户端仍需确认。

1. 客户端状态下「① 本机作为主机」区：开启共享按钮置灰，端口/连接码相关按钮置灰
2. 客户端状态下 ① 区提示引导「先断开 / 回到本机」
3. 客户端状态调用 toggle_host：不启动主机、不弹任何确认（防误点双保险）
4. 「断开 / 回到本机」后按钮恢复可点，可正常开启共享
5. 主机状态点「连接」→ 先弹确认；选「否」角色不变（仍在共享）
6. 选「是」→ 切成客户端
7. 「当前角色」标签会跟着角色在 ① / ② 之间移动
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.lanui import LanDialog  # noqa: E402
from wm.constants import CLR_WARN  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


wapp.messagebox.showwarning = lambda *a, **k: None
wapp.messagebox.showinfo = lambda *a, **k: None
wapp.messagebox.showerror = lambda *a, **k: None
asked = {"n": 0, "text": "", "answer": False}
wapp.messagebox.askyesno = lambda title, msg="", **k: (
    asked.update(n=asked["n"] + 1, text=msg) or asked["answer"])

# ---- 主机实例
TMP1 = tempfile.mkdtemp(prefix="wm_h3_")
wapp.app_dir = lambda: TMP1
Store(os.path.join(TMP1, "data", "warehouse.db")).close()
root1 = tk.Tk()
host = wapp.App(root1)
host.store.insert_many([blank_record() | {"code": "WL-%05d" % i, "brand": "ABB",
                                          "qty": 5, "price": 88.0}
                        for i in range(1, 4)])
host.load_data()
root1.update()
ok, msg = host.start_lan_host(18976, "246810")
check("测试用主机开启共享", ok, msg)

# ---- 客户端实例（本地库 0 条，便于区分「本机数据」和「主机数据」）
TMP2 = tempfile.mkdtemp(prefix="wm_c3_")
wapp.app_dir = lambda: TMP2
Store(os.path.join(TMP2, "data", "warehouse.db")).close()
root2 = tk.Tk()
client = wapp.App(root2)
root2.geometry("1200x760+60+60")
root2.update()
ok, msg = client.connect_lan("127.0.0.1", 18976, "246810")
check("客户端连上主机", ok and client.lan_mode == "client", msg)
check("客户端看到主机 3 条", len(client.records) == 3, len(client.records))

dlg = LanDialog(root2, client)
root2.update()

print("\n== 1. 客户端状态下 ① 区按钮全部置灰 ==")
check("①「开启共享」按钮置灰",
      str(dlg.btn_host.cget("state")) == "disabled", dlg.btn_host.cget("state"))
check("「新连接的电脑直接允许录入」置灰",
      str(dlg.cb_allow.cget("state")) == "disabled", dlg.cb_allow.cget("state"))
check("「复制地址」置灰",
      str(dlg.btn_copy.cget("state")) == "disabled", dlg.btn_copy.cget("state"))
check("「换一个」置灰",
      str(dlg.btn_newcode.cget("state")) == "disabled", dlg.btn_newcode.cget("state"))
check("②「连接」按钮仍可用",
      str(dlg.btn_conn.cget("state")) == "normal", dlg.btn_conn.cget("state"))

print("\n== 2. 客户端状态下 ① 区提示 ==")
check("提示引导「先断开 / 回到本机」",
      "断开 / 回到本机" in dlg.lbl_host_msg.cget("text"),
      dlg.lbl_host_msg.cget("text"))
check("提示是警示色（CLR_WARN）", dlg.lbl_host_msg.cget("fg") == CLR_WARN,
      dlg.lbl_host_msg.cget("fg"))

print("\n== 3. 客户端状态调用 toggle_host：防误点双保险 ==")
asked.update(n=0, answer=True)
dlg.var_port.set("18977")
dlg.var_code.set("135790")
dlg.toggle_host()
root2.update()
check("不启动主机服务", client.lan_status()["running"] is False)
check("仍是客户端、仍看到主机数据",
      client.lan_mode == "client" and len(client.records) == 3)
check("没有弹任何确认框（按钮置灰是唯一入口）", asked["n"] == 0, asked["n"])
check("② 区提示写明拒绝原因",
      "断开 / 回到本机" in dlg.lbl_cli_msg.cget("text"),
      dlg.lbl_cli_msg.cget("text"))

print("\n== 4. 「当前角色」标签在 ② 上 ==")
check("② 显示「当前角色」",
      dlg.cli_badge.cget("text") == "当前角色" and bool(dlg.cli_badge.winfo_ismapped()),
      dlg.cli_badge.cget("text"))
check("① 标签隐藏", not bool(dlg.host_badge.winfo_ismapped()))

print("\n== 5. 断开后按钮恢复，可正常当主机 ==")
asked.update(n=0)
ok, msg = client.disconnect_lan()
root2.update()
check("断开成功", ok and client.lan_mode == "off", msg)
check("断开后「开启共享」恢复可点",
      str(dlg.btn_host.cget("state")) == "normal", dlg.btn_host.cget("state"))
dlg.toggle_host()
root2.update()
check("可正常开启共享（本机主机）",
      client.lan_mode == "host" and client.lan_status()["running"] is True)
check("① 显示「当前角色」标签",
      dlg.host_badge.cget("text") == "当前角色"
      and not bool(dlg.cli_badge.winfo_ismapped()))

print("\n== 6. 主机状态点「连接」→ 取消 ==")
dlg.var_host.set("127.0.0.1")
dlg.var_cport.set("18976")
dlg.var_ccode.set("246810")
asked.update(n=0, answer=False)
dlg.connect()
root2.update()
check("弹出确认框", asked["n"] == 1, asked["n"])
check("确认文案说明会停掉本机共享",
      "停止本机共享" in asked["text"], asked["text"][:60])
check("选「否」后仍是主机", client.lan_mode == "host" and
      client.lan_status()["running"] is True)

print("\n== 7. 主机状态点「连接」→ 确定（连接走后台探测+进度条） ==")
asked.update(n=0, answer=True)
dlg.connect()
root2.update()
check("点连接立刻返回（不卡界面）且进度条出现",
      asked["n"] == 1 and str(dlg.pb.winfo_manager()) == "pack",
      "%d / %s" % (asked["n"], dlg.pb.winfo_manager()))
for _ in range(250):                 # 最多等 5 秒让后台探测完成
    if client.lan_mode == "client":
        break
    root2.update()
    time.sleep(0.02)
root2.update()
check("确认后切回客户端", client.lan_mode == "client", client.lan_mode)
check("本机共享已停止", client.lan_status()["running"] is False)
check("重新读到主机 3 条", len(client.records) == 3, len(client.records))
check("进度条已收起", not bool(dlg.pb.winfo_ismapped()),
      dlg.pb.winfo_manager())
check("按钮恢复可点",
      str(dlg.btn_conn.cget("state")) == "normal", dlg.btn_conn.cget("state"))
check("角色标签回到 ②",
      dlg.cli_badge.cget("text") == "当前角色"
      and not bool(dlg.host_badge.winfo_ismapped()))

client.disconnect_lan()
client.stop_lan_host()
host.stop_lan_host()
root1.destroy()
root2.destroy()
print("\n失败项：%s" % (FAILS or "无"))
sys.exit(1 if FAILS else 0)
