"""
Chuỗi Google Trends theo NGÀY và theo TUẦN → `trends_daily`. Nuôi phần ① của Hub.

    grain='day'   `today 3-m`   ~90 điểm ngày   → L · M_ngắn · M_bền
    grain='week'  ~400 ngày     ~57 điểm tuần   → YoY

Hai truy vấn chứ không một: Google trả theo ngày khi khoảng đủ ngắn (≲ 9 tháng) và theo
tuần khi dài hơn, mà lát cùng kỳ năm ngoái thì cần > 12 tháng. Và vì mỗi truy vấn có mốc
chuẩn hoá 0–100 riêng, KHÔNG được trộn hai grain trong một phép trừ.

`anchor` là thứ làm cho `MIN_INDEX` có nghĩa: không neo thì mỗi chuỗi chuẩn hoá theo đỉnh
của chính nó và một ngưỡng chung là vô nghĩa. Gửi kèm từ khoá neo trong cùng truy vấn thì
mọi chuỗi về chung một thước.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..signal import store

#: Khoảng cho chuỗi ngày. 3 tháng = ~90 điểm, dư cho cửa sổ dài nhất (d[-55..-28]).
DAY_RANGE = "today 3-m"
#: Bao nhiêu ngày cho chuỗi tuần. Cần ≥ 56 tuần để có 4 tuần cùng kỳ 52 tuần trước.
WEEK_SPAN_DAYS = 400


def week_range(today: date | None = None) -> str:
    """Khoảng tuỳ chọn dạng `YYYY-MM-DD YYYY-MM-DD` — Google hiểu và trả theo tuần."""
    end = today or date.today()
    return f"{end - timedelta(days=WEEK_SPAN_DAYS)} {end}"


def _pytrends_points(keyword: str, timeframe: str, geo: str) -> list[tuple[str, float]]:
    """Dự phòng khi Chrome thật không mở được. Thường 429 — giữ lại vì rẻ."""
    try:
        from pytrends.request import TrendReq
        py = TrendReq(hl="en-US", tz=0)
        py.build_payload([keyword], timeframe=timeframe, geo=geo)
        df = py.interest_over_time()
        if df is None or df.empty:
            return []
        return [(str(d.date()), float(v)) for d, v in zip(df.index, df[keyword].tolist())]
    except Exception:
        return []


def _fetch(keywords: list[str], timeframe: str, geo: str,
           anchor: str | None) -> dict[str, list[tuple[str, float]]]:
    """Chrome thật trước, pytrends sau. Cùng thứ tự ưu tiên với `gtrends.refresh`."""
    got: dict[str, list[tuple[str, float]]] = {}
    try:
        from . import trends_browser
        got = trends_browser.fetch_points_many(keywords, geo, timeframe, anchor) or {}
    except Exception:
        got = {}
    for kw in keywords:
        if got.get(kw):
            continue
        # Neo không áp dụng được cho đường dự phòng: pytrends một từ khoá mỗi lượt, và
        # trộn một chuỗi đã neo với một chuỗi chưa neo trong cùng bảng là hỏng cả ngưỡng.
        if anchor:
            continue
        pts = _pytrends_points(kw, timeframe, geo)
        if pts:
            got[kw] = pts
    return got


def refresh(keywords: list[str], geo: str = "VN", region: str = "ALL",
            anchor: str | None = None) -> dict:
    """
    Lấy và lưu cả hai chuỗi cho từng từ khoá.

    Từ khoá nào không lấy được thì BỎ QUA, không ghi gì — chuỗi cũ trong DB vẫn còn nguyên
    và vẫn tính được (chỉ là cũ đi một ngày). Ghi đè bằng chuỗi rỗng mới là mất dữ liệu.
    """
    keywords = [k.strip() for k in keywords if k and k.strip()]
    if not keywords:
        return {"keywords": 0, "day_points": 0, "week_points": 0, "missing": []}

    # Ghi kèm TÊN từ khoá neo: hai đợt neo vào hai từ khác nhau là hai thước khác nhau, và
    # nếu cùng mang nhãn "anchored" thì bộ dò trộn thang không thấy gì.
    kind = f"anchored:{anchor}" if anchor else "index"
    day_pts = _fetch(keywords, DAY_RANGE, geo, anchor)
    week_pts = _fetch(keywords, week_range(), geo, anchor)

    n_day = n_week = 0
    for kw in keywords:
        if day_pts.get(kw):
            n_day += store.save_points(kw, region, "day", day_pts[kw], kind)
        if week_pts.get(kw):
            n_week += store.save_points(kw, region, "week", week_pts[kw], kind)

    missing = [k for k in keywords if not day_pts.get(k)]
    return {"keywords": len(keywords), "region": region, "geo": geo,
            "value_kind": kind, "anchor": anchor,
            "day_points": n_day, "week_points": n_week, "missing": missing}
