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
                        CLR_UNLISTED_BG, UI_THEME)
from .pillimg import capsule_b64

try:
    from PIL import Image, ImageDraw, ImageTk, ImageFont
    HAS_PIL = True
except Exception:
    HAS_PIL = False

# 设计稿同款徽章配色（light / dark）
_BADGE_ON = {"light": ("#DCFCE7", "#15803D"), "dark": ("#0E2A18", "#4ADE80")}
_BADGE_OFF = {"light": ("#E2E8F0", "#64748B"), "dark": ("#233049", "#94A3B8")}


def _shade(css, k):
    """hex 颜色加深(k<1)/提亮(k>1)：让胶囊与行底同色系但保留可见轮廓。"""
    try:
        s = str(css).lstrip("#")
        if len(s) != 6:
            return css
        ch = [int(s[i:i + 2], 16) for i in (0, 2, 4)]
        if k < 1:
            out = [int(v * k) for v in ch]
        else:
            out = [min(255, int(v + (255 - v) * (k - 1))) for v in ch]
        return "#%02X%02X%02X" % tuple(out)
    except Exception:
        return css

_FONT_FILES = [(False, "C:/Windows/Fonts/msyh.ttc"),
               (True, "C:/Windows/Fonts/msyhbd.ttc"),
               (False, "C:/Windows/Fonts/simhei.ttf")]


def _badge_font(bold, px):
    for want_bold, path in _FONT_FILES:
        if want_bold != bold:
            continue
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default()


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
        self._pills = {}        # iid -> Canvas（上架徽章）
        self._pill_pool = []    # 回收复用
        self._chks = {}         # iid -> Canvas（首列复选框，v1.46.3）
        self._chk_pool = []     # 回收复用
        self._head_chk = None   # 表头全选复选框（v1.46.7，设计稿同款三态）
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
        has_chk = "_chk" in disp
        # 先收集位置：开关必须先放、网格线后放（后 place 的在上层，
        # 否则开关整格铺底会把列边界和行分隔线盖出一个洞）
        vpos = []
        x = -xoff
        for w in widths:
            x += w
            if 2 < x < vw - 1:                    # 视口内的边界才画竖线
                vpos.append(int(x))
        # 表头全选复选框（v1.46.7）：画在首列 _chk 表头格中央，设计稿同款
        # 三态圆角方块（全选蓝勾 / 半选蓝横杠 / 未选灰边），点它全选/全不选。
        if has_chk and widths:
            self._head_chkbox(0, 0, widths[0], head_h)
        elif self._head_chk is not None:
            self._head_chk.place_forget()

        hpos = []
        pills = []
        chks = []
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
            # 行被裁掉一半以上就不画徽章/复选框：避免表格底部出现
            # 「只有一颗徽章、没有行内容」的游离贴片（v1.46.3 用户反馈；
            # v1.46.5 再收紧：中点判断对「bbox 高度被裁」的形态失效，
            # 改为贴片整格必须完整落在行区内才画）
            if int(bb[1]) + int(bb[3]) // 2 > vh:
                continue
            if iid not in getattr(self.app, "by_id", {}):
                continue
            if has_listed:
                try:
                    pb = t.bbox(str(iid), column="listed")
                except Exception:
                    pb = None
                if (pb and int(pb[1]) >= head_h
                        and int(pb[1]) + int(pb[3]) <= vh):
                    pills.append((str(iid), pb))
            if has_chk:
                try:
                    cb = t.bbox(str(iid), column="_chk")
                except Exception:
                    cb = None
                if (cb and int(cb[1]) >= head_h
                        and int(cb[1]) + int(cb[3]) <= vh):
                    chks.append((str(iid), cb))
        live = set()
        for iid, pb in pills:
            live.add(iid)
        self._recycle_pills(live)      # 先把滚出视口的收进池，新行才能复用同一批对象
        for iid, pb in pills:
            self._pill(iid, pb)
        live = set()
        for iid, cb in chks:
            live.add(iid)
        self._recycle_chks(live)
        for iid, cb in chks:
            self._chkbox(iid, cb)
        for x in vpos:
            self._vline(x, head_h, vh)
        for y in hpos:
            self._hline(0, y, vw)
        self._recycle_lines()
        self.restack()

    def restack(self):
        """显式定叠放：上色贴片 < 开关 < 网格线 < 表头复选框。

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
        if self._head_chk is not None:
            try:
                self._head_chk.lift()
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

        优先级：用户上色 > 选中蓝 > 下架灰/低库存橙/斑马纹 > 默认。
        v1.46.9：选中态必须排在 unlisted/low/odd 之前——Treeview 自身把
        选中蓝画在整行上（盖过下架灰/斑马），覆盖层贴片若还按下架灰取色，
        就会出现「复选框/徽章格底色和整行不一样」的两色割裂（用户红框反馈）。
        只有用户手动上色格仍最高优先（贴片替它扛住该格底色）。
        """
        try:
            cc = getattr(self.app, "cell_colors", None)
            if cc:
                c = cc.get(str(iid), {}).get("listed")
                if c:
                    return c
        except Exception:
            pass
        # Treeview 选中蓝盖过其它行 tag：贴片底色必须跟随
        try:
            if str(iid) in self.tree.selection():
                return CLR_SEL
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
        """「上架状态」列徽章（v1.46.2，设计稿同款 pill：圆点+文字）。

        点击整格仍可切换上架状态（原开关行为保留）。
        """
        cv.delete("all")
        cv.configure(bg=bg)
        try:
            rec = self.app.by_id.get(iid)
            on = bool(rec and rec.get("listed"))
        except Exception:
            on = False
        img = self._badge_image(on, w, h, bg)
        if img is not None:
            cv.create_image(w // 2, h // 2, image=img)
        else:
            # 兜底矢量徽章（图片加载失败时）
            txt = "已上架" if on else "下架"
            theme = UI_THEME if UI_THEME in ("light", "dark") else "light"
            fgc = (_BADGE_ON if on else _BADGE_OFF)[theme][1]
            bgc = bg or (_BADGE_ON if on else _BADGE_OFF)[theme][0]
            bh = max(12, min(int(22 * float(getattr(self.app, "ui_scale", 1.0) or 1.0)), h - 8))
            cv.create_rectangle(w // 2 - 30, h // 2 - bh // 2, w // 2 + 30,
                                h // 2 - bh // 2 + bh, fill=bgc, outline=bgc)
            cv.create_text(w // 2, h // 2, text=txt, fill=fgc)

    def _badge_image(self, on, cw, ch, bg=None):
        """抗锯齿徽章 PNG（PIL 渲染，按 (on,宽,高,主题,底色) 缓存）。

        v1.46.3 收小一档（设计稿 pill 高约 18px、8.5pt 字），避免整格
        被大徽章撑满显得笨重。
        v1.46.9：徽章胶囊底色跟随所在行底色（选中蓝/下架灰/斑马白…）。
        v1.46.10：纯用行底色会让胶囊轮廓消失（用户「框怎么没了」），改为
        同色系略深一档填充 + 一圈细描边——颜色协调但框清晰可见。
        """
        if not HAS_PIL or cw < 36 or ch < 14:
            return None
        theme = UI_THEME if UI_THEME in ("light", "dark") else "light"
        fgc = (_BADGE_ON if on else _BADGE_OFF)[theme][1]
        # 底色跟随行底色；无底色传入时退回主题默认胶囊色
        bgc = bg or (_BADGE_ON if on else _BADGE_OFF)[theme][0]
        # 同色系略深填充 + 细描边，保住胶囊轮廓（light 加深 / dark 提亮）
        fill_c = _shade(bgc, 0.88 if theme == "light" else 1.18)
        edge_c = _shade(bgc, 0.78 if theme == "light" else 1.30)
        scale = float(getattr(self.app, "ui_scale", 1.0) or 1.0)
        bh = min(int(18 * scale), ch - int(10 * scale))
        if bh < 11:
            bh = ch - 4
        px = max(9, int(round(8.5 * 96.0 / 72 * scale)))
        f = _badge_font(True, px)
        txt = "已上架" if on else "下架"
        meas = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        try:
            box = meas.textbbox((0, 0), txt, font=f)
            tw2, th2 = box[2] - box[0], box[3] - box[1]
        except AttributeError:
            tw2, th2 = meas.textsize(txt, font=f)
        dot = max(3, int(2.5 * scale))
        pad = max(4, int(7 * scale))
        gap = max(3, int(3.5 * scale))
        bw = pad * 2 + dot + gap + tw2
        if bw > cw - int(8 * scale):
            bw = cw - int(8 * scale)
        key = (bool(on), int(bw), int(bh), theme, str(bgc))
        img = self._imgs.get(key)
        if img is not None:
            return img
        im = Image.new("RGBA", (int(bw), int(bh)), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=bh // 2,
                            fill=fill_c, outline=edge_c, width=1)
        cy = bh / 2.0
        d.ellipse([pad, cy - dot / 2, pad + dot, cy + dot / 2], fill=fgc)
        try:
            box = d.textbbox((0, 0), txt, font=f)
            ox, oy = box[0], box[1]
            th2 = box[3] - box[1]
        except AttributeError:
            ox = oy = 0
        d.text((pad + dot + gap - ox, cy - th2 / 2 - oy), txt, font=f, fill=fgc)
        img = ImageTk.PhotoImage(im)
        self._imgs[key] = img
        return img

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

    # ------------------------------------------------ 复选框列（v1.46.3）
    def _recycle_chks(self, live_iids):
        """收起本轮不可见的复选框贴片（放回池里复用）。"""
        for iid in list(self._chks):
            if iid in live_iids:
                continue
            cv = self._chks.pop(iid)
            try:
                cv.place_forget()
            except Exception:
                pass
            cv._sig = None
            if len(self._chk_pool) < 96:
                self._chk_pool.append(cv)
            else:
                try:
                    cv.destroy()
                except Exception:
                    pass

    def _chkbox(self, iid, bbox):
        """首列复选框贴片：小圆角方块，选中=品牌蓝底白勾（设计稿同款）。"""
        cv = self._chks.get(iid)
        if cv is None:
            if self._chk_pool:
                cv = self._chk_pool.pop()
            else:
                cv = tk.Canvas(self.tree, bd=0, highlightthickness=0,
                               cursor="hand2")
                cv.bind("<MouseWheel>", self.app._on_wheel)
                cv.bind("<Button-3>", lambda e: self.tree.event_generate(
                    "<Button-3>", x=e.x, y=e.y, rootx=e.x_root, rooty=e.y_root))
            self._chks[iid] = cv
        cv.bind("<Button-1>", self._on_chk_click)
        x, y, w, h = (int(v) for v in bbox)
        scale = float(getattr(self.app, "ui_scale", 1.0) or 1.0)
        px = min(int(16 * scale), h - int(8 * scale), w - int(12 * scale))
        if px < 10:
            return
        try:
            checked = str(iid) in self.tree.selection()
        except Exception:
            checked = False
        bg = self._row_bg(iid)
        sig = (bg, w, h, px, checked)
        if getattr(cv, "_sig", None) != sig:
            self._draw_chk(cv, bg, w, h, px, checked)
            cv._sig = sig
        try:
            cv.place(x=x, y=y, width=w, height=h)
        except Exception:
            pass

    def _draw_chk(self, cv, bg, w, h, px, checked):
        cv.delete("all")
        cv.configure(bg=bg)
        img = self._chk_image(checked, px)
        if img is not None:
            cv.create_image(w // 2, h // 2, image=img)

    def _chk_image(self, checked, px):
        """抗锯齿复选框：未选=白底灰边圆角方块；选中=蓝底白勾；
        半选=蓝底白横杠（表头部分选中态）。

        checked 接受 True / False / "partial"；行里只传 bool，表头传三态。
        """
        if not HAS_PIL:
            return None
        state = ("on" if checked is True
                 else "off" if checked is False else "partial")
        key = ("chk", state, int(px))
        img = self._imgs.get(key)
        if img is not None:
            return img
        SS = 4
        W = px * SS
        if state in ("on", "partial"):
            fill, outline = CLR_ACCENT, CLR_ACCENT
        else:
            fill, outline = "#FFFFFF", "#C9D2DE"
        im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, W - 1, W - 1], radius=int(2.5 * SS),
                            fill=fill, outline=outline, width=SS)
        if state == "on":
            # 白勾：圆头折线（相对坐标，居中）
            lw = max(2, int(1.8 * SS))
            pts = [(0.26 * W, 0.53 * W), (0.43 * W, 0.70 * W), (0.74 * W, 0.32 * W)]
            d.line(pts, fill="#FFFFFF", width=lw, joint="curve")
            for p in (pts[0], pts[2]):
                r = lw / 2.0
                d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill="#FFFFFF")
        elif state == "partial":
            # 白横杠：圆头短线（表头部分选中）
            lw = max(2, int(1.8 * SS))
            d.line([(0.28 * W, 0.5 * W), (0.72 * W, 0.5 * W)],
                   fill="#FFFFFF", width=lw)
            r = lw / 2.0
            for x in (0.28 * W, 0.72 * W):
                d.ellipse([x - r, 0.5 * W - r, x + r, 0.5 * W + r], fill="#FFFFFF")
        img = ImageTk.PhotoImage(im.resize((px, px), Image.LANCZOS))
        self._imgs[key] = img
        return img

    # -------------------------------------------- 表头全选复选框（v1.46.7）
    def _head_chkbox(self, x, y, w, h):
        """表头首列画设计稿同款复选框：有选中=蓝底白勾 / 无选中=白底灰边。

        v1.46.8 两处修正（用户反馈）：
        ① 位置：canvas 占满整列宽（同行复选框一致），图在 w//2 —— 之前用
           cx 偏移 + 缩窄 canvas，中心跟行复选框差十几像素（明显错位）。
        ② 状态：不要半选横杠，只要有选中就显示勾（与行选中态同款）。
        """
        cv = self._head_chk
        if cv is None:
            cv = tk.Canvas(self.tree, bd=0, highlightthickness=0,
                           cursor="hand2")
            cv.bind("<Button-1>", self._on_head_chk_click)
            cv.bind("<MouseWheel>", self.app._on_wheel)
            self._head_chk = cv
        sel = len(self.tree.selection())
        state = bool(sel)              # 有选中就画勾，不再区分全选/半选
        scale = float(getattr(self.app, "ui_scale", 1.0) or 1.0)
        px = min(int(15 * scale), h - int(6 * scale), w - int(10 * scale))
        if px < 9:
            cv.place_forget()
            return
        img = self._chk_image(state, px)
        sig = (state, px, w, h)
        # 画布占满整列（x..x+w），图片画在正中 w//2 —— 与行复选框定位完全一致
        if getattr(cv, "_sig", None) != sig:
            cv.delete("all")
            cv.configure(bg=self._head_bg())
            if img is not None:
                cv.create_image(w // 2, h // 2, image=img)
            cv._sig = sig
        try:
            cv.place(x=x, y=y, width=w, height=h)
        except Exception:
            pass

    def _head_bg(self):
        """表头底色（跟随主题）；取 ttk 样式，取不到用常量兜底。"""
        try:
            import tkinter.ttk as ttk
            bg = ttk.Style().lookup("Treeview.Heading", "background")
            if bg:
                return bg
        except Exception:
            pass
        from . import constants as C
        return getattr(C, "CLR_HEADER", "#F3F6FB")

    def _on_head_chk_click(self, e):
        """点表头复选框：全不选 ⇄ 全选（当前页全部行）。"""
        try:
            self.app._toggle_check_all()
        except Exception:
            pass
        return "break"

    def _on_chk_click(self, e):
        """点复选框贴片：只切换该行选中（不清其他行），同 Ctrl+点行。"""
        for iid, cv in list(self._chks.items()):
            if cv is e.widget:
                try:
                    self.app._chk_toggle_iid(iid)
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
        for cv in self._chks.values():
            try:
                cv.place_forget()
            except Exception:
                pass
        self._chk_pool.extend(self._chks.values())
        self._chks.clear()
        if self._head_chk is not None:
            try:
                self._head_chk.place_forget()
            except Exception:
                pass
