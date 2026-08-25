"""Amazon Worker — cào listing qua browser backend (anti-detect/Playwright).

Cào trang search public amazon.com/s?k=<keyword>, parse product card.
Amazon chặn bot mạnh → dùng anti-detect browser (rẻ + tránh ban) là tối ưu.
"""
from __future__ import annotations
import re
import time
import urllib.parse
from .base import BaseWorker
from . import browser
from ..config import get_settings


def _fetch_seller(asin: str) -> tuple[str | None, str | None]:
    """Vào trang /dp/<asin> lấy (seller thật, brand). Amazon lộ seller ở trang chi tiết."""
    html, _ = browser.get_html(f"https://www.amazon.com/dp/{asin}")
    if not html:
        return None, None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        seller = None
        el = soup.select_one("#sellerProfileTriggerId")
        if el:
            seller = el.get_text(strip=True) or None
        brand = None
        b = soup.select_one("#bylineInfo")
        if b:
            brand = re.sub(r"^(Brand:|Visit the)\s*|\s*Store$", "", b.get_text(strip=True)).strip() or None
        return seller, brand
    except Exception:
        return None, None

VND_PER_USD = 25400.0    # tỉ giá xấp xỉ để quy đổi giá VND (Amazon serve theo IP VN) -> USD


def _parse_price(text: str) -> tuple[float | None, str]:
    """Parse '$24.99' hoặc 'VND 260,759' -> (amount_usd, currency)."""
    if not text:
        return None, ""
    is_vnd = "VND" in text.upper() or "₫" in text
    m = re.search(r"([0-9][0-9.,]*)", text)
    if not m:
        return None, ""
    num = m.group(1)
    # VND dùng '.'/',' làm phân cách nghìn -> bỏ hết; USD giữ '.' thập phân
    if is_vnd:
        val = float(re.sub(r"[^0-9]", "", num))
        return round(val / VND_PER_USD, 2), "VND->USD"
    return (float(num.replace(",", "")), "USD") if num else (None, "")


def _img(card) -> str | None:
    """Ảnh sản phẩm. Amazon dùng nhiều lớp markup tuỳ loại card
    (thường / sponsored / video), nên thử lần lượt nhiều selector."""
    for sel in ("img.s-image", "img[data-image-latency]",
                "img[srcset*='media-amazon']", "img[src*='media-amazon']",
                ".s-product-image-container img", "img"):
        el = card.select_one(sel)
        if not el:
            continue
        src = el.get("src") or el.get("data-src")
        if not src:
            # srcset: "url1 1x, url2 2x" -> lấy url đầu
            ss = el.get("srcset") or ""
            src = ss.split(",")[0].strip().split(" ")[0] if ss else None
        if src and src.startswith("http") and "media-amazon" in src:
            return src
    return None


def _parse_bought(text: str) -> int | None:
    """Parse '1K+ bought in past month' -> 1000; '900+' -> 900; '2.5K+' -> 2500."""
    m = re.search(r"([0-9][0-9.,]*)\s*([KkMm]?)\+?\s*bought in past month", text)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = {"k": 1000, "m": 1_000_000}.get(m.group(2).lower(), 1)
    return int(num * mult)


def _parse_search_html(html: str, limit: int) -> list[dict]:
    """Parse product card từ HTML search Amazon: title, giá, rating, review, bought/tháng."""
    items: list[dict] = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        for m in re.finditer(r'data-asin="([A-Z0-9]{10})"', html):
            items.append({"title": None, "url": f"https://www.amazon.com/dp/{m.group(1)}",
                          "raw": {"asin": m.group(1)}})
            if len(items) >= limit:
                break
        return items

    soup = BeautifulSoup(html, "html.parser")
    for c in soup.select("div[data-asin]"):
        asin = c.get("data-asin")
        if not asin:
            continue
        title_el = c.select_one("h2 span") or c.select_one("h2 a span")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            continue
        card_text = c.get_text(" ", strip=True)

        # Giá: span.a-price > a-offscreen (lấy cái đầu, tránh gộp list-price)
        price, cur = None, ""
        off = c.select_one("span.a-price span.a-offscreen")
        if off:
            price, cur = _parse_price(off.get_text())
        if price is not None and (price < 0.3 or price > 5000):
            price = None

        # Rating
        rating = None
        rat = c.select_one("span.a-icon-alt")
        if rat:
            rm = re.search(r"([0-9.]+) out of 5", rat.get_text())
            rating = float(rm.group(1)) if rm else None

        # Review count: thử aria-label rồi fallback regex trên text card
        reviews = None
        rev = c.select_one("[aria-label*='rating']")
        if rev and rev.get("aria-label"):
            rn = re.sub(r"[^0-9]", "", rev["aria-label"])
            reviews = int(rn) if rn else None
        if reviews is None:
            rm = re.search(r"\b([0-9][0-9,]{0,6})\s+ratings?\b", card_text)
            if rm:
                reviews = int(rm.group(1).replace(",", ""))

        # Sponsored: kết quả trả tiền, không phải thứ hạng tự nhiên.
        sponsored = bool(c.select_one("[data-component-type='sp-sponsored-result']")
                         or "Sponsored" in card_text[:120])

        # Giá gạch (list price) -> tỷ lệ giảm giá. Ngách phải phá giá = biên mỏng.
        list_price = None
        lp = c.select_one("span.a-price.a-text-price span.a-offscreen")
        if lp:
            list_price, _ = _parse_price(lp.get_text())
            if list_price is not None and (list_price < 0.3 or list_price > 5000):
                list_price = None

        # Bought in past month = tín hiệu bán THẬT (ưu tiên làm est_sales)
        bought = _parse_bought(card_text)
        est = bought if bought is not None else min(int((reviews or 0) * 0.08), 4000)

        # Brand (best-effort) làm seller — Amazon không lộ seller ổn định trên
        # trang search. Thử nhiều selector và loại bỏ các badge (không phải tên shop).
        brand = None
        _BADGE = ("amazon's choice", "best seller", "overall pick", "sponsored",
                  "limited time deal", "climate pledge")
        for sel in ("h2 .a-size-base-plus",
                    "span.a-size-base-plus.a-color-base",
                    "h5 .a-size-base-plus",
                    ".s-line-clamp-1 span",          # dòng "Brand" dưới tiêu đề
                    "[data-cy='title-recipe'] .a-size-base-plus"):
            bel = c.select_one(sel)
            if not bel:
                continue
            bt = (bel.get_text(strip=True) or "").strip()
            low = bt.lower()
            if not bt or len(bt) > 40:
                continue
            if low == (title or "").lower():
                continue
            if any(b in low for b in _BADGE):        # badge, không phải tên shop
                continue
            brand = bt
            break

        items.append({
            "title": title, "price": price, "currency": cur or "USD",
            "favorites": None, "reviews": reviews, "est_sales": est,
            "seller": f"amazon_{brand}" if brand else None,
            "url": f"https://www.amazon.com/dp/{asin}",
            "tags": [],
            "raw": {"asin": asin, "rating": rating, "bought_past_month": bought,
                    "brand": brand, "image": _img(c),
                    "sponsored": sponsored, "list_price": list_price,
                    "fetch_tier": "session",
                    "discount_pct": (round((list_price - price) / list_price * 100)
                                     if list_price and price and list_price > price else None),
                    # link store của brand trên Amazon (nếu có)
                    "shop_url": (f"https://www.amazon.com/s?k={urllib.parse.quote_plus(brand)}"
                                 if brand else None)},
        })
        if len(items) >= limit:
            break
    return items


def crawl_batch(keywords: list[str], limit: int = 40) -> dict:
    """Cào nhiều keyword bằng một phiên Chrome (mở Chrome 1 lần rồi search
    liên tiếp) — nhanh hơn nhiều so với mở Chrome mới mỗi keyword.
    """
    from . import amazon_session
    from .. import db

    run_id = db.start_run("amazon", keywords, "chrome-session-batch")
    total, errors = 0, []
    try:
        htmls = amazon_session.fetch_search_html(keywords)
        m_re = re.compile(r"([0-9][0-9,]{2,})\s*results")
        for kw, html in htmls.items():
            try:
                m = m_re.search(html)
                total_results = int(m.group(1).replace(",", "")) if m else None
                items = _parse_search_html(html, limit)
                for r, it in enumerate(items):
                    it.setdefault("keyword", kw)
                    it.setdefault("rank", r + 1)
                    it.setdefault("raw", {})["total_results"] = total_results
                total += db.insert_listings(items, "amazon")
            except Exception as e:  # noqa
                errors.append(f"{kw}: {e}")
        missed = [k for k in keywords if k not in htmls]
        if missed:
            errors.append(f"không lấy được HTML: {len(missed)} keyword")
        status = "done" if total else "error"
        db.finish_run(run_id, total, status=status, note="; ".join(errors)[:500])
    except Exception as e:  # noqa
        db.finish_run(run_id, total, status="error", note=str(e)[:500])
        errors.append(str(e))
        status = "error"
    return {"run_id": run_id, "n_items": total, "status": status,
            "keywords": len(keywords), "ok": len(keywords) - len(errors), "errors": errors[:5]}


class AmazonWorker(BaseWorker):
    platform = "amazon"

    def __init__(self):
        self.backend_name = browser.active_backend()

    def fetch(self, keyword: str, limit: int) -> list[dict]:
        # ĐƯỜNG CHÍNH: phiên trình duyệt thật (trang chủ -> ô tìm kiếm).
        # Gõ thẳng /s?k= luôn bị 503; đi qua trang chủ để nhận cookie phiên thì được.
        html, backend = None, None
        try:
            from . import amazon_session
            got = amazon_session.fetch_search_html([keyword])
            if got.get(keyword):
                html, backend = got[keyword], "chrome-session"
        except Exception:
            pass
        # DỰ PHÒNG: đường cũ (thường 503, giữ lại phòng khi Amazon nới)
        if not html:
            url = "https://www.amazon.com/s?k=" + urllib.parse.quote_plus(keyword)
            html, backend = browser.get_html(url)
        self.backend_name = backend
        if not html:
            raise RuntimeError("Không lấy được HTML Amazon (backend: %s)" % backend)
        if "robot" in html.lower() and "captcha" in html.lower():
            raise RuntimeError("Amazon chặn bot (captcha). Cần anti-detect browser.")
        # Tổng kết quả của keyword (vd "10,000 results") = quy mô cạnh tranh THẬT,
        # khác hẳn việc chỉ đếm 40 listing cào được.
        m_tot = re.search(r"([0-9][0-9,]{2,})\s*results", html)
        total_results = int(m_tot.group(1).replace(",", "")) if m_tot else None

        items = _parse_search_html(html, limit)
        for it in items:
            it.setdefault("raw", {})["total_results"] = total_results
        if not items:
            raise RuntimeError("Parse 0 sản phẩm (có thể bị chặn hoặc đổi layout).")

        # Enrich tên shop thật cho mọi sản phẩm (vào trang /dp lấy 'Sold by').
        # `fast=True` bỏ qua bước này vì mỗi ASIN là một lượt mở trang + sleep,
        # quá chậm cho tra cứu tương tác.
        if getattr(self, "fast", False):
            return items
        if get_settings().crawl_amazon_fetch_seller:
            delay = min(get_settings().crawl_delay_seconds, 2.0)
            for it in items:
                asin = (it.get("raw") or {}).get("asin")
                if not asin:
                    continue
                seller, brand = _fetch_seller(asin)
                name = seller or brand
                if name:
                    it["seller"] = f"amazon_{name}"
                    it["raw"]["seller_name"] = seller
                    it["raw"]["brand"] = brand or it["raw"].get("brand")
                time.sleep(delay)
        return items
