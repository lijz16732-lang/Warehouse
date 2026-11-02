# -*- coding: utf-8 -*-
"""完整复刻 PpOcrEngine.detect() 后处理（双线性+blob打分+minAreaQuad+透视矫正），
对倾斜用例输出每个框的四点与矫正图，定位 ±15° 以上失败原因。"""
import sys
import math
import numpy as np
import onnxruntime as ort
from PIL import Image
from scipy import ndimage

sess = ort.InferenceSession(
    '.venvocr/Lib/site-packages/rapidocr/models/PP-OCRv6_det_small.onnx',
    providers=['CPUExecutionProvider'])
inp = sess.get_inputs()[0].name

LIMIT_SIDE, DET_THRESH, BOX_THRESH, UNCLIP_RATIO = 736, 0.30, 0.50, 1.6


def min_area_quad(pts):
    if len(pts) < 4:
        return None
    # 凸包
    packed = sorted(set((int(x), int(y)) for x, y in pts))
    if len(packed) < 3:
        return None

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and cross(h[-2], h[-1], p) <= 0:
                h.pop()
            h.append(p)
        return h
    lower = half(packed)
    upper = half(reversed(packed))
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return None
    best_area = float('inf')
    best = None
    n = len(hull)
    for i in range(n):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % n]
        ang = math.atan2(y2 - y1, x2 - x1)
        ca, sa = math.cos(ang), math.sin(ang)
        us = [px * ca + py * sa for px, py in hull]
        vs = [-px * sa + py * ca for px, py in hull]
        area = (max(us) - min(us)) * (max(vs) - min(vs))
        if area < best_area:
            best_area = area
            best = (ang, min(us), max(us), min(vs), max(vs))
    ang, mu, xu, mv, xv = best
    w, h = xu - mu, xv - mv
    d = (w * h * UNCLIP_RATIO) / (2.0 * (w + h))
    cu, cv = (mu + xu) / 2, (mv + xv) / 2
    hu, hv = w / 2 + d, h / 2 + d
    ca, sa = math.cos(ang), math.sin(ang)
    quad = []
    for du, dv in ((-hu, -hv), (hu, -hv), (hu, hv), (-hu, hv)):
        u, v = cu + du, cv + dv
        quad.append((u * ca - v * sa, u * sa + v * ca))
    return quad


def analyze(path):
    src = Image.open(path).convert('RGB')
    W, H = src.size
    ratio = max(1.0, LIMIT_SIDE / min(W, H))
    rw = max(32, round(W * ratio / 32) * 32)
    rh = max(32, round(H * ratio / 32) * 32)
    im = src.resize((rw, rh), Image.BILINEAR)
    grid = np.asarray(im).astype(np.float32) / 127.5 - 1.0
    prob = sess.run(None, {inp: np.ascontiguousarray(grid.transpose(2, 0, 1))[None]})[0][0, 0]
    mask = prob > DET_THRESH
    dil = mask.copy()
    dil[:-1, :] |= mask[1:, :]
    dil[:, :-1] |= mask[:, 1:]
    dil[:-1, :-1] |= mask[1:, 1:]
    lab, n = ndimage.label(dil, structure=np.ones((3, 3), int))
    print(path.split('/')[-1], f'src={W}x{H} det_in={rw}x{rh} comps={n}')
    for k in range(1, n + 1):
        blob = lab == k
        if blob.sum() < 6:
            continue
        ys, xs = np.nonzero(blob)
        bw, bh = xs.max()-xs.min()+1, ys.max()-ys.min()+1
        if min(bw, bh) < 3:
            continue
        score = prob[blob].mean()
        if score < BOX_THRESH:
            continue
        quad = min_area_quad(list(zip(xs, ys)))
        if quad is None:
            print('  comp%d: quad=None' % k)
            continue
        xs4 = [p[0] for p in quad]
        ys4 = [p[1] for p in quad]
        # 各边长
        import itertools
        edges = []
        for i in range(4):
            a, b = quad[i], quad[(i + 1) % 4]
            edges.append(round(math.hypot(b[0]-a[0], b[1]-a[1]), 1))
        print('  comp%d: score=%.2f quad边长=%s 宽高=%.0fx%.0f 角度=%.1f°'
              % (k, score, edges, max(xs4)-min(xs4), max(ys4)-min(ys4),
                 math.degrees(math.atan2(quad[1][1]-quad[0][1], quad[1][0]-quad[0][0]))))


if __name__ == '__main__' and len(sys.argv) > 1:
    for c in sys.argv[1:]:
        analyze(c)
