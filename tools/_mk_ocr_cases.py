# -*- coding: utf-8 -*-
"""生成 OCR 回归素材（模拟「字很小但清晰」的各种标签照片）。

用途：把生成的图推到手机/模拟器的
    /sdcard/Android/data/com.cangguanjia.app/files/ocr_cases/
然后长按「识别」跑自检（或 adb am start --ez diag true），
ScanActivity 会逐张识别并把「文件名 → 结果」打到 logcat(CGMDIAG) 与屏幕，
用来客观判断预处理改动的效果（而不是凭感觉）。

gen(out_dir) 返回 [(文件名, 期望包含的文字), ...]
"""
import os

from PIL import Image, ImageDraw, ImageFont

# 标签上常见的型号/规格文字：字母数字为主，夹杂少量中文
CASES = [
    # (文件名, 字号, 是否紧贴边缘, 背景, 期望关键字)
    ("a_tight_small.png", 15, True, "#ffffff", "GV2ME08"),
    ("b_small_margin.png", 15, False, "#ffffff", "GV2ME08"),
    ("c_label_photo.png", 19, True, "#e8e4dc", "LC1D18"),
    ("d_two_lines.png", 17, True, "#ffffff", "SEREAM"),
    ("e_gray_blur.png", 20, True, "#cfd3d8", "T40"),
]


def _font(size, text=""):
    has_cjk = any('\u4e00' <= c <= '\u9fa5' for c in text)
    cands = ([r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
              r"C:\Windows\Fonts\simhei.ttf"] if has_cjk else
             [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"])
    for p in cands:
        if os.path.isfile(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _draw(text, size, tight, bg, pad=0):
    f = _font(size, text)
    tmp = Image.new("RGB", (10, 10), bg)
    d = ImageDraw.Draw(tmp)
    box = d.textbbox((0, 0), text, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    margin = 0 if tight else max(8, size)
    img = Image.new("RGB", (w + margin * 2 + 4, h + margin * 2 + 4), bg)
    d = ImageDraw.Draw(img)
    d.text((margin + 2 - box[0], margin + 2 - box[1]), text, font=f, fill="#1a1a1a")
    return img


def gen(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    made = []
    texts = {
        "a_tight_small.png": "GV2ME08",
        "b_small_margin.png": "GV2ME08",
        "c_label_photo.png": "LC1D18 施耐德 交流接触器",
        "d_two_lines.png": "SEREAM T40\n59633 9成新",
        "e_gray_blur.png": u"型号 T40 59633",
    }
    for name, size, tight, bg, want in CASES:
        text = texts[name]
        if "\n" in text:
            lines = text.split("\n")
            imgs = [_draw(l, size, tight, bg) for l in lines]
            w = max(i.width for i in imgs)
            h = sum(i.height for i in imgs) + (4 if tight else 0)
            img = Image.new("RGB", (w, h), bg)
            y = 0
            for i in imgs:
                img.paste(i, (0, y))
                y += i.height
        else:
            img = _draw(text, size, tight, bg)
        if name == "e_gray_blur.png":      # 轻微失焦 + 噪点：模拟手持拍照
            from PIL import ImageFilter
            img = img.filter(ImageFilter.GaussianBlur(0.6))
        path = os.path.join(out_dir, name)
        img.save(path)
        made.append((name, want))
    return made


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tmpdbg", "ocr_cases")
    for n, w in gen(out):
        print(n, "->", w)
    print("out:", out)
