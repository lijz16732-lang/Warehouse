# -*- coding: utf-8 -*-
"""使用说明窗口。

原来的 messagebox 放长文本会被 Windows 截断（超出部分看不到），这里改成
独立窗口：左侧目录跳转、右侧可滚动正文、支持关键词搜索与一键复制。
"""

import tkinter as tk
from tkinter import ttk

from .constants import (CLR_ACCENT, CLR_BG, CLR_BORDER, CLR_CARD, CLR_DANGER,
                        CLR_MUTED, CLR_TEXT, apply_window_icon, center_window)


def help_sections(db_path=""):
    """使用说明正文，按章节拆分：[(章节名, 正文), ...]。"""
    return [
        ("快速上手",
         "1. 点「导入 XLSX」选择 Excel 文件，系统会自动识别表头并预览字段映射；\n"
         "2. 「导入方式」选「按型号合并」：型号已存在的行会跳过，型号不存在才新增，\n"
         "   库中原有记录不会被改动；预览区的「重复判断」列会标出每行将新增还是跳过；\n"
         "3. 双击任意单元格即可编辑；双击「上架状态」列可直接上/下架；\n"
         "4. 鼠标按住左键在表格里划过若干单元格即可框选区块：松开鼠标自动复制到剪贴板\n"
         "   （可直接粘贴进 Excel），右下「记录详情」也会同步显示这块内容，\n"
         "   那里的文字可用鼠标拖选、Ctrl+C 复制；勾选「拖选即复制」可关闭这个自动复制；\n"
         "5. 右键列表可复制单元格、整行、整列、选中行或全部结果（可直接粘贴到 Excel）；\n"
         "   「出售记录」「出库记录」两个页面的表格同样支持：拖选复制、Ctrl+C、右键复制；\n"
         "6. 手动上色：按住左键划过要标记的单元格（或先选中若干行），右键 →「区域上色」\n"
         "   选颜色即可（8 个预设色 + 「自定义颜色…」取色器），颜色随仓库永久保存；\n"
         "   同一菜单里可「取消选区颜色」或「取消全部颜色」，\n"
         "   也可用「数据 → 清除全部单元格颜色」一次清干净；\n"
         "7. 左侧可按品牌/品类/成色/货架/上架状态/价格区间筛选（下拉框也能直接打字筛），\n"
         "   表头点击可排序；下架的行默认灰显，可在左侧或「数据」菜单关掉；\n"
         "8. 鼠标划过表格任意一行会整行淡蓝高亮（移开即恢复），方便横向看数据；\n"
         "9. 「数据分析」页提供指标卡与多维度图表，可一键导出统计报表；\n"
         "10. 「数据 → 按型号检查重复」可列出库中重复录入的型号；\n"
         "    「数据 → 按型号去重」可一键清理重复（每组保留最早一条）。"),

        ("导入方式说明",
         "· 按型号合并（推荐）—— 与库中数据对比：型号已存在的行跳过不导入，\n"
         "  不会改动、不会删除库中已有记录；型号不存在的行才新增，永不产生重复条目；\n"
         "· 追加导入 —— 全部原样加入，不做重复判断、不去重；\n"
         "· 覆盖全部 —— 先清空再导入，编号从 WL-00001 重新开始；文件内自动去重。"),

        ("多仓库",
         "· 顶部工具栏「仓库」下拉可随时切换，每个仓库是独立的一套数据、\n"
         "  独立的编号（都从 WL-00001 开始）与独立的统计；\n"
         "· 「管理」或「数据 → 仓库管理」可新建仓库（空白 / 复制当前仓数据）、\n"
         "  重命名、移除（移除只从列表去掉，数据库文件保留在数据目录）。"),

        ("编号规则",
         "· 库中还有数据 —— 新记录编号接着已有最大编号往下排，不会重号；\n"
         "· 数据被清空后（清空全部数据 / 覆盖导入）—— 编号从 WL-00001 重新开始。"),

        ("登记出售（销售出库）",
         "· 选中一行后点工具栏「登记出售」（或右键 / Ctrl+D）：填写数量、售价、\n"
         "  日期、买家、收货地址即可成交，库存数量自动扣减；\n"
         "· 「收货地址」选填：下拉可选历史地址，选中已有买家时会自动带出\n"
         "  该买家上次用过的地址（只统计销售记录，可按地址搜索）；\n"
         "· 出售也是出库（同样减库存），所以也会出现在「出库记录」总览里；\n"
         "· 计入「出售记录」页的销售额 / 成本 / 利润 / 买家统计与趋势图、销售目标；\n"
         "· 数量扣到 0 时记录保留并标记「已售完」（列表灰显，可用上架状态筛选）。"),

        ("手动补录出售（不扣库存）",
         "· 在「出售记录」页点右上「+ 登记出售」：不用先在库存里选货，直接手填一条记录；\n"
         "· 适合补录系统外的成交（老货、代发、库存早已清掉等），只写记录、不扣库存；\n"
         "· 编号填库里已有的编号时，会自动带出品牌 / 品类 / 型号 / 货架 / 成本单价\n"
         "  （都能改）；没登记过采购成本的商品按原单价估算，利润口径与正常出售一致；\n"
         "· 撤销这类记录只删除记录，不会给任何商品加回数量（提示会写明「不涉及库存」）。"),

        ("局域网共享（多台电脑共用一份数据）",
         "· 一台常开的电脑当「主机」：菜单「数据 → 局域网共享」→ 填端口和连接码 →"
         "「开启共享」；\n"
         "· 其他电脑打开同一个程序，在同一个窗口里填主机地址（主机的 本机地址 + 端口，"
         "可用「复制地址」发过去）和连接码 → 「连接」；\n"
         "· 数据只有主机这一份，客户端连上后看到的就是主机当前的数据，本机不存副本；\n"
         "· 权限：其他电脑默认「只读」（可查看、筛选、导出）；要录入时点顶部「请求录入」，"
         "  主机上会弹窗询问，允许后即可新增 / 修改 / 出入库；\n"
         "· 主机在「已连接的电脑」列表里双击一行，也可以随时授权或收回；\n"
         "  选中一行后还能「移除连接」（对方立即断开、可重连）或「加入黑名单」\n"
         "  （该电脑彻底无法连接，直到在「黑名单管理」里移出，黑名单重启后仍在）；\n"
         "· 一台电脑只能选一种角色（①主机 或 ②客户端），窗口右上角带「当前角色」标签的\n"
         "  就是本机正在用的那一种；客户端状态下「开启共享」按钮是灰的，\n"
         "  要当主机请先点「断开 / 回到本机」；主机状态下去连接别人的主机，\n"
         "  会先弹窗确认（连接会停掉本机共享，已连上的电脑会断开）；\n"
         "· 客户端连接成功过的主机会记在「历史连接」里（最多 8 条，只存本机），\n"
         "  下次在下拉框选中就自动填好地址、端口和连接码，不用再翻聊天记录；\n"
         "· 主机换仓库、改数据，客户端几秒内自动跟随；首次开启共享时，"
         "  Windows 若询问防火墙请选择「允许」；\n"
         "· 手机端（App）：主机开启共享后，③ 手机访问里有地址和二维码。手机安装\n"
         "  《仓管家手机版》App（android 目录可打包生成 apk），首次打开填入地址、\n"
         "  输入连接码即可；手机默认只读，登记出售要点「申请权限」由主机弹窗确认；\n"
         "  会话 12 小时有效，连接码连错 5 次锁 10 分钟，「手机全部下线」可一键踢掉。"),

        ("登记出库（非销售出库）",
         "· 选中一行后点「出库记录」页右上「+ 登记出库」（或右键 / Ctrl+U）：\n"
         "  选类型（报废 / 损耗 / 退货 / 借出 / 赠送 / 调拨 / 其他），\n"
         "  填数量与原因/去向，只扣库存；\n"
         "· 不填售价和买家，不计销售额与利润，不会混进出售统计；\n"
         "· 「出库记录」是「全部出库」的总览：既有销售出库（类型=销售），\n"
         "  也有报废/损耗/退货等非销售出库（列表淡黄底标出）；\n"
         "· 出库页统一按「库存减少价值（成本单价 × 数量）」统计，\n"
         "  KPI 为 出库笔数 / 出库件数 / 成本价值 / 其中销售与非销售笔数，\n"
         "  支持日期·品牌·类型·关键词筛选、导出 XLSX、双击一行撤销（数量加回库存）；\n"
         "· 只想看销售流水与利润，去「出售记录」页（含售价/销售额/利润/买家/收货地址）。"),

        ("修改出库类型（如：出库去维修 → 修好后卖掉）",
         "· 在「出库记录」或「出售记录」里选中一行，点底部「修改类型」\n"
         "  （或右键「修改选中记录的类型…」）；\n"
         "· 改类型不会重复扣库存 —— 这笔出库登记时已经扣过一次；\n"
         "· 改成「销售」：补填售价、买家、收货地址、日期，立刻计入销售额与利润；\n"
         "· 改成报废/损耗/磨损等非销售类型：售价与买家、地址清空，只留出库痕迹；\n"
         "· 多条一起选中时只能批量改成非销售类型（改销售要填金额，需一次一条）。"),

        ("买家与销售目标（都在「出售记录」页）",
         "· 「显示趋势图」可展开近 12 个月销售额柱状图与品牌销售额排行（只统计销售）；\n"
         "· 「设置目标」可设置本月销售目标，页面上会显示完成进度条；\n"
         "· 「买家管理」按买家汇总消费金额与贡献利润，可重命名（改成已有买家名即合并）；\n"
         "· 「导出出售记录」导出的 XLSX 里同样带「收货地址」列，方便打单发货。"),

        ("采购入库 / 成本",
         "· 选中一行后点工具栏「采购入库」（或右键 / Ctrl+P）：填写采购数量、\n"
         "  采购单价、供应商即可入库，库存数量自动增加；\n"
         "· 成本单价按「移动加权平均」自动重算，利润 = 销售额 − 成本×数量；\n"
         "· 未登记过采购的商品，出售时成本退回用「原单价」估算；\n"
         "· 「数据 → 采购记录」可查看/撤销采购并导出 XLSX。"),

        ("批量修改字段",
         "· 选中多行后点「批量修改」（或右键 / Ctrl+B）：勾选要改的字段并填新值，\n"
         "  一次可统一修改货架、成色、品牌、备注、价格、数量、上架状态等。"),

        ("回收站",
         "· 删除的记录不会立刻消失，而是先进回收站（数据 → 回收站）；\n"
         "· 在回收站里可「恢复选中」（编号保持不变）或「彻底删除 / 清空回收站」。"),

        ("低库存提醒",
         "· 默认不高亮：数量 ≤ 阈值的记录与普通记录显示一致；\n"
         "· 需要提醒时勾选左侧筛选区（或「数据」菜单）的「低库存橙色高亮」，\n"
         "  数量 ≤ 阈值的记录会橙色高亮，数量为 0 的显示深橙色文字；\n"
         "· 无论是否高亮，勾选左侧「只看低库存」都可只显示这些记录（数量为 0\n"
         "  的缺货记录也算低库存），侧栏也会统计「低库存 N 条」；\n"
         "· 阈值在「数据 → 低库存阈值设置」里调整（默认 3 件）；\n"
         "· 高亮开关随仓库保存，下次打开保持上次的选择。"),

        ("快捷键",
         "Ctrl+I 导入    Ctrl+S 导出    Ctrl+N 新增    Ctrl+E 编辑\n"
         "Ctrl+D 登记出售    Ctrl+U 登记出库    Ctrl+P 采购入库    Ctrl+B 批量修改\n"
         "Ctrl+C 复制（框选区块 / 选中行，库存·出售·出库三页通用）    Ctrl+A 全选本页\n"
         "Ctrl+F 搜索    F5 刷新"),

        ("数据存放",
         "%s\n\n提示：数据库文件可直接复制备份。" % (db_path or "（打开程序后显示）")),
    ]


class HelpDialog(tk.Toplevel):
    """使用说明窗口：左目录 + 右滚动正文 + 搜索。"""

    def __init__(self, master, sections, fam="Microsoft YaHei UI", version=""):
        super().__init__(master)
        self.fam = fam
        self.sections = list(sections or [])
        self.marks = []
        self.title("使用说明")
        self.configure(bg=CLR_BG)
        self.transient(master)
        apply_window_icon(self)
        self._build(version)
        center_window(self, master, size=(900, 680))
        self.minsize(640, 420)
        self.resizable(True, True)
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.toc.selection_clear(0, "end")
        self.text.focus_set()

    # ------------------------------------------------------------ UI
    def _build(self, version):
        head = tk.Frame(self, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        head.pack(fill="x")
        tk.Label(head, text="使用说明", bg=CLR_CARD, fg=CLR_TEXT,
                 font=(self.fam, 13, "bold")).pack(side="left", padx=(16, 8), pady=10)
        tk.Label(head, text=("版本 %s" % version) if version else "",
                 bg=CLR_ACCENT, fg="#FFFFFF", font=(self.fam, 8)).pack(
            side="left", pady=12)

        # 搜索（右侧，先 pack 保证窗口变窄时不被挤掉）
        self.var_kw = tk.StringVar()
        self.lbl_found = tk.Label(head, text="", bg=CLR_CARD, fg=CLR_MUTED,
                                  font=(self.fam, 8), width=12, anchor="w")
        self.lbl_found.pack(side="right", padx=(0, 14))
        ent = tk.Entry(head, textvariable=self.var_kw, width=16, font=(self.fam, 9),
                       relief="flat", highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        ent.pack(side="right", ipady=3, pady=10)
        ent.bind("<Return>", lambda e: self._find())
        ent.bind("<KeyRelease>", self._on_search_key)
        tk.Label(head, text="搜索", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(side="right", padx=(0, 4))

        body = tk.Frame(self, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=12, pady=10)

        # 左：目录
        left = tk.Frame(body, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        left.pack(side="left", fill="y")
        tk.Label(left, text="目录", bg=CLR_CARD, fg=CLR_MUTED,
                 font=(self.fam, 9)).pack(anchor="w", padx=10, pady=(8, 4))
        self.toc = tk.Listbox(left, width=17, font=(self.fam, 9),
                              bd=0, highlightthickness=0, activestyle="none",
                              bg=CLR_CARD, fg=CLR_TEXT,
                              selectbackground=CLR_ACCENT, selectforeground="#FFFFFF",
                              exportselection=False)
        self.toc.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        for title, _ in self.sections:
            self.toc.insert("end", title)
        self.toc.bind("<<ListboxSelect>>", self._jump)

        # 右：正文
        right = tk.Frame(body, bg=CLR_CARD, highlightbackground=CLR_BORDER,
                         highlightthickness=1)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.text = tk.Text(right, wrap="word", bd=0, highlightthickness=0,
                            bg=CLR_CARD, fg=CLR_TEXT, font=(self.fam, 10),
                            padx=16, pady=12, cursor="arrow",
                            spacing1=2, spacing2=3, spacing3=4)
        vs = ttk.Scrollbar(right, orient="vertical", style="Vertical.TScrollbar",
                           command=self.text.yview)
        self.text.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        self.text.tag_configure("h", font=(self.fam, 12, "bold"), foreground=CLR_ACCENT,
                                spacing1=16, spacing3=6)
        self.text.tag_configure("body", font=(self.fam, 10), lmargin1=2, lmargin2=2)
        self.text.tag_configure("hit", background="#FFE58F")
        for i, (title, body_txt) in enumerate(self.sections):
            idx = self.text.index("end-1c")
            self.text.mark_set("sec_%d" % i, idx)
            self.text.mark_gravity("sec_%d" % i, "left")
            self.marks.append(idx)
            if i:
                self.text.insert("end", "\n")
            self.text.insert("end", title + "\n", "h")
            self.text.insert("end", body_txt + "\n", "body")
        self.text.configure(state="disabled")

        # 滚轮：正文与目录都能滚
        for w in (self.text, self.toc):
            w.bind("<MouseWheel>", self._wheel)

        foot = tk.Frame(self, bg=CLR_BG)
        foot.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Button(foot, text="关闭", width=10,
                   command=self.destroy).pack(side="right")
        ttk.Button(foot, text="复制全部说明", style="Ghost.TButton",
                   command=self._copy_all).pack(side="right", padx=(0, 8))
        self.lbl_tip = tk.Label(foot, text="左侧点章节可跳转 · 文本可拖选复制 · Esc 关闭",
                                bg=CLR_BG, fg=CLR_MUTED, font=(self.fam, 8))
        self.lbl_tip.pack(side="left")

    # ------------------------------------------------------------ 动作
    def _wheel(self, event):
        delta = -1 if event.delta > 0 else 1
        event.widget.yview_scroll(delta * 3, "units")
        return "break"

    def _jump(self, _event=None):
        sel = self.toc.curselection()
        if not sel:
            return
        i = int(sel[0])
        if 0 <= i < len(self.marks):
            self.text.yview(self.marks[i])

    def _on_search_key(self, _event=None):
        if not (self.var_kw.get() or "").strip():
            self.text.tag_remove("hit", "1.0", "end")
            self.lbl_found.configure(text="")

    def _find(self):
        kw = (self.var_kw.get() or "").strip()
        self.text.tag_remove("hit", "1.0", "end")
        if not kw:
            self.lbl_found.configure(text="")
            return
        start, count, first = "1.0", 0, None
        while True:
            idx = self.text.search(kw, start, stopindex="end", nocase=True)
            if not idx:
                break
            end = "%s+%dc" % (idx, len(kw))
            self.text.tag_add("hit", idx, end)
            if first is None:
                first = idx
            count += 1
            start = end
        if not count:
            self.lbl_found.configure(text="未找到", fg=CLR_DANGER)
            return
        self.lbl_found.configure(text="找到 %d 处" % count, fg=CLR_MUTED)
        # 从当前视口往下找第一处，找不到就回到第一处
        top = self.text.index("@0,0")
        target = self.text.search(kw, top, stopindex="end", nocase=True) or first
        self.text.see(target)

    def _copy_all(self):
        txt = "\n\n".join("%s\n%s" % (t, b) for t, b in self.sections)
        try:
            self.clipboard_clear()
            self.clipboard_append(txt)
            self.lbl_tip.configure(text="已复制全部说明（%d 字）" % len(txt))
        except Exception as e:
            self.lbl_tip.configure(text="复制失败：%s" % e)
