# -*- coding: utf-8 -*-
"""启动演示数据并打开界面（用于截图检查）。用法: python tools/demo.py [tab]"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import tkinter as tk

import wm.app as wapp
from wm.store import Store

DEMO = [
    ("SKU-1001", "罗技 G502 无线鼠标", "罗技", "外设", "G502 LIGHTSPEED", "99新", 389.00, 12, "A-01", 1, "拆封未使用"),
    ("SKU-1002", "iPhone 13 128G", "Apple", "手机", "A2634", "95新", 2899.00, 3, "B-03", 1, "国行无锁"),
    ("SKU-1003", "戴尔 U2720Q 显示器", "戴尔", "显示器", "U2720Q", "9成新", 1580.00, 5, "C-02", 1, "边角轻微磕碰"),
    ("SKU-1004", "ThinkPad X1 Carbon", "联想", "笔记本", "X1C Gen9", "8成新", 3600.00, 2, "D-01", 0, "电池健康88%"),
    ("SKU-1005", "小米手环8", "小米", "穿戴", "SPP4020", "全新", 199.90, 30, "A-02", 1, ""),
    ("SKU-1006", "AirPods Pro 2", "Apple", "耳机", "A3047", "99新", 1299.00, 8, "B-01", 1, "含保护壳"),
    ("SKU-1007", "罗技 K380 键盘", "罗技", "外设", "K380", "95新", 129.00, 15, "A-01", 0, ""),
    ("SKU-1008", "iPad Air 5", "Apple", "平板", "A2589", "9成新", 3299.00, 4, "B-02", 1, "蓝天色"),
    ("SKU-1009", "华为 FreeBuds 5", "华为", "耳机", "T0018", "全新", 449.00, 10, "B-01", 1, ""),
    ("SKU-1010", "三星 980 Pro 1TB", "三星", "存储", "MZ-V8P1T0", "95新", 599.00, 20, "E-03", 1, ""),
    ("SKU-1011", " Kindle Paperwhite 5", "亚马逊", "阅读器", "KPW5", "8成新", 549.00, 3, "D-02", 0, "屏幕细微划痕"),
    ("SKU-1012", " Nintendo Switch OLED", "任天堂", "游戏机", "HEG-001", "95新", 1780.00, 6, "C-01", 1, "日版"),
    ("SKU-1013", "罗技 G304", "罗技", "外设", "G304", "9成新", 159.00, 25, "A-01", 1, ""),
    ("SKU-1014", "戴尔 U2419H", "戴尔", "显示器", "U2419H", "8成新", 699.00, 7, "C-02", 0, ""),
    ("SKU-1015", "小米音箱 Pro", "小米", "智能硬件", "L09A", "全新", 399.00, 9, "A-03", 1, ""),
    ("SKU-1016", "Anker 65W 氮化镓", "Anker", "充电", "A2665", "99新", 149.00, 18, "E-01", 1, ""),
    ("SKU-1017", "绿联 扩展坞 9合1", "绿联", "扩展坞", "CM360", "95新", 219.00, 14, "E-01", 1, ""),
    ("SKU-1018", "iPad mini 6", "Apple", "平板", "A2567", "9成新", 2699.00, 2, "B-02", 0, "紫色"),
]


def seed(store):
    store.clear_all()
    rows = []
    for code, name, brand, cat, model, cond, price, qty, shelf, listed, remark in DEMO:
        rows.append({"code": code, "name": name, "brand": brand, "category": cat,
                     "model": model, "condition": cond, "price": price, "qty": qty,
                     "shelf": shelf, "listed": listed, "remark": remark})
    store.insert_many(rows)


def main():
    tab = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    root = tk.Tk()
    app = wapp.App(root)
    seed(app.store)
    app.load_data()
    if tab:
        root.after(400, lambda: app.nb.select(tab))
    root.mainloop()


if __name__ == "__main__":
    main()
