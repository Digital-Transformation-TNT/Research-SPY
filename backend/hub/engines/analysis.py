"""AI AGENT — đọc RAW data từ DB, làm sạch, phân tích thành output chuẩn (mở rộng).

Output: Top Keywords (Demand/Competition/Growth/Trend/Opp/Seasonality/BuyerIntent/Collection/
Material/Style/Đề xuất SP) · Top Products (Revenue/Quantity theo thời gian & khu vực) ·
Key Insights · Prediction 30-60 ngày · Đề xuất R&D + Seller · End-user persona · Design niches.

Tối ưu chi phí: số liệu = heuristic ($0); LLM chỉ cho phần tổng hợp (ưu tiên model rẻ).
Role: 'rnd' (thêm độ khó sản xuất/fit/margin) | 'seller' (chỉ độ quan tâm + doanh số).
"""
from __future__ import annotations
import statistics as stats
from datetime import datetime, timezone, timedelta

from .. import db, llm
from ..knowledge import PRINTWAY_CONTEXT
from ..ingestion import gtrends
from . import normalize as norm, scoring, ontology, learning

# ---- Collection classifier ----
_COLLECTION_RULES = [
    ("Ornaments", ["ornament", "bauble"]),
    ("Decorations", ["decoration", "decor", "stocking", "wreath", "garland"]),
    ("Drinkware", ["mug", "tumbler", "cup", "bottle"]),
    ("Kitchen", ["cutting board", "kitchen", "apron", "coaster"]),
    ("Wall Art", ["canvas", "poster", "sign", "wall art"]),
    ("Apparel", ["shirt", "hoodie", "sweater", "tee"]),
    ("Home Decor", ["blanket", "pillow", "plaque", "night light", "candle"]),
    ("Gifts", ["gift", "personalized", "custom"]),
]
_STYLE_RULES = [
    ("rustic", ["rustic", "farmhouse", "barn", "wood"]),
    ("vintage", ["vintage", "retro", "antique"]),
    ("modern", ["modern", "minimalist", "sleek", "contemporary"]),
    ("cute", ["cute", "kawaii", "fun", "funny", "adorable"]),
    ("elegant", ["elegant", "luxury", "gold", "premium", "classy"]),
    ("festive", ["christmas", "holiday", "festive", "xmas", "santa", "noel"]),
    ("boho", ["boho", "bohemian"]),
    ("personalized", ["personalized", "custom", "monogram", "name", "photo"]),
]


_OCCASION_RULES = [
    ("Christmas", ["christmas", "xmas", "santa", "noel", "holiday"]),
    ("Halloween", ["halloween", "spooky", "pumpkin"]),
    ("Valentine's Day", ["valentine"]),
    ("Mother's Day", ["mother", "mom", "mum", "grandma", "nana"]),
    ("Father's Day", ["father", "dad", "grandpa", "papa"]),
    ("Easter", ["easter", "bunny"]),
    ("Graduation", ["graduation", "graduate", "grad "]),
    ("Wedding", ["wedding", "bride", "groom", "marriage"]),
    ("Anniversary", ["anniversary"]),
    ("Birthday", ["birthday", "birth flower", "bday"]),
    ("Baby Shower", ["baby", "newborn", "nursery"]),
    ("Memorial", ["memorial", "loving memory", "sympathy", "loss"]),
    ("Back-to-school", ["teacher", "school", "classroom"]),
]


def _occasion_for(text: str) -> str:
    t = text.lower()
    for occ, kws in _OCCASION_RULES:
        if any(w in t for w in kws):
            return occ
    return "Year-round"


def _style_for(text: str) -> str:
    t = text.lower()
    for style, kws in _STYLE_RULES:
        if any(w in t for w in kws):
            return style
    return "classic"


def _buyer_intent(keyword: str) -> str:
    k = keyword.lower()
    if any(w in k for w in ["how ", "what ", "idea", "diy", "tutorial"]):
        return "informational"
    if any(w in k for w in ["planner", "planning", "calendar", "checklist", "2026", "2027"]):
        return "planning"
    if any(w in k for w in ["gift", "for her", "for him", "for mom", "for dad", "for kids",
                            "for women", "for men", "for teacher", "for grandma", "for grandpa"]):
        return "gift"
    if any(w in k for w in ["decor", "decoration", "ornament", "wreath", "garland", "stocking"]):
        return "decorative"
    if any(w in k for w in ["best", "buy", "cheap", "sale", "deal", "review", "vs"]):
        return "purchase"
    return "purchase"


def _seasonality_label(score: float) -> str:
    return "high" if score >= 75 else ("medium" if score >= 50 else "low")


# ---------------- CLEAN + FILTER ----------------
def clean(rows: list[dict], filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    plat = filters.get("platform")
    since_days = filters.get("since_days")
    cutoff = None
    if since_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(since_days))).isoformat()
    seen, out = set(), []
    for r in rows:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        if plat and r.get("platform") != plat:
            continue
        if cutoff and (r.get("crawled_at") or "") < cutoff:
            continue
        key = (r.get("platform"), title.lower()[:80])
        if key in seen:
            continue
        seen.add(key)
        r = dict(r)
        p = float(r["price"]) if r.get("price") else None
        if p is not None and (p < 0.5 or p > 5000):
            p = None
        r["price"] = p
        r["favorites"] = int(r["favorites"] or 0)
        r["reviews"] = int(r["reviews"] or 0)
        r["est_sales"] = min(int(r["est_sales"] or 0), 5000)
        out.append(r)
    return out


def _group(rows: list[dict], key) -> dict:
    g: dict = {}
    for r in rows:
        g.setdefault(key(r), []).append(r)
    return g


def _sig_for(rows: list[dict]) -> dict:
    etsy = [r for r in rows if r["platform"] == "etsy"]
    amz = [r for r in rows if r["platform"] == "amazon"]
    def agg(rs, f): return sum(r.get(f) or 0 for r in rs)
    def avgprice(rs):
        ps = [r["price"] for r in rs if r.get("price")]
        return round(stats.mean(ps), 2) if ps else 20.0
    n_sellers = len({r.get("seller") for r in rows if r.get("seller")})   # số shop THẬT bán keyword
    return {
        "etsy": {"search_volume": int(agg(etsy, "favorites") * 1.2 + len(etsy) * 500),
                 "active_listings": max(len(etsy) * 60, 1), "sellers_with_sales": max(len(etsy) * 12, 1),
                 "favorites_30d": agg(etsy, "favorites"), "avg_price_usd": avgprice(etsy),
                 "top_listing_reviews": max([r.get("reviews", 0) for r in etsy], default=0)},
        "amazon": {"search_volume": int(agg(amz, "reviews") * 2 + len(amz) * 400),
                   "active_listings": max(len(amz) * 40, 1), "avg_price_usd": avgprice(amz),
                   "est_monthly_units": agg(amz, "est_sales")},
        "n_sellers": n_sellers,
    }


# ---------------- NGUỒN THỐNG NHẤT: opportunities từ data CRAWL THẬT ----------------
def current_opportunities(filters: dict | None = None):
    """Dựng list OpportunityScore (9 chỉ số) từ keyword đã crawl trong DB.

    Nguồn dùng chung cho Copilot/Dashboard/Explorer/Compare/Report.
    DB rỗng -> fallback seed_opportunities.
    """
    from ..store import store
    cleaned = clean(db.get_listings(limit=8000), filters)
    if not cleaned:
        return [scoring.score_opportunity(o) for o in store.opportunities]
    out = []
    for kw, rs in _group(cleaned, lambda r: (r.get("keyword") or "").strip().lower()).items():
        if not kw:
            continue
        sig = _sig_for(rs)
        series, _ = gtrends.cached_series(kw)
        top_title = max(rs, key=lambda r: (r.get("favorites") or 0) + (r.get("reviews") or 0))["title"]
        nr = norm.normalize_heuristic(top_title)
        out.append(scoring.score_keyword(kw, top_title, sig, series, nr=nr))
    # rerank theo sở thích ĐÃ HỌC (điểm gốc giữ nguyên, chỉ đổi thứ tự ưu tiên)
    prof = learning.profile()
    out.sort(key=lambda s: s.total_score + learning.boost(
        s.category, s.material, _style_for(s.sample_title), s.normalized_product_type, prof), reverse=True)
    return out


# ---------------- KEYWORD TABLE (mở rộng) ----------------
def build_keyword_table(rows: list[dict], top: int = 15) -> list[dict]:
    by_kw = _group(rows, lambda r: (r.get("keyword") or "").strip().lower())
    out = []
    for kw, rs in by_kw.items():
        if not kw:
            continue
        sig = _sig_for(rs)
        series, tsrc = gtrends.cached_series(kw)
        top_title = max(rs, key=lambda r: (r.get("favorites") or 0) + (r.get("reviews") or 0))["title"]
        nr = norm.normalize_heuristic(top_title)                 # heuristic -> rẻ + nhanh
        sc = scoring.score_keyword(kw, top_title, sig, series, nr=nr)
        dims = {d.key: d.score for d in sc.dimensions}
        out.append({
            "keyword": kw,
            "demand": dims["demand"],
            "competition": dims["competition"],
            "growth": dims["growth"],
            "trend": round(series[-1], 1) if series else 50.0,       # mức độ quan tâm hiện tại
            "opp": sc.total_score,
            "seasonality": _seasonality_label(dims["seasonality"]),
            "buyer_intent": _buyer_intent(kw),
            "collection": nr.category,                    # Collection Printway thật (từ chuẩn hóa)
            "occasion": _occasion_for(top_title + " " + kw),
            "material": nr.material,
            "style": _style_for(top_title + " " + kw),
            "product_suggestion": nr.product_type,
            "trend_source": tsrc,
            "n_listings": len(rs),
            "n_sellers": len({r.get("seller") for r in rs if r.get("seller")}),   # số shop bán keyword
            "sellers_by_platform": {p: len({r.get("seller") for r in rs if r.get("seller") and r["platform"] == p})
                                    for p in sorted({r["platform"] for r in rs})},
            "verdict": sc.verdict,
            "lifecycle": sc.lifecycle.stage,
        })
    # rerank theo sở thích ĐÃ HỌC
    prof = learning.profile()
    for r in out:
        r["boost"] = learning.boost(r["collection"], r["material"], r["style"], r["product_suggestion"], prof)
        r["personalized"] = r["boost"] > 0
    out.sort(key=lambda r: r["opp"] + r["boost"], reverse=True)
    return out[:top]


# ---------------- PRODUCT TABLE (thời gian + khu vực + role) ----------------
_REGION = {"amazon": "US/VN*", "etsy": "Global"}   # *giá Amazon serve theo IP VN


def build_product_table(rows: list[dict], role: str = "rnd", top: int = 15) -> list[dict]:
    # Khử trùng theo (sàn,url): cùng 1 SP xuất hiện ở nhiều keyword chỉ tính doanh thu 1 lần.
    uniq, seen_url = [], set()
    for r in rows:
        k = (r.get("platform"), r.get("url"))
        if r.get("url") and k in seen_url:
            continue
        seen_url.add(k)
        uniq.append(r)
    rows = uniq
    for r in rows:
        r["_pt"] = norm.normalize_heuristic(r["title"])
    by_pt = _group(rows, lambda r: r["_pt"].product_type)
    out = []
    for pt, rs in by_pt.items():
        prices = [r["price"] for r in rs if r.get("price")]
        avg_price = round(stats.mean(prices), 2) if prices else 0.0
        qty_30d = sum(r.get("est_sales") or 0 for r in rs)
        rev_30d = int(qty_30d * avg_price)
        nr0 = rs[0]["_pt"]
        ptx = store_pt(nr0.product_type_id)
        row = {
            "product_type": pt, "category": nr0.category, "material": nr0.material,
            "avg_price_usd": avg_price, "region": "+".join(sorted({_REGION.get(r["platform"], "?") for r in rs})),
            "qty_30d": qty_30d, "revenue_30d": rev_30d,
            "qty_last_year": qty_30d * 12, "revenue_last_year": rev_30d * 12,
            "platforms": sorted({r["platform"] for r in rs}), "n_listings": len(rs),
            "suggested_sku": ontology.generate_sku(pt, nr0.material, nr0.personalization),
        }
        if role == "rnd" and ptx:      # R&D: thêm chỉ số sản xuất
            row["production_difficulty"] = ptx.get("production_difficulty")
            row["margin_low"] = ptx.get("margin_low")
            row["margin_high"] = ptx.get("margin_high")
            row["capacity"] = ptx.get("capacity")
        out.append(row)
    out.sort(key=lambda r: r["revenue_30d"], reverse=True)
    return out[:top]


def store_pt(pt_id):
    from ..store import store
    return store.pt_by_id.get(pt_id)


# ---------------- SYNTHESIS (insight + prediction + personas + niches + role recs) ----------------
def synthesize(keywords: list[dict], products: list[dict], role: str) -> dict:
    kw_txt = "; ".join(f"{k['keyword']}(opp {k['opp']}, growth {k['growth']}, {k['collection']}/{k['style']}, {k['buyer_intent']})" for k in keywords[:8])
    pr_txt = "; ".join(f"{p['product_type']}(${p['revenue_30d']}/th, {p['qty_30d']} đơn)" for p in products[:6])
    if llm.enabled():
        try:
            system = PRINTWAY_CONTEXT + ("\n\nBạn là AI R&D analyst Printway. Viết NGẮN GỌN, mỗi ý 1 câu, "
                     f"hành động được, tiếng Việt, không bịa số. Đối tượng: {role}.") + learning.profile_prompt()
            prompt = (f"TOP KEYWORDS: {kw_txt}\nTOP PRODUCTS: {pr_txt}\n\n"
                      "Trả JSON (mỗi phần tử là 1 câu NGẮN): {\"key_insights\":[3], \"prediction_30_60d\":[2], "
                      "\"rec_rnd\":[2], \"rec_seller\":[2], \"personas\":[2], \"design_niches\":[3]}")
            data = llm.complete_json(system, prompt, tier="smart", max_tokens=1600)
            if data and "key_insights" in data:
                data["_by"] = "llm"
                return data
        except Exception:
            pass
    # heuristic fallback
    top = keywords[0] if keywords else None
    coll = {}
    for k in keywords:
        coll[k["collection"]] = coll.get(k["collection"], 0) + 1
    hot = max(coll, key=coll.get) if coll else "Gifts"
    p0 = products[0] if products else None
    return {
        "_by": "heuristic",
        "key_insights": [
            f"Keyword mạnh nhất: '{top['keyword']}' (Opp {top['opp']}, Growth {top['growth']}, intent {top['buyer_intent']})." if top else "Chưa đủ dữ liệu.",
            f"Collection nổi bật: {hot}. Nhiều keyword mang intent quà tặng → hợp mùa lễ.",
            f"SP doanh thu cao nhất: {p0['product_type']} (~${p0['revenue_30d']:,}/tháng, {p0['qty_30d']:,} đơn)." if p0 else "",
        ],
        "prediction_30_60d": [
            "30-60 ngày tới nhu cầu nhóm quà tặng/trang trí sẽ tăng khi vào cao điểm Q4.",
            "Keyword Growth cao + cạnh tranh vừa tiếp tục lên; nên vào sớm 1-2 tuần.",
            "Chuẩn bị năng lực cho product type doanh thu cao trước khi đỉnh mùa.",
        ],
        "rec_rnd": [
            f"Làm {p0['product_type']} ({p0['material']}) — kiểm tra độ khó/ margin trước khi scale." if p0 else "",
            f"Ưu tiên collection {hot}; test 3-5 design/keyword Opp≥66.",
        ],
        "rec_seller": [
            f"Bán {p0['product_type']} cho niche {hot}; nhấn design cá nhân hóa." if p0 else "",
            "Tránh keyword growth âm (bão hòa); tập trung intent 'gift'.",
        ],
        "personas": [
            "Người mua quà mùa lễ: tìm SP cá nhân hóa cho gia đình/bạn bè, giá 15-40$.",
            "Người trang trí nhà: tìm ornament/decor theo phong cách festive.",
        ],
        "design_niches": [
            f"{hot} cá nhân hóa tên/ảnh", "Baby's first Christmas", "Pet memorial ornament",
            "Family established sign",
        ],
    }


# ---------------- FULL PIPELINE ----------------
def full_analysis(role: str = "rnd", filters: dict | None = None, save: bool = True) -> dict:
    raw = db.get_listings(limit=8000)
    cleaned = clean(raw, filters)
    # filter theo category/material (sau normalize)
    filters = filters or {}
    cat, mat = filters.get("category"), filters.get("material")
    if cat or mat:
        kept = []
        for r in cleaned:
            nr = norm.normalize_heuristic(r["title"])
            if cat and nr.category != cat:
                continue
            if mat and nr.material != mat:
                continue
            kept.append(r)
        cleaned = kept
    keywords = build_keyword_table(cleaned)
    products = build_product_table(cleaned, role=role)
    synth = synthesize(keywords, products, role)
    now = datetime.now(timezone.utc)
    result = {
        "generated_at": now.isoformat(), "role": role, "filters": filters,
        "raw_count": len(raw), "clean_count": len(cleaned),
        "sources": sorted({r["platform"] for r in raw}),
        "keywords": keywords, "products": products,
        "key_insights": synth.get("key_insights", []),
        "prediction_30_60d": synth.get("prediction_30_60d", []),
        "rec_rnd": synth.get("rec_rnd", []),
        "rec_seller": synth.get("rec_seller", []),
        "personas": synth.get("personas", []),
        "design_niches": synth.get("design_niches", []),
        "analyzed_by": synth.get("_by", "heuristic"),
    }
    if save:
        db.save_report("analysis", f"Daily POD Research {now:%Y-%m-%d}", to_markdown(result))
    return result


def to_markdown(res: dict) -> str:
    d = datetime.fromisoformat(res["generated_at"])
    md = [f"# Daily POD Keyword Research — {d:%Y-%m-%d}",
          f"*AI Agent · {res['clean_count']}/{res['raw_count']} listing · Nguồn: {', '.join(res['sources'])} · vai trò: {res['role']} · engine: {res['analyzed_by']}*",
          "", "## 🔥 Top Keywords", "",
          "| Keyword | Opp | Demand | Comp | Growth | Shops | Season | Intent | Collection | Style | Đề xuất SP |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in res["keywords"]:
        md.append(f"| {k['keyword']} | {k['opp']} | {k['demand']} | {k['competition']} | {k['growth']} | {k.get('n_sellers','-')} | {k['seasonality']} | {k['buyer_intent']} | {k['collection']} | {k['style']} | {k['product_suggestion']} |")
    md += ["", "## 📦 Top Products", "",
           "| Product | Revenue/30d | Qty/30d | Revenue/năm | Region | Category | Material |",
           "|---|---|---|---|---|---|---|"]
    for p in res["products"]:
        md.append(f"| {p['product_type']} | ${p['revenue_30d']:,} | {p['qty_30d']:,} | ${p['revenue_last_year']:,} | {p['region']} | {p['category']} | {p['material']} |")
    md += ["", "## 💡 Key Insights", ""] + [f"{i+1}. {x}" for i, x in enumerate(res["key_insights"]) if x]
    md += ["", "## 📈 Prediction 30–60 ngày", ""] + [f"- {x}" for x in res["prediction_30_60d"] if x]
    md += ["", "## 🎯 Đề xuất cho R&D", ""] + [f"- {x}" for x in res["rec_rnd"] if x]
    md += ["", "## 🛒 Đề xuất cho Seller", ""] + [f"- {x}" for x in res["rec_seller"] if x]
    md += ["", "## 👤 Chân dung người dùng cuối", ""] + [f"- {x}" for x in res["personas"] if x]
    md += ["", "## 🎨 Ngách thiết kế gợi ý", ""] + [f"- {x}" for x in res["design_niches"] if x]
    return "\n".join(md)
