# -*- coding: utf-8 -*-
"""探针：设置页「关于与维护」—— 存储占用 / 数据体检 / 孤立照片 / VACUUM。

只碰临时数据目录。
"""

import ctypes
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk

from wm import app as wapp
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="probe_about_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "warehouse.db")).close()
ctypes.windll.user32.SetCursorPos(2, 2)

fails = []


def chk(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        fails.append(name)


def wait(cond, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        root.update()
        if cond():
            return True
        time.sleep(0.05)
    root.update()
    return cond()


root = tk.Tk()
app = wapp.App(root)
root.update()


def rec(code, model, qty, price=10.0):
    r = blank_record()
    r.update({"code": code, "brand": "B", "category": "C", "model": model,
              "condition": "全新", "price": price, "qty": qty,
              "shelf": "1排A-1", "listed": 1, "remark": ""})
    return r


rows = [rec("WL-%05d" % i, "M%d" % i, 2) for i in range(10)]
rows.append(rec("WL-00090", "DUPMM", 3))        # 同型号两条
rows.append(rec("WL-00091", "DUPMM", 1))
rows.append(rec("WL-00092", "NEG", -3))         # 负库存
rows.append(rec("WL-00093", "ZERO", 0))         # 数量 0 未标售完
app.store.insert_many(rows)
app.load_data()
root.update()

# 一条指向不存在商品的出售记录 + 一条正常出售
item_id = app.store.all_records()[0]["id"]
app.store.add_sale(item_id, 1, 12.0, buyer="张三", sale_date="2026-11-01")
with app.store._lock:
    app.store.conn.execute(
        'INSERT INTO sales (item_id, code, brand, category, model, qty, price,'
        ' total, cost, buyer, address, sale_date, remark, out_type, created_at)'
        ' VALUES (99999, "WL-88888", "B", "C", "X", 1, 10, 10, 0, "", "", '
        '"2026-11-02", "", "销售", "2026-11-02 10:00:00")')
    app.store.conn.commit()

# 孤立照片：库里没有 WL-77777，磁盘上却有
orph_dir = os.path.join(app.store.photos_root(), "item", "WL-77777")
os.makedirs(orph_dir, exist_ok=True)
with open(os.path.join(orph_dir, "a.jpg"), "wb") as f:
    f.write(b"x" * 4096)
with open(os.path.join(orph_dir, "b.jpg"), "wb") as f:
    f.write(b"x" * 2048)
# 一条正常记录的照片（不能算孤立）
keep_dir = os.path.join(app.store.photos_root(), "item", "WL-00000")
os.makedirs(keep_dir, exist_ok=True)
with open(os.path.join(keep_dir, "k.jpg"), "wb") as f:
    f.write(b"y" * 1024)

# ============================================ 1. 数据体检（纯 store 层）
res = {r["key"]: r for r in app.store.health_check()}
chk("体检项目齐全(6 项)", len(res) == 6, list(res))
chk("检出负库存 1 条", res["neg"]["count"] == 1, res["neg"]["rows"])
chk("负库存为警示级", res["neg"]["level"] == "warn")
chk("检出数量为 0 未售完 1 条", res["zero"]["count"] == 1, res["zero"]["rows"])
chk("检出同型号重复 1 组", res["dup"]["count"] == 1, res["dup"]["rows"])
chk("检出孤立照片 1 个", res["photo"]["count"] == 1, res["photo"]["rows"])
chk("孤立照片统计张数=2", res["photo"]["rows"] == ["商品 WL-77777（2 张）"],
    res["photo"]["rows"])
chk("出售关联缺失 1 条", res["lost"]["count"] == 1, res["lost"]["rows"])
chk("出售有成本提示（成本 0）出现", res["cost"]["count"] >= 1, res["cost"]["rows"])
chk("体检样本含编号", all(isinstance(x, str) for x in res["neg"]["samples"]))

# ============================================ 2. 统计
n_ph, sz_ph = app.store.photo_stats()
chk("照片统计 3 张", n_ph == 3, n_ph)
chk("照片字节 4096+2048+1024", sz_ph == 7168, sz_ph)
chk("库大小 > 0", app.store.db_size() > 0)
cnt = app.store.table_counts()
chk("记录数：在库 14", cnt["items"] == 14, cnt["items"])
chk("记录数：出售 2", cnt["sales"] == 2, cnt["sales"])
chk("记录数：客户 0", cnt["customers"] == 0)
chk("记录数：采购 0", cnt["purchases"] == 0)

# ============================================ 3. 设置页 UI
app.open_appearance("about")
root.update()
win = app._settings_win
chk("设置窗口打开", win is not None)
win.title("W M 关于探针 %d" % os.getpid())
root.update()

# 存储占用应在 after(120) 后自动统计完成
def walk(w, out):
    out.append(w)
    for c in w.winfo_children():
        walk(c, out)


allw = []
walk(win, allw)
labels = [w for w in allw if isinstance(w, tk.Label)]


def ltxt(w):
    """Label 的显示文本：有 textvariable 时取值，否则取 text。"""
    tv = str(w.cget("textvariable") or "")
    if tv:
        try:
            return str(win.getvar(tv))
        except Exception:
            pass
    return str(w.cget("text"))


texts = [ltxt(w) for w in labels]
chk("页面标题存在", "关于与维护" in texts)
chk("侧栏有「关于与维护」入口", any("关于与维护" in t for t in texts))
chk("显示版本号", any(("v" + wapp.APP_VERSION) == t for t in texts),
    [t for t in texts if t.startswith("v1.")])
chk("显示当前仓库名", any("当前仓库" in t for t in texts))

# 等后台统计把数值填进去（占位符是「…」）
ok = wait(lambda: "…" not in [ltxt(w) for w in labels
                              if w.winfo_exists()], 10)
vals = [ltxt(w) for w in labels if w.winfo_exists()]
chk("存储占用统计完成（无「…」占位）", ok,
    [t for t in vals if t.endswith("B") or "MB" in t or "KB" in t])
chk("显示库存条数", any("库存 " in t for t in vals), [t for t in vals if "库存 " in t])
chk("显示照片张数", any("张，" in t for t in vals), [t for t in vals if "张，" in t])

# 体检按钮 → 结果渲染
btns = [w for w in allw if w.winfo_class() == "TButton"]
names = [str(w.cget("text")) for w in btns]
chk("有「开始体检」按钮", "开始体检" in names, names[:20])
chk("有「清理多余照片」按钮", "清理多余照片" in names)
chk("有「压缩数据库」按钮", "压缩数据库" in names)
chk("有「检查数据库完整性」按钮", "检查数据库完整性" in names)

for b in btns:
    if str(b.cget("text")) == "开始体检":
        b.invoke()
        break
ok = wait(lambda: any("项检查" in ltxt(w) for w in labels if w.winfo_exists()), 10)
chk("体检结果已渲染", ok)
res_txt = [ltxt(w) for w in labels if "项检查" in ltxt(w)]
chk("体检汇总提到需处理项", bool(res_txt) and "建议处理" in res_txt[0], res_txt)
allw2 = []
walk(win, allw2)
labels2 = [w for w in allw2 if isinstance(w, tk.Label)]
t2 = [ltxt(w) for w in labels2]
chk("体检行列出「库存数量为负」", "库存数量为负" in t2, t2[-16:])
chk("体检行显示「1 条」", "1 条" in t2)
chk("6 项都列出例证", sum(1 for t in t2 if t.startswith("例：")) == 6,
    [t for t in t2 if "例：" in t])

# ============================================ 4. 清理孤立照片（直接调 store，绕过确认框）
before_n, _sz = app.store.photo_stats()
dirs, freed = app.store.photos_clear_orphans()
after_n, _sz2 = app.store.photo_stats()
chk("清理 1 个孤立目录", dirs == 1, dirs)
chk("释放空间 6144 字节", freed == 6144, freed)
chk("照片从 3 张降到 1 张", (before_n, after_n) == (3, 1), (before_n, after_n))
chk("在库记录的照片未被误删", os.path.isdir(keep_dir))
chk("孤立目录已删除", not os.path.isdir(orph_dir))
chk("再查已无孤立", app.store.orphan_photos() == [])

# ============================================ 5. VACUUM / 完整性
app.store.delete_ids([r["id"] for r in app.store.all_records()[:6]])
with app.store._lock:                   # 先撑大库再丢表，制造可回收的空洞
    app.store.conn.execute('CREATE TABLE IF NOT EXISTS _noise (b BLOB)')
    app.store.conn.execute('INSERT INTO _noise (b) VALUES (?)',
                           (b"z" * (300 * 1024),))
    app.store.conn.commit()
    app.store.conn.execute('DROP TABLE _noise')
    app.store.conn.commit()
b4, af = app.store.vacuum()
chk("VACUUM 返回前后大小", isinstance(b4, int) and isinstance(af, int), (b4, af))
chk("VACUUM 后不变大", af <= b4, (b4, af))
ok, msgs = app.store.integrity_check()
chk("完整性检查通过", ok, msgs)

# 压缩后数据仍在
chk("压缩后记录数不变", app.store.table_counts()["items"] == 8,
    app.store.table_counts()["items"])

# ============================================ 6. 截图
try:
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import screenshot
    out = os.path.join(ROOT, ".tmpdbg")
    os.makedirs(out, exist_ok=True)
    win._show_page("about")
    root.update()
    root.update_idletasks()
    screenshot.capture_window("W M 关于探针",
                              os.path.join(out, "settings_about.png"))
    app._settings_win = None
    win.destroy()
    root.update()
    print("SHOT ok")
except Exception as e:
    print("SHOT fail", e)

root.destroy()

print("\n==== %d fail ====" % len(fails))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
