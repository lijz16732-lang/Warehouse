# -*- coding: utf-8 -*-
"""探针：readonly 下拉框「点箭头开 -> 再点箭头关（不选择）」后值是否还在。
用 ctypes 真实鼠标（event_generate 假阳性），输出 cb.get() / textvariable / 显示状态。
"""
import ctypes
import ctypes.wintypes as wt
import tkinter as tk
from tkinter import ttk

user32 = ctypes.windll.user32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def real_click(x, y):
    user32.SetCursorPos(int(x), int(y))
    import time
    time.sleep(0.15)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.25)


root = tk.Tk()
root.geometry("320x200+100+100")

var = tk.StringVar(value="60 天")
cb = ttk.Combobox(root, textvariable=var, state="readonly", width=14,
                  values=["永久保留", "30 天", "60 天", "90 天", "180 天"])
cb.place(x=40, y=60)

root.update()
root.update_idletasks()

rx = cb.winfo_rootx()
ry = cb.winfo_rooty()
w = cb.winfo_width()
h = cb.winfo_height()
# 箭头大约在右侧边缘中间
ax, ay = rx + w - 10, ry + h // 2
# 框中央（readonly 点击文字区同样 Post）
bx, by = rx + w // 2, ry + h // 2

# 把指针先移开
user32.SetCursorPos(2, 2)


def report(tag):
    cb.tk.call("update", "idletasks")
    cb.tk.call("update")
    try:
        v_var = str(cb.tk.globalgetvar(str(var)))
    except Exception as e:
        v_var = "<err %s>" % e
    print("[%s] cb.get()=%r var=%r popdown=%s mapped=%s" % (
        tag, cb.get(), v_var,
        cb.tk.call("winfo", "exists", str(cb) + ".popdown"),
        cb.tk.call("winfo", "ismapped", str(cb))))


# 记录 trace 触发（观察变量有没有被清）
trig = []
_tcmd = "_probe_trace"
cb.tk.createcommand(_tcmd, lambda *a: trig.append(str(cb.tk.globalgetvar(str(var)))))
cb.tk.call("trace", "add", "variable", str(var), "write", _tcmd)

report("init")

# 第一次点箭头：弹层打开
real_click(ax, ay)
report("after open (click arrow)")

# 第二次点箭头：弹层关闭（不选择）——用户报告这里变空白
real_click(ax, ay)
report("after close (click arrow again)")

# 再测：点框中央开，点框中央关
real_click(bx, by)
report("after open (click box)")
real_click(bx, by)
report("after close (click box again)")

print("trace writes:", trig)
root.after(300, root.destroy)
root.mainloop()
