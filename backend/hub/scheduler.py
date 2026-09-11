"""Lịch chạy nền — làm tươi toàn bộ database mỗi đêm.

LỊCH ĐÊM (giờ máy chủ):
  02:00  discover  quét keyword mới từ Google Trends  -> discovered_keywords
  02:40  listings  cào Etsy/Amazon                    -> raw_listings
  03:30  trends    lấy chuỗi 12 điểm qua Chrome thật  -> trends_cache
  03:50  unify     chuẩn hoá 2 sàn về 1 lược đồ       -> listings_unified
  04:00  report    sinh báo cáo ngày                  -> reports
  05:00  sigtrends chuỗi Trends ngày+tuần (Hub ①)     -> trends_daily
  05:40  sigsnap   chụp listing theo từ khoá (Hub ②)    -> listings_snapshot
  01:00  sigcat    top 100 mỗi ngành shopee, vn ‖ ph song song -> listings_snapshot + crawl_log
         (đo 11/09: ~3h50, xong ~04:50 — trước giờ làm việc 08:30)
  09:00  sig1688   top bán chạy 205 ngành trên 1688 (~18 phút)  -> listings_snapshot + crawl_log
         (đầu giờ làm việc CÓ CHỦ Ý: 1688 đòi giải slider định kỳ, cần người trực)

Tắt bằng biến môi trường: SCHEDULER_ENABLED=0
Chạy ngay một lần: POST /api/scheduler/run?job=all
"""
from __future__ import annotations
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger("scheduler")

# giờ chạy (0-23) cho từng job
# `shopnames` chạy trước `unify` để tên shop kịp vào cột chuẩn hoá `shop_name`.
HOURS = {"discover": 2, "listings": 2, "sales": 3, "shopnames": 3, "trends": 3,
         "unify": 3, "report": 4,
         "sigtrends": 5, "sigsnap": 5, "sigcat": 1, "sig1688": 9}
MINUTES = {"discover": 0, "listings": 40, "sales": 10, "shopnames": 20,
           "trends": 30, "unify": 50, "report": 0,
           "sigtrends": 0, "sigsnap": 40, "sigcat": 0, "sig1688": 0}

# giới hạn mỗi đêm — đủ tươi mà không đụng trần quota
MAX_SEEDS = 96          # hạt giống từ catalog
MAX_CRAWL_KW = 250      # keyword cào Etsy mỗi đêm
MAX_TRENDS_KW = 200     # keyword lấy chuỗi mỗi đêm
MAX_SHOPNAMES = 1500    # ASIN lấy tên shop mỗi đêm (Amazon)
STALE_DAYS = 3          # listing cũ hơn ngần này thì cào lại


def _enabled() -> bool:
    return os.environ.get("SCHEDULER_ENABLED", "1") != "0"


# ─────────────────────── các job ───────────────────────
def job_discover() -> dict:
    """Quét keyword mới từ Google Trends -> discovered_keywords."""
    import asyncio
    from .ingestion import seedgen
    from . import db
    sd = seedgen.seeds(MAX_SEEDS)
    exp = asyncio.run(seedgen.expand(sd, "US"))
    saved = db.save_discovered(exp["keywords"])
    return {"job": "discover", "seeds": len(sd), "unique": exp["unique"], "saved": saved}


def _target_keywords(limit: int) -> list[str]:
    """Keyword đáng cào: đã lọc nhiễu, có dính catalog, ưu tiên chưa cào/cũ."""
    from .ingestion import signals
    from . import db
    known = signals._known_terms()
    clean: list[str] = []
    for r in db.list_discovered(limit=3000):
        kw = r["keyword"]
        if signals._is_noise(kw):
            continue
        w = set(kw.split())
        if not (w & known) or len(w) > 5:
            continue
        clean.append(kw)
    clean = list(dict.fromkeys(clean))

    with db.connect() as c:
        rows = c.execute(
            "SELECT keyword, MAX(crawled_at) FROM raw_listings GROUP BY keyword").fetchall()
    last = {r[0]: r[1] for r in rows}
    cutoff = (datetime.utcnow() - timedelta(days=STALE_DAYS)).isoformat()

    never = [k for k in clean if k not in last]              # chưa cào bao giờ
    stale = [k for k in clean if last.get(k, "") < cutoff and k in last]
    return (never + stale)[:limit]


def job_listings() -> dict:
    """★ Cào Etsy -> raw_listings. Bảng gốc của mọi con số tiền."""
    from .workers.etsy_worker import EtsyWorker
    from .workers.base import run_worker
    from . import db
    todo = _target_keywords(MAX_CRAWL_KW)
    total, fail = 0, 0
    for i in range(0, len(todo), 10):
        try:
            r = run_worker(EtsyWorker(), todo[i:i + 10])
            total += r.get("n_items") or 0
        except Exception as e:  # noqa
            fail += 1
            log.warning("crawl lô %s lỗi: %s", i // 10 + 1, e)
        time.sleep(1)
    return {"job": "listings", "keywords": len(todo), "items": total,
            "failed_batches": fail, "db": db.counts()}


def job_trends() -> dict:
    """Chuỗi 12 điểm qua Chrome thật -> trends_cache. pytrends đã chết (429)."""
    from .ingestion import trends_browser as tb
    from . import db
    with db.connect() as c:
        have = {r[0] for r in c.execute("SELECT keyword FROM trends_cache")}
        kws = [r[0] for r in c.execute("SELECT DISTINCT keyword FROM raw_listings")]
    todo = [k for k in kws if k not in have][:MAX_TRENDS_KW]
    n = 0
    for i in range(0, len(todo), 10):
        try:
            got = tb.fetch_series_many(todo[i:i + 10])
            for kw, s in got.items():
                if s:
                    db.set_trend(kw, s, "gtrends")
                    n += 1
        except Exception as e:  # noqa
            log.warning("trends lô %s lỗi: %s", i // 10 + 1, e)
    return {"job": "trends", "requested": len(todo), "saved": n}


def job_report() -> dict:
    """Sinh báo cáo ngày -> reports."""
    from .engines import analysis, market
    from . import db
    try:
        mk = market.analyze(8000)
        rows = analysis.build_keyword_table(db.get_listings(limit=8000), top=30)
        title = f"Báo cáo ngày {datetime.utcnow():%Y-%m-%d}"
        body = [f"# {title}", "",
                f"- Listing: {mk['summary']['n_listings']:,} · có đơn "
                f"{mk['summary']['n_sold']:,} ({100 - mk['summary']['dead_pct']}%)",
                f"- Doanh thu 30 ngày: ${mk['summary']['revenue_30d']:,}",
                f"- Shop đang bán: {mk['summary']['n_shops']:,}", "", "## Top keyword"]
        for r in rows[:15]:
            body.append(f"- {r.get('keyword')} — opp {r.get('opp')}")
        db.save_report("daily", title, "\n".join(body))
        return {"job": "report", "keywords": len(rows)}
    except Exception as e:  # noqa
        return {"job": "report", "error": str(e)[:120]}


def job_sales() -> dict:
    """Làm giàu Etsy: số bán THẬT (/shops) + ẢNH (/listings/batch).

    Cả hai đều là thứ findAllListingsActive không trả, phải gọi endpoint riêng.
    Gộp chung một job vì cùng đọc một tập listing.
    """
    from .ingestion import etsy_sales, etsy_images
    from . import db
    rows = [r for r in db.get_listings(platform="etsy", limit=20000)]
    sales = etsy_sales.enrich_rows(rows, max_shops=2000)
    imgs = etsy_images.enrich_rows(rows)
    return {"job": "sales", "sales": sales, "images": imgs}


def job_unify() -> dict:
    """Chuẩn hoá 2 sàn về listings_unified — lớp đọc cho AI và báo cáo."""
    from .engines import unify
    return {"job": "unify", **unify.rebuild()}


def job_shopnames() -> dict:
    """Lấy tên shop thật cho cả 2 sàn, nạp vào cột chuẩn hoá `shop_name`.
    Chạy trước `unify` để tên kịp vào bảng chuẩn hoá cùng đêm.
    """
    from .ingestion import amazon_shops, etsy_shops
    out = {"job": "shopnames"}
    try:
        out["amazon"] = amazon_shops.fetch_names(limit=MAX_SHOPNAMES, workers=6)
    except Exception as e:                                   # noqa: BLE001
        out["amazon"] = {"ok": False, "reason": str(e)[:120]}
    try:
        out["etsy"] = etsy_shops.fetch_names()
    except Exception as e:                                   # noqa: BLE001
        out["etsy"] = {"ok": False, "reason": str(e)[:120]}
    return out


# ─────────────── Trend Signal Hub (phần ① và ②) ───────────────
# Hai job này đọc DANH SÁCH THEO DÕI (`signal_config` scope `watchlist`) chứ không tự đoán
# từ khoá như `_target_keywords` phía trên — cái đó lấy hạt giống từ catalog Printway, một
# nguồn mà Hub mới không còn dùng.
#
# CHẠY MỖI NGÀY LÀ ĐIỀU KIỆN SỐNG CÒN, không phải tuỳ chọn: cả `growth_long%` lẫn `spike%`
# đều là HIỆU giữa hai lần chụp. Bỏ một đêm là thủng một mốc, và `_upd_series` sẽ chia đều
# lượng bán của hai ngày ra — làm phẳng đúng cú đột biến mà bảng sinh ra để bắt.
def job_sigtrends() -> dict:
    """Chuỗi Google Trends ngày + tuần cho danh sách theo dõi -> trends_daily."""
    from .ingestion import trends_daily
    from .signal import store as sig_store
    wl = sig_store.get_config("watchlist") or {}
    kws = (wl.get("keywords") or [])[:MAX_TRENDS_KW]
    if not kws:
        return {"job": "sigtrends", "skipped": True,
                "reason": "danh sách theo dõi trống — khai ở mục Tín hiệu Trends"}
    out = trends_daily.refresh(kws, geo=wl.get("geo") or "VN",
                               region=wl.get("region") or "ALL",
                               anchor=(wl.get("anchor") or None))
    return {"job": "sigtrends", **out}


def job_sigcat() -> dict:
    """
    Chụp top bán chạy TỪNG DANH MỤC -> listings_snapshot. Nguồn của bảng Top 10.

    Thị trường lấy từ `shopee_categories`, KHÔNG từ `watchlist`. Watchlist là danh sách từ
    khoá theo dõi; trước đây job này bám vào nó nên chỉ chạy `ph` — vn không có mặt trong
    watchlist thì 206 ngành của vn không bao giờ được cào, mà không có gì báo ra cả.
    """
    import asyncio
    from .ingestion import market_snapshot, shopee_categories
    markets = shopee_categories.markets()
    if not markets:
        return {"job": "sigcat", "markets": 0, "runs": [],
                "error": "chưa nạp danh mục — chạy"
                         " `python -m hub.ingestion.shopee_categories`"}
    # CÁC THỊ TRƯỜNG CHẠY SONG SONG, và đây là kết luận từ phép đo chứ không phải phỏng đoán.
    #
    # Đo 11/09/2026, 20 ngành vn ‖ 20 ngành ph cùng lúc với trang máy-thợ mở 2 luồng:
    #   40/40 ngành ok, 0 lỗi, chỉ 1 ngành hụt trang 2 (2%) — bằng đúng mức khi chạy một mình.
    #   63–69 giây một ngành, NHANH HƠN cả lúc chạy đơn hôm trước (100–119s).
    # Mốc xấu để so: vòng vn ngày 10/09 chạy cùng Trends và trang xem DB hụt 58/199 = 29%.
    # Tức thứ làm hỏng là TẢI MÁY nói chung, không phải việc hai vòng cào chạy cùng nhau.
    #
    # AN TOÀN NHỜ MỘT BẤT BIẾN: mỗi vòng cào bắn job một-cái-một và chờ xong mới bắn tiếp, nên
    # hàng đợi có nhiều nhất một job cho mỗi nguồn, và các luồng của máy-thợ luôn nhặt được
    # những tên miền khác nhau — mỗi tên miền một tab, không ai giành của ai. Bắn nhiều job của
    # CÙNG một nguồn cùng lúc sẽ làm gãy bất biến này.
    #
    # Vẫn gộp vào MỘT job thay vì ba job ở ba giờ: `_job_locks` chỉ chặn hai lượt của cùng một
    # job, hai job khác nhau không chặn nhau nên sẽ chồng lên nhau khi một cái chạy quá giờ.
    async def _song_song():
        ket = await asyncio.gather(
            *(market_snapshot.snapshot_categories(mk) for mk in markets),
            return_exceptions=True)
        return [r if not isinstance(r, BaseException) else {"market": mk, "error": str(r)[:200]}
                for mk, r in zip(markets, ket)]

    runs = list(asyncio.run(_song_song()))

    return {"job": "sigcat", "markets": len(runs), "runs": runs}


def job_sig1688() -> dict:
    """
    Cào top bán chạy theo ngành trên 1688 -> listings_snapshot. Nguồn tra GIÁ VỐN.

    CHẠY 09:00 CHỨ KHÔNG PHẢI NỬA ĐÊM, và đây là quyết định vận hành chứ không phải kỹ thuật.
    1688 đòi giải slider Baxia định kỳ: cookie `x5sec` hết hiệu lực sau vài giờ, nên một lượt
    cào lúc 00:00 không ai canh sẽ hỏng SẠCH cả 205 ngành. Đo 11/09/2026: nhịp nghỉ 4 giây giữ
    được suốt một lượt 18 phút, nhưng lượt sau đó vẫn dính `FAIL_SYS_USER_VALIDATE`.

    Đặt vào đầu giờ làm việc để có người giải một lần khi nó bật lên. Đánh đổi: dữ liệu 1688
    trễ hơn Shopee 8 tiếng — chấp nhận được, vì đây là nguồn tra giá nhập chứ không phải nguồn
    của bảng xếp hạng, không cần tươi từng đêm.

    Shopee KHÔNG dùng cơ chế này nên vẫn chạy 01:00 không cần ai trực.
    """
    import asyncio

    from .ingestion import market_snapshot
    try:
        r = asyncio.run(market_snapshot.snapshot_keyword_categories("1688", "cn"))
    except Exception as e:  # noqa
        return {"job": "sig1688", "error": str(e)[:200]}
    return {"job": "sig1688", **r}


def job_sigsnap() -> dict:
    """Chụp listing theo TỪ KHOÁ theo dõi -> listings_snapshot. Bổ sung cho `sigcat`."""
    import asyncio
    from .ingestion import market_snapshot
    from .signal import store as sig_store
    wl = sig_store.get_config("watchlist") or {}
    parts = wl.get("partitions") or []
    runs = []
    for q in parts:
        kws = q.get("keywords") or wl.get("keywords") or []
        if not kws:
            continue
        try:
            runs.append(asyncio.run(market_snapshot.snapshot(
                q.get("platform") or "shopee", q.get("market") or "vn", kws)))
        except Exception as e:  # noqa
            runs.append({"platform": q.get("platform"), "market": q.get("market"),
                         "error": str(e)[:200]})
    return {"job": "sigsnap", "partitions": len(runs), "runs": runs}


JOBS = {"discover": job_discover, "listings": job_listings, "sales": job_sales,
        "trends": job_trends, "unify": job_unify, "report": job_report,
        "shopnames": job_shopnames,
        "sigtrends": job_sigtrends, "sigsnap": job_sigsnap,
        "sigcat": job_sigcat, "sig1688": job_sig1688}


# Khoá mỗi job để hai lượt cùng job không chạy chồng nhau (nhất là `unify`).
_job_locks: dict[str, threading.Lock] = {n: threading.Lock() for n in
                                         ("discover", "listings", "sales",
                                          "trends", "unify", "report",
                                          "sigtrends", "sigsnap", "sigcat", "sig1688")}


def run_job(name: str) -> dict:
    fn = JOBS.get(name)
    if not fn:
        return {"error": f"job không tồn tại: {name}"}
    lock = _job_locks.setdefault(name, threading.Lock())
    if not lock.acquire(blocking=False):
        # Không xếp hàng: trả về ngay để người gọi biết job đang chạy.
        log.warning("scheduler %s: đang chạy, bỏ qua lượt gọi này", name)
        return {"job": name, "skipped": True,
                "reason": "job này đang chạy — bỏ qua để không ghi chồng dữ liệu"}
    t0 = time.time()
    try:
        out = fn()
    except Exception as e:  # noqa
        out = {"job": name, "error": str(e)[:200]}
    finally:
        lock.release()
    out["took_s"] = round(time.time() - t0, 1)
    log.info("scheduler %s -> %s", name, out)
    return out


def run_all() -> list[dict]:
    """Chạy tuần tự theo đúng thứ tự phụ thuộc."""
    return [run_job(n) for n in ("discover", "listings", "sales", "shopnames",
                                "trends", "unify", "report",
                                "sigtrends", "sigsnap", "sigcat", "sig1688")]


# ─────────────────────── vòng lặp lịch ───────────────────────
_last_run: dict[str, str] = {}


def _loop():
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            for name in JOBS:
                if _last_run.get(name) == today:
                    continue
                if now.hour > HOURS[name] or (now.hour == HOURS[name] and now.minute >= MINUTES[name]):
                    _last_run[name] = today          # đánh dấu trước để không chạy lại
                    run_job(name)
        except Exception as e:  # noqa
            log.warning("scheduler loop lỗi: %s", e)
        time.sleep(60)


def start():
    """Gọi trong startup của FastAPI. Chạy nền, không chặn app."""
    if not _enabled():
        log.info("scheduler tắt (SCHEDULER_ENABLED=0)")
        return
    t = threading.Thread(target=_loop, daemon=True, name="scheduler")
    t.start()
    log.info("scheduler chạy: discover 02:00 · listings 02:40 · trends 03:30 · report 04:00")


def status() -> dict:
    return {"enabled": _enabled(), "last_run": dict(_last_run),
            "schedule": {n: f"{HOURS[n]:02d}:{MINUTES[n]:02d}" for n in JOBS},
            "limits": {"seeds": MAX_SEEDS, "crawl_keywords": MAX_CRAWL_KW,
                       "trends_keywords": MAX_TRENDS_KW, "stale_days": STALE_DAYS}}
