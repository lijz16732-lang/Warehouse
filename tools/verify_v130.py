# -*- coding: utf-8 -*-
"""v1.4.0 导入语义端到端验证（真实数据库副本 + 真实 xlsx）。

规则：
  · 按型号合并：与库中数据对比，型号已存在 → 跳过（原记录不改动不删除）；不存在 → 新增
  · 覆盖导入：先清空，编号从 WL-00001 重新开始
  · 清空全部数据后导入：编号从 WL-00001 重新开始
  · 库中还有数据时导入新增：编号接着最大编号往下排
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wm.xlsxio import read_xlsx, rows_to_records, normalize_record  # noqa: E402
from wm.store import Store, FIELD_KEYS  # noqa: E402

REAL_DB = r"D:\仓库管理工具\data\warehouse.db"
XLSX = r"C:\Users\Administrator\Desktop\已修复1.xlsx"
WORK = os.path.join(ROOT, ".tmpverify")

ok, fail = 0, 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("  [PASS] %s" % name)
    else:
        fail += 1
        print("  [FAIL] %s  %s" % (name, extra))


def fill_codes(store, recs):
    missing = [r for r in recs if not str(r.get("code") or "").strip()]
    if missing:
        codes = iter(store.generate_codes(len(missing)))
        for r in missing:
            r["code"] = next(codes)
    return len(missing)


def load_records():
    headers, rows, meta = read_xlsx(XLSX, None, None)
    recs, mapping, unmapped = rows_to_records(headers, rows)
    recs = [normalize_record(r) for r in recs]
    print("  工作表=%s 表头行=%s 有效行=%d 匹配字段=%d 未识别=%s"
          % (meta["sheet"], meta["header_row"], len(recs),
             len(set(mapping.values())), unmapped))
    return recs


def fresh_copy(tag):
    dst = os.path.join(WORK, "wh_%s.db" % tag)
    for suffix in ("", "-wal", "-shm"):
        p = dst + suffix
        if os.path.exists(p):
            os.remove(p)
    shutil.copy2(REAL_DB, dst)
    return dst


def snapshot(store):
    return {r["id"]: tuple(str(r.get(k)) for k in FIELD_KEYS) for r in store.all_records()}


def main():
    os.makedirs(WORK, exist_ok=True)
    base = load_records()
    src = Store(REAL_DB)
    print("  源库记录数 = %d" % src.count())
    src.close()

    # ---------------------------------------- A. 按型号合并：原有记录一条都不能变
    print("\n== A. 按型号合并 → 只新增，原有记录完全不动 ==")
    st = Store(fresh_copy("merge"))
    before = snapshot(st)
    max_code = max(r["code"] for r in st.all_records() if str(r["code"]).startswith("WL-"))
    # 用真实文件前 200 行导入：大部分型号已存在（应跳过），少数新型号（应新增）
    sample = [dict(r) for r in base[:200]]
    out = st.merge_many(sample, "model")
    after = snapshot(st)
    print("  库中最大编号=%s（%d 条）→ 导入 200 行：新增 %d，跳过 %d，文件内合并 %d"
          % (max_code, len(before), out["added"], out["skipped"], out["merged"]))
    check("跳过 + 新增 + 文件内合并 = 导入行数",
          out["skipped"] + out["added"] + out["merged"] == len(sample), str(out))
    removed = set(before) - set(after)
    check("原有记录一条都没被删除", not removed, str(sorted(removed)[:5]))
    changed = [i for i in before if i in after and before[i] != after[i]]
    check("原有记录内容一条都没被修改", not changed, "被改动的 id=%s" % (changed[:5],))
    check("新增行没有更新动作",
          "updated" not in out and "cleaned" not in out, str(out))
    new_codes = [c for c in (set(after) - set(before))]
    check("新增记录编号接续最大编号",
          all(after[i][0] > max_code for i in new_codes), str(new_codes[:3]))
    st.close()

    # ---------------------------------------- B. 覆盖导入：编号从 1 开始
    print("\n== B. 覆盖导入（先清空再编号）→ 编号从 WL-00001 开始 ==")
    st = Store(fresh_copy("replace"))
    records = [dict(r) for r in base]
    st.clear_all()
    check("清空后记录数为 0", st.count() == 0)
    auto = fill_codes(st, records)
    st.insert_many(records)
    got = sorted(r["code"] for r in st.all_records() if str(r["code"]).startswith("WL-"))
    print("  导入 %d 条，编号 %s ~ %s（自动编号 %d 条）"
          % (st.count(), got[0], got[-1], auto))
    check("覆盖导入首条编号 = WL-00001", got[0] == "WL-00001", got[0])
    check("覆盖导入编号连续无跳号", got == ["WL-%05d" % i for i in range(1, len(got) + 1)])
    check("覆盖导入后数据条数正确", st.count() == len(base), "%d/%d" % (st.count(), len(base)))
    st.close()

    # ---------------------------------------- C. 清空后导入：从 1 开始
    print("\n== C. 清空全部数据 → 重新导入 → 从 WL-00001 开始 ==")
    st = Store(fresh_copy("clear"))
    st.clear_all()
    recs2 = [dict(r) for r in base[:5]]
    fill_codes(st, recs2)
    st.insert_many(recs2)
    got2 = sorted(r["code"] for r in st.all_records())
    check("清空后重新导入从 WL-00001 起",
          got2 == ["WL-%05d" % i for i in range(1, 6)], str(got2))
    st.close()

    # ---------------------------------------- D. 覆盖后再次合并：重复被跳过
    print("\n== D. 覆盖导入后再合并同一份数据 → 全部跳过，编号不变 ==")
    st = Store(fresh_copy("repeat"))
    records = [dict(r) for r in base[:300]]
    st.clear_all()
    fill_codes(st, records)
    st.insert_many(records)
    max_before = max(r["code"] for r in st.all_records())
    again = st.merge_many([dict(r) for r in base[:300]], "model")
    check("重复导入：0 新增", again["added"] == 0, str(again))
    check("重复导入后条数不变", st.count() == 300, "%d" % st.count())
    check("重复导入后最大编号不变",
          max(r["code"] for r in st.all_records()) == max_before, max_before)
    st.close()

    print("\n================ v1.4.0 导入语义验证 ================")
    print("通过 %d 项，失败 %d 项" % (ok, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
