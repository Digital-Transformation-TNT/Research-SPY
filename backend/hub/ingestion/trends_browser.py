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
        # `finally` chứ không phải dòng cuối — xem ghi chú cùng loại ở `amazon_shops.py`.
        try:
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
        finally:
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


# ─────────────────── CHUỖI GIỮ NGUYÊN NGÀY (cho Trend Signal Hub) ───────────────────
# `_parse`/`_fetch_many` ở trên nén về 12 điểm và vứt trục thời gian — đủ cho cái sparkline
# của bản Printway, KHÔNG đủ cho `signal/trendsig.py`: L, M_ngắn, M_bền đều là phép tính
# trên những cửa sổ ngày cụ thể (d[-6..-0], d[-13..-7], d[-55..-28]). Nén xong là mất đúng
# thứ chúng ăn vào. Hai hàm dưới lấy cùng một RPC nhưng giữ nguyên (ngày, giá trị).


def _parse_points(raw: str, n_series: int = 1) -> list[tuple[str, list[float]]]:
    """timelineData → [(YYYY-MM-DD, [giá trị của từng term])]. `time` là epoch giây UTC."""
    from datetime import datetime, timezone
    i = raw.find("{")
    if i < 0:
        return []
    try:
        data = json.loads(raw[i:])
    except Exception:
        return []
    out = []
    for r in (data.get("default") or {}).get("timelineData") or []:
        vals = r.get("value") or []
        if len(vals) < n_series or not r.get("time"):
            continue
        day = datetime.fromtimestamp(int(r["time"]), timezone.utc).date().isoformat()
        out.append((day, [float(v) for v in vals[:n_series]]))
    return out


async def _fetch_points(keywords: list[str], geo: str, date_range: str,
                        anchor: str | None) -> dict[str, list[tuple[str, float]]]:
    from playwright.async_api import async_playwright

    got: dict[str, list[tuple[str, float]]] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        try:
            ctx = await browser.new_context(
                storage_state=str(AUTH) if AUTH.exists() else None, locale="en-US")
            page = await ctx.new_page()
            cur: dict = {"rows": None}
            n_series = 2 if anchor else 1

            async def on_resp(r):
                if MULTILINE not in r.url:
                    return
                try:
                    rows = _parse_points(await r.text(), n_series)
                except Exception:
                    return
                if rows:
                    cur["rows"] = rows

            page.on("response", on_resp)

            for kw in keywords:
                cur["rows"] = None
                terms = f"{anchor},{kw}" if anchor else kw
                url = (f"{EXPLORE}?q={urllib.parse.quote(terms)}"
                       f"&geo={geo}&date={urllib.parse.quote(date_range)}")
                try:
                    await page.goto(url, timeout=45000)
                    for _ in range(16):
                        if cur["rows"]:
                            break
                        await page.wait_for_timeout(500)
                except Exception:
                    pass
                rows = cur["rows"]
                if not rows:
                    continue
                if anchor:
                    # Cùng một truy vấn nên hai chuỗi đã chung một mốc chuẩn hoá. Chia cho
                    # mức trung bình của từ khoá neo là đưa MỌI đợt lấy về chung một thước:
                    # đó là điều kiện để so `L` giữa các từ khoá — không có bước này thì mỗi
                    # chuỗi được chuẩn hoá theo đỉnh của chính nó và 60 với 30 không so được.
                    base = [v[0] for _d, v in rows]
                    ref = sum(base) / len(base) if base else 0
                    if ref <= 0:
                        continue
                    got[kw] = [(d, round(v[1] / ref * 100, 2)) for d, v in rows]
                else:
                    got[kw] = [(d, v[0]) for d, v in rows]
        finally:
            await browser.close()
    return got


def fetch_points_many(keywords: list[str], geo: str = "VN",
                      date_range: str = "today 3-m",
                      anchor: str | None = None) -> dict[str, list[tuple[str, float]]]:
    """
    Chuỗi (ngày, giá trị) cho từng keyword.

    `anchor` là một từ khoá ổn định gửi kèm trong CÙNG truy vấn. Có nó thì giá trị trả về
    tính theo thước của từ khoá neo (`value_kind='anchored'`) và so được giữa các từ khoá;
    không có thì mỗi chuỗi tự chuẩn hoá theo đỉnh của nó (`value_kind='index'`) và chỉ
    dùng được cho các chỉ số TỈ LỆ — M_ngắn, M_bền, YoY. Ngưỡng quy mô `MIN_INDEX` chỉ
    thật sự có nghĩa ở chế độ neo.
    """
    try:
        return asyncio.run(_fetch_points(keywords, geo, date_range, anchor))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_fetch_points(keywords, geo, date_range, anchor))
        finally:
            loop.close()
