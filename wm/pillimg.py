# -*- coding: utf-8 -*-
"""抗锯齿胶囊开关图片。

Tk 的 Canvas 没有抗锯齿：椭圆 + 矩形拼出来的胶囊边缘是硬像素阶梯，
在 16px 高度下尤其明显（看着"不圆润"）。这里用 4× 超采样把胶囊渲染成
RGBA PNG，再交给 tk.PhotoImage 贴到 Canvas 上——透明区域自动透出画布底色，
边缘按覆盖率与底色混合，视觉上就是平滑圆角。

不依赖 PIL：PNG 用 zlib 手写（同 tools/screenshot.py 的做法），
超采样用"点到胶囊的距离场"判定覆盖率。
"""

import base64
import struct
import zlib

SS = 4          # 超采样倍数


def _hex2rgb(s):
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def capsule_png(pw, ph, fill, on, knob="#FFFFFF", pad=2):
    """生成一颗胶囊开关的 PNG 字节串（RGBA，尺寸 pw×ph）。

    on=True 时滑块在右（轨道 fill 色），False 时滑块在左。
    pad 是滑块与轨道上下边缘的间距（逻辑像素）。
    """
    pw, ph = int(pw), int(ph)
    if pw < 4 or ph < 4:
        return None
    W, H = pw * SS, ph * SS
    r = H / 2.0
    m = float(max(1, pad) * SS)
    kr = (H - 2 * m) / 2.0
    if kr <= 0:
        return None
    kx = (W - m - kr) if on else (m + kr)
    cy = H / 2.0
    tr, tg, tb = _hex2rgb(fill)
    nr, ng, nb = _hex2rgb(knob)

    pix = bytearray()
    inv = 1.0 / (SS * SS)
    for py in range(ph):
        y0 = py * SS
        for px in range(pw):
            x0 = px * SS
            t_in = 0
            k_in = 0
            for sy in range(SS):
                y = y0 + sy + 0.5
                dy = y - cy
                for sx in range(SS):
                    x = x0 + sx + 0.5
                    # 轨道：两端半圆的圆角矩形
                    if x < r:
                        dx = r - x
                    elif x > W - r:
                        dx = x - (W - r)
                    else:
                        dx = 0.0
                    if dx * dx + dy * dy <= r * r:
                        t_in += 1
                        kdx = x - kx
                        if kdx * kdx + dy * dy <= kr * kr:
                            k_in += 1
            a = t_in * inv
            if a <= 0.0:
                pix += b"\x00\x00\x00\x00"
                continue
            k = k_in * inv
            # 滑块压轨道：按滑块覆盖率混色
            cr = int(tr * (1 - k) + nr * k + 0.5)
            cg = int(tg * (1 - k) + ng * k + 0.5)
            cb = int(tb * (1 - k) + nb * k + 0.5)
            pix += bytes((cr, cg, cb, int(a * 255 + 0.5)))

    return _encode(pw, ph, pix)


def _encode(w, h, pix):
    def chunk(t, d):
        return (len(d).to_bytes(4, "big") + t + d +
                (zlib.crc32(t + d) & 0xffffffff).to_bytes(4, "big"))
    # 每行前加 filter 字节 0（None）
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += pix[y * stride:(y + 1) * stride]
    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    out += chunk(b"IEND", b"")
    return out


def capsule_b64(pw, ph, fill, on, knob="#FFFFFF", pad=2):
    png = capsule_png(pw, ph, fill, on, knob, pad)
    if not png:
        return None
    return base64.b64encode(png).decode("ascii")


def roundrect_png(pw, ph, fill, radius):
    """抗锯齿圆角矩形 PNG 字节串（RGBA，四角透明）。

    与胶囊同一套 4× 超采样思路：圆角矩形 = 中心距场
    dx = max(|x-cx| - (w/2-r), 0)，dy 同理，dx²+dy² ≤ r² 即在圆角内。
    """
    pw, ph = int(pw), int(ph)
    if pw < 4 or ph < 4:
        return None
    r = max(1, min(int(radius), min(pw, ph) // 2)) * SS
    W, H = pw * SS, ph * SS
    x0, y0, x1, y1 = r, r, W - r, H - r
    tr, tg, tb = _hex2rgb(fill)
    pix = bytearray()
    inv = 1.0 / (SS * SS)
    for py in range(ph):
        yy0 = py * SS
        for px in range(pw):
            xx0 = px * SS
            t_in = 0
            for sy in range(SS):
                y = yy0 + sy + 0.5
                dy = max(y0 - y, y - y1, 0.0)
                for sx in range(SS):
                    x = xx0 + sx + 0.5
                    dx = max(x0 - x, x - x1, 0.0)
                    if dx * dx + dy * dy <= r * r:
                        t_in += 1
            a = int(t_in * inv * 255 + 0.5)
            pix += bytes((tr, tg, tb, a))
    return _encode(pw, ph, pix)


def roundrect_b64(pw, ph, fill, radius):
    png = roundrect_png(pw, ph, fill, radius)
    if not png:
        return None
    return base64.b64encode(png).decode("ascii")
