"""
Đọc kho `hub_data.db` để xem bằng mắt. CHỈ ĐỌC — không hàm nào ở đây ghi gì.

Nuôi trang `/research/dbview/index.html`. Mục đích hẹp và cố ý giữ hẹp: trả lời câu "vòng cào
đêm qua thực sự thu được gì", không phải thay một trình duyệt SQLite đầy đủ.

BA CÂU HỎI TRANG NÀY PHẢI TRẢ LỜI, và chúng quyết định hình dạng của mọi hàm dưới đây:

  1. Hôm nay cào được bao nhiêu, so với hôm qua thì hơn hay kém?
  2. Ngành nào hỏng, hỏng vì gì?
  3. Dữ liệu một ngành cụ thể trông ra sao — có đúng là thứ dùng được không?

Câu 3 là câu quan trọng nhất và hay bị bỏ quên nhất. Một bảng đếm dòng nói "ngành này 100
dòng" trông y hệt nhau dù 100 dòng ấy là hàng thật hay là rác; phải mở ra nhìn mới biết. Nên
mọi hàm liệt kê ở đây đều có đường đi tiếp vào chi tiết.
"""

from __future__ import annotations

from . import db

#: Các bảng đáng đếm. Cố ý KHÔNG liệt kê hết bảng trong kho — `sqlite_sequence` và mấy bảng
#: nội bộ chỉ làm loãng màn hình.
_TABLES = ("shopee_categories", "listings_snapshot", "trends_rank", "crawl_log",
           "trends_daily", "raw_listings", "reports")


def overview() -> dict:
    """Đếm tổng, và nhật ký cào theo ngày — chỗ nhìn đầu tiên mỗi sáng."""
    with db.connect() as c:
        tables = []
        for t in _TABLES:
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                continue                      # bảng chưa tồn tại ở kho cũ — bỏ qua, đừng vỡ
            tables.append({"name": t, "rows": n})

        crawl = [dict(r) for r in c.execute(
            "SELECT day, source, market_code AS market,"
            "       SUM(status='ok') AS ok, SUM(status='empty') AS empty,"
            "       SUM(status='error') AS error, COALESCE(SUM(n_rows),0) AS rows"
            " FROM crawl_log GROUP BY day, source, market_code"
            " ORDER BY day DESC, source, market_code LIMIT 40")]

        snapshot = [dict(r) for r in c.execute(
            "SELECT day, market, COUNT(*) AS rows,"
            "       COUNT(DISTINCT category_code) AS categories,"
            "       COUNT(DISTINCT product_id) AS products"
            " FROM listings_snapshot WHERE platform='shopee'"
            " GROUP BY day, market ORDER BY day DESC LIMIT 20")]

        trends = [dict(r) for r in c.execute(
            "SELECT day, market_code AS market, COUNT(*) AS rows,"
            "       COUNT(DISTINCT category_code) AS categories"
            " FROM trends_rank GROUP BY day, market_code ORDER BY day DESC LIMIT 20")]

    return {"tables": tables, "crawl": crawl, "snapshot": snapshot, "trends": trends}


def shopee_categories(market: str, day: str) -> list[dict]:
    """
    Ngành đã cào trong ngày, kèm lý do nếu hỏng.

    LEFT JOIN từ `crawl_log` chứ không từ `listings_snapshot`: ngành hỏng KHÔNG có dòng
    snapshot nào, nên đi từ bảng kia thì chúng biến mất khỏi màn hình — đúng những ngành cần
    nhìn nhất lại là những ngành không hiện ra.
    """
    with db.connect() as c:
        rows = c.execute(
            "SELECT l.category_code, l.status, l.n_rows, l.note,"
            "       sc.main_name, sc.sub_name,"
            "       (SELECT COUNT(*) FROM listings_snapshot s"
            "         WHERE s.market=l.market_code AND s.day=l.day"
            "           AND s.category_code=l.category_code) AS in_db"
            " FROM crawl_log l"
            " LEFT JOIN shopee_categories sc"
            "        ON sc.market=l.market_code AND sc.sub_id=l.category_code"
            " WHERE l.source='shopee' AND l.market_code=? AND l.day=?"
            " ORDER BY l.status='ok' DESC, sc.main_name, sc.sub_name",
            (market.lower(), day)).fetchall()
    return [dict(r) for r in rows]


def shopee_products(market: str, day: str, category_code: str, limit: int = 100) -> list[dict]:
    """Sản phẩm của một ngành trong một ngày, theo đúng thứ hạng đã cào."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT rank, product_id, title, price, currency, sold_cumulative, sold_monthly,"
            "       rating, reviews, shop_id, url, image_url"
            " FROM listings_snapshot"
            " WHERE platform='shopee' AND market=? AND day=? AND category_code=?"
            " ORDER BY rank LIMIT ?",
            (market.lower(), day, str(category_code), int(limit))).fetchall()
    return [dict(r) for r in rows]


def trends_categories(market: str, day: str) -> list[dict]:
    """Danh mục Trends đã cào trong ngày. Cũng đi từ `crawl_log`, cùng lý do như trên."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT l.category_code, l.status, l.n_rows, l.note,"
            "       (SELECT COUNT(*) FROM trends_rank t"
            "         WHERE t.market_code=l.market_code AND t.day=l.day"
            "           AND t.category_code=l.category_code AND t.list_type='top') AS n_top,"
            "       (SELECT COUNT(*) FROM trends_rank t"
            "         WHERE t.market_code=l.market_code AND t.day=l.day"
            "           AND t.category_code=l.category_code AND t.list_type='rising') AS n_rising"
            " FROM crawl_log l"
            " WHERE l.source='trends' AND l.market_code=? AND l.day=?"
            " ORDER BY l.status='ok' DESC, CAST(l.category_code AS INTEGER)",
            (market.lower(), day)).fetchall()
    out = [dict(r) for r in rows]

    # Tên danh mục nằm trong bảng ánh xạ của crawler, không nằm trong kho — tra ở đây để màn
    # hình không phải hiện những con số trần như "986" mà không ai đọc được.
    from .ingestion.trends_rank import CATEGORY_MAP
    ten: dict[str, str] = {}
    shopee: dict[str, list[str]] = {}
    with db.connect() as c:
        nganh = {r["main_id"]: r["main_name"] for r in c.execute(
            "SELECT DISTINCT main_id, main_name FROM shopee_categories WHERE market=?",
            (market.lower(),))}
    for main_id, (cat_id, cat_name) in (CATEGORY_MAP.get(market.lower()) or {}).items():
        if cat_id is None:
            continue
        ten[str(cat_id)] = cat_name
        if main_id in nganh:
            shopee.setdefault(str(cat_id), []).append(nganh[main_id])
    for r in out:
        r["cat_name"] = ten.get(r["category_code"], "")
        r["shopee"] = shopee.get(r["category_code"], [])
    return out


def trends_keywords(market: str, day: str, category_code: str) -> dict:
    """Hai bảng của một danh mục, giữ nguyên thứ hạng — KHÔNG xếp lại theo gì khác."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT list_type, rank, keyword FROM trends_rank"
            " WHERE market_code=? AND day=? AND category_code=?"
            " ORDER BY list_type, rank",
            (market.lower(), day, str(category_code))).fetchall()
    out: dict[str, list] = {"top": [], "rising": []}
    for r in rows:
        out.setdefault(r["list_type"], []).append({"rank": r["rank"], "keyword": r["keyword"]})
    return out


def days() -> list[str]:
    """Những ngày đã có dữ liệu, mới trước — để màn hình mặc định mở đúng ngày gần nhất."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT DISTINCT day FROM crawl_log"
            " UNION SELECT DISTINCT day FROM listings_snapshot"
            " ORDER BY day DESC LIMIT 30").fetchall()
    return [r["day"] for r in rows]
