"""SQLite database — nơi Worker ghi RAW data và AI Agent đọc để phân tích.

Dùng sqlite3 chuẩn (không thêm dependency). File db: backend/hub_data.db
"""
from __future__ import annotations
import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

# Đổi tên từ `data.db` sang `hub_data.db`: file này nằm chung thư mục `backend/` với
# nhiều kho khác của Research SPY, nên một cái tên chung chung là mời gọi nhầm lẫn.
# Nó bị gitignore — dựng lại được từ `hub/data/snapshot/dataset.zip`.
DB_PATH = Path(os.environ.get("HUB_DB_PATH", str(Path(__file__).parent.parent / "hub_data.db")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_listings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,
    keyword     TEXT,
    title       TEXT,
    price       REAL,
    currency    TEXT,
    favorites   INTEGER,     -- lượt thích/quan tâm (best view)
    reviews     INTEGER,     -- số review (proxy best-seller)
    est_sales   INTEGER,     -- ước lượng số bán
    rank        INTEGER,     -- thứ hạng trong kết quả (best seller list)
    seller      TEXT,        -- shop/seller (đếm số shop bán keyword)
    url         TEXT,
    tags        TEXT,
    raw_json    TEXT,
    crawled_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_platform ON raw_listings(platform);
CREATE INDEX IF NOT EXISTS idx_raw_keyword ON raw_listings(keyword);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,
    keywords    TEXT,
    status      TEXT,        -- running | done | error
    n_items     INTEGER DEFAULT 0,
    backend     TEXT,        -- api | antidetect | playwright | seed
    note        TEXT,
    started_at  TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT,
    title       TEXT,
    content_md  TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS trends_cache (
    keyword     TEXT PRIMARY KEY,
    series_json TEXT,
    source      TEXT,        -- gtrends | pseudo
    updated_at  TEXT
);

-- Keyword TỰ TÌM ĐƯỢC từ related_queries của Google Trends (không hardcode).
-- Mỗi lần quét ghi 1 snapshot theo ngày -> so 2 ngày liền kề ra "tín hiệu hôm nay".
CREATE TABLE IF NOT EXISTS discovered_keywords (
    day            TEXT,        -- YYYY-MM-DD, để so snapshot giữa các ngày
    keyword        TEXT,
    seed           TEXT,        -- hạt giống nào tìm ra nó
    value          REAL,        -- lượng tìm tương đối (0-100)
    rising         INTEGER,     -- 1 = đang tăng
    change_percent REAL,
    updated_at     TEXT,
    PRIMARY KEY (day, keyword)
);

-- AI học hành vi: log thao tác người dùng để cá nhân hóa đề xuất
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT,        -- rnd | seller
    action      TEXT,        -- interest | pick | click | reject
    target_type TEXT,        -- collection | material | style | keyword | product
    target_value TEXT,
    ts          TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)
        try:                                    # migration: thêm cột seller cho DB cũ
            c.execute("ALTER TABLE raw_listings ADD COLUMN seller TEXT")
        except Exception:
            pass
        # migration: mốc thời gian của chuỗi Trends (labels + timeframe)
        for _sql in ("ALTER TABLE trends_cache ADD COLUMN labels_json TEXT",
                     "ALTER TABLE trends_cache ADD COLUMN timeframe TEXT"):
            try:
                c.execute(_sql)
            except Exception:
                pass
        # Khử trùng rồi tạo UNIQUE index (sàn, url, keyword) để upsert hoạt động.
        c.execute("""DELETE FROM raw_listings WHERE id NOT IN
                     (SELECT MAX(id) FROM raw_listings GROUP BY platform, url, keyword)""")
        c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_unique
                     ON raw_listings(platform, url, keyword)""")

        # listings_unified: UNIQUE index (day, platform, url, keyword) chống trùng.
        # Bảng do unify.py tạo (không có trong SCHEMA chính) nên có thể chưa tồn tại.
        try:
            c.execute("""DELETE FROM listings_unified WHERE id NOT IN
                         (SELECT MAX(id) FROM listings_unified
                          GROUP BY day, platform, url, keyword)""")
            c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_lu_unique
                         ON listings_unified(day, platform, url, keyword)""")
        except Exception:
            pass


# ---------------- crawl runs ----------------
def start_run(platform: str, keywords: list[str], backend: str) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO crawl_runs(platform, keywords, status, backend, started_at) VALUES(?,?,?,?,?)",
            (platform, ", ".join(keywords), "running", backend, _now()),
        )
        return cur.lastrowid


def finish_run(run_id: int, n_items: int, status: str = "done", note: str = "") -> None:
    with connect() as c:
        c.execute(
            "UPDATE crawl_runs SET status=?, n_items=?, note=?, finished_at=? WHERE id=?",
            (status, n_items, note, _now(), run_id),
        )


def reap_stale_runs(minutes: int = 30) -> int:
    """Đóng các run treo — process bị kill giữa chừng thì run kẹt 'running' mãi."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    with connect() as c:
        cur = c.execute(
            "UPDATE crawl_runs SET status='timeout', finished_at=?, "
            "note=COALESCE(note,'')||' [tự đóng: treo quá "
            + str(minutes) + " phút]' "
            "WHERE status='running' AND started_at < ?", (_now(), cutoff))
        return cur.rowcount


def list_runs(limit: int = 20) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ---------------- raw listings ----------------
def insert_listings(items: list[dict], platform: str) -> int:
    ts = _now()
    with connect() as c:
        for it in items:
            # UPSERT: cào lại cùng (sàn,url,keyword) -> cập nhật số liệu mới nhất, KHÔNG nhân đôi.
            c.execute(
                """INSERT INTO raw_listings
                   (platform, keyword, title, price, currency, favorites, reviews, est_sales, rank, seller, url, tags, raw_json, crawled_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(platform, url, keyword) DO UPDATE SET
                     title=excluded.title, price=excluded.price, currency=excluded.currency,
                     favorites=excluded.favorites, reviews=excluded.reviews, est_sales=excluded.est_sales,
                     rank=excluded.rank, seller=excluded.seller, tags=excluded.tags,
                     raw_json=excluded.raw_json, crawled_at=excluded.crawled_at""",
                (platform, it.get("keyword"), it.get("title"), it.get("price"), it.get("currency", "USD"),
                 it.get("favorites"), it.get("reviews"), it.get("est_sales"), it.get("rank"), it.get("seller"),
                 it.get("url"), json.dumps(it.get("tags", []), ensure_ascii=False),
                 json.dumps(it.get("raw", {}), ensure_ascii=False), ts),
            )
    return len(items)


def get_listings(platform: str | None = None, limit: int = 1000) -> list[dict]:
    with connect() as c:
        if platform:
            rows = c.execute("SELECT * FROM raw_listings WHERE platform=? ORDER BY id DESC LIMIT ?",
                             (platform, limit)).fetchall()
        else:
            # Cân bằng 2 sàn: chia đều hạn mức để sàn crawl sau (id lớn hơn)
            # không chiếm hết chỗ của sàn kia.
            plats = [r[0] for r in c.execute(
                "SELECT DISTINCT platform FROM raw_listings WHERE platform IS NOT NULL")]
            if len(plats) <= 1:
                rows = c.execute("SELECT * FROM raw_listings ORDER BY id DESC LIMIT ?",
                                 (limit,)).fetchall()
            else:
                share = max(1, limit // len(plats))
                rows = []
                for p in plats:
                    rows += c.execute(
                        "SELECT * FROM raw_listings WHERE platform=? ORDER BY id DESC LIMIT ?",
                        (p, share)).fetchall()
                # sàn nào ít hơn phần chia thì trả lại chỗ thừa cho sàn khác
                if len(rows) < limit:
                    got = {id(r) for r in rows}
                    for r in c.execute("SELECT * FROM raw_listings ORDER BY id DESC LIMIT ?",
                                       (limit * 2,)):
                        if len(rows) >= limit:
                            break
                        if id(r) not in got:
                            rows.append(r)
        return [dict(r) for r in rows]


def listings_by_keyword(keyword: str, limit: int = 200) -> list[dict]:
    """Listing của 1 keyword, cả 2 sàn. Khớp lỏng để bắt cả biến thể chữ hoa/thường
    và keyword dài hơn (vd "personalized ornament" khớp cả "ornament")."""
    kw = (keyword or "").strip().lower()
    if not kw:
        return []
    with connect() as c:
        rows = c.execute(
            """SELECT * FROM raw_listings
               WHERE LOWER(keyword)=? OR LOWER(keyword) LIKE ? OR LOWER(title) LIKE ?
               ORDER BY est_sales DESC NULLS LAST, id DESC LIMIT ?""",
            (kw, f"%{kw}%", f"%{kw}%", limit)).fetchall()
        return [dict(r) for r in rows]


def counts() -> dict:
    with connect() as c:
        total = c.execute("SELECT COUNT(*) n FROM raw_listings").fetchone()["n"]
        by_plat = c.execute("SELECT platform, COUNT(*) n FROM raw_listings GROUP BY platform").fetchall()
        return {"total": total, "by_platform": {r["platform"]: r["n"] for r in by_plat}}


def clear_listings(force: bool = False) -> None:
    """XOÁ TOÀN BỘ raw_listings. Mặc định từ chối nếu còn dữ liệu Etsy
    (Etsy đã khoá API, không crawl lại được); phải truyền `force=True`.
    """
    with connect() as c:
        n_etsy = c.execute(
            "SELECT COUNT(*) FROM raw_listings WHERE platform='etsy'").fetchone()[0]
        if n_etsy and not force:
            raise RuntimeError(
                f"TỪ CHỐI XOÁ: còn {n_etsy:,} listing Etsy không crawl lại được "
                "(Etsy đã khoá API). Xem docs/KHONG-XOA-DU-LIEU-ETSY.md. "
                "Nếu thật sự muốn xoá, gọi clear_listings(force=True)."
            )
        c.execute("DELETE FROM raw_listings")


# ---------------- trends cache ----------------
def save_discovered(rows: list[dict], day: str | None = None) -> int:
    """Ghi snapshot keyword tự tìm được. Upsert theo (day, keyword)."""
    from datetime import datetime, timezone
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = _now()
    n = 0
    with connect() as c:
        for r in rows:
            kw = (r.get("keyword") or "").strip().lower()
            if not kw:
                continue
            c.execute(
                """INSERT INTO discovered_keywords(day,keyword,seed,value,rising,change_percent,updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(day,keyword) DO UPDATE SET
                     change_percent=MAX(change_percent, excluded.change_percent),
                     value=excluded.value, rising=excluded.rising, updated_at=excluded.updated_at""",
                (day, kw, r.get("seed"), r.get("value"), 1 if r.get("rising") else 0,
                 r.get("change_percent"), now))
            n += 1
    return n


def list_discovered(day: str | None = None, limit: int = 100, rising_only: bool = False) -> list[dict]:
    """Đọc keyword đã tìm được, mới nhất trước, sắp theo % tăng."""
    where = "WHERE rising=1" if rising_only else ""
    if day:
        where += (" AND " if where else "WHERE ") + "day=?"
        args = (day, limit)
    else:
        args = (limit,)
    with connect() as c:
        rows = c.execute(
            f"""SELECT * FROM discovered_keywords {where}
                ORDER BY day DESC, change_percent DESC LIMIT ?""", args).fetchall()
    return [dict(r) for r in rows]


def discovered_days() -> list[str]:
    """Các ngày đã có snapshot — để biết so được với ngày nào."""
    with connect() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT day FROM discovered_keywords ORDER BY day DESC").fetchall()]


def get_trend(keyword: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM trends_cache WHERE keyword=?", (keyword.lower(),)).fetchone()
        return dict(r) if r else None


def set_trend(keyword: str, series: list[float], source: str,
              labels: list[str] | None = None, timeframe: str = "today 12-m") -> None:
    with connect() as c:
        c.execute("""INSERT INTO trends_cache(keyword, series_json, source, updated_at,
                                              labels_json, timeframe)
                     VALUES(?,?,?,?,?,?)
                     ON CONFLICT(keyword) DO UPDATE SET series_json=excluded.series_json,
                     source=excluded.source, updated_at=excluded.updated_at,
                     labels_json=excluded.labels_json, timeframe=excluded.timeframe""",
                  (keyword.lower(), json.dumps(series), source, _now(),
                   json.dumps(labels or []), timeframe))


# ---------------- events (AI học hành vi) ----------------
def log_event(role: str, action: str, target_type: str, target_value: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO events(role, action, target_type, target_value, ts) VALUES(?,?,?,?,?)",
                  (role, action, target_type, target_value, _now()))


def get_events(limit: int = 1000) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def clear_events() -> None:
    with connect() as c:
        c.execute("DELETE FROM events")


# ---------------- reports ----------------
def save_report(kind: str, title: str, content_md: str) -> int:
    with connect() as c:
        cur = c.execute("INSERT INTO reports(kind, title, content_md, created_at) VALUES(?,?,?,?)",
                        (kind, title, content_md, _now()))
        return cur.lastrowid
