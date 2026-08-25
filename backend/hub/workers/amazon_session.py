"""Lấy HTML Amazon bằng phiên trình duyệt thật — không cần anti-detect browser.

Gõ thẳng /s?k=... bị chặn 503, nên đi vòng: vào trang chủ để nhận cookie phiên
trước, rồi gõ từ khoá vào ô #twotabsearchtextbox và Enter. Giữ một phiên cho
nhiều keyword và giãn nhịp giữa các lần search để tránh bị chặn.
"""
from __future__ import annotations
import asyncio
import json
import random
import time

import httpx

from pathlib import Path

# Lưu phiên để tái dùng cookie thay vì xin mới mỗi lần chạy -> ít bị nghi.
STATE = Path(__file__).resolve().parents[2] / ".auth" / "amazon.json"

HOME = "https://www.amazon.com/"
SEARCH_BOX = "#twotabsearchtextbox"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# HTML trang chặn chỉ ~2.7KB; trang thật hàng trăm KB
MIN_OK_BYTES = 100_000


# Trần thời gian cho cả lượt để một keyword kẹt không treo mãi.
MAX_TOTAL_S = 600          # 10 phút cho cả lô
MAX_PER_KW_S = 45          # 45 giây cho một keyword


async def _run(keywords: list[str], delay: float = 3.0) -> dict[str, str]:
    import time as _t
    from playwright.async_api import async_playwright

    t0 = _t.monotonic()
    out: dict[str, str] = {}
    async with async_playwright() as p:
        # Chrome THẬT: Google/Amazon phân biệt được với Chromium đi kèm Playwright
        browser = await p.chromium.launch(channel="chrome", headless=True)
        ctx = await browser.new_context(
            locale="en-US", user_agent=UA,
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            storage_state=str(STATE) if STATE.exists() else None,
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()

        # ── bước 1: lấy cookie phiên từ trang chủ
        try:
            await page.goto(HOME, timeout=45000)
            await page.wait_for_timeout(2000)
        except Exception:
            await browser.close()
            return out

        for i, kw in enumerate(keywords):
            if _t.monotonic() - t0 > MAX_TOTAL_S:
                break                      # hết giờ -> trả về những gì đã lấy
            try:
                if i:
                    # quay lại trang chủ + nhịp ngẫu nhiên cho giống người dùng thật
                    await page.goto(HOME, timeout=45000)
                    await page.wait_for_timeout(int(delay * 1000 * random.uniform(1.0, 2.6)))
                await page.fill(SEARCH_BOX, kw)
                await page.press(SEARCH_BOX, "Enter")
                await page.wait_for_timeout(3500)
                try:
                    await page.wait_for_selector("[data-asin]", timeout=6000)
                except Exception:
                    pass
                # cuộn nhẹ để trang lazy-load ảnh phía dưới
                try:
                    await page.mouse.wheel(0, 1400)
                    await page.wait_for_timeout(900)
                except Exception:
                    pass
                html = await page.content()
                if html and len(html) >= MIN_OK_BYTES and "data-asin" in html:
                    out[kw] = html
                elif html and len(html) < MIN_OK_BYTES:
                    break          # gặp trang chặn -> dừng ngay
            except Exception:
                continue

        # lưu phiên cho lần sau
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            await ctx.storage_state(path=str(STATE))
        except Exception:
            pass
        await browser.close()
    return out


# ── ĐƯỜNG NHANH: dùng lại cookie của phiên Chrome, gọi bằng httpx ──
# Nhanh hơn nhiều so với mở Chrome mỗi keyword; Chrome chỉ còn dùng để lấy
# cookie lần đầu (hoặc khi cookie hết hạn).
UA_HTTP = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _cookies_from_state() -> dict:
    """Đọc cookie amazon từ storage_state đã lưu."""
    if not STATE.exists():
        return {}
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {c["name"]: c["value"] for c in st.get("cookies", [])
            if "amazon" in (c.get("domain") or "")}


def fetch_fast(keywords: list[str], delay: float = 1.2) -> dict[str, str]:
    """Cào bằng httpx + cookie phiên. Trả {keyword: html}, thiếu thì vắng mặt."""
    import urllib.parse as _up

    ck = _cookies_from_state()
    if not ck:
        return {}
    out: dict[str, str] = {}
    with httpx.Client(headers=UA_HTTP, cookies=ck, timeout=25,
                      follow_redirects=True) as cli:
        for kw in keywords:
            try:
                r = cli.get("https://www.amazon.com/s?k=" + _up.quote_plus(kw))
                if (r.status_code == 200 and len(r.text) >= MIN_OK_BYTES
                        and "data-asin" in r.text):
                    out[kw] = r.text
                else:
                    break          # bị chặn -> dừng, để phiên Chrome làm lại
            except Exception:
                continue
            time.sleep(delay * random.uniform(0.7, 1.6))
    return out


def fetch_search_html(keywords: list[str], delay: float = 3.0) -> dict[str, str]:
    """Trả {keyword: html trang tìm kiếm}. Keyword nào fail thì vắng mặt.

    Thứ tự: httpx + cookie đã lưu -> Chrome thật cho phần còn thiếu (Chrome
    vừa làm dự phòng vừa làm mới cookie).
    """
    fast = fetch_fast(keywords)
    remain = [k for k in keywords if k not in fast]
    if not remain:
        return fast
    try:
        fast.update(asyncio.run(_run(remain, delay)))
        return fast
    except RuntimeError:                    # đã có event loop (FastAPI async)
        loop = asyncio.new_event_loop()
        try:
            fast.update(loop.run_until_complete(_run(remain, delay)))
            return fast
        finally:
            loop.close()
