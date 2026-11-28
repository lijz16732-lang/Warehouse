# -*- coding: utf-8 -*-
"""GitHub Release 发版脚本（v1.45.7 云更新）。

用法：
    .venv310/Scripts/python.exe tools/release.py                # exe+apk 全发
    .venv310/Scripts/python.exe tools/release.py --exe         # 只发电脑端
    .venv310/Scripts/python.exe tools/release.py --apk         # 只发手机端

做什么：
1. 读 wm/constants.py 的 APP_VERSION 与 AndroidManifest 的 versionCode/Name
2. 计算 dist/ 安装包 md5
3. GitHub API 创建/复用 release tag vX.Y.Z，上传安装包（ASCII 文件名）
4. 生成 deploy/version.json（客户端检查更新的依据）并 commit+push

凭据：静默走 git credential helper（不打印 token）；网络走本机代理
127.0.0.1:7897（--no-proxy 关闭）。失败给出可操作的报错。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
REPO_HOST = "github.com"
PROXY = "http://127.0.0.1:7897"


def read_version():
    src = open(os.path.join(ROOT, "wm", "constants.py"), encoding="utf-8").read()
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
    assert m, "constants.py 里找不到 APP_VERSION"
    return m.group(1)


def read_apk_version():
    mf = open(os.path.join(ROOT, "android", "AndroidManifest.xml"),
              encoding="utf-8").read()
    code = re.search(r'android:versionCode="(\d+)"', mf)
    name = re.search(r'android:versionName="([^"]+)"', mf)
    assert code and name, "AndroidManifest 缺 versionCode/versionName"
    return int(code.group(1)), name.group(1)


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_token():
    """静默从 git credential helper 取 token（绝不打印）。"""
    q = subprocess.run(["git", "credential", "fill"],
                       input="protocol=https\nhost=%s\n\n" % REPO_HOST,
                       capture_output=True, text=True)
    m = re.search(r"^password=(.+)$", q.stdout, re.M)
    if not m:
        raise SystemExit("拿不到 GitHub 凭据：请先在本机 git push 一次（已保存凭据）")
    return m.group(1).strip()


def api(method, url, token, data=None, raw=None, ctype=None, ok404=False):
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        ctype = "application/json"
    elif raw is not None:
        body = raw
    else:
        body = None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "token " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "cangguanjia-release")
    if body is not None:
        req.add_header("Content-Type", ctype)
    handlers = []
    if "--no-proxy" not in sys.argv:
        handlers.append(urllib.request.ProxyHandler(
            {"http": PROXY, "https": PROXY}))
    else:
        # 关键：显式空 ProxyHandler，否则 urllib 仍会读环境变量里的代理
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            if not raw.strip():
                return None          # 204 等空响应（DELETE 资产）
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        if ok404 and e.code == 404:
            return None
        detail = e.read().decode("utf-8", "replace")[:500]
        raise SystemExit("GitHub API %s %s 失败：HTTP %d\n%s"
                         % (method, url, e.code, detail))


def upload_asset(token, repo, rel_id, path, name):
    url = ("https://uploads.github.com/repos/%s/releases/%d/assets?name=%s"
           % (repo, rel_id, urllib.parse.quote(name)))
    raw = open(path, "rb").read()
    api("POST", url, token, raw=raw, ctype="application/octet-stream")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", action="store_true", help="只发电脑端")
    ap.add_argument("--apk", action="store_true", help="只发手机端")
    ap.add_argument("--notes", default="", help="版本说明（写进 version.json.notes）")
    ap.add_argument("--no-proxy", action="store_true")
    args = ap.parse_args()
    send_exe = args.exe or not (args.exe or args.apk)
    send_apk = args.apk or not (args.exe or args.apk)

    ver = read_version()
    apk_code, apk_name = read_apk_version()
    repo = re.sub(r"^.*github\.com[:/]", "",
                  subprocess.run(["git", "remote", "get-url", "origin"],
                                 capture_output=True, text=True,
                                 cwd=ROOT).stdout.strip())
    repo = re.sub(r"\.git$", "", repo)
    print("repo:", repo, "| exe:", ver, "| apk:", apk_name, "(code %d)" % apk_code)

    files = []          # (本地路径, release 资产名, 端标识)
    exe_path = os.path.join(DIST, "仓管家-仓库管理系统.exe")
    apk_path = os.path.join(DIST, "仓管家手机版.apk")
    if send_exe:
        assert os.path.exists(exe_path), "先跑 build.py 打包 exe"
        files.append((exe_path, "WarehouseManager-%s.exe" % ver, "exe"))
    if send_apk:
        assert os.path.exists(apk_path), "先跑 android/build_apk.py 打包 APK"
        files.append((apk_path, "cangguanjia-mobile-%s.apk" % apk_name, "apk"))

    token = git_token()
    base = "https://%s/%s" % (REPO_HOST, repo)
    tag = "v" + ver

    # 1) 建或复用 release
    rel = api("GET", "https://api.github.com/repos/%s/releases/tags/%s"
              % (repo, tag), token, ok404=True)
    if rel is None:
        rel = api("POST", "https://api.github.com/repos/%s/releases" % repo,
                  token, data={"tag_name": tag, "name": tag,
                               "body": args.notes or ("仓管家 %s" % ver),
                               "draft": False, "prerelease": False})
        print("已创建 release", tag)
    else:
        print("复用已有 release", tag)
    rel_id = rel["id"]

    # 2) 上传资产（已存在的同名资产先删再传，支持重跑）
    have = {a["name"]: a["id"] for a in rel.get("assets") or []}
    for path, name, _kind in files:
        if name in have:
            api("DELETE", "https://api.github.com/repos/%s/releases/assets/%d"
                % (repo, have[name]), token)
            print("已删旧资产", name)
        upload_asset(token, repo, rel_id, path, name)
        print("已上传", name, "(%d MB)" % (os.path.getsize(path) >> 20))

    # 3) 生成 version.json 并 push
    info = {"check": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "repo": repo}
    for path, name, kind in files:
        if kind == "exe":
            info["exe"] = {"version": ver,
                           "url": "%s/releases/download/%s/%s"
                                  % (base, tag, name),
                           "md5": md5_of(path),
                           "notes": args.notes}
        else:
            info["apk"] = {"versionCode": apk_code, "versionName": apk_name,
                           "url": "%s/releases/download/%s/%s"
                                  % (base, tag, name),
                           "md5": md5_of(path),
                           "notes": args.notes}
    if send_exe and "exe" not in info:
        info["exe"] = json.loads(
            open(os.path.join(ROOT, "deploy", "version.json"),
                 encoding="utf-8").read())["exe"]
    if send_apk and "apk" not in info:
        info["apk"] = json.loads(
            open(os.path.join(ROOT, "deploy", "version.json"),
                 encoding="utf-8").read())["apk"]

    vdir = os.path.join(ROOT, "deploy")
    os.makedirs(vdir, exist_ok=True)
    vpath = os.path.join(vdir, "version.json")
    with open(vpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("version.json 已生成")

    env = dict(os.environ)
    if "--no-proxy" not in sys.argv:
        env["https_proxy"] = PROXY
        env["http_proxy"] = PROXY
    # 本地 git 留档（代理可用时 push）；正式通道走 Contents API（见下）
    r = subprocess.run(["git", "add", "deploy/version.json"], cwd=ROOT,
                       env=env, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "release: %s version.json" % tag],
                   cwd=ROOT, env=env, capture_output=True, text=True)

    # 用 Contents API 把 version.json 写进仓库（api.github.com 直连稳定，
    # 不依赖 git push 通道——git 443 常被重置而 API 能通）
    import base64
    content = base64.b64encode(
        open(vpath, "rb").read()).decode("ascii")
    old = api("GET", "https://api.github.com/repos/%s/contents/%s"
              % (repo, "deploy/version.json"), token, ok404=True)
    put = {"message": "release: %s version.json" % tag,
           "content": content}
    if old and isinstance(old, dict) and old.get("sha"):
        put["sha"] = old["sha"]
    api("PUT", "https://api.github.com/repos/%s/contents/%s"
        % (repo, "deploy/version.json"), token, data=put)
    print("version.json 已写入仓库（Contents API）")
    for k in ("exe", "apk"):
        if k in info:
            print("  %s: v%s md5=%s" % (k, info[k].get("version") or
                                        info[k].get("versionName"),
                                        info[k]["md5"]))
    print("\n完成。客户端检查地址：")
    print("https://raw.githubusercontent.com/%s/main/deploy/version.json" % repo)


if __name__ == "__main__":
    main()
