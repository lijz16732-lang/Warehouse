# -*- coding: utf-8 -*-
"""iOS 式拨动开关（Canvas 绘制）：蓝底 + 右侧白钮 = 开，灰底 + 左侧白钮 = 关。

替代「已上架/未上架」下拉框：状态一目了然，单击即切换。
variable 为 tk 变量，on_value/off_value 对应开/关时的取值（编辑弹窗里
传 StringVar 与「已上架」/「未上架」即可与旧保存逻辑完全兼容）。
"""

import tkinter as tk

from .constants import CLR_ACCENT, CLR_ACCENT_LT, CLR_BORDER_LT, CLR_CARD

# 全局开关动效（设置里可关）。app 启动时按 settings["toggle_anim"] 同步；
# 关掉后拨动开关瞬间跳变，不跑动画。
ANIM = {"enabled": True}


def set_anim(flag):
    ANIM["enabled"] = bool(flag)


class Toggle(tk.Canvas):
    """拨动开关。variable.get() 为 on_value 时显示开启态。"""

    def __init__(self, parent, variable, on_value=1, off_value=0,
                 command=None, scale=1.0, bg=None):
        w = int(46 * float(scale or 1.0))
        h = int(24 * float(scale or 1.0))
        bg = bg or CLR_CARD
        tk.Canvas.__init__(self, parent, width=w, height=h, bg=bg,
                           highlightthickness=0, bd=0, cursor="hand2")
        self.var = variable
        self.on_value = on_value
        self.off_value = off_value
        self.command = command
        self._tw, self._th = w, h
        self._job = None                          # 动画 after id
        self._pos = 1.0 if self.is_on() else 0.0  # 白钮位置：0=左（关）1=右（开）
        variable.trace_add("write", lambda *_: self._sync_from_var())
        self.bind("<Button-1>", self._flip)
        self._draw()

    def is_on(self):
        try:
            return self.var.get() == self.on_value
        except Exception:
            return False

    def _flip(self, _e=None):
        self.var.set(self.off_value if self.is_on() else self.on_value)
        if self.command:
            self.command()

    def _sync_from_var(self):
        """变量变化 → 目标位置。能动画就滑过去，关掉动效时瞬间到位。"""
        target = 1.0 if self.is_on() else 0.0
        if ANIM["enabled"] and abs(target - self._pos) > 0.001:
            self._animate_to(target)   # 动画中再点会取消旧动画、从当前位置重来
        else:
            if self._job is not None:
                try:
                    self.after_cancel(self._job)
                except Exception:
                    pass
                self._job = None
            self._pos = target
            self._draw()

    def _animate_to(self, target, steps=8):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        start = self._pos
        delta = target - start

        def step(i):
            self._pos = start + delta * (i / float(steps))
            self._draw()
            if i < steps:
                self._job = self.after(16, lambda: step(i + 1))
            else:
                self._pos = target
                self._job = None
                self._draw()

        step(1)

    def _draw(self):
        self.delete("all")
        w, h = self._tw, self._th
        m = 2                                   # 胶囊外边距
        d = h - 2 * m                           # 钮直径 / 胶囊高
        on = self.is_on()
        # 胶囊：左圆 + 右圆 + 中间矩形
        fill = CLR_ACCENT if on else CLR_BORDER_LT
        self.create_oval(m, m, m + d, m + d, fill=fill, outline=fill)
        self.create_oval(w - m - d, m, w - m, m + d, fill=fill, outline=fill)
        self.create_rectangle(m + d / 2, m, w - m - d / 2, m + d,
                              fill=fill, outline=fill)
        # 白钮：按当前动画进度插值位置
        kx = m + (w - 2 * m - d) * self._pos
        self.create_oval(kx, m, kx + d, m + d, fill="#FFFFFF",
                         outline=CLR_ACCENT_LT if on else "#9AA3B2")
