# -*- coding: utf-8 -*-
"""端到端验证单实例保护：进程1启动(隐藏到托盘) → 进程2启动应被拦截并唤醒进程1。"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(HERE, ".venv310", "Scripts", "python.exe")

# ---------- 进程 1：实例 A，带托盘，窗口隐藏模拟「最小化到托盘」 ----------
inst_a = os.path.join(tempfile.mkdtemp(prefix="si_a_"), "inst_a.py")
with open(inst_a, "w", encoding="utf-8") as f:
    f.write('''
# -*- coding: utf-8 -*-
import os, sys, tempfile, time
ROOT = r"{root}"
sys.path.insert(0, ROOT)
import tkinter as tk
from wm.single import first_instance
assert first_instance(), "进程A 应是第一个实例"
from wm import app as wapp
from wm.store import Store
TMP = tempfile.mkdtemp(prefix="siadata_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
root = tk.Tk()
app = wapp.App(root)
app.settings["min_to_tray"] = True
app._ensure_tray()
print("TRAY_OK" if app.tray and app.tray.ok else "TRAY_FAIL", flush=True)
root.withdraw()                       # 模拟已隐藏到托盘
state_seen = []
deadline = time.time() + 15
while time.time() < deadline:
    root.update()
    if root.state() == "normal":
        state_seen.append(time.time())
        break
    time.sleep(0.05)
print("RESTORED" if state_seen else "NOT_RESTORED", flush=True)
root.destroy()
'''.format(root=HERE))

p1 = subprocess.Popen([PY, "-u", inst_a], stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT, cwd=HERE)
ok_line = p1.stdout.readline().decode("utf-8", "ignore").strip()
print("实例A:", ok_line)
assert "TRAY_OK" in ok_line, "实例A 托盘没起来"
time.sleep(1.0)                       # 等托盘窗口消息循环就绪

# ---------- 进程 2：重复启动应被拦截 ----------
inst_b = os.path.join(tempfile.mkdtemp(prefix="si_b_"), "inst_b.py")
with open(inst_b, "w", encoding="utf-8") as f:
    f.write('''
import sys
sys.path.insert(0, r"{root}")
from wm.single import first_instance
print("ALLOWED" if first_instance() else "BLOCKED", flush=True)
'''.format(root=HERE))
r2 = subprocess.run([PY, "-u", inst_b], capture_output=True, cwd=HERE,
                    timeout=30, text=True)
print("实例B:", r2.stdout.strip(), r2.stderr.strip()[:200])
chk_b = "BLOCKED" in r2.stdout

# 进程A 应收到激活消息并恢复窗口
line_a = p1.stdout.readline().decode("utf-8", "ignore").strip()
print("实例A 恢复:", line_a)
if "RESTORED" not in line_a:
    try:
        rest = p1.stdout.read().decode("utf-8", "ignore")
        print("A 其余输出:", rest[:800])
    except Exception:
        pass
chk_a = "RESTORED" in line_a
p1.wait(timeout=30)

# ---------- 进程 3：A 退出后再启动应放行 ----------
r3 = subprocess.run([PY, "-u", inst_b], capture_output=True, cwd=HERE,
                    timeout=30, text=True)
print("实例C(无运行实例):", r3.stdout.strip())
chk_c = "ALLOWED" in r3.stdout

PASS = chk_b and chk_a and chk_c
print("\n==== %s ====" % ("ALL PASS" if PASS else "FAIL"))
sys.exit(0 if PASS else 1)
