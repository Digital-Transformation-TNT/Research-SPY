"""Chuẩn hoá listing 2 sàn về một lược đồ chung (`listings_unified`) để query.

Ba nguyên tắc:
  1. Một khái niệm — một tên cột. Sàn nào thiếu thì NULL, không bịa.
  2. Mỗi số kèm nguồn: real | proxy | none.
  3. Chuẩn hoá đơn vị: doanh số về "đơn/30 ngày", giá về USD.

raw_listings vẫn là bản gốc; bảng này là lớp đọc.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

from .. import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings_unified (
    id            INTEGER PRIMARY KEY,   -- = raw_listings.id
    day           TEXT,                  -- ngày chuẩn hoá (snapshot)
    platform      TEXT,                  -- etsy | amazon
    keyword       TEXT,
    external_id   TEXT,                  -- listing_id (Etsy) | asin (Amazon)
    title         TEXT,
    url           TEXT,
    image_url     TEXT,

    -- ── TIỀN (đã chuẩn hoá về USD, đơn/30 ngày) ──
    price_usd     REAL,
    list_price    REAL,                  -- giá gạch, chỉ Amazon
    discount_pct  REAL,
    units_30d     INTEGER,               -- SỐ BÁN 30 ngày
    units_src     TEXT,                  -- real (Amazon bought) | proxy (Etsy favorites)
    revenue_30d   REAL,                  -- price × units

    -- ── QUAN TÂM ──
    views         INTEGER,               -- chỉ Etsy
    favorites     INTEGER,               -- chỉ Etsy
    rating        REAL,                  -- chỉ Amazon
    reviews       INTEGER,               -- chỉ Amazon
    engagement    REAL,                  -- favorites/views (Etsy) | reviews/units (Amazon)

    -- ── NGƯỜI BÁN ──
    shop_id       TEXT,
    shop_name     TEXT,
    shop_url      TEXT,

    -- ── SẢN PHẨM ──
    materials     TEXT,                  -- JSON list, chỉ Etsy
    personalizable INTEGER,              -- 1/0/NULL
    made_to_order INTEGER,               -- 1/0/NULL, chỉ Etsy
    has_variations INTEGER,
    stock_qty     INTEGER,
    lead_days_min INTEGER,               -- processing_min, chỉ Etsy
    lead_days_max INTEGER,

    -- ── THỊ TRƯỜNG ──
    rank_pos      INTEGER,               -- vị trí trong kết quả tìm
    sponsored     INTEGER,               -- 1 = quảng cáo, chỉ Amazon
    total_results INTEGER,               -- quy mô cạnh tranh, chỉ Amazon
    listed_at     TEXT,                  -- ngày đăng, chỉ Etsy
    age_days      INTEGER,
    taxonomy_id   TEXT,

    fetch_tier    TEXT,                  -- api | session | http
    crawled_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_lu_kw   ON listings_unified(keyword);
CREATE INDEX IF NOT EXISTS ix_lu_day  ON listings_unified(day);
CREATE INDEX IF NOT EXISTS ix_lu_shop ON listings_unified(shop_id);
-- Chống trùng THẬT. Không có dòng này thì `INSERT OR REPLACE` bên dưới vô tác
-- dụng (không có gì để "conflict") và bảng chỉ sạch nhờ DELETE toàn bảng.
-- Khoá dùng `url` chứ không dùng `external_id`: url phủ 100%, external_id rỗng
-- ~0.8% nên các dòng rỗng sẽ gom nhầm thành một nhóm trùng giả.
CREATE UNIQUE INDEX IF NOT EXISTS idx_lu_unique
  ON listings_unified(day, platform, url, keyword);
"""

# Trần chặn outlier — dùng chung với market.py
MAX_UNITS = 5000
MAX_PRICE = 500.0
ETSY_FAV_TO_SALES = 0.15   # Etsy KHÔNG trả sales, phải suy từ favorites


def _raw(r: dict) -> dict:
    try:
        return json.loads(r.get("raw_json") or "{}")
    except Exception:
        return {}


# Chuỗi không phải tên shop — badge, nhãn giá, nút bấm. Lọc ở tầng chuẩn hoá để
# cột `shop_name` luôn sạch dù nguồn ghi bẩn.
_NOT_A_SHOP = (
    "amazon's choice", "overall pick", "best seller", "sponsored", "prime",
    "limited time deal", "climate pledge", "sold by", "click to see",
    "see price", "add to cart", "buy now", "in stock", "out of stock",
    "free shipping", "coupon", "save ", "deal",
)


def _shop_display(name: str | None) -> str | None:
    """Tên shop cho cột chuẩn hoá `shop_name` — DÙNG CHO CẢ 2 SÀN.

    · Bỏ tiền tố kỹ thuật: `etsy_shop_18067333` -> `Shop 18067333`,
      `amazon_Mayvoro` -> `Mayvoro`.
    · Loại badge/nhãn giá bị bắt nhầm làm tên shop.
    · Không bịa tên: chưa biết thì trả None để báo cáo ghi "chưa có".
    """
    if not name:
        return None
    from ..ingestion.etsy_shops import display_name
    out = display_name(name)
    if not out or out == "—":
        return None
    low = out.lower()
    if any(b in low for b in _NOT_A_SHOP):
        return None
    if len(out) > 60:
        return None
    return out


def _row(r: dict, day: str) -> tuple:
    x = _raw(r)
    plat = r.get("platform")
    price = r.get("price") or 0
    price = price if 0 < price <= MAX_PRICE else None

    # ── ĐƠN BÁN: mỗi sàn một cách, nhưng ra CÙNG MỘT cột + ghi rõ nguồn.
    # Thứ tự ưu tiên: số THẬT trước, ước lượng sau.
    if plat == "amazon" and x.get("bought_past_month"):
        units, usrc = int(x["bought_past_month"]), "real"
    elif x.get("units_real") is not None:
        # Etsy: phân bổ transaction_sold_count THẬT của shop theo tỷ trọng
        # favorites. Mẫu số là số Etsy công bố, không phải hệ số đoán.
        units, usrc = min(int(x["units_real"]), MAX_UNITS), "real"
    elif plat == "etsy" and r.get("favorites"):
        units = min(int((r.get("favorites") or 0) * ETSY_FAV_TO_SALES), MAX_UNITS)
        usrc = "proxy"
    else:
        units, usrc = None, "none"

    revenue = (price * units) if (price and units) else None

    # ── TƯƠNG TÁC: Etsy fav/views, Amazon review/đơn — cùng ý nghĩa "được quan tâm"
    views = x.get("views")
    favs = r.get("favorites")
    engagement = None
    if plat == "etsy" and views:
        engagement = round((favs or 0) / views, 4)
    elif plat == "amazon" and units:
        engagement = round((r.get("reviews") or 0) / units, 4)

    # ── TUỔI LISTING
    listed_at, age = None, None
    ts = x.get("created_ts")
    if ts:
        d = datetime.fromtimestamp(ts, tz=timezone.utc)
        listed_at = d.strftime("%Y-%m-%d")
        age = int((datetime.now(timezone.utc) - d).days)

    lp = x.get("list_price")
    disc = (round((lp - price) / lp * 100, 1)
            if lp and price and lp > price else None)

    return (
        r.get("id"), day, plat, r.get("keyword"),
        str(x.get("listing_id") or x.get("asin") or ""),
        r.get("title"), r.get("url"), x.get("image"),
        price, lp, disc, units, usrc, revenue,
        views, favs,
        x.get("rating") or x.get("shop_rating"),
        r.get("reviews") or x.get("shop_reviews"),
        engagement,
        str(x.get("shop_id") or "") or r.get("seller"),
        # Tên shop chuẩn hoá — xem ingestion/etsy_shops.display_name.
        _shop_display(x.get("shop_name") or x.get("seller_name")
                      or x.get("brand") or r.get("seller")),
        x.get("shop_url"),
        json.dumps(x.get("materials") or [], ensure_ascii=False),
        (1 if x.get("is_personalizable") else (0 if x.get("is_personalizable") is False else None)),
        (1 if x.get("when_made") == "made_to_order" else None),
        (1 if x.get("has_variations") else (0 if x.get("has_variations") is False else None)),
        x.get("quantity"), x.get("processing_min"), x.get("processing_max"),
        r.get("rank"),
        (1 if x.get("sponsored") else (0 if "sponsored" in x else None)),
        x.get("total_results"), listed_at, age, str(x.get("taxonomy_id") or "") or None,
        x.get("fetch_tier") or ("api" if plat == "etsy" else "session"),
        r.get("crawled_at"),
    )


COLS = 37


def rebuild(limit: int = 100_000) -> dict:
    """Dựng lại toàn bộ bảng chuẩn hoá từ raw_listings."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = db.get_listings(limit=limit)
    with db.connect() as c:
        c.executescript(SCHEMA)
        c.execute("DELETE FROM listings_unified")
        c.executemany(
            f"INSERT OR REPLACE INTO listings_unified VALUES ({','.join('?' * COLS)})",
            [_row(r, day) for r in rows])
    with db.connect() as c:
        n = c.execute("SELECT COUNT(*) FROM listings_unified").fetchone()[0]
        real = c.execute(
            "SELECT COUNT(*) FROM listings_unified WHERE units_src='real'").fetchone()[0]
        proxy = c.execute(
            "SELECT COUNT(*) FROM listings_unified WHERE units_src='proxy'").fetchone()[0]
    return {"rebuilt": n, "units_real": real, "units_proxy": proxy,
            "units_none": n - real - proxy, "day": day}


def coverage() -> dict:
    """Độ phủ từng cột theo sàn — AI/người dùng biết cột nào tin được."""
    fields = ["price_usd", "units_30d", "revenue_30d", "views", "favorites",
              "rating", "reviews", "image_url", "shop_url", "materials",
              "personalizable", "lead_days_max", "sponsored", "total_results",
              "age_days", "taxonomy_id"]
    out: dict = {}
    with db.connect() as c:
        for plat in ("etsy", "amazon"):
            tot = c.execute(
                "SELECT COUNT(*) FROM listings_unified WHERE platform=?", (plat,)
            ).fetchone()[0] or 1
            cols = {}
            for f in fields:
                n = c.execute(
                    f"SELECT COUNT(*) FROM listings_unified "
                    f"WHERE platform=? AND {f} IS NOT NULL AND {f} <> '' AND {f} <> '[]'",
                    (plat,)).fetchone()[0]
                cols[f] = {"n": n, "pct": round(n / tot * 100)}
            out[plat] = {"total": tot, "fields": cols}
    return out
