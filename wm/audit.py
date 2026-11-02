# -*- coding: utf-8 -*-
"""局域网访问日志（合规用）。

依据《中华人民共和国网络安全法》第二十三条（2025 年修正、2026-01-01 施行；修正前为第二十一条）：
网络运营者应当采取监测、记录网络运行状态、
网络安全事件的技术措施，并按照规定留存相关的网络日志不少于六个月。

落地取舍：
  · 只记「谁、什么时候、访问了哪个接口、结果如何」，**不记业务内容**
    （不写型号、买家、金额、照片），避免日志自己变成第二份个人信息库；
  · 不记 /ping 心跳：电脑客户端每 4 秒轮询一次，记下来一天几万行，
    180 天就是几百 MB，且没有任何审计价值；
  · 按天分文件 access-YYYYMMDD.log，方便按时间范围取证与到期清理；
  · KEEP_DAYS 天之前的文件在写入时自动删除（启动首写、跨天首写各清一次）；
  · 任何异常都吞掉 —— 记日志失败绝不能让局域网服务报错。
"""

import datetime
import os
import threading

KEEP_DAYS = 180          # 法规下限 6 个月
MAX_BYTES = 8 * 1024 * 1024   # 单日文件上限，超了就停写当天（防异常刷屏撑爆磁盘）


class AccessLog(object):
    """一天一个文件，行格式：时间 \t IP \t 方法 \t 路径 \t 状态码"""

    def __init__(self, root):
        self.root = root
        self._lock = threading.Lock()
        self._day = ""
        self._purged_day = ""

    # ---------------------------------------------------------- 内部
    def _path(self, day):
        return os.path.join(self.root, "access-%s.log" % day)

    def _ensure_dir(self):
        if not os.path.isdir(self.root):
            os.makedirs(self.root, exist_ok=True)

    def _purge(self, today):
        """删掉超过保留期的日志文件（一天最多跑一次）。"""
        if self._purged_day == today:
            return
        self._purged_day = today
        limit = datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)
        try:
            for name in os.listdir(self.root):
                if not (name.startswith("access-") and name.endswith(".log")):
                    continue
                day = name[7:-4]
                try:
                    d = datetime.datetime.strptime(day, "%Y%m%d").date()
                except ValueError:
                    continue
                if d < limit:
                    try:
                        os.remove(os.path.join(self.root, name))
                    except OSError:
                        pass
        except OSError:
            pass

    # ---------------------------------------------------------- 对外
    def write(self, ip, method, path, status):
        if not path or path.startswith("/ping"):
            return          # 心跳不记，见模块说明
        try:
            now = datetime.datetime.now()
            day = now.strftime("%Y%m%d")
            with self._lock:
                self._ensure_dir()
                self._purge(day)
                f = self._path(day)
                try:
                    if os.path.getsize(f) >= MAX_BYTES:
                        return
                except OSError:
                    pass
                line = "%s\t%s\t%s\t%s\t%s\n" % (
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    str(ip or "-")[:64], str(method or "-")[:8],
                    str(path or "-")[:200], str(status or "-")[:8])
                with open(f, "a", encoding="utf-8") as fh:
                    fh.write(line)
        except Exception:
            pass        # 记日志失败不影响业务

    def tail(self, lines=300):
        """最近若干行（给界面看），跨天时把昨天的接在前面。"""
        out = []
        try:
            names = sorted(n for n in os.listdir(self.root)
                           if n.startswith("access-") and n.endswith(".log"))
        except OSError:
            return ""
        for name in reversed(names):
            try:
                with open(os.path.join(self.root, name), encoding="utf-8",
                          errors="replace") as fh:
                    rows = fh.readlines()[-lines:]
            except OSError:
                continue
            out = rows + out
            if len(out) >= lines:
                break
        return "".join(out[-lines:])

    def files(self):
        try:
            return sorted(n for n in os.listdir(self.root)
                          if n.startswith("access-") and n.endswith(".log"))
        except OSError:
            return []

    def clear(self):
        """清空日志（用户主动操作；正常情况应保留到期）。"""
        for name in self.files():
            try:
                os.remove(os.path.join(self.root, name))
            except OSError:
                pass

    def size(self):
        total = 0
        for name in self.files():
            try:
                total += os.path.getsize(os.path.join(self.root, name))
            except OSError:
                pass
        return total
