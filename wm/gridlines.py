# -*- coding: utf-8 -*-
"""表格装饰覆盖层：网格线 + 上架开关。

v1.31「线条分明」：Treeview 原生画不出单元格边框，也放不进内嵌控件。
用一层 1px 细线（Frame 池）盖在表格上补齐横竖分隔线，用小 Canvas 在
「上架状态」列画拨动开关，点击即切换——都是本代码库验证过的覆盖层
套路（同 CellHover 贴片 / 照片📷贴片）：

  - 线条/开关收到的事件原样转发生成回 tree（同 _bind_overlay_events），
    拖选、右键、滚轮、双击都不受影响
  - 滚动/列宽变化/窗口尺寸变化后由 app 调 redraw() 重新贴合
  - 1px 线只占边框像素，不遮内容；开关整格覆盖并自绘底色

颜色在 redraw() 时读模块全局（apply_palette 会同步副本），主题热切换
后无需重建本控件也能换色。
"""

import time

import tkinter as tk

from .constants import (CLR_ACCENT, CLR_ACCENT_LT, CLR_BORDER_LT,
                        CLR_INPUT, CLR_LOW_BG, CLR_ROW_ALT, CLR_SEL,
                        CLR_UNLISTED_BG)
from .pillimg import capsule_b64


class TreeDecor(object):
    """表格网格线 + 上架开关覆盖层。

    app 端约定：
        self.decor = TreeDecor(self.tree, self)
        self.decor.redraw()   # 在 _after_scroll / render_page / 列配置后调用
    """

    def __init__(self, tree, app):
        self.tree = tree
        self.app = app
        self._v = []            # 正在显示的竖线
        self._h = []            # 正在显示的横线
        self._vpool = []        # 回收池（已隐藏，可复用）
        self._hpool = []
        self._pills = {}        # iid -> Canvas（开关）
        self._pill_pool = []    # 回收复用
        self._imgs = {}         # (pw, ph, fill, on) -> PhotoImage（抗锯齿胶囊）
        self._drag_t = 0.0      # 拖动列头时节流
        tree.bind("<Configure>", lambda e: self.redraw(), add="+")
        # 列宽拖动结束 / 滚动条拖动：等布局稳定后重排
        tree.bind("<ButtonRelease-1>", self._on_release, add="+")
        # 拖动列宽 / 拖动列头换位的过程中实时跟随（节流，松手时还会再排一次）
        tree.bind("<B1-Motion>", self._on_drag_motion, add="+")

    # ------------------------------------------------------------ 入口
    def redraw(self):
        """重排网格线与开关。

        滚动时不能 "全部隐藏再重建"——那样每滚一格都会闪一下。
        这里把活动对象先并回池，重新 place 到新坐标（同一次事件处理内完成，
        Tk 只重绘最终状态），最后只把用不到的收起来。
        """
        t = self.tree
        try:
            if not t.winfo_exists() or not t.winfo_ismapped():
                self._hide()
                return
            vw, vh = int(t.winfo_width()), int(t.winfo_height())
        except Exception:
            self._hide()
            return
        if vw <= 4 or vh <= 4:
            self._hide()
            return
        self._vpool.extend(self._v)
        self._hpool.extend(self._h)
        self._v = []
        self._h = []
        head_h = int(self.app._head_height())
        disp = t["displaycolumns"]
        # ttk 在没有自定义列顺序时返回 ('#all',)，不是 "all"
        if not disp or list(disp) == ["#all"] or disp == "all":
            disp = list(t["columns"])
        try:
            widths = [max(1, int(t.column(c, "width"))) for c in disp]
        except Exception:
            return
        total = sum(widths)
        if total <= 0:
            return
        xv = t.xview()
        xoff = float(xv[0]) * total
        cols = self.app._cols()
        has_listed = "listed" in cols
        # 先收集位置：开关必须先放、网格线后放（后 place 的在上层，
        # 否则开关整格铺底会把列边界和行分隔线盖出一个洞）
        vpos = []
        x = -xoff
        for w in widths:
            x += w
            if 2 < x < vw - 1:                    # 视口内的边界才画竖线
                vpos.append(int(x))
        hpos = []
        pills = []
        # 只扫视口内的行：整页 2000+ 行时逐行问 bbox 要 10ms，滚动会发涩
        kids = t.get_children()
        try:
            yf = t.yview()
            n = len(kids)
            i0 = max(0, int(yf[0] * n) - 2)
            i1 = min(n, int(yf[1] * n) + 3)
            scan = kids[i0:i1] if n else kids
        except Exception:
            scan = kids
        for iid in scan:
            try:
                bb = t.bbox(str(iid))
            except Exception:
                bb = None
            if not bb or int(bb[3]) <= 1:
                continue
            y = int(bb[1]) + int(bb[3])
            if head_h < y < vh - 1:
                hpos.append(y)
            if has_listed:
                try:
                    pb = t.bbox(str(iid), column="listed")
                except Exception:
                    pb = None
                if pb and int(pb[1]) >= head_h:
                    pills.append((str(iid), pb))
        live = set()
        for iid, pb in pills:
            live.add(iid)
        self._recycle_pills(live)      # 先把滚出视口的收进池，新行才能复用同一批对象
        for iid, pb in pills:
            self._pill(iid, pb)
        for x in vpos:
            self._vline(x, head_h, vh)
        for y in hpos:
            self._hline(0, y, vw)
        self._recycle_lines()
        self.restack()

    def restack(self):
        """显式定叠放：上色贴片 < 开关 < 网格线。

        Tk 的叠放次序按控件的创建先后（place 顺序不作数），上色贴片
        往往比开关晚创建、会盖住开关还露出「已上架」字样；所以每次
        重排/重画贴片后都抬一遍，保证开关永远可见可点。
        """
        for cv in self._pills.values():
            try:
                cv.lift()
            except Exception:
                pass
        for f in self._v + self._h:
            try:
                f.lift()
            except Exception:
                pass

    def _recycle_pills(self, live_pills):
        """收起本轮不可见的开关（放回池里等复用）。"""
        for iid in list(self._pills):
            if iid in live_pills:
                continue
            cv = self._pills.pop(iid)
            try:
                cv.place_forget()
            except Exception:
                pass
            cv._sig = None
            if len(self._pill_pool) < 64:
                self._pill_pool.append(cv)
            else:
                try:
                    cv.destroy()
                except Exception:
                    pass

    def _recycle_lines(self):
        """收起本轮没用到的线与开关（滚出视口 / 行已删）。"""
        for f in self._vpool:
            try:
                f.place_forget()
            except Exception:
                pass
        for f in self._hpool:
            try:
                f.place_forget()
            except Exception:
                pass

    def _on_release(self, e):
        # 点在表头（列宽拖动）结束后重排；数据行点击无需处理
        try:
            if self.tree.identify_region(e.x, e.y) in ("heading", "separator"):
                self.redraw()
        except Exception:
            pass

    def _on_drag_motion(self, e):
        # 拖列宽/拖列头换位的过程：开关和线要实时跟着列走（节流 ~13fps）
        try:
            if self.tree.identify_region(e.x, e.y) not in ("heading", "separator"):
                return
        except Exception:
            return
        now = time.time()
        if now - self._drag_t < 0.075:
            return
        self._drag_t = now
        self.redraw()

    # ------------------------------------------------------------ 竖线/横线
    def _get(self, pool):
        if pool:
            return pool.pop()
        f = tk.Frame(self.tree, bd=0, highlightthickness=0)
        self.app._bind_overlay_events(f)
        return f

    def _vline(self, x, y0, y1):
        f = self._get(self._vpool)
        f.configure(bg=CLR_BORDER_LT)
        try:
            f.place(x=x, y=y0, width=1, height=max(1, y1 - y0))
        except Exception:
            pass
        self._v.append(f)          # 活动列表：下轮 _hide 才收得回去

    def _hline(self, x, y, w):
        f = self._get(self._hpool)
        f.configure(bg=CLR_BORDER_LT)
        try:
            f.place(x=x, y=y, width=max(1, w), height=1)
        except Exception:
            pass
        self._h.append(f)

    # ------------------------------------------------------------ 开关
    def _row_bg(self, iid):
        """行底色：与 tree 的实际绘制顺序一致。

        优先级：用户上色（开关替贴片扛住该格，底色必须跟上）>
        划过（hover tag 最高）> 下架灰/低库存橙/斑马纹 > 选中蓝 > 默认。
        开关铺满整格，底色取错就会露出一个方框，所以必须逐层对齐。
        """
        try:
            cc = getattr(self.app, "cell_colors", None)
            if cc:
                c = cc.get(str(iid), {}).get("listed")
                if c:
                    return c
        except Exception:
            pass
        # 划过整行高亮已移除（v1.45.1）：开关底色只跟用户上色 / 下架灰
        try:
            tags = self.tree.item(iid, "tags")
        except Exception:
            tags = ()
        if "unlisted" in tags:
            return CLR_UNLISTED_BG
        if "low" in tags:
            return CLR_LOW_BG
        if "odd" in tags:
            return CLR_ROW_ALT
        try:
            if str(iid) in self.tree.selection():
                return CLR_SEL          # 无色块的行，选中色才真的画得出来
        except Exception:
            pass
        return CLR_INPUT

    def _pill(self, iid, bbox):
        cv = self._pills.get(iid)
        if cv is None:
            if self._pill_pool:
                cv = self._pill_pool.pop()
            else:
                cv = tk.Canvas(self.tree, bd=0, highlightthickness=0,
                               cursor="hand2")
                self._bind_pill_events(cv)
            self._pills[iid] = cv
        # 池复用后旧绑定还在，每次取用都重绑一次（iid 通过 _pills 反查）
        cv.bind("<Button-1>", self._on_pill_click)
        scale = float(getattr(self.app, "ui_scale", 1.0) or 1.0)
        x, y, w, h = (int(v) for v in bbox)
        pw = min(int(40 * scale), max(int(24 * scale), int(w * 0.42)))
        ph = min(int(16 * scale), h - int(10 * scale))
        if pw < 18 or ph < 8:
            return
        bg = self._row_bg(iid)
        try:
            rec = self.app.by_id.get(iid)
            on = bool(rec and rec.get("listed"))
        except Exception:
            on = False
        # 内容签名没变就只挪位置：滚动时不必每格都 delete + 重画
        sig = (bg, w, h, pw, ph, on)
        if getattr(cv, "_sig", None) != sig:
            self._draw_pill(cv, bg, w, h, pw, ph, iid)
            cv._sig = sig
            cv._geo = (w, h, pw, ph)   # 悬停换行时只刷底色不重排
        try:
            cv.place(x=x, y=y, width=w, height=h)
        except Exception:
            pass

    def refresh_colors(self):
        """只重画开关底色（鼠标换行时用，整层重排会闪）。"""
        for iid, cv in list(self._pills.items()):
            geo = getattr(cv, "_geo", None)
            if not geo:
                continue
            self._draw_pill(cv, self._row_bg(iid), geo[0], geo[1], geo[2], geo[3], iid)
            cv._sig = None       # 内容改由 _draw_pill 直接画，签名作废以便下轮重认

    def _bind_pill_events(self, cv):
        """开关只接管左键；滚轮/右键必须自己补，否则指针停在开关上就断。
        （划过整行高亮已移除，v1.45.1——Motion/Enter/Leave 不再需要转发）"""
        app = self.app
        cv.bind("<MouseWheel>", app._on_wheel)
        cv.bind("<Button-3>", lambda e: self.tree.event_generate(
            "<Button-3>", x=e.x, y=e.y, rootx=e.x_root, rooty=e.y_root))

    def _draw_pill(self, cv, bg, w, h, pw, ph, iid):
        cv.delete("all")
        cv.configure(bg=bg)
        try:
            rec = self.app.by_id.get(iid)
            on = bool(rec and rec.get("listed"))
        except Exception:
            on = False
        fill = CLR_ACCENT if on else "#C4CBDA"
        img = self._pill_image(pw, ph, fill, on)
        if img is not None:
            # 抗锯齿胶囊（Tk 的 oval 是硬边，看着不圆润）
            cv.create_image(w // 2, h // 2, image=img)
        else:
            self._draw_pill_vector(cv, w, h, pw, ph, fill, on)
        # 「是/否」字样：画在滑块对侧的空半边（像素字号 + 粗体，小字才清楚）
        try:
            fam = self.app.fam
        except Exception:
            fam = "Microsoft YaHei"
        fs = -max(10, ph - 6)                # 负数 = 像素字号
        px = (w - pw) // 2
        m = 2
        d = ph - 2 * m
        if on:
            tx, tc = px + (pw - d) / 2.0, "#FFFFFF"
            txt = "是"
        else:
            tx, tc = px + d + (pw - d) / 2.0, "#39445C"
            txt = "否"
        if pw - d >= 12:
            cv.create_text(tx, h / 2.0, text=txt, fill=tc,
                           font=(fam, fs, "bold"))

    def _pill_image(self, pw, ph, fill, on):
        """抗锯齿胶囊图片（按尺寸/颜色缓存，PhotoImage 必须留引用）。"""
        key = (int(pw), int(ph), fill, bool(on))
        img = self._imgs.get(key)
        if img is not None:
            return img
        try:
            b64 = capsule_b64(pw, ph, fill, on)
            if not b64:
                return None
            img = tk.PhotoImage(data=b64)
        except Exception:
            return None
        self._imgs[key] = img
        return img

    def _draw_pill_vector(self, cv, w, h, pw, ph, fill, on):
        """兜底矢量画法（图片加载失败时用，边缘有锯齿）。"""
        px, py = (w - pw) // 2, (h - ph) // 2
        m = 2
        d = ph - 2 * m
        cv.create_oval(px, py + m, px + d, py + m + d, fill=fill, outline=fill)
        cv.create_oval(px + pw - d, py + m, px + pw, py + m + d,
                       fill=fill, outline=fill)
        cv.create_rectangle(px + d / 2, py + m, px + pw - d / 2, py + m + d,
                            fill=fill, outline=fill)
        kx = px + pw - m - d if on else px + m
        cv.create_oval(kx, py + m, kx + d, py + m + d, fill="#FFFFFF",
                       outline=CLR_ACCENT_LT if on else "#9AA3B2")

    def _on_pill_click(self, e):
        # 点中的开关：找到 place 时的 iid（canvas 挂在 _pills 里反查）
        for iid, cv in list(self._pills.items()):
            if cv is e.widget:
                try:
                    self.app.toggle_listed_iid(iid)
                except Exception:
                    pass
                return "break"
        return "break"

    # ------------------------------------------------------------ 隐藏
    def _hide(self):
        for f in self._v + self._h:
            try:
                f.place_forget()
            except Exception:
                pass
        self._vpool.extend(self._v)
        self._hpool.extend(self._h)
        self._v = []
        self._h = []
        for cv in self._pills.values():
            try:
                cv.place_forget()
            except Exception:
                pass
        self._pill_pool.extend(self._pills.values())
        self._pills.clear()
