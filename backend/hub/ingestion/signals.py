"""Tín hiệu hôm nay — sinh từ dữ liệu thật (discovered_keywords, raw_listings, taxonomy).

4 nhóm tín hiệu khớp bộ lọc frontend:
  season     mùa vụ    — đếm ngược tới đỉnh, cửa sổ launch còn bao lâu
  product    sản phẩm  — product type xếp theo doanh thu thật
  keyword    từ khóa   — keyword đang lên trong catalog
  emerging   mới nổi   — ghép ý ngoài catalog / mới xuất hiện

Mỗi alert giữ shape: {kind, dir, sev, title, detail, metric, link, time, act, id}
"""
from __future__ import annotations
import re
from datetime import date, datetime, timezone

from .. import db
from ..store import store

HOT, WARM = 50.0, 15.0

# Đỉnh mùa vụ (tháng) — để đếm ngược tới cửa sổ launch
PEAK_MONTH = {
    "Christmas": 12, "Halloween": 10, "Thanksgiving": 11, "Valentine's Day": 2,
    "Easter": 4, "Mother's Day": 5, "Father's Day": 6, "Graduation": 5,
    "Back-to-school": 8, "St Patrick's Day": 3, "America 250": 7,
}
# Thời gian tối thiểu để listing kịp tích review trước sóng
LEAD_DAYS = 40

# Nhiễu: sàn / chuỗi bán lẻ / thương hiệu / game — trùng từ nhưng vô nghĩa với POD.
_NOISE = {
    "etsy", "amazon", "temu", "shein", "walmart", "target", "five", "below",
    "ebay", "aliexpress", "costco", "kohls", "michaels", "dollar", "tree",
    "hallmark", "lenox", "pottery", "barn", "swarovski", "disney", "nike",
    "skechers", "bobs", "adidas", "starbucks", "stanley", "yeti",
    "hades", "fortnite", "roblox", "minecraft", "pokemon", "zelda", "genshin",
    "elden", "diablo", "warcraft", "sims", "fuggler", "labubu",
    # điện tử / gia dụng — không phải POD
    "dyson", "iphone", "samsung", "airpods", "ipad", "macbook", "laptop",
    "vacuum", "printer", "camera", "tv", "router", "charger",
    # phần mềm — "bookmarks" trùng nghĩa với dấu trang trình duyệt
    "chrome", "firefox", "safari", "edge", "browser", "export", "import",
    "backup", "sync", "app", "software", "download", "install",
    # bán buôn / dropship — không phải nhu cầu người tiêu dùng cuối
    "wholesale", "bulk", "dropship", "supplier", "manufacturer", "factory",
}
_QUERY_WORDS = {
    "how", "what", "where", "why", "when", "who", "meaning", "definition",
    "wiki", "reddit", "youtube", "walkthrough", "guide", "cheat", "mod",
    # ô chữ / đố vui — "keepsakes crossword clue" không phải nhu cầu mua
    "crossword", "clue", "answer", "answers", "puzzle", "quiz",
    # hãng đồng hồ / thể thao / mỹ phẩm — trùng từ với catalog nhưng khác ngành
    "casio", "seiko", "rolex", "fossil", "garmin", "fitbit", "hoka", "bondi",
    "orioles", "yankees", "lakers", "nfl", "nba", "mlb", "coppertone",
    "compostable", "tanning", "sunscreen", "shampoo", "detergent",
    # cụm chỉ nơi bán / khuyến mãi, không phải sản phẩm
    "deals", "coupon", "discount", "clearance", "near", "shop",
}
_STOP = {"the", "a", "an", "for", "with", "and", "of", "to", "in", "on", "by",
         "custom", "personalized", "customized", "gift", "gifts", "best", "new"}


def _sev(pct: float) -> str:
    return "hot" if pct >= HOT else ("warm" if pct >= WARM else "cold")


def _dir(pct: float) -> str:
    return "up" if pct > 3 else ("down" if pct < -3 else "flat")


# Keyword chứa năm là hiệu ứng lịch, không phải trend sản phẩm.
_YEAR = re.compile(r"20\d\d")

# Trần % hợp lý: trên mức này gần như luôn do nền so sánh bằng 0 (Google gắn "Breakout").
PCT_CAP = 300.0


# Từ chỉ ý định mua hoặc thuộc tính POD. Keyword không có từ nào trong đây
# thường là tên riêng / thương hiệu / truy vấn tra cứu, không phải cơ hội sản phẩm.
_INTENT = {
    "personalized", "custom", "customized", "customizable", "monogram",
    "monogrammed", "engraved", "printed", "embroidered", "handmade",
    "photo", "picture", "name", "gift", "gifts", "set", "bulk",
    "matching", "funny", "cute", "unique", "vintage", "minimalist",
    "birthday", "wedding", "anniversary", "christmas", "halloween",
    "memorial", "baby", "family", "couple", "mom", "dad", "teacher", "pet",
}


def _is_noise(kw: str) -> bool:
    w = set(kw.lower().split())
    if _YEAR.search(kw):
        return True
    if w & _NOISE or w & _QUERY_WORDS:
        return True
    # phải có ít nhất 1 từ chỉ ý định mua / thuộc tính POD
    if not (w & _INTENT):
        return True
    return False


BREAKOUT = 4900.0   # Google trả ~5000 khi nền so sánh gần bằng 0 ("Breakout")


def _cap(pct: float) -> tuple[float, bool]:
    """Hạ trần %. Trả (giá trị dùng để xếp hạng, có phải Breakout không)."""
    if pct >= BREAKOUT:
        return PCT_CAP, True
    if pct > PCT_CAP:
        return PCT_CAP, True
    return pct, False


def _known_terms() -> set[str]:
    t: set[str] = set()
    for p in store.product_types:
        t.update((p.get("product_type") or "").lower().split())
        for a in p.get("aliases") or []:
            t.update(a.lower().split())
    return t


def _pt_index() -> dict[str, dict]:
    """từ đơn -> product type, để map keyword về catalog."""
    idx: dict[str, dict] = {}
    for p in store.product_types:
        for w in (p.get("product_type") or "").lower().split():
            if w not in _STOP:
                idx.setdefault(w, p)
        for a in p.get("aliases") or []:
            for w in a.lower().split():
                if w not in _STOP:
                    idx.setdefault(w, p)
    return idx


# Mỗi loại % so một kỳ khác nhau — nhãn dưới đây nói rõ so với kỳ nào.
BASIS = {
    # Google Trends related_queries, cửa sổ `today 12-m`: Google so 12 tháng
    # gần nhất với 12 tháng liền trước đó. 5000 = nhãn "Breakout".
    "gtrends": "Google Trends · 12 tháng gần nhất so với 12 tháng trước đó",
    # Tính từ listing đã cào: so nhóm listing mới với nhóm listing cũ trong
    # CÙNG một lần cào — không phải so hai mốc thời gian.
    "listing_new_vs_old": "listing mới (dưới 6 tháng) so với listing cũ, trong dữ liệu đã cào",
    # Đếm ngược tới đỉnh mùa — là số NGÀY, không phải % tăng trưởng.
    "season_calendar": "lịch mùa vụ, không phải % tăng trưởng",
    # Tỷ trọng listing của mùa này trên tổng listing đã cào — là THỊ PHẦN
    # tại một thời điểm, không phải tăng trưởng theo thời gian.
    "season_share": "thị phần listing của mùa này trong dữ liệu đã cào (không phải tăng trưởng)",
}


def _mk(kind, pct, title, detail, act, link, when="hôm nay", basis="gtrends") -> dict:
    return {"kind": kind, "dir": _dir(pct), "sev": _sev(abs(pct)), "title": title,
            "detail": detail, "metric": f"{pct:+.0f}%", "link": link,
            "time": when, "act": act, "id": 0, "_source": "live",
            # Nói RÕ % này so kỳ nào — giao diện hiện kèm mỗi dòng.
            "basis": basis, "basis_label": BASIS.get(basis, basis)}


# ───────────────────────── MÙA VỤ ─────────────────────────
def _season_alerts() -> list[dict]:
    """Mùa vụ — số liệu đo từ listing thật.

    · cửa sổ launch  <- lead time (trung vị tháng đăng -> tháng đỉnh)
    · % hiển thị     <- share_now: % listing của dịp này đăng trong tháng hiện tại
    Dịp chưa đủ mẫu (<30 listing có đơn) thì không sinh tín hiệu.
    """
    from ..engines import seasonwin

    today = date.today()
    out = []
    for name, m in PEAK_MONTH.items():
        year = today.year if m >= today.month else today.year + 1
        peak = date(year, m, 15)
        days = (peak - today).days
        if days > 200 or days < -30:
            continue

        w = seasonwin.launch_window(name, m)
        if not w.get("enough"):
            # KHÔNG bịa: chưa đủ listing để đo cửa sổ launch của dịp này
            continue

        lead = w["lead_days"]
        window = days - lead
        share = w["share_now_pct"]
        base = (f"Đo trên {w['n_listings']:,} listing có đơn của dịp này: người bán "
                f"thật đăng trước đỉnh ~{w['lead_months']} tháng "
                f"(tháng đăng nhiều nhất là T{w['busiest_month']}, {w['busiest_n']} listing). "
                f"{share:.0f}% số listing đó rơi vào tháng này.")

        if days < 0:
            pct = -share
            title = f"{name} đã qua đỉnh {abs(days)} ngày"
            act = "Dừng chi quảng cáo, giữ listing cũ"
        elif window <= 0:
            pct = share
            title = (f"{name} còn {days} ngày — đã quá cửa sổ launch "
                     f"({lead} ngày) mà người bán thật dùng")
            act = "Đã muộn để mở mới — tối ưu listing đang có"
        elif window <= 30:
            pct = share
            title = f"{name} còn {days} ngày — cửa sổ launch đóng sau {window} ngày"
            act = "Chốt danh mục tuần này — cửa sổ launch sắp đóng"
        else:
            pct = share
            title = f"{name} còn {days} ngày — cửa sổ launch mở sau {window - 30} ngày"
            act = "Còn sớm — đưa vào kế hoạch quý"

        # `share` = thị phần listing của mùa này, không phải tăng trưởng.
        a = _mk("season", pct, title, base, act, {"lens": "season", "id": name.lower()},
                basis="season_share")
        a["_value"] = w["n_listings"]      # xếp hạng theo cỡ mẫu thật
        out.append(a)
    return out


# ───────────────── KEYWORD + EMERGING ─────────────────
def _keyword_alerts(rows, known, prev_set, prev_day) -> list[dict]:
    out = []
    for r in rows:
        kw = r["keyword"]
        if _is_noise(kw):
            continue
        pct = r.get("change_percent") or 0.0
        if pct < 3:
            continue
        words = set(kw.split())
        hits = words & known
        # bắt buộc dính catalog để loại truy vấn trùng nghĩa
        if not hits:
            continue
        outside = len(hits) < len(words) - 1
        fresh = bool(prev_day) and kw not in prev_set
        raw_pct = pct
        pct, capped = _cap(pct)
        if capped:
            detail = ("Google Trends xếp loại **Breakout** — tuần trước gần như không ai "
                      "tìm, nên chưa có nền để so tỷ lệ. Đây là tín hiệu MỚI, chưa phải "
                      f"tăng trưởng đã kiểm chứng. Lượng tìm hiện {r.get('value') or 0:.0f}/100 "
                      f"· tìm ra từ hạt giống “{r.get('seed')}”.")
        else:
            detail = (f"Google Trends {pct:+.0f}% · lượng tìm {r.get('value') or 0:.0f}/100 "
                      f"· tìm ra từ hạt giống “{r.get('seed')}”.")
        if fresh:
            detail += f" Chưa có ở lần quét {prev_day}."
        if outside:
            detail += " Ghép ý ngoài catalog Printway — cơ hội mở rộng danh mục."
        title = f"“{kw}” — MỚI NỔI" if capped else f"“{kw}” {pct:+.0f}%"
        a = _mk("emerging" if (outside or fresh or capped) else "keyword", pct,
                title, detail,
                "Cào sâu Etsy/Amazon xem có ai bán được thật không",
                {"lens": "keyword", "id": kw}, r.get("day") or "hôm nay")
        a["_value"] = r.get("value") or 0
        if capped:
            a["metric"] = "MỚI"        # không khoe +5000% — nó không có nghĩa
            a["sev"] = "warm"          # chưa kiểm chứng -> không xếp HOT
        out.append(a)
    return out


# ───────────────────── SẢN PHẨM HOT ─────────────────────
def _catalog_alerts(rows, ptidx) -> list[dict]:
    """Sinh nhóm tín hiệu `product` — product type xếp theo doanh thu thật."""
    pt_pct: dict[str, list[float]] = {}
    for r in rows:
        kw, pct = r["keyword"], (r.get("change_percent") or 0.0)
        if _is_noise(kw) or pct < 3:
            continue
        pct, _ = _cap(pct)
        for w in kw.split():
            p = ptidx.get(w)
            if p:
                pt_pct.setdefault(p["product_type"], []).append(pct)
                break

    out = []
    # Dùng chung nguồn với bảng "Sản phẩm hot" ở trang tổng quan: xếp theo
    # doanh thu thật, không phải % Google Trends.
    from ..engines import market as _mkt
    try:
        mk = _mkt.analyze(6000)
        for row in (mk.get("products") or [])[:6]:
            name = row["name"]
            p = next((x for x in store.product_types
                      if x["product_type"] == name), None)
            cap = "in-house" if (p or {}).get("capacity") == "in_house" else "đối tác"
            mh = int(((p or {}).get("margin_high") or 0) * 100)
            # % tăng lấy từ Trends nếu có, để vẫn thấy được hướng
            grw = sum(pt_pct.get(name, [])) / len(pt_pct[name]) if pt_pct.get(name) else 0.0
            out.append(_mk(
                "product", grw,
                f"{name} — ${row['revenue_30d']:,}/30 ngày · {row['units_30d']:,} đơn",
                f"{row['n_shops']} shop đang bán · sản xuất {cap} · biên tới {mh}% · "
                f"độ khó {(p or {}).get('production_difficulty')}/5"
                + (f" · {len(pt_pct[name])} keyword đang lên {grw:+.0f}%" if grw else ""),
                "Dựng mẫu thiết kế tuần này",
                {"lens": "product", "id": name.lower()}))
    except Exception:
        pass
    return out


# ───────────── NGƯỜI BÁN ĐỔ VÀO (từ listed_at) ─────────────
def _entry_alerts() -> list[dict]:
    """Tín hiệu mới nổi đo từ phía cung (listed_at) — không cần Google Trends.

    Nhiều listing mới hơn nền + hàng mới bán tốt hơn mặt bằng = đang vào trend.
    Cũng phát tín hiệu ngược: đổ vào nhiều mà không bán được = cầu chưa theo kịp.
    """
    from ..engines import entry_rate
    try:
        r = entry_rate.analyze()
    except Exception:
        return []
    if not r.get("available"):
        return []

    base = r["baseline"]
    out = []
    for g in r["groups"]:
        if not (g["entering"] or g["crowding_no_demand"]):
            continue
        pt = next((x for x in store.product_types
                   if x["product_type"] == g["product_type"]), None)
        cap = "in-house" if (pt or {}).get("capacity") == "in_house" else "đối tác"

        if g["entering"]:
            pct = (g["sell_lift"] - 1) * 100
            title = (f"{g['product_type']} — người bán đang đổ vào, hàng mới bán "
                     f"tốt hơn mặt bằng {g['sell_lift']:.1f}×")
            detail = (f"{g['n_new']}/{g['n_listings']} listing đăng trong 90 ngày "
                      f"({g['new_share_pct']}%, gấp {g['share_vs_base']}× nền "
                      f"{base['new_share_pct']}%). Trong đó {g['new_sell_pct']}% đã có đơn, "
                      f"so với nền {base['new_sell_pct']}% của listing cùng tuổi. "
                      f"Sản xuất {cap}. Nguồn: ngày đăng listing trên Etsy.")
            act = "Vào sớm — dựng 3-5 mẫu test tuần này"
        else:
            pct = -(1 - g["sell_lift"]) * 100
            title = (f"{g['product_type']} — chợ đang đông lên nhưng hàng mới "
                     f"chưa bán được")
            detail = (f"{g['n_new']} listing mới trong 90 ngày ({g['new_share_pct']}%, "
                      f"gấp {g['share_vs_base']}× nền) nhưng chỉ {g['new_sell_pct']}% có đơn "
                      f"— dưới nền {base['new_sell_pct']}%. Người bán đang thử, cầu chưa theo kịp.")
            act = "Khoan vào — theo dõi thêm 2-4 tuần"

        a = _mk("emerging", pct, title, detail, act,
                {"lens": "product", "id": g["product_type"].lower()},
                basis="listing_new_vs_old")
        a["_value"] = g["n_new"]
        out.append(a)
    return out


# ───────────────────────── BUILD ─────────────────────────
def build(limit: int = 60) -> dict:
    days = db.discovered_days()
    rows = db.list_discovered(limit=900)
    known = _known_terms()
    ptidx = _pt_index()
    prev = days[1] if len(days) > 1 else None
    prev_set = ({r["keyword"] for r in db.list_discovered(day=prev, limit=3000)}
                if prev else set())

    alerts: list[dict] = []
    alerts += _season_alerts()
    if rows:
        alerts += _keyword_alerts(rows, known, prev_set, prev)
        alerts += _catalog_alerts(rows, ptidx)
    # Tín hiệu từ listed_at — chạy được KỂ CẢ khi không có Google Trends.
    alerts += _entry_alerts()

    # Sắp xếp: hot trước rồi theo độ lớn, nhưng đảm bảo mỗi nhóm đều có mặt.
    def _w(a):
        # Ưu tiên nền tìm kiếm thật hơn % tăng.
        base = a.get("_value") or 0
        try:
            m = abs(float(a["metric"].rstrip("%")))
        except ValueError:
            m = 0.0                    # "MỚI" — chưa có tỷ lệ đáng tin
        return (a["sev"] == "hot", base, m)

    alerts.sort(key=_w, reverse=True)
    by_kind: dict[str, list[dict]] = {}
    for a in alerts:
        by_kind.setdefault(a["kind"], []).append(a)

    QUOTA = 6                      # mỗi nhóm giữ tối đa 6 cái mạnh nhất trước
    picked, rest = [], []
    for k, lst in by_kind.items():
        picked += lst[:QUOTA]
        rest += lst[QUOTA:]
    picked.sort(key=_w, reverse=True)
    rest.sort(key=_w, reverse=True)
    alerts = (picked + rest)[:limit]
    for i, a in enumerate(alerts):
        a["id"] = i

    counts: dict[str, int] = {}
    for a in alerts:
        counts[a["kind"]] = counts.get(a["kind"], 0) + 1

    return {"available": bool(alerts), "generated_from": "live",
            "days": days, "compared_with": prev, "total_scanned": len(rows),
            "counts": counts, "alerts": alerts,
            "generated_at": datetime.now(timezone.utc).isoformat()}
