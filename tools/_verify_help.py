# -*- coding: utf-8 -*-
"""验证（v1.10.9）：使用说明改成可滚动窗口。

覆盖：
  1. 正文完整（最后一章「数据存放」与数据库路径都在）
  2. 内容比窗口高 → 有滚动余量，能滚到最底部（原来 messagebox 后面看不到）
  3. 左侧目录跳转：点最后一章 → 该章出现在视口顶部
  4. 搜索：命中数正确、有高亮；清空后高亮消失
  5. 复制全部说明
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import tkinter as tk  # noqa: E402
import screenshot  # noqa: E402
from wm import app as wapp  # noqa: E402
from wm.help import HelpDialog, help_sections  # noqa: E402
from wm.store import Store  # noqa: E402

OUT = os.path.join(ROOT, ".tmpdbg")
os.makedirs(OUT, exist_ok=True)
FAILS = []


def check(name, ok, extra=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name +
          ((" -> " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


TMP = tempfile.mkdtemp(prefix="wm_help_")
wapp.app_dir = lambda: TMP
Store(os.path.join(TMP, "data", "warehouse.db")).close()

root = tk.Tk()
app = wapp.App(root)
root.geometry("1400x860+60+40")
root.deiconify()
root.update()

print("== 1. 打开使用说明窗口 ==")
app.show_help()
root.update()
dlg = None
for w in root.winfo_children():
    if isinstance(w, tk.Toplevel) and w.title() == "使用说明":
        dlg = w
check("使用说明是独立窗口（不再是 messagebox）", dlg is not None)
if dlg is None:
    print("失败项：", FAILS)
    sys.exit(1)

text = dlg.text
content = text.get("1.0", "end-1c")
check("章节数 = %d" % len(help_sections()), len(dlg.sections) == len(help_sections()),
      len(dlg.sections))
check("目录条目与章节一致", dlg.toc.size() == len(dlg.sections), dlg.toc.size())
check("最后一章「数据存放」在文末", "【" not in content.split("数据存放")[-1],
      content[-120:].replace("\n", " | "))
check("数据库路径已写入", app.db_path in content, app.db_path)
check("新增「手动补录出售」章节", "手动补录出售" in content)

print("== 2. 可滚动（能看到后面）==")
root.update()
first, last = text.yview()
check("内容比窗口高（有滚动余量）", last - first < 0.999,
      "可视比例 %.2f" % (last - first))
text.yview_moveto(1.0)
root.update()
check("能滚到最底部", abs(text.yview()[1] - 1.0) < 1e-6, text.yview())
check("底部能看到「提示：数据库文件可直接复制备份」",
      text.bbox("end-2c") is not None, text.bbox("end-2c"))
text.yview_moveto(0)
root.update()

print("== 3. 目录跳转 ==")
mid_i = len(dlg.sections) // 2
dlg.toc.selection_clear(0, "end")
dlg.toc.selection_set(mid_i)
dlg._jump()
root.update()
top = text.index("@0,0")
check("跳到中间章节：标题落在视口顶部",
      abs(int(top.split(".")[0]) - int(dlg.marks[mid_i].split(".")[0])) <= 1,
      "%s vs %s" % (top, dlg.marks[mid_i]))

last_i = len(dlg.sections) - 1
dlg.toc.selection_clear(0, "end")
dlg.toc.selection_set(last_i)
dlg._jump()
root.update()
# 最后一章后面没内容可滚了，只能保证「看得到」，不强求贴顶
check("跳到最后一章：标题可见", text.bbox(dlg.marks[last_i]) is not None,
      text.yview())

print("== 4. 搜索 ==")
dlg.toc.selection_clear(0, "end")
text.yview_moveto(0)
dlg.var_kw.set("收货地址")
dlg._find()
root.update()
hits = text.tag_ranges("hit")
check("搜索命中并高亮", len(hits) >= 4, len(hits))
check("命中数提示", "找到" in dlg.lbl_found.cget("text"), dlg.lbl_found.cget("text"))
dlg.var_kw.set("不存在的关键词ZZZ")
dlg._find()
check("搜不到时提示「未找到」", dlg.lbl_found.cget("text") == "未找到",
      dlg.lbl_found.cget("text"))
dlg.var_kw.set("")
dlg._on_search_key()
check("清空搜索后高亮清除", len(text.tag_ranges("hit")) == 0)

print("== 5. 复制全部 ==")
dlg._copy_all()
root.update()
clip = root.clipboard_get()
check("复制到剪贴板", len(clip) > 1500 and "手动补录出售" in clip, len(clip))

print("== 6. 截图 ==")
text.yview_moveto(0)
root.update()
screenshot.capture_window("使用说明", os.path.join(OUT, "help_window.png"))

dlg.destroy()
root.destroy()
print("\n失败项：%s" % (FAILS or "无"))
sys.exit(1 if FAILS else 0)
