# -*- coding: utf-8 -*-
"""探针：/m/api/photo_check 核对照片是否还在电脑上（v1.44.5）。
用假 srv 直调 handle_photo_check，覆盖：登录校验、缺照片检测、
参数防御、照片补传后（photo_add 再核对应无缺失）。
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
from wm.mobile import handle_photo_check  # noqa: E402

TMP = tempfile.mkdtemp(prefix="cgm_probe_phchk_")
store_mod.resolve_data_dir = lambda: TMP
st = store_mod.Store(os.path.join(TMP, "probe.db"))


class FakeMobile(object):
    def check(self, token, ip):
        return token == "tok-ok"


class FakeSrv(object):
    mobile = FakeMobile()

    def get_store(self):
        return st


srv = FakeSrv()
IMG = ("data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD//gA7QAAAAAAA"
       "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
       "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
       "AAAAAAAAAAAAAAAAAAAAA//2Q==")

# ① 未登录 → 401
code_, body = handle_photo_check(srv, "1.2.3.4", "bad", {"checks": []})[:2]
ck("未登录 401", code_ == 401 and body.get("need_login"))

# ② 参数不是 list → 400
code_, body = handle_photo_check(srv, "1.2.3.4", "tok-ok",
                                 {"checks": "x"})[:2]
ck("参数非法 400", code_ == 400)

# ③ 手机传一张照片（photo_add 语义：kind=phone, code）
name = st.photo_add("phone", "APP-00001", IMG.split(",")[1], "p1.jpg")
ck("照片已入库", bool(name) and name in st.photos_list("phone", "APP-00001"))

# ④ 核对：照片在 → 无缺失；没传过的编号 → 报缺失
code_, body = handle_photo_check(srv, "1.2.3.4", "tok-ok", {"checks": [
    {"code": "APP-00001", "names": [name]},
    {"code": "APP-00002", "names": ["whatever"]},
]})[:2]
ck("在的不缺、缺的报出", code_ == 200 and body["ok"]
   and body["missing"] == {"APP-00002": ["whatever"]})

# ⑤ 电脑端删掉照片 → 核对报缺失
st.photo_del("phone", "APP-00001", name)
code_, body = handle_photo_check(srv, "1.2.3.4", "tok-ok", {"checks": [
    {"code": "APP-00001", "names": [name]},
]})[:2]
ck("删后报缺失", code_ == 200 and body["missing"] == {"APP-00001": [name]})

# ⑥ 记录被整条删除（照片目录也没了）→ 同样报缺失
import shutil  # noqa: E402
shutil.rmtree(st.photos_dir("phone", "APP-00001"), ignore_errors=True)
code_, body = handle_photo_check(srv, "1.2.3.4", "tok-ok", {"checks": [
    {"code": "APP-00001", "names": [name]},
]})[:2]
ck("记录删光也报缺失", body["missing"] == {"APP-00001": [name]})

# ⑦ 补传后（photo_add 重建）→ 缺失消失
st.photo_add("phone", "APP-00001", IMG.split(",")[1], "p1.jpg")
code_, body = handle_photo_check(srv, "1.2.3.4", "tok-ok", {"checks": [
    {"code": "APP-00001", "names": [name]},
]})[:2]
ck("补传后无缺失", body["missing"] == {})

# ⑧ names 非法 / 空 code 的项被忽略，不炸
code_, body = handle_photo_check(srv, "1.2.3.4", "tok-ok", {"checks": [
    {"code": "", "names": ["x"]}, "junk",
    {"code": "APP-00001"}, {"code": "APP-00001", "names": []},
]})[:2]
ck("脏项忽略", code_ == 200 and body["ok"] and body["missing"] == {})

print("\nALL %d PASSED" % PASS)
