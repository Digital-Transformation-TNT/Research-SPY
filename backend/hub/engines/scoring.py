"""Opportunity Scoring Engine — 9 chỉ số / 3 nhóm (theo tri thức Printway).

Số ra từ công thức xác định (deterministic) — LLM không bịa số, chỉ viết lời giải thích.

Nhóm I  Năng lực sản xuất : Production Fit · Production Time · Seasonality Fit · Personalization
Nhóm II Tài chính         : Revenue Potential · Profit Margin
Nhóm III Thị trường       : Market Demand · Growth Rate · Competition Level
+ Production Fit gate (Recommend/Not) + Product Life Cycle stage
+ LUẬT BẮT BUỘC: growth âm ⇒ hạ điểm mạnh (bão hòa/suy thoái).
"""
from __future__ import annotations
import math
from datetime import datetime, timezone

from ..store import store
from ..schemas import ScoreDimension, ProductionFit, OpportunityScore, Lifecycle
from . import normalize as norm

GROUP_PROD = "Năng lực sản xuất"
GROUP_FIN = "Tài chính"
GROUP_MKT = "Thị trường & cạnh tranh"

# Trọng số 9 chỉ số (tổng = 1.0)
WEIGHTS = {
    "demand": 0.16, "growth": 0.16, "competition": 0.14,     # Nhóm III
    "revenue": 0.12, "profit_margin": 0.10,                   # Nhóm II
    "production_fit": 0.12, "seasonality": 0.08,
    "production_time": 0.06, "personalization": 0.06,         # Nhóm I
}

MONTH_NAMES = ["", "Th1", "Th2", "Th3", "Th4", "Th5", "Th6", "Th7", "Th8", "Th9", "Th10", "Th11", "Th12"]
PROD_DAYS = {1: 3, 2: 5, 3: 7, 4: 10, 5: 14}


def _log_norm(x: float, lo: float, hi: float) -> float:
    x = max(x, 1.0)
    v = (math.log(x) - math.log(lo)) / (math.log(hi) - math.log(lo))
    return round(max(0.0, min(1.0, v)) * 100, 1)


def _now_month() -> int:
    return datetime.now(timezone.utc).month


# ---------------- Nhóm III: Thị trường & cạnh tranh ----------------
def _demand(sig: dict) -> ScoreDimension:
    etsy, amz = sig.get("etsy", {}), sig.get("amazon", {})
    raw = (etsy.get("search_volume", 0) + amz.get("search_volume", 0)
           + 0.5 * etsy.get("favorites_30d", 0) + 3 * amz.get("est_monthly_units", 0))
    score = _log_norm(raw, 5000, 150000)
    return ScoreDimension(
        key="demand", label="Market Demand", group=GROUP_MKT, score=score, weight=WEIGHTS["demand"],
        evidence={"etsy_search": etsy.get("search_volume"), "amazon_search": amz.get("search_volume"),
                  "favorites_30d": etsy.get("favorites_30d"), "amazon_units_month": amz.get("est_monthly_units"),
                  "demand_index": raw},
        explanation=f"Tổng cầu (Etsy+Amazon search + favorites + đơn/tháng) ≈ {int(raw):,} → demand index {score}/100.",
    )


def _competition(sig: dict) -> ScoreDimension:
    etsy, amz = sig.get("etsy", {}), sig.get("amazon", {})
    listings = etsy.get("active_listings", 0) + amz.get("active_listings", 0)
    n_sellers = sig.get("n_sellers", 0)   # số shop THẬT trong top kết quả (phân mảnh = cạnh tranh)
    saturation = (listings + 2 * etsy.get("sellers_with_sales", 0)
                  + etsy.get("top_listing_reviews", 0) + 60 * n_sellers)
    sat_score = _log_norm(saturation, 300, 12000)
    score = round(100 - sat_score, 1)
    lvl = "thấp" if score >= 66 else ("trung bình" if score >= 40 else "cao")
    seller_note = f", {n_sellers} shop bán" if n_sellers else ""
    return ScoreDimension(
        key="competition", label="Competition Level", group=GROUP_MKT, score=score, weight=WEIGHTS["competition"],
        evidence={"total_active_listings": listings, "n_sellers": n_sellers,
                  "top_listing_reviews": etsy.get("top_listing_reviews"), "saturation_index": saturation},
        explanation=f"{listings:,} listing{seller_note}, top review {etsy.get('top_listing_reviews', 0)} → cạnh tranh {lvl} (điểm {score}/100, càng cao càng dễ chen chân).",
    )


def _growth_pct(series: list[float]) -> float:
    if not series:
        return 0.0
    prev = sum(series[-6:-3]) / 3 if len(series) >= 6 else sum(series[:3]) / 3
    last = sum(series[-3:]) / 3
    return round((last - prev) / prev * 100, 1) if prev else 0.0


def _growth(series: list[float]) -> ScoreDimension:
    # Không có chuỗi Trends -> không chấm, cho điểm trung tính 50.
    if not series:
        return ScoreDimension(
            key="growth", label="Growth Rate", group=GROUP_MKT, score=50.0,
            weight=WEIGHTS["growth"], evidence={"trend_series": [], "source": "unavailable"},
            explanation="Chưa có dữ liệu Google Trends cho từ khóa này → chưa chấm được tăng trưởng (tạm 50/100).",
        )
    pct = _growth_pct(series)
    score = round(max(0.0, min(100.0, (pct + 15) / 70 * 100)), 1)
    arrow = "↑" if pct > 3 else ("↓" if pct < -3 else "→")
    return ScoreDimension(
        key="growth", label="Growth Rate", group=GROUP_MKT, score=score, weight=WEIGHTS["growth"],
        evidence={"trend_series": series, "growth_pct_3m": pct, "source": "gtrends"},
        explanation=f"Google Trends 3 tháng gần nhất {arrow} {pct:+.0f}% so với quý trước → growth {score}/100.",
    )


# ---------------- Nhóm II: Tài chính ----------------
def _revenue(sig: dict, pt: dict | None) -> ScoreDimension:
    etsy, amz = sig.get("etsy", {}), sig.get("amazon", {})
    units = amz.get("est_monthly_units", 0) or int(etsy.get("favorites_30d", 0) * 0.15)
    price = amz.get("avg_price_usd") or etsy.get("avg_price_usd", 20)
    margin = ((pt or {}).get("margin_low", 0.35) + (pt or {}).get("margin_high", 0.5)) / 2
    monthly_profit = units * price * margin
    score = _log_norm(monthly_profit, 2000, 100000)
    return ScoreDimension(
        key="revenue", label="Revenue Potential", group=GROUP_FIN, score=score, weight=WEIGHTS["revenue"],
        evidence={"est_units_month": units, "avg_price_usd": price, "margin_mid": round(margin, 2),
                  "est_monthly_profit_usd": int(monthly_profit)},
        explanation=f"≈{units:,} đơn/tháng × ${price} × biên {int(margin*100)}% ⇒ lợi nhuận ~${int(monthly_profit):,}/tháng → revenue {score}/100.",
    )


def _profit_margin(pt: dict | None) -> ScoreDimension:
    low = (pt or {}).get("margin_low", 0.30)
    high = (pt or {}).get("margin_high", 0.45)
    mid = (low + high) / 2
    score = round(max(0.0, min(100.0, (mid - 0.20) / (0.65 - 0.20) * 100)), 1)
    return ScoreDimension(
        key="profit_margin", label="Profit Margin", group=GROUP_FIN, score=score, weight=WEIGHTS["profit_margin"],
        evidence={"margin_low": low, "margin_high": high, "margin_mid": round(mid, 2)},
        explanation=f"Biên lợi nhuận {int(low*100)}–{int(high*100)}% (= Giá bán − (COGS + Shipping + Phí sàn)) → margin {score}/100.",
    )


# ---------------- Nhóm I: Năng lực sản xuất ----------------
def _production_fit_dim(pt: dict | None) -> ScoreDimension:
    if not pt:
        return ScoreDimension(key="production_fit", label="Production Fit", group=GROUP_PROD, score=20.0,
                              weight=WEIGHTS["production_fit"], evidence={},
                              explanation="Không map được product type trong catalog Printway → khó đánh giá năng lực.")
    # Có trên menu Catalog nhưng chưa có số sản xuất -> KHÔNG suy default 3.
    if pt.get("_econ") == "unknown":
        return ScoreDimension(key="production_fit", label="Production Fit", group=GROUP_PROD, score=0.0,
                              weight=WEIGHTS["production_fit"], evidence={"_econ": "unknown"},
                              explanation=f"{pt['product_type']} có trong catalog nhưng chưa có số "
                                          f"sản xuất (độ khó/giá vốn) → chưa chấm được.")
    base = 85 if pt.get("capacity") == "in_house" else 55
    base -= (pt["production_difficulty"] - 1) * 5
    if pt.get("margin_high", 0) >= 0.55:
        base += 8
    elif pt.get("margin_high", 0) < 0.40:
        base -= 8
    score = round(max(0.0, min(100.0, base)), 1)
    cap = "in-house" if pt.get("capacity") == "in_house" else "đối tác"
    return ScoreDimension(
        key="production_fit", label="Production Fit", group=GROUP_PROD, score=score, weight=WEIGHTS["production_fit"],
        evidence={"capacity": pt.get("capacity"), "difficulty": pt.get("production_difficulty"),
                  "margin_high": pt.get("margin_high")},
        explanation=f"Sản xuất {cap}, độ khó {pt.get('production_difficulty')}/5 → production fit {score}/100.",
    )


def _production_time(pt: dict | None) -> ScoreDimension:
    diff = (pt or {}).get("production_difficulty")
    if diff is None:
        return ScoreDimension(key="production_time", label="Production Time", group=GROUP_PROD,
                              score=0.0, weight=WEIGHTS["production_time"],
                              evidence={"_econ": "unknown"},
                              explanation="Chưa có độ khó sản xuất cho product type này → chưa ước được lead time.")
    days = PROD_DAYS.get(diff, 7) + (2 if (pt or {}).get("capacity") != "in_house" else 0)
    score = round(max(0.0, min(100.0, 100 - (days - 2) * 5)), 1)
    return ScoreDimension(
        key="production_time", label="Production Time", group=GROUP_PROD, score=score, weight=WEIGHTS["production_time"],
        evidence={"est_production_days": days, "difficulty": diff},
        explanation=f"Lead time sản xuất ước ~{days} ngày (độ khó {diff}/5) → production time {score}/100 (nhanh = cao).",
    )


def _seasonality(peak_months: list[int]) -> ScoreDimension:
    m = _now_month()
    if not peak_months:
        return ScoreDimension(key="seasonality", label="Seasonality Fit", group=GROUP_PROD, score=60.0,
                              weight=WEIGHTS["seasonality"], evidence={"peak_months": []},
                              explanation="Không rõ mùa vụ → điểm trung tính 60.")
    lead = min((p - m) % 12 for p in peak_months)
    if lead == 0:
        score, note = 72.0, "đang trong mùa cao điểm (kịp bán nhưng muộn để build)"
    elif 1 <= lead <= 3:
        score, note = 92.0, f"còn {lead} tháng tới đỉnh — CỬA SỔ LAUNCH LÝ TƯỞNG"
    elif 4 <= lead <= 6:
        score, note = 58.0, f"còn {lead} tháng tới đỉnh — hơi sớm, có thời gian chuẩn bị"
    else:
        score, note = 38.0, f"còn {lead} tháng tới đỉnh — trái mùa"
    peaks = ", ".join(MONTH_NAMES[p] for p in peak_months)
    return ScoreDimension(
        key="seasonality", label="Seasonality Fit", group=GROUP_PROD, score=score, weight=WEIGHTS["seasonality"],
        evidence={"peak_months": peak_months, "current_month": m, "lead_months": lead},
        explanation=f"Đỉnh mùa: {peaks}. Hiện {MONTH_NAMES[m]} → {note} (điểm {score}/100).",
    )


def _personalization(nr) -> ScoreDimension:
    n = len(nr.personalization)
    base = {0: 50, 1: 68, 2: 80, 3: 90, 4: 96}.get(min(n, 4), 60)
    return ScoreDimension(
        key="personalization", label="Personalization", group=GROUP_PROD, score=float(base),
        weight=WEIGHTS["personalization"], evidence={"signals": nr.personalization},
        explanation=f"Hỗ trợ cá nhân hóa: {', '.join(nr.personalization)} ({n} chiều) → personalization {base}/100.",
    )


# ---------------- Fit gate + Lifecycle + Verdict ----------------
def _fit(pt: dict | None, nr) -> ProductionFit:
    if not pt:
        return ProductionFit(recommend=False, reason="Không map được về product_type nào trong catalog Printway.")
    in_house = pt.get("capacity") == "in_house"
    good_margin = pt.get("margin_high", 0) >= 0.40
    recommend = in_house and good_margin
    reasons = ["sản xuất in-house" if in_house else "cần đối tác (partner)",
               f"độ khó {pt.get('production_difficulty')}/5",
               f"biên {int(pt.get('margin_low',0)*100)}–{int(pt.get('margin_high',0)*100)}%"]
    return ProductionFit(
        recommend=recommend, matched_product_type=pt["product_type"], material=nr.material,
        difficulty=pt.get("production_difficulty"), margin_low=pt.get("margin_low"), margin_high=pt.get("margin_high"),
        reason="Fit năng lực: " + ", ".join(reasons) + (". → Phù hợp." if recommend else ". → Cân nhắc."),
    )


def _lifecycle(growth_pct: float, competition_score: float, demand_score: float) -> Lifecycle:
    if growth_pct <= -8:
        return Lifecycle(stage="Decline", note=f"growth {growth_pct:+.0f}%",
                         action="Suy thoái — không mở mới; nếu đang bán thì clearance/giảm giá xả hàng.")
    if growth_pct < 8 and competition_score < 45 and demand_score >= 55:
        return Lifecycle(stage="Saturation", note=f"growth {growth_pct:+.0f}%, cạnh tranh cao",
                         action="Bão hòa — chỉ vào nếu có EDGE khác biệt (design/material/personalization độc đáo).")
    if growth_pct >= 25 and competition_score >= 55 and demand_score < 72:
        return Lifecycle(stage="Conception", note=f"growth {growth_pct:+.0f}%, cạnh tranh còn thấp",
                         action="Tín hiệu sớm — VÀO SỚM: test nhanh 3–5 design, chưa cần scale.")
    if growth_pct >= 12:
        return Lifecycle(stage="Growth", note=f"growth {growth_pct:+.0f}%",
                         action="Tăng trưởng — LAUNCH ngay, chuẩn bị năng lực scale + siết fulfillment đúng hạn.")
    return Lifecycle(stage="Launch/Test", note=f"growth {growth_pct:+.0f}%",
                     action="Tạo listing test, đo phản hồi thực tế trước khi scale.")


def _verdict(total: float, fit: ProductionFit, lifecycle: Lifecycle) -> str:
    if fit.matched_product_type is None:
        return "Not Recommend"
    if lifecycle.stage == "Decline":
        return "Not Recommend"
    if lifecycle.stage == "Saturation":
        return "Consider (bão hòa)" if total >= 50 else "Not Recommend"
    if total >= 66 and fit.recommend:
        return "Recommend"
    if total >= 66 and not fit.recommend:
        return "Consider (ngoài năng lực in-house)"
    if total >= 50:
        return "Consider"
    return "Not Recommend"


def _assemble(oid, niche, keyword, title, sig, series, peak_months, nr=None) -> OpportunityScore:
    nr = nr or norm.normalize(title)     # nr truyền sẵn (heuristic) -> tránh gọi LLM hàng loạt
    pt = store.pt_by_id.get(nr.product_type_id)
    dims = [
        _demand(sig), _growth(series), _competition(sig),
        _revenue(sig, pt), _profit_margin(pt),
        _production_fit_dim(pt), _seasonality(peak_months), _production_time(pt), _personalization(nr),
    ]
    total = round(sum(d.score * d.weight for d in dims), 1)

    # LUẬT BẮT BUỘC: growth âm ⇒ hạ điểm mạnh (bão hòa/suy thoái)
    gpct = _growth_pct(series)
    guard_note = ""
    if gpct <= -8:
        total = round(min(total, 48.0), 1)
        guard_note = " ⚠️ Growth âm mạnh → hạ điểm (suy thoái)."
    elif gpct < 0:
        total = round(min(total, 58.0), 1)
        guard_note = " ⚠️ Growth âm → hạ điểm (chớm bão hòa)."

    demand_s = next(d.score for d in dims if d.key == "demand")
    comp_s = next(d.score for d in dims if d.key == "competition")
    lifecycle = _lifecycle(gpct, comp_s, demand_s)
    fit = _fit(pt, nr)
    verdict = _verdict(total, fit, lifecycle)

    # điểm trung bình mỗi nhóm
    groups: dict[str, list[float]] = {}
    for d in dims:
        groups.setdefault(d.group, []).append(d.score)
    group_avg = {g: round(sum(v) / len(v), 1) for g, v in groups.items()}

    top = sorted(dims, key=lambda d: d.score, reverse=True)
    headline = (f"{verdict} — {niche} ({nr.product_type}/{nr.material}): {total}/100 · {lifecycle.stage}. "
                f"Điểm sáng: {top[0].label} {top[0].score}, {top[1].label} {top[1].score}.{guard_note}")
    return OpportunityScore(
        id=oid, niche=niche, keyword=keyword, sample_title=title,
        normalized_product_type=nr.product_type, category=nr.category, material=nr.material,
        total_score=total, verdict=verdict, dimensions=dims, groups=group_avg, fit=fit, lifecycle=lifecycle,
        headline=headline, sources=["etsy_open_api", "amazon_helium10_export", "google_trends"],
        captured_at=store.last_updated,
    )


def score_opportunity(opp: dict) -> OpportunityScore:
    series = store.trend_series(opp.get("trend_key", "custom_generic"))
    return _assemble(opp["id"], opp["niche"], opp["keyword"], opp["sample_title"],
                     opp["signals"], series, opp.get("peak_months", []))


def score_keyword(keyword: str, title: str, sig: dict, series: list[float],
                  peak_months: list[int] | None = None, nr=None) -> OpportunityScore:
    """Chấm 9 chỉ số cho 1 keyword từ dữ liệu cào (dùng cho bảng Keyword Research)."""
    return _assemble("kw-" + str(abs(hash(keyword)) % 100000), keyword, keyword, title,
                     sig, series, peak_months or [11, 12], nr=nr)


def score_all() -> list[OpportunityScore]:
    return sorted((score_opportunity(o) for o in store.opportunities),
                  key=lambda s: s.total_score, reverse=True)


def score_title(title: str, niche: str | None = None) -> OpportunityScore:
    nr = norm.normalize(title)
    best = None
    for o in store.opportunities:
        onr = norm.normalize(o["sample_title"])
        s = 0
        if niche and o["niche"].lower() == niche.lower():
            s += 5
        if onr.category == nr.category:
            s += 2
        if onr.product_type == nr.product_type:
            s += 3
        if best is None or s > best[0]:
            best = (s, o)
    o = best[1]
    series = store.trend_series(o.get("trend_key", "custom_generic"))
    return _assemble("adhoc-" + str(abs(hash(title)) % 100000), niche or o["niche"], title, title,
                     o["signals"], series, o.get("peak_months", []))
