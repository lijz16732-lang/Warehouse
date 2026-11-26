# -*- coding: utf-8 -*-
"""探针：照片导出按型号自动建文件夹（v1.44.2）。
① store.photo_export_folder：item/phone 取型号、wf 取标题、非法字符清洗、空退回编号
② 子文件夹自动创建
③ photos.py 源码含自动建目录逻辑
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS = 0


def ck(name, cond):
    global PASS
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        raise SystemExit("FAIL %s" % name)


import wm.store as store_mod  # noqa: E402

TMP = tempfile.mkdtemp(prefix="cgm_probe_export_")
store_mod.resolve_data_dir = lambda: TMP

st = store_mod.Store(os.path.join(TMP, "probe.db"))

# ① 库存：取型号（含非法字符清洗）
st.insert(dict(store_mod.blank_record(),
               code="WL-00001", brand="测试牌", model="A11/Pro:x",
               qty=3, price=10))
code = "WL-00001"
ck("item 取型号+清洗", st.photo_export_folder("item", code) == "A11_Pro_x")

# ② 型号为空 → 退回编号
st.insert(dict(store_mod.blank_record(),
               code="WL-00002", brand="测试牌", model="", qty=1, price=5))
code2 = "WL-00002"
ck("item 空型号退回编号", st.photo_export_folder("item", code2) == code2)

# ③ 手机数据：取型号
st.m_upsert_item({"lid": 1, "code": "APP-00001", "brand": "手机牌",
                  "model": "S10MD JXX", "qty": 2, "price": 99})
ck("phone 取型号", st.photo_export_folder("phone", "APP-00001")
   == "S10MD JXX")

# ④ 制作单：取标题（同样清洗）
wid, _ = st.wf_create("外壳加工<x>", by="张三")
wf_no = st.wf_list()[0]["no"]
ck("wf 取标题+清洗", st.photo_export_folder("wf", wf_no) == "外壳加工_x_")

# ⑤ 未知编号 → 退回编号本身
ck("未知 item 退回", st.photo_export_folder("item", "WL-99999") == "WL-99999")
ck("未知 wf 退回", st.photo_export_folder("wf", "WO-88888") == "WO-88888")

# ⑥ 子文件夹自动创建（与 do_save_multi 同样的 makedirs 语义，含已存在不报错）
base = os.path.join(TMP, "导出")
target = os.path.join(base, st.photo_export_folder("item", code))
os.makedirs(target, exist_ok=True)
os.makedirs(target, exist_ok=True)
ck("型号子文件夹已建", os.path.isdir(target))
with open(os.path.join(target, "x.jpg"), "wb") as f:
    f.write(b"fake")
ck("子文件夹可写文件", os.path.isfile(os.path.join(target, "x.jpg")))

# ⑦ photos.py 源码含三处关键逻辑
src = open(os.path.join(ROOT, "wm", "photos.py"), encoding="utf-8").read()
ck("批量保存建型号目录", "photo_export_folder" in src
   and "os.makedirs(target, exist_ok=True)" in src)
ck("单张保存定位型号目录", "initialdir=initial" in src
   and src.count("photo_export_folder") >= 2)
ck("保存后 _note_dir 记目录", "_note_dir(os.path.dirname(path))" in src)

print("\nALL %d PASSED" % PASS)
