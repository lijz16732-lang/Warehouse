# -*- coding: utf-8 -*-
"""SQLite 数据层：仓库记录的持久化与查询。"""

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from .constants import (FIELD_KEYS, FIELD_TYPE, LISTED_TEXT, MODEL_BLANK,
                        MULTI_SEP, OUT_TYPE_SALE, is_blank_model, norm_model)

SQL_COLS = ", ".join('"%s"' % k for k in FIELD_KEYS)
# 读取时额外带上 sold_out / cost / deleted_at（均不属于可编辑字段）
#   sold_out   「已售完」标记
#   cost       采购成本单价（移动加权平均，由采购登记维护）
#   deleted_at 软删除时间（非空 = 在回收站里）
SQL_READ = "id, %s, sold_out, cost, deleted_at" % SQL_COLS

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    {cols},
    sold_out   INTEGER DEFAULT 0,
    cost       REAL DEFAULT 0,
    deleted_at TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS purchases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER,
    code          TEXT,
    brand         TEXT,
    category      TEXT,
    model         TEXT,
    shelf         TEXT,
    qty           INTEGER DEFAULT 0,
    unit_cost     REAL DEFAULT 0,
    total         REAL DEFAULT 0,
    supplier      TEXT,
    purchase_date TEXT,
    remark        TEXT,
    created_at    TEXT
);
CREATE TABLE IF NOT EXISTS sales (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER,
    code       TEXT,
    brand      TEXT,
    category   TEXT,
    model      TEXT,
    shelf      TEXT,
    qty        INTEGER DEFAULT 0,
    price      REAL DEFAULT 0,
    total      REAL DEFAULT 0,
    cost       REAL DEFAULT 0,
    buyer      TEXT,
    address    TEXT,
    sale_date  TEXT,
    remark     TEXT,
    out_type   TEXT DEFAULT '销售',
    paid       INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
-- 数据版本号：任何写操作都会 +1，局域网客户端据此判断「主机数据变了没有」
CREATE TABLE IF NOT EXISTS sync_state (
    k TEXT PRIMARY KEY,
    v INTEGER DEFAULT 0
);
INSERT OR IGNORE INTO sync_state (k, v) VALUES ('rev', 1);
CREATE INDEX IF NOT EXISTS idx_items_code  ON items("code");
CREATE INDEX IF NOT EXISTS idx_items_brand ON items("brand");
CREATE INDEX IF NOT EXISTS idx_items_cat   ON items("category");
CREATE INDEX IF NOT EXISTS idx_items_shelf ON items("shelf");
CREATE INDEX IF NOT EXISTS idx_sales_date  ON sales("sale_date");
CREATE INDEX IF NOT EXISTS idx_sales_code  ON sales("code");
CREATE INDEX IF NOT EXISTS idx_purch_date  ON purchases("purchase_date");
CREATE INDEX IF NOT EXISTS idx_purch_item  ON purchases("item_id");
-- 手机端独立数据（App 同步上来的记录，不进主库存；电脑端「手机数据」页查看管理）
CREATE TABLE IF NOT EXISTS phone_items (
    lid         INTEGER PRIMARY KEY,
    {cols},
    sold_out    INTEGER DEFAULT 0,
    transferred INTEGER DEFAULT 0,
    pc_id       INTEGER DEFAULT 0,
    synced_at   TEXT,
    created_at  TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS phone_sales (
    lid       INTEGER PRIMARY KEY,
    item_lid  INTEGER DEFAULT 0,
    code      TEXT,
    brand     TEXT,
    category  TEXT,
    model     TEXT,
    qty       INTEGER DEFAULT 0,
    price     REAL DEFAULT 0,
    total     REAL DEFAULT 0,
    buyer     TEXT,
    sale_date TEXT,
    out_type  TEXT DEFAULT '出售',
    remark    TEXT,
    synced_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_phone_sales_date ON phone_sales("sale_date");
-- 客户档案（v1.32.0）：与出售记录的 buyer 按姓名对应，累计数据实时汇总
CREATE TABLE IF NOT EXISTS customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL DEFAULT '',
    phone      TEXT DEFAULT '',
    address    TEXT DEFAULT '',
    level      TEXT DEFAULT '',
    note       TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers("name");
-- 销售退货（v1.32.0）：一条出售可部分退，退回库存可选；金额/成本按退货当日快照
CREATE TABLE IF NOT EXISTS returns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id     INTEGER,
    item_id     INTEGER,
    code        TEXT,
    brand       TEXT,
    category    TEXT,
    model       TEXT,
    shelf       TEXT,
    qty         INTEGER DEFAULT 0,
    price       REAL DEFAULT 0,
    refund      REAL DEFAULT 0,
    cost        REAL DEFAULT 0,
    restock     INTEGER DEFAULT 1,
    buyer       TEXT,
    return_date TEXT,
    remark      TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_returns_date ON returns("return_date");
CREATE INDEX IF NOT EXISTS idx_returns_sale ON returns("sale_id");
-- 盘点单（v1.32.0）：头 + 明细快照，提交时按实盘数写回库存
CREATE TABLE IF NOT EXISTS stocktakes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    no         TEXT DEFAULT '',
    name       TEXT DEFAULT '',
    status     TEXT DEFAULT 'draft',
    created_at TEXT,
    done_at    TEXT,
    note       TEXT
);
CREATE TABLE IF NOT EXISTS stocktake_items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    st_id    INTEGER,
    item_id  INTEGER,
    code     TEXT,
    brand    TEXT,
    model    TEXT,
    shelf    TEXT,
    book_qty INTEGER DEFAULT 0,
    real_qty INTEGER DEFAULT 0,
    note     TEXT
);
CREATE INDEX IF NOT EXISTS idx_st_items ON stocktake_items("st_id");
-- 制作流程（v1.42.0）：A发起制作 → B制作标签 → C贴标签 → D质检 → E入库，
-- 节点名称可自定义（meta["workflow_stages"]），流转全程留痕 workflow_logs
CREATE TABLE IF NOT EXISTS workflows (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    no         TEXT DEFAULT '',
    title      TEXT DEFAULT '',
    kind       TEXT DEFAULT '',
    target     TEXT DEFAULT '',
    stage      INTEGER DEFAULT 0,
    status     TEXT DEFAULT 'active',
    created_at TEXT,
    updated_at TEXT,
    done_at    TEXT,
    note       TEXT,
    extra      TEXT
);
CREATE INDEX IF NOT EXISTS idx_wf_status ON workflows("status");
CREATE TABLE IF NOT EXISTS workflow_logs (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    wf_id  INTEGER,
    stage  INTEGER DEFAULT 0,
    action TEXT DEFAULT '',
    by     TEXT DEFAULT '',
    at     TEXT,
    note   TEXT
);
CREATE INDEX IF NOT EXISTS idx_wf_logs ON workflow_logs("wf_id");
""".format(cols=",\n    ".join(
    '"%s" %s DEFAULT %s' % (
        k,
        {"text": "TEXT", "money": "REAL", "int": "INTEGER", "bool": "INTEGER"}[FIELD_TYPE[k]],
        "0" if FIELD_TYPE[k] in ("money", "int", "bool") else "''",
    ) for k in FIELD_KEYS
))

# 写操作 → 版本号自增（由数据库触发器保证，任何写入途径都会触发）
SYNC_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_sync_items_i AFTER INSERT ON items
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_items_u AFTER UPDATE ON items
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_items_d AFTER DELETE ON items
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_sales_i AFTER INSERT ON sales
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_sales_u AFTER UPDATE ON sales
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_sales_d AFTER DELETE ON sales
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_pur_i AFTER INSERT ON purchases
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_pur_d AFTER DELETE ON purchases
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_meta_i AFTER INSERT ON meta
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_meta_u AFTER UPDATE ON meta
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_meta_d AFTER DELETE ON meta
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_phitem_i AFTER INSERT ON phone_items
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_phitem_u AFTER UPDATE ON phone_items
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_phitem_d AFTER DELETE ON phone_items
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_phsale_i AFTER INSERT ON phone_sales
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_phsale_u AFTER UPDATE ON phone_sales
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_phsale_d AFTER DELETE ON phone_sales
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_wf_i AFTER INSERT ON workflows
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_wf_u AFTER UPDATE ON workflows
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_wf_d AFTER DELETE ON workflows
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_wflog_i AFTER INSERT ON workflow_logs
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_wflog_u AFTER UPDATE ON workflow_logs
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
CREATE TRIGGER IF NOT EXISTS trg_sync_wflog_d AFTER DELETE ON workflow_logs
BEGIN UPDATE sync_state SET v = v + 1 WHERE k = 'rev'; END;
"""

CODE_SEQ_KEY = "code_seq"

# --------------------------------------------------------------------------
# 照片（v1.25.0）：每条记录可挂多张照片，文件存磁盘、不动数据库结构。
# 目录：data/photos/<库文件名>/<kind>/<编号>/，kind = item 主库存 / phone 手机区
# 列表即目录内容；照片增删后写 meta 触发 rev 自增，客户端轮询即感知刷新。
# --------------------------------------------------------------------------
PHOTO_MAX = 10                     # 每条记录最多张数
PHOTO_KINDS = ("item", "phone", "wf")   # wf = 制作单（入库拍照留证）
PHOTO_EXTS = (".jpg", ".jpeg", ".png")


def _safe_code(code):
    """编号 → 安全目录名（保留中英文数字-_.，其余替换为下划线）。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t ]+', "_", str(code or "").strip())
    return s[:80] or "_"


def _shrink_image(data, max_side=1600, quality=85):
    """图片字节压缩：最长边超限等比缩小并转 JPEG。PIL 不可用或解析失败
    时原样返回 (data, None)；成功返回 (jpg_bytes, ".jpg")。"""
    try:
        import io as _io
        from PIL import Image
        im = Image.open(_io.BytesIO(data))
        im.load()
        if im.mode != "RGB":
            im = im.convert("RGB")
        if max(im.size) > max_side:
            r = float(max_side) / max(im.size)
            im = im.resize((max(1, int(im.width * r)),
                            max(1, int(im.height * r))), Image.LANCZOS)
        out = _io.BytesIO()
        im.save(out, "JPEG", quality=quality)
        return out.getvalue(), ".jpg"
    except Exception:
        return data, None


def _content_key(rec):
    """记录内容指纹（不含编号、不含上架状态）：用于「无型号但内容相同」的去重判断。

    无效型号（空、/、无型号…）统一按空串处理，保证「/」和空白彼此视为相同。
    数字字段（价格/数量）做归一化，保证 0 与 0.00、1 与 "1" 视为相同。
    上架状态（listed）不参与指纹：它是导入后最常被人工修改的字段，
    重复导入同一文件时不应因上架状态改过而误判为新数据。
    """
    out = []
    for f in FIELD_KEYS:
        if f in ("code", "listed"):
            continue
        v = rec.get(f)
        t = FIELD_TYPE.get(f)
        if t == "money":
            s = str(v if v is not None else "").strip().replace("¥", "").replace(",", "")
            try:
                out.append("%.2f" % float(s) if s else "0.00")
            except (TypeError, ValueError):
                out.append("0.00")
        elif t == "int":
            s = str(v if v is not None else "").strip()
            try:
                out.append(str(int(float(s))) if s else "0")
            except (TypeError, ValueError):
                out.append("0")
        elif t == "bool":
            out.append("1" if str(v or "").strip() in ("1", "已上架", "True", "true", "是") else "0")
        else:
            s = str(v if v is not None else "").strip()
            if f == "model" and is_blank_model(s):
                s = ""
            out.append(s)
    return tuple(out)


def dedupe_records(recs, match_field="model"):
    """文件内去重：相同型号只保留最后一条；无型号但内容完全相同的也只留一条。

    返回 (去重后的列表, 去重掉的条数)。
    """
    kept, pos_model, pos_content = [], {}, {}
    for rec in recs:
        k = norm_model(rec.get(match_field))
        if k and k not in MODEL_BLANK:
            if k in pos_model:
                kept[pos_model[k]] = rec      # 后来的覆盖先前的
            else:
                pos_model[k] = len(kept)
                kept.append(rec)
            continue
        ck = _content_key(rec)
        if ck in pos_content:
            kept[pos_content[ck]] = rec
        else:
            pos_content[ck] = len(kept)
            kept.append(rec)
    return kept, len(recs) - len(kept)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def blank_record():
    rec = {}
    for k in FIELD_KEYS:
        t = FIELD_TYPE[k]
        rec[k] = 0 if t in ("money", "int") else (0 if t == "bool" else "")
    return rec


class Store(object):
    """线程安全的记录仓库。UI 线程与后台导入线程共用同一连接。"""

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._src_l = threading.local()     # 操作日志来源（每线程独立栈）
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.executescript(SYNC_TRIGGERS)
        self.conn.commit()
        self._migrate()

    def _migrate(self):
        """老库升级：补齐后续版本新增的列（不改动已有数据）。"""
        with self._lock:
            try:
                cols = {r["name"] for r in
                        self.conn.execute("PRAGMA table_info(items)").fetchall()}
                adds = [("sold_out", 'ALTER TABLE items ADD COLUMN "sold_out" INTEGER DEFAULT 0'),
                        ("cost", 'ALTER TABLE items ADD COLUMN "cost" REAL DEFAULT 0'),
                        ("deleted_at", 'ALTER TABLE items ADD COLUMN "deleted_at" TEXT')]
                changed = False
                for name, sql in adds:
                    if name not in cols:
                        self.conn.execute(sql)
                        changed = True
                # 出库记录：老库补 out_type 列（历史行一律视为「销售」）
                scols = {r["name"] for r in
                         self.conn.execute("PRAGMA table_info(sales)").fetchall()}
                if "out_type" not in scols:
                    self.conn.execute(
                        "ALTER TABLE sales ADD COLUMN \"out_type\" TEXT DEFAULT '%s'"
                        % OUT_TYPE_SALE)
                    changed = True
                # 收货地址：老库补 address 列（历史行留空）
                if "address" not in scols:
                    self.conn.execute(
                        "ALTER TABLE sales ADD COLUMN \"address\" TEXT")
                    changed = True
                # v1.39.0 来源列：这笔出库是谁操作的（主机/电脑·名/手机(ip)）
                if "src" not in scols:
                    self.conn.execute(
                        "ALTER TABLE sales ADD COLUMN \"src\" TEXT DEFAULT ''")
                    changed = True
                # v1.40.0 收款状态：1=已收款（默认，老数据视为已收），0=挂账
                if "paid" not in scols:
                    self.conn.execute(
                        "ALTER TABLE sales ADD COLUMN \"paid\" INTEGER DEFAULT 1")
                    changed = True
                # v1.42.4 制作单附加字段（类型专属，如原型号/标签种类），JSON
                wcols = {r["name"] for r in
                         self.conn.execute("PRAGMA table_info(workflows)").fetchall()}
                if "extra" not in wcols:
                    self.conn.execute(
                        "ALTER TABLE workflows ADD COLUMN \"extra\" TEXT")
                    changed = True
                # v1.42.10 加急标记
                if "urgent" not in wcols:
                    self.conn.execute(
                        "ALTER TABLE workflows ADD COLUMN"
                        " \"urgent\" INTEGER DEFAULT 0")
                    changed = True
                # v1.43.0 目标工位（同节点多人的情况下，推给具体哪个工位）
                if "station" not in wcols:
                    self.conn.execute(
                        "ALTER TABLE workflows ADD COLUMN"
                        " \"station\" TEXT DEFAULT ''")
                    changed = True
                # v1.24.0 操作日志（独立表，不参与同步触发器）
                self.conn.execute(
                    "CREATE TABLE IF NOT EXISTS oplog ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, src TEXT,"
                    " act TEXT, code TEXT, detail TEXT)")
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_oplog_ts ON oplog(\"ts\")")
                self._oplog_prune()
                changed = True
                if changed:
                    self.conn.commit()
            except Exception:
                pass

    # ---------------------------------------------------------------- 基础
    def close(self):
        with self._lock:
            try:
                self.conn.commit()
                self.conn.close()
            except Exception:
                pass

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    # ---------------------------------------------------------- 操作日志
    @property
    def _srcs(self):
        lst = getattr(self._src_l, "s", None)
        if lst is None:
            lst = []
            self._src_l.s = lst
        return lst

    @property
    def log_src(self):
        """当前线程的操作来源（as_source 栈顶；主机界面默认「主机」）。"""
        lst = self._srcs
        return lst[-1] if lst else "主机"

    @contextmanager
    def as_source(self, src):
        """来源上下文：with store.as_source("手机(192.168.1.5)"): ..."""
        self._srcs.append(str(src))
        try:
            yield
        finally:
            self._srcs.pop()

    def log_op(self, act, code="", detail=""):
        """记一条操作日志（失败静默，绝不能影响业务）。"""
        try:
            self._execute(
                "INSERT INTO oplog (ts, src, act, code, detail) VALUES (?,?,?,?,?)",
                (time.time(), self.log_src, str(act)[:20], str(code)[:80],
                 str(detail)[:400]))
        except Exception:
            pass

    def _codes_of(self, ids):
        """按 id 查编号（删除前先取，删完就查不到了）。"""
        ids = [int(i) for i in ids]
        if not ids:
            return []
        ph = ", ".join(["?"] * len(ids))
        try:
            with self._lock:
                rows = self.conn.execute(
                    "SELECT id, code FROM items WHERE id IN (%s)" % ph,
                    tuple(ids)).fetchall()
            d = {r["id"]: (r["code"] or "#%d" % r["id"]) for r in rows}
            return [d.get(int(i), "#%d" % int(i)) for i in ids]
        except Exception:
            return []

    @staticmethod
    def _sv(v, n=24):
        return "" if v is None else str(v)[:n]

    def _oplog_prune(self):
        """清掉超过保留期的日志（meta.oplog_days，默认 180 天）。"""
        try:
            days = int(float(self.get_meta("oplog_days", 180) or 180))
        except (TypeError, ValueError):
            days = 180
        self._execute("DELETE FROM oplog WHERE ts < ?",
                      (time.time() - days * 86400,))

    def oplog_list(self, src="", kw="", days=0, limit=2000):
        sql = "SELECT * FROM oplog WHERE 1 = 1"
        args = []
        if src:
            sql += " AND src = ?"
            args.append(src)
        if kw:
            sql += " AND (code LIKE ? OR detail LIKE ? OR act LIKE ?)"
            like = "%" + kw + "%"
            args += [like, like, like]
        if days:
            sql += " AND ts >= ?"
            args.append(time.time() - int(days) * 86400)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self.conn.execute(sql, tuple(args)).fetchall()
        return [dict(r) for r in rows]

    def oplog_srcs(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT DISTINCT src FROM oplog ORDER BY src").fetchall()
        return [r["src"] for r in rows]

    def oplog_clear(self):
        self._execute("DELETE FROM oplog")

    # ---------------------------------------------------------- 元数据 / 设置
    def get_meta(self, key, default=None):
        with self._lock:
            row = self.conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
        if row is None or row["v"] is None or str(row["v"]) == "":
            return default
        return row["v"]

    def get_num(self, key, default=0.0):
        try:
            return float(self.get_meta(key, default))
        except (TypeError, ValueError):
            return float(default)

    def set_meta(self, key, value):
        self._execute("INSERT INTO meta (k, v) VALUES (?, ?) "
                      "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, str(value)))

    # ---------------------------------------------------------- 列题自定义
    # 存 meta["col_titles"]（JSON）：{字段名: 自定义标题}，电脑端表头与手机端
    # 表格共用这一份设置 —— 手机上改了，电脑端表头跟着变，反之亦然。
    COL_TITLES_KEY = "col_titles"
    COL_TITLE_MAX = 12             # 标题最长 12 字（表格列宽有限）

    def col_titles(self):
        """返回 {字段名: 自定义标题}（只含有效自定义；无自定义返回空 dict）。"""
        import json as _json
        try:
            raw = _json.loads(self.get_meta(self.COL_TITLES_KEY, "") or "{}")
        except (ValueError, TypeError):
            raw = {}
        if not isinstance(raw, dict):
            return {}
        out = {}
        for k, v in raw.items():
            t = str(v).strip()
            if k in FIELD_KEYS and t and len(t) <= self.COL_TITLE_MAX:
                out[k] = t
        return out

    def set_col_titles(self, mapping):
        """保存列题自定义：值为空/超长 → 恢复该列默认标题；非法字段名忽略。"""
        import json as _json
        cur = self.col_titles()
        for k, v in (mapping or {}).items():
            if k not in FIELD_KEYS:
                continue
            t = str(v if v is not None else "").strip()
            if t and len(t) <= self.COL_TITLE_MAX:
                cur[k] = t
            else:
                cur.pop(k, None)
        self.set_meta(self.COL_TITLES_KEY,
                      _json.dumps(cur, ensure_ascii=False) if cur else "")
        return cur

    # ---------------------------------------------------------------- 手机数据
    # 手机 App 同步上来的记录单独存 phone_items / phone_sales，绝不写主库存；
    # 电脑端「手机数据」页查看管理，可手动「转入库存」。

    def _m_kw_match(self, r, kw):
        if not kw:
            return True
        kw = kw.lower()
        return any(kw in str(r.get(f) or "").lower()
                   for f in ("code", "brand", "category", "model", "shelf", "condition"))

    def _m_item_upsert_sql(self):
        sets = ", ".join('"%s"=?' % k for k in FIELD_KEYS)
        cols = SQL_COLS
        ph = ", ".join(["?"] * (len(FIELD_KEYS) + 1))     # 字段 + lid
        return sets, cols, ph

    def m_upsert_item(self, rec):
        """手机商品按本地 id（lid）覆盖保存：存在则更新，不存在则新增。"""
        lid = int(rec.get("lid") or 0)
        if lid <= 0:
            raise ValueError("lid 无效")
        vals = self._vals(rec)
        ts = now_str()
        so = 1 if rec.get("sold_out") in (1, True, "1", "是") else 0
        sets, cols, ph = self._m_item_upsert_sql()
        with self._lock:
            row = self.conn.execute(
                "SELECT lid, created_at FROM phone_items WHERE lid = ?", (lid,)).fetchone()
            if row:
                self.conn.execute(
                    'UPDATE phone_items SET {sets}, sold_out=?, synced_at=?, updated_at=? '
                    'WHERE lid=?'.format(sets=sets),
                    tuple(vals) + (so, ts, ts, lid))
            else:
                self.conn.execute(
                    'INSERT INTO phone_items (lid, {cols}, sold_out, synced_at, '
                    'created_at, updated_at) VALUES ({ph}, ?, ?, ?, ?)'.format(
                        cols=cols, ph=ph),
                    tuple([lid] + vals) + (so, ts, ts, ts))
        self.conn.commit()
        self.log_op("手机上传商品", rec.get("code") or rec.get("model") or "",
                    "App 同步%s" % ("更新" if row else "新增"))
        return lid

    def m_upsert_sale(self, rec):
        """手机出售记录按本地 id（lid）覆盖保存（幂等，重复同步不产生重复行）。"""
        lid = int(rec.get("lid") or 0)
        if lid <= 0:
            raise ValueError("lid 无效")
        ts = now_str()

        def _i(k):
            try:
                return int(float(rec.get(k) or 0))
            except (TypeError, ValueError):
                return 0

        def _f(k):
            try:
                return float(rec.get(k) or 0)
            except (TypeError, ValueError):
                return 0.0

        def _s(k, n=120):
            return str(rec.get(k) or "").strip()[:n]
        args = (lid, _i("item_lid"), _s("code", 40), _s("brand", 40), _s("category", 40),
                _s("model", 120), max(1, _i("qty")), _f("price"), _f("total"),
                _s("buyer", 40), _s("sale_date", 20), _s("out_type", 20) or "出售",
                _s("remark", 200), ts)
        with self._lock:
            self.conn.execute(
                "INSERT INTO phone_sales (lid, item_lid, code, brand, category, model, "
                "qty, price, total, buyer, sale_date, out_type, remark, synced_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(lid) DO UPDATE SET item_lid=excluded.item_lid, "
                "code=excluded.code, brand=excluded.brand, category=excluded.category, "
                "model=excluded.model, qty=excluded.qty, price=excluded.price, "
                "total=excluded.total, buyer=excluded.buyer, sale_date=excluded.sale_date, "
                "out_type=excluded.out_type, remark=excluded.remark, "
                "synced_at=excluded.synced_at", args)
        self.conn.commit()
        self.log_op("手机上传出售", _s("code", 40) or _s("model", 40),
                    "%d 件 × %.2f 元" % (max(1, _i("qty")), _f("price")))
        return lid

    def m_items(self, kw=""):
        """手机商品列表（含 transferred/pc_id/synced_at），按同步顺序。"""
        with self._lock:
            rows = self.conn.execute(
                'SELECT * FROM phone_items ORDER BY lid ASC').fetchall()
        out = [dict(r) for r in rows]
        return [r for r in out if self._m_kw_match(r, kw)]

    def m_sales(self, kw=""):
        """手机出售记录列表，按日期倒序（新的在前）。"""
        with self._lock:
            rows = self.conn.execute(
                'SELECT * FROM phone_sales ORDER BY sale_date DESC, lid DESC').fetchall()
        out = [dict(r) for r in rows]
        return [r for r in out if self._m_kw_match(r, kw)]

    # 行颜色标记：meta["phone_colors"]（JSON）{"item:<lid>"/"sale:<lid>": "#RRGGBB"}
    PHONE_COLORS_KEY = "phone_colors"

    def m_colors(self):
        """手机数据行颜色标记 {key: "#RRGGBB"}。key = "item:<lid>" 或 "sale:<lid>"。"""
        import json as _json
        try:
            raw = _json.loads(
                self.get_meta(self.PHONE_COLORS_KEY, "") or "{}")
        except (ValueError, TypeError):
            raw = {}
        if not isinstance(raw, dict):
            return {}
        out = {}
        for k, v in raw.items():
            s = str(v).strip()
            if (":" in str(k) and s.startswith("#")
                    and len(s) in (7, 9)):
                out[str(k)] = s
        return out

    def m_set_color(self, key, color):
        """设置/取消一条手机记录的行颜色（color 为 None/空 → 取消）。"""
        import json as _json
        cur = self.m_colors()
        s = str(color or "").strip()
        if s.startswith("#") and len(s) in (7, 9):
            cur[str(key)] = s
        else:
            cur.pop(str(key), None)
        self.set_meta(self.PHONE_COLORS_KEY,
                      _json.dumps(cur, ensure_ascii=False) if cur else "")
        return cur

    def m_del_item(self, lid):
        with self._lock:
            row = self.conn.execute("SELECT code, model FROM phone_items WHERE lid = ?",
                                    (int(lid),)).fetchone()
            self.conn.execute("DELETE FROM phone_items WHERE lid = ?", (int(lid),))
        self.conn.commit()
        self.m_set_color("item:%d" % int(lid), None)     # 颜色标记一并清理
        d = dict(row) if row else {}
        if d.get("code"):                    # 手机区商品照片一并清理
            self.photos_wipe("phone", d["code"])
        self.log_op("手机删除商品", d.get("code") or d.get("model") or "", "手机区商品")

    def m_del_sale(self, lid):
        with self._lock:
            row = self.conn.execute("SELECT code FROM phone_sales WHERE lid = ?",
                                    (int(lid),)).fetchone()
            self.conn.execute("DELETE FROM phone_sales WHERE lid = ?", (int(lid),))
        self.conn.commit()
        self.m_set_color("sale:%d" % int(lid), None)     # 颜色标记一并清理
        self.log_op("手机删除出售", dict(row)["code"] if row else "", "手机区出售记录")

    def m_clear(self):
        """清空全部手机数据（不影响主库存）。"""
        with self._lock:
            n = self.conn.execute("SELECT COUNT(*) FROM phone_items").fetchone()[0]
            self.conn.execute("DELETE FROM phone_items")
            self.conn.execute("DELETE FROM phone_sales")
        self.conn.commit()
        self.set_meta(self.PHONE_COLORS_KEY, "")         # 颜色标记一并清理
        self.photos_wipe_kind("phone")       # 手机区照片一并清理
        self.log_op("清空手机数据", "", "%d 条手机区记录" % n)

    def m_transfer(self, lids):
        """把手机商品转入主库存：生成电脑编号（接着最大号排）、插入 items，
        并在手机数据里标记 transferred=1。返回 (转入条数, 新编号列表)。
        已转入的自动跳过；原记录保留在手机数据页（标「已转入」），不删不重复转入。"""
        lids = [int(x) for x in (lids or [])]
        n, codes = 0, []
        for lid in lids:
            with self._lock:
                row = self.conn.execute(
                    "SELECT * FROM phone_items WHERE lid = ?", (lid,)).fetchone()
            if row is None or row["transferred"]:
                continue
            rec = {k: row[k] for k in FIELD_KEYS}
            rec["sold_out"] = row["sold_out"]
            old_code = row["code"]
            code = self.generate_codes(1)[0]
            rec["code"] = code
            rid = self.insert(rec)
            if row["sold_out"]:
                with self._lock:
                    self.conn.execute("UPDATE items SET sold_out=1 WHERE id=?", (rid,))
                self.conn.commit()
            if old_code:                     # 照片跟随转入主库存
                self.photos_copy("phone", old_code, "item", code)
            with self._lock:
                self.conn.execute(
                    "UPDATE phone_items SET transferred=1, pc_id=?, updated_at=? "
                    "WHERE lid=?", (rid, now_str(), lid))
            self.conn.commit()
            n += 1
            codes.append(code)
        if n:
            self.log_op("转入库存", "、".join(codes[:6]) + ("…" if len(codes) > 6 else ""),
                        "手机数据转入 %d 条" % n)
        return n, codes

    # ---------------------------------------------------------------- 查询
    def all_records(self):
        # 默认升序：最早入库/编号最小的在最前（列表默认升序展示）
        with self._lock:
            cur = self.conn.execute(
                'SELECT {read} FROM items WHERE deleted_at IS NULL ORDER BY id ASC'
                .format(read=SQL_READ))
            return [dict(r) for r in cur.fetchall()]

    def count(self):
        with self._lock:
            return self.conn.execute(
                "SELECT COUNT(*) FROM items WHERE deleted_at IS NULL").fetchone()[0]

    def revision(self):
        """数据版本号：任何写操作都会让这个数 +1（局域网客户端用它判断要不要刷新）。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT v FROM sync_state WHERE k = 'rev'").fetchone()
            return int(row["v"]) if row else 0

    def distinct(self, field):
        if field not in FIELD_KEYS:
            return []
        with self._lock:
            cur = self.conn.execute(
                'SELECT DISTINCT "{f}" v FROM items WHERE deleted_at IS NULL '
                'AND "{f}" IS NOT NULL AND "{f}" != \'\' '
                'ORDER BY "{f}"'.format(f=field))
            vals = [r["v"] for r in cur.fetchall()]
        if field == "shelf":
            # 多货架记录（「6排A-3 / 7排A-1」）拆成单个货架位，去重保序
            out, seen = [], set()
            for v in vals:
                for part in str(v).split(MULTI_SEP):
                    part = part.strip()
                    if part and part not in seen:
                        seen.add(part)
                        out.append(part)
            return out
        return vals

    def find_by_code(self, code):
        with self._lock:
            cur = self.conn.execute(
                'SELECT id FROM items WHERE "code" = ? AND deleted_at IS NULL LIMIT 1', (code,))
            row = cur.fetchone()
            return row["id"] if row else None

    # 编号规则（App 启动时按 settings 注入，默认 WL-00001）
    code_prefix = "WL"
    code_digits = 5

    def set_code_rule(self, prefix=None, digits=None):
        """设置自动编号的前缀与位数（只影响之后新生成的编号）。"""
        p = str(prefix if prefix is not None else self.code_prefix or "WL")
        p = re.sub(r"[^0-9A-Za-z_-]", "", p.strip())[:8] or "WL"
        try:
            d = int(digits)
        except (TypeError, ValueError):
            d = int(self.code_digits or 5)
        self.code_prefix = p.upper()
        self.code_digits = max(3, min(8, d))
        return self.code_prefix, self.code_digits

    def code_sample(self):
        """示例编号（给提示文案用，如 WL-00001 / SP-0001）。"""
        try:
            return "%s-%s" % (self.code_prefix, "0" * (self.code_digits - 1) + "1")
        except Exception:
            return "WL-00001"

    def generate_codes(self, n):
        """生成 n 个不与现有数据冲突的编号（默认 WL-00001 起顺序递增）。

        规则（编号跟着数据走）：
          · 库中还有数据  → 接着已有编号的最大尾号往下排（追加/合并导入不会重号）
          · 库已被清空    → 计数器归零，从 1 号重新开始
          · 前缀/位数可在设置里改（如 SP-0001），改后只影响新编号，旧编号原样保留
        """
        prefix = str(self.code_prefix or "WL")
        digits = int(self.code_digits or 5)
        pat = re.compile(r"^%s-(\d+)$" % re.escape(prefix), re.IGNORECASE)
        with self._lock:
            cur = self.conn.execute('SELECT "code" FROM items')
            existing = {str(r["code"]).strip() for r in cur.fetchall() if r["code"] is not None}
            seq_row = cur.execute("SELECT v FROM meta WHERE k = ?", (CODE_SEQ_KEY,)).fetchone()
        mx = 0
        # 只有库中仍有编号时才接续计数器；库被清空后忽略历史计数，重新从 1 开始
        if existing and seq_row and seq_row["v"]:
            try:
                mx = int(seq_row["v"])
            except (TypeError, ValueError):
                mx = 0
        for c in existing:
            m = pat.match(c)
            if m:
                mx = max(mx, int(m.group(1)))
                continue
            # 兼容其它前缀的既有编号（如 SKU-1018），保证编号接着往下排
            tail = re.search(r"(\d+)\s*$", c)
            if tail:
                mx = max(mx, int(tail.group(1)))
        out = []
        i = mx + 1
        last = mx
        while len(out) < n:
            code = "%s-%0*d" % (prefix, digits, i)
            if code not in existing:
                out.append(code)
                existing.add(code)
                last = i
            i += 1
        with self._lock:
            self.conn.execute("INSERT INTO meta (k, v) VALUES (?, ?) "
                              "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                              (CODE_SEQ_KEY, str(last)))
            self.conn.commit()
        return out

    # ---------------------------------------------------------------- 写入
    def _vals(self, rec):
        out = []
        for k in FIELD_KEYS:
            t = FIELD_TYPE[k]
            v = rec.get(k, "" if t == "text" else 0)
            if t == "money":
                try:
                    v = float(v or 0)
                except (TypeError, ValueError):
                    v = 0.0
            elif t == "int":
                try:
                    v = int(float(v or 0))
                except (TypeError, ValueError):
                    v = 0
            elif t == "bool":
                v = 1 if v in (1, True, "1", "是") else 0
            else:
                v = "" if v is None else str(v)
            out.append(v)
        return out

    def insert(self, rec):
        ts = now_str()
        sql = ('INSERT INTO items ({cols}, created_at, updated_at) VALUES ({ph})'
               .format(cols=SQL_COLS, ph=", ".join(["?"] * (len(FIELD_KEYS) + 2))))
        cur = self._execute(sql, tuple(self._vals(rec)) + (ts, ts))
        self.log_op("新增", rec.get("code") or "")
        return cur.lastrowid

    def insert_many(self, recs, progress=None):
        ts = now_str()
        sql = ('INSERT INTO items ({cols}, created_at, updated_at) VALUES ({ph})'
               .format(cols=SQL_COLS, ph=", ".join(["?"] * (len(FIELD_KEYS) + 2))))
        n = 0
        with self._lock:
            cur = self.conn.cursor()
            batch = []
            for r in recs:
                batch.append(tuple(self._vals(r)) + (ts, ts))
                if len(batch) >= 500:
                    cur.executemany(sql, batch)
                    n += len(batch)
                    batch = []
                    if progress:
                        progress(n)
            if batch:
                cur.executemany(sql, batch)
                n += len(batch)
            self.conn.commit()
        self.log_op("导入", "", "新增 %d 条" % n)
        return n

    def update(self, rid, rec):
        sets = ", ".join('"{k}" = ?'.format(k=k) for k in FIELD_KEYS)
        # 数量被改回 > 0 时自动清除「已售完」标记
        sql = ('UPDATE items SET {sets}, "sold_out" = CASE WHEN ? > 0 THEN 0 ELSE "sold_out" END, '
               'updated_at = ? WHERE id = ?'.format(sets=sets))
        try:
            qleft = int(float(rec.get("qty") or 0))
        except (TypeError, ValueError):
            qleft = 0
        with self._lock:
            old = self.conn.execute("SELECT * FROM items WHERE id = ?", (rid,)).fetchone()
        oldd = dict(old) if old else {}
        self._execute(sql, tuple(self._vals(rec)) + (qleft, now_str(), rid))
        if oldd:
            diffs = ["%s: %s → %s" % (k, self._sv(oldd.get(k)), self._sv(rec.get(k)))
                     for k in FIELD_KEYS
                     if str(oldd.get(k) if oldd.get(k) is not None else "") !=
                     str(rec.get(k) if rec.get(k) is not None else "")]
            self.log_op("修改", oldd.get("code") or "",
                        "；".join(diffs) if diffs else "无字段变化")

    def update_field(self, rid, field, value):
        if field not in FIELD_KEYS:
            return
        with self._lock:
            old = self.conn.execute("SELECT code, \"%s\" v FROM items WHERE id = ?"
                                    % field, (rid,)).fetchone()
        oldcode = (dict(old)["code"] if old else "")
        oldv = (dict(old)["v"] if old else None)
        rec = blank_record()
        rec[field] = value
        if field == "qty":
            try:
                qleft = int(float(value or 0))
            except (TypeError, ValueError):
                qleft = 0
            self._execute('UPDATE items SET "qty" = ?, "sold_out" = '
                          'CASE WHEN ? > 0 THEN 0 ELSE "sold_out" END, updated_at = ? '
                          'WHERE id = ?', (self._vals(rec)[FIELD_KEYS.index(field)],
                                           qleft, now_str(), rid))
            self.log_op("修改", oldcode, "%s: %s → %s" % (field, self._sv(oldv),
                                                         self._sv(value)))
            return
        v = self._vals(rec)[FIELD_KEYS.index(field)]
        self._execute('UPDATE items SET "{f}" = ?, updated_at = ? WHERE id = ?'
                      .format(f=field), (v, now_str(), rid))
        self.log_op("修改", oldcode, "%s: %s → %s" % (field, self._sv(oldv),
                                                     self._sv(value)))

    def batch_update(self, ids, updates):
        """批量修改若干字段（只改传入的字段）。数量改回 >0 时自动清除「已售完」。"""
        ids = list(ids)
        if not ids or not updates:
            return 0
        sets, vals = [], []
        for k, v in updates.items():
            if k not in FIELD_KEYS:
                continue
            rec = blank_record()
            rec[k] = v
            sets.append('"%s" = ?' % k)
            vals.append(self._vals(rec)[FIELD_KEYS.index(k)])
        if not sets:
            return 0
        if "qty" in updates:
            try:
                qleft = int(float(updates.get("qty") or 0))
            except (TypeError, ValueError):
                qleft = 0
            sets.append('"sold_out" = CASE WHEN ? > 0 THEN 0 ELSE "sold_out" END')
            vals.append(qleft)
        sets.append('"updated_at" = ?')
        vals.append(now_str())
        ph = ", ".join(["?"] * len(ids))
        codes = self._codes_of(ids)
        cur = self._execute(
            'UPDATE items SET %s WHERE id IN (%s) AND deleted_at IS NULL'
            % (", ".join(sets), ph), tuple(vals) + tuple(ids))
        self.log_op("批量修改", "、".join(codes[:6]) + ("…" if len(codes) > 6 else ""),
                    "%d 条，%s" % (cur.rowcount,
                                   "；".join("%s → %s" % (k, self._sv(v, 40))
                                             for k, v in updates.items()
                                             if k in FIELD_KEYS)))
        return cur.rowcount

    def set_listed(self, ids, listed):
        ids = list(ids)
        if not ids:
            return 0
        ph = ", ".join(["?"] * len(ids))
        cur = self._execute('UPDATE items SET "listed" = ?, updated_at = ? WHERE id IN ({ph})'
                            .format(ph=ph), (1 if listed else 0, now_str()) + tuple(ids))
        self.log_op("上架" if listed else "下架", "", "%d 条" % cur.rowcount)
        return cur.rowcount

    def delete_ids(self, ids, soft=True):
        """删除记录。默认软删除（进回收站，可恢复）；soft=False 时物理删除。"""
        ids = list(ids)
        if not ids:
            return 0
        ph = ", ".join(["?"] * len(ids))
        ts = now_str()
        codes = self._codes_of(ids)
        if soft:
            cur = self._execute(
                'UPDATE items SET "deleted_at" = ?, "updated_at" = ? '
                'WHERE id IN ({ph}) AND deleted_at IS NULL'.format(ph=ph),
                (ts, ts) + tuple(ids))
            self.log_op("删除", "、".join(codes[:6]) + ("…" if len(codes) > 6 else ""),
                        "移入回收站 %d 条" % cur.rowcount)
        else:
            cur = self._execute(
                "DELETE FROM items WHERE id IN ({ph}) AND deleted_at IS NOT NULL".format(ph=ph),
                tuple(ids))
            for c in codes:                      # 物理删除 → 照片一并清理
                self.photos_wipe("item", c)
            self.log_op("彻底删除", "、".join(codes[:6]) + ("…" if len(codes) > 6 else ""),
                        "%d 条" % cur.rowcount)
        return cur.rowcount

    # ---------------------------------------------------------------- 回收站
    def list_deleted(self):
        """回收站里的记录（按删除时间倒序）。"""
        with self._lock:
            cur = self.conn.execute(
                'SELECT {read} FROM items WHERE deleted_at IS NOT NULL '
                'ORDER BY deleted_at DESC, id DESC'.format(read=SQL_READ))
            return [dict(r) for r in cur.fetchall()]

    def deleted_count(self):
        with self._lock:
            return self.conn.execute(
                "SELECT COUNT(*) FROM items WHERE deleted_at IS NOT NULL").fetchone()[0]

    def restore_ids(self, ids):
        """从回收站恢复记录（回到库存列表）。"""
        ids = list(ids)
        if not ids:
            return 0
        ph = ", ".join(["?"] * len(ids))
        codes = self._codes_of(ids)
        cur = self._execute(
            'UPDATE items SET "deleted_at" = NULL, "updated_at" = ? '
            'WHERE id IN ({ph}) AND deleted_at IS NOT NULL'.format(ph=ph),
            (now_str(),) + tuple(ids))
        self.log_op("恢复", "、".join(codes[:6]) + ("…" if len(codes) > 6 else ""),
                    "从回收站恢复 %d 条" % cur.rowcount)
        return cur.rowcount

    def purge_ids(self, ids):
        """彻底删除（仅限回收站里的记录，不可恢复）。"""
        ids = list(ids)
        if not ids:
            return 0
        ph = ", ".join(["?"] * len(ids))
        codes = self._codes_of(ids)
        cur = self._execute(
            "DELETE FROM items WHERE id IN ({ph}) AND deleted_at IS NOT NULL".format(ph=ph),
            tuple(ids))
        for c in codes:                          # 照片一并清理
            self.photos_wipe("item", c)
        self.log_op("彻底删除", "、".join(codes[:6]) + ("…" if len(codes) > 6 else ""),
                    "%d 条（回收站）" % cur.rowcount)
        return cur.rowcount

    def purge_trash_older(self, days):
        """回收站自动清理：删除 deleted_at 早于 days 天前的记录（days<=0 表示永久保留）。

        返回实际清理条数。照片一并清理，并写一条操作日志。
        """
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 0
        if days <= 0:
            return 0
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            rows = self.conn.execute(
                'SELECT id, code FROM items WHERE deleted_at IS NOT NULL '
                'AND deleted_at < ?', (cutoff,)).fetchall()
            if not rows:
                return 0
            ph = ", ".join(["?"] * len(rows))
            ids = [r["id"] for r in rows]
            self.conn.execute(
                "DELETE FROM items WHERE id IN ({ph})".format(ph=ph), ids)
            self.conn.commit()
        for r in rows:
            if r["code"]:
                try:
                    self.photos_wipe("item", r["code"])
                except Exception:
                    pass
        self.log_op("自动清理", "", "回收站中超过 %d 天的 %d 条记录" % (days, len(rows)))
        return len(rows)

    def purge_all_deleted(self):
        codes = [r["code"] for r in
                 self.conn.execute('SELECT code FROM items WHERE deleted_at IS NOT NULL')
                 if r["code"]]
        cur = self._execute("DELETE FROM items WHERE deleted_at IS NOT NULL")
        for c in codes:                          # 照片一并清理
            self.photos_wipe("item", c)
        self.log_op("清空回收站", "", "%d 条" % cur.rowcount)
        return cur.rowcount

    def reset_code_seq(self):
        """清除编号计数器，让下一次导入从 WL-00001 重新开始。"""
        self._execute("DELETE FROM meta WHERE k = ?", (CODE_SEQ_KEY,))
        self.log_op("重置编号", "", "编号计数器归零，下次从 1 开始")

    # ---------------------------------------------------------------- 照片
    def photos_dir(self, kind, code):
        """某条记录的照片目录（按库文件名隔离，多仓库互不干扰）。"""
        stem = os.path.splitext(os.path.basename(self.path))[0]
        return os.path.join(os.path.dirname(os.path.abspath(self.path)),
                            "photos", stem, kind, _safe_code(code))

    def photos_list(self, kind, code):
        """某条记录的照片文件名列表（按文件名排序，即添加顺序）。"""
        if kind not in PHOTO_KINDS:
            return []
        d = self.photos_dir(kind, code)
        try:
            return sorted(
                f for f in os.listdir(d)
                if f.lower().endswith(PHOTO_EXTS)
                and os.path.isfile(os.path.join(d, f)))
        except OSError:
            return []

    def photo_codes(self, kind):
        """该类别下所有存有照片的编号集合（扫一遍照片目录，轻量）。
        供表格渲染 📷 指示列，避免逐条 photos_list。"""
        if kind not in PHOTO_KINDS:
            return set()
        stem = os.path.splitext(os.path.basename(self.path))[0]
        root = os.path.join(os.path.dirname(os.path.abspath(self.path)),
                            "photos", stem, kind)
        out = set()
        try:
            with os.scandir(root) as it:
                for e in it:
                    if not e.is_dir():
                        continue
                    try:
                        with os.scandir(e.path) as sub:
                            for f in sub:
                                if (f.is_file()
                                        and f.name.lower().endswith(PHOTO_EXTS)):
                                    out.add(e.name)
                                    break
                    except OSError:
                        pass
        except OSError:
            pass
        return out

    def photo_path(self, kind, code, name):
        """照片绝对路径（做 basename 防路径穿越；不存在返回 None）。"""
        name = os.path.basename(str(name or ""))
        if (kind not in PHOTO_KINDS or not name
                or not name.lower().endswith(PHOTO_EXTS)):
            return None
        p = os.path.join(self.photos_dir(kind, code), name)
        return p if os.path.isfile(p) else None

    def photo_add(self, kind, code, data, orig_name=""):
        """存一张照片（自动压缩），返回文件名；超过上限抛 ValueError。
        data 可为原始字节或 base64 字符串（局域网/手机接口传图用）。
        同一内容（md5 相同）重复添加只保留一份。"""
        if isinstance(data, str):
            try:
                data = base64.b64decode(data)
            except Exception:
                raise ValueError("照片数据不是有效的 base64")
        if kind not in PHOTO_KINDS:
            raise ValueError("未知的照片类型")
        if not data:
            raise ValueError("空照片")
        cur = self.photos_list(kind, code)
        if len(cur) >= PHOTO_MAX:
            raise ValueError("每条记录最多 %d 张照片" % PHOTO_MAX)
        jpg, ext = _shrink_image(data)
        if ext is None:                      # PIL 不可用 → 按原始扩展名保存
            ext = os.path.splitext(orig_name or "")[1].lower()
            if ext not in PHOTO_EXTS:
                ext = ".jpg"
        name = hashlib.md5(jpg).hexdigest()[:12] + ext
        d = self.photos_dir(kind, code)
        os.makedirs(d, exist_ok=True)
        if name not in cur:
            with open(os.path.join(d, name), "wb") as f:
                f.write(jpg)
            self._photo_rev()
            self.log_op("添加照片", str(code), name)
        return name

    def photo_del(self, kind, code, name):
        """删一张照片。返回是否删除了文件。"""
        p = self.photo_path(kind, code, name)
        if p:
            try:
                os.remove(p)
            except OSError:
                return False
            self._photo_rev()
            self.log_op("删除照片", str(code), name)
            return True
        return False

    def photo_data(self, kind, code, name):
        """读一张照片，返回 base64 字符串（不存在返回 None）。
        局域网客户端 / 手机端取图统一走这里（JSON 通道友好）。"""
        p = self.photo_path(kind, code, name)
        if not p:
            return None
        try:
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        except OSError:
            return None

    def photos_wipe(self, kind, code):
        """清掉某条记录的全部照片（删记录时级联调用）。"""
        shutil.rmtree(self.photos_dir(kind, code), ignore_errors=True)

    def photos_wipe_kind(self, kind):
        """清掉某类全部照片（清空数据 / 清空手机数据时级联调用）。"""
        if kind in PHOTO_KINDS:
            stem = os.path.splitext(os.path.basename(self.path))[0]
            shutil.rmtree(os.path.join(os.path.dirname(os.path.abspath(self.path)),
                                       "photos", stem, kind), ignore_errors=True)

    def photos_copy(self, kind_src, code_src, kind_dst, code_dst):
        """照片整体迁移（手机商品转入主库存时用）。返回迁移张数。"""
        names = self.photos_list(kind_src, code_src)
        if not names:
            return 0
        os.makedirs(self.photos_dir(kind_dst, code_dst), exist_ok=True)
        n = 0
        for f in names:
            try:
                shutil.copy2(os.path.join(self.photos_dir(kind_src, code_src), f),
                             os.path.join(self.photos_dir(kind_dst, code_dst), f))
                n += 1
            except OSError:
                pass
        return n

    def _photo_rev(self):
        """照片变化后 bump 数据版本号（meta 写入由触发器自增 rev）。"""
        try:
            self.set_meta("photos_rev", now_str())
        except Exception:
            pass

    # ---------------------------------------------------------------- 出售
    def add_sale(self, item_id, qty, price, buyer="", sale_date="", remark="",
                 out_type=OUT_TYPE_SALE, address="", paid=True):
        """登记一笔出库：扣减库存数量，扣到 0 时标记「已售完」（记录保留）。

        out_type 为「销售」时按卖出处理（计销售额/成本/利润/买家）；
        其它类型（报废/损耗/退货/借出/赠送/调拨/其他）只扣库存，金额记 0。
        address 为收货地址，只对「销售」有效（非销售出库留空）。

        返回 (ok, msg)。
        """
        out_type = (str(out_type or "").strip() or OUT_TYPE_SALE)
        is_sale = (out_type == OUT_TYPE_SALE)
        try:
            qty = int(round(float(qty or 0)))
        except (TypeError, ValueError):
            return False, "出库数量不正确"
        if qty <= 0:
            return False, "出库数量必须大于 0"
        with self._lock:
            row = self.conn.execute('SELECT {read} FROM items WHERE id = ?'.format(read=SQL_READ),
                                    (item_id,)).fetchone()
            if row is None:
                return False, "记录不存在（可能已被删除）"
            rec = dict(row)
            stock = int(rec.get("qty") or 0)
            if qty > stock:
                return False, "出库数量 %d 超过当前库存 %d" % (qty, stock)
            try:
                price = float(price or 0)
            except (TypeError, ValueError):
                price = 0.0
            if not is_sale:
                price = 0.0                 # 非销售出库不计金额
            now = now_str()
            left = stock - qty
            date = (sale_date or "").strip() or now[:10]
            # 成本：优先用采购登记得到的成本单价；没登记过采购则退回原价格估算
            unit_cost = float(rec.get("cost") or 0)
            if unit_cost <= 0:
                unit_cost = float(rec.get("price") or 0)
            self.conn.execute(
                "INSERT INTO sales (item_id, code, brand, category, model, shelf, qty,"
                " price, total, cost, buyer, address, sale_date, remark, out_type,"
                " src, paid, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item_id, rec.get("code") or "", rec.get("brand") or "",
                 rec.get("category") or "", rec.get("model") or "", rec.get("shelf") or "",
                 qty, price, round(price * qty, 2), round(unit_cost, 4),
                 buyer or "" if is_sale else "",
                 (address or "").strip() if is_sale else "",
                 date, remark or "", out_type, self.log_src,
                 1 if (is_sale and paid) else (0 if is_sale else 1), now))
            self.conn.execute(
                'UPDATE items SET "qty" = ?, "sold_out" = ?, "updated_at" = ? WHERE id = ?',
                (left, 1 if left <= 0 else 0, now, item_id))
            self.conn.commit()
        code = rec.get("code") or ""
        self.log_op("出售" if is_sale else "出库", code,
                    "%d 件 × %.2f 元%s" % (qty, price,
                                           ("，买家 " + buyer) if buyer else ""))
        if is_sale:
            return True, ("已登记出售 %s：%d 件，合计 %.2f 元%s"
                          % (code, qty, price * qty,
                             "" if paid else "（挂账，未收款）"))
        return True, "已登记%s出库 %s：%d 件（不计销售额）" % (out_type, code, qty)

    def add_manual_sale(self, code="", brand="", category="", model="", shelf="",
                        qty=1, price=0.0, cost=0.0, buyer="", address="",
                        sale_date="", remark=""):
        """手动补录一条出售记录（不关联库存、不扣库存）。

        用于补录系统外的成交（老货、代发、库存已手动清掉等）：
          · 只写 sales 表，item_id 留空 → 撤销时也不会加回任何库存；
          · cost 为成本单价（选填），用于算利润；留空按 0 计；
          · 编号/品牌/型号至少填一项，否则这条记录认不出是什么货。

        返回 (ok, msg)。
        """
        code = (code or "").strip()
        brand = (brand or "").strip()
        model = (model or "").strip()
        if not (code or brand or model):
            return False, "请至少填写编号、品牌、型号中的一项"
        try:
            qty = int(round(float(qty or 0)))
        except (TypeError, ValueError):
            return False, "出售数量不正确"
        if qty <= 0:
            return False, "出售数量必须大于 0"
        try:
            price = float(price or 0)
            cost = float(cost or 0)
        except (TypeError, ValueError):
            return False, "单价请填写不小于 0 的数字"
        if price < 0 or cost < 0:
            return False, "单价不能小于 0"
        date = (sale_date or "").strip() or now_str()[:10]
        total = round(price * qty, 2)
        with self._lock:
            self.conn.execute(
                "INSERT INTO sales (item_id, code, brand, category, model, shelf, qty,"
                " price, total, cost, buyer, address, sale_date, remark, out_type,"
                " src, created_at) VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, brand, (category or "").strip(), model, (shelf or "").strip(),
                 qty, price, total, round(cost, 4), (buyer or "").strip(),
                 (address or "").strip(), date, (remark or "").strip(),
                 OUT_TYPE_SALE, self.log_src, now_str()))
            self.conn.commit()
        name = code or model or brand
        self.log_op("手动补录出售", code or model or brand,
                    "%d 件 × %.2f 元，合计 %.2f 元" % (qty, price, total))
        return True, ("已手动登记出售 %s：%d 件，合计 %.2f 元（未扣库存）"
                      % (name, qty, total))

    def list_sales(self, start="", end="", brand="", kw="", out_type="", scope=""):
        """按条件列出出库记录（按出库日期倒序）。

        scope 用于页面分流："" = 全部；"sale" = 只看销售；"out" = 只看非销售出库。
        out_type 在 scope 基础上再按具体类型过滤（空或「全部」= 不过滤）。
        """
        sql = "SELECT * FROM sales WHERE 1 = 1"
        args = []
        if start:
            sql += " AND COALESCE(sale_date, '') >= ?"
            args.append(start)
        if end:
            sql += " AND COALESCE(sale_date, '') <= ?"
            args.append(end)
        scp = (scope or "").strip().lower()
        if scp == "sale":
            sql += " AND COALESCE(out_type, ?) = ?"
            args.extend([OUT_TYPE_SALE, OUT_TYPE_SALE])
        elif scp == "out":
            sql += " AND COALESCE(out_type, ?) != ?"
            args.extend([OUT_TYPE_SALE, OUT_TYPE_SALE])
        if brand and brand != "全部":
            # 支持手动输入品牌关键词：不区分大小写包含匹配
            sql += " AND lower(brand) LIKE ?"
            args.append("%" + str(brand).strip().lower() + "%")
        otype = (out_type or "").strip()
        if otype and otype != "全部":
            sql += " AND COALESCE(out_type, ?) = ?"
            args.extend([OUT_TYPE_SALE, otype])
        kw = (kw or "").strip()
        if kw:
            like = "%" + kw + "%"
            sql += (" AND (code LIKE ? OR brand LIKE ? OR model LIKE ? OR category LIKE ?"
                    " OR buyer LIKE ? OR address LIKE ? OR remark LIKE ? OR out_type LIKE ?)")
            args.extend([like] * 8)
        sql += " ORDER BY COALESCE(sale_date, '') DESC, id DESC"
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def out_types_used(self):
        """出库记录里出现过的非销售类型（用于筛选下拉）。"""
        with self._lock:
            cur = self.conn.execute(
                "SELECT DISTINCT out_type v FROM sales "
                "WHERE COALESCE(out_type, ?) != ? AND out_type IS NOT NULL "
                "ORDER BY v", (OUT_TYPE_SALE, OUT_TYPE_SALE))
            return [r["v"] for r in cur.fetchall()]

    def sales_brands(self, out_type=""):
        """出库记录里出现过的品牌（用于筛选下拉）。"""
        sql = ('SELECT DISTINCT "brand" v FROM sales '
               'WHERE "brand" IS NOT NULL AND "brand" != \'\'')
        args = []
        otype = (out_type or "").strip()
        if otype and otype != "全部":
            sql += " AND COALESCE(out_type, ?) = ?"
            args.extend([OUT_TYPE_SALE, otype])
        sql += ' ORDER BY "brand"'
        with self._lock:
            cur = self.conn.execute(sql, args)
            return [r["v"] for r in cur.fetchall()]

    def delete_sale(self, sale_id, restore=True):
        """撤销一笔出库：删除出库记录；restore=True 时把数量加回库存并清除「已售完」。

        手动补录的记录（item_id 为空）不关联库存，撤销时只删记录。
        """
        restored = False
        with self._lock:
            row = self.conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if row is None:
                return False, "出库记录不存在"
            s = dict(row)
            if restore:
                cur = self.conn.execute('SELECT "qty" FROM items WHERE id = ?',
                                        (s.get("item_id"),)).fetchone()
                if cur is not None:
                    self.conn.execute(
                        'UPDATE items SET "qty" = ?, "sold_out" = 0, "updated_at" = ? '
                        'WHERE id = ?',
                        (int(cur["qty"] or 0) + int(s.get("qty") or 0), now_str(),
                         s.get("item_id")))
                    restored = True
            self.conn.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
            self.conn.commit()
        self.log_op("撤销出售", s.get("code") or "",
                    "%d 件%s" % (int(s.get("qty") or 0),
                                 "，数量已加回库存" if restored else "（手动补录）"))
        if restored:
            return True, "已撤销这笔出库，数量已加回库存"
        return True, "已撤销这笔出售记录（手动补录，不涉及库存）"

    def update_sale_type(self, sale_id, out_type, price=None, buyer="",
                         address="", remark=None, sale_date=""):
        """修改一笔已登记出库的类型（典型场景：出库去维修 → 修好后卖掉了）。

        · 新类型为「销售」：同时写入售价 / 买家 / 收货地址并重算总额，计入销售额与利润；
        · 新类型为其它（报废/损耗/退货/借出/赠送/调拨/其他）：金额与买家、地址清空，
          只留一条出库痕迹；
        · 数量与库存完全不动 —— 这笔出库当初已经扣过一次库存，改类型不重复扣减；
        · remark / sale_date 传 None 或空串表示保持原值。

        返回 (ok, msg)。
        """
        out_type = str(out_type or "").strip() or OUT_TYPE_SALE
        is_sale = (out_type == OUT_TYPE_SALE)
        with self._lock:
            row = self.conn.execute("SELECT * FROM sales WHERE id = ?",
                                    (sale_id,)).fetchone()
            if row is None:
                return False, "出库记录不存在（可能已被撤销）"
            s = dict(row)
            qty = int(s.get("qty") or 0)
            p = 0.0
            if is_sale:
                try:
                    p = float(price or 0)
                except (TypeError, ValueError):
                    return False, "售价请填写数字"
                if p < 0:
                    return False, "售价不能小于 0"
                sets = "out_type = ?, price = ?, total = ?, buyer = ?, address = ?"
                args = [out_type, p, round(p * qty, 2),
                        (buyer or "").strip(), (address or "").strip()]
            else:
                sets = ("out_type = ?, price = 0, total = 0,"
                        " buyer = '', address = ''")
                args = [out_type]
            if remark is not None:
                sets += ", remark = ?"
                args.append(str(remark or "").strip())
            d = (sale_date or "").strip()
            if d:
                sets += ", sale_date = ?"
                args.append(d)
            args.append(sale_id)
            self.conn.execute("UPDATE sales SET %s WHERE id = ?" % sets, args)
            self.conn.commit()
        code = s.get("code") or ""
        self.log_op("修改出售", code, "类型改为「%s」%s" % (
            out_type, ("，%.2f 元/件" % p) if is_sale else "（不计金额）"))
        if is_sale:
            return True, "已把 %s 的 %d 件出库改为「销售」（%.2f 元/件，合计 %.2f 元）" \
                         % (code, qty, p, p * qty)
        return True, "已把 %s 的出库类型改为「%s」（%d 件，不计销售额）" \
                     % (code, out_type, qty)

    def update_sale_types(self, sale_ids, out_type, remark=None):
        """批量把若干笔出库记录改成同一个类型（只用于非销售类型之间的纠正）。

        返回 (ok_count, msg)。
        """
        ids = [int(i) for i in (sale_ids or [])]
        if not ids:
            return 0, "没有选中记录"
        if str(out_type or "").strip() == OUT_TYPE_SALE:
            return 0, "改为「销售」需要填写售价与买家，请一次只选一条记录"
        n = 0
        fail = ""
        for sid in ids:
            ok, msg = self.update_sale_type(sid, out_type, remark=remark)
            if ok:
                n += 1
            elif not fail:
                fail = msg
        if n == 0:
            return 0, fail or "修改失败"
        return n, "已把 %d 笔出库记录的类型改为「%s」" % (n, out_type)

    @staticmethod
    def sales_totals(rows):
        """出库记录合计。

        金额类（销售额/成本/利润）只统计「销售」类型；非销售出库只计笔数与件数。
        返回：count/qty/amount/cost/profit（销售）+ out_count/out_qty（非销售出库）。
        """
        dep = lambda r: ((r.get("out_type") or OUT_TYPE_SALE) == OUT_TYPE_SALE)  # noqa: E731
        sale_rows = [r for r in rows if dep(r)]
        other_rows = [r for r in rows if not dep(r)]
        qty = sum(int(r.get("qty") or 0) for r in sale_rows)
        amount = sum(float(r.get("total") or 0) for r in sale_rows)
        cost = sum(float(r.get("cost") or 0) * int(r.get("qty") or 0) for r in sale_rows)
        return {"count": len(sale_rows), "qty": qty, "amount": round(amount, 2),
                "cost": round(cost, 2), "profit": round(amount - cost, 2),
                "out_count": len(other_rows),
                "out_qty": sum(int(r.get("qty") or 0) for r in other_rows),
                "all_count": len(rows)}

    def sales_stats_by_src(self, days=0):
        """按操作来源汇总销售数据（主机/局域网电脑/手机分开算）。

        days>0 只统计最近 N 天（按 sale_date）。只统计「销售」类型出库。
        返回 {"rows": [{src, count, qty, amount, cost, profit}...],
              "total": {count, qty, amount, cost, profit}}，rows 按销售额降序。
        """
        try:
            days = int(days or 0)
        except (TypeError, ValueError):
            days = 0
        sql = ("SELECT COALESCE(NULLIF(src, ''), '未知来源') AS src,"
               " COUNT(*) AS count, SUM(qty) AS qty,"
               " SUM(total) AS amount,"
               " SUM(COALESCE(cost, 0) * qty) AS cost"
               " FROM sales WHERE COALESCE(out_type, '%s') = '%s'"
               % (OUT_TYPE_SALE, OUT_TYPE_SALE))
        args = []
        if days > 0:
            sql += " AND COALESCE(sale_date, '') >= ?"
            args.append((date.today() - timedelta(days=days - 1)).isoformat())
        sql += " GROUP BY src ORDER BY amount DESC"
        try:
            with self._lock:
                rows = [dict(r) for r in
                        self.conn.execute(sql, args).fetchall()]
        except Exception:
            rows = []
        for r in rows:
            r["cost"] = round(float(r.get("cost") or 0), 2)
            r["profit"] = round(float(r.get("amount") or 0) - r["cost"], 2)
        total = {"count": sum(r["count"] for r in rows),
                 "qty": sum(r["qty"] or 0 for r in rows),
                 "amount": round(sum(r["amount"] or 0 for r in rows), 2),
                 "cost": round(sum(r["cost"] for r in rows), 2)}
        total["profit"] = round(total["amount"] - total["cost"], 2)
        return {"rows": rows, "total": total}

    @staticmethod
    def out_totals(rows):
        """非销售出库合计：笔数 / 件数 / 成本价值（按成本估算的库存减少）。        by_type 为 {类型: 件数}，用于页面上的类型分布。
        """
        qty = sum(int(r.get("qty") or 0) for r in rows)
        cost = sum(float(r.get("cost") or 0) * int(r.get("qty") or 0) for r in rows)
        by_type = {}
        for r in rows:
            t = r.get("out_type") or "其他"
            by_type[t] = by_type.get(t, 0) + int(r.get("qty") or 0)
        return {"count": len(rows), "qty": qty, "cost": round(cost, 2),
                "by_type": by_type}

    # ------------------------------------------------------------ 出售统计
    def month_sales_amount(self, month="", brand=""):
        """某月（YYYY-MM，空则本月）的销售额合计（只统计「销售」类型）。"""
        month = (month or "").strip() or datetime.now().strftime("%Y-%m")
        sql = ("SELECT COALESCE(SUM(total), 0) v, COALESCE(SUM(qty), 0) q, COUNT(*) c "
               "FROM sales WHERE SUBSTR(COALESCE(sale_date, ''), 1, 7) = ? "
               "AND COALESCE(out_type, ?) = ?")
        args = [month, OUT_TYPE_SALE, OUT_TYPE_SALE]
        if brand and brand != "全部":
            # 支持手动输入品牌关键词：不区分大小写包含匹配
            sql += " AND lower(brand) LIKE ?"
            args.append("%" + str(brand).strip().lower() + "%")
        with self._lock:
            row = self.conn.execute(sql, args).fetchone()
        return {"month": month, "amount": round(float(row["v"] or 0), 2),
                "qty": int(row["q"] or 0), "count": int(row["c"] or 0)}

    def monthly_sales(self, months=12, brand=""):
        """最近 months 个月的销售额（含没有销售的月份，值为 0）。

        返回 [("2025-11", 金额), ...]，按时间升序。
        """
        try:
            months = max(1, min(36, int(months)))
        except (TypeError, ValueError):
            months = 12
        now = datetime.now()
        y, m = now.year, now.month
        seq = []
        for i in range(months - 1, -1, -1):
            yy, mm = y, m - i
            while mm <= 0:
                yy -= 1
                mm += 12
            seq.append("%04d-%02d" % (yy, mm))
        start = seq[0] + "-00"
        sql = ("SELECT SUBSTR(COALESCE(sale_date, ''), 1, 7) k, COALESCE(SUM(total), 0) v "
               "FROM sales WHERE COALESCE(sale_date, '') >= ?"
               " AND COALESCE(out_type, ?) = ?")
        args = [start, OUT_TYPE_SALE, OUT_TYPE_SALE]
        if brand and brand != "全部":
            # 支持手动输入品牌关键词：不区分大小写包含匹配
            sql += " AND lower(brand) LIKE ?"
            args.append("%" + str(brand).strip().lower() + "%")
        sql += " GROUP BY k"
        with self._lock:
            rows = {r["k"]: float(r["v"] or 0) for r in
                    self.conn.execute(sql, args).fetchall()}
        return [(k, round(rows.get(k, 0.0), 2)) for k in seq]

    def brand_sales(self, limit=12):
        """按品牌汇总销售额（只统计「销售」），返回 [(品牌, 销售额, 利润), ...] 倒序。"""
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT COALESCE(NULLIF(TRIM(brand), ''), '（无品牌）') b,"
                " COALESCE(SUM(total), 0) amt,"
                " COALESCE(SUM(cost * qty), 0) cst"
                " FROM sales WHERE COALESCE(out_type, '%s') = '%s'"
                " GROUP BY b ORDER BY amt DESC" % (OUT_TYPE_SALE, OUT_TYPE_SALE)).fetchall()]
        out = [(r["b"], round(float(r["amt"] or 0), 2),
                round(float(r["amt"] or 0) - float(r["cst"] or 0), 2)) for r in rows]
        return out[:limit] if limit else out

    # ------------------------------------------------------------ 买家
    def buyer_names(self):
        with self._lock:
            cur = self.conn.execute(
                "SELECT DISTINCT buyer v FROM sales WHERE buyer IS NOT NULL "
                "AND TRIM(buyer) != '' AND COALESCE(out_type, '%s') = '%s' ORDER BY buyer"
                % (OUT_TYPE_SALE, OUT_TYPE_SALE))
            return [r["v"] for r in cur.fetchall()]

    def sale_addresses(self, limit=30):
        """历史收货地址（最近的在前），用于登记出售时的下拉补全。"""
        with self._lock:
            cur = self.conn.execute(
                "SELECT address v, MAX(COALESCE(sale_date, '')) d FROM sales "
                "WHERE address IS NOT NULL AND TRIM(address) != '' "
                "AND COALESCE(out_type, ?) = ? GROUP BY address "
                "ORDER BY d DESC, v", (OUT_TYPE_SALE, OUT_TYPE_SALE))
            vals = [r["v"] for r in cur.fetchall()]
        return vals[:limit] if limit else vals

    def buyer_address_map(self):
        """买家 → 最近一次用过的收货地址（选中历史买家时自动带出地址）。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT buyer, address FROM sales "
                "WHERE buyer IS NOT NULL AND TRIM(buyer) != '' "
                "AND address IS NOT NULL AND TRIM(address) != '' "
                "AND COALESCE(out_type, ?) = ? "
                "ORDER BY COALESCE(sale_date, '') ASC, id ASC",
                (OUT_TYPE_SALE, OUT_TYPE_SALE)).fetchall()
        m = {}
        for r in rows:                      # 升序遍历，最后一次覆盖前面
            m[r["buyer"]] = r["address"]
        return m

    def buyer_stats(self):
        """按买家汇总：笔数 / 件数 / 销售额 / 利润 / 最近一次购买日期（只统计「销售」）。"""
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT buyer b, COUNT(*) c, COALESCE(SUM(qty), 0) q,"
                " COALESCE(SUM(total), 0) amt, COALESCE(SUM(cost * qty), 0) cst,"
                " MAX(COALESCE(sale_date, '')) last"
                " FROM sales WHERE buyer IS NOT NULL AND TRIM(buyer) != ''"
                " AND COALESCE(out_type, '%s') = '%s'"
                " GROUP BY b ORDER BY amt DESC" % (OUT_TYPE_SALE, OUT_TYPE_SALE)).fetchall()]
        return [{"buyer": r["b"], "count": int(r["c"]), "qty": int(r["q"]),
                 "amount": round(float(r["amt"] or 0), 2),
                 "profit": round(float(r["amt"] or 0) - float(r["cst"] or 0), 2),
                 "last": r["last"] or ""} for r in rows]

    def rename_buyer(self, old, new):
        """重命名买家（改名到已有名字即等于合并）。"""
        old = (old or "").strip()
        new = (new or "").strip()
        if not old or not new or old == new:
            return 0
        cur = self._execute("UPDATE sales SET buyer = ? WHERE buyer = ?", (new, old))
        return cur.rowcount

    def clear_buyer(self, name):
        """清空某个买家标记（保留出售记录本身）。"""
        cur = self._execute("UPDATE sales SET buyer = '' WHERE buyer = ?",
                            ((name or "").strip(),))
        return cur.rowcount

    # ------------------------------------------------------------ 客户档案（v1.32.0）
    def list_customers(self, kw="", include_buyers=False):
        """客户列表 + 出售汇总。

        客户与出售记录按「姓名」对应（历史数据里 buyer 就是名字），
        所以老数据不用迁移：建个同名客户就能看到累计消费。
        """
        kw = (kw or "").strip().lower()
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT * FROM customers ORDER BY name COLLATE NOCASE").fetchall()]
            stat = {}
            for r in self.conn.execute(
                    "SELECT buyer b, COUNT(*) c, COALESCE(SUM(qty), 0) q,"
                    " COALESCE(SUM(total), 0) amt,"
                    " MAX(COALESCE(sale_date, '')) last"
                    " FROM sales WHERE TRIM(COALESCE(buyer, '')) != ''"
                    " AND COALESCE(out_type, '%s') = '%s' GROUP BY b"
                    % (OUT_TYPE_SALE, OUT_TYPE_SALE)).fetchall():
                stat[str(r["b"] or "").strip().lower()] = dict(r)
        out = []
        debt = {d["name"]: d["amount"] for d in self.sales_unpaid()["buyers"]}
        for r in rows:
            s = stat.get((r.get("name") or "").strip().lower()) or {}
            rec = {"id": int(r["id"]), "name": r.get("name") or "",
                   "phone": r.get("phone") or "", "address": r.get("address") or "",
                   "level": r.get("level") or "", "note": r.get("note") or "",
                   "count": int(s.get("c") or 0), "qty": int(s.get("q") or 0),
                   "amount": round(float(s.get("amt") or 0), 2),
                   "debt": round(float(debt.get((r.get("name") or "").strip()) or 0), 2),
                   "last": s.get("last") or ""}
            if kw and kw not in " ".join([rec["name"], rec["phone"], rec["address"],
                                          rec["note"]]).lower():
                continue
            out.append(rec)
        if include_buyers:
            # 手机端用：只买过东西、还没建档案的买家也列出来（电脑端不显示，
            # 避免把临时买家混进正式客户列表）
            have = {(r.get("name") or "").strip().lower() for r in out}
            for row in self.buyer_stats():
                name = (row.get("buyer") or "").strip()
                if not name or name.lower() in have:
                    continue
                if kw and kw not in name.lower():
                    continue
                out.append({"id": 0, "name": name, "phone": "", "address": "",
                            "level": "", "note": "（未建档案的买家）",
                            "count": int(row.get("count") or 0),
                            "qty": int(row.get("qty") or 0),
                            "amount": round(float(row.get("amount") or 0), 2),
                            "debt": round(float(debt.get(name) or 0), 2),
                            "last": row.get("last") or ""})
            out.sort(key=lambda d: -d["amount"])
        return out

    def add_customer(self, name, phone="", address="", level="", note=""):
        name = (name or "").strip()
        if not name:
            return False, "客户名称不能为空"
        with self._lock:
            dup = self.conn.execute(
                "SELECT id FROM customers WHERE LOWER(TRIM(name)) = ?",
                (name.lower(),)).fetchone()
            if dup:
                return False, "客户「%s」已存在" % name
            now = now_str()
            self.conn.execute(
                "INSERT INTO customers (name, phone, address, level, note,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (name, (phone or "").strip(), (address or "").strip(),
                 (level or "").strip(), (note or "").strip(), now, now))
            self.conn.commit()
        self.log_op("新增客户", name, (phone or "").strip())
        return True, "已新增客户：%s" % name

    def update_customer(self, cid, name=None, phone=None, address=None,
                        level=None, note=None):
        sets, args = [], []
        for col, val in (("name", name), ("phone", phone), ("address", address),
                         ("level", level), ("note", note)):
            if val is None:
                continue
            val = str(val).strip()
            if col == "name" and not val:
                return False, "客户名称不能为空"
            sets.append('"%s" = ?' % col)
            args.append(val)
        if not sets:
            return False, "没有要修改的内容"
        with self._lock:
            if name is not None:
                dup = self.conn.execute(
                    "SELECT id FROM customers WHERE LOWER(TRIM(name)) = ? AND id != ?",
                    (name.strip().lower(), int(cid))).fetchone()
                if dup:
                    return False, "客户「%s」已存在" % name.strip()
            args += [now_str(), int(cid)]
            self.conn.execute(
                "UPDATE customers SET %s, updated_at = ? WHERE id = ?"
                % ", ".join(sets), args)
            self.conn.commit()
        self.log_op("修改客户", str(name or ""), "")
        return True, "已保存"

    def delete_customer(self, cid):
        cur = self._execute("DELETE FROM customers WHERE id = ?", (int(cid),))
        return cur.rowcount

    def import_buyers(self):
        """把出售记录里出现过的买家导入客户表（同名跳过）。返回新增条数。"""
        rows = [dict(r) for r in self.conn.execute(
            "SELECT buyer b, MAX(COALESCE(sale_date, '')) last,"
            " (SELECT address FROM sales s2 WHERE s2.buyer = s.buyer"
            "  AND TRIM(COALESCE(s2.address, '')) != ''"
            "  ORDER BY s2.sale_date DESC LIMIT 1) addr"
            " FROM sales s WHERE TRIM(COALESCE(buyer, '')) != ''"
            " AND COALESCE(out_type, '%s') = '%s' GROUP BY b"
            % (OUT_TYPE_SALE, OUT_TYPE_SALE)).fetchall()]
        n = 0
        now = now_str()
        with self._lock:
            have = {str(r["n"] or "").strip().lower() for r in self.conn.execute(
                "SELECT name n FROM customers").fetchall()}
            for r in rows:
                name = str(r["b"] or "").strip()
                if not name or name.lower() in have:
                    continue
                self.conn.execute(
                    "INSERT INTO customers (name, phone, address, level, note,"
                    " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (name, "", r.get("addr") or "", "",
                     "由出售记录导入（最近成交 %s）" % (r.get("last") or ""), now, now))
                have.add(name.lower())
                n += 1
            self.conn.commit()
        if n:
            self.log_op("导入客户", "", "从出售记录导入 %d 个买家" % n)
        return n

    # ------------------------------------------------------------ 销售退货（v1.32.0）
    def returns_by_sale(self, sale_ids=None):
        """一批出售记录的已退情况：{sale_id: {"qty": 已退件数, "refund": 退款额}}。"""
        sql = ("SELECT sale_id, COALESCE(SUM(qty), 0), COALESCE(SUM(refund), 0)"
               " FROM returns")
        args = []
        if sale_ids is not None:
            ids = [int(x) for x in sale_ids if x]
            if not ids:
                return {}
            sql += " WHERE sale_id IN (%s)" % ", ".join(["?"] * len(ids))
            args = ids
        sql += " GROUP BY sale_id"
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        return {int(r[0] or 0): {"qty": int(r[1] or 0),
                                 "refund": round(float(r[2] or 0), 2)}
                for r in rows}

    def sales_unpaid(self):
        """应收（挂账）汇总：只统计 paid=0 的销售单，退款按单冲减，按买家合并。"""
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT TRIM(COALESCE(s.buyer, '')) b,"
                " COALESCE(s.total, 0) - COALESCE((SELECT SUM(r.refund)"
                "   FROM returns r WHERE r.sale_id = s.id), 0) amt"
                " FROM sales s WHERE COALESCE(s.paid, 1) = 0"
                " AND COALESCE(s.out_type, '%s') = '%s'"
                % (OUT_TYPE_SALE, OUT_TYPE_SALE)).fetchall()]
        total = 0.0
        by = {}
        for r in rows:
            amt = round(float(r.get("amt") or 0), 2)
            if amt <= 0:
                continue
            total += amt
            name = str(r.get("b") or "").strip() or "（未填买家）"
            cur = by.setdefault(name, {"name": name, "amount": 0.0, "count": 0})
            cur["amount"] = round(cur["amount"] + amt, 2)
            cur["count"] += 1
        return {"total": round(total, 2), "count": len(rows),
                "buyers": sorted(by.values(), key=lambda d: -d["amount"])}

    def settle_unpaid(self, buyer=""):
        """结清应收：把某客户（buyer 为空则全部）的挂账出售标记为已收款。

        返回结清的笔数。
        """
        sql = "UPDATE sales SET paid = 1 WHERE COALESCE(paid, 1) = 0"
        args = []
        buyer = (buyer or "").strip()
        if buyer:
            sql += " AND TRIM(COALESCE(buyer, '')) = ?"
            args.append(buyer)
        cur = self._execute(sql, tuple(args))
        if cur.rowcount:
            self.log_op("结清应收", buyer or "全部挂账",
                        "%d 笔" % cur.rowcount)
        return cur.rowcount

    def returnable_qty(self, sale_id):
        """某笔出售还能退多少件（已退的扣掉）。"""
        with self._lock:
            row = self.conn.execute("SELECT qty FROM sales WHERE id = ?",
                                    (int(sale_id),)).fetchone()
            if row is None:
                return 0
            back = self.conn.execute(
                "SELECT COALESCE(SUM(qty), 0) FROM returns WHERE sale_id = ?",
                (int(sale_id),)).fetchone()[0]
        return max(0, int(row[0] or 0) - int(back or 0))

    def add_return(self, sale_id, qty=0, refund=None, restock=True,                   return_date="", remark=""):
        """登记一笔销售退货：可选把货退回库存，退款默认按原单价 × 数量。

        返回 (ok, msg)。
        """
        try:
            qty = int(round(float(qty or 0)))
        except (TypeError, ValueError):
            return False, "退货数量不正确"
        if qty <= 0:
            return False, "退货数量必须大于 0"
        with self._lock:
            row = self.conn.execute("SELECT * FROM sales WHERE id = ?",
                                    (int(sale_id),)).fetchone()
            if row is None:
                return False, "找不到对应的出售记录"
            s = dict(row)
            if str(s.get("out_type") or OUT_TYPE_SALE) != OUT_TYPE_SALE:
                return False, "只有「销售」记录才能退货"
            sold = int(s.get("qty") or 0)
            back = self.conn.execute(
                "SELECT COALESCE(SUM(qty), 0) FROM returns WHERE sale_id = ?",
                (int(sale_id),)).fetchone()[0]
            left = sold - int(back or 0)
            if qty > left:
                return False, ("该笔最多还能退 %d 件（已退 %d 件）"
                               % (max(0, left), int(back or 0)))
            price = float(s.get("price") or 0)
            if refund is None:
                refund = round(price * qty, 2)
            try:
                refund = float(refund or 0)
            except (TypeError, ValueError):
                return False, "退款金额不正确"
            if refund < 0:
                return False, "退款金额不能为负数"
            cost = float(s.get("cost") or 0)
            date = (return_date or "").strip() or now_str()[:10]
            item_id = s.get("item_id")
            restore = bool(restock) and bool(item_id)
            self.conn.execute(
                "INSERT INTO returns (sale_id, item_id, code, brand, category,"
                " model, shelf, qty, price, refund, cost, restock, buyer,"
                " return_date, remark, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(sale_id), item_id or 0, s.get("code") or "",
                 s.get("brand") or "", s.get("category") or "",
                 s.get("model") or "", s.get("shelf") or "", qty, price,
                 round(refund, 2), round(cost, 4), 1 if restore else 0,
                 s.get("buyer") or "", date, (remark or "").strip(), now_str()))
            if restore:
                self.conn.execute(
                    'UPDATE items SET "qty" = COALESCE("qty", 0) + ?,'
                    ' "sold_out" = 0, "updated_at" = ? WHERE id = ?',
                    (qty, now_str(), item_id))
            self.conn.commit()
        code = s.get("code") or ""
        self.log_op("销售退货", code,
                    "%d 件，退款 %.2f 元%s" % (qty, refund,
                                               "，已退回库存" if restore else ""))
        return True, ("已登记退货 %s：%d 件，退款 %.2f 元%s"
                      % (code, qty, refund, "，已退回库存" if restore else ""))

    def list_returns(self, start="", end="", kw=""):
        sql = "SELECT * FROM returns WHERE 1 = 1"
        args = []
        if start:
            sql += " AND COALESCE(return_date, '') >= ?"
            args.append(start)
        if end:
            sql += " AND COALESCE(return_date, '') <= ?"
            args.append(end)
        kw = (kw or "").strip()
        if kw:
            like = "%" + kw + "%"
            sql += (" AND (code LIKE ? OR brand LIKE ? OR model LIKE ?"
                    " OR buyer LIKE ? OR remark LIKE ?)")
            args += [like] * 5
        sql += " ORDER BY COALESCE(return_date, '') DESC, id DESC"
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def delete_return(self, rid):
        """撤销退货：退回库存的货再扣回来（库存不足则拒绝）。"""
        with self._lock:
            row = self.conn.execute("SELECT * FROM returns WHERE id = ?",
                                    (int(rid),)).fetchone()
            if row is None:
                return False, "退货记录不存在"
            r = dict(row)
            if int(r.get("restock") or 0) and int(r.get("item_id") or 0):
                item = self.conn.execute(
                    'SELECT "qty" FROM items WHERE id = ?',
                    (int(r["item_id"]),)).fetchone()
                if item is not None:
                    q = int(item[0] or 0)
                    if q < int(r.get("qty") or 0):
                        return False, ("库存只剩 %d 件，不足以撤销这次退货"
                                       % q)
                    left = q - int(r.get("qty") or 0)
                    self.conn.execute(
                        'UPDATE items SET "qty" = ?, "sold_out" = ?,'
                        ' "updated_at" = ? WHERE id = ?',
                        (left, 1 if left <= 0 else 0, now_str(),
                         int(r["item_id"])))
            self.conn.execute("DELETE FROM returns WHERE id = ?", (int(rid),))
            self.conn.commit()
        self.log_op("撤销退货", r.get("code") or "",
                    "%d 件，退款 %.2f 元" % (int(r.get("qty") or 0),
                                            float(r.get("refund") or 0)))
        return True, "已撤销这笔退货"

    def returns_total(self, start="", end=""):
        sql = ("SELECT COUNT(*) c, COALESCE(SUM(qty), 0) q,"
               " COALESCE(SUM(refund), 0) amt, COALESCE(SUM(cost * qty), 0) cst"
               " FROM returns WHERE 1 = 1")
        args = []
        if start:
            sql += " AND COALESCE(return_date, '') >= ?"
            args.append(start)
        if end:
            sql += " AND COALESCE(return_date, '') <= ?"
            args.append(end)
        with self._lock:
            r = dict(self.conn.execute(sql, args).fetchone())
        return {"count": int(r["c"] or 0), "qty": int(r["q"] or 0),
                "refund": round(float(r["amt"] or 0), 2),
                "cost": round(float(r["cst"] or 0), 2)}

    # ------------------------------------------------------------ 销售利润（v1.32.0）
    def profit_rows(self, start="", end="", brand="", kw=""):
        """逐笔销售利润（退货冲减原单）。

        利润 = 实收（销售额 - 退款） - 净成本（成本 - 退回部分成本），
        这样「卖出去又退回来」的货利润归零，不会虚增。
        """
        sql = ("SELECT s.*, COALESCE(r.q, 0) rq, COALESCE(r.amt, 0) ramt,"
               " COALESCE(r.cst, 0) rcst FROM sales s"
               " LEFT JOIN (SELECT sale_id, SUM(qty) q, SUM(refund) amt,"
               " SUM(cost * qty) cst FROM returns GROUP BY sale_id) r"
               " ON r.sale_id = s.id"
               " WHERE COALESCE(s.out_type, '%s') = '%s'"
               % (OUT_TYPE_SALE, OUT_TYPE_SALE))
        args = []
        if start:
            sql += " AND COALESCE(s.sale_date, '') >= ?"
            args.append(start)
        if end:
            sql += " AND COALESCE(s.sale_date, '') <= ?"
            args.append(end)
        brand = (brand or "").strip()
        if brand and brand != "全部":
            sql += " AND s.brand LIKE ?"
            args.append("%" + brand + "%")
        kw = (kw or "").strip()
        if kw:
            like = "%" + kw + "%"
            sql += (" AND (s.code LIKE ? OR s.brand LIKE ? OR s.model LIKE ?"
                    " OR s.buyer LIKE ?)")
            args += [like] * 4
        sql += " ORDER BY COALESCE(s.sale_date, '') DESC, s.id DESC"
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(sql, args).fetchall()]
        out = []
        for r in rows:
            qty = int(r.get("qty") or 0)
            rq = int(r.get("rq") or 0)
            amount = float(r.get("total") or 0) - float(r.get("ramt") or 0)
            cost = (float(r.get("cost") or 0) * qty
                    - float(r.get("rcst") or 0))
            profit = amount - cost
            out.append({
                "id": int(r["id"]), "code": r.get("code") or "",
                "brand": r.get("brand") or "", "category": r.get("category") or "",
                "model": r.get("model") or "", "buyer": r.get("buyer") or "",
                "date": r.get("sale_date") or "", "qty": qty, "rq": rq,
                "price": round(float(r.get("price") or 0), 2),
                "amount": round(amount, 2), "refund": round(float(r.get("ramt") or 0), 2),
                "cost": round(cost, 2), "profit": round(profit, 2),
                "margin": round(profit / amount * 100, 2) if amount else 0.0,
            })
        return out

    # ------------------------------------------------------------ 盘点单（v1.32.0）
    def create_stocktake(self, name="", brand="", category="", shelf="",
                         kw="", only_stock=True):
        """按筛选条件生成盘点单快照（账面数 = 当前库存）。返回 (st_id, msg)。"""
        where = ["COALESCE(deleted_at, '') = ''"]
        args = []
        for col, val in (("brand", brand), ("category", category),
                         ("shelf", shelf)):
            val = (val or "").strip()
            if val and val != "全部":
                where.append('"%s" LIKE ?' % col)
                args.append("%" + val + "%")
        kw = (kw or "").strip()
        if kw:
            like = "%" + kw + "%"
            where.append('("code" LIKE ? OR "model" LIKE ? OR "brand" LIKE ?)')
            args += [like] * 3
        if only_stock:
            where.append('COALESCE("qty", 0) > 0')
        sql = ('SELECT id, code, brand, model, shelf, "qty" FROM items WHERE '
               + " AND ".join(where) + ' ORDER BY "code"')
        with self._lock:
            src = [dict(r) for r in self.conn.execute(sql, args).fetchall()]
            if not src:
                return 0, "没有符合条件的记录（可取消「只盘有货的」再试）"
            created = now_str()
            no = "PD%s" % time.strftime("%Y%m%d%H%M%S")
            cur = self.conn.execute(
                "INSERT INTO stocktakes (no, name, status, created_at, note)"
                " VALUES (?,?, 'draft', ?, '')",
                (no, (name or "").strip() or ("盘点 %s" % created[:16]), created))
            st_id = int(cur.lastrowid)
            self.conn.executemany(
                "INSERT INTO stocktake_items (st_id, item_id, code, brand,"
                " model, shelf, book_qty, real_qty, note)"
                " VALUES (?,?,?,?,?,?,?,?, '')",
                [(st_id, int(r["id"]), r.get("code") or "", r.get("brand") or "",
                  r.get("model") or "", r.get("shelf") or "",
                  int(r.get("qty") or 0), int(r.get("qty") or 0)) for r in src])
            self.conn.commit()
        self.log_op("新建盘点单", no, "%d 条记录" % len(src))
        return st_id, "已生成盘点单 %s：%d 条记录" % (no, len(src))

    def list_stocktakes(self):
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT s.*,"
                " (SELECT COUNT(*) FROM stocktake_items i WHERE i.st_id = s.id) n,"
                " (SELECT COUNT(*) FROM stocktake_items i WHERE i.st_id = s.id"
                "  AND i.real_qty != i.book_qty) d,"
                " (SELECT COALESCE(SUM(i.real_qty - i.book_qty), 0)"
                "  FROM stocktake_items i WHERE i.st_id = s.id) dq"
                " FROM stocktakes s ORDER BY s.id DESC").fetchall()]
        return [{"id": int(r["id"]), "no": r.get("no") or "",
                 "name": r.get("name") or "", "status": r.get("status") or "draft",
                 "created_at": r.get("created_at") or "",
                 "done_at": r.get("done_at") or "",
                 "count": int(r.get("n") or 0), "diff": int(r.get("d") or 0),
                 "diff_qty": int(r.get("dq") or 0)} for r in rows]

    def stocktake_detail(self, st_id):
        with self._lock:
            head = self.conn.execute("SELECT * FROM stocktakes WHERE id = ?",
                                     (int(st_id),)).fetchone()
            if head is None:
                return None
            rows = [dict(r) for r in self.conn.execute(
                "SELECT * FROM stocktake_items WHERE st_id = ? ORDER BY code",
                (int(st_id),)).fetchall()]
        return {"head": dict(head), "rows": rows}

    def set_stocktake_qty(self, row_id, real_qty, note=None):
        try:
            real_qty = int(round(float(real_qty)))
        except (TypeError, ValueError):
            return False, "实盘数量必须是整数"
        if real_qty < 0:
            return False, "实盘数量不能为负数"
        with self._lock:
            row = self.conn.execute(
                "SELECT i.st_id, s.status FROM stocktake_items i"
                " JOIN stocktakes s ON s.id = i.st_id WHERE i.id = ?",
                (int(row_id),)).fetchone()
            if row is None:
                return False, "盘点明细不存在"
            if str(row[1] or "draft") != "draft":
                return False, "盘点单已提交，不能再改实盘数"
            if note is None:
                self.conn.execute(
                    "UPDATE stocktake_items SET real_qty = ? WHERE id = ?",
                    (real_qty, int(row_id)))
            else:
                self.conn.execute(
                    "UPDATE stocktake_items SET real_qty = ?, note = ? WHERE id = ?",
                    (real_qty, str(note).strip(), int(row_id)))
            self.conn.commit()
        return True, ""

    def commit_stocktake(self, st_id):
        """按实盘数写回库存，并把单据标记为已完成。返回 (ok, msg)。"""
        with self._lock:
            head = self.conn.execute("SELECT * FROM stocktakes WHERE id = ?",
                                     (int(st_id),)).fetchone()
            if head is None:
                return False, "盘点单不存在"
            if str(head["status"] or "draft") != "draft":
                return False, "这张盘点单已经提交过了"
            rows = [dict(r) for r in self.conn.execute(
                "SELECT * FROM stocktake_items WHERE st_id = ?",
                (int(st_id),)).fetchall()]
            changed = 0
            for r in rows:
                book = int(r.get("book_qty") or 0)
                real = int(r.get("real_qty") or 0)
                if real == book:
                    continue
                item = self.conn.execute(
                    'SELECT "qty" FROM items WHERE id = ?',
                    (int(r.get("item_id") or 0),)).fetchone()
                if item is None:
                    continue          # 盘点期间被删掉的记录：跳过
                self.conn.execute(
                    'UPDATE items SET "qty" = ?, "sold_out" = ?,'
                    ' "updated_at" = ? WHERE id = ?',
                    (real, 1 if real <= 0 else 0, now_str(),
                     int(r["item_id"])))
                changed += 1
            self.conn.execute(
                "UPDATE stocktakes SET status = 'done', done_at = ? WHERE id = ?",
                (now_str(), int(st_id)))
            self.conn.commit()
        diff_qty = sum(int(r.get("real_qty") or 0) - int(r.get("book_qty") or 0)
                       for r in rows)
        self.log_op("提交盘点", head["no"] or "",
                    "%d 条差异，净变动 %+d 件" % (changed, diff_qty))
        return True, ("盘点已提交：%d 条记录库存被调整，净变动 %+d 件"
                      % (changed, diff_qty))

    def delete_stocktake(self, st_id):
        with self._lock:
            head = self.conn.execute("SELECT status FROM stocktakes WHERE id = ?",
                                     (int(st_id),)).fetchone()
            if head is None:
                return 0
            if str(head[0] or "") == "done":
                return -1             # 已提交的单据不给删（库存已改，删了没意义）
            self.conn.execute("DELETE FROM stocktake_items WHERE st_id = ?",
                              (int(st_id),))
            self.conn.execute("DELETE FROM stocktakes WHERE id = ?", (int(st_id),))
            self.conn.commit()
        return 1

    # -------------------------------------------------- 制作流程（v1.42.0）
    # A发起制作 → B制作标签 → C贴标签 → D质检 → E入库；节点名可自定义，
    # 每一步（发起/推进/退回/取消）都要求填写操作人姓名，全程留痕。
    WF_STAGES_KEY = "workflow_stages"
    WF_DEFAULT_STAGES = ["发起制作", "制作标签", "贴标签", "质检", "入库"]
    WF_KINDS_KEY = "workflow_kinds"
    WF_STATIONS_KEY = "workflow_stations"
    # 类型可自定义；每个类型可带若干「附加字段」，
    # field = {"label": 名称, "options": [选项,...], "multi": 是否多选}
    # （有 options 渲染成下拉/勾选，multi=True 是勾选框可同时选多项；
    #   无 options 就是普通输入框）
    WF_DEFAULT_KINDS = [
        {"name": "修复", "fields": []},
        {"name": "更换型号标签",
         "fields": [{"label": "原型号"}, {"label": "更换后型号"}]},
        {"name": "制作标签",
         "fields": [{"label": "标签种类", "multi": True,
                     "options": ["外箱标", "机身标", "配件标"]}]},
        {"name": "返工", "fields": []},
        {"name": "其他", "fields": []},
    ]
    WF_ACTIONS = {"create": "发起", "advance": "推进", "back": "退回",
                  "cancel": "取消", "resume": "恢复", "stock": "入库",
                  "finish": "结单", "urgent": "标加急", "unurgent": "取消加急"}

    def wf_stages(self):
        """流程节点名称列表（meta 可自定义；无自定义用默认五节点）。"""
        raw = self.get_meta(self.WF_STAGES_KEY, "")
        if raw:
            try:
                names = json.loads(raw)
                if isinstance(names, list):
                    names = [str(x).strip() for x in names if str(x).strip()]
                    if len(names) >= 2:
                        return names[:12]
            except Exception:
                pass
        return list(self.WF_DEFAULT_STAGES)

    def wf_set_stages(self, names):
        """保存自定义节点名（去重去空；已有单据超界时钳到最后一节点）。"""
        clean = []
        for n in names or []:
            n = str(n).strip()[:20]
            if n and n not in clean:
                clean.append(n)
        if len(clean) < 2:
            return False, "流程至少要 2 个节点"
        if len(clean) > 12:
            return False, "节点最多 12 个"
        self.set_meta(self.WF_STAGES_KEY, json.dumps(clean, ensure_ascii=False))
        with self._lock:
            self.conn.execute("UPDATE workflows SET stage = ? WHERE stage >= ?",
                              (len(clean) - 1, len(clean)))
            self.conn.commit()
        self.log_op("修改", "制作流程", "节点：%s" % " → ".join(clean))
        return True, "节点已保存：%s" % " → ".join(clean)

    # ---------------------------------------------------- 工位（一个节点可多人）
    def wf_stations(self):
        """工位列表 [{"name": 工位名, "stage": 节点序号}]。

        一个节点可以有多个人：工位名可写成「制作标签A」「制作标签B」，
        都绑定同一个节点；推送时可以指定发给哪个工位（不指定 = 该节点任意人）。
        没有自定义工位时，默认每个节点一个同名工位。
        """
        stages = self.wf_stages()
        raw = self.get_meta(self.WF_STATIONS_KEY, "")
        out = []
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    for it in data[:60]:
                        if not isinstance(it, dict):
                            continue
                        name = str(it.get("name") or "").strip()[:20]
                        try:
                            stg = int(it.get("stage"))
                        except (TypeError, ValueError):
                            continue
                        if 0 <= stg < len(stages) and name \
                                and not any(o["name"] == name for o in out):
                            out.append({"name": name, "stage": stg})
            except Exception:
                out = []
        # 每个节点至少有一个工位（没配的用节点名兜底，避免推给空气）
        have = {o["stage"] for o in out}
        for i, s in enumerate(stages):
            if i not in have and s not in [o["name"] for o in out]:
                out.append({"name": s, "stage": i})
        out.sort(key=lambda o: (o["stage"], o["name"]))
        return out

    def wf_set_stations(self, items):
        """保存工位定义（名称去重、必须绑定有效节点；每节点至少一个）。"""
        stages = self.wf_stages()
        clean, seen = [], set()
        for it in (items or [])[:60]:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()[:20]
            try:
                stg = int(it.get("stage"))
            except (TypeError, ValueError):
                continue
            if not name or name in seen or not (0 <= stg < len(stages)):
                continue
            seen.add(name)
            clean.append({"name": name, "stage": stg})
        if not clean:
            return False, "至少要有一个工位"
        # 每个节点至少留一个工位（没配的用节点名兜底，避免「推给空气」）
        for i, st in enumerate(stages):
            if i in {c["stage"] for c in clean}:
                continue
            name, k = st, 2
            while name in seen:           # 节点名已被别的工位占用 → 加序号
                name, k = "%s-%d" % (st, k), k + 1
            seen.add(name)
            clean.append({"name": name, "stage": i})
        clean.sort(key=lambda c: (c["stage"], c["name"]))
        self.set_meta(self.WF_STATIONS_KEY,
                      json.dumps(clean, ensure_ascii=False))
        return True, "已保存 %d 个工位" % len(clean)

    def wf_station_names(self, stage=None):
        """某节点下的工位名列表；stage=None 返回全部。"""
        out = [s["name"] for s in self.wf_stations()
               if stage is None or s["stage"] == stage]
        return out

    def wf_station_stage(self, name):
        """工位名 → 节点序号（找不到返回 -1）。"""
        for s in self.wf_stations():
            if s["name"] == name:
                return s["stage"]
        return -1

    def wf_kinds(self):
        """制作类型列表（含各自的附加字段定义；meta 可自定义）。"""
        raw = self.get_meta(self.WF_KINDS_KEY, "")
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, list) and data:
                    kinds = self._clean_kinds(data)
                    if kinds:
                        return kinds
            except Exception:
                pass
        return [dict(k) for k in self.WF_DEFAULT_KINDS]

    @staticmethod
    def _clean_kinds(data):
        """清洗类型定义：去空名/去重/字段去空，最多 20 类 × 每类 8 字段。"""
        kinds = []
        for k in data[:20]:
            if not isinstance(k, dict):
                continue
            name = str(k.get("name") or "").strip()[:20]
            if not name or any(x["name"] == name for x in kinds):
                continue
            fields = []
            for f in (k.get("fields") or [])[:8]:
                if not isinstance(f, dict):
                    continue
                label = str(f.get("label") or "").strip()[:20]
                if not label:
                    continue
                opts = [str(o).strip()[:30] for o in (f.get("options") or [])
                        if str(o).strip()]
                fd = {"label": label, "options": opts[:12]}
                if opts and f.get("multi"):
                    fd["multi"] = True      # 勾选框，可同时选多项
                fields.append(fd)
            kinds.append({"name": name, "fields": fields})
        return kinds

    def wf_set_kinds(self, kinds):
        """保存自定义类型（含附加字段定义）。"""
        clean = self._clean_kinds(kinds)
        if not clean:
            return False, "至少要保留 1 个类型"
        self.set_meta(self.WF_KINDS_KEY,
                      json.dumps(clean, ensure_ascii=False))
        names = "、".join(k["name"] for k in clean)
        self.log_op("修改", "制作流程", "类型：%s" % names)
        return True, "类型已保存：%s" % names

    def wf_create(self, title, kind="", target="", note="", by="", extra=None,
                  station=""):
        """发起一张制作单。station = 发给第一站的哪个工位（空 = 任意人）。"""
        title = (title or "").strip()
        by = (by or "").strip()
        if not title:
            return 0, "事项内容不能为空"
        if not by:
            return 0, "请填写你的名字（发起人）"
        station = (station or "").strip()[:20]
        if station and self.wf_station_stage(station) != 0:
            return 0, "工位「%s」不在第一站" % station
        ts = now_str()
        with self._lock:
            row = self.conn.execute(
                "SELECT v FROM meta WHERE k = 'wf_seq'").fetchone()
            seq = int(row["v"]) if row and str(row["v"]).isdigit() else 0
            seq += 1
            no = "WO-%05d" % seq
            self.conn.execute(
                "INSERT INTO meta (k, v) VALUES ('wf_seq', ?) "
                "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (str(seq),))
            cur = self.conn.execute(
                "INSERT INTO workflows (no, title, kind, target, stage, status,"
                " created_at, updated_at, note, extra, station)"
                " VALUES (?,?,?,?,0,'active',?,?,?,?,?)",
                (no, title, (kind or "").strip(), (target or "").strip(),
                 ts, ts, (note or "").strip(),
                 json.dumps(extra or {}, ensure_ascii=False)
                 if isinstance(extra, dict) and extra else None, station))
            wf_id = int(cur.lastrowid)
            self.conn.execute(
                "INSERT INTO workflow_logs (wf_id, stage, action, by, at, note)"
                " VALUES (?,?,?,?,?,?)",
                (wf_id, 0, "create", by, ts,
                 "发起制作：%s%s" % (title, ("（交给 %s）" % station)
                                     if station else "")))
            self.conn.commit()
        self.log_op("制作流程", no, "%s（发起人：%s）" % (title, by))
        return wf_id, no

    def wf_list(self, status="active", kw="", station=""):
        """按状态列出制作单（附节点名、经手人、停留天数）。

        station 给了工位名时：只返回「指定给这个工位」的单，
        以及「没指定人、停在同一个节点」的单（= 该节点的公共池）。
        """
        stages = self.wf_stages()
        where, args = [], []
        if status in ("active", "done", "cancelled"):
            where.append("status = ?")
            args.append(status)
        kw = (kw or "").strip()
        if kw:
            like = "%" + kw + "%"
            where.append("(title LIKE ? OR target LIKE ? OR no LIKE ? OR note LIKE ?"
                         " OR extra LIKE ?)")
            args += [like] * 5
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT * FROM workflows"
                + (" WHERE " + " AND ".join(where) if where else "")
                + " ORDER BY urgent DESC, id DESC", args).fetchall()]
            # 经手人 = 最近一条流转记录的 by
            bys = {}
            if rows:
                ids = [int(r["id"]) for r in rows]
                ph = ",".join("?" * len(ids))
                for r in self.conn.execute(
                        "SELECT wf_id, by FROM workflow_logs WHERE wf_id IN (%s)"
                        " ORDER BY id DESC" % ph, ids).fetchall():
                    k = int(r["wf_id"])
                    if k not in bys:
                        bys[k] = str(r["by"] or "")
        out = []
        want = (station or "").strip()
        want_stage = self.wf_station_stage(want) if want else -1
        for r in rows:
            st = int(r.get("stage") or 0)
            r["stage_name"] = stages[st] if 0 <= st < len(stages) else ("节点%d" % st)
            r["extra"] = self._parse_extra(r.get("extra"))
            r["last_name"] = stages[-1] if stages else ""
            r["at_last"] = (st == len(stages) - 1) and r.get("status") == "active"
            r["handler"] = bys.get(int(r["id"]), "")
            try:
                d0 = datetime.strptime((r.get("updated_at") or "")[:10], "%Y-%m-%d")
                r["days"] = max(0, (datetime.now() - d0).days)
            except Exception:
                r["days"] = 0
            r["station"] = str(r.get("station") or "")
            if want and r.get("status") == "active":
                # 明确指定给别人 → 我不该看到；没指定且同节点 → 公共池，都能看到
                if r["station"]:
                    if r["station"] != want:
                        continue
                elif st != want_stage:
                    continue
            out.append(r)
        return out

    @staticmethod
    def _parse_extra(raw):
        """workflows.extra 的 JSON → dict（坏数据退回空 dict）。"""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def wf_one(self, wf_id):
        """取一张制作单的原始行（工位权限校验用）。"""
        with self._lock:
            r = self.conn.execute("SELECT * FROM workflows WHERE id = ?",
                                  (int(wf_id),)).fetchone()
        return dict(r) if r else None

    def wf_counts(self):
        """各节点在办数量 + 已完成 / 已取消数量（画流程条用）。"""
        stages = self.wf_stages()
        with self._lock:
            rows = self.conn.execute(
                "SELECT stage, COUNT(*) n FROM workflows WHERE status = 'active'"
                " GROUP BY stage").fetchall()
            done = int(self.conn.execute(
                "SELECT COUNT(*) n FROM workflows WHERE status = 'done'"
            ).fetchone()["n"])
            cancelled = int(self.conn.execute(
                "SELECT COUNT(*) n FROM workflows WHERE status = 'cancelled'"
            ).fetchone()["n"])
        cnt = [0] * len(stages)
        for r in rows:
            cnt[min(int(r["stage"]), len(stages) - 1)] = int(r["n"])
        return {"stages": stages, "counts": cnt,
                "done": done, "cancelled": cancelled}

    def wf_stamp(self):
        """制作流程的数据指纹（主机端轮询：别人推进了就自动刷列表）。"""
        with self._lock:
            a = self.conn.execute(
                "SELECT COUNT(*) n, IFNULL(MAX(updated_at), '') u FROM workflows"
            ).fetchone()
            b = self.conn.execute(
                "SELECT COUNT(*) n, IFNULL(MAX(id), 0) m FROM workflow_logs"
            ).fetchone()
        return [int(a["n"]), str(a["u"]), int(b["n"]), int(b["m"])]

    def _wf_move(self, wf_id, by, note, forward=True, target=None, station=""):
        """推进 / 退回。station 指定交给目标节点的哪个工位（空=任意人）。
        退回默认到相邻上一站，target 可指定更早的站
        （如质检发现问题直接退回到「制作标签」，不必一站一站退）。返回 (ok, msg)。"""
        by = (by or "").strip()
        if not by:
            return False, "请先填写你的名字（经手人）"
        stages = self.wf_stages()
        note = (note or "").strip()
        with self._lock:
            head = self.conn.execute("SELECT * FROM workflows WHERE id = ?",
                                     (int(wf_id),)).fetchone()
            if head is None:
                return False, "制作单不存在"
            if str(head["status"] or "active") != "active" and not forward:
                pass                       # 已完成也允许退回（重新打开）
            elif str(head["status"] or "active") != "active":
                return False, "该单已结束（%s）" % head["status"]
            st = int(head["stage"] or 0)
            if forward:
                new = st + 1
            else:
                if target is None:
                    new = st - 1
                else:
                    try:
                        new = int(target)
                    except (TypeError, ValueError):
                        return False, "目标节点不正确"
                    if new < 0 or new >= st:
                        return False, "只能退回到当前节点（%s）之前的节点" % stages[st]
            if new < 0:
                return False, "已在第一个节点（%s）" % stages[0]
            if new > len(stages) - 1:
                return False, "已在最后节点（%s）" % stages[-1]
            station = (station or "").strip()[:20]
            if station and self.wf_station_stage(station) != new:
                return False, ("工位「%s」不在「%s」站，不能推给它"
                               % (station, stages[new]))
            ts = now_str()
            # v1.42.8：推进到最后一站（入库）不再立即结束——单据停在入库站，
            # 由入库员执行入库（wf_stock_in）或直接结单（wf_finish）才算走完
            log_note = note or ("退回「%s」" % stages[new] if not forward else "")
            # v1.42.10：备注同步写到单据上，下一站在列表/详情里直接可见；
            # 没填新备注时保留上一次的留言
            if log_note:
                self.conn.execute(
                    "UPDATE workflows SET stage = ?, status = 'active',"
                    " updated_at = ?, done_at = NULL, note = ?, station = ?"
                    " WHERE id = ?",
                    (new, ts, log_note, station, int(wf_id)))
            else:
                self.conn.execute(
                    "UPDATE workflows SET stage = ?, status = 'active',"
                    " updated_at = ?, done_at = NULL, station = ? WHERE id = ?",
                    (new, ts, station, int(wf_id)))
            act = "advance" if forward else "back"
            self.conn.execute(
                "INSERT INTO workflow_logs (wf_id, stage, action, by, at, note)"
                " VALUES (?,?,?,?,?,?)",
                (int(wf_id), new, act, by, ts,
                 log_note + (("（交给 %s）" % station) if station else "")))
            self.conn.commit()
        head = dict(head)
        if forward:
            self.log_op("制作流程", head.get("no") or "",
                        "%s → %s（%s）" % (stages[st], stages[new], by))
        else:
            self.log_op("制作流程", head.get("no") or "",
                        "%s 退回 %s（%s）" % (stages[st], stages[new], by))
        if forward and new == len(stages) - 1:
            return True, ("已推进到「%s」——请在该站完成收尾（填库存信息或结单）"
                          % stages[-1])
        return True, "已%s到「%s」（%s）" % ("推进" if forward else "退回",
                                            stages[new], by)

    def wf_advance(self, wf_id, by, note="", station=""):
        return self._wf_move(wf_id, by, note, forward=True, station=station)

    def wf_back(self, wf_id, by, note="", target=None, station=""):
        return self._wf_move(wf_id, by, note, forward=False, target=target,
                             station=station)

    def wf_cancel(self, wf_id, by, note=""):
        by = (by or "").strip()
        if not by:
            return False, "请先填写你的名字（操作人）"
        with self._lock:
            head = self.conn.execute("SELECT status FROM workflows WHERE id = ?",
                                     (int(wf_id),)).fetchone()
            if head is None:
                return False, "制作单不存在"
            if str(head[0] or "active") != "active":
                return False, "只有进行中的单据才能取消"
            ts = now_str()
            self.conn.execute(
                "UPDATE workflows SET status = 'cancelled', updated_at = ?,"
                " note = ? WHERE id = ?",
                (ts, (note or "").strip(), int(wf_id)))
            self.conn.execute(
                "INSERT INTO workflow_logs (wf_id, stage, action, by, at, note)"
                " VALUES (?,?,?,?,?,?)",
                (int(wf_id), 0, "cancel", by, ts, (note or "").strip()))
            self.conn.commit()
        self.log_op("制作流程", "", "取消单据 #%d（%s）" % (int(wf_id), by))
        return True, "已取消"

    def wf_resume(self, wf_id, by):
        by = (by or "").strip()
        if not by:
            return False, "请先填写你的名字（操作人）"
        with self._lock:
            head = self.conn.execute("SELECT status FROM workflows WHERE id = ?",
                                     (int(wf_id),)).fetchone()
            if head is None:
                return False, "制作单不存在"
            if str(head[0] or "") != "cancelled":
                return False, "只有已取消的单据才能恢复"
            ts = now_str()
            self.conn.execute(
                "UPDATE workflows SET status = 'active', updated_at = ?"
                " WHERE id = ?", (ts, int(wf_id)))
            self.conn.execute(
                "INSERT INTO workflow_logs (wf_id, stage, action, by, at, note)"
                " VALUES (?,?,?,?,?,?)",
                (int(wf_id), 0, "resume", by, ts, ""))
            self.conn.commit()
        self.log_op("制作流程", "", "恢复单据 #%d（%s）" % (int(wf_id), by))
        return True, "已恢复为进行中"

    def wf_set_urgent(self, wf_id, urgent, by=""):
        """标记 / 取消加急。加急单在列表里排最前并红色高亮。返回 (ok, msg)。"""
        flag = 1 if (urgent in (1, True, "1", "是")) else 0
        with self._lock:
            head = self.conn.execute("SELECT no, title FROM workflows"
                                     " WHERE id = ?", (int(wf_id),)).fetchone()
            if head is None:
                return False, "制作单不存在"
            ts = now_str()
            self.conn.execute(
                "UPDATE workflows SET urgent = ?, updated_at = ? WHERE id = ?",
                (flag, ts, int(wf_id)))
            self.conn.execute(
                "INSERT INTO workflow_logs (wf_id, stage, action, by, at, note)"
                " VALUES (?,?,?,?,?,?)",
                (int(wf_id), 0, "urgent" if flag else "unurgent",
                 (by or "").strip(), ts, ""))
            self.conn.commit()
        self.log_op("制作流程", head["no"] or "",
                    "%s单据 #%d（%s）" % ("加急" if flag else "取消加急",
                                          int(wf_id), by))
        return True, "已标记加急" if flag else "已取消加急"

    def wf_delete(self, wf_id):
        with self._lock:
            head = self.conn.execute("SELECT no, title FROM workflows WHERE id = ?",
                                     (int(wf_id),)).fetchone()
            if head is None:
                return False
            self.conn.execute("DELETE FROM workflow_logs WHERE wf_id = ?",
                              (int(wf_id),))
            self.conn.execute("DELETE FROM workflows WHERE id = ?", (int(wf_id),))
            self.conn.commit()
        no = dict(head)["no"] or ""
        try:                              # 连带清掉这张单的入库照片
            self.photos_wipe("wf", no)
        except Exception:
            pass
        self.log_op("制作流程", no, "删除单据：%s" % (dict(head)["title"] or ""))
        return True

    def wf_stock_in(self, wf_id, fields, by=""):
        """入库：按制作单新增一条库存，并把单据照片带到库存记录上。

        fields = {brand/category/model/condition/shelf/qty/price}
        返回 (ok, msg)。客户端推进到入库时也走这一个方法，
        照片复制发生在主机侧（照片文件只在主机上）。
        """
        with self._lock:
            r = self.conn.execute("SELECT * FROM workflows WHERE id = ?",
                                  (int(wf_id),)).fetchone()
        if r is None:
            return False, "制作单不存在"
        rec = dict(r)
        if str(rec.get("status") or "active") != "active":
            return False, "该单已结束，如需重新处理请先退回重开"
        stages = self.wf_stages()
        if int(rec.get("stage") or 0) != len(stages) - 1:
            return False, "该单还没到「%s」，不能入库" % stages[-1]
        f = dict(fields or {})
        model = str(f.get("model") or "").strip()
        if not model:
            return False, "入库需要至少填写「型号」"
        try:
            qty = int(float(f.get("qty") or 1))
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            return False, "数量必须是大于 0 的整数"
        try:
            price = float(f.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        code = self.generate_codes(1)[0]
        item = blank_record()
        item["code"] = code
        for k in ("brand", "category", "condition", "shelf"):
            item[k] = str(f.get(k) or "").strip()
        item["model"] = model
        item["qty"] = qty
        item["price"] = price
        item["remark"] = "制作入库 %s %s" % (rec.get("no") or "", rec.get("title") or "")
        try:
            self.insert(item)
        except Exception as e:
            return False, "新增库存失败：%s" % e
        self.wf_set_target(int(wf_id), code, by=by,
                           note="入库：%s 型号 %s ×%d" % (code, model, qty))
        n = 0
        try:                              # 入库照片带到库存记录，之后在库存里也能看
            n = self.photos_copy("wf", rec.get("no") or "", "item", code)
        except Exception:
            pass
        extra = ("，已带入 %d 张照片" % n) if n else ""
        ts = now_str()
        with self._lock:                   # 入库完成 = 单据走完流程
            self.conn.execute(
                "UPDATE workflows SET status = 'done', updated_at = ?,"
                " done_at = ? WHERE id = ?", (ts, ts, int(wf_id)))
            self.conn.commit()
        return True, "已入库：%s（%s ×%d%s）——单据已完成" % (code, model, qty, extra)

    def wf_finish(self, wf_id, by, note=""):
        """入库站直接结单：不新增库存（如报废 / 库存已在），单据标记完成。"""
        by = (by or "").strip()
        if not by:
            return False, "请先填写你的名字（操作人）"
        stages = self.wf_stages()
        note = (note or "").strip()
        with self._lock:
            head = self.conn.execute(
                "SELECT status, stage FROM workflows WHERE id = ?",
                (int(wf_id),)).fetchone()
            if head is None:
                return False, "制作单不存在"
            if str(head["status"] or "active") != "active":
                return False, "该单已结束"
            if int(head["stage"] or 0) != len(stages) - 1:
                return False, "该单还没到「%s」，不能结单" % stages[-1]
            ts = now_str()
            self.conn.execute(
                "UPDATE workflows SET status = 'done', updated_at = ?,"
                " done_at = ?, note = ? WHERE id = ?",
                (ts, ts, note, int(wf_id)))
            self.conn.execute(
                "INSERT INTO workflow_logs (wf_id, stage, action, by, at, note)"
                " VALUES (?,?,?,?,?,?)",
                (int(wf_id), len(stages) - 1, "finish", by, ts, note))
            self.conn.commit()
        self.log_op("制作流程", "", "结单 #%d（%s）" % (int(wf_id), by))
        return True, "已结单（未新增库存）——单据已完成"

    def wf_set_target(self, wf_id, target, by="", note=""):
        """入库后把生成的库存编号回写到单据（target），并留痕。"""
        ts = now_str()
        with self._lock:
            self.conn.execute("UPDATE workflows SET target = ?, updated_at = ?,"
                              " note = ? WHERE id = ?",
                              (str(target).strip(), ts, (note or "").strip(),
                               int(wf_id)))
            self.conn.execute(
                "INSERT INTO workflow_logs (wf_id, stage, action, by, at, note)"
                " VALUES (?,?,?,?,?,?)",
                (int(wf_id), 0, "stock", (by or "").strip(), ts,
                 (note or "").strip()))
            self.conn.commit()

    def wf_logs(self, wf_id):
        with self._lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT * FROM workflow_logs WHERE wf_id = ? ORDER BY id",
                (int(wf_id),)).fetchall()]
        stages = self.wf_stages()
        for r in rows:
            st = int(r.get("stage") or 0)
            r["stage_name"] = stages[st] if 0 <= st < len(stages) else ("节点%d" % st)
            r["action_name"] = self.WF_ACTIONS.get(str(r.get("action") or ""),
                                                   str(r.get("action") or ""))
        return rows


    # ------------------------------------------------------------ 采购入库
    def _recalc_cost(self, item_id):
        """按该商品全部采购记录重算移动加权平均成本单价。"""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(qty), 0) q, COALESCE(SUM(total), 0) t "
            "FROM purchases WHERE item_id = ?", (item_id,)).fetchone()
        q = float(row["q"] or 0)
        if q <= 0:
            return 0.0
        return round(float(row["t"] or 0) / q, 4)

    def add_purchase(self, item_id, qty, unit_cost, supplier="", purchase_date="", remark=""):
        """登记一笔采购入库：增加库存数量、更新成本单价（移动加权平均）。

        返回 (ok, msg)。
        """
        try:
            qty = int(round(float(qty or 0)))
        except (TypeError, ValueError):
            return False, "采购数量不正确"
        if qty <= 0:
            return False, "采购数量必须大于 0"
        try:
            unit_cost = float(unit_cost or 0)
        except (TypeError, ValueError):
            return False, "采购单价不正确"
        if unit_cost < 0:
            return False, "采购单价不能为负数"
        with self._lock:
            row = self.conn.execute(
                'SELECT {read} FROM items WHERE id = ? AND deleted_at IS NULL'
                .format(read=SQL_READ), (item_id,)).fetchone()
            if row is None:
                return False, "记录不存在（可能已被删除）"
            rec = dict(row)
            now = now_str()
            date = (purchase_date or "").strip() or now[:10]
            self.conn.execute(
                "INSERT INTO purchases (item_id, code, brand, category, model, shelf, qty,"
                " unit_cost, total, supplier, purchase_date, remark, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item_id, rec.get("code") or "", rec.get("brand") or "",
                 rec.get("category") or "", rec.get("model") or "", rec.get("shelf") or "",
                 qty, unit_cost, round(unit_cost * qty, 2), supplier or "", date,
                 remark or "", now))
            left = int(rec.get("qty") or 0) + qty
            cost = self._recalc_cost(item_id)
            self.conn.execute(
                'UPDATE items SET "qty" = ?, "cost" = ?, '
                '"sold_out" = CASE WHEN ? > 0 THEN 0 ELSE "sold_out" END,'
                '"updated_at" = ? WHERE id = ?',
                (left, cost, left, now, item_id))
            self.conn.commit()
        self.log_op("采购入库", rec.get("code") or "",
                    "%d 件 × %.2f 元，成本 %.2f 元%s"
                    % (qty, unit_cost, cost,
                       ("，供应商 " + supplier) if supplier else ""))
        return True, ("已入库 %s：%d 件 × %.2f 元，合计 %.2f 元，库存 %d 件，"
                      "成本单价 %.2f 元" % (rec.get("code") or "", qty, unit_cost,
                                            unit_cost * qty, left, cost))

    def list_purchases(self, start="", end="", kw=""):
        """按条件列出采购记录（按采购日期倒序）。"""
        sql = "SELECT * FROM purchases WHERE 1 = 1"
        args = []
        if start:
            sql += " AND COALESCE(purchase_date, '') >= ?"
            args.append(start)
        if end:
            sql += " AND COALESCE(purchase_date, '') <= ?"
            args.append(end)
        kw = (kw or "").strip()
        if kw:
            like = "%" + kw + "%"
            sql += (" AND (code LIKE ? OR brand LIKE ? OR model LIKE ?"
                    " OR supplier LIKE ? OR remark LIKE ?)")
            args.extend([like] * 5)
        sql += " ORDER BY COALESCE(purchase_date, '') DESC, id DESC"
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    @staticmethod
    def purchase_totals(rows):
        qty = sum(int(r.get("qty") or 0) for r in rows)
        amount = sum(float(r.get("total") or 0) for r in rows)
        return {"count": len(rows), "qty": qty, "amount": round(amount, 2),
                "avg": round(amount / qty, 2) if qty else 0.0}

    def delete_purchase(self, pid):
        """撤销一笔采购：扣回库存数量并重算成本单价。"""
        with self._lock:
            row = self.conn.execute("SELECT * FROM purchases WHERE id = ?", (pid,)).fetchone()
            if row is None:
                return False, "采购记录不存在"
            p = dict(row)
            item_id = p.get("item_id")
            cur = self.conn.execute('SELECT "qty" FROM items WHERE id = ?',
                                    (item_id,)).fetchone()
            if cur is not None:
                left = max(0, int(cur["qty"] or 0) - int(p.get("qty") or 0))
                self.conn.execute(
                    'UPDATE items SET "qty" = ?, "updated_at" = ? WHERE id = ?',
                    (left, now_str(), item_id))
            self.conn.execute("DELETE FROM purchases WHERE id = ?", (pid,))
            cost = self._recalc_cost(item_id)
            self.conn.execute('UPDATE items SET "cost" = ? WHERE id = ?', (cost, item_id))
            self.conn.commit()
        return True, "已撤销这笔采购，库存数量已相应扣回"

    def backup_to(self, path):
        """把当前库一致性备份到 path（SQLite 在线备份，含尚未落盘的 WAL 内容）。"""
        with self._lock:
            dst = sqlite3.connect(path)
            try:
                with dst:
                    self.conn.backup(dst)
            finally:
                dst.close()
        return path

    def clear_all(self, reset_seq=True, purge_sales=False):
        """删除全部记录（连同回收站）。默认同时把编号计数器归零，之后导入从 1 开始。

        purge_sales=True 时连同出售记录一起清空（菜单「清空全部数据」用）；
        导入「覆盖全部」只重建库存，保留出售流水。
        """
        self._execute("DELETE FROM items")
        self.photos_wipe_kind("item")            # 照片一并清理
        if purge_sales:
            self._execute("DELETE FROM sales")
            self._execute("DELETE FROM purchases")
            self.log_op("清空全部", "", "库存+出售+采购记录全部清空")
        else:
            self.log_op("清空全部", "", "库存记录全部清空%s"
                        % ("（出售流水保留）" if not purge_sales else ""))
        if reset_seq:
            self.reset_code_seq()

    # ---------------------------------------------------------- 导入合并
    def model_keys(self):
        """返回库中所有「有效型号」的归一化集合，用于导入前判断是否重复。"""
        with self._lock:
            cur = self.conn.execute('SELECT "model" v FROM items WHERE deleted_at IS NULL')
            out = set()
            for r in cur.fetchall():
                k = norm_model(r["v"])
                if k and k not in MODEL_BLANK:
                    out.add(k)
            return out

    def blank_content_keys(self):
        """库中所有「无型号」记录的内容指纹集合，用于导入预览判断是否重复。"""
        out = set()
        with self._lock:
            cur = self.conn.execute('SELECT {read} FROM items WHERE deleted_at IS NULL'
                                    .format(read=SQL_READ))
            for r in cur.fetchall():
                k = norm_model(r["model"])
                if not k or k in MODEL_BLANK:
                    out.add(_content_key(dict(r)))
        return out

    def duplicate_models(self):
        """返回库中被重复录入的型号：[(型号原值, 重复条数, 记录列表)]，按条数倒序。"""
        with self._lock:
            cur = self.conn.execute('SELECT {read} FROM items WHERE deleted_at IS NULL '
                                    'ORDER BY id'.format(read=SQL_READ))
            rows = [dict(r) for r in cur.fetchall()]
        groups = {}
        for r in rows:
            k = norm_model(r.get("model"))
            if not k or k in MODEL_BLANK:
                continue
            groups.setdefault(k, []).append(r)
        dup = [(g[0].get("model") or "", len(g), g) for g in groups.values() if len(g) > 1]
        dup.sort(key=lambda x: -x[1])
        return dup

    def merge_many(self, recs, match_field="model", dedupe_in_file=True,
                   auto_code=True, progress=None):
        """按 match_field（默认「型号」）把新数据并入库中：**只新增，不改动原有数据**。

        规则：
          · 型号与库中已有记录相同 → 该行跳过，不导入（库中原记录保持原样，不更新不删除）
          · 型号为空/无效（空、-、无型号…）→ 按「内容指纹」（品牌+品类+成色+价格+数量等
            全部字段）与库中已有的无型号记录比对，内容完全相同 → 跳过；否则新增
          · 同一文件里型号重复 → 只保留最后一条，避免一次导入就产生重复
          · 新增行没有编号 → 自动生成 WL-xxxxx（库中有数据则接着排；库为空则从 WL-00001 开始）
          · 库中已有的记录在任何情况下都不会被修改或删除

        返回 dict: added / skipped(与库中重复而跳过) / merged(文件内重复合并) / auto
        """
        ts = now_str()
        insert_sql = ('INSERT INTO items ({cols}, created_at, updated_at) VALUES ({ph})'
                      .format(cols=SQL_COLS, ph=", ".join(["?"] * (len(FIELD_KEYS) + 2))))

        def _empty(raw):
            return raw is None or str(raw).strip() == ""

        with self._lock:
            cur = self.conn.cursor()
            cur.execute('SELECT {read} FROM items WHERE deleted_at IS NULL ORDER BY id'
                        .format(read=SQL_READ))
            index = {}          # 归一化型号 -> True（库中已存在）
            blank_index = set() # 库中无型号记录的内容指纹
            for r in cur.fetchall():
                k = norm_model(r[match_field])
                if k and k not in MODEL_BLANK:
                    index[k] = True
                else:
                    blank_index.add(_content_key(dict(r)))

            # ① 文件内去重：同一型号只保留最后一条；无型号但内容完全相同的也只留一条
            if dedupe_in_file:
                kept, merged = dedupe_records(recs, match_field)
            else:
                kept, merged = list(recs), 0

            # ② 与库中数据对比：型号已存在 → 跳过；无型号但内容与库中已有记录相同 → 跳过
            inserts, skipped = [], 0
            for rec in kept:
                k = norm_model(rec.get(match_field))
                if k and k not in MODEL_BLANK:
                    if index.get(k):
                        skipped += 1
                        continue
                else:
                    ck = _content_key(rec)
                    if ck in blank_index:
                        skipped += 1
                        continue
                    blank_index.add(ck)   # 本批新加的无型号记录，后续相同内容也跳过
                inserts.append(rec)

            # ③ 新增行补自动编号（一次性生成，避免重号）
            auto = 0
            if auto_code:
                missing = [r for r in inserts if _empty(r.get("code"))]
                if missing:
                    codes = iter(self.generate_codes(len(missing)))
                    for r in missing:
                        r["code"] = next(codes)
                    auto = len(missing)

            # ④ 只执行新增，绝不 UPDATE / DELETE 库中已有记录
            ins_batch, added = [], 0
            for rec in inserts:
                ins_batch.append(tuple(self._vals(rec)) + (ts, ts))
                if len(ins_batch) >= 500:
                    cur.executemany(insert_sql, ins_batch)
                    added += len(ins_batch)
                    ins_batch = []
            if ins_batch:
                cur.executemany(insert_sql, ins_batch)
                added += len(ins_batch)
            if progress:
                progress(len(kept))
            self.conn.commit()
        return {"added": added, "skipped": skipped, "merged": merged, "auto": auto}

    def dedupe_db(self, dry_run=False):
        """清理库中重复记录：相同型号只保留最早一条；无型号但内容完全相同的也只留一条。

        被清理的记录会进回收站（可在「数据 → 回收站」里恢复）。
        dry_run=True 时只统计不删除，用于确认对话框预览数量。
        返回 {"deleted": 删除条数, "groups": 重复组数}。
        """
        with self._lock:
            cur = self.conn.execute('SELECT {read} FROM items WHERE deleted_at IS NULL '
                                    'ORDER BY id'.format(read=SQL_READ))
            rows = [dict(r) for r in cur.fetchall()]
        seen_model, seen_content = {}, {}
        del_ids, groups = [], set()
        for r in rows:
            k = norm_model(r.get("model"))
            if k and k not in MODEL_BLANK:
                if k in seen_model:
                    del_ids.append(r["id"])
                    groups.add(k)
                else:
                    seen_model[k] = r["id"]
            else:
                ck = _content_key(r)
                if ck in seen_content:
                    del_ids.append(r["id"])
                    groups.add(ck)
                else:
                    seen_content[ck] = r["id"]
        if del_ids and not dry_run:
            self.delete_ids(del_ids)
        return {"deleted": len(del_ids), "groups": len(groups)}

    # ---------------------------------------------------------- 维护
    def _db_files(self):
        """数据库主文件 + WAL/SHM 中实际存在的那些。"""
        out = []
        for p in (self.path, self.path + "-wal", self.path + "-shm"):
            try:
                if os.path.isfile(p):
                    out.append(p)
            except OSError:
                pass
        return out

    def db_size(self):
        """数据库占用字节数（主文件 + WAL，SHM 只是共享内存索引，一并计入无妨）。"""
        total = 0
        for p in self._db_files():
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
        return total

    def photos_root(self):
        """当前仓库的照片根目录：<数据目录>/photos/<库文件名>/。"""
        stem = os.path.splitext(os.path.basename(self.path))[0]
        return os.path.join(os.path.dirname(os.path.abspath(self.path)),
                            "photos", stem)

    def photo_stats(self):
        """照片张数与占用字节数（扫一遍目录，只读）。"""
        n = 0
        size = 0
        for dirpath, _dirs, files in os.walk(self.photos_root()):
            for fn in files:
                if not fn.lower().endswith(PHOTO_EXTS):
                    continue
                try:
                    size += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    continue
                n += 1
        return n, size

    def table_counts(self):
        """各表记录数（库存区分在用 / 已售完 / 回收站）。"""
        def q(sql):
            try:
                with self._lock:
                    row = self.conn.execute(sql).fetchone()
                return int(row[0] or 0) if row else 0
            except Exception:
                return 0

        live = "deleted_at IS NULL"
        return {
            "items": q('SELECT COUNT(*) FROM items WHERE %s' % live),
            "sold": q('SELECT COUNT(*) FROM items WHERE %s AND sold_out = 1' % live),
            "trash": q('SELECT COUNT(*) FROM items WHERE deleted_at IS NOT NULL'),
            "sales": q('SELECT COUNT(*) FROM sales'),
            "purchases": q('SELECT COUNT(*) FROM purchases'),
            "customers": q('SELECT COUNT(*) FROM customers'),
            "phone_items": q('SELECT COUNT(*) FROM phone_items'),
            "phone_sales": q('SELECT COUNT(*) FROM phone_sales'),
            "oplog": q('SELECT COUNT(*) FROM oplog'),
        }

    def orphan_photos(self):
        """照片目录里存在、但库里找不到对应编号的目录（彻底删除记录后留下的）。"""
        root = self.photos_root()
        codes = set()
        for tbl in ("items", "phone_items"):
            try:
                with self._lock:
                    rows = self.conn.execute(
                        'SELECT "code" FROM %s' % tbl).fetchall()
            except Exception:
                continue
            for r in rows:
                c = str(r[0] or "").strip()
                if c:
                    codes.add(_safe_code(c))
        try:                          # 制作单照片（kind="wf"，编号是 WO-xxxxx）
            with self._lock:
                rows = self.conn.execute("SELECT no FROM workflows").fetchall()
            for r in rows:
                c = str(r[0] or "").strip()
                if c:
                    codes.add(_safe_code(c))
        except Exception:
            pass
        out = []
        for kind in PHOTO_KINDS:
            kd = os.path.join(root, kind)
            try:
                entries = list(os.scandir(kd))
            except OSError:
                continue
            for e in entries:
                try:
                    if not e.is_dir() or e.name in codes:
                        continue
                except OSError:
                    continue
                cnt, size = 0, 0
                for dirpath, _dirs, files in os.walk(e.path):
                    for fn in files:
                        if not fn.lower().endswith(PHOTO_EXTS):
                            continue
                        cnt += 1
                        try:
                            size += os.path.getsize(os.path.join(dirpath, fn))
                        except OSError:
                            pass
                out.append({"kind": kind, "code": e.name, "n": cnt,
                            "size": size})
        return out

    def photos_clear_orphans(self):
        """删除孤立照片目录，返回 (删掉的目录数, 释放字节数)。

        只动 <照片根>/<kind>/<编号> 这一层，且编号必须不在库里；
        回收站里的记录算「在库」，它们的照片不会被删。
        """
        root = os.path.abspath(self.photos_root())
        dirs, size = 0, 0
        for o in self.orphan_photos():
            d = os.path.abspath(os.path.join(root, o["kind"], o["code"]))
            try:
                if os.path.normcase(os.path.commonpath([d, root])) \
                        != os.path.normcase(root):
                    continue                    # 越界，宁可不删
                if d == root:
                    continue
                shutil.rmtree(d)
                dirs += 1
                size += int(o.get("size") or 0)
            except Exception:
                continue
        return dirs, size

    def _wal_trim(self):
        """把 WAL 收回主库并截断，让前后大小可直接对比（失败忽略）。"""
        try:
            with self._lock:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self.conn.commit()
        except Exception:
            pass

    def vacuum(self):
        """VACUUM 压缩数据库，返回 (压缩前, 压缩后) 字节数。

        VACUUM 会重写整个库文件；若不算上 WAL，压缩后「总大小」可能反而变大
        （旧页面还留在 -wal 里），所以前后各做一次 checkpoint。
        """
        self._wal_trim()
        before = self.db_size()
        with self._lock:
            self.conn.commit()
            self.conn.execute("VACUUM")
            self.conn.commit()
        self._wal_trim()
        return before, self.db_size()

    def integrity_check(self):
        """PRAGMA integrity_check：返回 (是否正常, 消息列表)。"""
        try:
            with self._lock:
                rows = self.conn.execute("PRAGMA integrity_check").fetchall()
            msgs = [str(r[0]) for r in rows]
            ok = len(msgs) == 1 and msgs[0].strip().lower() == "ok"
            return ok, msgs[:5]
        except Exception as e:
            return False, [str(e)]

    def health_check(self):
        """数据体检：返回一组 {key,title,level,count,samples,hint}。

        level=warn 表示建议处理，info 表示仅供参考。全部只读，不改数据。
        """
        def rows(sql):
            try:
                with self._lock:
                    return [r[0] for r in self.conn.execute(sql).fetchall()]
            except Exception:
                return []

        live = "deleted_at IS NULL"
        qty_i = "CAST(COALESCE(qty, 0) AS INTEGER)"
        out = []
        out.append({
            "key": "neg", "title": "库存数量为负", "level": "warn",
            "rows": rows('SELECT "code" FROM items WHERE %s AND %s < 0'
                         % (live, qty_i)),
            "hint": "数量小于 0 通常是导入或出售时填错，改成实际数量即可。"})
        out.append({
            "key": "zero", "title": "数量为 0 但未标记售完", "level": "info",
            "rows": rows('SELECT "code" FROM items WHERE %s AND sold_out = 0 '
                         'AND %s = 0' % (live, qty_i)),
            "hint": "卖完后忘记标「售完」的记录；不影响数据，只是列表里还当在售显示。"})
        out.append({
            "key": "dup", "title": "同型号多条记录", "level": "info",
            "rows": rows('SELECT "model" FROM items WHERE %s AND model <> \'\' '
                         'GROUP BY model HAVING COUNT(*) > 1' % live),
            "hint": "同型号分批到货属正常；如果是重复导入，可用「清理重复记录」合并。"})
        out.append({
            "key": "cost", "title": "已出售但没记成本", "level": "info",
            "rows": rows('SELECT DISTINCT s."code" FROM sales s '
                         'LEFT JOIN items i ON i.id = s.item_id '
                         'WHERE s.item_id <> 0 AND (i.cost IS NULL OR i.cost <= 0)'),
            "hint": "这些商品的利润按售价全额计算；登记一次采购入库就会自动补上成本。"})
        out.append({
            "key": "lost", "title": "出售记录找不到对应商品", "level": "warn",
            "rows": rows('SELECT DISTINCT "code" FROM sales WHERE item_id <> 0 '
                         'AND item_id NOT IN (SELECT id FROM items)'),
            "hint": "多半是商品被彻底删除过；出售记录本身还在，对账不受影响。"})
        orphans = self.orphan_photos()
        out.append({
            "key": "photo", "title": "多余的照片文件", "level": "info",
            "rows": ["%s %s（%d 张）" % ("商品" if o["kind"] == "item" else "手机",
                                        o["code"], o["n"]) for o in orphans],
            "size": sum(int(o.get("size") or 0) for o in orphans),
            "hint": "截图里这些编号已经被彻底删除，照片还留在磁盘上，可点「清理」释放空间。"})
        for r in out:
            r["count"] = len(r["rows"])
            r["samples"] = r["rows"][:8]
        return out

    # ---------------------------------------------------------- 统计
    def stats(self, records):
        """对给定记录集合做汇总统计。"""
        total = len(records)
        total_qty = sum(int(r.get("qty") or 0) for r in records)
        total_value = sum(float(r.get("price") or 0) * int(r.get("qty") or 0) for r in records)
        listed = sum(1 for r in records if int(r.get("listed") or 0) == 1)
        prices = [float(r.get("price") or 0) for r in records if float(r.get("price") or 0) > 0]

        def group(field, value_mode="count"):
            agg = {}
            for r in records:
                key = str(r.get(field) or "").strip() or "未填写"
                slot = agg.setdefault(key, {"count": 0, "qty": 0, "value": 0.0})
                slot["count"] += 1
                slot["qty"] += int(r.get("qty") or 0)
                slot["value"] += float(r.get("price") or 0) * int(r.get("qty") or 0)
            if value_mode == "count":
                items = sorted(agg.items(), key=lambda kv: -kv[1]["count"])
                return [(k, v["count"], v) for k, v in items]
            items = sorted(agg.items(), key=lambda kv: -kv[1]["qty"])
            return [(k, v["qty"], v) for k, v in items]

        # 价格区间
        buckets = [(0, 100, "<100"), (100, 300, "100-300"), (300, 500, "300-500"),
                   (500, 1000, "500-1k"), (1000, 3000, "1k-3k"), (3000, 10000, "3k-1w"),
                   (10000, float("inf"), "≥1w")]
        price_dist = []
        for lo, hi, label in buckets:
            c = sum(1 for p in prices if lo <= p < hi)
            if c:
                price_dist.append((label, c))

        return {
            "total": total,
            "total_qty": total_qty,
            "total_value": total_value,
            "listed": listed,
            "unlisted": total - listed,
            "listed_rate": (listed / total * 100.0) if total else 0.0,
            "avg_price": (sum(prices) / len(prices)) if prices else 0.0,
            "max_price": max(prices) if prices else 0.0,
            "min_price": min(prices) if prices else 0.0,
            "brands": group("brand"),
            "categories": group("category"),
            "conditions": group("condition"),
            "shelves": group("shelf"),
            "price_dist": price_dist,
            "brand_count": len({str(r.get("brand") or "").strip()
                                for r in records if str(r.get("brand") or "").strip()}),
            "category_count": len({str(r.get("category") or "").strip()
                                   for r in records if str(r.get("category") or "").strip()}),
            "shelf_count": len({str(r.get("shelf") or "").strip()
                                for r in records if str(r.get("shelf") or "").strip()}),
        }


__all__ = ["Store", "blank_record", "now_str", "LISTED_TEXT"]
