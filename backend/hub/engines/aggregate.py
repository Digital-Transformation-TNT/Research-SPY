"""Trend Aggregation — gộp tín hiệu thành bảng xếp hạng hành động được.

Nguồn: analysis.current_opportunities() (fallback seed khi DB rỗng).
"""
from __future__ import annotations

from ..store import store
from . import analysis


def _dim(s, key):
    return next(d for d in s.dimensions if d.key == key)


def dashboard() -> dict:
    scored = analysis.current_opportunities()

    top_opportunities = [
        {"id": s.id, "niche": s.niche, "product_type": s.normalized_product_type,
         "material": s.material, "score": s.total_score, "verdict": s.verdict,
         "lifecycle": s.lifecycle.stage, "action": s.lifecycle.action,
         "headline": s.headline} for s in scored[:8]
    ]

    fastest_growing = sorted(
        [{"niche": s.niche, "keyword": s.keyword,
          "growth_pct": _dim(s, "growth").evidence.get("growth_pct_3m", 0),
          "score": s.total_score} for s in scored],
        key=lambda r: r["growth_pct"], reverse=True)[:6]

    least_competitive = sorted(
        [{"niche": s.niche, "product_type": s.normalized_product_type,
          "competition_score": _dim(s, "competition").score, "score": s.total_score} for s in scored],
        key=lambda r: r["competition_score"], reverse=True)[:6]

    top_revenue = sorted(
        [{"niche": s.niche, "product_type": s.normalized_product_type,
          "est_monthly_profit_usd": _dim(s, "revenue").evidence.get("est_monthly_profit_usd", 0),
          "score": s.total_score} for s in scored],
        key=lambda r: r["est_monthly_profit_usd"] or 0, reverse=True)[:6]

    alerts = []
    for s in scored:
        g = _dim(s, "growth").evidence.get("growth_pct_3m", 0)
        cs = _dim(s, "competition").score
        if g >= 25 and cs >= 45:
            alerts.append({"niche": s.niche, "product_type": s.normalized_product_type,
                           "growth_pct": g, "competition_score": cs, "score": s.total_score,
                           "message": f"🚀 {s.niche} tăng {g:+.0f}% mà cạnh tranh còn dễ ({cs}/100) — vào sớm."})
    alerts = sorted(alerts, key=lambda a: a["growth_pct"], reverse=True)[:5]

    return {
        "last_updated": store.last_updated,
        "sources": ["Etsy Open API", "Amazon (crawl)", "Google Trends"],
        "counts": {"opportunities": len(scored), "product_types": len(store.product_types),
                   "niches": len({s.niche for s in scored})},
        "top_opportunities": top_opportunities,
        "fastest_growing": fastest_growing,
        "least_competitive": least_competitive,
        "top_revenue": top_revenue,
        "early_trend_alerts": alerts,
    }


def compare_niches(niches: list[str]) -> dict:
    scored = analysis.current_opportunities()
    wanted = {n.lower() for n in niches}
    rows = [s for s in scored if s.niche.lower() in wanted]
    if not rows:
        rows = [s for s in scored if any(w in s.niche.lower() for w in wanted)]
    best_per_niche: dict[str, object] = {}
    for s in rows:
        cur = best_per_niche.get(s.niche)
        if cur is None or s.total_score > cur.total_score:
            best_per_niche[s.niche] = s
    table = []
    for s in best_per_niche.values():
        dd = {d.key: d.score for d in s.dimensions}
        table.append({"niche": s.niche, "product_type": s.normalized_product_type, "material": s.material,
                      "total": s.total_score, "verdict": s.verdict, "lifecycle": s.lifecycle.stage,
                      "dimensions": dd, "headline": s.headline})
    table.sort(key=lambda r: r["total"], reverse=True)
    return {"compared": niches, "table": table, "winner": table[0] if table else None}
