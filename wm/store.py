# -*- coding: utf-8 -*-
"""SQLite 数据层：仓库记录的持久化与查询。"""

import os
import re
import sqlite3
import threading
from datetime import datetime

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
"""

CODE_SEQ_KEY = "code_seq"


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

    def m_del_item(self, lid):
        with self._lock:
            self.conn.execute("DELETE FROM phone_items WHERE lid = ?", (int(lid),))
        self.conn.commit()

    def m_del_sale(self, lid):
        with self._lock:
            self.conn.execute("DELETE FROM phone_sales WHERE lid = ?", (int(lid),))
        self.conn.commit()

    def m_clear(self):
        """清空全部手机数据（不影响主库存）。"""
        with self._lock:
            self.conn.execute("DELETE FROM phone_items")
            self.conn.execute("DELETE FROM phone_sales")
        self.conn.commit()

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
            code = self.generate_codes(1)[0]
            rec["code"] = code
            rid = self.insert(rec)
            if row["sold_out"]:
                with self._lock:
                    self.conn.execute("UPDATE items SET sold_out=1 WHERE id=?", (rid,))
                self.conn.commit()
            with self._lock:
                self.conn.execute(
                    "UPDATE phone_items SET transferred=1, pc_id=?, updated_at=? "
                    "WHERE lid=?", (rid, now_str(), lid))
            self.conn.commit()
            n += 1
            codes.append(code)
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

    def generate_codes(self, n):
        """生成 n 个不与现有数据冲突的编号（WL-00001 起顺序递增）。

        规则（编号跟着数据走）：
          · 库中还有数据  → 接着已有编号的最大尾号往下排（追加/合并导入不会重号）
          · 库已被清空    → 计数器归零，从 WL-00001 重新开始
        """
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
            m = re.match(r"^WL-(\d+)$", c, re.IGNORECASE)
            if m:
                mx = max(mx, int(m.group(1)))
                continue
            # 兼容其它前缀的既有编号（如 SKU-1018），保证编号接着往下排
            tail = re.search(r"(\d+)\s*$", c)
            if tail:
                mx = max(mx, int(tail.group(1)))
        out = []
        i = mx + 1
        while len(out) < n:
            code = "WL-%05d" % i
            if code not in existing:
                out.append(code)
                existing.add(code)
            i += 1
        last = mx + len(out)
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
        self._execute(sql, tuple(self._vals(rec)) + (qleft, now_str(), rid))

    def update_field(self, rid, field, value):
        if field not in FIELD_KEYS:
            return
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
            return
        v = self._vals(rec)[FIELD_KEYS.index(field)]
        self._execute('UPDATE items SET "{f}" = ?, updated_at = ? WHERE id = ?'
                      .format(f=field), (v, now_str(), rid))

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
        cur = self._execute(
            'UPDATE items SET %s WHERE id IN (%s) AND deleted_at IS NULL'
            % (", ".join(sets), ph), tuple(vals) + tuple(ids))
        return cur.rowcount

    def set_listed(self, ids, listed):
        ids = list(ids)
        if not ids:
            return 0
        ph = ", ".join(["?"] * len(ids))
        cur = self._execute('UPDATE items SET "listed" = ?, updated_at = ? WHERE id IN ({ph})'
                            .format(ph=ph), (1 if listed else 0, now_str()) + tuple(ids))
        return cur.rowcount

    def delete_ids(self, ids, soft=True):
        """删除记录。默认软删除（进回收站，可恢复）；soft=False 时物理删除。"""
        ids = list(ids)
        if not ids:
            return 0
        ph = ", ".join(["?"] * len(ids))
        ts = now_str()
        if soft:
            cur = self._execute(
                'UPDATE items SET "deleted_at" = ?, "updated_at" = ? '
                'WHERE id IN ({ph}) AND deleted_at IS NULL'.format(ph=ph),
                (ts, ts) + tuple(ids))
        else:
            cur = self._execute(
                "DELETE FROM items WHERE id IN ({ph}) AND deleted_at IS NOT NULL".format(ph=ph),
                tuple(ids))
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
        cur = self._execute(
            'UPDATE items SET "deleted_at" = NULL, "updated_at" = ? '
            'WHERE id IN ({ph}) AND deleted_at IS NOT NULL'.format(ph=ph),
            (now_str(),) + tuple(ids))
        return cur.rowcount

    def purge_ids(self, ids):
        """彻底删除（仅限回收站里的记录，不可恢复）。"""
        ids = list(ids)
        if not ids:
            return 0
        ph = ", ".join(["?"] * len(ids))
        cur = self._execute(
            "DELETE FROM items WHERE id IN ({ph}) AND deleted_at IS NOT NULL".format(ph=ph),
            tuple(ids))
        return cur.rowcount

    def purge_all_deleted(self):
        cur = self._execute("DELETE FROM items WHERE deleted_at IS NOT NULL")
        return cur.rowcount

    def reset_code_seq(self):
        """清除编号计数器，让下一次导入从 WL-00001 重新开始。"""
        self._execute("DELETE FROM meta WHERE k = ?", (CODE_SEQ_KEY,))

    # ---------------------------------------------------------------- 出售
    def add_sale(self, item_id, qty, price, buyer="", sale_date="", remark="",
                 out_type=OUT_TYPE_SALE, address=""):
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
                " price, total, cost, buyer, address, sale_date, remark, out_type, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item_id, rec.get("code") or "", rec.get("brand") or "",
                 rec.get("category") or "", rec.get("model") or "", rec.get("shelf") or "",
                 qty, price, round(price * qty, 2), round(unit_cost, 4),
                 buyer or "" if is_sale else "",
                 (address or "").strip() if is_sale else "",
                 date, remark or "", out_type, now))
            self.conn.execute(
                'UPDATE items SET "qty" = ?, "sold_out" = ?, "updated_at" = ? WHERE id = ?',
                (left, 1 if left <= 0 else 0, now, item_id))
            self.conn.commit()
        code = rec.get("code") or ""
        if is_sale:
            return True, "已登记出售 %s：%d 件，合计 %.2f 元" % (code, qty, price * qty)
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
                " created_at) VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, brand, (category or "").strip(), model, (shelf or "").strip(),
                 qty, price, total, round(cost, 4), (buyer or "").strip(),
                 (address or "").strip(), date, (remark or "").strip(),
                 OUT_TYPE_SALE, now_str()))
            self.conn.commit()
        name = code or model or brand
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

    @staticmethod
    def out_totals(rows):
        """非销售出库合计：笔数 / 件数 / 成本价值（按成本估算的库存减少）。

        by_type 为 {类型: 件数}，用于页面上的类型分布。
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
        if purge_sales:
            self._execute("DELETE FROM sales")
            self._execute("DELETE FROM purchases")
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
