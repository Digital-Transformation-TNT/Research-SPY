"""Đọc/ghi ba bảng của Trend Signal Hub. Không tính toán gì ở đây."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .. import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ───────────────────────── trends_daily ─────────────────────────

def save_points(keyword: str, region: str, grain: str,
                points: list[tuple[str, float]], value_kind: str = "index") -> int:
    """
    Ghi chuỗi (ngày, giá trị) của một keyword.

    REPLACE chứ không IGNORE, ngược với `listings_snapshot` ngay bên dưới — và có lý do:
    Google chuẩn hoá lại TOÀN BỘ chuỗi mỗi lần truy vấn, nên điểm của ngày hôm kia lấy về
    hôm nay có thể mang giá trị khác điểm cùng ngày lấy về hôm qua. Giữ bản cũ là để lẫn
    hai mốc chuẩn hoá trong cùng một chuỗi, và mọi phép trừ sau đó đều lệch.
    """
    if not points:
        return 0
    rows = [(keyword, region, grain, d, float(v), value_kind, _now())
            for d, v in points if d and v is not None]
    with db.connect() as c:
        c.executemany(
            "INSERT OR REPLACE INTO trends_daily"
            " (keyword, region_code, grain, date, value, value_kind, crawled_at)"
            " VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


def series(keyword: str, region: str = "ALL", grain: str = "day") -> list[dict]:
    """Chuỗi của một keyword, CŨ TRƯỚC MỚI SAU — mọi công thức đều giả định thứ tự này."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT date, value, value_kind FROM trends_daily"
            " WHERE keyword=? AND region_code=? AND grain=? ORDER BY date ASC",
            (keyword, region, grain)).fetchall()
    return [dict(r) for r in rows]


def tracked_keywords(region: str = "ALL") -> list[str]:
    with db.connect() as c:
        rows = c.execute(
            "SELECT DISTINCT keyword FROM trends_daily WHERE region_code=? ORDER BY keyword",
            (region,)).fetchall()
    return [r["keyword"] for r in rows]


def tracked_regions() -> list[str]:
    with db.connect() as c:
        rows = c.execute(
            "SELECT region_code, COUNT(DISTINCT keyword) n FROM trends_daily"
            " GROUP BY region_code ORDER BY n DESC").fetchall()
    return [r["region_code"] for r in rows]


# ─────────────────────── listings_snapshot ───────────────────────

def save_snapshot(rows: list[dict]) -> int:
    """
    Ghi snapshot listing. IGNORE khi trùng (platform, market, product_id, day).

    IGNORE chứ không REPLACE — ngược hẳn với `save_points` ở trên. Cào lại lần hai trong
    cùng một ngày phải KHÔNG đổi được mốc đã ghi: giữ lần chụp đầu tiên thì khoảng cách
    giữa hai mốc luôn xấp xỉ 24 giờ, còn cho phép đè thì mốc trôi dần về cuối ngày và
    `bán/ngày` co giãn theo giờ chạy cron chứ không theo nhu cầu thật.
    """
    if not rows:
        return 0
    now = _now()
    vals = []
    for r in rows:
        sold = r.get("sold_cumulative")
        if sold is None or not r.get("product_id"):
            continue                      # thiếu hai trường này thì dòng vô dụng, bỏ sớm
        vals.append((
            r.get("platform"), r.get("market"), str(r["product_id"]), r.get("day"),
            int(sold), r.get("sold_type") or "cumulative", r.get("sold_monthly"),
            # ÉP None → '' CHO HAI CỘT NẰM TRONG KHOÁ CHÍNH. Chúng là NOT NULL, mà câu lệnh
            # dưới là `INSERT OR IGNORE` — và IGNORE nuốt luôn vi phạm NOT NULL, không chỉ vi
            # phạm trùng khoá. Để None lọt xuống thì mỗi dòng bị bỏ IM LẶNG và hàm vẫn trả về
            # số dòng "đã ghi". Vòng cào danh mục truyền `keyword=None` nên cả mẻ sẽ mất trắng.
            r.get("rank"), r.get("keyword") or "", r.get("category_code") or "",
            r.get("title"), r.get("price"), r.get("currency"), r.get("rating"),
            r.get("reviews"), r.get("favorites"), r.get("shop_id"),
            r.get("image_url"), r.get("url"), now))
    if not vals:
        return 0
    with db.connect() as c:
        c.executemany(
            "INSERT OR IGNORE INTO listings_snapshot"
            " (platform, market, product_id, day, sold_cumulative, sold_type, sold_monthly,"
            "  rank, keyword, category_code, title, price, currency, rating, reviews,"
            "  favorites, shop_id, image_url, url, crawled_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", vals)
    return len(vals)


def log_crawl(source: str, market: str, category_code: str, day: str,
              status: str, n_rows: int = 0, note: str | None = None,
              started_at: str | None = None) -> None:
    """
    Ghi một dòng nhật ký cào. GỌI CẢ KHI HỎNG — đó mới là lúc nó có giá trị.

    REPLACE chứ không IGNORE: chạy lại một ngành trong ngày là để CHỮA lần hỏng trước, nên
    kết quả mới phải đè lên. Ngược với `save_snapshot` ngay trên — bảng kia giữ mốc đầu tiên
    vì mốc là dữ liệu, còn ở đây "lần chạy gần nhất ra sao" mới là thứ cần biết.

    `status`: 'ok' (có dòng), 'empty' (chạy xong, sàn không trả gì), 'error' (không chạy được).
    Tách 'empty' khỏi 'error' vì hai cái dẫn tới hai việc khác nhau: một ngành thật sự hết
    hàng thì không có gì để sửa, còn máy-thợ rớt thì phải chạy lại.
    """
    with db.connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO crawl_log"
            " (source, market_code, category_code, day, status, n_rows, note,"
            "  started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (source, market, str(category_code), day, status, int(n_rows),
             (note or None) and str(note)[:500], started_at or _now(), _now()))


def crawl_health(source: str, market: str, day: str) -> dict:
    """
    Một ngày cào ra sao. Dùng để trả lời "hôm nay có tin được không" trước khi đọc số.

    Không có dòng nào trong `crawl_log` KHÁC HẲN với "cào xong, 0 kết quả" — nên `missing`
    đếm số ngành đang bật mà hôm đó không hề có nhật ký, tức chưa chạy tới.
    """
    with db.connect() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) n FROM crawl_log"
            " WHERE source=? AND market_code=? AND day=? GROUP BY status",
            (source, market, day)).fetchall()
        active = c.execute(
            "SELECT COUNT(*) FROM shopee_categories WHERE market=? AND active=1",
            (market,)).fetchone()[0]
    by = {r["status"]: r["n"] for r in rows}
    logged = sum(by.values())
    return {"day": day, "source": source, "market": market,
            "ok": by.get("ok", 0), "empty": by.get("empty", 0),
            "error": by.get("error", 0),
            "missing": max(active - logged, 0), "categories_active": active}


def partitions() -> list[dict]:
    """Các cặp (sàn, thị trường) đã có dữ liệu, kèm độ dày lịch sử."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT platform, market, COUNT(DISTINCT product_id) n_products,"
            "       COUNT(DISTINCT day) n_days, MIN(day) first_day, MAX(day) last_day"
            " FROM listings_snapshot GROUP BY platform, market"
            " ORDER BY n_products DESC").fetchall()
    return [dict(r) for r in rows]


def snapshot_rows(platform: str, market: str) -> list[dict]:
    """Mọi mốc của một partition, gom sẵn theo product rồi theo ngày."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT product_id, day, sold_cumulative, sold_type, sold_monthly, rank, title, price, currency,"
            "       url, image_url, shop_id, keyword, rating, reviews"
            " FROM listings_snapshot WHERE platform=? AND market=?"
            " ORDER BY product_id ASC, day ASC", (platform, market)).fetchall()
    return [dict(r) for r in rows]


# ───────────────────────── signal_config ─────────────────────────

def get_config(scope: str) -> dict:
    with db.connect() as c:
        row = c.execute("SELECT json FROM signal_config WHERE scope=?", (scope,)).fetchone()
    if not row:
        return {}
    try:
        out = json.loads(row["json"])
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def set_config(scope: str, cfg: dict) -> None:
    with db.connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO signal_config (scope, json, updated_at) VALUES (?,?,?)",
            (scope, json.dumps(cfg, ensure_ascii=False), _now()))
