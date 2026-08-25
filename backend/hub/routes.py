from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, Form

from .schemas import (NormalizeRequest, ScoreTitleRequest, ReportRequest,
                      CopilotRequest, CopilotResponse)
from .store import store
from .engines import normalize as norm
from .engines import scoring, aggregate, copilot, analysis, learning
from .engines import competitors as competitors_engine
from .engines import design_insight as design_engine
from .engines import report as report_engine
from .ingestion import csv_import, gtrends
from . import llm, db
from .workers.base import run_worker
from .workers.etsy_worker import EtsyWorker
from .workers.amazon_worker import AmazonWorker
from .workers import seed_worker

# Tiền tố `/api/hub` chứ không phải `/api`: router này nay sống chung app với
# `/api/ads`, `/api/imagesearch`, `/api/keywords`, `/api/media`, `/api/opportunity`.
# Trang HTML gửi đường dẫn dạng `/api/health` — `trend-signal-hub.html` tự chèn `/hub`
# vào giữa ở đúng hai chỗ `jget`/`jpost`, nên mọi đường ở đây không phải sửa.
router = APIRouter(prefix="/api/hub")

def _shop_name(row: dict) -> str | None:
    """Tên shop hiển thị được, từ một dòng raw_listings.

    Ưu tiên tên THẬT trong raw_json (shop_name/seller_name/brand), không có thì
    lấy cột seller rồi bỏ tiền tố kỹ thuật (`etsy_shop_123` -> `Shop 123`).
    Cùng một hàm với `unify._shop_display` nên API và cột chuẩn hoá luôn khớp.
    """
    import json as _j
    from .engines.unify import _shop_display
    try:
        x = _j.loads(row.get("raw_json") or "{}")
    except Exception:
        x = {}
    cand = (x.get("shop_name") or x.get("seller_name") or x.get("brand")
            or row.get("seller"))
    return _shop_display(cand)



@router.get("/health")
def health():
    return {"status": "ok", "llm_enabled": llm.enabled(),
            "last_updated": store.last_updated,
            "counts": {"opportunities": len(store.opportunities),
                       "product_types": len(store.product_types),
                       "niches": len(store.niches())}}


@router.get("/taxonomy")
def taxonomy():
    return store.taxonomy


@router.get("/niches")
def niches():
    # Niche = keyword đã crawl (fallback seed khi DB rỗng) -> Compare/Filter nói về data thật
    ns = sorted({s.niche for s in analysis.current_opportunities()})
    return {"niches": ns or store.niches()}


# ---- Normalization ----
@router.post("/normalize")
def normalize(req: NormalizeRequest):
    return norm.normalize(req.text)


@router.get("/normalize/evaluate")
def normalize_eval():
    return norm.evaluate_testset()


# ---- Scoring (đọc từ DATA CRAWL THẬT qua current_opportunities) ----
@router.get("/opportunities")
def opportunities():
    return {"opportunities": [s.model_dump() for s in analysis.current_opportunities()],
            "last_updated": store.last_updated}


@router.get("/opportunities/{oid}")
def opportunity(oid: str):
    for s in analysis.current_opportunities():
        if s.id == oid:
            return s
    return {"error": "not found"}


@router.post("/score/title")
def score_title(req: ScoreTitleRequest):
    return scoring.score_title(req.title, req.niche)


# ---- Aggregation ----
@router.get("/dashboard")
def dashboard():
    return aggregate.dashboard()


@router.post("/compare")
def compare(payload: dict):
    return aggregate.compare_niches(payload.get("niches", []))


# ---- Report ----
@router.post("/report")
def report(req: ReportRequest):
    return report_engine.generate(opportunity_ids=req.opportunity_ids, niches=req.niches, title=req.title)


# ---- Copilot ----
@router.post("/copilot", response_model=CopilotResponse)
def copilot_chat(req: CopilotRequest):
    out = copilot.answer(req.message, [m.model_dump() for m in req.history])
    return CopilotResponse(**out)


# ---- One-shot AI (chatbot ở Trend Signal Hub) ----
@router.post("/oneshot")
def oneshot_run(payload: dict):
    """One-shot AI: DeepSeek ground trên dữ liệu sản phẩm THẬT khớp câu hỏi.

    payload: {question: str}. Trả {answer, keywords:[{...,top_image,top_url}], scope}.
    """
    from .engines import oneshot
    return oneshot.run((payload or {}).get("question", ""))


# ---- Ingestion ----
@router.post("/ingest/csv")
async def ingest_csv(file: UploadFile = File(...), source: str = Form("etsy")):
    content = await file.read()
    return csv_import.import_csv(content, source=source)


@router.post("/ingest/reset")
def ingest_reset():
    store.reload()
    return {"status": "reset to seed", "opportunities": len(store.opportunities)}


@router.get("/trends/discover")
async def trends_discover(seed: str, country: str = "US"):
    """Gợi ý keyword đang HOT liên quan tới seed (Google Trends thật qua gtrends/Playwright)."""
    from .ingestion import discover as disc
    return await disc.discover(seed, country)


@router.post("/trends/discover/scan")
async def trends_discover_scan(payload: dict | None = None):
    """QUÉT FULL catalog -> lưu keyword tìm được vào DB (snapshot theo ngày).

    payload: {seeds: <số hạt giống, mặc định toàn bộ catalog>, country: "US"}
    48 hạt giống mất ~7-15 phút. Nên chạy nền / theo lịch đêm.
    """
    from .ingestion import seedgen
    p = payload or {}
    n_seeds = int(p.get("seeds") or 999)      # 999 = toàn bộ catalog
    country = p.get("country") or "US"
    sd = seedgen.seeds(n_seeds)
    exp = await seedgen.expand(sd, country)
    saved = db.save_discovered(exp["keywords"])
    return {"seeds_run": len(sd), "seeds_ok": exp["seeds_ok"],
            "seeds_failed": exp["seeds_failed"], "unique": exp["unique"], "saved": saved}


@router.get("/keyword/{kw}/listings")
def keyword_listings(kw: str, limit: int = 60):
    """Sản phẩm THẬT đang bán cho 1 keyword — bấm vào tín hiệu là ra ngay.

    Tách theo sàn, sắp theo số bán. Chỉ dòng CÓ ĐƠN mới tính vào doanh thu
    (sale-based analysis) — dòng 0 đơn vẫn trả về nhưng đánh dấu riêng.
    """
    import json as _json
    rows = db.listings_by_keyword(kw, limit * 3)
    out = {"keyword": kw, "platforms": {}, "total": len(rows)}
    for plat in ("etsy", "amazon"):
        items = [r for r in rows if r.get("platform") == plat]
        norm = []
        for r in items:
            sales = r.get("est_sales") or 0
            try:
                raw = _json.loads(r.get("raw_json") or "{}")
                sales = max(sales, raw.get("bought_past_month") or 0)
                rating = raw.get("rating")
            except Exception:
                rating = None
            norm.append({
                "title": r.get("title"), "price": r.get("price"),
                "sales": sales, "revenue": round((r.get("price") or 0) * sales, 2),
                # Tên shop đã chuẩn hoá (chung hàm với listings_unified.shop_name)
                "shop": _shop_name(r), "favorites": r.get("favorites"),
                "reviews": r.get("reviews"), "rating": rating, "url": r.get("url"),
                "image": (_json.loads(r.get("raw_json") or "{}") or {}).get("image"),
                "shop_url": (_json.loads(r.get("raw_json") or "{}") or {}).get("shop_url"),
            })
        norm.sort(key=lambda x: x["sales"], reverse=True)
        sold = [x for x in norm if x["sales"] > 0]
        prices = sorted([x["price"] for x in sold if x["price"]])
        out["platforms"][plat] = {
            "n_listings": len(norm),
            "n_sold": len(sold),
            "dead_pct": round((1 - len(sold) / len(norm)) * 100) if norm else 0,
            "revenue_30d": round(sum(x["revenue"] for x in sold)),
            "units_30d": sum(x["sales"] for x in sold),
            "price_med": prices[len(prices) // 2] if prices else None,
            "price_min": prices[0] if prices else None,
            "price_max": prices[-1] if prices else None,
            "n_shops": len({x["shop"] for x in sold if x["shop"]}),
            "items": norm[:limit],
        }
    return out


@router.get("/catalogue/keywords")
def catalogue_keywords(limit: int = 60, min_listings: int = 5):
    """Keyword thật đã cào. Chỉ trả keyword có dòng trong listings_unified;
    trường nào không có nguồn thì null.
    """
    from .engines import catalogue
    return catalogue.build(limit, min_listings)


@router.get("/catalogue/fit/{kw}")
def catalogue_fit(kw: str):
    """Năng lực sản xuất — đọc từ seed_taxonomy.json."""
    from .engines import catalogue
    return catalogue.fit(kw)


@router.get("/catalogue/seasons")
def catalogue_seasons():
    """Mùa vụ gom từ listings_unified."""
    from .engines import catalogue
    return catalogue.seasons()


@router.get("/catalogue/product/{name}")
def catalogue_product(name: str, top: int = 10):
    """Một product type: số liệu thị trường + listing bán chạy + keyword của nó."""
    from .engines import catalogue
    return catalogue.product(name, top)


@router.get("/catalogue/competition/{kw}")
def catalogue_competition(kw: str, top: int = 6):
    """Thị phần theo shop cho 1 keyword — từ listings_unified."""
    from .engines import catalogue
    return catalogue.competition(kw, top)


@router.get("/catalogue/related/{kw}")
def catalogue_related(kw: str, limit: int = 12):
    """Keyword liên quan — từ discovered_keywords, KHÔNG sinh bằng template."""
    from .engines import catalogue
    return catalogue.related(kw, limit)


@router.get("/gallery/products")
def gallery_products(top: int = 8):
    """Ảnh sản phẩm thật cho khung "Sản phẩm hot", nhóm theo product type."""
    from .engines import gallery
    return gallery.by_product(top)


@router.get("/gallery/product/{name}")
def gallery_product(name: str, top: int = 12):
    """Dải ảnh của MỘT product type."""
    from .engines import gallery
    return gallery.for_product(name, top)


@router.get("/gallery/keyword/{kw}")
def gallery_keyword(kw: str, top: int = 12):
    """Dải ảnh của một keyword."""
    from .engines import gallery
    return gallery.for_keyword(kw, top)


@router.get("/gallery/coverage")
def gallery_coverage():
    """Bao nhiêu % listing có ảnh, theo sàn."""
    from .engines import gallery
    return gallery.coverage()


@router.get("/data/schema")
def data_schema():
    """Lược đồ chuẩn hoá 2 sàn (listings_unified) + độ phủ từng cột.

    Mỗi khái niệm có đúng một tên cột, kèm units_src (real|proxy|none) để biết
    số đó đo thật hay ước lượng.
    """
    from .engines import unify
    return {"table": "listings_unified", "coverage": unify.coverage()}


@router.post("/data/unify")
def data_unify():
    """Dựng lại bảng chuẩn hoá từ raw_listings."""
    from .engines import unify
    return unify.rebuild()


@router.get("/progress")
def progress():
    """Tiến độ kéo dữ liệu — xem được ở /progress.html.

    Trả: số dòng từng bảng · độ phủ các trường quan trọng ·
    lần cào gần nhất · lịch scheduler.
    """
    from . import scheduler
    from .engines import unify
    db.reap_stale_runs(30)      # đóng run treo trước khi hiển thị
    with db.connect() as c:
        def one(q, *a):
            return c.execute(q, a).fetchone()[0]
        tables = {}
        for t in ("raw_listings", "listings_unified", "discovered_keywords",
                  "trends_cache", "crawl_runs", "reports"):
            try:
                tables[t] = one(f"SELECT COUNT(*) FROM {t}")
            except Exception:
                tables[t] = 0
        et = one("SELECT COUNT(*) FROM raw_listings WHERE platform='etsy'")
        am = one("SELECT COUNT(*) FROM raw_listings WHERE platform='amazon'")
        kw_listing = one("SELECT COUNT(DISTINCT keyword) FROM raw_listings")
        img_q = ("SELECT COUNT(*) FROM raw_listings WHERE platform=? "
                 "AND raw_json LIKE '%\"image\"%'")
        # Đếm số bán thật của cả 2 sàn: Etsy ghi `units_real`, Amazon ghi
        # `bought_past_month`.
        real_q = ("SELECT COUNT(*) FROM raw_listings WHERE platform=? AND ("
                  "raw_json LIKE '%units_real%' OR raw_json LIKE '%bought_past_month%')")
        enrich = {
            "units_real": one("SELECT COUNT(*) FROM raw_listings WHERE "
                              "raw_json LIKE '%units_real%' OR "
                              "raw_json LIKE '%bought_past_month%'"),
            # tách theo sàn để thấy sàn nào đang nghẽn
            "units_real_etsy": one(real_q, "etsy"),
            "units_real_amazon": one(real_q, "amazon"),
            "image": one("SELECT COUNT(*) FROM raw_listings "
                         "WHERE raw_json LIKE '%\"image\"%'"),
            # tách theo sàn để thấy rõ sàn nào còn thiếu
            "image_etsy": one(img_q, "etsy"),
            "image_amazon": one(img_q, "amazon"),
            "sponsored": one("SELECT COUNT(*) FROM raw_listings "
                             "WHERE raw_json LIKE '%sponsored%'"),
        }
        running = one("SELECT COUNT(*) FROM crawl_runs WHERE status='running'")
        runs = [dict(r) for r in c.execute(
            "SELECT platform, status, n_items, backend, started_at, finished_at "
            "FROM crawl_runs ORDER BY id DESC LIMIT 12")]
        try:
            src = {r[0]: r[1] for r in c.execute(
                "SELECT units_src, COUNT(*) FROM listings_unified GROUP BY units_src")}
        except Exception:
            src = {}
    return {
        "tables": tables,
        "platforms": {"etsy": et, "amazon": am},
        "keywords_with_listing": kw_listing,
        "enrichment": enrich,
        "running_jobs": running,
        "units_source": src,
        "coverage": unify.coverage(),
        "recent_runs": runs,
        "scheduler": scheduler.status(),
    }


@router.post("/shops/fetch-names")
def shops_fetch_names(payload: dict | None = None):
    """Lấy TÊN SHOP thật cho listing đang chỉ có mã.

    payload: {platform: 'amazon'|'etsy'|'both', limit?: int}

    Amazon: đọc trang /dp/<asin> bằng Chrome — Amazon KHÔNG chặn (đo 85% thành công).
    Etsy:   qua `listings/batch?includes=Shop`, 100 listing/request. Etsy chặn mọi
            cách nạo trang (403 kể cả Chrome headful) nên chỉ còn đường API, mà
            API giới hạn 5.000 lượt/ngày.
    """
    payload = payload or {}
    plat = (payload.get("platform") or "both").lower()
    limit = int(payload.get("limit") or 300)
    out = {}
    if plat in ("amazon", "both"):
        from .ingestion import amazon_shops
        out["amazon"] = amazon_shops.fetch_names(limit=limit)
    if plat in ("etsy", "both"):
        from .ingestion import etsy_shops
        out["etsy"] = etsy_shops.fetch_names()
    return out


@router.get("/shops/quota")
def shops_quota():
    """Còn bao nhiêu lượt Etsy hôm nay — đọc thẳng từ header, không đoán."""
    from .ingestion import etsy_shops
    return etsy_shops._quota()


@router.get("/export/{table}.csv")
def export_csv(table: str, limit: int = 100000, platform: str | None = None):
    """Xuất CSV để team tải về.

    table: listings_unified (khuyên dùng — đã chuẩn hoá 2 sàn, có shop_name)
         · raw_listings · discovered_keywords · trends_cache
    """
    import csv as _csv
    import io as _io
    from fastapi.responses import StreamingResponse

    ALLOWED = {"listings_unified", "raw_listings",
               "discovered_keywords", "trends_cache"}
    if table not in ALLOWED:
        return {"error": f"chỉ xuất được: {', '.join(sorted(ALLOWED))}"}

    where, args = "", []
    if platform and table in ("listings_unified", "raw_listings"):
        where, args = " WHERE platform=?", [platform]

    with db.connect() as c:
        cur = c.execute(f"SELECT * FROM {table}{where} LIMIT ?", (*args, limit))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        # raw_json là JSON lồng — bỏ để CSV mở được bằng Excel
        w.writerow(["" if v is None else
                    (str(v)[:200] if k == "raw_json" else v)
                    for k, v in zip(cols, r)])
    buf.seek(0)

    name = f"{table}{'_' + platform if platform else ''}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/snapshot/export")
def snapshot_export():
    """Đóng gói DB hiện tại vào `app/data/snapshot/dataset.zip` để commit.

    Chạy khi vừa crawl thêm dữ liệu và muốn cả đội cùng có. Commit file zip
    (~4MB) rồi push — đồng đội `git pull` là app tự bung lúc khởi động.
    """
    from .ingestion import snapshot
    return snapshot.export()


@router.get("/snapshot/status")
def snapshot_status():
    """Snapshot đi kèm repo có gì, DB hiện tại có gì."""
    import os
    from .ingestion import snapshot
    return {
        "snapshot_exists": snapshot.exists(),
        "snapshot_path": snapshot.ZIP_PATH,
        "snapshot_size_mb": (round(os.path.getsize(snapshot.ZIP_PATH) / 1024 / 1024, 1)
                             if snapshot.exists() else None),
        "db_counts": db.counts(),
    }


@router.get("/export/manifest")
def export_manifest():
    """Danh mục dữ liệu tải được — bảng nào, bao nhiêu dòng, tải ở đâu."""
    import os
    out = []
    with db.connect() as c:
        for t, note in (
            ("listings_unified", "KHUYÊN DÙNG — 2 sàn đã chuẩn hoá, có shop_name, units_30d, revenue_30d"),
            ("raw_listings", "dữ liệu thô như lúc cào về, có raw_json"),
            ("discovered_keywords", "keyword tự tìm qua Google Trends + % thay đổi"),
            ("trends_cache", "chuỗi Google Trends 12 tháng theo keyword"),
        ):
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                n = 0
            out.append({"table": t, "rows": n, "note": note,
                        "csv": f"/api/export/{t}.csv"})
    return {
        "db_path": db.DB_PATH,
        "db_size_mb": round(os.path.getsize(db.DB_PATH) / 1024 / 1024, 1)
                      if os.path.exists(db.DB_PATH) else None,
        "tables": out,
        "note": "Thêm ?platform=etsy hoặc ?platform=amazon để lọc theo sàn.",
    }


@router.get("/coverage-report")
def coverage_report_api():
    """Đã tra được bao nhiêu phần catalog Printway, còn thiếu nhóm nào."""
    from .engines import coverage_report
    return coverage_report.build()


@router.post("/pull")
def pull_keyword(payload: dict | None = None):
    """Kéo dữ liệu THẬT cho 1 keyword chưa có trong DB.

    payload: {keyword: str, limit?: int (mặc định 25), amazon?: bool}
    Quy mô nhỏ có chủ đích — đây là tra cứu tương tác, người dùng đang chờ.
    Trả về từng bước kèm thời gian đo được, và `sources` ghi rõ nguồn nào
    thực sự có dữ liệu.
    """
    from .engines import ondemand
    payload = payload or {}
    return ondemand.pull(
        payload.get("keyword") or "",
        limit=int(payload.get("limit") or ondemand.DEFAULT_LIMIT),
        with_amazon=payload.get("amazon", True),
    )


@router.get("/entry-rate")
def entry_rate_api():
    """Tốc độ người bán đổ vào từng nhóm — đo từ ngày đăng listing.

    Nguồn độc lập với Google Trends: Trends đo người TÌM, cái này đo người BÁN
    và kiểm chứng bằng đơn hàng thật. Dùng được khi API Trends bị giới hạn.
    """
    from .engines import entry_rate
    return entry_rate.analyze()


@router.get("/category/{name}")
def category_detail(name: str):
    """Số thật cho popup chi tiết ngành hàng.

    Mọi trường đọc từ listing đã cào + taxonomy công ty. Không có thì trả null
    để frontend hiện "chưa đủ dữ liệu" — không suy số.
    """
    from .engines import market as _mkt
    mk = _mkt.analyze(8000)
    row = next((c for c in (mk.get("categories") or [])
                if c["name"].lower() == name.lower()), None)
    if not row:
        return {"available": False, "name": name,
                "message": "Chưa có listing nào thuộc ngành hàng này"}

    # product type CỦA ngành này, theo taxonomy công ty
    pts = [p["product_type"] for p in store.product_types
           if p.get("category") == row["name"]]
    # nhóm con nào ĐANG có doanh thu thật (thay cho tô xanh hardcode)
    rev_by_pt = {p["name"]: p["revenue_30d"] for p in (mk.get("products") or [])}
    subs = [{"name": pt, "revenue_30d": rev_by_pt.get(pt, 0),
             "active": rev_by_pt.get(pt, 0) > 0} for pt in pts]
    subs.sort(key=lambda x: -x["revenue_30d"])

    # keyword THẬT của ngành: keyword có listing thuộc product type trong ngành
    with db.connect() as c:
        kws = [dict(r) for r in c.execute(
            """SELECT keyword, COUNT(*) n, SUM(COALESCE(units_30d,0)) units,
                      SUM(COALESCE(revenue_30d,0)) rev
               FROM listings_unified
               WHERE keyword IS NOT NULL
               GROUP BY keyword ORDER BY rev DESC LIMIT 200""")]
    kw_rows = []
    low_pts = [p.lower() for p in pts]
    for k in kws:
        kl = (k["keyword"] or "").lower()
        if any(t.split()[0] in kl for t in low_pts if t):
            kw_rows.append(k)
        if len(kw_rows) >= 8:
            break

    # % thay đổi thật từ Google Trends (nếu đã quét)
    for k in kw_rows:
        d = db.get_discovered_one(k["keyword"]) if hasattr(db, "get_discovered_one") else None
        k["change_percent"] = (d or {}).get("change_percent")

    return {
        "available": True,
        "name": row["name"],
        "revenue_30d": row["revenue_30d"],
        "units_30d": row["units_30d"],
        "n_listings": row["n_listings"],
        "n_shops": row["n_shops"],
        "share_pct": row["share_pct"],
        "n_product_types": len(pts),
        "subs": subs,
        "keywords": kw_rows,
        "source": "listings_unified + taxonomy Printway",
    }


@router.get("/scheduler/status")
def scheduler_status():
    """Lịch chạy nền: job nào chạy lúc mấy giờ, lần cuối chạy khi nào."""
    from . import scheduler
    return scheduler.status()


@router.post("/scheduler/run")
def scheduler_run(job: str = "all"):
    """Chạy job ngay, không đợi tới giờ. job = all|discover|listings|trends|report.

    listings là job quan trọng nhất — nó nuôi raw_listings, bảng gốc của
    mọi con số tiền.
    """
    from . import scheduler
    if job == "all":
        return {"results": scheduler.run_all()}
    return scheduler.run_job(job)


@router.get("/hub/metrics/{kw}")
def hub_metrics(kw: str):
    """Chỉ số theo công thức của data analyst (Long demo) — chạy trên data thật.

    competition đếm theo SHOP_ID · favorite_rate · whitespace ·
    confidence chiết khấu điểm · 9 tiêu chí pass/fail · luật rủi ro.
    """
    from .engines import hubmetrics
    return hubmetrics.compute(kw)


@router.get("/score/keyword/{kw}")
def score_keyword_live(kw: str):
    """Chấm 9 chỉ số cho 1 keyword từ dữ liệu THẬT — thay panel số cứng.

    Chỉ số nào không có nguồn thật thì available=false, KHÔNG chấm;
    tổng điểm chia lại theo trọng số các chỉ số còn lại.
    """
    from .engines import kwscore
    return kwscore.score(kw)


@router.get("/market/analysis")
def market_analysis(limit: int = 5000):
    """Phân tích thị trường từ TOÀN BỘ listing đã cào.

    Trả 5 chiều R&D cần: mùa vụ · ngành hàng · ngách tiềm năng · sản phẩm hot
    · đối thủ (kèm THỊ PHẦN và sản phẩm bán chạy nhất của họ).
    Chỉ tính doanh thu trên listing CÓ ĐƠN (sale-based analysis).
    """
    from .engines import market
    return market.analyze(limit)


@router.get("/signals/today")
def signals_today(limit: int = 40):
    """TÍN HIỆU HÔM NAY — sinh từ keyword đã quét, không hardcode.

    Mỗi alert = 1 keyword đang lên, kèm % thay đổi thật của Google Trends.
    Khi có >=2 ngày snapshot sẽ so được ngày/ngày; hiện dùng % của chính Google.
    """
    from .ingestion import signals
    return signals.build(limit)


@router.get("/trends/discover/top")
async def trends_discover_top(seeds: int = 12, top: int = 30, country: str = "US"):
    """Tự tìm TOP keyword đang lên — thay cho danh sách hardcode.

    Hạt giống sinh từ catalog Printway, lan tỏa bằng related_queries của Google.
    ~12 hạt mất ~2 phút; 48 hạt mất ~7 phút. Nên chạy theo lịch đêm.
    """
    from .ingestion import seedgen
    return await seedgen.discover_top(seeds, top, country)


@router.get("/trends/{keyword}")
def trends(keyword: str, range: str = gtrends.DEFAULT_RANGE, live: bool = False):
    """Chuỗi Google Trends cho 1 keyword.

    Mặc định đọc CACHE (đã refresh sẵn) — nhanh và không dội rate-limit của Google.
    `?live=true` ép gọi thẳng Google. `?range=` chọn khoảng: 7d|1m|3m|12m|5y.
    Không có dữ liệu -> series rỗng + source="unavailable" (KHÔNG bịa số).
    """
    if not live:
        series, source = gtrends.cached_series(keyword)
        if series:
            meta = gtrends.cached_meta(keyword)
            # Trả kèm mốc thời gian: không có nó thì client không biết 12 điểm
            # này là tuần hay tháng, của khoảng nào.
            return {"keyword": keyword, "series": series,
                    "labels": meta.get("labels") or [],
                    "range": range, "source": source,
                    "timeframe": meta.get("timeframe"),
                    "updated_at": meta.get("updated_at")}
    series, labels, source = gtrends.fetch_series(keyword, range)
    if series:
        gtrends.db.set_trend(keyword, series, source)
    return {"keyword": keyword, "series": series, "labels": labels,
            "range": range, "source": source}


# =========================================================
#  CRAWLER (Worker) — cào RAW data về DB
# =========================================================
DEFAULT_KEYWORDS = [
    "christmas gifts", "personalized christmas ornament", "christmas ornaments set",
    "christmas decorations indoor", "christmas gifts for kids", "personalized mug",
]


@router.post("/crawl/run")
def crawl_run(payload: dict):
    """Chạy worker cào dữ liệu. payload: {platforms:['etsy','amazon'], keywords:[...]}."""
    platforms = payload.get("platforms") or ["etsy"]
    keywords = payload.get("keywords") or DEFAULT_KEYWORDS
    results = []
    for p in platforms:
        if p == "etsy":
            results.append(run_worker(EtsyWorker(), keywords))
        elif p == "amazon":
            results.append(run_worker(AmazonWorker(), keywords))
        elif p == "seed":
            results.append({"platform": "seed", **seed_worker.seed_db(reset=False), "status": "done"})
    return {"runs": results, "db": db.counts()}


@router.post("/crawl/seed")
def crawl_seed(force: bool = False):
    """Nạp RAW giả lập để demo offline (không cần mạng).

    `reset=True` xoá sạch raw_listings; endpoint từ chối chạy khi còn dữ liệu
    Etsy (không crawl lại được) trừ khi truyền `?force=true`.
    """
    with db.connect() as c:
        n_etsy = c.execute(
            "SELECT COUNT(*) FROM raw_listings WHERE platform='etsy'").fetchone()[0]
    if n_etsy and not force:
        return {
            "refused": True,
            "reason": f"Còn {n_etsy:,} listing Etsy KHÔNG crawl lại được "
                      "(Etsy đã khoá API). Nạp seed sẽ xoá sạch chúng.",
            "doc": "docs/KHONG-XOA-DU-LIEU-ETSY.md",
            "how_to_override": "POST /api/crawl/seed?force=true",
        }
    return {**seed_worker.seed_db(reset=True), "db": db.counts()}


@router.get("/crawl/runs")
def crawl_runs():
    return {"runs": db.list_runs(), "db": db.counts()}


@router.get("/crawl/backend")
def crawl_backend():
    from .workers import browser
    return {"active_backend": browser.active_backend(),
            "etsy_ready": EtsyWorker().available()}


@router.get("/raw")
def raw_listings(platform: str | None = None, limit: int = 200):
    return {"listings": db.get_listings(platform=platform, limit=limit), "counts": db.counts()}


# =========================================================
#  AI AGENT — đọc RAW, phân tích ra output chuẩn
# =========================================================
# Cache cho /analyze: tránh gọi lại LLM khi kết quả gần như không đổi. Khóa gồm
# tổng số listing nên vừa crawl thêm là cache tự hết hiệu lực.
_ANALYZE_CACHE: dict[tuple, tuple[float, dict]] = {}
_ANALYZE_TTL = 900.0          # 15 phút


@router.post("/analyze")
def analyze(payload: dict | None = None, refresh: bool = False):
    """payload: {role:'rnd'|'seller', filters:{platform,category,material,since_days}}.

    refresh=true bỏ qua cache và chấm điểm lại từ đầu.
    """
    payload = payload or {}
    role = payload.get("role", "rnd")
    filters = payload.get("filters") or {}

    import json as _json
    import time as _time
    key = (role, _json.dumps(filters, sort_keys=True), db.counts().get("total", 0))

    if not refresh:
        hit = _ANALYZE_CACHE.get(key)
        if hit and (_time.time() - hit[0]) < _ANALYZE_TTL:
            out = dict(hit[1])
            out["_cached"] = True
            out["_cached_age_s"] = round(_time.time() - hit[0], 1)
            return out

    res = analysis.full_analysis(role=role, filters=filters, save=True)
    _ANALYZE_CACHE[key] = (_time.time(), res)
    # khóa đã gắn tổng listing nên bản ghi cũ không còn dùng được -> dọn luôn
    for k in [k for k in _ANALYZE_CACHE if k != key]:
        _ANALYZE_CACHE.pop(k, None)
    return res


@router.get("/analyze/markdown")
def analyze_markdown(role: str = "rnd"):
    res = analysis.full_analysis(role=role, save=False)
    return {"markdown": analysis.to_markdown(res), "analyzed_by": res["analyzed_by"]}


# =========================================================
#  AI HỌC HÀNH VI (V1) — feedback → profile → cá nhân hóa
# =========================================================
@router.post("/feedback")
def feedback(payload: dict):
    """Ghi thao tác người dùng. payload: {role, action, target_type, target_value}."""
    learning.log_event(payload.get("role", "rnd"), payload.get("action", "interest"),
                       payload.get("target_type", ""), payload.get("target_value", ""))
    return {"ok": True, "profile": learning.profile()}


@router.get("/profile")
def get_profile():
    return learning.profile()


# ---- Competitor Tracker + Design Insight (bonus) ----
@router.get("/competitors")
def competitors():
    return competitors_engine.competitors()


@router.get("/design-insight")
def design_insight():
    return design_engine.design_insight()


@router.post("/profile/reset")
def reset_profile():
    db.clear_events()
    return {"ok": True, "profile": learning.profile()}


@router.post("/trends/refresh")
def trends_refresh(payload: dict | None = None):
    """Fetch Google Trends thật cho danh sách keyword (mặc định: keyword đang có trong DB)."""
    payload = payload or {}
    kws = payload.get("keywords")
    if not kws:
        with db.connect() as c:
            rows = c.execute("SELECT DISTINCT keyword FROM raw_listings WHERE keyword IS NOT NULL LIMIT 25").fetchall()
        kws = [r["keyword"] for r in rows]
    return gtrends.refresh(kws)


@router.get("/filters/options")
def filter_options():
    """Danh sách giá trị cho bộ lọc (platform/category/material)."""
    return {
        "platforms": list(db.counts()["by_platform"].keys()),
        "categories": store.taxonomy["categories"],
        "materials": store.taxonomy["materials"],
        "roles": ["rnd", "seller"],
    }
