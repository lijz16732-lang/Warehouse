# -*- coding: utf-8 -*-
"""CSV 导出：与 XLSX 导出同口径（同样的列、同样的取值规则），只是纯文本。

设置里「默认导出格式」选 CSV 时走这里；CSV 天生只有一张表，所以不带
XLSX 版里的多工作表汇总（出售汇总 / 分品牌统计等）。编码由设置里的
「CSV 导出编码」决定（Excel 兼容 / GBK / UTF-8）。
"""

import csv

from .constants import FIELD_KEYS, FIELD_LABEL, FIELD_TYPE, LISTED_TEXT


def _cell(v, t):
    if t == "bool":
        return LISTED_TEXT.get(int(v or 0), "未上架")
    if t == "money":
        return "%.2f" % float(v or 0)
    if t == "int":
        return str(int(v or 0))
    return "" if v is None else str(v)


def export_records_csv(path, records, columns=None, encoding="utf-8-sig"):
    """库存记录 → CSV（列与「导出为 XLSX」完全一致）。"""
    columns = columns or FIELD_KEYS
    with open(path, "w", encoding=encoding, newline="") as f:
        wr = csv.writer(f)
        wr.writerow([FIELD_LABEL[c] for c in columns])
        for r in records:
            wr.writerow([_cell(r.get(c), FIELD_TYPE[c]) for c in columns])
    return len(records)


def _write(path, headers, rows, encoding):
    with open(path, "w", encoding=encoding, newline="") as f:
        wr = csv.writer(f)
        wr.writerow([h[1] for h in headers])
        for row in rows:
            wr.writerow(row)
    return len(rows)


def export_sales_csv(path, rows, encoding="utf-8-sig"):
    """出售记录 → CSV（明细；口径与 export_sales_xlsx 的明细表一致）。"""
    from .xlsxio import SALE_HEADERS
    out = []
    for r in rows:
        qty = int(r.get("qty") or 0)
        total = float(r.get("total") or 0)
        cost = float(r.get("cost") or 0)
        out.append([r.get("sale_date") or "", r.get("code") or "",
                    r.get("brand") or "", r.get("category") or "",
                    r.get("model") or "", r.get("shelf") or "",
                    qty, "%.2f" % float(r.get("price") or 0), "%.2f" % total,
                    "%.2f" % cost, "%.2f" % (total - cost * qty),
                    r.get("buyer") or "", r.get("address") or "",
                    r.get("remark") or ""])
    return _write(path, SALE_HEADERS, out, encoding)


def export_out_csv(path, rows, encoding="utf-8-sig"):
    """出库记录 → CSV（明细；口径与 export_out_xlsx 的明细表一致）。"""
    from .xlsxio import OUT_HEADERS
    out = []
    for r in rows:
        out.append([r.get("out_date") or "", r.get("out_type") or "",
                    r.get("code") or "", r.get("brand") or "",
                    r.get("category") or "", r.get("model") or "",
                    r.get("shelf") or "", int(r.get("qty") or 0),
                    "%.2f" % float(r.get("unit_cost") or 0),
                    "%.2f" % float(r.get("cost_total") or 0),
                    r.get("remark") or ""])
    return _write(path, OUT_HEADERS, out, encoding)


def export_purchases_csv(path, rows, encoding="utf-8-sig"):
    """采购记录 → CSV（明细；口径与 export_purchases_xlsx 的明细表一致）。"""
    from .xlsxio import PURCHASE_HEADERS
    out = []
    for r in rows:
        out.append([r.get("purchase_date") or "", r.get("code") or "",
                    r.get("brand") or "", r.get("category") or "",
                    r.get("model") or "", r.get("shelf") or "",
                    int(r.get("qty") or 0),
                    "%.2f" % float(r.get("unit_cost") or 0),
                    "%.2f" % float(r.get("total") or 0),
                    r.get("supplier") or "", r.get("remark") or ""])
    return _write(path, PURCHASE_HEADERS, out, encoding)
