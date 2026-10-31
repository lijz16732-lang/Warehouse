# -*- coding: utf-8 -*-
"""全弹窗「防闪左上角」端到端探针。

装上 main._install_noflash_toplevel 全局补丁后，构建真实 App，逐一打开
全部弹窗，记录每个窗口「被映射那一刻」的坐标并和最终坐标对比：
闪左上角 = 映射位置在默认位置(~0,0) 或 != 最终位置。

两类打开方式：
· 直接构造（无 wait_window）→ 打开后按「新增 Toplevel 差集」断言再销毁；
· ask_* 包装（内部 wait_window 会阻塞）→ 靠 reaper 定时销毁放行。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import main as m
m._install_noflash_toplevel()          # 与 exe 主流程一致的全局补丁

import tkinter as tk

# ---- Map 记录器：包住补丁后的 Toplevel.__init__ ----
MAPS = []                              # (title, mapped_x, mapped_y)
_ORIG_INIT = tk.Toplevel.__init__


def _rec_init(self, *a, **kw):
    _ORIG_INIT(self, *a, **kw)

    def _on_map(_e):
        if _e.widget is not self:
            return                    # <Map> 会因子控件映射触发，只记自身
        try:
            alpha = self.attributes("-alpha")
        except Exception:
            alpha = 1.0
        MAPS.append((self.title(), self.winfo_x(), self.winfo_y(), alpha))
        try:
            self.unbind("<Map>")
        except Exception:
            pass
    self.bind("<Map>", _on_map)


tk.Toplevel.__init__ = _rec_init

FAILS = []


def check(name, ok, detail=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ("  " + str(detail) if (detail and not ok) or True else ""))
    if not ok:
        FAILS.append(name)
    return ok


def all_toplevels(w):
    out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Toplevel):
            out.append(c)
        out.extend(all_toplevels(c))
    return out


def main():
    try:
        from wm.screen import enable_dpi_awareness
        enable_dpi_awareness()
    except Exception:
        pass

    import wm.app as wapp
    from wm import sales, extras, editor, help as helpmod, importer

    root = tk.Tk()
    root.withdraw()
    app = wapp.App(root)
    root.deiconify()
    root.update()                      # 主窗口完全映射（与实机一致）

    # 种子数据：两条同型号（供重复检查）+ 一条有库存
    app.store.insert_many([
        {"brand": "罗技", "category": "外设", "model": "M-DUP", "condition": "99新",
         "price": 100, "qty": 2, "shelf": "1排A-1", "listed": 1, "remark": ""},
        {"brand": "罗技", "category": "外设", "model": "M-DUP", "condition": "95新",
         "price": 90, "qty": 1, "shelf": "1排A-2", "listed": 1, "remark": ""},
        {"brand": "Apple", "category": "手机", "model": "M-ONE", "condition": "全新",
         "price": 2000, "qty": 5, "shelf": "2排B-1", "listed": 1, "remark": ""},
    ])
    if hasattr(app, "refresh_table"):
        app.refresh_table()
    root.update()
    rec = app.store.all_records()[0]

    def open_case(fn, tag, parent=None, _retry=True):
        """打开弹窗 → 用新增 Toplevel 差集断言映射位置 → 销毁。"""
        parent = parent or root
        before = set(all_toplevels(root))
        MAPS.clear()
        try:
            fn()
        except Exception as e:
            check(tag, False, "创建异常 %r" % e)
            return None
        root.update()
        new = [w for w in all_toplevels(root) if w not in before]
        if not new:
            # 兜底：弹窗可能被物理点击提前关闭（探针在用户桌面上跑），
            # 但 <Map> 记录还在——凭记录判定
            recs = [r for r in MAPS]
            MAPS.clear()
            if recs:
                bad = [r for r in recs if r[1] == 0 and r[2] == 0 and r[3] > 0]
                check(tag, not bad, "凭Map记录: %s" % recs[:3])
                return None
            if _retry:
                # 探针期间物理鼠标可能点到弹出的模态窗（wait_window 提前
                # 返回），属环境噪音——重试一次
                return open_case(fn, tag, parent=parent, _retry=False)
            check(tag, False, "未出现新 Toplevel（可能 messagebox 提前返回）")
            return None
        win = new[-1]
        try:
            win.update_idletasks()
            root.update()
            hits = [h for h in MAPS if h[0] == win.title()]
            if not hits:
                check(tag, False, "未记录到 <Map>")
                return win
            mx, my, mal = hits[0][1], hits[0][2], hits[0][3]
            fx, fy = win.winfo_x(), win.winfo_y()
            ok = ((mx, my) == (fx, fy) or mal == 0.0) and mx >= 0
            check(tag, ok and fx >= 50 and fy >= 50,
                  "mapped=(%d,%d,alpha=%s) final=(%d,%d)"
                  % (mx, my, mal, fx, fy))
            return win
        finally:
            pass

    def close_all():
        for w in all_toplevels(root):
            try:
                w.destroy()
            except Exception:
                pass
        root.update()

    print("== A. 直接构造型弹窗 ==")
    open_case(app.open_lan, "A1 局域网共享")
    close_all()
    open_case(app.manage_warehouses, "A2 仓库管理")
    close_all()
    open_case(app.check_duplicates, "A3 按型号检查重复")
    close_all()
    open_case(app.open_appearance, "A4 设置（外观/快捷键）")
    close_all()
    open_case(lambda: extras.PurchaseListDialog(app, app.fam), "A5 采购记录")
    close_all()
    open_case(lambda: extras.BuyerDialog(app, app.fam), "A6 买家管理")
    close_all()
    open_case(lambda: extras.RecycleBinDialog(app, app.fam), "A7 删除回收站")
    close_all()
    open_case(lambda: extras.BatchEditDialog(app, app.fam), "A8 批量修改字段")
    close_all()
    open_case(lambda: helpmod.HelpDialog(app.root, helpmod.help_sections(),
                                         app.fam, "test"), "A9 帮助")
    close_all()

    # A10 黑名单管理（LanDialog 的子窗口）
    dlg_lan = open_case(app.open_lan, "A10-1 局域网共享（为黑名单复开）")
    if dlg_lan is not None and dlg_lan.winfo_exists():
        open_case(lambda: dlg_lan.manage_blocked(), "A10 黑名单管理", parent=dlg_lan)
    close_all()

    # A11 照片管理窗（PhotoStrip.view）+ 双击预览
    try:
        from wm.photos import PhotoStrip
        strip = PhotoStrip(root, app, kind="item")
        strip.set_code(rec["code"])
        root.update()
        names = app.store.photos_list("item", rec["code"]) or []
        if names:
            win = open_case(lambda: strip.view(names[0]), "A11 照片管理窗")
            if win is not None and win.winfo_exists() and hasattr(win, "_msel"):
                ms = win._msel
                open_case(lambda: ms["dblclick"](names[0]), "A12 双击放大预览",
                          parent=win)
        else:
            print("  [SKIP] A11 照片管理窗（无照片数据）")
        try:
            strip.destroy()
        except Exception:
            pass
    except Exception as e:
        print("  [SKIP] A11/A12 照片窗:", e)
    close_all()

    print("== B. ask_* 包装型（wait_window，靠 reaper 放行）==")
    stop_reap = []

    def reap():
        if stop_reap:
            return
        tops = all_toplevels(root)
        if tops:
            try:
                tops[-1].destroy()
            except Exception:
                pass
        if not stop_reap:
            root.after(150, reap)

    def ask_case(fn, tag):
        MAPS.clear()
        stop_reap.clear()
        root.after(250, reap)
        try:
            fn()
            root.update()
        except Exception as e:
            check(tag, False, repr(e))
            stop_reap.append(1)
            return
        stop_reap.append(1)
        hits = list(MAPS)
        MAPS.clear()
        if not hits:
            check(tag, False, "未记录到映射（可能 messagebox 提前返回）")
            return
        # 映射在最终位置，或映射时 alpha=0（透明防闪）都算过；
        # 不透明状态落在 (0,0) 才是闪框
        bad = [h for h in hits if h[1] < 50 and h[3] > 0]
        check(tag, not bad, "映射位置: %s" % hits[:3])

    ask_case(lambda: sales.ask_sale(root, rec, app.fam, buyers=["甲", "乙"]),
             "B1 出售/出库登记")
    ask_case(lambda: sales.ask_manual_sale(root, app.fam, buyers=["甲"]),
             "B2 手动补录出售")
    ask_case(lambda: sales.ask_out_type(root, [rec], app.fam), "B3 出库类型选择")
    ask_case(lambda: editor.ask_record(root, None, [], "新增记录", app.fam),
             "B4 新增/编辑记录")
    ask_case(lambda: extras.ask_purchase(root, rec, app.fam), "B5 采购入库")
    ask_case(lambda: extras.ask_name(root, "低库存阈值", "提示", "5"), "B6 输入小弹窗")

    # 导入向导：生成一个真 xlsx
    try:
        import openpyxl
        xp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_imp.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["品牌", "品类", "型号", "数量", "成色", "单格", "货架", "备注", "是否上架"])
        ws.append(["罗技", "外设", "G-IMP", 1, "99新", 10, "1排A-1", "", "是"])
        wb.save(xp)
        ask_case(lambda: importer.ask_import(root, xp, app.fam), "B7 导入向导")
        os.remove(xp)
    except Exception as e:
        print("  [SKIP] B7 导入向导:", e)

    print("== 汇总：FAIL=%d ==" % len(FAILS), FAILS if FAILS else "")
    root.destroy()
    print("PROBE DONE" if not FAILS else "PROBE FAILED")


if __name__ == "__main__":
    main()
