# -*- coding: utf-8 -*-
"""打包产物验收：把 exe 复制到干净临时目录启动，确认窗口出现、库自动初始化。

不碰 dist/data（那是历史库），全程在一个 python 进程内完成，
避免子进程随调用会话被回收。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from screenshot import capture_window  # noqa: E402

EXE = os.path.join(ROOT, "dist", "仓管家-仓库管理系统.exe")
OUT = os.path.join(ROOT, ".tmpdbg", "exe_start.png")

ok = True


def chk(name, cond, detail=""):
    global ok
    if not cond:
        ok = False
    print("%s %s %s" % ("[OK] " if cond else "[FAIL]", name, detail))


tmp = tempfile.mkdtemp(prefix="cgm_exe_")
dst = os.path.join(tmp, os.path.basename(EXE))
shutil.copy2(EXE, dst)
chk("exe 复制到干净目录", os.path.isfile(dst),
    "%.1f MB" % (os.path.getsize(dst) / 1024.0 / 1024.0))
chk("干净目录无 data", not os.path.exists(os.path.join(tmp, "data")))

p = subprocess.Popen([dst], cwd=tmp)
t0 = time.time()
shot = None
err = None
try:
    shot = capture_window("仓管家", OUT)
except Exception as e:          # 窗口没出来
    err = e
elapsed = time.time() - t0

alive = p.poll() is None
chk("进程存活", alive, "pid=%s exit=%s" % (p.pid, p.poll()))
chk("主窗口出现", shot is not None, err or "%.1f s" % elapsed)
db = os.path.join(tmp, "data", "warehouse.db")
chk("首次启动自动建库", os.path.isfile(db),
    "%.0f KB" % (os.path.getsize(db) / 1024.0) if os.path.isfile(db) else "缺失")

try:
    p.terminate()
    p.wait(timeout=6)
except Exception:
    p.kill()
chk("进程可正常退出", p.poll() is not None)

shutil.rmtree(tmp, ignore_errors=True)
print("截图:", OUT if shot else "无")
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
