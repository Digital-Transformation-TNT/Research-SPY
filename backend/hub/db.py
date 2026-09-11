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

-- ══ TÍN HIỆU GOOGLE TRENDS — 1 bản ghi = 1 keyword × 1 vùng × 1 mốc thời gian ══
-- Thay cho `trends_cache` (keyword -> 12 điểm đã nén, không ngày tháng): công thức L /
-- M_ngắn / M_bền cần chuỗi 60 NGÀY LIÊN TỤC, YoY cần lát cùng kỳ năm ngoái. Nén 12 điểm
-- là làm mất đúng thứ mà cả bốn chỉ số ăn vào.
--
-- `grain` tách hai chuỗi ĐỘC LẬP của cùng một keyword, và đây là chỗ dễ hiểu sai nhất:
-- Google chuẩn hoá 0-100 TRONG NỘI BỘ MỘT TRUY VẤN. Chuỗi ngày (3 tháng) và chuỗi tuần
-- (12 tháng) là hai truy vấn khác nhau nên KHÔNG so trực tiếp được với nhau. Vì vậy
-- L/M_ngắn/M_bền đọc grain='day', còn YoY đọc grain='week' — mỗi chỉ số ở nguyên trong
-- một mốc chuẩn hoá. Trộn hai grain vào một phép trừ là ra số vô nghĩa.
CREATE TABLE IF NOT EXISTS trends_daily (
    keyword     TEXT NOT NULL,
    region_code TEXT NOT NULL DEFAULT 'ALL',   -- 'VN', 'VN-HN'… hoặc 'ALL' = toàn quốc
    grain       TEXT NOT NULL DEFAULT 'day',   -- day (3 tháng) | week (12 tháng, cho YoY)
    date        TEXT NOT NULL,                 -- YYYY-MM-DD, ngày THẬT của điểm dữ liệu
    value       REAL NOT NULL,
    value_kind  TEXT NOT NULL DEFAULT 'index', -- index = 0-100 | absolute = lượt/ngày thật
    crawled_at  TEXT,
    PRIMARY KEY (keyword, region_code, grain, date)
);
CREATE INDEX IF NOT EXISTS idx_td_kw ON trends_daily(keyword, region_code, grain);

-- ══ SNAPSHOT LISTING SÀN — 1 dòng = 1 listing × 1 NGÀY (append-only) ══
-- Khác `raw_listings` ở ba chỗ quyết định: có `product_id` native (bám đúng listing dù
-- seller đổi tên), có `sold_cumulative` (mọi % tăng đều là HIỆU của cột này giữa hai ngày),
-- và khoá chính chứa `day` nên cào lại trong ngày không đè mất mốc cũ.
--
-- `sold_type` là chốt an toàn, không phải cột thừa: cả Shopee/Taobao/1688 hiện đều trả số
-- LŨY KẾ. Ngày nào thêm một nguồn chỉ cho bán-theo-tháng, lớp tính nhìn cờ này là biết
-- ngay, thay vì lặng lẽ trừ hai đại lượng khác loại rồi cho ra một con số trông vẫn hợp lý.
-- KHOA CHINH CO CA `category_code` VA `keyword`, khong chi (san, nuoc, san_pham, ngay).
--
-- Mot san pham nam o HAI nganh thi la HAI dong voi hai thu hang khac nhau. Khoa cu chi co
-- (platform, market, product_id, day) nen dong thu hai bi `INSERT OR IGNORE` bo di — va
-- mat luon thu hang cua no o nganh kia. Do ngay 10/09/2026: nhat ky ghi 17.538 dong vn va
-- 19.125 dong ph, kho chi giu 17.140 va 18.778 — hut 745 dong (2%), im lang.
--
-- Duong cao theo TU KHOA cung can `keyword` trong khoa vi ly do y het: cung mot san pham
-- ra o hai tu khoa la hai lan quan sat khac nhau.
--
-- CA HAI COT PHAI NOT NULL. SQLite cho phep NULL trong khoa chinh va coi hai NULL la KHAC
-- nhau, nen de nullable thi khoa moi khong chan duoc gi ca — no chi thanh mot cai ten dai.
CREATE TABLE IF NOT EXISTS listings_snapshot (
    platform        TEXT NOT NULL,             -- shopee | taobao | 1688
    market          TEXT NOT NULL,             -- vn | ph | th | id | cn…
    product_id      TEXT NOT NULL,             -- shopid_itemid | item_id | offer_id
    day             TEXT NOT NULL,             -- YYYY-MM-DD
    sold_cumulative INTEGER NOT NULL,
    sold_type       TEXT NOT NULL DEFAULT 'cumulative',
    -- Bộ đếm "đã bán 30 ngày" mà Shopee hiển thị SẴN cạnh tổng đã bán. Có nó thì ngày đầu
    -- chạy đã dựng được cửa sổ 30 ngày: bán lũy kế 30 ngày trước = tổng − 30-ngày-gần-nhất.
    -- Xem `signal/top10.py`, chế độ ước lượng.
    sold_monthly    INTEGER,
    -- Thứ hạng trong danh sách bán chạy của NGÀY ĐÓ (1 = cao nhất). Nhánh 1 xếp bằng hạng
    -- chứ không bằng %-tăng: sản phẩm giữ hạng cao ổn định có mức tăng ~0 nhưng lại là sản
    -- phẩm mạnh nhất. Ngày không có mặt trong bảng = không có dòng, và lớp tính đọc đó
    -- thành 0 điểm. Xem `signal/top10.py`.
    rank            INTEGER,
    keyword         TEXT NOT NULL DEFAULT '',
    -- Ngành mà listing được nhìn thấy trong đó. `rank` chỉ có nghĩa KÈM cột này: hạng 1 của
    -- "Áo Ba Lỗ" và hạng 1 của "Đồ Chơi" là hai thang khác nhau. Nằm trong khoá chính nên
    -- một sản phẩm ở hai ngành là hai dòng, giữ được cả hai thứ hạng.
    category_code   TEXT NOT NULL DEFAULT '',
    title           TEXT,
    price           REAL,                      -- TIỀN GỐC của thị trường, không quy đổi
    currency        TEXT,
    rating          REAL,
    reviews         INTEGER,
    favorites       INTEGER,
    shop_id         TEXT,
    image_url       TEXT,
    url             TEXT,
    crawled_at      TEXT NOT NULL,
    PRIMARY KEY (platform, market, product_id, day, category_code, keyword)
);
CREATE INDEX IF NOT EXISTS idx_ls_part ON listings_snapshot(platform, market, day);

-- Ngưỡng người dùng chỉnh. `scope` = 'trends' hoặc 'shopee:vn' (mỗi partition một bộ, vì
-- quy mô mỗi thị trường một khác — xem spec Top 10 mục D).
CREATE TABLE IF NOT EXISTS signal_config (
    scope      TEXT PRIMARY KEY,
    json       TEXT NOT NULL,
    updated_at TEXT
);

-- ══ DANH MỤC SHOPEE — danh sách ngành hàng cần quét, nhập từ Google Sheet ══
-- Nguồn: sheet "Chốt danh mục sản phẩm" của chủ dự án, không phải cây `get_category_tree`
-- của Shopee. Hai thứ KHÁC NHAU và không được trộn: cây của sàn là toàn bộ ngành hàng đang
-- tồn tại, còn bảng này là tập con ĐÃ CHỌN để làm — có ngành bị bỏ hẳn khỏi phạm vi.
-- `hub/ingestion/categories.py` lấy cây của sàn; nó phục vụ việc khác, đừng thay bảng này.
--
-- `sub_id` là khoá thật. `main_id` đi kèm chỉ để dựng link `-cat.{main}.{sub}` và để nhóm
-- báo cáo; Shopee cho một ngành con nằm dưới đúng một ngành cha nên không sợ nhân bản.
CREATE TABLE IF NOT EXISTS shopee_categories (
    market       TEXT NOT NULL,             -- vn | ph
    main_id      TEXT NOT NULL,
    sub_id       TEXT NOT NULL,
    main_name    TEXT,                      -- tên hiển thị (VI với vn, EN với ph)
    main_name_en TEXT,                      -- chỉ vn mới có cột EN riêng trong sheet
    sub_name     TEXT,
    sub_name_en  TEXT,
    url          TEXT,
    sheet_row    INTEGER,                   -- cột "No." trong sheet, để đối chiếu khi lệch
    active       INTEGER NOT NULL DEFAULT 1,
    imported_at  TEXT NOT NULL,
    PRIMARY KEY (market, sub_id)
);
CREATE INDEX IF NOT EXISTS idx_sc_active ON shopee_categories(market, active);

-- ══ XẾP HẠNG GOOGLE TRENDS — 1 dòng = 1 từ khoá × 1 ngành × 1 ngày × 1 bảng ══
-- LƯU THỨ HẠNG, KHÔNG LƯU CHỈ SỐ 0–100. Google chuẩn hoá lại thang 0–100 theo từng lần hỏi
-- nên hai lần cào cách nhau một ngày cho ra hai thang khác nhau; trừ chúng cho nhau ra một
-- con số vô nghĩa mà trông vẫn hợp lý. Thứ hạng thì bền qua các lần chuẩn hoá.
--
-- `list_type` tách hai bảng của Trends và KHÔNG được trộn khi xếp hạng: 'top' là khối lượng,
-- 'rising' là phần trăm tăng trưởng. Một cụm +1.800% có thể chỉ nhảy từ 2 lên 36 lượt tìm.
-- Xem `signal/trendsig.py` và ghi chú `_primary_pool`.
CREATE TABLE IF NOT EXISTS trends_rank (
    market_code   TEXT NOT NULL,            -- vn | ph
    category_code TEXT NOT NULL,            -- mã Danh mục của Trends, KHÔNG phải catid Shopee
    day           TEXT NOT NULL,            -- YYYY-MM-DD
    list_type     TEXT NOT NULL,            -- top | rising
    keyword       TEXT NOT NULL,            -- giữ nguyên dấu tiếng Việt để nối được qua ngày
    rank          INTEGER NOT NULL,         -- 1 = cao nhất
    crawled_at    TEXT NOT NULL,
    PRIMARY KEY (market_code, category_code, day, list_type, keyword)
);
CREATE INDEX IF NOT EXISTS idx_tr_part ON trends_rank(market_code, category_code, day, list_type);

-- ══ NHẬT KÝ CÀO — phân biệt "rớt khỏi bảng" với "hôm đó cào lỗi" ══
-- BẢNG NÀY LÀ BẮT BUỘC, không phải tiện ích ghi log. Không có nó thì một từ khoá vắng mặt
-- hôm nay có hai cách đọc trái ngược nhau — mất hạng thật, hay chưa bao giờ cào được — và
-- lớp tính không có cách nào phân biệt. Ghi một dòng cho MỖI cặp (ngành, thị trường, ngày)
-- kể cả khi hỏng, `status` nói ra là hỏng.
--
-- Dùng chung cho cả hai nguồn: `source` = 'trends' hoặc 'shopee'.
CREATE TABLE IF NOT EXISTS crawl_log (
    source        TEXT NOT NULL,            -- trends | shopee
    market_code   TEXT NOT NULL,
    category_code TEXT NOT NULL,
    day           TEXT NOT NULL,
    status        TEXT NOT NULL,            -- ok | empty | error
    n_rows        INTEGER NOT NULL DEFAULT 0,
    note          TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    PRIMARY KEY (source, market_code, category_code, day)
);

-- ══ NGÀNH HÀNG CỦA SÀN KHÔNG-PHẢI-SHOPEE ══
-- Shopee có `shopee_categories` riêng vì nó mang mã số hai tầng và link của sheet. Các sàn
-- khác không có hình dạng đó: ngành hàng 1688 CHÍNH LÀ một cụm từ khoá tiếng Trung, nên `code`
-- ở đây vừa là mã vừa là thứ ném thẳng vào ô tìm kiếm. Đừng ép chúng vào một bảng chung với
-- Shopee — hai thứ chỉ giống nhau ở cái tên "danh mục".
CREATE TABLE IF NOT EXISTS crawl_categories (
    platform    TEXT NOT NULL,             -- 1688 | taobao
    market      TEXT NOT NULL,             -- cn
    code        TEXT NOT NULL,             -- với 1688: chính là từ khoá tiếng Trung
    name        TEXT,
    parent_code TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (platform, market, code)
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
        # migration: mốc thời gian của chuỗi Trends (labels + timeframe), và bộ đếm 30 ngày
        for _sql in ("ALTER TABLE trends_cache ADD COLUMN labels_json TEXT",
                     "ALTER TABLE trends_cache ADD COLUMN timeframe TEXT",
                     "ALTER TABLE listings_snapshot ADD COLUMN sold_monthly INTEGER",
                     "ALTER TABLE listings_snapshot ADD COLUMN rank INTEGER",
                     # Ngành hàng mà listing được nhìn thấy trong đó. `rank` chỉ có nghĩa
                     # KÈM cột này: hạng 1 của "Áo Ba Lỗ" và hạng 1 của "Đồ Chơi" là hai
                     # thang khác nhau, gộp lại thành một bảng xếp hạng là sai.
                     "ALTER TABLE listings_snapshot ADD COLUMN category_code TEXT"):
            try:
                c.execute(_sql)
            except Exception:
                pass
        _migrate_snapshot_pk(c)

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


def _migrate_snapshot_pk(c) -> None:
    """
    Dựng lại `listings_snapshot` khi kho còn dùng khoá chính cũ.

    KHÔNG CỨU ĐƯỢC DÒNG ĐÃ MẤT. Những dòng bị `INSERT OR IGNORE` bỏ đi ở các lần cào trước
    không còn ở đâu cả — migration này chỉ làm cho các lần cào SAU không mất nữa.

    Chép sang bảng mới rồi đổi tên, không `ALTER TABLE`: SQLite không sửa được khoá chính tại
    chỗ. `COALESCE(...,'')` vì hai cột mới phải NOT NULL, còn dòng cũ thì đang để NULL.
    """
    row = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='listings_snapshot'"
    ).fetchone()
    if not row or not row[0]:
        return                                   # bảng chưa tồn tại — SCHEMA vừa tạo bản mới
    if "category_code, keyword)" in row[0]:
        return                                   # đã là khoá mới, không làm gì

    cot = [r[1] for r in c.execute("PRAGMA table_info(listings_snapshot)")]
    if "category_code" not in cot:
        return                                   # kho quá cũ, để `ALTER TABLE` ở trên lo trước

    chung = [x for x in cot if x not in ("category_code", "keyword")]
    chon = ", ".join(chung) + ", COALESCE(category_code,''), COALESCE(keyword,'')"
    dich = ", ".join(chung) + ", category_code, keyword"

    c.execute("DROP TABLE IF EXISTS listings_snapshot__moi")
    c.executescript(SCHEMA.split("CREATE TABLE IF NOT EXISTS listings_snapshot (")[1]
                    .split(");")[0]
                    .join(["CREATE TABLE listings_snapshot__moi (", ");"]))
    c.execute(f"INSERT INTO listings_snapshot__moi ({dich})"
              f" SELECT {chon} FROM listings_snapshot")
    c.execute("DROP TABLE listings_snapshot")
    c.execute("ALTER TABLE listings_snapshot__moi RENAME TO listings_snapshot")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ls_part"
              " ON listings_snapshot(platform, market, day)")
