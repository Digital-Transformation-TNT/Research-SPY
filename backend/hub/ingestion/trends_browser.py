"""Chuỗi Google Trends qua trang /explore bằng Chrome thật — thay pytrends.

Mở /explore (kèm phiên đăng nhập gtrends/) rồi bắt phản hồi `widgetdata/multiline`.
Phải dùng Chrome thật (channel="chrome") — Chromium đi kèm Playwright trả payload rỗng.
"""
from __future__ import annotations
import asyncio
import json
import urllib.parse
from pathlib import Path

AUTH = Path(__file__).resolve().parents[2] / "gtrends" / ".auth" / "google.json"
EXPLORE = "https://trends.google.com/trends/explore"
# Trang /explore phát nhiều RPC; chuỗi thời gian nằm ở widget này.
MULTILINE = "widgetdata/multiline"


def _downsample(vals: list[float], n: int = 12) -> list[float]:
    """Gộp về n điểm bằng trung bình — giữ được đỉnh."""
    if not vals:
        return []
    if len(vals) <= n:
        return [round(float(v), 1) for v in vals]
    size = len(vals) / n
    out = []
    for i in range(n):
        lo, hi = int(i * size), max(int((i + 1) * size), int(i * size) + 1)
        chunk = vals[lo:hi]
        out.append(round(sum(chunk) / len(chunk), 1) if chunk else 0.0)
    return out


def _parse(raw: str) -> list[float]:
    """Bóc timelineData. Phản hồi mở đầu bằng )]}', phải cắt trước khi parse."""
    i = raw.find("{")
    if i < 0:
        return []
    try:
        data = json.loads(raw[i:])
    except Exception:
        return []
    rows = (data.get("default") or {}).get("timelineData") or []
    out = []
    for r in rows:
        v = r.get("value") or []
        if v:
            out.append(float(v[0]))
    return out


async def _fetch_many(keywords: list[str], geo: str = "US",
                      date_range: str = "today 12-m") -> dict[str, list[float]]:
    from playwright.async_api import async_playwright

    got: dict[str, list[float]] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        ctx = await browser.new_context(
            storage_state=str(AUTH) if AUTH.exists() else None, locale="en-US")
        page = await ctx.new_page()

        current: dict = {"kw": None, "series": None}

        async def on_resp(r):
            if MULTILINE not in r.url:
                return
            try:
                series = _parse(await r.text())
            except Exception:
                return
            if series:
                current["series"] = series

        page.on("response", on_resp)

        for kw in keywords:
            current["kw"], current["series"] = kw, None
            url = (f"{EXPLORE}?q={urllib.parse.quote(kw)}"
                   f"&geo={geo}&date={urllib.parse.quote(date_range)}")
            try:
                await page.goto(url, timeout=45000)
                # chờ RPC multiline về; 8s là đủ cho mạng bình thường
                for _ in range(16):
                    if current["series"]:
                        break
                    await page.wait_for_timeout(500)
            except Exception:
                pass
            if current["series"]:
                got[kw] = _downsample(current["series"])
        await browser.close()
    return got


def fetch_series_many(keywords: list[str], geo: str = "US",
                      date_range: str = "today 12-m") -> dict[str, list[float]]:
    """Đồng bộ hoá cho worker/route gọi. Trả {keyword: series 12 điểm}."""
    try:
        return asyncio.run(_fetch_many(keywords, geo, date_range))
    except RuntimeError:
        # đã có event loop (chạy trong FastAPI async) -> chạy loop riêng
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_fetch_many(keywords, geo, date_range))
        finally:
            loop.close()
