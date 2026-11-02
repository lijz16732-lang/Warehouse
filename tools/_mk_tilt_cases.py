# -*- coding: utf-8 -*-
"""生成倾斜识别回归素材：文字渲染后旋转 θ，再按非白像素包围盒紧框裁出——
精确模拟「用户框选倾斜文字后交给引擎的轴对齐斜字条」。
输出到 .tmpdbg/tilt_cases/，命名 tNN_<tag>_h<字高>_a<角度>。
用模拟器自检（长按识别 / --ez diag）扫 ocr_cases 目录即可跑回归。"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(__file__), '..', '.tmpdbg', 'tilt_cases')


def font(sz):
    for p in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\msyh.ttc"):
        if os.path.isfile(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def make(text, px, angle_deg, name):
    W, H = 1800, 500
    tmp = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(tmp)
    f = font(px)
    bb = d.textbbox((0, 0), text, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((W - tw) / 2 - bb[0], (H - th) / 2 - bb[1]), text, font=f, fill='black')
    rot = tmp.rotate(angle_deg, resample=Image.BICUBIC, fillcolor='white')
    g = rot.convert('L')
    mask = g.point(lambda v: 255 if v < 200 else 0)
    bbox = mask.getbbox()
    crop = rot.crop(bbox)
    crop.save(os.path.join(OUT, name))
    return crop.size


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    i = 0
    for text in ['- IP 00 to IEC 60529', 'LC1D18M7']:
        tag = 'ip' if 'IP' in text else 'lc'
        for px in (16, 24, 32):
            for ang in (0, 5, -5, 10, -10, 15, -15, 20, -20, 30, -30):
                i += 1
                name = f"t{i:02d}_{tag}_h{px}_a{ang:+d}.png"
                size = make(text, px, ang, name)
                print(name, size)
    print('total', i)


if __name__ == '__main__':
    main()
