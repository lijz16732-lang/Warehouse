# -*- coding: utf-8 -*-
"""验证：电脑端二维码内容 = 地址 + 真实连接码，且能被 App 同款 ZXing 解码。

跑法：.venv310/Scripts/python.exe tools/_check_qr_conn.py
"""
import os
import subprocess
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wm import lanui                                  # noqa: E402


class FakeDialog:
    """只借 LanDialog 的 _phone_qr_text 逻辑，不建整个窗口。"""

    def __init__(self, code):
        self.var_code = tk.StringVar(value=code)

    def _phone_url(self):
        return "http://192.168.1.5:8765/m"


def main():
    root = tk.Tk()
    root.withdraw()
    dlg = FakeDialog("246810")

    txt = lanui.LanDialog._phone_qr_text(dlg, {"code": "246810"})
    print("二维码内容:", txt)
    assert txt == "http://192.168.1.5:8765/m#c=246810", txt

    # 输入框被改成别的、但主机还在用旧码时，以实际生效的码为准
    dlg.var_code.set("999999")
    txt2 = lanui.LanDialog._phone_qr_text(dlg, {"code": "246810"})
    assert txt2.endswith("#c=246810"), txt2
    print("改了输入框仍取实际连接码:", txt2)

    # 未运行（st 里没有 code）时回退输入框
    txt3 = lanui.LanDialog._phone_qr_text(dlg, {})
    assert txt3.endswith("#c=999999"), txt3
    print("无运行码时回退输入框:", txt3)

    import segno
    png = os.path.join(tempfile.gettempdir(), "qr_conn_check.png")
    segno.make(txt).save(png, kind="png", scale=4, border=2)
    root.destroy()

    java = r"D:\android-build\jdk-17.0.21.0.2+1\bin\java.exe"
    zx = os.path.join(ROOT, "android", "libs", "zxing-core-3.5.3.jar")
    cls = os.path.join(tempfile.gettempdir(), "qrc")
    javac = r"D:\android-build\jdk-17.0.21.0.2+1\bin\javac.exe"
    src = os.path.join(ROOT, "tools", "QrCheck.java")
    subprocess.check_call([javac, "-encoding", "UTF-8", "-cp", zx, "-d", cls, src])
    out = subprocess.check_output([java, "-cp", cls + ";" + zx, "QrCheck", png],
                                  text=True).strip()
    print("ZXing 解码:", out)
    assert out == "QR=" + txt, (out, txt)
    print("OK：电脑端二维码内容可被 App 解码，且包含真实连接码")


if __name__ == "__main__":
    main()
