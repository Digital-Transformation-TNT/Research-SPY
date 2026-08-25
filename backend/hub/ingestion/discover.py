"""Trend Discovery — dùng gói gtrends (Playwright + Chrome thật) lấy keyword liên quan đang tăng từ 1 seed.

Setup 1 lần (nếu chưa, adapter trả available=False kèm hướng dẫn):
    pip install playwright && playwright install chromium
    cd backend && python -m gtrends.login      # đăng nhập Google (Chrome thật)
    # chạy uvicorn KHÔNG kèm --reload (Playwright cần ProactorEventLoop trên Windows)
"""
from __future__ import annotations


async def discover(seed: str, country: str = "US") -> dict:
    try:
        from gtrends import fetch_related_queries, TrendsContext   # lazy: cần playwright
    except Exception as e:  # noqa
        return {"available": False, "queries": [],
                "message": f"Chưa cài gtrends/playwright: {e}. Xem backend/gtrends/README.md."}
    try:
        out = await fetch_related_queries(seed, TrendsContext(country=country))
    except Exception as e:  # noqa
        return {"available": False, "queries": [], "message": f"Lỗi gtrends: {e}"}
    if getattr(out, "needs_login", False):
        return {"available": False, "needs_login": True, "queries": [],
                "message": out.message or "Cần đăng nhập: cd backend && python -m gtrends.login"}
    ctx = TrendsContext(country=country)
    return {
        "available": True,
        "seed": seed,
        "took_ms": getattr(out, "took_ms", None),
        # Cửa sổ so sánh — giao diện hiện kèm mỗi %.
        "time_range": ctx.time_range,
        "country": country,
        "queries": [{"query": q.query, "value": q.value, "rising": q.rising,
                     "change_percent": q.change_percent} for q in out.queries],
    }
