"""Google Trends batch — query hàng loạt keyword của ngành POD.

Chia lô ≤5 keyword (giới hạn pytrends), dùng keyword anchor có mặt ở mọi lô để
hiệu chỉnh chỉ số tương đối 0-100 về cùng thang, có giãn nhịp + retry backoff.

    kws = expand_keywords(niches=["pet lovers"], products=["ornament","mug"])
    result = fetch_many(kws, anchor="christmas gift")
    # result[kw] = {"series": [...12 số...], "growth_pct": 42.1, "yoy": 18.3, ...}
"""
from __future__ import annotations

import io
import time
import random
from typing import Iterable

BATCH = 5                 # giới hạn cứng của Google Trends
SLEEP_MIN, SLEEP_MAX = 2.0, 4.5   # giãn nhịp giữa các lô
MAX_RETRY = 3


# ──────────────────────────────────────────────────────────────
# 1. SINH KEYWORD TỪ TAXONOMY
# ──────────────────────────────────────────────────────────────
MODIFIERS = ["personalized", "custom", "monogrammed", "engraved"]


def expand_keywords(niches: Iterable[str],
                    products: Iterable[str],
                    occasions: Iterable[str] | None = None,
                    modifiers: Iterable[str] | None = None,
                    max_out: int = 2000) -> list[str]:
    """Sinh tổ hợp keyword niches × products × modifiers (+ occasions nếu có)."""
    mods = list(modifiers) if modifiers else MODIFIERS
    occs = list(occasions) if occasions else [""]
    out, seen = [], set()
    for occ in occs:
        for n in niches:
            for p in products:
                for m in mods:
                    kw = " ".join(x for x in (m, n, p, occ) if x).lower().strip()
                    kw = " ".join(kw.split())
                    if kw and kw not in seen:
                        seen.add(kw)
                        out.append(kw)
                        if len(out) >= max_out:
                            return out
    return out


# ──────────────────────────────────────────────────────────────
# 2. GỌI GOOGLE TRENDS THEO LÔ
# ──────────────────────────────────────────────────────────────
def _client():
    from pytrends.request import TrendReq
    return TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)


def _one_batch(py, kws: list[str], timeframe: str, geo: str) -> dict[str, list[float]]:
    """Gọi 1 lô ≤5 keyword. Trả {kw: [chuỗi số]}."""
    for attempt in range(MAX_RETRY):
        try:
            py.build_payload(kws, timeframe=timeframe, geo=geo)
            df = py.interest_over_time()
            if df is None or df.empty:
                return {k: [] for k in kws}
            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])
            return {k: [float(v) for v in df[k].tolist()] for k in kws if k in df.columns}
        except Exception as e:  # noqa
            if attempt == MAX_RETRY - 1:
                return {k: [] for k in kws}
            time.sleep((attempt + 1) * 5 + random.uniform(0, 2))
    return {k: [] for k in kws}


def fetch_many(keywords: list[str],
               anchor: str | None = None,
               timeframe: str = "today 12-m",
               geo: str = "US",
               points: int = 12) -> dict[str, dict]:
    """Query hàng loạt keyword, hiệu chỉnh về cùng thang bằng anchor.

    anchor: keyword mỏ neo có mặt ở mọi lô. Nên chọn từ phổ biến, ổn định
            (vd "christmas gift"). Nhờ nó, điểm giữa các lô so sánh được.
    """
    kws = [k for k in dict.fromkeys(keywords) if k]     # bỏ trùng, giữ thứ tự
    if not kws:
        return {}

    py = _client()
    per_batch = BATCH - 1 if anchor else BATCH
    raw: dict[str, list[float]] = {}
    anchor_levels: list[float] = []

    for i in range(0, len(kws), per_batch):
        chunk = kws[i:i + per_batch]
        payload = ([anchor] + chunk) if anchor else chunk
        got = _one_batch(py, payload, timeframe, geo)

        if anchor:
            a = got.get(anchor) or []
            a_mean = (sum(a) / len(a)) if a else 0.0
            anchor_levels.append(a_mean)
            # hệ số hiệu chỉnh: đưa mọi lô về mức anchor của lô đầu
            base = anchor_levels[0] or a_mean or 1.0
            factor = (base / a_mean) if a_mean else 1.0
            for k in chunk:
                raw[k] = [v * factor for v in (got.get(k) or [])]
        else:
            for k in chunk:
                raw[k] = got.get(k) or []

        if i + per_batch < len(kws):
            time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

    return {k: _summarize(v, points) for k, v in raw.items()}


# ──────────────────────────────────────────────────────────────
# 3. TÓM TẮT THÀNH CHỈ SỐ DÙNG ĐƯỢC
# ──────────────────────────────────────────────────────────────
def _downsample(vals: list[float], n: int) -> list[float]:
    if not vals:
        return []
    if len(vals) <= n:
        return [round(v, 1) for v in vals]
    size = len(vals) / n
    out = []
    for i in range(n):
        lo, hi = int(i * size), max(int(i * size) + 1, int((i + 1) * size))
        seg = vals[lo:hi] or [vals[min(lo, len(vals) - 1)]]
        out.append(round(sum(seg) / len(seg), 1))
    return out


def _summarize(vals: list[float], points: int) -> dict:
    """Từ chuỗi thô → các chỉ số R&D thực sự dùng."""
    if not vals:
        return {"series": [], "growth_pct": None, "yoy": None,
                "peak_idx": None, "level": None, "has_data": False}

    series = _downsample(vals, points)
    n = len(series)

    # tăng trưởng: 1/4 cuối so với 1/4 liền trước
    q = max(1, n // 4)
    last = sum(series[-q:]) / q
    prev = sum(series[-2 * q:-q]) / q if n >= 2 * q else last
    growth = round((last - prev) / prev * 100, 1) if prev else 0.0

    # so cùng kỳ năm trước: nửa cuối vs nửa đầu (chuỗi 12 tháng)
    h = n // 2
    yoy = None
    if h >= 2:
        a = sum(series[:h]) / h
        b = sum(series[h:]) / (n - h)
        yoy = round((b - a) / a * 100, 1) if a else None

    return {
        "series": series,
        "growth_pct": growth,
        "yoy": yoy,
        "peak_idx": series.index(max(series)),
        "level": round(last, 1),          # mức hiện tại (đã hiệu chỉnh anchor)
        "has_data": True,
    }


# ──────────────────────────────────────────────────────────────
# 4. TRUY VẤN LIÊN QUAN (top + rising) — miễn phí, rất đáng lấy
# ──────────────────────────────────────────────────────────────
def related(keyword: str, timeframe: str = "today 12-m", geo: str = "US") -> dict:
    """Trả {"top":[{q,value}], "rising":[{q,value,breakout}]}.

    'rising': keyword tăng >900% được Google đánh dấu Breakout.
    """
    try:
        py = _client()
        py.build_payload([keyword], timeframe=timeframe, geo=geo)
        rq = py.related_queries().get(keyword) or {}
        def pack(df, rising=False):
            if df is None or df.empty:
                return []
            out = []
            for _, r in df.head(10).iterrows():
                v = r["value"]
                out.append({"q": r["query"],
                            "value": v,
                            "breakout": bool(rising and (v == "Breakout" or
                                            (isinstance(v, (int, float)) and v >= 900)))})
            return out
        return {"top": pack(rq.get("top")), "rising": pack(rq.get("rising"), True)}
    except Exception:
        return {"top": [], "rising": []}


# ──────────────────────────────────────────────────────────────
# 5. LỌC 2 BƯỚC — tiết kiệm chi phí crawl sâu
# ──────────────────────────────────────────────────────────────
def screen(keywords: list[str],
           min_level: float = 8.0,
           min_growth: float = -5.0,
           anchor: str | None = "christmas gift") -> list[dict]:
    """Chạy Trends trên toàn bộ keyword, giữ lại cái đáng crawl sâu trước khi tốn request Etsy/Amazon."""
    data = fetch_many(keywords, anchor=anchor)
    keep = []
    for kw, d in data.items():
        if not d["has_data"]:
            continue
        if d["level"] is not None and d["level"] >= min_level \
           and (d["growth_pct"] or 0) >= min_growth:
            keep.append({"keyword": kw, **d})
    keep.sort(key=lambda x: (x["growth_pct"] or 0) * 0.6 + (x["level"] or 0) * 0.4,
              reverse=True)
    return keep


# ──────────────────────────────────────────────────────────────
# 6. DỰ PHÒNG KHI pytrends BỊ 429
# ──────────────────────────────────────────────────────────────
# A. Đổi IP mỗi vài request qua proxy (requests_args={"proxies": {...}}).
# B. Tải CSV thủ công từ trends.google.com rồi nạp qua load_csv().
# C. Dịch vụ có phí (SerpApi / DataForSEO) cho production.


def load_csv(path: str, keyword: str | None = None, points: int = 12) -> dict:
    """Nạp file CSV tải thủ công từ trends.google.com.

    File có dạng:
        Category: All categories
        Week,personalized ornament: (United States)
        2025-08-24,42
        ...
    """
    import csv as _csv
    rows, name = [], keyword
    with io.open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.lower().startswith("category"):
                continue
            parts = next(_csv.reader([line]))
            if len(parts) < 2:
                continue
            if parts[0].lower() in ("week", "day", "month", "time"):
                if not name:
                    name = parts[1].split(":")[0].strip()
                continue
            try:
                rows.append(float(str(parts[1]).replace("<1", "0.5")))
            except ValueError:
                continue
    return {"keyword": name, **_summarize(rows, points)}


def load_csv_dir(folder: str, points: int = 12) -> dict[str, dict]:
    """Nạp cả thư mục CSV đã tải. Trả {keyword: {series, growth_pct, ...}}."""
    import os
    out = {}
    for fn in os.listdir(folder):
        if not fn.lower().endswith(".csv"):
            continue
        try:
            d = load_csv(os.path.join(folder, fn))
            if d.get("keyword"):
                out[d["keyword"]] = d
        except Exception:
            continue
    return out


if __name__ == "__main__":
    # chạy thử: python -m app.ingestion.gtrends_batch
    kws = ["personalized christmas ornament", "custom photo mug",
           "pet memorial ornament", "baby first christmas ornament",
           "engraved cutting board", "custom neon sign"]
    print(f"Query {len(kws)} keyword…")
    res = fetch_many(kws, anchor="christmas gift")
    for k, v in res.items():
        if v["has_data"]:
            print(f"  {k:38s} level={v['level']:6.1f}  growth={v['growth_pct']:+6.1f}%  "
                  f"yoy={v['yoy']}")
        else:
            print(f"  {k:38s} (không có dữ liệu)")
