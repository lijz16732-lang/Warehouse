# -*- coding: utf-8 -*-
"""模拟器实测：装包→启动→抓崩溃/初始化日志。用法：
    ./.venv310/Scripts/python.exe tools/_grab_crash.py            # 装 dist/_debug_x86.apk
    ./.venv310/Scripts/python.exe tools/_grab_crash.py --apk X.apk --wait 6
"""
import os
import re
import subprocess
import sys
import time

ADB = r"D:\android-sdk\platform-tools\adb.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "com.cangguanjia.app"


def sh(*args, timeout=120):
    r = subprocess.run([ADB] + list(args), capture_output=True, timeout=timeout)
    return (r.returncode, r.stdout.decode("utf-8", "replace"),
            r.stderr.decode("utf-8", "replace"))


def pick_device():
    _, out, _ = sh("devices")
    devs = [l.split("\t")[0] for l in out.splitlines()[1:] if "\tdevice" in l]
    if not devs:
        sys.exit("没有已连接的设备：先启动模拟器，或 adb connect 127.0.0.1:5555")
    return devs[0]


def main():
    apk = os.path.join(ROOT, "dist", "_debug_x86.apk")
    wait = 6
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--apk":
            apk = argv[i + 1]
        elif a == "--wait":
            wait = int(argv[i + 1])
    if not os.path.isfile(apk):
        sys.exit("找不到 APK：%s" % apk)

    dev = pick_device()
    print("设备：%s  APK：%s" % (dev, os.path.basename(apk)))
    _, out, err = sh("-s", dev, "install", "-r", "-d", apk, timeout=300)
    print("安装：", (out.strip() or err.strip()).splitlines()[-1])

    sh("-s", dev, "shell", "am", "force-stop", PKG)
    sh("-s", dev, "logcat", "-c")
    sh("-s", dev, "shell", "am", "start", "-W", "-n", PKG + "/.MainActivity")
    time.sleep(wait)

    _, pid, _ = sh("-s", dev, "shell", "pidof", PKG)
    alive = bool(pid.strip())
    print("进程存活：", "是 pid=%s" % pid.strip() if alive else "否（崩溃或未启动）")
    print("顶层 Activity：")
    _, top, _ = sh("-s", dev, "shell", "dumpsys", "activity", "activities")
    print("  " + "\n  ".join([l.strip() for l in top.splitlines()
                              if "mResumedActivity" in l or "topResumedActivity" in l][:3]))

    _, log, _ = sh("-s", dev, "logcat", "-d", "-v", "time")
    keep = []
    hot = re.compile(r"(FATAL EXCEPTION|AndroidRuntime|Process: %s|Caused by|"
                     r"mlkit|MlKit|Unable to (get|instantiate)|"
                     r"ClassNotFound|NoClassDefFound|UnsatisfiedLink|"
                     r"ActivityManager.*%s|ContentProvider)" % (PKG, PKG), re.I)
    for line in log.splitlines():
        if hot.search(line):
            keep.append(line)
    print("\n=== 关键日志（%d 行）===" % len(keep))
    print("\n".join(keep[-120:]) or "（无）")


if __name__ == "__main__":
    main()
