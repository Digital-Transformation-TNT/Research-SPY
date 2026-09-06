"""
Chuỗi Google Trends theo NGÀY và theo TUẦN → `trends_daily`. Nuôi phần ① của Hub.

HAI CHUỖI CHO MỖI TỪ KHOÁ, và đây là quyết định gốc của cả phần ①:

    grain='day'   `today 3-m`   ~90 điểm ngày   → L · M_ngắn · M_bền
    grain='week'  ~400 ngày     ~57 điểm tuần   → YoY

Vì sao không một chuỗi duy nhất: Google trả theo NGÀY khi khoảng thời gian đủ ngắn (≲ 9
tháng) và theo TUẦN khi dài hơn. Muốn có lát cùng kỳ năm ngoái thì khoảng phải > 12 tháng,
mà như thế thì mất độ phân giải ngày — không tính nổi M_ngắn (hôm nay so tuần trước).
Cắt hai truy vấn là cách duy nhất có cả hai.

VÀ VÌ THẾ TUYỆT ĐỐI KHÔNG TRỘN HAI GRAIN TRONG MỘT PHÉP TRỪ. Google chuẩn hoá 0–100 trong
nội bộ MỖI truy vấn, nên điểm ngày và điểm tuần của cùng một từ khoá nằm trên hai thước
khác nhau. `signal/trendsig.py` đọc mỗi chỉ số từ đúng một grain, không bắc cầu.

TUỲ CHỌN `anchor` — thứ làm cho `MIN_INDEX` có nghĩa. Không neo thì mỗi chuỗi được chuẩn
hoá theo đỉnh của CHÍNH nó: "chỉ số 60" của từ khoá A và "chỉ số 30" của B không so được,
nên một ngưỡng quy mô chung là vô nghĩa. Gửi kèm một từ khoá neo ổn định trong cùng truy
vấn thì mọi chuỗi quy về một thước, và lúc đó ngưỡng mới lọc đúng cái nó hứa.
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

    # Ghi kèm TÊN từ khoá neo, không chỉ ghi "anchored". Hai đợt cào neo vào hai từ khác
    # nhau là hai thước đo khác nhau y như neo-với-không-neo, nhưng nếu cả hai cùng mang
    # nhãn "anchored" thì bộ dò trộn thang không thấy gì — và cột `Chỉ số` lại trông như
    # so được với nhau. Đã suýt dính: 8 từ khoá neo vào "nồi cơm điện" nằm chung bảng với
    # một từ còn neo vào "điện thoại" từ đợt trước.
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
