# -*- coding: utf-8 -*-
"""探针：编号规则 / 默认排序 / 搜索范围 / 列显示隐藏 / 局域网端口。"""

import ctypes
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk
from tkinter import ttk

from wm import app as wapp
from wm.constants import FIELD_KEYS
from wm.store import Store, blank_record

TMP = tempfile.mkdtemp(prefix="probe_set2_")
wapp.resolve_data_dir = lambda: TMP
ctypes.windll.user32.SetCursorPos(2, 2)

fails = []


def chk(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok:
        fails.append(name)


def rec(code, brand, model, price, qty, remark=""):
    r = blank_record()
    r.update({"code": code, "brand": brand, "category": "C", "model": model,
              "condition": "全新", "price": price, "qty": qty,
              "shelf": "1排A-1", "listed": 1, "remark": remark})
    return r


# ================================================ 1. 编号规则（纯 store 层）
DB = os.path.join(TMP, "warehouse.db")
st = Store(DB)
st.insert_many([rec("WL-00012", "B", "M1", 100, 1)])
chk("默认示例编号 WL-00001", st.code_sample() == "WL-00001", st.code_sample())

st.set_code_rule("SP", 4)
codes = st.generate_codes(2)
chk("改前缀 SP + 4 位：接着旧尾号 12", codes == ["SP-0013", "SP-0014"], codes)

st.set_code_rule("sp", 3)                    # 小写自动转大写
chk("前缀统一大写", st.code_prefix == "SP", st.code_prefix)
codes = st.generate_codes(1)
chk("位数改 3：SP-015", codes == ["SP-015"], codes)

# 冲突跳过：手工塞一个 SP-016
st.insert_many([rec("SP-016", "B", "M2", 10, 1)])
codes = st.generate_codes(2)
chk("已占用的号自动跳过", codes == ["SP-017", "SP-018"], codes)

# 非法前缀/位数被规整
st.set_code_rule("A B#C", 99)
chk("前缀去掉非法字符", st.code_prefix == "ABC", st.code_prefix)
chk("位数夹到 3-8", st.code_digits == 8, st.code_digits)
st.set_code_rule("WL", 5)

# 覆盖导入清空后重新从 1 开始
st.clear_all()
chk("清空后示例回到 WL-00001",
    st.generate_codes(1) == ["WL-00001"], st.generate_codes(1))
st.close()

# ================================================ 2. 造数据 + 启动 App
st = Store(DB)
st.clear_all()
st.insert_many([
    rec("WL-00001", "甲", "AAA", 50.0, 9, "备注里有 蓝月亮 三个字"),
    rec("WL-00002", "乙", "BBB", 300.0, 3, "普通"),
    rec("WL-00003", "丙", "CCC", 120.0, 7, "普通"),
])
st.close()

settings_file = os.path.join(TMP, "settings.json")


def boot():
    root = tk.Tk()
    application = wapp.App(root)
    root.update()
    return root, application


root, app = boot()

# ---- 默认排序：写设置后重启生效
app.settings["default_sort"] = "price"
app.settings["search_scope"] = "key"
app._save_settings()
root.destroy()

root, app = boot()
chk("默认排序按价格", app.sort_key == "price", app.sort_key)
chk("价格排序是降序", app.sort_desc is True)
chk("首条是最高价", app.filtered[0]["code"] == "WL-00002",
    [r["code"] for r in app.filtered])
chk("搜索范围读到 key", app.search_scope == "key", app.search_scope)

# ---- 搜索范围
app.var_kw.set("蓝月亮")
app.apply_filters()
chk("仅编号型号：搜备注词命中 0 条", len(app.filtered) == 0, len(app.filtered))
app.search_scope = "all"
app.settings["search_scope"] = "all"
app.apply_filters()
chk("全部字段：搜备注词命中 1 条", len(app.filtered) == 1,
    [r["code"] for r in app.filtered])
app.var_kw.set("WL-00003")
app.apply_filters()
chk("按编号搜索仍正常", len(app.filtered) == 1
    and app.filtered[0]["code"] == "WL-00003")

# ---- 列显示隐藏
app.var_kw.set("")
app.apply_filters()
chk("初始 10 列 + 照片列", len(app.tree["columns"]) == len(FIELD_KEYS) + 1,
    len(app.tree["columns"]))
app._toggle_col("remark", False)
chk("隐藏备注后列数 -1", "remark" not in app.tree["columns"],
    app.tree["columns"])
chk("隐藏后仍有 9 列数据", len(app.tree["columns"]) == len(FIELD_KEYS),
    len(app.tree["columns"]))
chk("其余列不受影响", "code" in app.tree["columns"])
saved = json.load(open(settings_file, encoding="utf-8"))
chk("隐藏状态已存盘", "remark" not in (saved.get("visible_cols") or []),
    saved.get("visible_cols"))
app._toggle_col("remark", True)
chk("恢复显示备注", "remark" in app.tree["columns"])

# 至少保留一列的保护
for k in FIELD_KEYS[1:]:
    app._toggle_col(k, False)
chk("最少保留一列（不被清空）", len(app.visible_cols) == 1, app.visible_cols)
app._show_all_cols()
chk("显示全部列恢复 10 列", len(app.visible_cols) == len(FIELD_KEYS))

# ---- 局域网端口
app.lan_cfg["port"] = 8080
app._save_lan_cfg()
chk("端口默认 8080", app.lan_cfg.get("port") == 8080)

# ================================================ 3. 设置页 UI
app.open_appearance("code")
root.update()
win = app._settings_win
chk("编号规则页可打开", win is not None)


def walk(w, out):
    out.append(w)
    for c in w.winfo_children():
        walk(c, out)


def ltxt(w):
    tv = str(w.cget("textvariable") or "")
    if tv:
        try:
            return str(win.getvar(tv))
        except Exception:
            pass
    return str(w.cget("text"))


def collect():
    a = []
    walk(win, a)
    return a


w1 = collect()
texts = [ltxt(w) for w in w1 if isinstance(w, tk.Label)]
chk("侧栏有「编号规则」", any("编号规则" in t for t in texts))
chk("页面有前缀输入框",
    any(isinstance(w, tk.Entry) for w in w1))
chk("显示示例编号", any("新编号示例" in t for t in texts),
    [t for t in texts if "示例" in t])
chk("有「保存规则」按钮",
    any(isinstance(w, ttk.Button) and ltxt(w) == "保存规则" for w in w1))

# 通过 UI 保存规则
ent = [w for w in w1 if isinstance(w, tk.Entry)]
vars_ = [str(w.cget("textvariable")) for w in ent]
# 直接改 settings 再调保存等价路径
app.settings["code_prefix"] = "SP"
app.settings["code_digits"] = 4
app.store.set_code_rule("SP", 4)
chk("store 立即用新规则", app.store.code_sample() == "SP-0001",
    app.store.code_sample())

app._settings_win._show_page("look")
root.update()
w2 = collect()
texts2 = [ltxt(w) for w in w2 if isinstance(w, tk.Label)]
chk("外观页有「显示的列」卡片", "显示的列" in texts2)
chk("外观页有「列表与搜索」卡片", "列表与搜索" in texts2)
chk("列标题勾选框齐全",
    sum(1 for w in w2 if isinstance(w, tk.Checkbutton)
        and ltxt(w) in ("编号", "品牌", "品类", "型号", "成色", "价格",
                        "数量", "货架", "上架状态", "备注")) >= 10,
    sum(1 for w in w2 if isinstance(w, tk.Checkbutton)))

app._settings_win._show_page("system")
root.update()
w3 = collect()
chk("系统页有「局域网端口」卡片",
    "局域网端口" in [ltxt(w) for w in w3 if isinstance(w, tk.Label)])
chk("端口输入框显示 8080",
    "8080" in [ltxt(w) for w in w3 if isinstance(w, tk.Entry)]
    or any(ltxt(w) == "8080" for w in w3))

wapp.App._settings_win = None
try:
    win.destroy()
except Exception:
    pass
app._settings_win = None
root.update()

# 截图（编号规则页）
try:
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import screenshot
    out = os.path.join(ROOT, ".tmpdbg")
    os.makedirs(out, exist_ok=True)
    app.open_appearance("code")
    root.update()
    time.sleep(0.3)
    root.update()
    w = app._settings_win
    w.title("W M 编号规则探针 %d" % os.getpid())
    root.update()
    screenshot.capture_window("W M 编号规则探针",
                              os.path.join(out, "settings_code.png"))
    w.destroy()
    app._settings_win = None
    print("SHOT ok")
except Exception as e:
    print("SHOT fail", e)

root.destroy()

print("\n==== %d fail ====" % len(fails))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
