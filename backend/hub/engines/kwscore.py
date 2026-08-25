"""Chấm 9 chỉ số cho MỘT keyword từ dữ liệu thật (3 nhóm: năng lực sản xuất,
tài chính, thị trường).

Chỉ số nào không có nguồn thật thì `available=False`; tổng điểm chia lại theo
trọng số các chỉ số còn lại.
"""
from __future__ import annotations
import json
import statistics
from datetime import date, datetime, timezone

from .. import db
from ..store import store
from . import market

WEIGHTS = {
    "production_fit": 0.12, "turnaround": 0.06, "seasonality": 0.08, "personalization": 0.06,
    "revenue": 0.12, "margin": 0.10,
    "demand": 0.16, "growth": 0.16, "competition": 0.14,
}
GROUPS = {
    "production_fit": "I. Năng lực sản xuất", "turnaround": "I. Năng lực sản xuất",
    "seasonality": "I. Năng lực sản xuất", "personalization": "I. Năng lực sản xuất",
    "revenue": "II. Tài chính", "margin": "II. Tài chính",
    "demand": "III. Thị trường", "growth": "III. Thị trường", "competition": "III. Thị trường",
}
LABELS = {
    "production_fit": "Production Fit", "turnaround": "Turnaround Time",
    "seasonality": "Seasonality Fit", "personalization": "Personalization",
    "revenue": "Revenue Potential", "margin": "Profit Margin",
    "demand": "Market Demand", "growth": "Growth Rate", "competition": "Competition Level",
}
PROD_DAYS = {1: 3, 2: 5, 3: 7, 4: 10, 5: 14}
FEE = 0.095   # Etsy 6.5% + payment 3%


def _raw(r: dict) -> dict:
    try:
        return json.loads(r.get("raw_json") or "{}")
    except Exception:
        return {}


def _dim(key, score, src, note, ok=True):
    return {"key": key, "label": LABELS[key], "group": GROUPS[key],
            "weight": WEIGHTS[key], "score": round(score, 1) if ok else None,
            "src": src, "note": note, "available": ok}


def _clip(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def score(keyword: str) -> dict:
    rows = db.listings_by_keyword(keyword, 300)
    idx = market._pt_index()
    dims: list[dict] = []

    # ── map về product type Printway (dùng title bán chạy nhất)
    sold = [r for r in rows if market._sales(r) > 0]
    pt = None
    if sold:
        top = max(sold, key=market._sales)
        pt = market._match_pt(top.get("title") or "", idx)
    if not pt:
        for r in rows:
            pt = market._match_pt(r.get("title") or "", idx)
            if pt:
                break

    # ═══ NHÓM I ═══
    # `_econ == "unknown"`: có trong catalog nhưng chưa có số kinh tế -> không chấm.
    if pt and pt.get("_econ") == "unknown":
        dims.append(_dim("production_fit", 0, "—",
                         f"{pt['product_type']} có trong catalog nhưng chưa có số "
                         f"sản xuất (độ khó/giá vốn) — chưa chấm được", ok=False))
    elif pt:
        base = 85 if pt.get("capacity") == "in_house" else 55
        base -= (pt["production_difficulty"] - 1) * 5
        mh = pt.get("margin_high") or 0
        base += 8 if mh >= 0.55 else (-8 if mh < 0.40 else 0)
        cap = "in-house" if pt.get("capacity") == "in_house" else "đối tác"
        dims.append(_dim("production_fit", _clip(base), "catalog",
                         f"{pt['product_type']} · {cap} · độ khó {pt.get('production_difficulty')}/5"))
    else:
        dims.append(_dim("production_fit", 0, "—",
                         "Không map được về product type nào trong catalog Printway", ok=False))

    # Turnaround: SO SÁNH với lead time thật của đối thủ trên Etsy
    comp_days = [_raw(r).get("processing_max") for r in rows]
    comp_days = [d for d in comp_days if d]
    if pt and pt.get("_econ") != "unknown" and comp_days:
        med = statistics.median(comp_days)
        mine = PROD_DAYS.get(pt["production_difficulty"], 7) + \
            (2 if pt.get("capacity") != "in_house" else 0)
        # nhanh hơn trung vị đối thủ = điểm cao
        s = _clip(50 + (med - mine) * 8)
        cmp_txt = "nhanh hơn" if mine < med else ("chậm hơn" if mine > med else "ngang")
        dims.append(_dim("turnaround", s, "etsy+catalog",
                         f"Xưởng ~{mine} ngày · đối thủ trung vị {med:.0f} ngày ({cmp_txt}) · n={len(comp_days)}"))
    elif pt:
        mine = PROD_DAYS.get(pt["production_difficulty"], 7)
        dims.append(_dim("turnaround", _clip(100 - (mine - 2) * 5), "catalog",
                         f"Xưởng ~{mine} ngày (chưa có lead time đối thủ để so)"))
    else:
        dims.append(_dim("turnaround", 0, "—", "Chưa map được product type", ok=False))

    # Seasonality: từ mùa vụ nhận ra trong title
    occ = None
    for r in sold or rows:
        occ = market._match_occasion(r.get("title") or "")
        if occ:
            break
    m = market.PEAK_MONTH.get(occ or "", 0)
    if m:
        today = date.today()
        yr = today.year if m >= today.month else today.year + 1
        days = (date(yr, m, 15) - today).days
        if 40 <= days <= 100:
            s, note = 92.0, f"{occ} còn {days} ngày — CỬA SỔ VÀNG"
        elif days > 100:
            s, note = 58.0, f"{occ} còn {days} ngày — còn sớm"
        else:
            s, note = 38.0, f"{occ} còn {days} ngày — đã muộn để mở mới"
        dims.append(_dim("seasonality", s, "lịch mùa", note))
    else:
        dims.append(_dim("seasonality", 65.0, "suy luận",
                         "Không gắn mùa vụ cụ thể — bán được quanh năm"))

    # Personalization: seller TỰ KHAI, không đoán từ title
    pers = [_raw(r).get("is_personalizable") for r in rows]
    pers = [p for p in pers if p is not None]
    if pers:
        rate = sum(1 for p in pers if p) / len(pers)
        dims.append(_dim("personalization", _clip(30 + rate * 70), "etsy",
                         f"{rate*100:.0f}% listing cho cá nhân hóa (seller khai, n={len(pers)})"))
    else:
        dims.append(_dim("personalization", 0, "—",
                         "Chưa có dữ liệu is_personalizable", ok=False))

    # ═══ NHÓM II ═══
    rev = sum(market._sales(r) * market._price(r) for r in sold)
    units = sum(market._sales(r) for r in sold)
    prices = sorted([market._price(r) for r in sold if market._price(r) > 0])
    if sold and rev > 0:
        # log scale: $2k -> 0, $200k -> 100
        import math
        s = _clip((math.log(max(rev, 1)) - math.log(2000)) / (math.log(200000) - math.log(2000)) * 100)
        dims.append(_dim("revenue", s, "etsy+amazon",
                         f"${rev:,.0f}/30 ngày · {units:,} đơn · {len(sold)}/{len(rows)} listing có đơn"))
    else:
        dims.append(_dim("revenue", 0, "—", "Chưa có listing nào bán được", ok=False))

    if pt and prices:
        med_price = prices[len(prices) // 2]
        cost = pt.get("base_cost_usd") or 0
        ship = 2.0 if cost < 2 else (3.2 if cost < 5 else (4.5 if cost < 9 else 6.0))
        net = (med_price - cost - ship - med_price * FEE) / med_price if med_price else 0
        dims.append(_dim("margin", _clip((net - 0.20) / 0.45 * 100), "catalog+giá thật",
                         f"Giá trung vị ${med_price} − cost ${cost} − ship ${ship} − phí {FEE*100:.1f}% "
                         f"⇒ biên {net*100:.0f}%"))
    else:
        dims.append(_dim("margin", 0, "—", "Cần cả catalog và giá thị trường", ok=False))

    # ═══ NHÓM III ═══
    views = sum(_raw(r).get("views") or 0 for r in rows)
    favs = sum(r.get("favorites") or 0 for r in rows)
    if views or favs or units:
        import math
        raw_idx = views + 2 * favs + 5 * units
        s = _clip((math.log(max(raw_idx, 1)) - math.log(500)) / (math.log(500000) - math.log(500)) * 100)
        dims.append(_dim("demand", s, "etsy+amazon",
                         f"{views:,} lượt xem · {favs:,} lượt thích · {units:,} đơn"))
    else:
        dims.append(_dim("demand", 0, "—", "Chưa có dữ liệu cầu", ok=False))

    trow = db.get_trend(keyword)
    if trow:
        series = json.loads(trow["series_json"])
        if len(series) >= 6:
            prev = sum(series[-6:-3]) / 3
            last = sum(series[-3:]) / 3
            pct = ((last - prev) / prev * 100) if prev else 0
            dims.append(_dim("growth", _clip((pct + 15) / 70 * 100), "g-trends",
                             f"{pct:+.0f}% — Google Trends 3 tháng gần nhất"))
        else:
            dims.append(_dim("growth", 0, "—", "Chuỗi Trends quá ngắn", ok=False))
    else:
        dims.append(_dim("growth", 0, "—",
                         "Chưa có chuỗi Google Trends — chạy /api/trends/refresh", ok=False))

    shops = {r.get("seller") for r in sold if r.get("seller")}
    if sold:
        ages = []
        now = datetime.now(timezone.utc).timestamp()
        for r in sold:
            ts = _raw(r).get("created_ts")
            if ts:
                ages.append((now - ts) / 86400)
        med_age = statistics.median(ages) if ages else None
        # nhiều shop = phân mảnh = dễ chen; top listing càng già càng khó
        import math
        frag = _clip(math.log(max(len(shops), 1)) / math.log(60) * 100)
        if med_age is not None:
            fresh = _clip(100 - (med_age / 730) * 100)   # >2 năm -> 0
            s = frag * 0.55 + fresh * 0.45
            note = f"{len(shops)} shop có đơn · tuổi listing trung vị {med_age/30:.0f} tháng"
        else:
            s, note = frag, f"{len(shops)} shop có đơn (chưa có tuổi listing)"
        dims.append(_dim("competition", s, "etsy", note + " · điểm cao = còn thoáng"))
    else:
        dims.append(_dim("competition", 0, "—", "Chưa có listing có đơn để đo", ok=False))

    # ── tổng: CHIA LẠI theo trọng số các chỉ số chấm được
    ok = [d for d in dims if d["available"]]
    wsum = sum(d["weight"] for d in ok)
    total = round(sum(d["score"] * d["weight"] for d in ok) / wsum, 1) if wsum else 0.0

    groups: dict[str, dict] = {}
    for d in dims:
        g = groups.setdefault(d["group"], {"sum": 0.0, "w": 0.0, "n_ok": 0, "n": 0})
        g["n"] += 1
        if d["available"]:
            g["sum"] += d["score"] * d["weight"]
            g["w"] += d["weight"]
            g["n_ok"] += 1
    group_out = [{"name": k, "score": round(v["sum"] / v["w"], 1) if v["w"] else None,
                  "weight_pct": round(v["w"] * 100), "n_ok": v["n_ok"], "n": v["n"]}
                 for k, v in groups.items()]

    verdict = ("NÊN LÀM NGAY" if total >= 66 else
               "CÂN NHẮC" if total >= 50 else "KHÔNG NÊN")
    level = "go" if total >= 66 else ("hot" if total >= 50 else "stop")

    return {
        "keyword": keyword, "available": bool(ok),
        "total": total, "verdict": verdict, "level": level,
        "n_scored": len(ok), "n_total": len(dims),
        "coverage_note": (f"Tính trên {len(ok)}/9 chỉ số có dữ liệu thật"
                          + ("" if len(ok) == 9 else " — các chỉ số còn lại chưa đủ nguồn")),
        "product_type": (pt or {}).get("product_type"),
        "category": (pt or {}).get("category"),
        "n_listings": len(rows), "n_sold": len(sold),
        "groups": group_out, "dims": dims,
    }
