# -*- coding: utf-8 -*-
"""探针：入库段（照片 + 货架 + 自动建库存 + 照片带过去）。"""
import base64
import io
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk

from wm import app as wapp
from wm import workflow as wfmod
from wm.store import Store

TMP = tempfile.mkdtemp(prefix="wf_stock_")
wapp.resolve_data_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()
wfmod.messagebox.showinfo = lambda *a, **k: None

fails = []


def chk(name, cond, got=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + ("" if cond else "  -> %s" % (got,)))
    if not cond:
        fails.append(name)


root = tk.Tk()
app = wapp.App(root)
tab = wfmod.WorkflowTab(root, app)
tab.pack(fill="both", expand=True)
root.update_idletasks()
root.update()

store = app.store
stages = store.wf_stages()
wf_id, no = store.wf_create("保德型号更换", kind="更换型号标签", by="张三",
                            extra={"原型号": "WL-00012", "更换后型号": "S10MD"})
# 推到入库站（最后一站）——v1.42.8 起推进到最后一站不再立即结束
for i in range(len(stages) - 1):
    store.wf_advance(wf_id, "工位%d" % i, "")
rec = [r for r in store.wf_list("active", "") if int(r["id"]) == wf_id][0]
chk("推进到入库站仍是进行中", rec["stage_name"] == stages[-1],
    rec["stage_name"])

# 一张最小 PNG（1x1）
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAA"
    "YAAf8B9W8lAAAAAElFTkSuQmCC")

dlg = wfmod.FlowDialog(tab, tab, rec, True)
root.update()
chk("入库段有照片区", getattr(dlg, "photo_strip", None) is not None)
chk("照片区绑在本单号上", dlg.photo_strip.code == no, dlg.photo_strip.code)
chk("新增库存默认勾选（货架等可直接填）", dlg.var_stock.get() is True)
shelf_ent = None
for w in dlg._stock_widgets:
    pass
chk("货架字段存在且可编辑",
    str(dlg.stock_vars["shelf"].get()) == ""
    and any(str(w.cget("state")) != "disabled" for w in dlg._stock_widgets))
chk("型号已预填「更换后型号」", dlg.stock_vars["model"].get() == "S10MD",
    dlg.stock_vars["model"].get())

# 通过 PhotoStrip 的接口加一张照片（走 store.photo_add，和界面同一条路）
ok, err = 0, ""
try:
    store.photo_add("wf", no, base64.b64encode(png).decode("ascii"), "入库.png")
    ok = 1
except Exception as e:
    err = str(e)
chk("制作单能存照片", ok == 1, err)
chk("照片列表读得到", len(store.photos_list("wf", no)) == 1)
dlg.photo_strip.set_code(no)
root.update()
chk("弹窗照片区显示 1 张", dlg.photo_strip.lbl_cap.cget("text").startswith("照片 1/"),
    dlg.photo_strip.lbl_cap.cget("text"))

# 填货架等，走存储层入库
dlg.stock_vars["brand"].set("保德")
dlg.stock_vars["category"].set("开关电源")
dlg.stock_vars["shelf"].set("A-03-2")
dlg.stock_vars["qty"].set("2")
dlg.stock_vars["price"].set("150")
stock_rec = {k: v.get().strip() for k, v in dlg.stock_vars.items()}
ok2, msg = store.wf_stock_in(wf_id, stock_rec, by="李四")
chk("入库成功", ok2, msg)
print("   入库返回：", msg)
items = [it for it in store.all_records() if it.get("model") == "S10MD"]
chk("库存里有了对应型号", len(items) == 1, len(items))
it = items[0]
chk("货架写对", it.get("shelf") == "A-03-2", it.get("shelf"))
chk("数量/单价写对", int(it.get("qty") or 0) == 2 and float(it.get("price") or 0) == 150,
    (it.get("qty"), it.get("price")))
chk("备注标了制作入库", "制作入库" in (it.get("remark") or ""), it.get("remark"))
chk("入库照片带到了库存记录", len(store.photos_list("item", it["code"])) == 1,
    store.photos_list("item", it["code"]))
wf_done = store.wf_one(wf_id)
chk("入库后单据标记完成", wf_done.get("status") == "done",
    wf_done.get("status"))

wf_now = store.wf_one(wf_id)
chk("单据回写了关联编号", wf_now.get("target") == it["code"], wf_now.get("target"))
logs = store.wf_logs(wf_id)
chk("流转记录里有入库一步",
    any(g.get("action") == "stock" for g in logs),
    [g.get("action") for g in logs])

# 列表 📷 列（单据已完成 → 切到「已完成」列表看）
tab.var_status.set("done")
tab.refresh_rows()
root.update()
iid = str(wf_id)
chk("列表显示照片标记", tab.tree.set(iid, "photo") == "📷",
    tab.tree.set(iid, "photo"))

# 缺型号拦截（用另一张停在入库站的进行中单据测）
wid2, _ = store.wf_create("拦截测试", by="张三")
for i in range(len(stages) - 1):
    store.wf_advance(wid2, "工位%d" % i, "")
ok3, msg3 = store.wf_stock_in(wid2, {"model": "", "qty": "1"}, by="李四")
chk("型号为空被拦", ok3 is False and "型号" in msg3, msg3)
ok4, msg4 = store.wf_stock_in(wid2, {"model": "X", "qty": "0"}, by="李四")
chk("数量为 0 被拦", ok4 is False and "数量" in msg4, msg4)
ok5, msg5 = store.wf_finish(wid2, "李四", "不要了")
chk("不新增库存直接结单", ok5, msg5)
chk("结单后单据完成", store.wf_one(wid2).get("status") == "done",
    store.wf_one(wid2).get("status"))

# 删除单连带清照片
store.wf_delete(wf_id)
chk("删除制作单连带清照片", store.photos_list("wf", no) == [],
    store.photos_list("wf", no))
chk("库存照片不受影响（已复制到 item）",
    len(store.photos_list("item", it["code"])) == 1)

root.destroy()
print("\n%s" % ("ALL PASSED" if not fails else "FAILED: %s" % fails))
sys.exit(0 if not fails else 1)
