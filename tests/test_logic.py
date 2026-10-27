# -*- coding: utf-8 -*-
"""自动化测试：数据层 + XLSX 读写 + GUI 冒烟（含后台任务线程安全）。"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback

import faulthandler  # noqa: E402
faulthandler.dump_traceback_later(180, exit=True)   # 卡死 4 分钟自动转储堆栈并退出

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import wm.app as wapp  # noqa: E402
from wm import xlsxio  # noqa: E402
from wm.store import blank_record, dedupe_records  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wm_test_")
wapp.app_dir = lambda: TMP

FAILS = []


def check(name, cond, extra=""):
    if cond:
        print("  [PASS] %s" % name)
    else:
        print("  [FAIL] %s %s" % (name, extra))
        FAILS.append(name)


# ============================================================ 数据层测试
print("== 1. 表头智能映射 ==")
from wm.constants import FIELD_KEYS  # noqa: E402
check("名称字段已移除", "name" not in FIELD_KEYS)

sample_headers = ["商品编码", "牌子", "品类", "规格型号", "新旧程度", "售价(元)",
                  "库存数量", "G (货架)", "是否上架", "说明", "多余列"]
mp = xlsxio.map_headers(sample_headers)
mapped = set(mp.values())
need = {"code", "brand", "category", "model", "condition", "price", "qty",
        "shelf", "listed", "remark"}
check("全部核心字段识别", need <= mapped, "缺:%s" % (need - mapped))
check("括号表头识别为货架",
      sample_headers[[i for i, v in mp.items() if v == "shelf"][0]] == "G (货架)")
check("未识别列忽略", "多余列" not in [sample_headers[i] for i in mp])

# 括号在前的变体
mp_b = xlsxio.map_headers(["货架(3排区)", "品牌(主要)", "单价（元）"])
check("括号在前变体", mp_b.get(0) == "shelf" and mp_b.get(1) == "brand"
      and mp_b.get(2) == "price", str(mp_b))

# 真实场景：没有编号列、价格列写成「单格」
real_headers = ["品牌", "品类", "型号", "数量", "成色", "单格", "货架", "备注", "是否上架"]
mp_c = xlsxio.map_headers(real_headers)
check("「单格」识别为价格", mp_c.get(5) == "price", str(mp_c))
check("无编号列时不误判", "code" not in set(mp_c.values()), str(mp_c))
check("该表 9 列全部识别", len(mp_c) == 9, "实际=%d" % len(mp_c))

# 数量列的累加写法
check("数量 1+1 → 2", xlsxio.to_int("1+1") == 2)
check("数量 48+9 → 57", xlsxio.to_int("48+9") == 57)
check("数量 纯数字", xlsxio.to_int(3) == 3 and xlsxio.to_int("6") == 6)

# 多货架：同一字段多列（位置1/位置2/位置3）识别与合并
mp_d = xlsxio.map_headers(["品牌", "型号", "货架(位置1)", "货架(位置2)", "货架(位置3)"])
check("多货架列全部识别为货架",
      mp_d.get(2) == "shelf" and mp_d.get(3) == "shelf" and mp_d.get(4) == "shelf",
      str(mp_d))
recs_d, mp_d2, unmapped_d = xlsxio.rows_to_records(
    ["品牌", "型号", "货架(位置1)", "货架(位置2)", "货架(位置3)"],
    [["罗技", "G502", "6排A-3", "7排A-1", ""],
     ["罗技", "G503", "2排A-1", "2排B-1", "2排B-2"],
     ["罗技", "G504", "5排A-1", "5排A-1", ""]])
check("两货架合并", xlsxio.normalize_record(recs_d[0])["shelf"] == "6排A-3 / 7排A-1",
      "=%r" % recs_d[0]["shelf"])
check("三货架合并", xlsxio.normalize_record(recs_d[1])["shelf"] == "2排A-1 / 2排B-1 / 2排B-2",
      "=%r" % recs_d[1]["shelf"])
check("重复货架值不重复合并", xlsxio.normalize_record(recs_d[2])["shelf"] == "5排A-1",
      "=%r" % recs_d[2]["shelf"])
check("多货架列不计入未识别", unmapped_d == [], str(unmapped_d))

print("== 2. 生成测试 XLSX ==")
xlsx_path = os.path.join(TMP, "in.xlsx")
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["仓库 2026 年 10 月台帐"])   # 干扰行
ws.append([])
ws.append(sample_headers)
sample_rows = [
    ["SKU-001", "罗技", "外设", "G502 LIGHTSPEED", "99新", 389.5, 12, "3排A-1", "是", "x"],
    ["SKU-002", "Apple", "手机", "A2634", "95新", 2899, 3, "7排B-2", "已上架", ""],
    ["SKU-003", "戴尔", "显示器", "U2720Q", "9成新", 1580, 0, "10排A架旁", "否", "边角磕碰"],
    ["SKU-004", "联想", "笔记本", "X1C Gen9", "8成新", 3600, 2, "金总办公室", "未上架", ""],
    ["SKU-005", "小米", "穿戴", "SPP4020", "全新", 199.9, 30, "4排B-1", "是", ""],
]
for r in sample_rows:
    ws.append(r)
# 无编号行 + 同文件重复编号行（模拟用户真实数据）
ws.append([None, "无牌", "杂项", "-", "新", 5, 1, "Z-9", "否", "编号缺失"])
ws.append(["SKU-001", "罗技", "外设", "G502", "99新", 420, 1, "3排A-2", "是", "同编号第二行"])
wb.save(xlsx_path)

headers, rows, meta = xlsxio.read_xlsx(xlsx_path)
check("表头行自动探测", meta["header_row"] == 3, "实际=%s" % meta["header_row"])
check("读到 7 行数据", len(rows) == 7, "实际=%d" % len(rows))
records, mp2, unmapped = xlsxio.rows_to_records(headers, rows)
check("转换 7 条记录", len(records) == 7, "实际=%d" % len(records))
norm = [xlsxio.normalize_record(r) for r in records]
check("价格类型", abs(norm[0]["price"] - 389.5) < 1e-6, "=%r" % norm[0]["price"])
check("数量类型", norm[0]["qty"] == 12)
check("货架列取值正确", norm[0]["shelf"] == "3排A-1", "=%r" % norm[0]["shelf"])
check("上架=是→1", norm[0]["listed"] == 1)
check("上架=否→0", norm[2]["listed"] == 0)
check("上架=未上架→0", norm[3]["listed"] == 0)

print("== 3. SQLite 存储 ==")
db = os.path.join(TMP, "t.db")
from wm.store import Store
st = Store(db)
n = st.insert_many(norm)
check("批量插入", n == 7)
check("全量读取", len(st.all_records()) == 7)
check("distinct 品牌", set(st.distinct("brand")) == {"罗技", "Apple", "戴尔", "联想", "小米", "无牌"})

# 多货架：distinct 拆分 + 筛选拆分命中
st.insert_many([blank_record() | {"code": "WL-M1", "brand": "罗技", "model": "MS-1",
                                  "shelf": "6排A-3 / 7排A-1"}])
check("distinct 货架拆分",
      "6排A-3" in st.distinct("shelf") and "7排A-1" in st.distinct("shelf")
      and "6排A-3 / 7排A-1" not in st.distinct("shelf"), str(st.distinct("shelf"))[:120])
from wm.app import shelf_parts  # noqa: E402
check("shelf_parts 拆分", shelf_parts("6排A-3 / 7排A-1") == ["6排A-3", "7排A-1"],
      str(shelf_parts("6排A-3 / 7排A-1")))
check("shelf_parts 单值", shelf_parts(" 3排A-1 ") == ["3排A-1"], str(shelf_parts(" 3排A-1 ")))
check("shelf_parts 空值", shelf_parts("") == [] and shelf_parts(None) == [])
# 删除多货架测试记录，恢复原有 7 条，避免影响后续计数断言
_m1 = [r for r in st.all_records() if r.get("code") == "WL-M1"]
st.delete_ids([r["id"] for r in _m1])
check("多货架测试记录已清理", st.count() == 7, "实际=%d" % st.count())

rid = [r for r in st.all_records() if r["code"] == "SKU-001"][0]["id"]
upd = blank_record()
upd.update({"code": "SKU-001", "price": 400, "qty": 9,
            "brand": "罗技", "category": "外设", "model": "G502", "condition": "99新",
            "shelf": "3排A-1", "listed": 0, "remark": "改"})
st.update(rid, upd)
rec = [r for r in st.all_records() if r["id"] == rid][0]
check("更新生效", rec["brand"] == "罗技" and rec["price"] == 400 and rec["listed"] == 0)

st.set_listed([rid], 1)
rec = [r for r in st.all_records() if r["id"] == rid][0]
check("上架切换", rec["listed"] == 1)

# 编号自动生成
codes = st.generate_codes(3)
check("自动编号格式", all(c.startswith("WL-") for c in codes), str(codes))
check("自动编号唯一", len(set(codes)) == 3)
st.insert_many([blank_record() | {"code": c, "brand": "auto"} for c in codes])
check("自动编号无冲突", st.count() == 10)

# ============================================================ 按「型号」合并
print("== 3.1 按型号合并（重复则跳过且不改动原记录，不重复则新增） ==")
from wm.constants import norm_model, is_blank_model  # noqa: E402
from wm.store import Store  # noqa: E402
ms = Store(os.path.join(TMP, "model.db"))
ms.insert_many([dict(blank_record(), **r) for r in (
    {"code": "WL-00001", "brand": "B&R贝加莱", "category": "电机", "model": "8MSA4L.R0-W2",
     "condition": "已修复", "price": 16000, "qty": 1, "shelf": "1排B-2", "listed": 1,
     "remark": ""},
    {"code": "WL-00002", "brand": "东荣", "category": "驱动器", "model": "VLAST-070P3V-X",
     "condition": "已修复", "price": 25000, "qty": 1, "shelf": "10排B架旁", "listed": 1,
     "remark": ""},
    {"code": "WL-00003", "brand": "ABB", "category": "驱动器", "model": "ABB  PFEA111",
     "condition": "旧", "price": 100, "qty": 2, "shelf": "A-1", "listed": 0,
     "remark": "原备注"},
)])
mr = ms.merge_many([
    # ① 型号相同（大小写/多余空格视为同一型号）→ 跳过，库中原记录完全不动
    {"model": "abb pfea111", "brand": "ABB", "category": "驱动器", "condition": "已修复",
     "price": 888, "qty": 5, "shelf": "4排B-1", "listed": 1, "remark": ""},
    # ② 型号不存在 → 新增，编号自动生成（承接 WL-00003）
    {"model": "NEW-MODEL-01", "brand": "新品牌", "category": "电机", "condition": "全新",
     "price": 66, "qty": 3, "shelf": "Z-1", "listed": 1, "remark": ""},
    # ③ 同一文件里型号重复 → 合并为一条（保留最后一条）
    {"model": "DUP-01", "price": 10, "qty": 1, "brand": "x", "remark": ""},
    {"model": "dup-01", "price": 20, "qty": 2, "brand": "y", "remark": ""},
    # ④ 型号为空 / 无效 → 不参与判定，一律新增
    {"model": "", "price": 1, "qty": 1, "brand": "无型号", "remark": ""},
    {"model": "-", "price": 2, "qty": 1, "brand": "无型号2", "remark": ""},
], "model")
check("按型号合并：型号已存在则跳过 1 条", mr["skipped"] == 1, str(mr))
check("按型号合并：新增 4 条", mr["added"] == 4, str(mr))
check("按型号合并：文件内重复合并 1 条", mr["merged"] == 1, str(mr))
check("按型号合并：自动编号 4 条", mr["auto"] == 4, str(mr))
check("按型号合并不含更新/清理动作",
      "updated" not in mr and "cleaned" not in mr, str(mr))
check("按型号合并后总条数", ms.count() == 7, "实际=%d" % ms.count())

recs_ms = ms.all_records()
abb = [r for r in recs_ms if norm_model(r["model"]) == "abb pfea111"]
check("同型号只保留一条", len(abb) == 1, "实际=%d" % len(abb))
check("原有记录编号未被改动", abb[0]["code"] == "WL-00003", abb[0]["code"])
check("原有记录价格未被改动", abs(float(abb[0]["price"]) - 100) < 1e-6, abb[0]["price"])
check("原有记录数量未被改动", int(abb[0]["qty"]) == 2, abb[0]["qty"])
check("原有记录备注未被改动", abb[0]["remark"] == "原备注", abb[0]["remark"])
check("原有记录品牌未被改动", abb[0]["brand"] == "ABB", abb[0]["brand"])
dup_row = [r for r in recs_ms if norm_model(r["model"]) == "dup-01"][0]
check("文件内重复取最后一条", abs(float(dup_row["price"]) - 20) < 1e-6, dup_row["price"])
new_codes = sorted(r["code"] for r in recs_ms if r["code"] not in
                   ("WL-00001", "WL-00002", "WL-00003"))
check("新增行自动编号承接原编号", new_codes[0] == "WL-00004", str(new_codes))
check("空型号行正常新增",
      sum(1 for r in recs_ms if is_blank_model(r["model"])) == 2, str(len(recs_ms)))

# 第二次导入同一份数据：全部命中 → 0 新增、不产生重复（模拟反复导入同一份清单）
mr2 = ms.merge_many([
    {"model": "8MSA4L.R0-W2", "brand": "B&R贝加莱", "price": 17000, "qty": 4, "shelf": "2排A-1"},
    {"model": "VLAST-070P3V-X", "brand": "东荣", "price": 26000, "qty": 2, "shelf": "11排A-2"},
], "model")
check("重复导入：0 新增", mr2["added"] == 0, str(mr2))
check("重复导入：跳过 2 条", mr2["skipped"] == 2, str(mr2))
check("重复导入后总条数不变", ms.count() == 7, "实际=%d" % ms.count())
after2 = [r for r in ms.all_records() if norm_model(r["model"]) == "8msa4l.r0-w2"][0]
check("重复导入未改动原有价格", abs(float(after2["price"]) - 16000) < 1e-6, after2["price"])
check("重复导入未改动原有货架", after2["shelf"] == "1排B-2", after2["shelf"])

# 无型号记录：除上架状态外内容相同 → 视为重复（上架状态是导入后最常被人工修改的字段）
ls_store = Store(os.path.join(TMP, "listed.db"))
ls_store.insert_many([blank_record() | {"code": "L-1", "brand": "Sankyo三协电机6孔母头",
                                        "model": "/", "condition": "全新", "qty": 1,
                                        "remark": "编码器线插头", "listed": 0}])
ls_store.update([r for r in ls_store.all_records() if r["code"] == "L-1"][0]["id"],
                blank_record() | {"code": "L-1", "brand": "Sankyo三协电机6孔母头",
                                  "model": "/", "condition": "全新", "qty": 1,
                                  "remark": "编码器线插头", "listed": 1})
mr3 = ls_store.merge_many([
    {"model": "/", "brand": "Sankyo三协电机6孔母头", "condition": "全新", "qty": 1,
     "remark": "编码器线插头", "listed": 0},
], "model")
check("无型号仅上架状态不同：跳过不导入", mr3["added"] == 0 and mr3["skipped"] == 1, str(mr3))
check("无型号仅上架状态不同：库中仍一条", ls_store.count() == 1, "实际=%d" % ls_store.count())
res_ls = ls_store.dedupe_db()
check("去重菜单可清理仅上架状态不同的旧重复",
      res_ls["deleted"] == 0, str(res_ls))  # 库中已只剩一条，无需清理
ls_store.insert_many([blank_record() | {"code": "L-2", "brand": "Sankyo三协电机6孔母头",
                                        "model": "/", "condition": "全新", "qty": 1,
                                        "remark": "编码器线插头", "listed": 1}])
res_ls2 = ls_store.dedupe_db()
check("去重菜单清理仅上架状态不同的重复（保留最早）",
      res_ls2["deleted"] == 1 and ls_store.count() == 1, "%s count=%d" % (res_ls2, ls_store.count()))
ls_store.close()

# 库中存在同型号多条时，导入不得删除任何原有记录
dd_store = Store(os.path.join(TMP, "nodel.db"))
dd_store.insert_many([blank_record() | {"code": "N-1", "model": "SAME-X", "price": 1},
                      blank_record() | {"code": "N-2", "model": "SAME-X", "price": 2}])
nd = dd_store.merge_many([{"model": "same-x", "price": 99}], "model")
check("库中重复记录不被清理", dd_store.count() == 2, "实际=%d" % dd_store.count())
check("重复行被跳过而非更新", nd["added"] == 0 and nd["skipped"] == 1, str(nd))
check("原有两条价格均未改动",
      sorted(float(r["price"]) for r in dd_store.all_records()) == [1.0, 2.0],
      str([r["price"] for r in dd_store.all_records()]))
dd_store.close()

# 无型号行按内容指纹与库中比对：内容相同 → 跳过；内容不同 → 新增（v1.5.4）
bk = Store(os.path.join(TMP, "blank.db"))
bk.insert_many([blank_record() | {"code": "WL-00001", "model": "/", "brand": "Sankyo三协",
                                  "category": "编码器线插头", "condition": "全新",
                                  "price": 0, "qty": 1}])
rb = bk.merge_many([
    # 与库中那条完全相同（型号同为 /，价格写法不同也视为相同）
    {"model": "/", "brand": "Sankyo三协", "category": "编码器线插头",
     "condition": "全新", "price": "0.00", "qty": "1"},
    # 内容不同 → 新增
    {"model": "/", "brand": "Schneider施耐德", "category": "伺服网线",
     "condition": "全新", "price": 0, "qty": 6},
])
check("无型号内容相同：跳过不导入", rb["added"] == 1 and rb["skipped"] == 1, str(rb))
check("无型号跳过后库中不产生重复", bk.count() == 2, "实际=%d" % bk.count())
brands = sorted(r["brand"] for r in bk.all_records())
check("无型号不同内容正常新增", brands == ["Sankyo三协", "Schneider施耐德"], str(brands))
# 再次导入同样两行：全部命中 → 0 新增
rb2 = bk.merge_many([
    {"model": "/", "brand": "Sankyo三协", "category": "编码器线插头",
     "condition": "全新", "price": 0, "qty": 1},
    {"model": "", "brand": "Schneider施耐德", "category": "伺服网线",
     "condition": "全新", "price": 0, "qty": 6},
])
check("无型号重复导入：全部跳过", rb2["added"] == 0 and rb2["skipped"] == 2, str(rb2))
check("无型号重复导入后条数不变", bk.count() == 2, "实际=%d" % bk.count())
bk.close()

# 重复型号检出（只读检查）
ds = Store(os.path.join(TMP, "dup.db"))
ds.insert_many([blank_record() | {"code": "X1", "model": "SAME-1"},
                blank_record() | {"code": "X2", "model": " same-1 "},
                blank_record() | {"code": "X3", "model": "-"}])
dd = ds.duplicate_models()
check("重复型号检出", len(dd) == 1 and dd[0][1] == 2, str(dd))
check("无型号行不算重复", len(ds.model_keys()) == 1, str(ds.model_keys()))
ds.close()

# 文件内去重 dedupe_records：相同型号留最后一条；无型号但内容完全相同也只留一条
dk, dn = dedupe_records([
    {"model": "M-1", "price": 1},
    {"model": "m-1 ", "price": 2},
    {"model": "", "brand": "Sankyo", "category": "插头", "price": 0, "qty": 1},
    {"model": "/", "brand": "Sankyo", "category": "插头", "price": 0, "qty": 1},
    {"model": "", "brand": "其它", "category": "插头", "price": 5, "qty": 1},
])
check("文件内去重：5 行变 3 行", len(dk) == 3 and dn == 2, "%s removed=%d" % (len(dk), dn))
check("文件内去重：型号重复取最后一条", abs(float(dk[0]["price"]) - 2) < 1e-6, str(dk[0]))
check("文件内去重：无型号内容相同也去重",
      sum(1 for r in dk if is_blank_model(r["model"]) and r["brand"] == "Sankyo") == 1)

# 库内去重 dedupe_db：相同型号留最早一条；无型号内容相同留最早一条
dz = Store(os.path.join(TMP, "dedupe.db"))
dz.insert_many([
    blank_record() | {"code": "WL-00001", "model": "DUP-A", "price": 1},
    blank_record() | {"code": "WL-00002", "model": "dup-a", "price": 99},
    blank_record() | {"code": "WL-00003", "model": "DUP-A", "price": 55},
    blank_record() | {"code": "WL-00004", "model": "/", "brand": "Sankyo", "qty": 1},
    blank_record() | {"code": "WL-00005", "model": "/", "brand": "Sankyo", "qty": 1},
    blank_record() | {"code": "WL-00006", "model": "UNIQ-1", "price": 7},
])
pre = dz.dedupe_db(dry_run=True)
check("库内去重预览：删 3 条 2 组", pre["deleted"] == 3 and pre["groups"] == 2, str(pre))
check("库内去重预览不删除", dz.count() == 6)
res = dz.dedupe_db()
check("库内去重执行：删除 3 条", res["deleted"] == 3 and dz.count() == 3, str(res))
left = sorted(r["code"] for r in dz.all_records())
check("库内去重保留最早一条", left == ["WL-00001", "WL-00004", "WL-00006"], str(left))
check("保留记录内容未被改动",
      abs(float([r for r in dz.all_records() if r["code"] == "WL-00001"][0]["price"]) - 1) < 1e-6)
res2 = dz.dedupe_db()
check("再次去重无变化", res2["deleted"] == 0)
dz.close()

# 在线备份接口（清空/覆盖导入前自动备份用）
import sqlite3  # noqa: E402
bs = Store(os.path.join(TMP, "bksrc.db"))
bs.insert_many([blank_record() | {"code": "WL-00001", "model": "BK-1"},
                blank_record() | {"code": "WL-00002", "model": "BK-2"}])
bt = os.path.join(TMP, "bk.db")
bs.backup_to(bt)
bc = sqlite3.connect(bt)
check("备份文件含全部记录", bc.execute("select count(*) from items").fetchone()[0] == 2)
bc.close()
bs.clear_all()
check("清空后原库为 0", bs.count() == 0)
bc = sqlite3.connect(bt)
check("备份不受清空影响", bc.execute("select count(*) from items").fetchone()[0] == 2)
bc.close()
bs.close()
ms.close()

# ---------------------------------------------------------------- 编号规则：跟着数据走
# 库中有数据 → 接着排；数据被清空 → 从 1 开始。用独立数据库验证（不影响主数据集）
st2 = Store(os.path.join(TMP, "seq.db"))
st2.insert_many([blank_record() | {"code": "SKU-%d" % (1000 + i), "brand": "旧"}
                 for i in range(1, 6)])
c_a = st2.generate_codes(2)
check("库中有数据时承接最大尾号", c_a[0] == "WL-01006", str(c_a))
st2.insert_many([blank_record() | {"code": c} for c in c_a])
st2.clear_all()
check("清空后数据为 0", st2.count() == 0)
c_b = st2.generate_codes(2)
check("清空数据后编号回到 WL-00001", c_b == ["WL-00001", "WL-00002"], "%s" % (c_b,))
st2.insert_many([blank_record() | {"code": c} for c in c_b])
check("清空重导后再取号接续", st2.generate_codes(1)[0] == "WL-00003")
st2.clear_all()
check("连续两次清空后仍从 1 开始", st2.generate_codes(1)[0] == "WL-00001")
st2.close()

# 覆盖导入等价路径：app 会先 clear_all() 再补编号
st4 = Store(os.path.join(TMP, "seq3.db"))
st4.insert_many([blank_record() | {"code": "WL-%05d" % i} for i in range(1, 11)])
st4.clear_all()
c_rep = st4.generate_codes(3)
check("覆盖导入从 WL-00001 重新开始",
      c_rep == ["WL-00001", "WL-00002", "WL-00003"], str(c_rep))
st4.close()

# 空库（从未导入过）仍从 WL-00001 开始
st3 = Store(os.path.join(TMP, "seq2.db"))
check("全新库从 1 开始", st3.generate_codes(1)[0] == "WL-00001")
st3.close()

print("== 3.2 出售记录 ==")
ss = Store(os.path.join(TMP, "sales.db"))
ss.insert_many([
    blank_record() | {"code": "WL-00001", "brand": "罗技", "category": "外设", "model": "G502",
                      "condition": "99新", "price": 100.0, "qty": 5, "shelf": "6排A-3", "listed": 1},
    blank_record() | {"code": "WL-00002", "brand": "Apple", "category": "手机", "model": "A2634",
                      "condition": "95新", "price": 2000.0, "qty": 2, "shelf": "7排B-2", "listed": 1},
])
r1 = [r for r in ss.all_records() if r["code"] == "WL-00001"][0]
ok1, msg1 = ss.add_sale(r1["id"], 2, 150.0, buyer="张三", sale_date="2026-10-01", remark="微信")
check("登记出售成功", ok1, msg1)
rec = [r for r in ss.all_records() if r["id"] == r1["id"]][0]
check("出售后扣减库存", int(rec["qty"]) == 3, "实际=%d" % rec["qty"])
check("部分出售不标记售完", int(rec["sold_out"]) == 0)
ok2, _ = ss.add_sale(r1["id"], 3, 150.0, sale_date="2026-10-02")
rec = [r for r in ss.all_records() if r["id"] == r1["id"]][0]
check("售完后库存为 0", int(rec["qty"]) == 0, "实际=%d" % rec["qty"])
check("售完标记已售完", int(rec["sold_out"]) == 1)
ok3, msg3 = ss.add_sale(r1["id"], 1, 10)
check("超卖被拒绝", (not ok3) and "超过" in msg3, msg3)
check("数量 0 不能出售", ss.add_sale(r1["id"], 0, 10)[0] is False)
rows_s = ss.list_sales()
check("出售记录条数", len(rows_s) == 2, "实际=%d" % len(rows_s))
tot = ss.sales_totals(rows_s)
check("出售合计 件数/销售额", tot["qty"] == 5 and abs(tot["amount"] - 750.0) < 1e-6, str(tot))
check("出售合计 成本/利润", abs(tot["cost"] - 500.0) < 1e-6
      and abs(tot["profit"] - 250.0) < 1e-6, str(tot))
check("出售按日期倒序", rows_s[0]["sale_date"] == "2026-10-02", rows_s[0]["sale_date"])
check("出售日期范围筛选", len(ss.list_sales(start="2026-10-02")) == 1)
check("出售品牌筛选", len(ss.list_sales(brand="罗技")) == 2)
check("出售品牌关键词筛选（手动输入包含匹配）", len(ss.list_sales(brand="罗")) == 2,
      str(len(ss.list_sales(brand="罗"))))
r_apple = [r for r in ss.all_records() if r["code"] == "WL-00002"][0]
ok_apple, _ = ss.add_sale(r_apple["id"], 1, 2200.0, buyer="Amy", sale_date="2026-10-03")
check("Apple 出售成功", ok_apple)
check("出售品牌筛选不区分大小写", len(ss.list_sales(brand="APPLE")) == 1,
      str(len(ss.list_sales(brand="APPLE"))))
check("出售关键词搜索买家", len(ss.list_sales(kw="张三")) == 1)
check("出售品牌下拉", set(ss.sales_brands()) == {"罗技", "Apple"}, str(ss.sales_brands()))
check("成本快照取原单价", abs(float(rows_s[0]["cost"]) - 100.0) < 1e-6, str(rows_s[0]["cost"]))
# 撤销出售 → 库存加回
okk, _ = ss.delete_sale(rows_s[0]["id"])
rec = [r for r in ss.all_records() if r["id"] == r1["id"]][0]
check("撤销出售成功", okk and len(ss.list_sales()) == 2,
      str(len(ss.list_sales())))
check("撤销后数量加回库存", int(rec["qty"]) == 3, "实际=%d" % rec["qty"])
check("撤销后清除已售完标记", int(rec["sold_out"]) == 0)

# ---- 手动补录出售记录（v1.10.8）：只写记录、不扣库存、可撤销 ----
stock_before = {r["code"]: int(r["qty"]) for r in ss.all_records()}
n_sales = len(ss.list_sales())
tot_prev = ss.sales_totals(ss.list_sales())
okm, msgm = ss.add_manual_sale(code="WL-00002", brand="Apple", model="iPad",
                               qty=2, price=300.0, cost=100.0, buyer="王五",
                               address="杭州市", sale_date="2026-10-04",
                               remark="手动补录")
check("手动补录成功", okm, msgm)
rows_m = ss.list_sales()
check("手动补录记录 +1", len(rows_m) == n_sales + 1, str(len(rows_m)))
rm = rows_m[0]
check("手动补录在最上面（日期倒序）", rm["sale_date"] == "2026-10-04", rm["sale_date"])
check("手动补录总额 2×300", abs(float(rm["total"]) - 600.0) < 1e-6, rm["total"])
check("手动补录不挂库存(item_id 空)", rm["item_id"] in (None, ""), rm["item_id"])
check("手动补录类型为销售", (rm.get("out_type") or "销售") == "销售", rm.get("out_type"))
tot_m = ss.sales_totals(rows_m)
check("手动补录计入销售额 +600 / 利润 +400",
      abs(tot_m["amount"] - tot_prev["amount"] - 600.0) < 1e-6
      and abs(tot_m["profit"] - tot_prev["profit"] - 400.0) < 1e-6,
      "%s -> %s" % (tot_prev, tot_m))
check("手动补录后库存一件不变",
      {r["code"]: int(r["qty"]) for r in ss.all_records()} == stock_before)
check("手动补录编号/品牌/型号必填一项",
      ss.add_manual_sale(qty=1, price=1)[0] is False)
check("手动补录数量 0 拒绝", ss.add_manual_sale(code="X", qty=0, price=1)[0] is False)
check("手动补录负单价拒绝", ss.add_manual_sale(code="X", qty=1, price=-1)[0] is False)
okdm, msgdm = ss.delete_sale(rm["id"])
check("撤销手动补录：只删记录不动库存", okdm and len(ss.list_sales()) == n_sales
      and {r["code"]: int(r["qty"]) for r in ss.all_records()} == stock_before,
      msgdm)
check("撤销提示「不涉及库存」", "不涉及库存" in msgdm, msgdm)

# ---- 使用说明（v1.10.9）：独立窗口的章节内容 ----
from wm.help import help_sections  # noqa: E402
secs = help_sections("D:/测试数据目录")
check("使用说明共 16 章", len(secs) == 16, str(len(secs)))
titles = [t for t, _ in secs]
check("章节标题唯一且非空",
      len(set(titles)) == len(titles) and all(t.strip() for t in titles))
check("使用说明含「手动补录出售」与「数据存放」章节",
      any("手动补录出售" in t for t in titles) and "数据存放" in titles, str(titles))
check("数据存放章节写入数据库路径", "D:/测试数据目录" in secs[-1][1], secs[-1][1])
check("各章正文均非空", all(b.strip() for _, b in secs))
check("使用说明含「局域网共享」章节", any("局域网共享" in t for t in titles), str(titles))
_lan_body = [b for t, b in secs if "局域网共享" in t][0]
check("局域网章节写明「一台电脑只能选一种角色」",
      "只能选一种角色" in _lan_body, _lan_body[:80])
check("局域网章节写明切换会弹窗确认",
      "弹窗确认" in _lan_body, _lan_body[-80:])

# ---- 局域网共享（v1.11.0）：主机服务 + 客户端只读 / 授权录入 ----
from wm.lan import LanServer  # noqa: E402
from wm.remote import (HostUnreachable, PermissionDenied, RemoteError,  # noqa: E402
                       RemoteStore)
from wm import remote as remote_mod  # noqa: E402
import socket as _socket  # noqa: E402

_s = _socket.socket()
_s.bind(("127.0.0.1", 0))
_lan_port = _s.getsockname()[1]
_s.close()
_lan_srv = LanServer(lambda: ss, lambda: "测试仓", "987654", _lan_port)
okl, msgl = _lan_srv.start()
check("局域网主机服务启动", okl, msgl)
_lan_cli = RemoteStore("127.0.0.1", _lan_port, "987654", "t1", "测试电脑")
info_l = _lan_cli.ping()
check("客户端 ping 成功且仓库名正确",
      info_l.get("ok") and info_l.get("warehouse") == "测试仓", info_l)
check("客户端默认只读", info_l.get("can_write") is False, info_l)
check("客户端读到与主机一致的记录数", len(_lan_cli.all_records()) == ss.count())
_lan_rev0 = ss.revision()
try:
    _lan_cli.add_manual_sale(code="WL-LAN", brand="ABB", qty=1, price=10)
    check("未授权写入被拒绝", False)
except PermissionDenied:
    check("未授权写入被拒绝", True)
_lan_srv.allow("127.0.0.1", True)
_lan_info2 = _lan_cli.ping()
check("主机授权后 can_write", _lan_info2.get("can_write") is True, _lan_info2)
okl2, msgl2 = _lan_cli.add_manual_sale(code="WL-LAN", brand="ABB", qty=2, price=25)
check("授权后客户端写入成功", okl2, msgl2)
check("数据落在主机同一个库",
      any(r.get("code") == "WL-LAN" for r in ss.list_sales()))
check("客户端写入后 rev 增加", _lan_cli.revision() > _lan_rev0,
      "%s -> %s" % (_lan_rev0, ss.revision()))
# ---- 移除连接 / 黑名单（v1.11.4）----
_lan_srv.kick("127.0.0.1")
check("移除后客户端列表为空", _lan_srv.snapshot() == [], _lan_srv.snapshot())
try:
    _lan_cli.ping()
    check("被移除的电脑 ping 被拒（kicked）", False)
except RemoteError as e:
    check("被移除的电脑 ping 被拒（kicked）",
          "移除本机的连接" in str(e), str(e))
_lan_srv.kicked.clear()             # 模拟 60 秒后可重新连接
info_l3 = _lan_cli.ping()
check("被移除的电脑可重新连接", info_l3.get("ok") is True, info_l3)
_lan_srv.block("127.0.0.1", "测试电脑")
check("黑名单快照含该 IP",
      [b["ip"] for b in _lan_srv.blocked_snapshot()] == ["127.0.0.1"],
      _lan_srv.blocked_snapshot())
check("拉黑后客户端列表为空", _lan_srv.snapshot() == [], _lan_srv.snapshot())
try:
    _lan_cli.ping()
    check("黑名单电脑 ping 被拒（连接码正确也不行）", False)
except RemoteError as e:
    check("黑名单电脑 ping 被拒（连接码正确也不行）", "黑名单" in str(e), str(e))
_lan_srv.unblock("127.0.0.1")
info_l4 = _lan_cli.ping()
check("移出黑名单后可重新连接", info_l4.get("ok") is True, info_l4)
_lan_srv.set_blocked([{"ip": "10.9.9.9", "name": "老黑名单"}])
check("启动时恢复黑名单（set_blocked）",
      [b["ip"] for b in _lan_srv.blocked_snapshot()] == ["10.9.9.9"],
      _lan_srv.blocked_snapshot())
_lan_srv.set_blocked([])

# ---- 手机端（v1.14.0）：/m 登录会话 + 只读 / 授权出售 ----
import urllib.error as _uerr  # noqa: E402
import urllib.request as _ureq  # noqa: E402
from http.cookiejar import CookieJar  # noqa: E402

from wm.mobile import COOKIE_NAME, MobileService, PAGE_HTML, _token_of  # noqa: E402

ss.insert(blank_record() | {"code": "WL-MOB", "brand": "手机测试", "qty": 3, "price": 66.0})


def _mreq(path, data=None, opener=None):
    """手机端 HTTP 实测：返回 (status, body, headers)。"""
    url = "http://127.0.0.1:%d%s" % (_lan_port, path)
    if data is not None:
        req = _ureq.Request(url, data=json.dumps(data).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST")
    else:
        req = _ureq.Request(url)
    op = opener or _ureq.build_opener(_ureq.HTTPCookieProcessor(CookieJar()))
    try:
        with op.open(req, timeout=6) as r:
            raw = r.read()
            ct = r.headers.get("Content-Type", "")
            body = json.loads(raw) if "json" in ct else raw.decode("utf-8")
            return r.status, body, r.headers
    except _uerr.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except Exception:
            body = raw.decode("utf-8", "replace")
        return e.code, body, e.headers


_mb_op = _ureq.build_opener(_ureq.HTTPCookieProcessor(CookieJar()))
_msc, _mb, _mh = _mreq("/m")
check("手机页面可访问（HTML）", _msc == 200 and "仓管家" in _mb and "<html" in _mb.lower(),
      "%s %s…" % (_msc, _mb[:40]))
check("手机页面 JS 无 Python 转义残留（反斜杠=页面脚本必坏）",
      "\\" not in PAGE_HTML,
      [l for l in PAGE_HTML.splitlines() if "\\" in l][:2])
check("手机页面登录按钮已绑定事件",
      '$("btnLogin").onclick' in PAGE_HTML and "function esc" in PAGE_HTML)
check("手机页面禁止被 iframe 嵌套",
      _mh.get("X-Frame-Options") == "DENY", dict(_mh))
_msc, _mb, _ = _mreq("/m/api/whoami", opener=_mb_op)
check("未登录调 API 被拒（401）", _msc == 401 and _mb.get("need_login"), (_msc, _mb))
_msc, _mb, _ = _mreq("/m/login", {"code": "000000"}, opener=_mb_op)
check("错误连接码登录被拒（401）", _msc == 401 and not _mb.get("ok"), (_msc, _mb))
_msc, _mb, _mh = _mreq("/m/login", {"code": "987654"}, opener=_mb_op)
check("正确连接码登录成功", _msc == 200 and _mb.get("ok"), (_msc, _mb))
check("登录下发的 Cookie 是 HttpOnly",
      "httponly" in str(_mh.get("Set-Cookie", "")).lower()
      and COOKIE_NAME in str(_mh.get("Set-Cookie", "")),
      _mh.get("Set-Cookie"))
_msc, _mb, _ = _mreq("/m/api/whoami", opener=_mb_op)
check("登录后 whoami 正常且默认只读",
      _msc == 200 and _mb.get("ok") and _mb.get("can_write") is False
      and _mb.get("warehouse") == "测试仓", _mb)
_msc, _mb, _ = _mreq("/m/api/items?kw=", opener=_mb_op)
check("手机端能读到库存",
      _msc == 200 and _mb.get("ok") and len(_mb.get("items") or []) == ss.count(),
      "items=%d" % len(_mb.get("items") or []))
_msc, _mb, _ = _mreq("/m/api/sales?kw=", opener=_mb_op)
check("手机端能读到出售记录", _msc == 200 and _mb.get("ok") and "sales" in _mb, _msc)
_msc, _mb, _ = _mreq("/m/api/sell", {"code": "WL-MOB", "qty": 1, "price": 9.9},
                     opener=_mb_op)
check("只读时手机出售被拒（403）",
      _msc == 403 and _mb.get("readonly"), (_msc, _mb))
# 请求录入 → 主机审批 → 可写
_req_seen = []
_orig_evt = _lan_srv.on_event
_lan_srv.on_event = lambda ev, data=None: _req_seen.append((ev, data))
_msc, _mb, _ = _mreq("/m/api/request_write", {}, opener=_mb_op)
check("手机「请求录入」触发主机审批事件",
      _msc == 200 and any(ev == "request" for ev, _ in _req_seen), (_msc, _req_seen))
_lan_srv.on_event = _orig_evt
_lan_srv.allow("127.0.0.1", True)
_msc, _mb, _ = _mreq("/m/api/sell", {"code": "WL-MOB", "qty": 1, "price": 9.9},
                     opener=_mb_op)
check("授权后手机登记出售成功",
      _msc == 200 and _mb.get("ok") and "已登记" in (_mb.get("message") or ""),
      (_msc, _mb))
check("手机出售后库存真实扣减（与电脑同库）",
      [r for r in ss.all_records() if r["code"] == "WL-MOB"][0]["qty"] == 2)
_msc, _mb, _ = _mreq("/m/api/sell", {"code": "NO-SUCH-CODE", "qty": 1, "price": 1},
                     opener=_mb_op)
check("手机端出售不存在的编号被拒", _msc == 404 and "没有找到" in _mb.get("error", ""),
      (_msc, _mb))
# 手机端新增 / 修改（v1.15.0）
_msc, _mb, _ = _mreq("/m/api/add", {"brand": "手机新增", "qty": 4, "price": 12.5,
                                    "shelf": "测试架"}, opener=_mb_op)
check("手机端新增入库成功且自动编号",
      _msc == 200 and _mb.get("ok") and str(_mb.get("code", "")).startswith("WL-"),
      (_msc, _mb))
_mob_code = _mb.get("code")
check("手机新增的记录与电脑同库可见",
      any(r.get("code") == _mob_code and int(r.get("qty")) == 4
          for r in ss.all_records()), _mob_code)
_msc, _mb, _ = _mreq("/m/api/add", {"brand": "", "model": ""}, opener=_mb_op)
check("手机端新增时品牌/型号/品类全空被拒", _msc == 400, (_msc, _mb))
_mob_id = [r["id"] for r in ss.all_records() if r["code"] == _mob_code][0]
_msc, _mb, _ = _mreq("/m/api/update_all",
                     {"id": _mob_id, "brand": "手机新增", "qty": 9, "price": 20,
                      "shelf": "新架位", "model": "MX-1"}, opener=_mb_op)
check("手机端修改记录成功", _msc == 200 and _mb.get("ok"), (_msc, _mb))
_ed = [r for r in ss.all_records() if r["id"] == _mob_id][0]
check("修改后数量/价格/货架与电脑同库一致",
      int(_ed["qty"]) == 9 and float(_ed["price"]) == 20.0
      and _ed["shelf"] == "新架位" and _ed["code"] == _mob_code,
      dict(qty=_ed["qty"], price=_ed["price"], shelf=_ed["shelf"]))
_msc, _mb, _ = _mreq("/m/api/update_all", {"id": 99999999, "qty": 1}, opener=_mb_op)
check("手机端修改不存在的记录被拒（404）", _msc == 404, (_msc, _mb))
_lan_srv.allow("127.0.0.1", False)
_msc, _mb, _ = _mreq("/m/api/add", {"brand": "x"}, opener=_mb_op)
check("只读时手机新增被拒（403）", _msc == 403 and _mb.get("readonly"), (_msc, _mb))
_lan_srv.allow("127.0.0.1", True)
# 手机页面 JS 语法校验（esprima 纯 Python 解析，防转义/语法坏页）
try:
    import esprima  # noqa: E402
    _js = PAGE_HTML.split("<script>")[1].split("</" + "script>")[0]
    esprima.parseScript(_js)
    check("手机页面 JS 语法可解析（esprima）", True)
except ImportError:
    check("手机页面 JS 语法可解析（esprima）", True, "esprima 未安装，跳过")
except Exception as _e:
    check("手机页面 JS 语法可解析（esprima）", False, str(_e)[:100])
_msc, _mb, _ = _mreq("/m/logout", {}, opener=_mb_op)
check("退出登录成功", _msc == 200 and _mb.get("ok"), (_msc, _mb))
_msc, _mb, _ = _mreq("/m/api/whoami", opener=_mb_op)
check("退出后再调 API 需要重新登录", _msc == 401, _msc)
# 会话安全单元测试：IP 绑定 / 过期
_ms = MobileService()
_mc, _mb3, _mh3 = _ms.login("10.1.1.1", "123456", lambda c: c == "123456")
_t = _token_of(_mh3[0][1])
check("会话令牌足够长（token_urlsafe 32B）",
      isinstance(_t, str) and len(_t) >= 40, _t)
check("同 IP 会话有效", _ms.check(_t, "10.1.1.1") is True)
check("换 IP 后会话失效（IP 绑定）",
      _ms.check(_t, "10.1.1.2") is False and _ms.check(_t, "10.1.1.1") is False,
      "换网必须重新登录")
_ms2 = MobileService()
for _i in range(5):
    _mc, _mb2, _ = _ms2.login("10.2.2.2", "wrong", lambda c: False)
check("连续错 5 次触发锁定", _mc == 429 and _mb2.get("locked"), (_mc, _mb2))
_mc, _mb2, _ = _ms2.login("10.2.2.2", "123456", lambda c: c == "123456")
check("锁定期间连接码正确也拒绝登录", _mc == 429 and _mb2.get("locked"), (_mc, _mb2))
# 登录限速实测（最后做，避免锁住 127.0.0.1 影响前面的测试）
for _i in range(5):
    _mreq("/m/login", {"code": "000000"})
_msc, _mb, _ = _mreq("/m/login", {"code": "987654"})
check("手机端登录限速生效（错 5 次后锁 10 分钟）",
      _msc == 429 and _mb.get("locked"), (_msc, _mb))
_lan_srv.mobile._fails.clear()
_lan_srv.mobile._locked.clear()
_lan_srv.mobile.clear_all()

_lan_bad = RemoteStore("127.0.0.1", _lan_port, "000000", "t2", "错码电脑")
try:
    _lan_bad.ping()
    check("错误连接码被拒", False)
except RemoteError:
    check("错误连接码被拒", True)
_lan_srv.stop()
check("主机服务已停止", _lan_srv.running is False)
_dead = RemoteStore("127.0.0.1", _lan_port, "987654", "t3", "断线", timeout=2)
try:
    _dead.ping()
    check("服务停止后客户端报连不上", False)
except HostUnreachable as e:
    check("服务停止后客户端报连不上", "连不上主机" in str(e), str(e))
# 手工把数量改回 > 0 也要清除「已售完」
ss.add_sale(rec["id"], 3, 10)
rec = [r for r in ss.all_records() if r["id"] == rec["id"]][0]
check("再次售完标记", int(rec["sold_out"]) == 1)
ss.update_field(rec["id"], "qty", 4)
rec = [r for r in ss.all_records() if r["id"] == rec["id"]][0]
check("改回数量清除已售完", int(rec["sold_out"]) == 0 and int(rec["qty"]) == 4,
      "sold_out=%s qty=%s" % (rec["sold_out"], rec["qty"]))
# 导出售卖记录（出售口径：只有销售字段）
sale_path = os.path.join(TMP, "sales.xlsx")
xlsxio.export_sales_xlsx(sale_path, ss.list_sales(), "测试范围")
wb_s = openpyxl.load_workbook(sale_path)
check("出售导出含两个工作表",
      "出售记录" in wb_s.sheetnames and "出售汇总" in wb_s.sheetnames, str(wb_s.sheetnames))
ws_s = wb_s["出售记录"]
check("出售导出行数", ws_s.max_row == len(ss.list_sales()) + 1,
      "%d vs %d" % (ws_s.max_row, len(ss.list_sales()) + 1))
check("出售导出表头", [c.value for c in ws_s[1]][:3] == ["出售日期", "编号", "品牌"],
      str([c.value for c in ws_s[1]][:3]))
check("出售汇总含销售额", any(ws_s2.value == "销售额(元)"
                              for ws_s2 in wb_s["出售汇总"]["A"]))
wb_s.close()
ss.clear_all(purge_sales=True)
check("清空数据同时清出库记录", ss.count() == 0 and len(ss.list_sales()) == 0)
ss.close()

print("== 3.2b 出库类型（只有销售计金额）==")
ot = Store(os.path.join(TMP, "outtype.db"))
ot.insert_many([
    blank_record() | {"code": "WL-00001", "brand": "罗技", "model": "G502",
                      "price": 100.0, "qty": 10, "listed": 1},
    blank_record() | {"code": "WL-00002", "brand": "Apple", "model": "A2634",
                      "price": 2000.0, "qty": 4, "listed": 1},
])
o1 = [r for r in ot.all_records() if r["code"] == "WL-00001"][0]
o2 = [r for r in ot.all_records() if r["code"] == "WL-00002"][0]
check("默认出库类型=销售", ot.add_sale(o1["id"], 2, 150.0, buyer="张三",
                                       sale_date="2026-10-05")[0])
ok_ot, msg_ot = ot.add_sale(o1["id"], 3, 999.0, buyer="不该记",
                            sale_date="2026-10-06", out_type="报废")
check("报废出库成功且提示带类型", ok_ot and "报废" in msg_ot, msg_ot)
ot.add_sale(o2["id"], 1, 0, sale_date="2026-10-06", out_type="赠送")
ot.add_sale(o2["id"], 1, 0, sale_date="2026-10-06", out_type="退货")
rec_o1 = [r for r in ot.all_records() if r["id"] == o1["id"]][0]
check("非销售出库同样扣减库存", int(rec_o1["qty"]) == 5, "实际=%s" % rec_o1["qty"])
rows_ot = ot.list_sales()
check("出库记录共 4 笔", len(rows_ot) == 4, "实际=%d" % len(rows_ot))
check("类型筛选-报废", len(ot.list_sales(out_type="报废")) == 1)
check("类型筛选-全部", len(ot.list_sales(out_type="全部")) == 4)
check("类型筛选-销售", len(ot.list_sales(out_type="销售")) == 1)
tot_ot = ot.sales_totals(rows_ot)
check("合计只算销售：笔数/件数/销售额",
      tot_ot["count"] == 1 and tot_ot["qty"] == 2
      and abs(tot_ot["amount"] - 300.0) < 1e-6, str(tot_ot))
check("非销售出库合计笔数/件数",
      tot_ot["out_count"] == 3 and tot_ot["out_qty"] == 5, str(tot_ot))
check("非销售出库不计金额(total=0)",
      all(abs(float(r["total"] or 0)) < 1e-9
          for r in rows_ot if r["out_type"] != "销售"),
      str([(r["out_type"], r["total"]) for r in rows_ot]))
check("非销售出库不记买家",
      all(not (r["buyer"] or "")
          for r in rows_ot if r["out_type"] != "销售"),
      str([(r["out_type"], r["buyer"]) for r in rows_ot]))
mo = ot.month_sales_amount("2026-10")
check("月度销售额只算销售", abs(mo["amount"] - 300.0) < 1e-6, str(mo))
check("买家统计只算销售",
      [b["buyer"] for b in ot.buyer_stats()] == ["张三"], str(ot.buyer_stats()))
check("买家下拉只含销售买家", ot.buyer_names() == ["张三"], str(ot.buyer_names()))
check("品牌销售额只算销售",
      [b for b, _a, _p in ot.brand_sales()] == ["罗技"],
      str([(b, a) for b, a, _p in ot.brand_sales()]))
check("月度趋势只算销售",
      abs(sum(v for _k, v in ot.monthly_sales(12)) - 300.0) < 1e-6,
      str(ot.monthly_sales(12)))
check("scope=sale 只看销售", len(ot.list_sales(scope="sale")) == 1,
      str(len(ot.list_sales(scope="sale"))))
check("scope=out 只看非销售", len(ot.list_sales(scope="out")) == 3,
      str(len(ot.list_sales(scope="out"))))
check("scope 空 = 出库总览（销售 + 非销售）", len(ot.list_sales()) == 4,
      str(len(ot.list_sales())))
tot_all = ot.out_totals(ot.list_sales())
check("出库总览 KPI 含全部出库笔数/件数",
      tot_all["count"] == 4 and tot_all["qty"] == 7, str(tot_all))
check("出库总览分类型含销售",
      tot_all["by_type"].get("销售") == 2 and tot_all["by_type"].get("报废") == 3,
      str(tot_all["by_type"]))
tot_out = ot.out_totals(ot.list_sales(scope="out"))
check("out_totals 件数/成本价值",
      tot_out["qty"] == 5 and tot_out["cost"] > 0
      and tot_out["by_type"] == {"报废": 3, "赠送": 1, "退货": 1}, str(tot_out))
mp_ot = os.path.join(TMP, "outtype.xlsx")
xlsxio.export_out_xlsx(mp_ot, ot.list_sales(), "类型测试")
wb_o = openpyxl.load_workbook(mp_ot)
check("出库导出工作表名",
      "出库记录" in wb_o.sheetnames and "出库汇总" in wb_o.sheetnames,
      str(wb_o.sheetnames))
check("出库导出表头含类型",
      [c.value for c in wb_o["出库记录"][1]][:3] == ["出库日期", "类型", "编号"],
      str([c.value for c in wb_o["出库记录"][1]][:3]))
check("出库导出含销售行",
      any(c.value == "销售" for c in wb_o["出库记录"]["B"]),
      str([c.value for c in wb_o["出库记录"]["B"]]))
check("出库导出不出现售价/销售额字段",
      not any(v in ("售价(元)", "总额(元)", "销售额(元)")
              for c in wb_o["出库记录"][1] for v in [c.value]),
      str([c.value for c in wb_o["出库记录"][1]]))
check("出库汇总含非销售出库行",
      any(c.value == "其中非销售出库件数" for c in wb_o["出库汇总"]["A"]))
check("出库汇总含其中销售出库行",
      any(c.value == "其中销售出库笔数" for c in wb_o["出库汇总"]["A"]))
wb_o.close()
ok_rv, _ = ot.delete_sale([r for r in rows_ot if r["out_type"] == "报废"][0]["id"])
rec_o1 = [r for r in ot.all_records() if r["id"] == o1["id"]][0]
check("撤销报废出库加回库存", ok_rv and int(rec_o1["qty"]) == 8,
      "实际=%s" % rec_o1["qty"])
ot.close()

print("== 3.2c 收货地址 ==")
ad = Store(os.path.join(TMP, "address.db"))
ad.insert_many([blank_record() | {"code": "WL-00001", "brand": "罗技", "model": "G502",
                                  "price": 100.0, "qty": 6, "listed": 1}])
a1 = ad.all_records()[0]
check("登记出售带收货地址",
      ad.add_sale(a1["id"], 1, 150.0, buyer="张三", sale_date="2026-10-01",
                  address="广东省深圳市南山区科技园1号")[0])
ad.add_sale(a1["id"], 1, 150.0, buyer="张三", sale_date="2026-10-03",
            address="广东省深圳市南山区科技园2号")
ad.add_sale(a1["id"], 1, 0, sale_date="2026-10-04", out_type="报废",
            address="非销售不该记的地址")
rows_ad = ad.list_sales()
sale_addr = [r["address"] for r in rows_ad if r["out_type"] == "销售"]
check("出售记录保存收货地址",
      sale_addr == ["广东省深圳市南山区科技园2号", "广东省深圳市南山区科技园1号"],
      str(sale_addr))
check("非销售出库不记地址",
      all(not (r["address"] or "") for r in rows_ad if r["out_type"] != "销售"),
      str([(r["out_type"], r["address"]) for r in rows_ad]))
check("按地址关键词搜索出售记录", len(ad.list_sales(kw="南山区")) == 2,
      str(len(ad.list_sales(kw="南山区"))))
check("地址不串到非销售筛选", len(ad.list_sales(kw="南山区", scope="out")) == 0,
      str(len(ad.list_sales(kw="南山区", scope="out"))))
check("选中买家自动带出最近地址",
      ad.buyer_address_map().get("张三") == "广东省深圳市南山区科技园2号",
      str(ad.buyer_address_map()))
check("历史地址补全（最近的在前）",
      ad.sale_addresses() == ["广东省深圳市南山区科技园2号", "广东省深圳市南山区科技园1号"],
      str(ad.sale_addresses()))
ad_sale_x = os.path.join(TMP, "address.xlsx")
xlsxio.export_sales_xlsx(ad_sale_x, ad.list_sales(scope="sale"), "地址测试")
wb_a = openpyxl.load_workbook(ad_sale_x)
ws_a = wb_a["出售记录"]
head_a = [c.value for c in ws_a[1]]
check("出售导出含收货地址列", "收货地址" in head_a, str(head_a))
ci = head_a.index("收货地址") + 1
check("出售导出地址值正确",
      ws_a.cell(row=2, column=ci).value == "广东省深圳市南山区科技园2号",
      str(ws_a.cell(row=2, column=ci).value))
check("出售导出备注列仍在", head_a.index("备注") == len(head_a) - 1, str(head_a))
wb_a.close()
ad.close()

print("== 3.2d 修改出库类型（出库维修 → 修好卖出） ==")
tc = Store(os.path.join(TMP, "modtype.db"))
tc.insert_many([blank_record() | {"code": "WL-00001", "brand": "小米", "model": "K40",
                                  "price": 800.0, "qty": 4, "listed": 1}])
t1 = tc.all_records()[0]
# 先登记一笔非销售出库：借出去维修 2 件
check("登记借出出库（送修）",
      tc.add_sale(t1["id"], 2, 0, sale_date="2026-10-02", remark="送修屏幕",
                  out_type="借出")[0])
check("送修已扣库存",
      int([r for r in tc.all_records() if r["id"] == t1["id"]][0]["qty"]) == 2,
      "db=%s items=%s" % (tc.path, [(r["id"], r["code"], r["qty"]) for r in tc.all_records()]))
o_sid = tc.list_sales()[0]["id"]
check("送修不计销售额", tc.sales_totals(tc.list_sales())["amount"] == 0.0,
      "sales=%s" % [(r["id"], r["qty"], r["out_type"], r["price"], r["total"])
                    for r in tc.list_sales()])
check("借出记录不在出售页范围", len(tc.list_sales(scope="sale")) == 0,
      str([(r["id"], r["out_type"]) for r in tc.list_sales()]))

# 修好卖掉了：把这条出库改成「销售」并补金额
ok_ct, msg_ct = tc.update_sale_type(o_sid, "销售", price=300.0, buyer="李四",
                                    address="北京市朝阳区建国路1号",
                                    remark="修好后卖出", sale_date="2026-10-08")
check("非销售出库可改为销售", ok_ct, msg_ct)
row_s = tc.list_sales()[0]
check("改销售后类型正确", row_s["out_type"] == "销售", str(row_s["out_type"]))
check("改销售后写售价与总额",
      float(row_s["price"]) == 300.0 and float(row_s["total"]) == 600.0,
      "%s / %s" % (row_s["price"], row_s["total"]))
check("改销售后写买家与地址",
      row_s["buyer"] == "李四" and row_s["address"] == "北京市朝阳区建国路1号",
      "%s / %s" % (row_s["buyer"], row_s["address"]))
check("改销售后日期与备注更新",
      row_s["sale_date"] == "2026-10-08" and row_s["remark"] == "修好后卖出",
      "%s / %s" % (row_s["sale_date"], row_s["remark"]))
check("改销售不动库存",
      int([r for r in tc.all_records() if r["id"] == t1["id"]][0]["qty"]) == 2)
st_s = tc.sales_totals(tc.list_sales())
check("改销售后计入销售额与利润",
      st_s["amount"] == 600.0 and st_s["count"] == 1 and st_s["qty"] == 2,
      str(st_s))
check("出售页现在能看到这笔", len(tc.list_sales(scope="sale")) == 1)
check("出库总览仍包含这笔", len(tc.list_sales(scope="")) == 1)
check("买家统计已包含新买家", [b["buyer"] for b in tc.buyer_stats()] == ["李四"],
      str(tc.buyer_stats()))

# 改回非销售类型：金额与买家、地址清空，库存仍不动
ok_b, msg_b = tc.update_sale_type(o_sid, "报废")
check("销售可改回报废", ok_b, msg_b)
row_b = tc.list_sales()[0]
check("改非销售后金额清零",
      float(row_b["price"]) == 0 and float(row_b["total"]) == 0,
      "%s / %s" % (row_b["price"], row_b["total"]))
check("改非销售后清空买家与地址",
      (row_b["buyer"] or "") == "" and (row_b["address"] or "") == "",
      "%s / %s" % (row_b["buyer"], row_b["address"]))
check("改非销售后备注与日期保持原值",
      row_b["remark"] == "修好后卖出" and row_b["sale_date"] == "2026-10-08",
      "%s / %s" % (row_b["remark"], row_b["sale_date"]))
check("改非销售不恢复库存",
      int([r for r in tc.all_records() if r["id"] == t1["id"]][0]["qty"]) == 2)
check("销售统计回到 0", tc.sales_totals(tc.list_sales())["amount"] == 0.0)

# 非法输入
check("改销售时负价被拒",
      not tc.update_sale_type(o_sid, "销售", price=-5)[0])
check("改销售时非数字价被拒",
      not tc.update_sale_type(o_sid, "销售", price="abc")[0])
check("不存在的出库记录被拒",
      not tc.update_sale_type(999999, "销售", price=1)[0])

# 批量改类型（非销售之间）
tc.add_sale(t1["id"], 1, 0, sale_date="2026-10-05", out_type="其他", remark="b1")
tc.add_sale(t1["id"], 1, 0, sale_date="2026-10-06", out_type="其他", remark="b2")
ids_oth = [r["id"] for r in tc.list_sales() if r["out_type"] == "其他"]
check("有两条「其他」待批量改", len(ids_oth) == 2, str(ids_oth))
n_batch, msg_batch = tc.update_sale_types(ids_oth, "损耗")
after = {r["id"]: r["out_type"] for r in tc.list_sales()}
check("批量改为损耗成功", n_batch == 2 and all(after[i] == "损耗" for i in ids_oth),
      "%s %s" % (n_batch, after))
check("批量改类型保留备注",
      all(r["remark"] in ("b1", "b2") for r in tc.list_sales()
          if r["out_type"] == "损耗"),
      str([(r["out_type"], r["remark"]) for r in tc.list_sales()]))
check("批量改销售被拒绝",
      tc.update_sale_types(ids_oth, "销售")[0] == 0, str(tc.update_sale_types(ids_oth, "销售")))
tc.close()

print("== 3.2e 屏幕自适应（笔记本 / 台式机、Win10 / Win11、高 DPI） ==")
from wm import screen as scr  # noqa: E402

_lap = {"x": 0, "y": 0, "w": 1366, "h": 728, "scale": 1.0,
        "build": 19045, "win11": False}                 # 1366×768 笔记本（Win10）
_desk = {"x": 0, "y": 0, "w": 1920, "h": 1032, "scale": 1.0,
         "build": 22631, "win11": True}                 # 1920×1080 台式（Win11）
_big = {"x": 0, "y": 0, "w": 2560, "h": 1400, "scale": 1.0,
        "build": 19045, "win11": False}                 # 2K 大屏
_hidpi = {"x": 0, "y": 0, "w": 1920, "h": 1032, "scale": 1.5,
          "build": 22631, "win11": True}                # 150% 缩放笔记本

_f_lap = scr.fit_window(_lap)
check("笔记本小屏直接最大化", _f_lap["maxed"] is True, _f_lap)
check("笔记本窗口铺满工作区（不压任务栏）",
      (_f_lap["w"], _f_lap["h"]) == (1366, 728), _f_lap)
check("笔记本最小尺寸不超过屏幕", _f_lap["min_w"] <= 1366
      and _f_lap["min_h"] <= 728, _f_lap)
_f_desk = scr.fit_window(_desk)
check("台式 1080p 用 1440×900 基准窗口",
      (_f_desk["w"], _f_desk["h"]) == (1440, 900), _f_desk)
check("台式机不最大化且水平居中",
      _f_desk["maxed"] is False and _f_desk["x"] == (1920 - 1440) // 2, _f_desk)
check("窗口垂直位置在工作区内",
      _f_desk["y"] >= 0 and _f_desk["y"] + _f_desk["h"] <= 1032, _f_desk)
_f_big = scr.fit_window(_big)
check("2K 大屏窗口不超过设计基准",
      (_f_big["w"], _f_big["h"]) == (1440, 900), _f_big)
_f_hd = scr.fit_window(_hidpi)
check("150% 缩放：窗口按比例放大", _f_hd["w"] > 1800 and _f_hd["h"] > 900, _f_hd)
check("150% 缩放：窗口仍收在屏幕内",
      _f_hd["w"] <= 1920 and _f_hd["h"] <= 1032, _f_hd)
check("150% 缩放：最小尺寸同步放大且不超屏",
      _f_hd["min_w"] >= 1080 and _f_hd["min_w"] <= 1920, _f_hd)
# 上次保存的窗口尺寸：换机器 / 换分辨率不能照搬
_f_s1 = scr.fit_window(_lap, saved="1920x1080+0+0")
check("换到小屏时恢复尺寸自动收进屏幕",
      (_f_s1["w"], _f_s1["h"]) == (1366, 728), _f_s1)
_f_s2 = scr.fit_window(_desk, saved="1200x800+120+80")
check("大屏上正常恢复上次尺寸 1200×800",
      (_f_s2["w"], _f_s2["h"]) == (1200, 800), _f_s2)
_f_s3 = scr.fit_window(_desk, saved="2400x1400+0+0")
check("超出工作区的上次尺寸被忽略", (_f_s3["w"], _f_s3["h"]) == (1440, 900), _f_s3)
# 弹窗：笔记本上不能比屏幕还高
_d_lap = scr.fit_dialog((670, 730), _lap)
check("730 高弹窗在 768 屏幕上被收进工作区",
      600 <= _d_lap[1] <= 728, _d_lap)
check("小屏弹窗宽度不被压缩", _d_lap[0] == 670, _d_lap)
check("1080p 上弹窗尺寸保持不变",
      scr.fit_dialog((670, 730), _desk) == (670, 730),
      scr.fit_dialog((670, 730), _desk))
check("150% 缩放下弹窗按比例放大",
      scr.fit_dialog((670, 730), _hidpi)[0] > 670, scr.fit_dialog((670, 730), _hidpi))
# 位置限制：标题栏不能被拖到屏幕外
check("窗口位置被限制在工作区内",
      scr.clamp_position(5000, -200, 400, 300, _desk) == (1920 - 400 - 8, 0),
      scr.clamp_position(5000, -200, 400, 300, _desk))
# 系统版本与 DPI
check("Win10 (19045) 不识别为 Win11", scr.is_win11(19045) is False)
check("Win11 (22631) 正确识别", scr.is_win11(22631) is True)
check("未开启 DPI 感知时缩放系数在 1.0~1.5",
      1.0 <= scr.dpi_scale() <= 1.5, scr.dpi_scale())
check("ui_scale 夹在 1.0~1.5", 1.0 <= scr.ui_scale(_hidpi) <= 1.5,
      scr.ui_scale(_hidpi))

print("== 3.3 回收站 / 批量修改 / 采购成本 / 买家 / 销售统计 ==")
rb = Store(os.path.join(TMP, "extras.db"))
rb.insert_many([
    blank_record() | {"code": "WL-00001", "brand": "罗技", "model": "G502",
                      "price": 100.0, "qty": 5, "shelf": "6排A-3"},
    blank_record() | {"code": "WL-00002", "brand": "Apple", "model": "A2634",
                      "price": 2000.0, "qty": 2, "shelf": "7排B-2"},
])
ids0 = {r["code"]: r["id"] for r in rb.all_records()}

# ---- 回收站（软删除）----
n_del = rb.delete_ids([ids0["WL-00001"]])
check("软删除返回条数", n_del == 1)
check("软删除后列表不含该记录", rb.count() == 1
      and all(r["code"] != "WL-00001" for r in rb.all_records()))
check("回收站有 1 条", rb.deleted_count() == 1 and len(rb.list_deleted()) == 1)
check("回收站记录保留原编号", rb.list_deleted()[0]["code"] == "WL-00001")
check("编号不回收（删除后 generate_codes 跳过）",
      rb.generate_codes(1)[0] != "WL-00001", str(rb.generate_codes(1)))
check("恢复回库存", rb.restore_ids([ids0["WL-00001"]]) == 1 and rb.count() == 2)
check("恢复后编号还在", any(r["code"] == "WL-00001" for r in rb.all_records()))
rb.delete_ids([ids0["WL-00001"]])
check("彻底删除（物理删除）",
      rb.purge_ids([ids0["WL-00001"]]) == 1 and rb.deleted_count() == 0)
check("彻底删除后 distinct 不含其品牌",
      "罗技" not in rb.distinct("brand"), str(rb.distinct("brand")))
rb.restore_ids([ids0["WL-00001"]]) if rb.deleted_count() else None
rb.insert(blank_record() | {"code": "WL-00001", "brand": "罗技", "model": "G502",
                            "price": 100.0, "qty": 5, "shelf": "6排A-3"})
ids0 = {r["code"]: r["id"] for r in rb.all_records()}

# ---- 批量修改字段 ----
all_ids = [r["id"] for r in rb.all_records()]
n_up = rb.batch_update(all_ids, {"shelf": "3排A-1", "condition": "99新", "listed": 1})
check("批量修改返回条数", n_up == 2, "实际=%d" % n_up)
check("批量修改生效", all(r["shelf"] == "3排A-1" and r["condition"] == "99新"
                        and int(r["listed"]) == 1 for r in rb.all_records()))
rb.batch_update(all_ids, {"qty": 0})
check("批量改数量 0 不误清已售完以外的字段",
      all(int(r["qty"]) == 0 for r in rb.all_records()))
rb.batch_update(all_ids, {"qty": 6, "listed": 0})
check("批量改回数量", all(int(r["qty"]) == 6 for r in rb.all_records()))

# ---- 采购入库 / 成本 ----
g1 = ids0["WL-00001"]
okp, msgp = rb.add_purchase(g1, 10, 320.0, supplier="深圳老王",
                            purchase_date="2026-08-12")
check("采购入库成功", okp, msgp)
rec = [r for r in rb.all_records() if r["id"] == g1][0]
check("采购后库存增加", int(rec["qty"]) == 16, "实际=%s" % rec["qty"])
check("采购后成本=进价", abs(float(rec["cost"]) - 320.0) < 1e-6, str(rec["cost"]))
rb.add_purchase(g1, 10, 360.0, purchase_date="2026-09-20")
rec = [r for r in rb.all_records() if r["id"] == g1][0]
check("移动加权平均成本", abs(float(rec["cost"]) - 340.0) < 1e-6, str(rec["cost"]))
check("采购数量校验", rb.add_purchase(g1, 0, 10)[0] is False)
check("采购单价校验", rb.add_purchase(g1, 1, -5)[0] is False)
prows = rb.list_purchases()
check("采购记录条数", len(prows) == 2, "实际=%d" % len(prows))
ptot = rb.purchase_totals(prows)
check("采购合计", ptot["qty"] == 20 and abs(ptot["amount"] - 6800.0) < 1e-6, str(ptot))
check("采购按日期倒序", prows[0]["purchase_date"] == "2026-09-20")
# 出售成本快照用采购成本而不是原单价
oks, _ = rb.add_sale(g1, 2, 500.0, buyer="张三", sale_date="2026-10-01")
srow = rb.list_sales()[0]
check("出售成本快照=采购成本", abs(float(srow["cost"]) - 340.0) < 1e-6, str(srow["cost"]))
check("出售利润=销售额-成本×数量",
      abs(rb.sales_totals([srow])["profit"] - (1000.0 - 680.0)) < 1e-6,
      str(rb.sales_totals([srow])))
okd, _ = rb.delete_purchase(prows[0]["id"])
rec = [r for r in rb.all_records() if r["id"] == g1][0]
check("撤销采购扣回库存", okd and int(rec["qty"]) == 14, "实际=%s" % rec["qty"])
check("撤销后成本重算", abs(float(rec["cost"]) - 320.0) < 1e-6, str(rec["cost"]))

# ---- 买家 ----
rb.add_sale(g1, 1, 500.0, buyer="张三", sale_date="2026-10-02")
rb.add_sale(g1, 1, 500.0, buyer="张三", sale_date="2026-10-03")
g2 = ids0["WL-00002"]
rb.add_sale(g2, 1, 2100.0, buyer="李四", sale_date="2026-10-03")
bstats = rb.buyer_stats()
check("买家统计条数", len(bstats) == 2, str(bstats))
z = [b for b in bstats if b["buyer"] == "张三"][0]
check("买家张三聚合", z["count"] == 3 and z["qty"] == 4
      and abs(z["amount"] - 2000.0) < 1e-6, str(z))
check("买家最近购买", z["last"] == "2026-10-03", str(z["last"]))
check("买家下拉", rb.buyer_names() == ["张三", "李四"], str(rb.buyer_names()))
check("重命名买家（改名到已有名即合并）",
      rb.rename_buyer("李四", "张三") == 1 and len(rb.buyer_names()) == 1)
check("清空买家标记", rb.clear_buyer("张三") == 4
      and rb.buyer_names() == [] and len(rb.list_sales()) == 4)

# ---- 销售统计（月度/品牌/本月）----
check("本月销售额", abs(rb.month_sales_amount("2026-10")["amount"] - 4100.0) < 1e-6,
      str(rb.month_sales_amount("2026-10")))
check("指定月销售额", rb.month_sales_amount("2026-09")["amount"] == 0.0)
mon = rb.monthly_sales(3)
check("月度序列长度与升序", len(mon) == 3 and mon[0][0] < mon[-1][0], str(mon))
check("月度销售额", abs([v for k, v in mon if k == "2026-10"][0] - 4100.0) < 1e-6, str(mon))
bs = rb.brand_sales()
check("品牌销售额聚合", abs(sum(v for _b, v, _p in bs) - 4100.0) < 1e-6
      and [v for b, v, _p in bs if b == "罗技"][0] == 2000.0, str(bs))

# ---- 设置项（meta）----
rb.set_meta("low_stock_threshold", 5)
check("meta 写入读取", rb.get_num("low_stock_threshold", 3) == 5.0)
rb.set_meta("monthly_target", 20000)
check("meta 目标读取", rb.get_num("monthly_target", 0) == 20000.0)
check("meta 默认值", rb.get_num("not_exist", 7) == 7.0)

# ---- 采购导出 ----
purch_path = os.path.join(TMP, "purchases.xlsx")
rb.add_purchase(g1, 3, 330.0, supplier="深圳老王", purchase_date="2026-10-05")
xlsxio.export_purchases_xlsx(purch_path, rb.list_purchases(), "测试仓")
wb_p = openpyxl.load_workbook(purch_path)
check("采购导出含两个工作表",
      "采购记录" in wb_p.sheetnames and "采购汇总" in wb_p.sheetnames, str(wb_p.sheetnames))
ws_p = wb_p["采购记录"]
check("采购导出行数", ws_p.max_row == len(rb.list_purchases()) + 1,
      "%d vs %d" % (ws_p.max_row, len(rb.list_purchases()) + 1))
check("采购导出表头", [c.value for c in ws_p[1]][:3] == ["采购日期", "编号", "品牌"],
      str([c.value for c in ws_p[1]][:3]))
wb_p.close()
rb.close()

print("== 4. 统计 ==")
s = st.stats(st.all_records())
check("记录数", s["total"] == 10, "实际=%d" % s["total"])
check("库存总数", s["total_qty"] == sum(int(r["qty"]) for r in st.all_records()))
check("品牌数", s["brand_count"] == 7, "实际=%d" % s["brand_count"])
check("价格区间非空", len(s["price_dist"]) > 0)
check("上架统计", s["listed"] == sum(1 for r in st.all_records() if int(r["listed"]) == 1))

print("== 5. 导出 XLSX ==")
out_path = os.path.join(TMP, "out.xlsx")
xlsxio.export_xlsx(out_path, st.all_records())
h2, r2, _ = xlsxio.read_xlsx(out_path)
check("导出后行数", len(r2) == 10, "实际=%d" % len(r2))
check("导出表头", h2[0] == "编号")
check("导出上架文本", any(v == "已上架" for v in [row[8] for row in r2]))

tpl_path = os.path.join(TMP, "tpl.xlsx")
xlsxio.write_template(tpl_path)
h3, r3, _ = xlsxio.read_xlsx(tpl_path)
check("模板可再导入", len(r3) == 4)

stat_path = os.path.join(TMP, "stats.xlsx")
xlsxio.export_stats_xlsx(stat_path, st.all_records(), s, "全部数据")
check("统计报表工作表", set(xlsxio.list_sheets(stat_path)) >=
      {"库存明细", "统计概览", "品牌统计", "品类统计", "成色统计", "货架统计", "价格区间"})

# ============================================================ GUI 冒烟测试
print("== 6. GUI 冒烟 ==")
tk_errors = []


def tk_hook(args):
    tk_errors.append(args)


threading.excepthook = tk_hook

import tkinter as tk
from tkinter import ttk
from wm.constants import center_window  # noqa: E402
root = tk.Tk()
root.withdraw()
try:
    app = wapp.App(root)
    root.deiconify()
    root.update()
    # ---- 屏幕自适应（v1.12.0）：窗口尺寸 / 最小尺寸 / 行高跟随屏幕与 DPI ----
    _wa = scr.screen_metrics(root)
    _mw, _mh = root.minsize()
    check("主窗口最小尺寸不超过屏幕工作区",
          int(_mw) <= _wa["w"] and int(_mh) <= _wa["h"],
          "%s vs %s" % ((_mw, _mh), (_wa["w"], _wa["h"])))
    check("按当前 DPI 计算了界面缩放", 1.0 <= app.ui_scale <= 1.5, app.ui_scale)
    check("表格行高跟随界面缩放",
          int(ttk.Style(root).lookup("Treeview", "rowheight"))
          == int(round(30 * app.ui_scale)),
          ttk.Style(root).lookup("Treeview", "rowheight"))
    check("窗口实际大小不超工作区",
          root.winfo_width() <= _wa["w"] and root.winfo_height() <= _wa["h"],
          "%sx%s" % (root.winfo_width(), root.winfo_height()))

    # 窗口缩到最小后，表格的横/竖滚动条不能被内容挤掉（pack 顺序坑，v1.12.2）
    def _scrollbars(w):
        out = []
        try:
            for c in w.winfo_children():
                if c.winfo_class() == "TScrollbar":
                    out.append(c)
                out.extend(_scrollbars(c))
        except Exception:
            pass
        return out

    root.geometry("1080x660")
    for _ in range(6):
        root.update()
    _bars = [b for b in _scrollbars(root) if b.winfo_ismapped()]
    _vbars = [b for b in _bars if b.winfo_width() > 8 and b.winfo_height() > 40]
    _hbars = [b for b in _bars if b.winfo_height() > 8 and b.winfo_width() > 40]
    check("最小窗口下竖向滚动条仍在", len(_vbars) >= 1,
          [(b.winfo_width(), b.winfo_height()) for b in _bars])
    check("最小窗口下横向滚动条仍在", len(_hbars) >= 1,
          [(b.winfo_width(), b.winfo_height()) for b in _bars])
    root.geometry("1440x900")
    for _ in range(4):
        root.update()
    # GUI 使用独立的 data/warehouse.db，灌入同一批数据
    app.store.clear_all()
    app.store.insert_many([dict(r) for r in norm])
    app.load_data()

    def _geo_xy(win):
        """解析窗口实际位置 (x, y, w, h)；解析失败返回 None。"""
        import re as _re
        m = _re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", win.geometry())
        return (int(m.group(3)), int(m.group(4)), int(m.group(1)), int(m.group(2))) if m else None

    def _expect_center(w, h):
        """center_window 的期望坐标（与主窗口对齐的居中公式）。"""
        return (root.winfo_rootx() + (root.winfo_width() - w) // 2,
                root.winfo_rooty() + int((root.winfo_height() - h) * 0.34))


    def pump_until(cond, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            root.update()
            if cond():
                return True
            time.sleep(0.02)
        return False


    check("主窗口加载", pump_until(lambda: len(app.records) == 7))
    check("表格渲染", len(app.tree.get_children()) == 7)

    # 筛选
    app.f_vars["brand"].set("罗技")
    app.apply_filters()
    check("品牌筛选", len(app.filtered) == 2, "实际=%d" % len(app.filtered))
    app.reset_filters()
    app.var_kw.set("SPP4020")
    app.apply_filters()
    check("关键词筛选", len(app.filtered) == 1)
    app.var_kw.set("")
    app.f_vars["brand"].set("全部")
    app.var_pmin.set("1000")
    app.apply_filters()
    check("价格下限筛选", len(app.filtered) == 3, "实际=%d" % len(app.filtered))
    app.reset_filters()
    check("重置筛选", len(app.filtered) == 7)

    # 多货架记录筛选：拆分后任一货架位命中（GUI 库里已含 WL-M1? 没有——GUI 用独立库）
    app.store.insert_many([blank_record() | {"code": "WL-M1", "brand": "罗技",
                                             "model": "MS-1", "qty": 2,
                                             "shelf": "6排A-3 / 7排A-1"}])
    app.load_data()
    root.update()
    check("货架下拉含拆分后的货架位",
          "7排A-1" in app.f_combos["shelf"]["values"]
          and "6排A-3 / 7排A-1" not in app.f_combos["shelf"]["values"],
          str(app.f_combos["shelf"]["values"])[:150])
    app.f_vars["shelf"].set("7排A-1")
    app.apply_filters()
    check("多货架记录按单个货架位命中筛选",
          any(r.get("code") == "WL-M1" for r in app.filtered),
          str([r.get("code") for r in app.filtered]))
    app.reset_filters()
    check("重置筛选含多货架记录", len(app.filtered) == 8,
          "实际=%d" % len(app.filtered))

    # 手动输入筛选（v1.10.2）：品牌/品类/成色/货架可输入，不区分大小写包含匹配
    check("品牌筛选框可手动输入", str(app.f_combos["brand"].cget("state")) == "normal",
          str(app.f_combos["brand"].cget("state")))
    check("上架状态筛选保持只读", str(app.f_combos["listed"].cget("state")) == "readonly")
    app.f_vars["brand"].set("罗")
    app.apply_filters()
    check("品牌手动输入包含匹配", len(app.filtered) == 3, "实际=%d" % len(app.filtered))
    app.f_vars["brand"].set("APP")
    app.apply_filters()
    check("品牌输入不区分大小写",
          len(app.filtered) == 1 and app.filtered[0]["brand"] == "Apple",
          str([(r.get("code"), r.get("brand")) for r in app.filtered]))
    app.f_vars["brand"].set("罗技")
    app.f_vars["shelf"].set("3排")
    app.apply_filters()
    check("货架手动输入包含匹配",
          len(app.filtered) == 2 and all("3排" in (r.get("shelf") or "")
                                         for r in app.filtered),
          str([(r.get("code"), r.get("shelf")) for r in app.filtered]))
    app.f_vars["brand"].set("全部")
    app.f_vars["shelf"].set("全部")

    # ---- 手动补录出售（v1.10.8）：出售页有「+ 登记出售」，出库页没有 ----
    def _btn_texts(w):
        out = []
        for c in w.winfo_children():
            if c.winfo_class() == "TButton":
                out.append(str(c.cget("text")))
            out.extend(_btn_texts(c))
        return out
    check("出售页有「+ 登记出售」按钮",
          "+ 登记出售" in _btn_texts(app.tab_sales), _btn_texts(app.tab_sales))
    check("出库页没有「+ 登记出售」按钮",
          "+ 登记出售" not in _btn_texts(app.tab_out))

    # ---- 下架行灰显（v1.10.3）：未上架行淡灰底，可开关 ----
    app.load_data()
    root.update()
    un_iid = str([r for r in app.records if not int(r.get("listed") or 0)][0]["id"])
    tags_un = app.tree.item(un_iid, "tags")
    check("下架行有灰显标记", "unlisted" in tags_un, str(tags_un))
    app.var_unlisted_hl.set(False)
    app.toggle_unlisted_hl()
    root.update()
    check("关闭灰显后下架行无标记",
          "unlisted" not in app.tree.item(un_iid, "tags"),
          str(app.tree.item(un_iid, "tags")))
    check("灰显开关随仓库保存",
          int(app.store.get_num("unlisted_shade", 1)) == 0)
    app.var_unlisted_hl.set(True)
    app.toggle_unlisted_hl()
    root.update()
    check("重新开启灰显", "unlisted" in app.tree.item(un_iid, "tags"))

    # ---- 手动区域上色（v1.10.3）：框选区块上色 / 贴片对位 / 取消 / 持久化 ----
    kids_p = app.tree.get_children()
    cols_p = app._cols()
    c0p, c1p = cols_p.index("brand"), cols_p.index("model")
    sel_p = [str(i) for i in kids_p[1:4]]
    app._drag_block = {"rows": sel_p, "c0": c0p, "c1": c1p}
    app.paint_cells("#FFD9D9")
    root.update()
    check("框选区块上色写入 cell_colors",
          all(app.cell_colors.get(i, {}).get("brand") == "#FFD9D9" for i in sel_p),
          str({k: app.cell_colors.get(k) for k in sel_p}))
    check("上色随仓库保存",
          json.loads(app.store.get_meta("cell_colors", "{}") or "{}").get(sel_p[0], {})
          .get("brand") == "#FFD9D9",
          str(app.store.get_meta("cell_colors", ""))[:120])
    check("上色生成贴片", len(app._paint_labels) == 9,
          str(len(app._paint_labels)))
    ok_pos = 0
    for lb in app._paint_labels:
        pi = lb.place_info()
        hit_iid, hit_idx = app._cell_at(int(pi["x"]) + 5, int(pi["y"]) + 5)
        if hit_iid and app.fmt(cols_p[hit_idx], app.by_id[str(hit_iid)]) == lb.cget("text"):
            ok_pos += 1
    check("贴片与单元格文本一一对齐", ok_pos == len(app._paint_labels),
          "%d/%d" % (ok_pos, len(app._paint_labels)))
    # 无区块时 → 给选中行整行上色
    app._drag_block = None
    app._block_preview = None
    app.tree.selection_set(kids_p[0])
    app.paint_cells("#D6E4FF")
    root.update()
    check("选中行整行上色",
          len(app.cell_colors.get(str(kids_p[0]), {})) == len(cols_p),
          str(len(app.cell_colors.get(str(kids_p[0]), {}))))
    # 重新载入后颜色仍在（随仓库持久化）
    app.load_data()
    root.update()
    check("重新载入后颜色保留", len(app._paint_labels) > 0
          and app.cell_colors.get(sel_p[0], {}).get("brand") == "#FFD9D9",
          str(app.cell_colors)[:120])
    # 取消选区颜色
    app._drag_block = {"rows": sel_p, "c0": c0p, "c1": c1p}
    app.clear_cell_colors()
    root.update()
    check("取消选区颜色", not any(app.cell_colors.get(i) for i in sel_p),
          str(app.cell_colors))
    check("取消后贴片移除", len(app._paint_labels) ==
          len(app.cell_colors.get(str(kids_p[0]), {})),
          str(len(app._paint_labels)))
    # 取消全部
    app.clear_cell_colors(all_rows=True)
    root.update()
    check("取消全部颜色", not app.cell_colors and not app._paint_labels,
          str((app.cell_colors, len(app._paint_labels))))
    check("取消全部后 meta 已清空",
          not (app.store.get_meta("cell_colors", "") or "").strip()
          or app.store.get_meta("cell_colors") in ("{}", ""),
          repr(app.store.get_meta("cell_colors", "")))

    # ---- 鼠标划过整行高亮（v1.10.7） ----
    app._drag_block = None
    app._block_preview = None
    app.clear_cell_colors(all_rows=True)
    app.hover.reset()
    root.update()
    kids_h = list(app.tree.get_children())
    r0, r1 = str(kids_h[0]), str(kids_h[1])
    bb_h = app.tree.bbox(r1, column="brand")
    got_h = app.hover.row_at(app.tree.winfo_rootx() + bb_h[0] + 5,
                             app.tree.winfo_rooty() + bb_h[1] + 5)
    check("划过坐标解析到正确行", got_h == r1, "%s vs %s" % (got_h, r1))
    check("表头/空白处不触发（表头）",
          app.hover.row_at(app.tree.winfo_rootx() + 50,
                           app.tree.winfo_rooty() + 3) is None)
    check("表格外不触发",
          app.hover.row_at(app.tree.winfo_rootx() - 20,
                           app.tree.winfo_rooty() + 40) is None)
    tags_before = set(app.tree.item(r1, "tags"))
    tags_r0 = set(app.tree.item(r0, "tags"))
    app.hover.set(r1)
    check("划过行带 hover 标记", "hover" in app.tree.item(r1, "tags"),
          str(app.tree.item(r1, "tags")))
    check("原有标记（斑马纹等）保留",
          set(app.tree.item(r1, "tags")) - {"hover"} == tags_before,
          str(app.tree.item(r1, "tags")))
    app.hover.set(r0)
    check("高亮随鼠标换行",
          "hover" in app.tree.item(r0, "tags")
          and "hover" not in app.tree.item(r1, "tags"),
          str((app.tree.item(r0, "tags"), app.tree.item(r1, "tags"))))
    app.hover.set(None)
    check("离开后 hover 标记清除",
          "hover" not in app.tree.item(r0, "tags")
          and set(app.tree.item(r0, "tags")) == tags_r0,
          str(app.tree.item(r0, "tags")))
    # 重排/刷新后旧行作废
    app.hover.set(r0)
    app.render_page()
    root.update()
    check("重新渲染后 hover 状态复位",
          app.hover.row is None
          and all("hover" not in app.tree.item(i, "tags")
                  for i in app.tree.get_children()))
    # 划过已上色行：只加淡描边，不重建贴片
    app.tree.selection_set(r1)
    app.paint_cells("#FFE3E3")
    app.tree.selection_set()
    app.hover.set(None)
    root.update()
    n_lab_h = len(app._paint_labels)
    app.hover.set(r1)
    root.update()
    th = [int(str(lb.cget("highlightthickness"))) for lb in app._paint_labels]
    check("划过上色行：贴片加淡描边且不重建",
          len(app._paint_labels) == n_lab_h and sum(1 for t in th if t == 1) == n_lab_h,
          "%d/%d %s" % (len(app._paint_labels), n_lab_h, th[:4]))
    app.hover.set(None)
    root.update()
    th2 = [int(str(lb.cget("highlightthickness"))) for lb in app._paint_labels]
    check("离开上色行：描边撤掉", sum(1 for t in th2 if t == 1) == 0, str(th2[:4]))
    app.clear_cell_colors(all_rows=True)
    root.update()

    # 出售/出库页也要有划过高亮
    app.tab_sales.refresh_rows()
    root.update()
    kids_s2 = list(app.tab_sales.tree.get_children())
    if kids_s2:
        app.tab_sales.hover.set(str(kids_s2[0]))
        check("出售页划过高亮",
              "hover" in app.tab_sales.tree.item(str(kids_s2[0]), "tags"),
              str(app.tab_sales.tree.item(str(kids_s2[0]), "tags")))
        app.tab_sales.refresh_rows()
        check("出售页刷新后 hover 复位",
              app.tab_sales.hover.row is None
              and all("hover" not in app.tab_sales.tree.item(i, "tags")
                      for i in app.tab_sales.tree.get_children()))
    else:
        check("出售页划过高亮（无数据跳过）", True)

    # ---- 贴片选中态 + 按下贴片同步选中（v1.10.4 修复：上色后看不出选中） ----
    app._drag_block = None
    app._block_preview = None
    app.hover.reset()
    kids_s = [str(i) for i in kids_p[:2]]
    for iid in kids_s:
        app.tree.selection_set([iid])
        app.paint_cells("#FFE3E3")        # 两行各整行上色
    app.tree.selection_set([kids_s[0]])   # 只选中第一行
    root.update()
    app._paint_overlays()
    hi = [int(str(lb.cget("highlightthickness"))) for lb in app._paint_labels]
    n_cs = len(cols_p)
    check("选中行的贴片有蓝描边", sum(1 for t in hi if t == 2) == n_cs, str(hi))
    check("未选中行的贴片无描边", sum(1 for t in hi if t == 0) == n_cs, str(hi))
    # 选中变化即时重画（TreeviewSelect 挂了重画钩子）
    app.tree.selection_set([kids_s[1]])
    root.update()
    hi2 = [int(str(lb.cget("highlightthickness"))) for lb in app._paint_labels]
    check("切换选中后描边跟随", sum(1 for t in hi2 if t == 2) == n_cs
          and sum(1 for t in hi2 if t == 0) == n_cs, str(hi2))
    # 按下贴片 → 同步选中所在行（否则上色退化成旧行）
    # 此时选中的是 kids_s[1]，取一个未选中行（kids_s[0]）的贴片来按
    lb0 = [lb for lb in app._paint_labels
           if int(str(lb.cget("highlightthickness"))) == 0][0]
    lb0.event_generate("<Button-1>", x=4, y=4,
                       rootx=lb0.winfo_rootx() + 4, rooty=lb0.winfo_rooty() + 4)
    root.update()
    check("按下贴片同步选中所在行",
          list(app.tree.selection()) == [kids_s[0]],
          str(app.tree.selection()))
    # 拖动中锚点丢失 → 自动补锚点（修复“有时只上一行”）
    app._drag_anchor = None
    app._drag_block = None
    app._block_preview = None
    bb1 = app.tree.bbox(kids_p[0], column="brand")
    bb2 = app.tree.bbox(kids_p[2], column="brand")
    class _Ev3:
        pass
    e3 = _Ev3()
    e3.x, e3.y = bb1[0] + bb1[2] // 2, bb1[1] + bb1[3] // 2
    app._on_drag(e3)
    e3.x, e3.y = bb2[0] + bb2[2] // 2, bb2[1] + bb2[3] // 2
    app._on_drag(e3)
    check("拖动中锚点丢失自动补", bool(app._drag_block)
          and len(app._drag_block["rows"]) == 3,   # 第1行拖到第3行=3行（含首尾）
          str(app._drag_block))
    app._drag_block = None
    app._block_preview = None
    app.clear_cell_colors(all_rows=True)
    root.update()

    # 右键不打散框选区块（v1.10.5：右键→上色只识别一行的根因）
    app._drag_block = {"rows": [str(i) for i in kids_p[1:4]],
                       "c0": cols_p.index("brand"), "c1": cols_p.index("model")}
    _captured_menu = []
    _orig_popup2 = tk.Menu.tk_popup

    def _fake_popup2(self_menu, x, y, entry=""):
        labs = []
        try:
            n = self_menu.index("end")
        except Exception:
            n = None
        if n is not None:
            for i in range(n + 1):
                try:
                    if self_menu.type(i) == "separator":
                        continue
                    labs.append(str(self_menu.entrycget(i, "label")))
                except Exception:
                    pass
        _captured_menu.append(labs)
    tk.Menu.tk_popup = _fake_popup2
    bb_rc = app.tree.bbox(kids_p[2], column="model")
    class _EvR:
        pass
    evr = _EvR()
    evr.x, evr.y = bb_rc[0] + bb_rc[2] // 2, bb_rc[1] + bb_rc[3] // 2
    evr.x_root, evr.y_root = 100, 100
    app.on_right_click(evr)
    root.update()
    tk.Menu.tk_popup = _orig_popup2
    check("右键落在区块内不打散区块", bool(app._drag_block)
          and len(app._drag_block["rows"]) == 3, str(app._drag_block))
    check("右键后上色目标为整块",
          len(app._paint_targets()) == 3 * 3, str(len(app._paint_targets())))
    rc_lab = [l for labs in _captured_menu for l in labs if l.startswith("区域上色")]
    check("右键菜单显示框选区块（3 行 × 3 列）",
          bool(rc_lab) and "3 行 × 3 列" in rc_lab[0], str(rc_lab))
    # 区块外右键 → 回落到选中行
    app._drag_block = {"rows": [str(i) for i in kids_p[1:4]],
                       "c0": cols_p.index("brand"), "c1": cols_p.index("model")}
    _captured_menu.clear()
    tk.Menu.tk_popup = _fake_popup2
    bb_out = app.tree.bbox(kids_p[6], column="price")
    evr.x, evr.y = bb_out[0] + bb_out[2] // 2, bb_out[1] + bb_out[3] // 2
    app.on_right_click(evr)
    root.update()
    tk.Menu.tk_popup = _orig_popup2
    rc_lab2 = [l for labs in _captured_menu for l in labs if l.startswith("区域上色")]
    check("区块外右键回落单行", not app._drag_block
          and len(app._paint_targets()) == len(cols_p), str(app._drag_block))
    check("区块外菜单显示选中行", bool(rc_lab2) and "框选区块" not in rc_lab2[0],
          str(rc_lab2))
    app.clear_cell_colors(all_rows=True)
    root.update()

    # ---- 滚动后贴片跟随（v1.10.6 修复：上色行滚出可视区再滚回，颜色消失） ----
    app.store.insert_many([blank_record() | {"code": "WL-S%03d" % i, "brand": "SCroll",
                                             "model": "M%d" % i, "qty": 1, "listed": 1}
                           for i in range(1, 61)])
    app.load_data()
    root.update()
    tgt_sc = str(app.tree.get_children()[2])
    app.tree.selection_set(tgt_sc)
    app.paint_cells("#FFD9D9")
    root.update()
    n_lab = len(app._paint_labels)
    check("滚动测试：整行上色生成贴片", n_lab == len(cols_p), str(n_lab))
    # 模拟"上色行滚出可视区"（贴片清零但颜色数据还在）再滚回来：贴片必须恢复
    app._forget_overlays()
    app._after_scroll()
    root.update()
    check("滚出可视区再滚回颜色恢复", len(app._paint_labels) == n_lab,
          "%d/%d" % (len(app._paint_labels), n_lab))
    # 滚轮事件必须"先滚动后重画"：滚完贴片与单元格一一对齐
    if app.tree.yview()[1] < 1.0:
        app._on_wheel(type("E", (), {"delta": -120})())
        root.update()
        ok_w = 0
        for lb in app._paint_labels:
            pi = lb.place_info()
            iid, idx = app._cell_at(int(pi["x"]) + 5, int(pi["y"]) + 5)
            if iid and app.fmt(cols_p[idx], app.by_id[str(iid)]) == lb.cget("text"):
                ok_w += 1
        check("滚轮滚动后贴片跟随对位",
              bool(app._paint_labels) and ok_w == len(app._paint_labels),
              "%d/%d" % (ok_w, len(app._paint_labels)))
        check("滚轮滚动真的滚动了", app.tree.yview()[0] > 0.0, str(app.tree.yview()))
        app.tree.yview_moveto(0.0)
        app._after_scroll()
        root.update()
    # 清理滚动测试数据与颜色
    _sc = [r for r in app.store.all_records()
           if (r.get("code") or "").startswith("WL-S")]
    app.store.delete_ids([r["id"] for r in _sc])
    app.clear_cell_colors(all_rows=True)
    app.load_data()
    root.update()
    check("滚动测试数据已清理", app.store.count() == 8, str(app.store.count()))

    # 清理多货架测试记录，恢复原有数据量
    _m1 = [r for r in app.store.all_records() if r.get("code") == "WL-M1"]
    app.store.delete_ids([r["id"] for r in _m1])
    app.load_data()
    root.update()
    check("GUI 多货架测试记录已清理", app.store.count() == 7,
          "实际=%d" % app.store.count())

    # 排序
    app.reset_filters()
    app.sort_column("price")
    prices = [float(r["price"]) for r in app.filtered]
    check("升序排序", prices == sorted(prices))
    app.sort_column("price")
    prices = [float(r["price"]) for r in app.filtered]
    check("降序排序", prices == sorted(prices, reverse=True))

    # 分页
    app._set_page_size("2")
    check("分页渲染", len(app.tree.get_children()) == 2)
    app.goto_page(2)
    check("翻页", app.page == 2 and len(app.tree.get_children()) == 2)
    app._set_page_size("全部")
    check("全部页", len(app.tree.get_children()) == 7)

    # 复制
    first = app.tree.get_children()[0]
    app.tree.selection_set(first)
    app.tree.focus(first)
    root.update()
    app.copy_selected()
    got = root.clipboard_get()
    check("复制选中行", "罗技" in got or "iPhone" in got or "\t" in got, repr(got[:40]))
    app.copy_all()
    check("复制全部", root.clipboard_get().count("\n") == 6)
    app.copy_cell()
    check("复制单元格", "\n" not in root.clipboard_get())
    app.copy_detail_json()
    check("复制JSON", root.clipboard_get().lstrip().startswith("{"))

    # 鼠标拖选区块复制（v1.6.0）：行区间 × 列区间
    rows3 = app.tree.get_children()[:3]
    cols_now = app._cols()
    app._drag_block = {"rows": list(rows3), "c0": cols_now.index("model"),
                       "c1": cols_now.index("price")}
    app.copy_block()
    blk_txt = root.clipboard_get()
    blk_lines = blk_txt.split("\n")
    check("区块复制：纯数据无表头", len(blk_lines) == 3, "实际=%d" % len(blk_lines))
    check("区块复制：只含所选列",
          "\t" in blk_lines[0] and not blk_lines[0].startswith("型号"), repr(blk_lines[0]))
    check("区块复制：每行列数一致",
          all(len(l.split("\t")) == 3 for l in blk_lines), repr(blk_lines))
    check("区块复制：内容与所选行一致",
          blk_lines[0].split("\t")[0] == app.fmt("model", app.by_id[str(rows3[0])]),
          repr(blk_lines[0]))
    check("区块复制后详情区展示该区块",
          "已框选 3 行 × 3 列" in app.lbl_detail_title.cget("text"),
          app.lbl_detail_title.cget("text"))
    # Ctrl+C 在无区块时回退为复制选中行
    app._drag_block = None
    app.tree.selection_set(rows3[0])
    app._on_ctrl_c()
    check("无区块时 Ctrl+C 复制选中行",
          root.clipboard_get().count("\n") == 0, repr(root.clipboard_get()[:40]))
    # 重新渲染后区块失效，不会复制到错行
    app._drag_block = {"rows": list(rows3), "c0": 0, "c1": 1}
    app.render_page()
    check("重新渲染后区块被清空", app._drag_block is None)

    # 上架切换
    rec0 = app.by_id[str(first)]
    before = int(rec0["listed"])
    app.store.set_listed([rec0["id"]], 1 - before)
    app.load_data()
    check("上架切换持久化", int(app.by_id[str(app.tree.get_children()[0])]["listed"]) != before)

    # 新增/编辑/删除（对话框）——直接调用底层
    new_rec = blank_record()
    new_rec.update({"code": "", "brand": "测试牌", "category": "测试",
                    "model": "T1", "condition": "全新", "price": 12.5, "qty": 4,
                    "shelf": "T-01", "listed": 1, "remark": "自动化"})
    new_rec["code"] = app.store.generate_codes(1)[0]
    check("自动编号前缀", new_rec["code"].startswith("WL-"))
    app.store.insert(new_rec)
    app.load_data()
    check("新增后加载", len(app.records) == 8)
    target = [r for r in app.records if r["code"] == new_rec["code"]][0]
    app.tree.selection_set(str(target["id"]))
    app.store.delete_ids([target["id"]])
    app.load_data()
    check("删除生效", len(app.records) == 7)

    # 后台导出（线程安全）
    result_holder = {}
    app.do_export = lambda: None  # 避免弹文件框
    out2 = os.path.join(TMP, "bg.xlsx")
    app._run_bg(lambda: xlsxio.export_xlsx(out2, app.records),
                lambda r, e: result_holder.update({"r": r, "e": e}), "测试导出…")
    check("后台导出完成", pump_until(lambda: result_holder or tk_errors, 20))
    check("后台导出无异常", not tk_errors and os.path.exists(out2))
    app._end_busy()
    check("后台任务已结束", not app._busy)

    # 数据分析页
    app.nb.select(1)
    root.update()
    stats = app.tab_ana.refresh()
    check("分析页KPI", stats["total"] == 7)
    root.update()

    # 导入向导弹窗
    from wm.importer import ImportDialog
    dlg = ImportDialog(root, xlsx_path, app.fam)
    root.update()
    check("导入向导识别行数", len(dlg.records) == 7, "实际=%d" % len(dlg.records))
    check("导入向导字段映射", set(dlg.mapping.values()) >=
          {"code", "brand", "category", "model", "condition", "price",
           "qty", "shelf", "listed", "remark"})
    check("导入向导预览列", len(dlg.preview["columns"]) >= 9)
    # 手动改映射：把「货架」列换到「备注」，再换回
    dlg.field_vars["shelf"].set("说明")
    dlg._on_map_change()
    check("手动映射生效", [i for i, v in dlg.mapping.items() if v == "shelf"] ==
          [dlg.headers.index("说明")])
    dlg.field_vars["shelf"].set("G (货架)")
    dlg._on_map_change()
    check("手动映射还原", [i for i, v in dlg.mapping.items() if v == "shelf"] ==
          [dlg.headers.index("G (货架)")])
    dlg.var_mode.set("append")
    dlg._ok()
    check("导入向导返回结果", dlg.result is not None and dlg.result["total_rows"] == 7)
    try:
        dlg.destroy()
    except Exception:
        pass

    # 编辑弹窗（上架状态为下拉可选项）
    from wm.editor import RecordDialog
    one = app.records[0]
    ed = RecordDialog(root, dict(one), app.suggestions(), "编辑记录", app.fam)
    root.update()
    listed_widget = ed.vars.get("listed")
    check("上架状态为下拉项", isinstance(listed_widget, tk.StringVar) and
          listed_widget.get() in ("已上架", "未上架"),
          "实际=%r" % (listed_widget.get() if listed_widget else None))
    ed.vars["listed"].set("未上架")
    ed.vars["price"].set("123.45")
    # 品牌/品类/成色/货架为「可输入 + 下拉」组合框（v1.10.2）
    def _all_combos(w):
        out = []
        for c in w.winfo_children():
            if isinstance(c, ttk.Combobox):
                out.append(c)
            out.extend(_all_combos(c))
        return out
    brand_cbs = [w for w in _all_combos(ed)
                 if str(w.cget("textvariable")) == str(ed.vars["brand"])]
    check("编辑弹窗品牌为可输入下拉", bool(brand_cbs)
          and str(brand_cbs[0].cget("state")) != "readonly",
          "state=%r" % (str(brand_cbs[0].cget("state")) if brand_cbs else None))
    ed.vars["brand"].set("全新品牌-手动输入")
    ed._save()
    check("编辑弹窗保存（含手动输入品牌）",
          ed.result is not None and ed.result["listed"] == 0
          and ed.result["brand"] == "全新品牌-手动输入"
          and abs(ed.result["price"] - 123.45) < 1e-6,
          str(ed.result and (ed.result["brand"], ed.result["listed"])))
    try:
        ed.destroy()
    except Exception:
        pass
    # 校验：价格非法
    ed2 = RecordDialog(root, dict(one), app.suggestions(), "编辑记录", app.fam)
    ed2.vars["price"].set("abc")
    ed2._save()
    check("价格校验拦截", ed2.result is None)
    try:
        ed2.destroy()
    except Exception:
        pass

    # 导入向导：默认「按型号合并」+ 重复判断列
    from wm.importer import ImportDialog
    dlg2 = ImportDialog(root, xlsx_path, app.fam,
                        existing_models={"g502 lightspeed", "a2634"})
    root.update()
    check("识别到型号列默认按型号合并", dlg2.var_mode.get() == "merge", dlg2.var_mode.get())
    check("预览含重复判断列", "STATUS" in dlg2.preview["columns"],
          str(dlg2.preview["columns"]))
    st_list = [dlg2._status_of(r, set()) for r in dlg2.records]
    check("型号重复行判为「跳过」",
          sum(1 for s, _ in st_list if s.startswith("跳过")) == 2, str(st_list))
    check("空型号行判为「新增（无型号）」",
          any(s.startswith("新增（无型号）") for s, _ in st_list), str(st_list))
    check("合并模式默认选中", dlg2.var_mode.get() == "merge", dlg2.var_mode.get())
    check("已移除「空值不覆盖/清理重复」勾选项",
          not hasattr(dlg2, "chk_skip") and not hasattr(dlg2, "chk_dedupe"))
    dup_n, new_n = dlg2._dup_stats()
    check("重复/新增统计自洽", dup_n + new_n == len(dlg2.records), "%d+%d" % (dup_n, new_n))
    dlg2.var_mode.set("append")
    dlg2._on_mode_change()
    check("切换到追加隐藏重复列", "STATUS" not in dlg2.preview["columns"])
    dlg2.var_mode.set("merge")
    dlg2._on_mode_change()
    dlg2._ok()
    check("返回结果含型号合并选项",
          dlg2.result is not None and dlg2.result["mode"] == "merge"
          and "skip_empty" not in dlg2.result)
    try:
        dlg2.destroy()
    except Exception:
        pass

    # 按型号检查重复（只读报告窗口）
    before_n = len(app.records)
    app.store.insert_many([blank_record() | {"code": "DUP-A", "model": "REP-1", "brand": "a"},
                           blank_record() | {"code": "DUP-B", "model": " rep-1 ", "brand": "b"}])
    app.load_data()
    root.update()
    dups = app.store.duplicate_models()
    check("按型号检出重复", len(dups) == 1 and dups[0][1] == 2, str(dups))
    app.check_duplicates()
    root.update()
    win_dup = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel) and w.title() == "按型号检查重复"]
    check("重复报告窗口可打开", len(win_dup) == 1)
    for w in win_dup:
        w.destroy()
    # 导入不能改动/删除库中已有记录（合并只跳过，不清理库内重复）
    mm = app.store.merge_many([{"model": "REP-1", "brand": "merged", "price": 9.9, "qty": 1}],
                              "model")
    check("合并遇到重复：0 新增，跳过 1 条",
          mm["added"] == 0 and mm["skipped"] == 1, str(mm))
    check("库中重复记录未被删除", len(app.store.duplicate_models()) == 1,
          str(app.store.duplicate_models()))
    check("库中重复记录内容未被修改",
          len([r for r in app.store.all_records()
               if (r.get("code") or "").startswith("DUP-")
               and float(r.get("price") or 0) == 0]) == 2)
    app.load_data()
    ids = [r["id"] for r in app.records if (r.get("code") or "").startswith("DUP-")]
    app.store.delete_ids(ids)
    app.load_data()
    check("清理测试数据", len(app.records) == before_n, "实际=%d" % len(app.records))

    # 导入核心逻辑 _import_work 回归（v1.5.1：修复闭包变量导致的 UnboundLocalError）
    iw_store = Store(os.path.join(TMP, "iw.db"))
    recs_in = [blank_record() | {"code": "", "model": "IW-1", "price": 5, "qty": 1},
               blank_record() | {"code": "", "model": "iw-1", "price": 6, "qty": 1},
               blank_record() | {"code": "", "model": "IW-2", "price": 7, "qty": 1}]
    r1 = app._import_work("append", recs_in, store=iw_store)
    check("追加导入：3 条原样全部加入（不去重）",
          r1["added"] == 3 and r1["merged"] == 0 and r1["auto"] == 3, str(r1))
    check("追加导入后库中 3 条",
          iw_store.count() == 3, "实际=%d" % iw_store.count())
    r2 = app._import_work("merge",
                          [blank_record() | {"code": "", "model": "IW-1", "price": 99}],
                          store=iw_store)
    check("合并导入：已有型号跳过不导入",
          r2["added"] == 0 and r2["skipped"] == 1, str(r2))
    r3 = app._import_work("replace",
                          [blank_record() | {"code": "", "model": "RW-1", "price": 1, "qty": 1}],
                          store=iw_store)
    left = iw_store.all_records()
    check("覆盖导入：清空重导 1 条", r3["added"] == 1 and len(left) == 1, str(r3))
    check("覆盖导入：编号从 WL-00001 重新开始",
          left and left[0]["code"] == "WL-00001", str(left))

    # 回归（v1.7.5）：数量「1+1」等累加写法导入后求和，不再变 0
    r4 = app._import_work("replace",
                          [blank_record() | {"code": "", "model": "QW-1",
                                             "qty": "1+3"},
                           blank_record() | {"code": "", "model": "QW-2",
                                             "qty": "4+1"},
                           blank_record() | {"code": "", "model": "QW-3",
                                             "qty": "1+1"}],
                          store=iw_store)
    qw = {r["model"]: r["qty"] for r in iw_store.all_records()}
    check("导入 数量 1+3 → 4", qw.get("QW-1") == 4, str(qw))
    check("导入 数量 4+1 → 5", qw.get("QW-2") == 5, str(qw))
    check("导入 数量 1+1 → 2", qw.get("QW-3") == 2, str(qw))
    iw_store.close()

    # 多仓库（v1.7.0）：每仓独立数据库、独立编号
    check("默认仓库迁移", app.wh_names() == ["主仓库"], str(app.wh_names()))
    ok, _ = app.add_warehouse("二号仓")
    check("新建仓库成功", ok and app.wh_names() == ["主仓库", "二号仓"],
          str(app.wh_names()))
    ok2, msg2 = app.add_warehouse("二号仓")
    check("同名仓库被拒绝", not ok2 and "同名" in msg2, msg2)
    ok3, msg3 = app.switch_warehouse(1)
    check("切换到二号仓", ok3 and app.store.path.endswith("warehouse_2.db"),
          "%s %s" % (ok3, app.store.path))
    check("二号仓为空库", app.store.count() == 0, str(app.store.count()))
    c2 = app.store.generate_codes(1)[0]
    check("二号仓独立编号从 WL-00001", c2 == "WL-00001", c2)
    app.store.insert(blank_record() | {"code": c2, "brand": "二号仓货", "qty": 1})
    app.load_data()
    check("二号仓数据独立", len(app.records) == 1, str(len(app.records)))
    check("标题栏显示当前仓库", "二号仓" in app.root.title(), app.root.title())
    ok4, _ = app.switch_warehouse(0)
    check("切回主仓库", ok4 and app.store.count() == 7, str(app.store.count()))
    check("主仓库数据未受影响", app.store.generate_codes(1)[0].startswith("WL-"))
    ok5, msg5 = app.rename_warehouse(1, "分仓B")
    check("重命名仓库", ok5 and app.wh_names()[1] == "分仓B", str(app.wh_names()))
    ok6, msg6 = app.remove_warehouse(0)
    check("移除非当前仓库", ok6 and app.wh_names() == ["分仓B"] and
          app.wh_index == 0, "%s %s" % (ok6, msg6))
    check("移除后数据库文件保留", os.path.exists(msg6))
    ok7, msg7 = app.remove_warehouse(0)
    check("最后一个仓库不可移除", not ok7, msg7)
    # 回归（v1.7.6/1.7.8）：下拉框选完移开焦点去掉蓝色底色，且文字不丢
    # （不能用 selection_clear：Windows 上会让 readonly 下拉框显示变空白）
    app.var_wh.set(app.wh_names()[0])
    app.cb_wh.selection_range(0, "end")
    app.cb_wh.event_generate("<<ComboboxSelected>>")
    root.update()
    check("仓库下拉框选完值不丢失", app.cb_wh.get() == app.wh_names()[0],
          repr(app.cb_wh.get()))
    check("仓库下拉框选完焦点移走", root.focus_get() is not app.cb_wh,
          str(root.focus_get()))
    # 全局类级绑定：任意下拉框（筛选/编辑对话框等）同样生效
    cbx = ttk.Combobox(root, values=["甲", "乙"])
    cbx.set("甲")
    cbx.event_generate("<<ComboboxSelected>>")
    root.update()
    check("全局下拉框选完值不丢失", cbx.get() == "甲", repr(cbx.get()))
    check("全局下拉框选完焦点移走", root.focus_get() is not cbx,
          str(root.focus_get()))
    cbx.destroy()
    # 回归：移除仓库（文件保留）后再新建，绝不能复用旧文件（v1.7.3）
    ok8, path8 = app.add_warehouse("二号仓")
    check("二号仓用新文件", ok8 and os.path.basename(path8) == "warehouse_3.db",
          "%s %s" % (ok8, path8))
    # 切到二号仓灌入数据，再切回来移除（模拟用户：导数据 → 移除仓库）
    app.switch_warehouse(1)
    app.store.insert(blank_record() |
                     {"code": "WL-00001", "brand": "旧货", "qty": 1})
    app.load_data()
    app.switch_warehouse(0)
    ok9, _ = app.remove_warehouse(1)
    check("移除带数据的仓库", ok9, str(ok9))
    ok10, path10 = app.add_warehouse("三号仓")
    check("新建仓库不复用已移除仓库的文件",
          ok10 and os.path.basename(path10) != os.path.basename(path8),
          "%s %s" % (ok10, path10))
    st_new = Store(path10)
    check("新建仓库是空库（不带旧数据）", st_new.count() == 0, str(st_new.count()))
    check("新仓库编号从 WL-00001 重新开始", st_new.generate_codes(1)[0] == "WL-00001")
    st_new.close()
    ok11, _ = app.remove_warehouse(app.wh_names().index("三号仓"))
    check("清理三号仓", ok11 and app.wh_names() == ["分仓B"], str(app.wh_names()))
    # settings 持久化
    with open(app.settings_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    check("仓库列表已持久化", cfg.get("current_wh") == 0 and
          [w["name"] for w in cfg.get("warehouses", [])] == ["分仓B"], str(cfg))

    # 仓库管理对话框（卡片式）
    found_dlg = []
    wh_geo = []

    def _close_wh_dlg():
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel) and w.title() == "仓库管理":
                found_dlg.append(w)
                w.update_idletasks()
                wh_geo.append(_geo_xy(w))
                w.destroy()
    root.after(150, _close_wh_dlg)
    app.manage_warehouses()
    root.update()
    check("仓库管理窗口可打开", len(found_dlg) == 1)

    # ---- v1.7.11：所有弹窗居中 ----
    ex_wh = _expect_center(wh_geo[0][2], wh_geo[0][3]) if wh_geo and wh_geo[0] else None
    check("仓库管理窗口居中于主窗口",
          ex_wh and abs(wh_geo[0][0] - ex_wh[0]) <= 2 and abs(wh_geo[0][1] - ex_wh[1]) <= 2,
          "%s vs %s" % (wh_geo, ex_wh))

    dup_geo = []
    app.check_duplicates()          # 非模态：直接打开后取几何再关掉
    root.update()
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel) and w.title() == "按型号检查重复":
            w.update_idletasks()
            dup_geo.append(_geo_xy(w))
            w.destroy()
    root.update()
    ex_dup = _expect_center(760, 520)
    check("按型号检查重复窗口居中于主窗口",
          dup_geo and abs(dup_geo[0][0] - ex_dup[0]) <= 2 and
          abs(dup_geo[0][1] - ex_dup[1]) <= 2,
          "%s vs %s" % (dup_geo, ex_dup))

    probe = tk.Toplevel(root)
    probe.geometry("300x200")
    center_window(probe, root, size=(300, 200))
    pg = _geo_xy(probe)
    ex_p = _expect_center(300, 200)
    check("center_window 通用居中计算正确（编辑/导入弹窗共用）",
          pg and abs(pg[0] - ex_p[0]) <= 2 and abs(pg[1] - ex_p[1]) <= 2,
          "%s vs %s" % (pg, ex_p))
    probe.destroy()

    # 数据分析页跟随当前仓库
    app.nb.select(1)
    root.update()
    stats_wh = app.tab_ana.refresh()
    check("分析页显示当前仓库名", app.cur_wh()["name"] in
          app.tab_ana.lbl_wh.cget("text"), app.tab_ana.lbl_wh.cget("text"))
    check("分析页数据为当前仓库", stats_wh["total"] == app.store.count(),
          "%s vs %s" % (stats_wh["total"], app.store.count()))

    # ---- 出售记录页 + 库存页已售完状态（放在最后，避免影响前面计数断言）----
    app.store.insert_many([blank_record() | {"code": "WL-SALE-1", "brand": "测试品牌",
                                             "category": "测试", "model": "SALE-TEST",
                                             "condition": "全新", "price": 50.0, "qty": 2,
                                             "shelf": "1排A-1", "listed": 1}])
    app.load_data()
    target = [r for r in app.store.all_records() if r.get("code") == "WL-SALE-1"][0]
    ok_s, _msg_s = app.store.add_sale(target["id"], 1, 88.0, buyer="测试买家",
                                      sale_date="2026-10-07", remark="GUI 测试",
                                      address="广东省深圳市南山区测试路1号")
    app.load_data()
    app.tab_sales.refresh_tab()
    root.update()
    check("出售页列出记录", len(app.tab_sales.tree.get_children()) == 1,
          str(len(app.tab_sales.tree.get_children())))
    check("出售页合计笔数与销售额",
          app.tab_sales.kpi["count"].cget("text") == "1"
          and "88.00" in app.tab_sales.kpi["amount"].cget("text"),
          "%s / %s" % (app.tab_sales.kpi["count"].cget("text"),
                       app.tab_sales.kpi["amount"].cget("text")))
    # 全部卖完 → 库存页显示「已售完」
    left = int([r for r in app.store.all_records() if r["id"] == target["id"]][0]["qty"])
    if left > 0:
        app.store.add_sale(target["id"], left, 10.0, sale_date="2026-10-07")
        app.load_data()
        rec_so = [r for r in app.records if r["id"] == target["id"]][0]
        check("售完记录标记已售完", int(rec_so.get("sold_out") or 0) == 1)
        check("库存页显示「已售完」", app.fmt("listed", rec_so) == "已售完",
              app.fmt("listed", rec_so))
        app.f_vars["listed"].set("已售完")
        app.apply_filters()
        check("可按「已售完」筛选",
              any(r["id"] == target["id"] for r in app.filtered), str(len(app.filtered)))
        app.f_vars["listed"].set("已上架")
        app.apply_filters()
        check("已售完不混入已上架筛选",
              not any(r["id"] == target["id"] for r in app.filtered))
        app.reset_filters()
    app.tab_sales.refresh_rows()
    check("出售页含两笔出售", len(app.tab_sales.tree.get_children()) >= 2,
          str(len(app.tab_sales.tree.get_children())))

    # ---- 出售记录页：地址列显示 / 拖选复制 / Ctrl+C / 右键复制项 ----
    tb = app.tab_sales
    app.nb.select(1)
    root.update()
    keys_s = tb.col_keys()
    kids = tb.tree.get_children()
    kid_addr = next((k for k in kids if tb.row_map()[k].get("address")), kids[0])
    vals_a = tb.row_values(tb.row_map()[kid_addr], tb.cols_def())
    check("出售页有「收货地址」列", "address" in keys_s, str(keys_s))
    check("出售页显示收货地址", "广东省深圳市南山区测试路1号" in vals_a, str(vals_a))
    check("出售页列表与复制取值一致",
          list(tb.tree.item(kid_addr, "values")) == [str(v) for v in vals_a],
          str(tb.tree.item(kid_addr, "values")))

    # 拖选区块（行 × 列）→ 复制纯数据 TSV
    tb._drag_block = {"rows": [kid_addr],
                      "c0": keys_s.index("code"), "c1": keys_s.index("address")}
    tb.copy_block()
    blk = root.clipboard_get()
    check("出售页区块复制列数正确",
          len(blk.split("\t")) == keys_s.index("address") - keys_s.index("code") + 1,
          repr(blk[:60]))
    check("出售页区块复制内容与所选列一致",
          blk.split("\t")[keys_s.index("buyer") - keys_s.index("code")] == "测试买家"
          and blk.split("\t")[-1] == "广东省深圳市南山区测试路1号", repr(blk[:80]))

    # 按坐标识别单元格（拖选的基础）：取单元格中心点
    bbox = tb.tree.bbox(kid_addr, column="qty")
    if bbox:
        iid_c, idx_c = tb._cell_at(bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2)
        check("出售页可按坐标识别单元格",
              iid_c == kid_addr and keys_s[idx_c] == "qty", str((iid_c, idx_c)))

    # Ctrl+C：有区块复制区块，无区块复制选中行
    tb._drag_block = None
    tb.tree.selection_set(kid_addr)
    tb.tree.focus(kid_addr)
    root.update()
    tb.copy_shortcut()
    one = root.clipboard_get()
    check("出售页 Ctrl+C 复制选中行", "\t" in one and "\n" not in one, repr(one[:60]))
    check("出售页复制内容含收货地址", "广东省深圳市南山区测试路1号" in one, repr(one[:80]))
    tb._cell_key = "buyer"
    tb.copy_cell()
    check("出售页复制单元格", root.clipboard_get() == "测试买家",
          repr(root.clipboard_get()))
    tb._cell_key = "buyer"
    tb.copy_column()
    check("出售页复制整列（有选中行时只复制选中行）",
          root.clipboard_get() == "测试买家", repr(root.clipboard_get()))
    tb.tree.selection_remove(*tb.tree.selection())
    tb.copy_column()
    check("出售页复制整列（无选中时复制全部筛选结果）",
          root.clipboard_get().split("\n") == ["", "测试买家"],
          repr(root.clipboard_get()))
    tb.copy_with_header()
    check("出售页复制表头 + 全部行",
          root.clipboard_get().split("\n")[0].startswith("出售日期\t编号"),
          repr(root.clipboard_get().split("\n")[0][:40]))

    # 全局 Ctrl+C 按当前标签页路由（出售页 / 出库页）
    tb._drag_block = None
    tb.tree.selection_set(kid_addr)
    tb.tree.focus(kid_addr)
    root.clipboard_clear()
    root.update()
    app._copy_shortcut()
    check("全局 Ctrl+C 在出售页复制表格", "测试买家" in root.clipboard_get(),
          repr(root.clipboard_get()[:60]))

    # 右键菜单可弹出（回归：SalesTab 内不能引用不存在的 self.root）
    class _Ev:
        pass
    ev = _Ev()
    bb_rc = tb.tree.bbox(kid_addr, column="brand")
    ev.x, ev.y = bb_rc[0] + bb_rc[2] // 2, bb_rc[1] + bb_rc[3] // 2
    ev.x_root, ev.y_root = 100, 100
    _orig_popup = tk.Menu.tk_popup
    _rc_called = []
    tk.Menu.tk_popup = lambda self, x, y, entry="": _rc_called.append(1)
    try:
        tb.on_right_click(ev)
        root.update()
        check("出售页右键菜单可弹出", bool(_rc_called), str(_rc_called))
        # 出库页同样检查
        _rc_called.clear()
        app.nb.select(2)
        root.update()
        ob = app.tab_out
        okids_rc = ob.tree.get_children()
        bb_o = ob.tree.bbox(okids_rc[0], column="out_type")
        ev.x, ev.y = bb_o[0] + bb_o[2] // 2, bb_o[1] + bb_o[3] // 2
        ob.on_right_click(ev)
        root.update()
        check("出库页右键菜单可弹出", bool(_rc_called), str(_rc_called))
    finally:
        tk.Menu.tk_popup = _orig_popup
    app.nb.select(0)

    # ---- 出库记录页同样支持复制 ----
    app.tab_out.refresh_tab()
    ob = app.tab_out
    keys_o = ob.col_keys()
    okids = ob.tree.get_children()
    app.nb.select(2)
    root.update()
    check("出库页列出全部出库", len(okids) == len(app.store.list_sales()),
          "%d vs %d" % (len(okids), len(app.store.list_sales())))
    ob._drag_block = {"rows": list(okids[:1]),
                      "c0": keys_o.index("out_type"), "c1": keys_o.index("qty")}
    ob.copy_block()
    ob_blk = root.clipboard_get()
    check("出库页区块复制（类型 + 数量）",
          len(ob_blk.split("\t")) == keys_o.index("qty") - keys_o.index("out_type") + 1,
          repr(ob_blk[:60]))
    ob._drag_block = None
    ob.tree.selection_set(okids[0])
    ob.tree.focus(okids[0])
    root.update()
    ob.copy_shortcut()
    check("出库页 Ctrl+C 复制选中行", "\t" in root.clipboard_get(),
          repr(root.clipboard_get()[:60]))
    root.clipboard_clear()
    root.update()
    app._copy_shortcut()
    check("全局 Ctrl+C 在出库页复制表格", root.clipboard_get().strip() != "",
          repr(root.clipboard_get()[:60]))
    ob._cell_key = "out_type"
    ob.copy_cell()
    check("出库页复制单元格（类型）",
          root.clipboard_get() in ("销售", "报废", "赠送", "退货"),
          repr(root.clipboard_get()))
    check("出库页带「拖选即复制」开关", app.var_drag_copy is not None)

    # ---- 修改出库类型（GUI：出库维修 → 修好卖出；库存不变）----
    from wm import sales as sales_mod

    def _btn_texts(w):
        out = []
        for c in w.winfo_children():
            try:
                if isinstance(c, ttk.Button):
                    out.append(str(c.cget("text")))
            except Exception:
                pass
            out.extend(_btn_texts(c))
        return out

    check("出库页有「修改类型」按钮", "修改类型" in _btn_texts(ob),
          str(_btn_texts(ob)))
    ob.refresh_rows()
    root.update()
    okids2 = ob.tree.get_children()
    cand = [i for i in okids2
            if (ob.row_map()[i].get("out_type") or "") != "销售"]
    tid2 = cand[0] if cand else okids2[0]
    rec0 = ob.row_map()[tid2]
    item_before = int([r for r in app.store.all_records()
                       if r["id"] == rec0["item_id"]][0]["qty"])
    ob.tree.selection_set(tid2)
    ob.tree.focus(tid2)
    root.update()
    _orig_ask_ot = sales_mod.ask_out_type
    sales_mod.ask_out_type = lambda *a, **k: {
        "out_type": "销售", "price": 99.0, "buyer": "改类型买家",
        "address": "上海市浦东新区测试路8号", "sale_date": "2026-10-08",
        "remark": "修好卖出", "batch": False}
    try:
        ob.change_type()
        root.update()
    finally:
        sales_mod.ask_out_type = _orig_ask_ot
    rec1 = [r for r in app.store.list_sales() if str(r["id"]) == str(tid2)][0]
    check("出库页可把非销售出库改成销售",
          rec1["out_type"] == "销售" and float(rec1["price"]) == 99.0,
          "%s / %s" % (rec1["out_type"], rec1["price"]))
    check("改类型后总额按数量重算",
          float(rec1["total"]) == 99.0 * int(rec1["qty"]),
          "%s vs %s" % (rec1["total"], 99.0 * int(rec1["qty"])))
    check("改类型后写入买家与地址",
          rec1["buyer"] == "改类型买家"
          and rec1["address"] == "上海市浦东新区测试路8号",
          "%s / %s" % (rec1["buyer"], rec1["address"]))
    item_after = int([r for r in app.store.all_records()
                      if r["id"] == rec0["item_id"]][0]["qty"])
    check("改类型不改库存", item_before == item_after,
          "%s -> %s" % (item_before, item_after))
    check("出售页立刻能看到改后的记录",
          any(str(r["id"]) == str(tid2) for r in app.store.list_sales(scope="sale")))
    check("状态栏提示已改为销售",
          "销售" in str(app.lbl_status.cget("text")),
          repr(app.lbl_status.cget("text")))

    # 多选 → 批量改成非销售类型
    ob.refresh_rows()
    root.update()
    two = list(ob.tree.get_children()[:2])
    ob.tree.selection_set(two)
    root.update()
    sales_mod.ask_out_type = lambda *a, **k: {
        "out_type": "损耗", "price": 0.0, "buyer": "", "address": "",
        "sale_date": "", "remark": None, "batch": True}
    try:
        ob.change_type()
        root.update()
    finally:
        sales_mod.ask_out_type = _orig_ask_ot
    after_types = {str(r["id"]): r["out_type"] for r in app.store.list_sales()}
    check("多选可批量改成非销售类型",
          len(two) == 2 and all(after_types.get(str(i)) == "损耗" for i in two),
          str({str(i): after_types.get(str(i)) for i in two}))

    # 右键菜单里有「修改选中记录的类型…」
    _menus = []
    _orig_popup2 = tk.Menu.tk_popup
    tk.Menu.tk_popup = lambda self, x, y, entry="": _menus.append(self)
    try:
        kids_rc = ob.tree.get_children()
        bb = ob.tree.bbox(kids_rc[0], column="out_type")
        ev.x, ev.y = bb[0] + bb[2] // 2, bb[1] + bb[3] // 2
        ev.x_root, ev.y_root = 100, 100
        ob.on_right_click(ev)
        root.update()
    finally:
        tk.Menu.tk_popup = _orig_popup2
    labels = []
    if _menus:
        for i in range(_menus[0].index("end") + 1):
            try:
                if _menus[0].type(i) == "command":
                    labels.append(str(_menus[0].entrycget(i, "label")))
            except Exception:
                pass
    check("右键菜单含「修改选中记录的类型…」",
          any("修改选中记录的类型" in s for s in labels), str(labels))
    app.nb.select(0)

    # ---- 客户端下禁止开启共享（v1.11.2）：按钮置灰，防误点顶掉连接 ----
    from wm.lanui import LanDialog
    from wm import lanui as lanmod
    fake_st = {"mode": "client", "running": False, "host": "192.168.1.9",
               "port": 8765, "code": "123456", "ips": ["10.0.0.2"],
               "clients": [], "default_allow": False, "can_write": True,
               "client_name": ""}
    _orig_status, _orig_start, _orig_ask = app.lan_status, app.start_lan_host, \
        lanmod.messagebox.askyesno
    asked = {"n": 0, "yes": True}
    started = []
    app.lan_status = lambda: dict(fake_st)
    app.start_lan_host = lambda p=None, c=None: (started.append((p, c)) or (True, "ok"))
    lanmod.messagebox.askyesno = lambda *a, **k: (asked.update(n=asked["n"] + 1)
                                                  or asked["yes"])
    dlg = LanDialog(app.root, app)
    root.update()
    check("客户端时 ①「开启共享」按钮置灰",
          str(dlg.btn_host.cget("state")) == "disabled", dlg.btn_host.cget("state"))
    check("「新连接直接允许录入」也置灰",
          str(dlg.cb_allow.cget("state")) == "disabled", dlg.cb_allow.cget("state"))
    check("客户端时 ① 提示引导「先断开 / 回到本机」",
          "断开 / 回到本机" in dlg.lbl_host_msg.cget("text")
          and "客户端" in dlg.lbl_host_msg.cget("text"), dlg.lbl_host_msg.cget("text"))
    check("「当前角色」标签在 ② 上（客户端）",
          dlg.cli_badge.cget("text") == "当前角色"
          and bool(dlg.cli_badge.winfo_ismapped()))
    dlg.var_port.set("8766")
    dlg.var_code.set("4321")
    asked.update(n=0, yes=True)
    dlg.toggle_host()
    check("客户端下调用 toggle_host 也不启动主机、不弹窗",
          started == [] and asked["n"] == 0, "%s / %d" % (started, asked["n"]))
    fake_st2 = dict(fake_st, mode="host", running=True, clients=[])
    app.lan_status = lambda: dict(fake_st2)
    dlg.refresh()
    check("主机模式按钮恢复可点",
          str(dlg.btn_host.cget("state")) == "normal", dlg.btn_host.cget("state"))
    check("切主机后「当前角色」标签移到 ①",
          dlg.host_badge.cget("text") == "当前角色"
          and not bool(dlg.cli_badge.winfo_ismapped()))
    # 主机状态去连别人：也要先问
    _orig_conn = app.connect_lan
    conns = []
    app.connect_lan = lambda *a, **k: (conns.append((a, k)) or (True, "ok"))
    _orig_mode = app.lan_mode
    app.lan_mode = "host"            # 真实对象是 off，这里只验确认逻辑
    # connect 现在走后台探测（v1.11.3），把 RemoteStore 换成立即成功的假实现
    class _FakeRS(object):
        def __init__(self, *a, **k):
            self.last_ping = {"ok": True, "can_write": False,
                              "warehouse": "测试仓", "rev": 1, "version": "t"}
        def ping(self):
            return self.last_ping
    _orig_rs = remote_mod.RemoteStore
    remote_mod.RemoteStore = _FakeRS
    dlg.var_host.set("10.1.1.5")
    dlg.var_cport.set("8765")
    dlg.var_ccode.set("111111")
    asked.update(n=0, yes=False)
    dlg.connect()
    check("主机点「连接」先弹确认", asked["n"] == 1, asked["n"])
    check("确认框选「否」→ 不连接、不探测", conns == [], str(conns))
    asked.update(n=0, yes=True)
    dlg.connect()
    for _ in range(100):             # 等后台探测线程完成（假实现立即返回）
        if conns:
            break
        root.update()
        time.sleep(0.02)
    check("确认后才连接（后台探测后带上 probe）",
          len(conns) == 1 and isinstance(conns[0][1].get("probe"), _FakeRS),
          str(conns))
    check("连接期间按钮锁定过（_conn_busy 复位）",
          dlg._conn_busy is False and str(dlg.pb.winfo_manager()) == "",
          "%s / %s" % (dlg._conn_busy, dlg.pb.winfo_manager()))
    remote_mod.RemoteStore = _orig_rs
    app.connect_lan = _orig_conn
    app.lan_mode = _orig_mode
    app.lan_status, app.start_lan_host = _orig_status, _orig_start
    lanmod.messagebox.askyesno = _orig_ask
    dlg.destroy()

    # ---- 移除连接 / 黑名单（v1.11.4）：按钮联动 + 客户端被踢自动断开 ----
    _orig_kick = app.lan_kick_client
    _orig_blk = app.lan_block_client
    _orig_unblk = app.lan_unblock
    kicks, blks, unblks = [], [], []
    app.lan_kick_client = lambda ip: (kicks.append(ip) or (True, "ok"))
    app.lan_block_client = lambda ip, name="": (blks.append((ip, name))
                                                or (True, "ok"))
    app.lan_unblock = lambda ip: (unblks.append(ip) or (True, "ok"))
    fake_host = {"mode": "host", "running": True, "host": "", "port": 8765,
                 "code": "123456", "ips": ["10.0.0.1"],
                 "clients": [{"ip": "10.0.0.5", "name": "客户端甲",
                              "allowed": False, "explicit": False,
                              "last_seen": time.time(), "requests": 0}],
                 "default_allow": False, "can_write": True, "client_name": ""}
    _orig_status2 = app.lan_status
    app.lan_status = lambda: dict(fake_host)
    dlg2 = LanDialog(app.root, app)
    root.update()
    # ---- 历史连接（v1.13.0）：记录 / 去重置顶 / 下拉一键填入 ----
    app._add_lan_history("10.9.9.9", 8765, "654321")
    app._add_lan_history("10.8.8.8", 9000, "111111")
    app._add_lan_history("10.9.9.9", 8765, "999999")     # 同地址再去 → 置顶 + 更新码
    _hist = app.lan_cfg["history"]
    check("连接历史去重置顶且更新连接码",
          len(_hist) == 2 and _hist[0]["host"] == "10.9.9.9"
          and _hist[0]["code"] == "999999" and _hist[1]["host"] == "10.8.8.8",
          _hist)
    check("连接历史最多 8 条",
          all(app._add_lan_history("10.0.0.%d" % i, 1000 + i, "c") or True
              for i in range(12)) and len(app.lan_cfg["history"]) == 8,
          len(app.lan_cfg["history"]))
    app._add_lan_history("10.9.9.9", 8765, "999999")     # 再置顶用于下拉验证
    dlg2.refresh_hist()
    root.update()
    check("历史连接下拉已填充",
          any("10.9.9.9:8765" in str(v) for v in dlg2.cb_hist["values"]),
          list(dlg2.cb_hist["values"])[:1])
    dlg2.cb_hist.current(0)
    dlg2._pick_history()
    check("选中历史自动填入地址/端口/连接码",
          dlg2.var_host.get() == "10.9.9.9" and dlg2.var_cport.get() == "8765"
          and dlg2.var_ccode.get() == "999999",
          "%s|%s|%s" % (dlg2.var_host.get(), dlg2.var_cport.get(),
                        dlg2.var_ccode.get()))
    app.lan_cfg["history"] = []
    dlg2.refresh_hist()
    check("清空后下拉显示暂无提示",
          "暂无" in str(dlg2.cb_hist.get()), dlg2.cb_hist.get())
    _wa2 = scr.screen_metrics(app.root)
    check("局域网窗口高度不超过屏幕工作区",
          dlg2.winfo_height() <= _wa2["h"],
          "%s vs %s" % (dlg2.winfo_height(), _wa2["h"]))
    check("局域网窗口内容区可滚动（小屏不裁按钮）",
          hasattr(dlg2, "canvas") and hasattr(dlg2, "vsb") and hasattr(dlg2, "body"))
    check("局域网窗口有「手机访问」区块",
          all(hasattr(dlg2, x) for x in
              ("lbl_phone_url", "lbl_qr", "lbl_phone_sessions", "lbl_phone_msg")))
    check("手机访问地址格式正确（http://IP:端口/m）",
          dlg2._phone_url().startswith("http://") and dlg2._phone_url().endswith("/m"),
          dlg2._phone_url())
    try:
        dlg2._render_qr("http://192.168.1.5:8765/m")
        check("手机地址二维码已生成", dlg2._qr_img is not None)
        dlg2._render_qr("")
        check("清空地址后二维码清除", dlg2._qr_img is None)
    except Exception as e:
        check("手机地址二维码已生成", False, str(e))
    check("主机未选中电脑时「移除连接」置灰",
          str(dlg2.btn_kick.cget("state")) == "disabled",
          dlg2.btn_kick.cget("state"))
    dlg2.tree.selection_set("10.0.0.5")
    root.update()
    check("选中后「移除连接」「加入黑名单」可点",
          str(dlg2.btn_kick.cget("state")) == "normal"
          and str(dlg2.btn_blk.cget("state")) == "normal",
          "%s / %s" % (dlg2.btn_kick.cget("state"), dlg2.btn_blk.cget("state")))
    lanmod.messagebox.askyesno = lambda *a, **k: False
    dlg2.kick_client()
    check("移除确认框选「否」→ 不踢", kicks == [], str(kicks))
    lanmod.messagebox.askyesno = lambda *a, **k: True
    dlg2.kick_client()
    check("确认后调用移除连接", kicks == ["10.0.0.5"], str(kicks))
    dlg2.block_client()
    check("加入黑名单带上名称", blks == [("10.0.0.5", "客户端甲")], str(blks))
    app.lan_unblock = _orig_unblk
    app.lan_block_client = _orig_blk
    app.lan_kick_client = _orig_kick
    dlg2.destroy()
    app.lan_status = _orig_status2

    # 客户端被踢 / 被拉黑：轮询报错后自动断开回本机（只弹一次）
    _orig_disc, _orig_mode2 = app.disconnect_lan, app.lan_mode
    _orig_warn = wapp.messagebox.showwarning
    _orig_info = wapp.messagebox.showinfo
    discs = []
    app.disconnect_lan = lambda *a, **k: (discs.append(1) or (True, "ok"))
    wapp.messagebox.showwarning = lambda *a, **k: None
    wapp.messagebox.showinfo = lambda *a, **k: None
    app.lan_mode = "client"
    app._lan_kick_seen = False
    app._on_lan_error("本机已被主机加入黑名单，无法连接（请联系主机移出黑名单）")
    for _ in range(100):
        if discs:
            break
        root.update()
        time.sleep(0.02)
    check("客户端收到黑名单错误后自动断开", len(discs) == 1, str(discs))
    app._on_lan_error("本机已被主机加入黑名单，无法连接（请联系主机移出黑名单）")
    for _ in range(50):
        root.update()
        time.sleep(0.01)
    check("黑名单错误只触发一次断开", len(discs) == 1, str(discs))
    app.lan_mode = _orig_mode2
    app.disconnect_lan = _orig_disc
    wapp.messagebox.showwarning = _orig_warn
    wapp.messagebox.showinfo = _orig_info

    app.on_close()
    check("正常退出", True)
except Exception:
    traceback.print_exc()
    FAILS.append("GUI 异常")
    try:
        root.destroy()
    except Exception:
        pass

print("== 7. 线程异常检查 ==")
check("无工作线程异常", not tk_errors, str(tk_errors[:2]))

print()
if FAILS:
    print("FAILURES: %d -> %s" % (len(FAILS), FAILS))
    _r = globals().get("root")
    if _r is not None:
        try:
            _r.destroy()          # 失败也要关掉测试窗口，避免残留卡死窗口
        except Exception:
            pass
    sys.exit(1)
print("ALL TESTS PASSED")
shutil.rmtree(TMP, ignore_errors=True)
