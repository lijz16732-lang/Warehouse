# -*- coding: utf-8 -*-
"""v1.46.1 探针：详情右抽屉。

验证点：
1. 默认（show_detail=True）：抽屉在表格右侧固定宽，细条不显示
2. 选中一行 → 抽屉标题与照片条联动
3. 点 ✕ 收起 → 抽屉消失、细条出现、设置持久化为 False
4. 点细条展开 → 抽屉回来、设置持久化为 True
5. KPI 卡 / 表尾汇总条不受布局调整影响
"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk
from tkinter import ttk

import wm.app as wapp
from wm.store import Store, blank_record


def _walk_lbls(w):
    out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Label):
            out.append(c)
        out.extend(_walk_lbls(c))
    return out

TMP = tempfile.mkdtemp(prefix="wm_probe_drawer_")
wapp.app_dir = lambda: TMP
wapp.resolve_data_dir = lambda: TMP
st = Store(os.path.join(TMP, "warehouse.db"))
for i in range(1, 4):
    rec = blank_record()
    rec.update({"lid": i, "code": "WL-%05d" % i, "brand": "基恩士",
                "category": "传感器", "model": "FS-V%d" % i,
                "qty": 3, "price": 1280.5, "listed": 1})
    st.insert(rec)
# cost 非录入字段（只由采购/SQL 写）：SQL 直置，驱动「成本/毛利」行
st.conn.execute("UPDATE items SET cost=860.0")
# 同型号（FS-V1）近 30 天出售两笔 → 驱动动向折线与统计
st.conn.execute(
    "INSERT INTO sales (code, brand, category, model, qty, price, total, "
    "cost, sale_date, out_type) VALUES ('WL-00001','基恩士','传感器','FS-V1',"
    "1,1280.5,1280.5,860,?,'出售')",
    (__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
st.conn.execute(
    "INSERT INTO sales (code, brand, category, model, qty, price, total, "
    "cost, sale_date, out_type) VALUES ('WL-00002','基恩士','传感器','FS-V1',"
    "2,1280.5,2561.0,1720,?,'出售')",
    (__import__("datetime").datetime(1, 1, 1).fromtimestamp(
        __import__("time").time() - 86400 * 3).strftime("%Y-%m-%d %H:%M:%S"),))
st.conn.commit()
st.close()

ok = [0, 0]


def check(name, cond, detail=""):
    ok[0] += 1
    if cond:
        ok[1] += 1
    print(("ok  " if cond else "FAIL") + " " + name
          + ("" if cond else (" | " + str(detail))))


try:
    ctypes.windll.user32.SetCursorPos(2, 2)
except Exception:
    pass

root = tk.Tk()
root.geometry("1280x820+20+20")
app = wapp.App(root)
app.nb.select(app.tab_inv)
app.load_data()
root.update_idletasks()
root.update()

# ---- 1 默认展开 ----
check("默认抽屉展开（show_detail=True）", app.var_show_detail.get() is True)
check("抽屉已映射且在表格右侧", app.detail_card.winfo_ismapped()
      and app.detail_card.winfo_rootx() > app.tree.winfo_rootx())
check("抽屉宽度 ≈300", 240 <= app.detail_card.winfo_width() <= 360)
check("收起细条未显示", not app.detail_rail.winfo_ismapped())

# ---- 2 选中联动 ----
iid = str(app.filtered[0]["id"])
app.tree.selection_set(iid)
root.update()
check("抽屉标题联动（编号·品牌）",
      "WL-00001" in app.lbl_detail_title.cget("text"))
check("照片条挂在抽屉内", str(app.photo_strip.master) == str(app.detail_card))

# ---- 2b 卡片模式（设计稿同款）----
check("卡片模式已开启（文本区隐藏）", app.detail_rows.winfo_ismapped()
      and not app.detail_txt.winfo_ismapped())
check("字段卡有行（编号/品牌/成色/价格/成本/货架/状态）",
      len(app.detail_rows.winfo_children()) >= 7)
texts = "|".join(str(w.cget("text")) for w in _walk_lbls(app.detail_rows))
check("编号蓝色加粗在卡内", "WL-00001" in texts)
check("成本含毛利", "毛利" in texts and "¥860.00" in texts)
check("2×2 动作按钮齐（出售/编辑/打印标签/退回制作）",
      len(app._act_btns) == 4
      and all(b.winfo_ismapped() for b in app._act_btns))
sale_txt = app.lbl_trend_sale.cget("text")
check("动向统计：近30天出售 3 件", "3 件" in sale_txt and "3,841.50" in sale_txt,
      sale_txt)
avg_txt = app.lbl_trend_avg.cget("text")
check("同类均价（另两条同品类在售）", avg_txt.startswith("¥"), avg_txt)
check("折线已画（canvas 有元素）", len(app.cv_trend.find("all")) > 0)

# 打印标签：桩掉系统打印，验证生成路径与调用
import os as _os
_printed = []
_orig_sf = _os.startfile
_os.startfile = lambda *a, **k: _printed.append(a)
try:
    app.print_label()
finally:
    _os.startfile = _orig_sf
check("打印标签走系统打印动词", len(_printed) == 1
      and _printed[0][1] == "print" if len(_printed) else False)

# 退回制作：跳到制作流程页并按编号筛选
app.goto_workflow_back()
root.update()
check("退回制作跳转制作流程页", str(app.nb.select()) == str(app.tab_workflow)
      and app.tab_workflow.var_kw.get() == "WL-00001")
app.nb.select(app.tab_inv)
root.update()

# ---- 3 ✕ 收起 ----
app._close_detail_drawer()
root.update()
check("✕ 后抽屉收起（细条显示）", not app.detail_card.winfo_ismapped()
      and app.detail_rail.winfo_ismapped())
check("设置持久化 False", app.settings.get("show_detail") is False
      and app.var_show_detail.get() is False)

# ---- 4 细条展开 ----
app._open_detail_drawer()
root.update()
check("细条点击后抽屉展开", app.detail_card.winfo_ismapped()
      and not app.detail_rail.winfo_ismapped())
check("设置持久化 True", app.settings.get("show_detail") is True)

# 选中内容不因收起/展开丢失
check("重开后标题仍在", "WL-00001" in app.lbl_detail_title.cget("text"))

# ---- 5 KPI / 汇总条共存 ----
check("KPI 行正常", app.kpi_vals["count"].cget("text") == "9")
check("汇总条正常", "3 / 3" in app.lbl_sum_hit.cget("text"))

root.destroy()
print("%d/%d 项通过" % (ok[1], ok[0]))
sys.exit(0 if ok[1] == ok[0] else 1)
