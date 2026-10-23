# -*- coding: utf-8 -*-
"""生成 assets/app.ico（纯标准库手写 ICO，无需 Pillow）。"""

import os
import struct

SIZES = [16, 32, 48, 64, 128, 256]
SS = 3  # 超采样倍数

C_TOP = (59, 130, 246)    # #3B82F6
C_BOT = (29, 78, 216)     # #1D4ED8
C_FG = (255, 255, 255)


def _inside_rrect(u, v, x0, y0, x1, y1, r):
    if u < x0 or u > x1 or v < y0 or v > y1:
        return False
    cx = min(max(u, x0 + r), x1 - r)
    cy = min(max(v, y0 + r), y1 - r)
    dx, dy = u - cx, v - cy
    if dx == 0 and dy == 0:
        return True
    return (dx * dx + dy * dy) <= r * r


def _sample(u, v):
    """返回 (r, g, b, a)。"""
    if not _inside_rrect(u, v, 0.03, 0.03, 0.97, 0.97, 0.21):
        return (0, 0, 0, 0)
    t = (u * 0.35 + v * 0.65)
    r = int(C_TOP[0] + (C_BOT[0] - C_TOP[0]) * t)
    g = int(C_TOP[1] + (C_BOT[1] - C_TOP[1]) * t)
    b = int(C_TOP[2] + (C_BOT[2] - C_TOP[2]) * t)

    # 白色货架：三根横条
    bar_h = 0.098
    for i in range(3):
        v0 = 0.305 + i * 0.155
        if _inside_rrect(u, v, 0.235, v0, 0.765, v0 + bar_h, bar_h / 2.0):
            return (C_FG[0], C_FG[1], C_FG[2], 255)
    # 左侧立柱
    if _inside_rrect(u, v, 0.235, 0.305, 0.325, 0.90, 0.045):
        return (C_FG[0], C_FG[1], C_FG[2], 255)
    return (r, g, b, 255)


def render(size):
    """返回 BGRA 像素数据（自上而下逐行）与 alpha 图。"""
    n = SS * SS
    px = bytearray(size * size * 4)
    alpha = bytearray(size * size)
    for y in range(size):
        for x in range(size):
            ar = ag = ab = aa = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    u = (x + (sx + 0.5) / SS) / float(size)
                    v = (y + (sy + 0.5) / SS) / float(size)
                    r, g, b, a = _sample(u, v)
                    af = a / 255.0
                    ar += r * af
                    ag += g * af
                    ab += b * af
                    aa += a
            a_avg = aa / n
            if a_avg <= 0.5:
                r = g = b = 0
            else:
                wsum = aa / 255.0
                r = int(ar / wsum) if wsum else 0
                g = int(ag / wsum) if wsum else 0
                b = int(ab / wsum) if wsum else 0
            i = (y * size + x) * 4
            px[i] = max(0, min(255, b))
            px[i + 1] = max(0, min(255, g))
            px[i + 2] = max(0, min(255, r))
            px[i + 3] = int(max(0, min(255, a_avg)))
            alpha[y * size + x] = int(max(0, min(255, a_avg)))
    return px, alpha


def dib(size):
    px, alpha = render(size)
    # BITMAPINFOHEADER
    hdr = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                      size * size * 4, 0, 0, 0, 0)
    # XOR 位图（自下而上）
    rows = []
    for y in range(size - 1, -1, -1):
        rows.append(bytes(px[y * size * 4:(y + 1) * size * 4]))
    xor = b"".join(rows)
    # AND 掩码（1bpp，行按 4 字节对齐，自下而上），透明处为 1
    stride = ((size + 31) // 32) * 4
    mask_rows = []
    for y in range(size - 1, -1, -1):
        row = bytearray(stride)
        for x in range(size):
            if alpha[y * size + x] < 128:
                row[x >> 3] |= (0x80 >> (x & 7))
        mask_rows.append(bytes(row))
    return hdr + xor + b"".join(mask_rows)


def build_ico(path):
    images = [(s, dib(s)) for s in SIZES]
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, data in images:
        out += struct.pack("<BBBBHHII",
                           s if s < 256 else 0, s if s < 256 else 0, 0, 0, 1, 32,
                           len(data), offset)
        offset += len(data)
    for _, data in images:
        out += data
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(out)
    return path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(os.path.dirname(here), "assets", "app.ico")
    p = build_ico(target)
    print("icon written:", p, os.path.getsize(p), "bytes")
