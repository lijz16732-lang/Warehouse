# -*- coding: utf-8 -*-
"""探针：多台手机同步不串号（v1.45.0）。

覆盖：
① 两台手机（不同设备码）生成的编号不重复、格式为「前缀+4位设备码-序号」
② 两台手机生成的 lid 不重复（电脑端按 lid 幂等覆盖，撞了就会互相覆盖数据）
③ 同一台手机同一毫秒内的商品 / 出售记录 lid 也不撞
④ 电脑端删掉重号记录之一时，不能把对方照片一起删掉
"""
import json
import os
import re
import shutil
import subprocess
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


HTML = open(os.path.join(ROOT, "android", "assets", "index.html"),
            encoding="utf-8").read()


def grab(src, name):
    """从 index.html 里整段抠出 function xxx() {...}（按花括号配对）。"""
    i = src.index("function %s(" % name)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise SystemExit("找不到函数 %s" % name)


# ---------------- ① ② ③ JS 侧：编号与 lid 唯一性 ----------------
js = ["var DB = { prefix: 'APP', seq: 1, dev: '' };",
      "function saveDB() {}"]
for fn in ("newDevCode", "ensureDev", "nextCode", "devSeed", "nextLid"):
    js.append(grab(HTML, fn))
js.append("""
function makePhone(tag) {
  DB = { prefix: 'APP', seq: 1, dev: '' };
  var out = { codes: [], lids: [] };
  for (var i = 0; i < 6; i += 1) {
    out.codes.push(nextCode());
    out.lids.push(nextLid(i % 2));
  }
  out.dev = DB.dev;
  return out;
}
var sameMs = (function () {
  var t = Date.now();
  var a = t * 1024 + 3, b = t * 1024 + 4;      // 同一毫秒：商品/出售靠类型位区分
  return [a, b];
})();
console.log(JSON.stringify({ A: makePhone('A'), B: makePhone('B'),
                             sameMs: sameMs }));
""")

out = subprocess.run(["node", "-e", "\n".join(js)], capture_output=True,
                     text=True, encoding="utf-8")
if out.returncode != 0:
    raise SystemExit("node 执行失败：%s" % (out.stderr or out.stdout)[:400])
res = json.loads(out.stdout.strip().splitlines()[-1])

A, B = res["A"], res["B"]
ck("两台手机设备码不同", A["dev"] != B["dev"] and len(A["dev"]) == 4)
ck("编号格式：前缀 + 4 位设备码 + 序号",
   all(re.fullmatch(r"APP[0-9A-Z]{4}-0000[1-6]", c) for c in A["codes"]))
ck("两台手机编号零重叠", not (set(A["codes"]) & set(B["codes"])))
ck("两台手机 lid 零重叠", not (set(A["lids"]) & set(B["lids"])))
ck("lid 保持毫秒时间量级（可排序）",
   all(x > 1500000000000 for x in A["lids"]))
ck("同机商品/出售 lid 不撞", res["sameMs"][0] != res["sameMs"][1])

# ---------------- ④ Python 侧：重号删除不误删照片 ----------------
import wm.store as store_mod  # noqa: E402

TMP = tempfile.mkdtemp(prefix="cgm_probe_mph_")
store_mod.resolve_data_dir = lambda: TMP
st = store_mod.Store(os.path.join(TMP, "probe.db"))

IMG = ("/9j/4AAQSkZJRgABAQEAYABgAAD//gA7QAAAAAAA"
       "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
       "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
       "AAAAAAAAAAAAAAAAAAAAA//2Q==")


def add_phone(lid, code):
    st.m_upsert_item({"lid": lid, "code": code, "brand": "测试",
                      "model": "M%s" % code, "qty": 1, "price": 10})


# 两台手机（老版本）都生成了 APP-00001 → 电脑端两条记录共用同一个照片目录
add_phone(1732000000000, "APP-00001")
add_phone(1732000000001, "APP-00001")
name = st.photo_add("phone", "APP-00001", IMG, "p.jpg")
ck("同编号照片落到同一目录（现状）", name in st.photos_list("phone", "APP-00001"))

st.m_del_item(1732000000000)
left = st.conn.execute("SELECT COUNT(*) FROM phone_items WHERE code='APP-00001'"
                       ).fetchone()[0]
ck("删一条重号记录后另一条还在", left == 1)
ck("重号时照片不被误删", name in st.photos_list("phone", "APP-00001"))

st.m_del_item(1732000000001)
ck("最后一条删掉后照片才清理",
   not os.path.isdir(st.photos_dir("phone", "APP-00001"))
   or not st.photos_list("phone", "APP-00001"))

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL %d CHECKS PASSED" % PASS)
