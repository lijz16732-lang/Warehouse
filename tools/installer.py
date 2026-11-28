# -*- coding: utf-8 -*-
"""仓管家电脑端安装向导（v1.45.8）。

独立打包成「仓管家安装程序.exe」：内嵌主程序 exe 与图标，无外部依赖。
界面：品牌蓝横幅 + 分步向导（欢迎 → 安装位置 → 安装进度 → 完成）。

安装动作：
1. 复制主程序到安装目录（覆盖旧版；data 数据目录原样保留）
2. 桌面 + 开始菜单快捷方式（图标）
3. 写 HKCU 卸载信息（控制面板「应用和功能」可见）
4. 安装目录内置 unins.bat 一键卸载

打包：.venv310/Scripts/python.exe build_installer.py
（PyInstaller --add-data dist 主 exe + assets/app.ico）
"""
import base64
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

try:
    from PyInstaller.__main__ import get_temp_dir  # noqa: F401
except Exception:
    pass

# ---------------- 资源定位（源码运行 / PyInstaller 打包两种形态） ----------------
def _res_dir():
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return base
    return ROOT


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_NAME = "仓管家-仓库管理系统"
EXE_NAME = APP_NAME + ".exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CangGuanJia"
BRAND = "#3584E4"
BRAND_DK = "#2A67C4"
BG = "#F3F6FB"
TEXT = "#1F2A3D"
MUTED = "#6B7A90"
OK = "#2FA35C"

DEFAULT_DIR = "D:\\仓库管理工具"


def bundled_exe():
    """内嵌主程序 exe 的路径（打包形态在 _MEIPASS/app 下；源码形态取 dist）。"""
    cand = [os.path.join(_res_dir(), "app", EXE_NAME),
            os.path.join(ROOT, "dist", EXE_NAME)]
    for p in cand:
        if os.path.exists(p):
            return p
    return None


def read_version():
    try:
        src = open(os.path.join(ROOT, "wm", "constants.py"),
                   encoding="utf-8").read()
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
        return m.group(1) if m else "1.45.8"
    except Exception:
        return "1.45.8"


# ============================================================ 安装动作（可单测）
def make_shortcuts(target_dir, version):
    """桌面 + 开始菜单快捷方式（PowerShell EncodedCommand，免编码乱码）。"""
    exe = os.path.join(target_dir, EXE_NAME)
    ico = os.path.join(target_dir, "app.ico")
    desktop = os.path.join(os.environ.get("USERPROFILE", ""),
                           "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.join(os.environ.get("PUBLIC", desktop), "Desktop")
    smenu = os.path.join(os.environ.get("APPDATA", ""),
                         "Microsoft", "Windows", "Start Menu", "Programs")
    targets = [os.path.join(desktop, "仓管家.lnk"),
               os.path.join(smenu, "仓管家.lnk")]
    for lnk in targets:
        ps = ("$ws = New-Object -ComObject WScript.Shell;"
              "$s = $ws.CreateShortcut('%s');"
              "$s.TargetPath = '%s';"
              "$s.WorkingDirectory = '%s';"
              "%s"
              "$s.Save()" % (lnk, exe, target_dir,
                             ("$s.IconLocation = '%s,0';" % ico)
                             if os.path.exists(ico) else ""))
        encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", encoded],
                       capture_output=True, timeout=30)


def write_uninstall_bat(target_dir):
    bat = os.path.join(target_dir, "unins.bat")
    exe = os.path.join(target_dir, EXE_NAME)
    script = (
        "@echo off\r\n"
        f"taskkill /f /im \"{EXE_NAME}\" >nul 2>&1\r\n"
        f"del /f /q \"{exe}\"\r\n"
        f"del /f /q \"%~f0\\..\\app.ico\" >nul 2>&1\r\n"
        f"reg delete \"HKCU\\{UNINSTALL_KEY}\" /f >nul 2>&1\r\n"
        "start /b cmd /c \"ping -n 3 127.0.0.1 >nul & rd /s /q \"%~dp0\"\"\r\n"
    )
    with open(bat, "w", encoding="gbk", newline="") as f:
        f.write(script)
    return bat


def write_uninstall_reg(target_dir, version):
    """HKCU 卸载信息：控制面板「应用和功能」可见。失败不阻断安装。"""
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        bat = os.path.join(target_dir, "unins.bat")
        vals = [
            ("DisplayName", "仓管家 仓库管理系统"),
            ("DisplayVersion", version),
            ("DisplayIcon", os.path.join(target_dir, "app.ico")),
            ("UninstallString", "cmd /c \"%s\"" % bat),
            ("Publisher", "仓管家"),
            ("NoModify", 1), ("NoRepair", 1),
        ]
        for name, val in vals:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(val))
        key.Close()
        return True
    except Exception:
        return False


def copy_exe(src, dst, progress=None):
    """分块复制（进度条有过程感）。"""
    total = os.path.getsize(src)
    done = 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            chunk = fi.read(1 << 20)
            if not chunk:
                break
            fo.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)


# ============================================================ 界面
class Wizard(tk.Tk):
    W, H = 660, 460

    def __init__(self):
        super().__init__()
        self.title("仓管家 安装向导")
        self.resizable(False, False)
        try:
            self.iconbitmap(os.path.join(_res_dir(), "assets", "app.ico"))
        except Exception:
            pass
        self.center()
        self._build()

        self.step = 0
        self._show(0)

    def center(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.W) // 2
        y = (self.winfo_screenheight() - self.H) // 2 - 30
        self.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))

    # ---- 结构：横幅 / 内容 / 底部按钮 ----
    def _build(self):
        self.banner = tk.Canvas(self, width=self.W, height=86,
                                highlightthickness=0, bd=0)
        self.banner.pack(fill="x")
        self._paint_banner("欢迎使用 仓管家")
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)
        foot = tk.Frame(self, bg="#EAEFF7")
        foot.pack(fill="x", side="bottom")
        self.btn_cancel = tk.Button(foot, text="取消", width=9, bd=0,
                                    bg="#EAEFF7", fg=MUTED,
                                    activebackground="#E0E7F2",
                                    font=("Microsoft YaHei", 9),
                                    command=self.destroy)
        self.btn_back = tk.Button(foot, text="< 上一步", width=10, bd=0,
                                  bg="#EAEFF7", fg=MUTED,
                                  activebackground="#E0E7F2",
                                  font=("Microsoft YaHei", 9),
                                  state="disabled", command=lambda: self._show(0))
        self.btn_next = tk.Button(foot, text="下一步 >", width=10, bd=0,
                                  bg=BRAND, fg="white",
                                  activebackground=BRAND_DK,
                                  activeforeground="white",
                                  font=("Microsoft YaHei", 9, "bold"),
                                  command=self._next)
        self.btn_cancel.pack(side="right", padx=10, pady=10)
        self.btn_next.pack(side="right", padx=(0, 4), pady=10)
        self.btn_back.pack(side="right")

        self.ver = read_version()
        self.var_dir = tk.StringVar(value=DEFAULT_DIR)
        self.var_run = tk.BooleanVar(value=True)

    def _paint_banner(self, title):
        c = self.banner
        w = int(c["width"])
        for x in range(0, w, 4):        # 手绘横向渐变（Tk 无原生渐变）
            ratio = x / max(w - 1, 1)
            r1, g1, b1 = 0x1D, 0x4F, 0xA0
            r2, g2, b2 = 0x35, 0x84, 0xE4
            col = "#%02x%02x%02x" % (
                int(r1 + (r2 - r1) * ratio),
                int(g1 + (g2 - g1) * ratio),
                int(b1 + (b2 - b1) * ratio))
            c.create_rectangle(x, 0, x + 4, 86, outline="", fill=col)
        c.create_text(24, 34, anchor="w", text="仓管家", fill="white",
                      font=("Microsoft YaHei", 17, "bold"))
        c.create_text(24, 62, anchor="w", text=title, fill="#DCE9FF",
                      font=("Microsoft YaHei", 10))

    # ---- 三个页面 ----
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _card(self):
        card = tk.Frame(self.body, bg="white")
        card.pack(fill="both", expand=True, padx=44, pady=(24, 12))
        return card

    def _page_welcome(self):
        self._paint_banner("欢迎使用 仓管家")
        card = self._card()
        tk.Label(card, text="📦", bg="white", font=("Segoe UI Emoji", 40)
                 ).place(x=40, y=24)
        tk.Label(card, text="即将安装 仓管家 仓库管理系统",
                 bg="white", fg=TEXT, font=("Microsoft YaHei", 13, "bold")
                 ).place(x=120, y=40)
        tk.Label(card, text="版本 %s" % self.ver, bg="white", fg=MUTED,
                 font=("Microsoft YaHei", 9)).place(x=122, y=72)
        msg = ("安装内容：主程序、桌面与开始菜单快捷方式\n\n"
               "数据说明：升级安装不会动已有的 data 数据目录\n\n"
               "卸载方式：控制面板「应用和功能」→ 仓管家\n\n"
               "继续安装即表示您已阅读并同意《用户协议》与《隐私政策》。")
        tk.Label(card, text=msg, bg="white", fg=MUTED, justify="left",
                 font=("Microsoft YaHei", 10)).place(x=120, y=120)
        self.btn_next.configure(text="下一步 >", state="normal")
        self.btn_back.configure(state="disabled")

    def _page_dir(self):
        self._paint_banner("选择安装位置")
        card = self._card()
        tk.Label(card, text="安装位置", bg="white", fg=TEXT,
                 font=("Microsoft YaHei", 10, "bold")).place(x=30, y=24)
        ent = tk.Entry(card, textvariable=self.var_dir, bg="#F6F8FC",
                       relief="flat", font=("Microsoft YaHei", 10))
        ent.place(x=30, y=54, width=380, height=30)
        tk.Button(card, text="浏览…", bd=0, bg=BRAND, fg="white",
                  activebackground=BRAND_DK, activeforeground="white",
                  font=("Microsoft YaHei", 9),
                  command=self._browse).place(x=424, y=54, width=76, height=30)
        tk.Label(card, text="建议保持默认位置；升级安装请选择原来的安装目录，"
                            "数据会原样保留。", bg="white", fg=MUTED,
                 font=("Microsoft YaHei", 9), justify="left"
                 ).place(x=30, y=100)
        old = self._detect_old()
        if old:
            tk.Label(card, text="检测到已安装：%s（将升级，数据保留）" % old,
                     bg="#EDF7EE", fg=OK, font=("Microsoft YaHei", 9)
                     ).place(x=30, y=132)
        self.btn_next.configure(text="安装", state="normal")
        self.btn_back.configure(state="normal")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.var_dir.get() or "D:\\",
                                    title="选择安装位置")
        if d:
            self.var_dir.set(os.path.normpath(d))

    def _detect_old(self):
        p = os.path.join(self.var_dir.get(), EXE_NAME)
        return p if os.path.exists(p) else None

    # ---- 安装过程 ----
    def _install(self):
        target = os.path.normpath(self.var_dir.get() or DEFAULT_DIR)
        src = bundled_exe()
        if not src:
            from tkinter import messagebox
            messagebox.showerror("安装向导", "安装包损坏：找不到内嵌的主程序。")
            return
        self._paint_banner("正在安装…")
        self._clear()
        card = self._card()
        self.lbl_step = tk.Label(card, text="准备安装…", bg="white", fg=TEXT,
                                 font=("Microsoft YaHei", 10))
        self.lbl_step.place(x=30, y=26)
        self.bar = ttk.Progressbar(card, maximum=100, length=460)
        self.bar.place(x=30, y=60)
        self.lbl_pct = tk.Label(card, text="0%", bg="white", fg=MUTED,
                                font=("Microsoft YaHei", 9))
        self.lbl_pct.place(x=30, y=92)
        self.btn_next.configure(state="disabled")
        self.btn_back.configure(state="disabled")

        def work():
            def prog(done, total):
                pct = int(done * 100 / max(total, 1))
                self.after(0, lambda p=pct: self._set_progress(p, "复制主程序…"))
            os.makedirs(target, exist_ok=True)
            copy_exe(src, os.path.join(target, EXE_NAME), prog)
            self.after(0, lambda: self._set_progress(70, "复制图标…"))
            try:
                ico_src = os.path.join(_res_dir(), "assets", "app.ico")
                if os.path.exists(ico_src):
                    shutil.copyfile(ico_src, os.path.join(target, "app.ico"))
            except Exception:
                pass
            self.after(0, lambda: self._set_progress(80, "创建快捷方式…"))
            try:
                make_shortcuts(target, self.ver)
            except Exception:
                pass
            self.after(0, lambda: self._set_progress(90, "写卸载信息…"))
            try:
                write_uninstall_bat(target)
                write_uninstall_reg(target, self.ver)
            except Exception:
                pass
            self.after(0, lambda: self._set_progress(100, "完成"))
            self.after(400, lambda: self._show_done(target))

        threading.Thread(target=work, daemon=True).start()

    def _set_progress(self, pct, text):
        try:
            self.bar["value"] = pct
            self.lbl_step.configure(text=text)
            self.lbl_pct.configure(text="%d%%" % pct)
        except Exception:
            pass

    def _show_done(self, target):
        self._paint_banner("安装完成")
        self._clear()
        card = self._card()
        tk.Label(card, text="✔", bg="white", fg=OK,
                 font=("Microsoft YaHei", 40)).place(x=30, y=18)
        tk.Label(card, text="安装完成", bg="white", fg=TEXT,
                 font=("Microsoft YaHei", 14, "bold")).place(x=92, y=32)
        tk.Label(card, text="安装位置：%s" % target, bg="white", fg=MUTED,
                 font=("Microsoft YaHei", 9)).place(x=92, y=66)
        dot = tk.Label(card, bg="white", cursor="hand2")
        self._dot_state = {"on": True}

        def refresh():
            dot.configure(fg=TEXT if self._dot_state["on"] else MUTED,
                          text=("● " if self._dot_state["on"] else "○ ")
                          + " 安装后立即运行仓管家")

        def toggle(_e=None):
            self._dot_state["on"] = not self._dot_state["on"]
            refresh()
        dot.place(x=92, y=104)
        dot.bind("<Button-1>", toggle)
        refresh()
        self.btn_next.configure(text="完成", state="normal",
                                command=self._finish)

    def _finish(self):
        target = os.path.normpath(self.var_dir.get() or DEFAULT_DIR)
        if self._dot_state.get("on"):
            try:
                os.startfile(os.path.join(target, EXE_NAME))
            except Exception:
                pass
        self.destroy()

    # ---- 步骤切换 ----
    def _show(self, idx):
        self.step = idx
        self._clear()
        [self._page_welcome, self._page_dir][idx]()
        if idx == 0:
            self.btn_next.configure(command=self._next)

    def _next(self):
        if self.step == 0:
            self._show(1)
        elif self.step == 1:
            self._install()


def main():
    Wizard().mainloop()


if __name__ == "__main__":
    main()
