# -*- coding: utf-8 -*-
"""v1.47.1 窗口 resize 节流探针。

验证：
1. 连续尺寸变化（模拟最大化/还原）时覆盖层不逐帧重绘（redraw 次数远小于
   Configure 事件数），消除卡顿；
2. 尺寸稳定后贴片正确恢复（网格线/徽章/复选框数量与位置）；
3. 上色贴片随重排同步（_on_overlay_resized 被调用）；
4. debounce 定时器正确取消，无重复 pending。
"""
import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk
import wm.app as wapp
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="wm_resizeperf_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP

st = Store(os.path.join(TMP, "warehouse.db"))
for i in range(1, 31):
    r = blank_record()
    r.update({"lid": i, "code": "WL-%05d" % i, "brand": "AB",
              "category": "继电器", "model": "193-EC%d" % i, "qty": 9,
              "price": 12.5, "listed": 1 if i % 2 else 0,
              "shelf": "1排A-%d" % i})
    st.insert(r)
st.close()

try:
    ctypes.windll.user32.SetCursorPos(2, 2)
except Exception:
    pass

ok = [0, 0]


def check(label, cond):
    ok[0] += 1
    ok[1] += bool(cond)
    print("  %-40s %s" % (label, "OK" if cond else "FAIL"))


root = tk.Tk()
root.geometry("1500x860+40+40")
app = wapp.App(root)
app.nb.select(app.tab_inv)
app.load_data()
root.update_idletasks(); root.update()

tree, decor = app.tree, app.decor
try:
    decor._resize_job = None
    decor._resize_pending = False
except Exception:
    pass

# 计数：Configure 事件数 / redraw 次数 / 上色同步次数
cnt = {"cfg": 0, "redraw": 0, "sync": 0}
tree.bind("<Configure>", lambda e: cnt.__setitem__("cfg", cnt["cfg"] + 1), add="+")
_orig_redraw = decor.redraw


def _wrap_redraw(*a, **k):
    cnt["redraw"] += 1
    return _orig_redraw(*a, **k)


decor.redraw = _wrap_redraw
_orig_sync = app._on_overlay_resized


def _wrap_sync(*a, **k):
    cnt["sync"] += 1
    return _orig_sync(*a, **k)


app._on_overlay_resized = _wrap_sync
root.update()
for k in cnt:
    cnt[k] = 0

# 给第 2 行上色，验证上色贴片同步
kids = list(tree.get_children())
app.cell_colors = {str(kids[1]): {"model": "#FF0000"}}
app._sync_paint_overlays()
root.update()

print("--- 模拟 Configure 洪流（直接触发 24 次绑定处理）---")
t0 = time.perf_counter()
for k in range(24):
    decor._on_configure()
cnt["cfg"] = 24
elapsed = (time.perf_counter() - t0) * 1000
print("  Configure=%d redraw=%d sync=%d dispatch_ms=%.1f" % (
    cnt["cfg"], cnt["redraw"], cnt["sync"], elapsed))

check("洪流中不逐帧重绘（debounce 合并）", cnt["redraw"] <= 2)
check("洪流中上色同步不逐帧执行", cnt["sync"] <= 2)
check("洪流中贴片已收起（pending）", decor._resize_pending)
check("洪流中只保留一个定时器", decor._resize_job is not None)

# 稳定后等待 debounce 完成
time.sleep(0.16)
root.update()
check("稳定后网格线恢复", len(decor._v) + len(decor._h) > 0)
check("稳定后徽章恢复", len(decor._pills) > 0)
check("稳定后复选框恢复", len(decor._chks) > 0)
check("稳定后上一个 timer 已清空", decor._resize_job is None)
check("稳定后 pending 标志已清", not decor._resize_pending)
check("上色贴片随重排同步", cnt["sync"] > 0)

# 再测一次最大化/还原（真实 state 切换）
cnt["redraw"] = 0
root.state("zoomed"); root.update()
root.state("normal"); root.update()
check("最大化/还原不逐帧重绘", cnt["redraw"] <= 2)
time.sleep(0.16); root.update()
check("还原后贴片仍完整", len(decor._pills) > 0 and len(decor._chks) > 0)

print("PROBE RESIZEPERF: %d/%d" % (ok[1], ok[0]))
try:
    app.on_close()
except Exception:
    try:
        root.destroy()
    except Exception:
        pass
