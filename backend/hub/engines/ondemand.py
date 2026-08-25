"""Kéo dữ liệu thật cho một keyword — dùng khi người dùng tra thứ chưa có trong DB.

Mỗi bước gọi và ghi thật:
  ① Etsy Open API   — listing, giá, favorites, ngày đăng
  ② Ảnh Etsy        — /listings/{id}/images cho listing vừa lấy
  ③ Amazon          — nguồn thứ hai (có `bought_past_month` = số bán thật)
  ④ Google Trends   — chuỗi 12 tháng (có thể fail)
  ⑤ Lưu             — raw_listings + trends_cache, rồi unify sang listings_unified

Mặc định 25 listing/sàn cho tra cứu tương tác. Mỗi bước có timeout riêng và fail
độc lập; `sources` ghi rõ nguồn nào có dữ liệu.
"""
from __future__ import annotations
import json
import time

from .. import db
from ..ingestion import etsy_images, gtrends
from ..workers.base import run_worker
from ..workers.etsy_worker import EtsyWorker

DEFAULT_LIMIT = 25


def _count(keyword: str) -> dict:
    with db.connect() as c:
        et = c.execute("SELECT COUNT(*) FROM raw_listings WHERE platform='etsy' AND keyword=?",
                       (keyword,)).fetchone()[0]
        am = c.execute("SELECT COUNT(*) FROM raw_listings WHERE platform='amazon' AND keyword=?",
                       (keyword,)).fetchone()[0]
    return {"etsy": et, "amazon": am}


def pull(keyword: str, limit: int = DEFAULT_LIMIT,
         with_amazon: bool = True) -> dict:
    """Kéo thật cho 1 keyword. Trả từng bước kèm thời gian ĐO ĐƯỢC."""
    kw = " ".join((keyword or "").strip().lower().split())
    if not kw:
        return {"ok": False, "error": "keyword rỗng"}

    steps: list[dict] = []
    t_all = time.time()

    def _friendly(err: str) -> str:
        """Đổi lỗi kỹ thuật thành câu người đọc hiểu được."""
        e = (err or "").lower()
        if "429" in e or "too many requests" in e:
            return "Sàn này tạm khoá vì hôm nay đã tra quá nhiều — thử lại sau ít phút"
        if "timeout" in e or "timed out" in e:
            return "Sàn này phản hồi chậm quá nên bỏ qua, các nguồn khác vẫn có"
        if "401" in e or "403" in e or "api key" in e:
            return "Chưa kết nối được với sàn này"
        return "Sàn này tạm thời không lấy được dữ liệu"

    def step(name, detail, fn):
        t0 = time.time()
        try:
            out = fn()
            ok, err = True, None
            # worker trả về status=error thay vì ném exception
            if isinstance(out, dict) and out.get("status") == "error":
                ok = False
                err = "; ".join(out.get("errors") or [])[:200]
            elif isinstance(out, dict) and out.get("n_items") == 0:
                ok = False
                err = "không tìm thấy sản phẩm nào"
        except Exception as e:                       # noqa: BLE001
            out, ok, err = None, False, str(e)[:200]
        steps.append({"step": name, "detail": detail, "ok": ok,
                      "took_s": round(time.time() - t0, 2),
                      "note": _friendly(err) if err else None,
                      "error": err, "result": out})
        return out

    before = _count(kw)

    # ① Etsy
    step("AI đang tìm sản phẩm trên Etsy", "Xem ai đang bán, giá bao nhiêu, bán từ khi nào",
         lambda: run_worker(EtsyWorker(), [kw], limit=limit))

    # ② Ảnh Etsy — chỉ cho listing của KEYWORD này
    def _imgs():
        rows = [r for r in db.get_listings(platform="etsy", limit=4000)
                if r.get("keyword") == kw]
        return etsy_images.enrich_rows(rows)
    step("AI đang tải ảnh sản phẩm", "Lấy hình để bạn xem mẫu mã đối thủ", _imgs)

    # ③ Amazon — nguồn thứ hai, có bought_past_month = số bán THẬT
    if with_amazon:
        def _amz():
            from ..workers.amazon_worker import AmazonWorker
            w = AmazonWorker()
            w.fast = True          # bỏ bước mở trang /dp từng sản phẩm
            return run_worker(w, [kw], limit=limit)
        step("AI đang đối chiếu bên Amazon", "Xem sàn thứ hai bán được bao nhiêu", _amz)

    # ④ Google Trends — có thể fail, KHÔNG chặn các bước khác
    def _tr():
        series, labels, source = gtrends.fetch_series(kw)
        if series:
            db.set_trend(kw, series, source, labels=labels)
            return {"points": len(series), "source": source}
        return {"points": 0, "source": "unavailable"}
    step("AI đang xem xu hướng 12 tháng", "Người Mỹ tìm từ khoá này nhiều hay ít", _tr)

    # ⑤ Chuẩn hoá chỉ keyword này, không dựng lại cả bảng: unify.rebuild() ghi
    # lại toàn bộ ~33.000 dòng nên quá chậm cho tra cứu tương tác.
    def _unify_one():
        from . import unify
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = [r for r in db.get_listings(limit=8000) if r.get("keyword") == kw]
        if not rows:
            return {"rows": 0}
        with db.connect() as c:
            c.executescript(unify.SCHEMA)
            c.executemany(
                f"INSERT OR REPLACE INTO listings_unified "
                f"VALUES ({','.join('?' * unify.COLS)})",
                [unify._row(r, day) for r in rows])
        return {"rows": len(rows)}
    step("AI đang sắp xếp lại cho bạn", "Gộp hai sàn, bỏ trùng rồi lưu lại", _unify_one)

    after = _count(kw)
    rows = [r for r in db.get_listings(limit=6000) if r.get("keyword") == kw]

    n_img = n_sold = 0
    prices = []
    sample = []
    for r in rows:
        try:
            x = json.loads(r.get("raw_json") or "{}")
        except Exception:
            x = {}
        img = x.get("image")
        if img:
            n_img += 1
        s = x.get("bought_past_month") or x.get("units_real") or r.get("est_sales") or 0
        if s:
            n_sold += 1
        p = r.get("price") or 0
        if 0 < p <= 500:
            prices.append(p)
        if len(sample) < 8:
            sample.append({"title": (r.get("title") or "")[:80],
                           "price": r.get("price"), "platform": r.get("platform"),
                           "seller": r.get("seller"), "image": img,
                           "url": r.get("url"), "est_sales": s})

    series, tsrc = gtrends.cached_series(kw)
    prices.sort()

    return {
        "ok": True, "keyword": kw,
        "took_s": round(time.time() - t_all, 2),
        "steps": steps,
        "before": before, "after": after,
        "added": {"etsy": after["etsy"] - before["etsy"],
                  "amazon": after["amazon"] - before["amazon"]},
        "coverage": {
            "n_listings": len(rows),
            "with_image": n_img,
            "with_sales": n_sold,
            "price_median": prices[len(prices) // 2] if prices else None,
            "trends_points": len(series),
            "trends_source": tsrc,
        },
        # Nguồn nào thực sự có dữ liệu
        "sources": {
            "etsy": after["etsy"] > 0,
            "amazon": after["amazon"] > 0,
            "google_trends": bool(series),
        },
        "sample": sample,
    }
