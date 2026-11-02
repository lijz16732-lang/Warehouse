# -*- coding: utf-8 -*-
"""验证「检测框重叠合并」能否修碎片问题（预处理路径）。"""
import math
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage
from rapidocr import RapidOCR
import sys
sys.path.insert(0, 'warehouse_manager/tools')
from _det_quad_dbg import min_area_quad, sess, inp, LIMIT_SIDE, DET_THRESH, BOX_THRESH

eng = RapidOCR()


def preprocess(src):
    w, h = src.size
    le, se = max(w, h), min(w, h)
    s = 1.0
    if le < 1500:
        s = 1500.0 / le
    elif le > 2000:
        s = 2000.0 / le
    if se * s < 320:
        s = 320.0 / se
    im = src.resize((round(w * s), round(h * s)), Image.BILINEAR)
    im = im.convert('L').filter(ImageFilter.UnsharpMask(1.2, 140, 2)).convert('RGB')
    pad = max(12, max(im.size) // 28)
    out = Image.new('RGB', (im.width + 2 * pad, im.height + 2 * pad), 'white')
    out.paste(im, (pad, pad))
    return out


def det_boxes(src):
    W, H = src.size
    ratio = max(1.0, LIMIT_SIDE / min(W, H))
    rw = max(32, round(W * ratio / 32) * 32)
    rh = max(32, round(H * ratio / 32) * 32)
    if rw * rh > 2_200_000:
        k = (2_200_000 / (rw * rh)) ** 0.5
        rw = max(32, round(rw * k / 32) * 32)
        rh = max(32, round(rh * k / 32) * 32)
    im = src.resize((rw, rh), Image.BILINEAR)
    grid = np.asarray(im).astype(np.float32) / 127.5 - 1.0
    prob = sess.run(None, {inp: np.ascontiguousarray(grid.transpose(2, 0, 1))[None]})[0][0, 0]
    mask = prob > DET_THRESH
    dil = mask.copy()
    if len(sys.argv) > 1 and sys.argv[1] == 'd3':
        dil = ndimage.binary_dilation(mask, np.ones((3, 3), bool))
    else:
        dil[:-1, :] |= mask[1:, :]
        dil[:, :-1] |= mask[:, 1:]
        dil[:-1, :-1] |= mask[1:, 1:]
    lab, n = ndimage.label(dil, structure=np.ones((3, 3), int))
    rects = []
    for k in range(1, n + 1):
        blob = lab == k
        if blob.sum() < 6:
            continue
        ys, xs = np.nonzero(blob)
        if min(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) < 3:
            continue
        if prob[blob].mean() < BOX_THRESH:
            continue
        rects.append([max(0, min(xs.min() / ratio, W - 1)),
                      max(0, min(ys.min() / ratio, H - 1)),
                      max(0, min(xs.max() / ratio, W - 1)),
                      max(0, min(ys.max() / ratio, H - 1)),
                      prob[blob].mean()])
    return rects, ratio, W, H


def merge_rects(rects):
    """bbox 相交就并（迭代至稳定）。"""
    rects = [list(r[:4]) for r in rects]
    merged = True
    while merged:
        merged = False
        out = []
        while rects:
            r = rects.pop(0)
            hit = None
            for o in out:
                if not (r[2] < o[0] or o[2] < r[0] or r[3] < o[1] or o[3] < r[1]):
                    hit = o
                    break
            if hit is not None:
                hit[0] = min(hit[0], r[0]); hit[1] = min(hit[1], r[1])
                hit[2] = max(hit[2], r[2]); hit[3] = max(hit[3], r[3])
                merged = True
            else:
                out.append(r)
        rects = out
    return rects


def rec_rect(src, r):
    x0, y0, x1, y1 = [int(round(v)) for v in r]
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(src.width, x1 + 1); y1 = min(src.height, y1 + 1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    crop = src.crop((x0, y0, x1, y1))
    p = max(3, round(min(crop.size) * 0.3))
    out = Image.new('RGB', (crop.width + 2 * p, crop.height + 2 * p), 'white')
    out.paste(crop, (p, p))
    res = eng(out)
    return ' '.join(res.txts or []).strip()


args = sys.argv[1:]
if args and args[0] == 'd3':
    args = args[1:]
for case in args:
    src = Image.open(f'warehouse_manager/.tmpdbg/tilt_cases/{case}.png').convert('RGB')
    pre = preprocess(src)
    rects, ratio, W, H = det_boxes(pre)
    n0 = len(rects)
    merged = merge_rects(rects)
    texts = []
    for r in merged:
        t = rec_rect(pre, r)
        if t:
            texts.append(t)
    print('%s: 框 %d → 合并 %d → %s' % (case, n0, len(merged), ' ⏐ '.join(texts)[:80]))
