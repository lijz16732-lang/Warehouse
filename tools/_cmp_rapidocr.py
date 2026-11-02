# -*- coding: utf-8 -*-
"""对比实测：同一批「小字标签」素材，RapidOCR（PP-OCR ONNX）能认出多少。

用法：.venvocr/Scripts/python.exe tools/_cmp_rapidocr.py
素材：.tmpdbg/ocr_cases/*.png（tools/_mk_ocr_cases.py 生成）+ .tmpdbg/real_label.jpg（真机照片）
"""
import os
import sys

from rapidocr import RapidOCR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = [
    ("a_tight_small.png", "GV2ME08", "16px 小字紧贴边框"),
    ("b_small_margin.png", "GV2ME08", "16px 小字留边"),
    ("c_label_photo.png", "LC1D18", "小字+中文（灰底标签）"),
    ("d_two_lines.png", "SEREAM", "两行小字"),
    ("e_gray_blur.png", "T40", "灰底+轻微失焦"),
    ("real_label.jpg", "", "真机拍的标签照片"),
]

# Tesseract（手机 App 里 v1.30.0 引擎）在同一批素材上的结果，手动抄自 adb logcat
TESS = {
    "a_tight_small.png": "GV2ME08",
    "b_small_margin.png": "GV2ME08",
    "c_label_photo.png": "LC1D18 ems 交流接触屁",
    "d_two_lines.png": "SEREAM T40 59633 9成新",
    "e_gray_blur.png": "型号 T40 59633",
}


def main():
    eng = RapidOCR()
    ok = 0
    total = 0
    for name, want, desc in CASES:
        path = os.path.join(ROOT, ".tmpdbg", "ocr_cases", name)
        if not os.path.isfile(path):
            path = os.path.join(ROOT, ".tmpdbg", name)
        if not os.path.isfile(path):
            print("缺素材:", name)
            continue
        r = eng(path)
        texts = list(r.txts or [])
        joined = " | ".join(texts)
        hit = (want in joined.replace(" ", "")) if want else None
        if want:
            total += 1
            ok += 1 if hit else 0
        print("=" * 70)
        print("%-22s %s" % (name, desc))
        print("  RapidOCR : %s  (scores %s)" % (
            joined or "(空)",
            ", ".join("%.2f" % s for s in (r.scores or []))[:60]))
        print("  Tesseract: %s" % TESS.get(name, "-"))
        if want:
            print("  期望包含 : %s  -> %s" % (want, "命中" if hit else "未命中"))
    if total:
        print("\nRapidOCR 命中 %d/%d" % (ok, total))


if __name__ == "__main__":
    sys.exit(main())
