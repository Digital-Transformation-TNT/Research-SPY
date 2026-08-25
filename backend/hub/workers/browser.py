"""Browser backend cho các sàn cần render/anti-bot (Amazon...).

Thứ tự ưu tiên (tối ưu chi phí + chống ban):
1. Anti-detect browser (AdsPower/GoLogin) — mở profile qua local API → CDP → Playwright connect.
2. Playwright thường (headless Chromium) — fallback khi chưa có acc anti-detect.
3. httpx GET (fallback cuối) — nhẹ nhất nhưng dễ bị chặn.

Tất cả import đều lazy để app không crash khi thiếu Playwright.
"""
from __future__ import annotations
import httpx
from ..config import get_settings

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def active_backend() -> str:
    s = get_settings()
    if s.antidetect_provider.strip():
        return f"antidetect:{s.antidetect_provider}"
    if _playwright_available():
        return "playwright"
    return "httpx"


def _playwright_available() -> bool:
    try:
        import playwright  # noqa
        return True
    except Exception:
        return False


# ---------- Anti-detect: mở profile, lấy CDP endpoint ----------
def _adspower_cdp() -> str | None:
    s = get_settings()
    try:
        r = httpx.get(f"{s.antidetect_api}/api/v1/browser/start",
                      params={"user_id": s.antidetect_profile_id}, timeout=30)
        data = r.json().get("data", {})
        return (data.get("ws") or {}).get("puppeteer")   # CDP ws endpoint
    except Exception:
        return None


def get_html(url: str) -> tuple[str | None, str]:
    """Trả (html, backend_dùng). html=None nếu thất bại."""
    s = get_settings()

    # 1. Anti-detect + Playwright over CDP
    if s.antidetect_provider.strip() and _playwright_available():
        cdp = _adspower_cdp() if s.antidetect_provider == "adspower" else None
        if cdp:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(cdp)
                    page = browser.contexts[0].new_page() if browser.contexts else browser.new_page()
                    page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    html = page.content()
                    page.close()
                    return html, f"antidetect:{s.antidetect_provider}"
            except Exception as e:  # noqa
                pass

    # 2. Playwright — ưu tiên Chrome thật (channel="chrome"), vì Google/Amazon
    # phân biệt được với Chromium đi kèm và trả trang rỗng cho bản đi kèm.
    # Rơi về Chromium khi máy không cài Chrome.
    if _playwright_available():
        for channel in ("chrome", None):
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    opts = {"headless": True}
                    if channel:
                        opts["channel"] = channel
                    browser = p.chromium.launch(**opts)
                    ctx = browser.new_context(
                        user_agent=UA, locale="en-US",
                        viewport={"width": 1366, "height": 900},
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                    )
                    page = ctx.new_page()
                    # ẩn dấu hiệu tự động hoá rõ nhất
                    page.add_init_script(
                        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
                    page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_selector("[data-asin]", timeout=6000)
                    except Exception:
                        pass          # không phải trang Amazon thì bỏ qua
                    html = page.content()
                    browser.close()
                    # HTML quá ngắn = trang chặn rỗng -> thử kênh tiếp theo
                    if html and len(html) > 20000:
                        return html, f"playwright:{channel or 'chromium'}"
            except Exception:
                continue

    # 3. httpx (dễ bị chặn, chỉ là fallback cuối)
    try:
        r = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=True)
        return r.text, "httpx"
    except Exception:
        return None, "none"
