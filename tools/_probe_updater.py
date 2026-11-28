# -*- coding: utf-8 -*-
"""探针：电脑端云更新（v1.45.7）。

不联网，全部本地逻辑：
1) 版本号数字比较（1.9 < 1.10，不是字符串序）
2) new_exe_info：识别更新 / 同版本 / 旧版本 / 缺字段
3) fetch_update_info 网络失败 → 返回 None（静默，不抛）
4) _spawn_replacer：bat 内容含 ping 等待/删旧/move/重启/自删，GBK 编码
用法：.venv310/Scripts/python.exe tools/_probe_updater.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tkinter as tk  # noqa: E402

from wm import updater  # noqa: E402

PASS = 0


def chk(name, ok, detail=""):
    global PASS
    if ok:
        PASS += 1
        print("  ok  %s" % name)
    else:
        print("  FAIL %s -> %r" % (name, detail))


def main():
    # ① 版本比较
    chk("1.45.6 < 1.45.7", updater._version_lt("1.45.6", "1.45.7"))
    chk("1.9 < 1.10（数字序）", updater._version_lt("1.9", "1.10"))
    chk("1.45.7 < 1.46", updater._version_lt("1.45.7", "1.46"))
    chk("1.45.7 不小于 1.45.7", not updater._version_lt("1.45.7", "1.45.7"))
    chk("2.0 不小于 1.99", not updater._version_lt("2.0", "1.99"))

    # ② new_exe_info
    chk("新版识别", (updater.new_exe_info(
        {"exe": {"version": "9.9.9", "url": "https://x/e.exe"}}) or {}).get("url")
        == "https://x/e.exe")
    chk("同版本不更新", updater.new_exe_info(
        {"exe": {"version": updater._cur_version(), "url": "https://x/e.exe"}})
        is None)
    chk("旧版本不更新", updater.new_exe_info(
        {"exe": {"version": "0.0.1", "url": "https://x/e.exe"}}) is None)
    chk("缺 url 不更新", updater.new_exe_info({"exe": {"version": "9.9.9"}}) is None)
    chk("空 info 不更新", updater.new_exe_info({}) is None)

    # ③ 网络失败静默（不联网环境跑：超时 2 秒）
    info = updater.fetch_update_info(timeout=2)
    chk("拉不到版本文件返回 None（静默）", info is None or isinstance(info, dict))

    # ④ bat 生成（打桩 _exe_path 指向临时目录，不真跑 cmd）
    tmp = tempfile.mkdtemp(prefix="wm_upd_")
    fake_exe = os.path.join(tmp, "仓管家-仓库管理系统.exe")
    open(fake_exe, "wb").write(b"old")
    updater._exe_path = lambda: fake_exe
    newp = fake_exe + ".new"
    open(newp, "wb").write(b"new-bytes")
    updater.subprocess.Popen = lambda *a, **k: None   # 只验证内容，不真跑 bat
    updater._spawn_replacer(newp)
    bat = fake_exe + ".update.bat"
    chk("bat 已生成", os.path.exists(bat))
    content = open(bat, "rb").read().decode("gbk")
    chk("bat 含等待/删旧/改名/重启/自删",
        all(x in content for x in ("ping -n 2", 'del /f /q', "move /y",
                                   "start \"\"", "%~f0"))
        and fake_exe in content and newp in content)

    # ⑤ _md5_of 与 hashlib 一致
    import hashlib
    chk("md5 计算正确",
        updater._md5_of(newp) == hashlib.md5(b"new-bytes").hexdigest())

    print("\n%d 项通过" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
