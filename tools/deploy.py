# -*- coding: utf-8 -*-
"""把 dist 里的新 exe 部署到 D:\\仓库管理工具\\（覆盖旧版）。

顺序固定：先备份线上库 → 再替换 exe → 最后 md5 校验。
exe 被占用（程序还开着）时直接报错退出，不强行删除——D 盘 exe 不能直接写，
必须"先删后放"，删不掉说明进程在跑。

用法：
    python tools/deploy.py            # 部署 dist/仓管家-仓库管理系统.exe
    python tools/deploy.py --no-db    # 只换 exe，不动库备份
"""

import hashlib
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE_NAME = "仓管家-仓库管理系统.exe"
SRC = os.path.join(ROOT, "dist", EXE_NAME)
TARGET_DIR = os.environ.get("CGM_DEPLOY_DIR", r"D:\仓库管理工具")


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def backup_db(target_dir):
    """用 sqlite backup API 复制线上库（WAL 下直接拷文件可能拿到半截数据）。"""
    src = os.path.join(target_dir, "data", "warehouse.db")
    if not os.path.isfile(src):
        print("跳过库备份：未找到 %s" % src)
        return None
    bdir = os.path.join(target_dir, "backups")
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, "warehouse_%s.db" % time.strftime("%Y%m%d_%H%M"))
    con = sqlite3.connect(src)
    try:
        out = sqlite3.connect(dst)
        try:
            con.backup(out)
        finally:
            out.close()
    finally:
        con.close()
    print("库已备份：%s（%.0f KB）" % (dst, os.path.getsize(dst) / 1024.0))
    return dst


def main():
    no_db = "--no-db" in sys.argv
    if not os.path.isfile(SRC):
        print("找不到产物：%s（先跑 build.py）" % SRC)
        return 2
    if not os.path.isdir(TARGET_DIR):
        print("目标目录不存在，跳过部署：%s" % TARGET_DIR)
        return 0

    dst = os.path.join(TARGET_DIR, EXE_NAME)
    if not no_db:
        backup_db(TARGET_DIR)

    # 旧版留一份，出问题能立刻回退
    if os.path.isfile(dst):
        keep = os.path.join(TARGET_DIR, "backups", "exe_prev_" +
                            time.strftime("%Y%m%d_%H%M") + ".exe")
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        try:
            with open(dst, "rb") as fi, open(keep, "wb") as fo:
                for blk in iter(lambda: fi.read(1 << 20), b""):
                    fo.write(blk)
        except OSError as e:
            print("旧 exe 备份失败（可能正被占用）：%s" % e)

    # 目标盘不能直接覆盖写：先写 .new，再删旧、改名
    tmp = dst + ".new"
    with open(SRC, "rb") as fi, open(tmp, "wb") as fo:
        for blk in iter(lambda: fi.read(1 << 20), b""):
            fo.write(blk)
    try:
        if os.path.exists(dst):
            os.remove(dst)
        os.replace(tmp, dst)
    except OSError as e:
        print("替换失败（程序是不是还开着？请先关闭仓管家再重试）\n  %s" % e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return 3

    a, b = md5(SRC), md5(dst)
    print("源  md5: %s" % a)
    print("目标 md5: %s" % b)
    if a != b:
        print("校验不一致！部署可能损坏")
        return 4
    print("已部署到 %s（%.1f MB）" % (dst, os.path.getsize(dst) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
