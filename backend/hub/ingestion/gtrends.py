"""Google Trends — chuỗi 12 điểm + cache DB.

Không lấy được thì trả rỗng + source="unavailable" (không bịa số). pytrends dùng
cho interest_over_time; phần khám phá keyword đi đường khác (xem discover.py).
"""
from __future__ import annotations
import json

from .. import db

# Khoảng thời gian Google Trends hỗ trợ. Mặc định 12 tháng.
RANGES = {
    "7d": "now 7-d", "1m": "today 1-m", "3m": "today 3-m",
    "12m": "today 12-m", "5y": "today 5-y",
}
DEFAULT_RANGE = "12m"


def _downsample(vals: list[float], n: int = 12) -> list[float]:
    """Gộp về n điểm bằng trung bình mỗi nhóm (giữ được đỉnh)."""
    if not vals:
        return []
    if len(vals) <= n:
        return [float(v) for v in vals]
    size = len(vals) / n
    out = []
    for i in range(n):
        lo, hi = int(i * size), max(int((i + 1) * size), int(i * size) + 1)
        chunk = vals[lo:hi]
        out.append(round(sum(chunk) / len(chunk), 1) if chunk else 0.0)
    return out


def fetch_series(keyword: str, rng: str = DEFAULT_RANGE) -> tuple[list[float], list[str], str]:
    """Fetch LIVE. Trả (series, labels, source). Lỗi -> ([], [], "unavailable")."""
    timeframe = RANGES.get(rng, RANGES[DEFAULT_RANGE])
    try:
        from pytrends.request import TrendReq
        py = TrendReq(hl="en-US", tz=0)
        py.build_payload([keyword], timeframe=timeframe)
        df = py.interest_over_time()
        if df is not None and not df.empty:
            vals = df[keyword].tolist()
            idx = [str(d.date()) for d in df.index]
            series = _downsample(vals)
            labels = _downsample_labels(idx)
            if series:
                return series, labels, "gtrends"
    except Exception:
        pass
    return [], [], "unavailable"


def _downsample_labels(idx: list[str], n: int = 12) -> list[str]:
    """Nhãn thời gian THẬT của từng điểm — để UI khỏi phải đoán ngày tháng."""
    if not idx:
        return []
    if len(idx) <= n:
        return idx
    size = len(idx) / n
    return [idx[min(int(i * size), len(idx) - 1)] for i in range(n)]


def cached_series(keyword: str) -> tuple[list[float], str]:
    """Đọc cache. Không có -> ([], "unavailable") — KHÔNG bịa số."""
    row = db.get_trend(keyword)
    if row:
        return json.loads(row["series_json"]), row["source"]
    return [], "unavailable"


def cached_meta(keyword: str) -> dict:
    """Mốc thời gian của chuỗi đã cache: labels, timeframe, lần cập nhật cuối."""
    row = db.get_trend(keyword)
    if not row:
        return {}
    k = row.keys()
    lab = []
    if "labels_json" in k and row["labels_json"]:
        try:
            lab = json.loads(row["labels_json"])
        except Exception:
            lab = []
    return {"labels": lab,
            "timeframe": (row["timeframe"] if "timeframe" in k and row["timeframe"]
                          else RANGES[DEFAULT_RANGE]),
            "updated_at": row["updated_at"]}


def refresh(keywords: list[str], rng: str = DEFAULT_RANGE) -> dict:
    """Fetch live từng keyword, lưu cache.

    Ưu tiên trang /explore qua Chrome thật; pytrends chỉ là dự phòng.
    """
    n_real, n_fail = 0, 0
    remain = list(keywords)

    # 1) đường chính: mở /explore bằng Chrome thật rồi bắt RPC multiline
    try:
        from . import trends_browser
        got = trends_browser.fetch_series_many(remain)
        for kw, series in got.items():
            if series:
                db.set_trend(kw, series, "gtrends")
                n_real += 1
        remain = [k for k in remain if k not in got]
    except Exception:
        pass

    # 2) dự phòng: pytrends (thường 429, giữ lại phòng khi Google mở lại)
    for kw in remain:
        series, _labels, source = fetch_series(kw, rng)
        if series:
            db.set_trend(kw, series, source)
            n_real += 1
        else:
            n_fail += 1
    return {"refreshed": len(keywords), "gtrends": n_real, "unavailable": n_fail}
