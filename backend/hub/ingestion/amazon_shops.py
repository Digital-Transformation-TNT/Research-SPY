"""Tên shop Amazon — lấy từ trang /dp/<asin> bằng Chrome thật.

Ưu tiên nguồn tên: #sellerProfileTriggerId (người bán) -> #bylineInfo (thương hiệu).
Chạy song song nhiều tab.
"""
from __future__ import annotations
import asyncio
import json
import re

from .. import db

# Không phải tên shop: badge, nhãn giá, chuỗi điều hướng.
_BADGE = ("amazon's choice", "best seller", "overall pick", "sponsored",
          "limited time deal", "climate pledge", "sold by", "click to see",
          "see price", "add to cart", "buy now", "in stock", "out of stock",
          "free shipping", "prime", "deal", "coupon", "save ")


def _clean(s: str | None) -> str | None:
    if not s:
        return None
    t = re.sub(r"^\s*(visit the|brand:)\s*", "", s.strip(), flags=re.I)
    t = re.sub(r"\s*store\s*$", "", t, flags=re.I).strip()
    if not t or len(t) > 40:
        return None
    if any(b in t.lower() for b in _BADGE):
        return None
    return t


def _todo(limit: int) -> list[tuple[int, str]]:
    """(row_id, asin) của listing Amazon chưa có tên shop."""
    out = []
    with db.connect() as c:
        rows = c.execute(
            """SELECT id, raw_json FROM raw_listings
               WHERE platform='amazon' AND (seller IS NULL OR seller='')""").fetchall()
    for rid, rj in rows:
        try:
            x = json.loads(rj or "{}")
        except Exception:
            continue
        if x.get("asin"):
            out.append((rid, x["asin"]))
        if len(out) >= limit:
            break
    return out


async def _scrape(asins: list[str], workers: int = 4) -> dict[str, str]:
    from playwright.async_api import async_playwright
    found: dict[str, str] = {}
    queue = list(asins)

    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        ctx = await b.new_context(
            locale="en-US",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        async def worker():
            pg = await ctx.new_page()
            # chặn ảnh/font cho nhanh — chỉ cần HTML
            await pg.route("**/*", lambda r: asyncio.ensure_future(
                r.abort() if r.request.resource_type in ("image", "media", "font")
                else r.continue_()))
            while queue:
                try:
                    asin = queue.pop()
                except IndexError:
                    break
                try:
                    await pg.goto(f"https://www.amazon.com/dp/{asin}",
                                  wait_until="domcontentloaded", timeout=25000)
                    # Amazon có nhiều layout; thêm bảng thông số (tr.po-brand)
                    # cho các trang không có #sellerProfileTriggerId/#bylineInfo.
                    got = await pg.evaluate("""()=>{
                      const pick = s => { const e=document.querySelector(s);
                        return e? e.textContent.trim().slice(0,60) : null; };
                      return {seller: pick('#sellerProfileTriggerId'),
                              byline: pick('#bylineInfo'),
                              brand:  pick('tr.po-brand td.a-span9 span')
                                   || pick('#brand')
                                   || pick('[data-feature-name="brandSnapshot"] a')};
                    }""")
                    name = (_clean(got.get("seller")) or _clean(got.get("byline"))
                            or _clean(got.get("brand")))
                    if name:
                        found[asin] = name
                except Exception:
                    continue
            await pg.close()

        await asyncio.gather(*[worker() for _ in range(workers)])
        await b.close()
    return found


def fetch_names(limit: int = 300, workers: int = 4) -> dict:
    todo = _todo(limit)
    if not todo:
        return {"ok": True, "reason": "mọi listing Amazon đã có tên shop", "updated": 0}

    asins = list({a for _, a in todo})
    try:
        found = asyncio.run(_scrape(asins, workers=workers))
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "reason": str(e)[:160]}

    pend = []
    with db.connect() as c:
        rows = c.execute(
            """SELECT id, raw_json FROM raw_listings
               WHERE platform='amazon' AND (seller IS NULL OR seller='')""").fetchall()
        for rid, rj in rows:
            try:
                x = json.loads(rj or "{}")
            except Exception:
                continue
            nm = found.get(x.get("asin"))
            if not nm:
                continue
            x["seller_name"] = nm
            pend.append((f"amazon_{nm}", json.dumps(x, ensure_ascii=False), rid))
        if pend:
            c.executemany("UPDATE raw_listings SET seller=?, raw_json=? WHERE id=?", pend)

    return {"ok": True, "asins_tried": len(asins), "names_found": len(found),
            "rows_updated": len(pend), "pending": len(_todo(10**9))}
