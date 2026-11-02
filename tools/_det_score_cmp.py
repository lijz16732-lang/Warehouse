# -*- coding: utf-8 -*-
"""对比 det 后处理两种打分：轴对齐 bbox 均值（现 Java 实现） vs blob 像素均值。
用倾斜失败用例验证「bbox 均值把斜字分数拉低到阈值下」的假设。"""
import sys
import numpy as np
import onnxruntime as ort
from PIL import Image
from scipy import ndimage

sess = ort.InferenceSession(
    '.venvocr/Lib/site-packages/rapidocr/models/PP-OCRv6_det_small.onnx',
    providers=['CPUExecutionProvider'])
inp = sess.get_inputs()[0].name


def analyze(path):
    src = Image.open(path).convert('RGB')
    W, H = src.size
    LIMIT_SIDE, DET_THRESH, BOX_THRESH = 736, 0.30, 0.50
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
    print(path.split('/')[-1], 'components:', n)
    for k in range(1, n + 1):
        blob = lab == k
        ys, xs = np.nonzero(blob)
        y0, x0, y1, x1 = ys.min(), xs.min(), ys.max(), xs.max()
        score_bbox = prob[y0:y1 + 1, x0:x1 + 1].mean()
        score_blob = prob[blob].mean()
        print('  comp%d: bbox=%dx%d bbox均值=%.3f(过0.5?%s) blob均值=%.3f(过0.5?%s)'
              % (k, x1 - x0 + 1, y1 - y0 + 1, score_bbox, score_bbox >= BOX_THRESH,
                 score_blob, score_blob >= BOX_THRESH))


for c in sys.argv[1:]:
    analyze(c)
