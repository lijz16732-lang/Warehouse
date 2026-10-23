# -*- coding: utf-8 -*-
"""临时脚本：低库存「橙色高亮」开关验证（默认不高亮 + 可切换 + 随仓库保存）。"""
import os
import shutil
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wm.app as wapp  # noqa: E402
from wm.store import Store, blank_record  # noqa: E402
import screenshot  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_lowhl_")
wapp.app_dir = lambda: TMP
OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)

st = Store(os.path.join(TMP, "data", "warehouse.db"))
st.close()

root = tk.Tk()
root.withdraw()
app = wapp.App(root)

DATA = [
    ("WL-00001", "罗技", "外设", "MX MASTER 3", "99新", 599.0, 2, "6排A-3", 1),   # 低库存
    ("WL-00002", "Apple", "手机", "A2634", "95新", 2899.0, 0, "7排B-2", 1),      # 缺货
    ("WL-00003", "西门子", "驱动器", "V20", "全新", 1200.0, 1, "5排A-1", 1),      # 低库存
    ("WL-00004", "戴尔", "显示器", "U2720Q", "9成新", 1580.0, 5, "8排C-1", 1),
    ("WL-00005", "华为", "网络", "S5720", "9成新", 2100.0, 12, "4排A-1", 1),
]
app.store.insert_many([blank_record() | {"code": c, "brand": b, "category": cat, "model": m,
                                         "condition": cond, "price": p, "qty": q,
                                         "shelf": sh, "listed": l}
                       for c, b, cat, m, cond, p, q, sh, l in DATA])
app.low_threshold = 3
app.store.set_meta("low_stock_threshold", 3)
app.load_data()
root.deiconify()
root.geometry("1400x880+80+30")
root.update()

FAIL = []


def check(name, cond):
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if not cond:
        FAIL.append(name)


def tagged():
    """返回 {iid: tags} —— 表格里每行当前的 ttk 标签。"""
    out = {}
    for iid in app.tree.get_children():
        out[iid] = tuple(app.tree.item(iid, "tags"))
    return out


def hi_count():
    t = tagged()
    return sum(1 for v in t.values() if "low" in v or "oos" in v)


print("== 1. 默认状态 ==")
check("默认不高亮（var_low_hl=False）", app.var_low_hl.get() is False)
check("默认表格无 low/oos 标签", hi_count() == 0)
check("侧栏仍统计低库存条数",
      "低库存" in app.lbl_side.cget("text"))
screenshot.capture(os.path.join(OUT, "lowhl_off.png"))
print("shot -> lowhl_off.png（默认：无橙色高亮）")

print("== 2. 勾选开启高亮 ==")
app.var_low_hl.set(True)
app.toggle_low_hl()
root.update()
check("开启后有 2 行低库存 + 1 行缺货被标记", hi_count() == 3)
check("低库存行带 low 标签（橙色底）",
      any("low" in v for v in tagged().values()))
check("缺货行带 oos 标签（深橙字）",
      any("oos" in v for v in tagged().values()))
check("状态栏提示已开启", "开启" in app.lbl_status.cget("text"))
screenshot.capture(os.path.join(OUT, "lowhl_on.png"))
print("shot -> lowhl_on.png（开启：橙色高亮）")

print("== 3. 随仓库保存 ==")
check("meta 已写入 1", int(app.store.get_num("low_stock_highlight", 0)) == 1)
app._load_prefs()
check("重新读取偏好后仍为开启", app.var_low_hl.get() is True)

print("== 4. 再次关闭 ==")
app.var_low_hl.set(False)
app.toggle_low_hl()
root.update()
check("关闭后无任何高亮", hi_count() == 0)
check("meta 已写入 0", int(app.store.get_num("low_stock_highlight", 0)) == 0)
check("「只看低库存」筛选仍可用（与高亮无关）", app.var_low_only.get() in (True, False))
app.var_low_only.set(True)
app.apply_filters()
root.update()
check("筛选命中 3 条低库存（含 0 库存缺货）", len(app.filtered) == 3)
check("侧栏统计口径与筛选一致（低库存 3 条）",
      "低库存 3 条" in app.lbl_side.cget("text"))
screenshot.capture(os.path.join(OUT, "lowhl_filter_only.png"))
print("shot -> lowhl_filter_only.png（不高亮 + 只看低库存筛选）")

root.destroy()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%s" % ("ALL PASSED" if not FAIL else "FAILED: %s" % FAIL))
