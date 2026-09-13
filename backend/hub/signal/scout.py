"""
TREND·SCOUT — Toplist và 7 lăng kính "Khám phá" của mục Top sản phẩm.

Công thức và CÁC MỨC lấy nguyên từ `Trend Signal Hub/Cach-tinh-tung-trang-thai.docx` (các số
tô đỏ trong tài liệu nằm ở `NGUONG`, chỉnh được theo từng sàn). Tài liệu ghi ba điều chung:
quét mỗi ngày một lần · cần ≥ 2 ngày để so sánh · tính riêng cho từng ngành.

    sàn        = Shopee VN · Shopee PH · 1688     (chữ "TikTok" trong file demo là viết nhầm cho 1688)
    lăng kính  = ban_chay · hot_gmv · hot_sold · steady · spike · gap · new

TÍNH BẰNG BAO NHIÊU NGÀY ĐANG CÓ. Chủ dự án chốt 13/09/2026: chưa đủ 7/10/30 ngày thì cửa sổ
co lại theo số ngày thật, công thức giữ nguyên, và mọi kết quả ghi kèm "tính trên N ngày".
Mức sàn duy nhất là mức của tài liệu — 2 lần quét. Hệ quả đã báo trước và được chấp nhận: khi
lịch sử còn ngắn, vài lăng kính mất độ phân biệt mà không báo lỗi —
  · Ổn định: "TB 7 ngày ≥ 80% TB 30 ngày" gần như luôn đạt vì hai cửa sổ trùng nhau.
  · Khe hở:  P20 của 2–3 giá trị ≈ trung vị, nên điều kiện "bán đều" gần như luôn đạt.
Hai lăng kính này tự sắc lại khi dữ liệu dày lên; `so_ngay` trên từng kết quả là để người xem biết.

"BÁN/NGÀY" LẤY Ở ĐÂU — khác nhau theo sàn, vì độ tin của hai con số trên hai sàn ngược nhau:
  · Shopee: HIỆU bộ đếm lũy kế giữa hai lần quét, chia đều cho số ngày giữa hai lần. Con số 30
    ngày của Shopee chỉ dùng làm chốt chặn bước nhảy vô lý (cùng guard với `top10._upd_series`).
  · 1688:   lũy kế bị làm tròn theo bậc ("1万+"), hiệu của nó toàn 0 rồi nhảy nghìn — ra đột biến
    giả. Nên bán/ngày = `sold_monthly` (bookedCount, chính xác) ÷ 30 tại mỗi lần quét. Đó là
    trung bình trượt 30 ngày: Tăng tốc vẫn có nghĩa, còn Đột biến gần như không bao giờ nổ trên
    1688 — vì chuỗi đã bị làm mượt, không phải vì thiếu sóng.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median

from .. import db
from . import store

SAN: dict[str, dict] = {
    "shopee_vn": {"platform": "shopee", "market": "vn", "cay": "vn", "nhan": "Shopee VN"},
    "shopee_ph": {"platform": "shopee", "market": "ph", "cay": "ph", "nhan": "Shopee PH"},
    # 1688 dùng CÂY NGÀNH VN: 205 cụm từ khoá của nó ánh xạ về ngành con Shopee VN (map_1688.py).
    "1688":      {"platform": "1688",   "market": "cn", "cay": "vn", "nhan": "1688"},
}

LANG_KINH = ("ban_chay", "hot_gmv", "hot_sold", "steady", "spike", "gap", "new")

#: Các số đỏ của tài liệu. Tên khoá = lăng kính + ý nghĩa, để trang cấu hình đọc thẳng được.
NGUONG: dict[str, float] = {
    "top_n": 100,                 # Toplist: Top 100 bán chạy / Top 100 doanh số
    "min_lan_quet": 2,            # "cần ≥ 2 ngày để so sánh"
    # 🔥 Đang tăng tốc
    "tang_toc_pct": 40,           # tăng ≥ 40%
    "tang_toc_luy_ke": 1000,      # đã bán lũy kế ≥ 1.000
    "tang_toc_cua_so": 7,         # 7 ngày này so 7 ngày trước
    # 🆕 Tân binh bán chạy
    "tan_binh_ngay": 21,          # xuất hiện không quá 21 ngày
    "tan_binh_da_ban": 300,       # đã bán ≥ 300
    # 💰 Bán khoẻ ổn định
    "on_dinh_moc": 100,           # sàn ≥ 100 sp/ngày
    "on_dinh_phan_vi": 20,        # sàn = mốc 20% từ dưới lên (ngày thấp thứ 6/30)
    "on_dinh_giu_nhiet": 80,      # TB 7 ngày ≥ 80% TB 30 ngày
    "on_dinh_cua_so": 30,
    # ⚡ Đột biến
    "dot_bien_pct": 500,          # vọt ≥ 500%
    "dot_bien_luy_ke": 1000,      # đã bán ≥ 1.000
    "dot_bien_nhanh": 2,          # 2 ngày cuối
    "dot_bien_nen": 10,           # nền ~10 ngày
    # 🎯 Khe hở
    "khe_ho_luy_ke": 1000,        # lũy kế > 1.000
    "khe_ho_deu": 90,             # P20 ≥ 90% mức thường
    "khe_ho_rating": 3.0,         # dẫn đầu có rating < 3.0★
}

BOUNDS: dict[str, tuple[float, float]] = {
    "top_n": (10, 500), "min_lan_quet": (2, 90),
    "tang_toc_pct": (1, 100_000), "tang_toc_luy_ke": (0, 10_000_000), "tang_toc_cua_so": (1, 45),
    "tan_binh_ngay": (1, 90), "tan_binh_da_ban": (0, 10_000_000),
    "on_dinh_moc": (0, 10_000_000), "on_dinh_phan_vi": (1, 99), "on_dinh_giu_nhiet": (1, 200),
    "on_dinh_cua_so": (7, 90),
    "dot_bien_pct": (10, 100_000), "dot_bien_luy_ke": (0, 10_000_000), "dot_bien_nhanh": (1, 7),
    "dot_bien_nen": (2, 60),
    "khe_ho_luy_ke": (0, 10_000_000), "khe_ho_deu": (1, 100), "khe_ho_rating": (0.1, 5.0),
}

#: Mẫu số tối thiểu (sp/ngày) cho các phép %. Nền 0 → 3 là "+∞%", và xếp thuần theo % thì cả
#: bảng toàn những dòng như thế. Cùng giá trị `floor` của top10.
NEN_TOI_THIEU = 1.0

#: Không tính lịch sử xa hơn kho giữ (db.GIU_NGAY) — cửa sổ dài nhất là 30 ngày cộng nền.
NGAY_TOI_DA = 90


def cau_hinh(san: str, saved: dict | None = None) -> dict:
    """Mức đang dùng = mức tài liệu, đè bằng giá trị đã lưu NẾU nằm trong khoảng hợp lệ."""
    cfg = dict(NGUONG)
    if saved is None:
        saved = store.get_config(f"scout:{san}")
    for k, v in (saved or {}).items():
        if k not in NGUONG:
            continue
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        lo, hi = BOUNDS[k]
        if lo <= num <= hi:
            cfg[k] = num if isinstance(NGUONG[k], float) else int(num)
    return cfg


def _san(san: str) -> dict:
    if san not in SAN:
        raise ValueError(f"sàn không hợp lệ: {san!r} — chọn một trong {list(SAN)}")
    return SAN[san]


# ───────────────────────── cây ngành ─────────────────────────

def _cay(san: str) -> tuple[list[dict], dict[str, list[str]]]:
    """(danh sách ngành lớn kèm ngành con, sub_id → mã category_code thật của sàn)."""
    s = _san(san)
    with db.connect() as c:
        rows = c.execute(
            "SELECT main_id, main_name, sub_id, sub_name FROM shopee_categories"
            " WHERE market=? AND active=1 ORDER BY CAST(main_id AS INTEGER), sheet_row",
            (s["cay"],)).fetchall()
        tu_khoa: dict[str, list[str]] = {}
        if s["platform"] == "1688":
            for r in c.execute("SELECT code, parent_code FROM crawl_categories"
                               " WHERE platform='1688' AND active=1 AND parent_code IS NOT NULL"):
                for sub in str(r["parent_code"]).split(","):
                    if sub.strip():
                        tu_khoa.setdefault(sub.strip(), []).append(r["code"])

    mains: dict[str, dict] = {}
    ma: dict[str, list[str]] = {}
    for r in rows:
        m = mains.setdefault(r["main_id"], {"main_id": r["main_id"], "main_name": r["main_name"],
                                            "subs": []})
        codes = tu_khoa.get(r["sub_id"], []) if s["platform"] == "1688" else [r["sub_id"]]
        if s["platform"] == "1688" and not codes:
            continue                          # ngành không có từ khoá 1688 (Sách, Khác...)
        m["subs"].append({"sub_id": r["sub_id"], "sub_name": r["sub_name"]})
        ma[r["sub_id"]] = codes
    return [m for m in mains.values() if m["subs"]], ma


def cay_nganh(san: str) -> dict:
    mains, _ = _cay(san)
    return {"san": san, "nhan": SAN[san]["nhan"], "nganh": mains}


def _ma_nganh(san: str, main_id: str, sub_id: str | None) -> tuple[list[str], str]:
    """
    Những `category_code` cần đọc cho một lựa chọn ngành, và nguồn của chúng.

    Ngành lớn Shopee đọc TẦNG LỚN đã cào riêng (hạng trong ngành cha khác gộp các ngành con —
    xem `shopee_categories.parents`). Tầng lớn bắt đầu cào từ 14/09/2026; trước ngày có dữ
    liệu thì gộp ngành con và nói rõ bằng `nguon = "gop_nganh_con"`.
    """
    s = _san(san)
    mains, ma = _cay(san)
    main = next((m for m in mains if m["main_id"] == str(main_id)), None)
    if main is None:
        raise ValueError(f"không có ngành lớn {main_id!r} trên {s['nhan']}")
    if sub_id:
        if str(sub_id) not in ma:
            raise ValueError(f"ngành con {sub_id!r} không thuộc {s['nhan']}")
        return ma[str(sub_id)], ("tu_khoa_1688" if s["platform"] == "1688" else "nganh_con")
    gop = [code for sub in main["subs"] for code in ma[sub["sub_id"]]]
    if s["platform"] == "1688":
        return gop, "tu_khoa_1688"
    with db.connect() as c:
        co_tang_lon = c.execute(
            "SELECT 1 FROM listings_snapshot WHERE platform=? AND market=? AND category_code=?"
            " LIMIT 1", (s["platform"], s["market"], str(main_id))).fetchone()
    return ([str(main_id)], "nganh_lon") if co_tang_lon else (gop, "gop_nganh_con")


# ───────────────────────── chuỗi bán/ngày ─────────────────────────

_COT = ("product_id, day, sold_cumulative, sold_monthly, sold_type, rank, category_code, title,"
        " price, currency, url, image_url, rating, reviews")


def _nap(platform: str, market: str, codes: list[str]) -> tuple[dict[str, list[dict]], list[str]]:
    """Mọi lần quét của các mã ngành, gom theo sản phẩm, MỘT dòng mỗi ngày mỗi sản phẩm."""
    if not codes:
        return {}, []
    dau = ",".join("?" * len(codes))
    with db.connect() as c:
        moi = c.execute(f"SELECT MAX(day) FROM listings_snapshot WHERE platform=? AND market=?"
                        f" AND category_code IN ({dau})", (platform, market, *codes)).fetchone()[0]
        if not moi:
            return {}, []
        tu = (date.fromisoformat(moi) - timedelta(days=NGAY_TOI_DA)).isoformat()
        rows = c.execute(
            f"SELECT {_COT} FROM listings_snapshot WHERE platform=? AND market=?"
            f" AND category_code IN ({dau}) AND day>=? ORDER BY product_id, day",
            (platform, market, *codes, tu)).fetchall()
    sp: dict[str, list[dict]] = {}
    ngay: set[str] = set()
    for r in rows:
        r = dict(r)
        ngay.add(r["day"])
        pts = sp.setdefault(r["product_id"], [])
        # Cùng sản phẩm hiện ở hai từ khoá 1688 trong cùng ngày: giữ một dòng (số giống nhau).
        if pts and pts[-1]["day"] == r["day"]:
            if (r["sold_monthly"] or 0) > (pts[-1]["sold_monthly"] or 0):
                pts[-1] = r
            continue
        pts.append(r)
    return sp, sorted(ngay)


def _chuoi(points: list[dict], platform: str) -> list[tuple[date, float, float]]:
    """
    (ngày, bán/ngày, doanh thu/ngày) — MỘT phần tử cho mỗi ngày lịch giữa lần quét đầu và cuối.

    Hai lần quét cách nhau g ngày thì lượng bán giữa chúng chia đều cho g ngày: ngày trống
    (lịch đêm hỏng 08–10/09) không bị đếm thành "ngày bán 0", cũng không bị gộp thành "một ngày
    bán gấp ba". Bước bị loại (xem dưới) để lại lỗ — thiếu còn hơn điền số bịa.
    """
    out: list[tuple[date, float, float]] = []
    for prev, cur in zip(points, points[1:]):
        d0, d1 = date.fromisoformat(prev["day"]), date.fromisoformat(cur["day"])
        gap = (d1 - d0).days
        if gap <= 0:
            continue
        if platform == "1688":
            if not cur["sold_monthly"]:
                continue
            rate = cur["sold_monthly"] / 30.0
        else:
            delta = (cur["sold_cumulative"] or 0) - (prev["sold_cumulative"] or 0)
            # Guard của top10._upd_series: bộ đếm giảm = sàn tính lại, không phải bán âm; một
            # bước bán nhiều hơn cả 30 ngày sàn tự khai = bộ đếm nhảy, không phải doanh số.
            if delta < 0:
                continue
            monthly = cur.get("sold_monthly")
            if monthly and gap <= 30 and delta > monthly:
                continue
            rate = delta / gap
        gia = cur["price"] or 0.0
        for i in range(1, gap + 1):
            out.append((d0 + timedelta(days=i), rate, rate * gia))
    return out


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _phan_vi(xs: list[float], p: float) -> float | None:
    """Mốc p% từ dưới lên, kiểu tài liệu: 20% của 30 ngày = ngày thấp thứ 6."""
    if not xs:
        return None
    k = max(1, math.ceil(round(p * len(xs) / 100.0, 9)))
    return sorted(xs)[min(k, len(xs)) - 1]


def _pct(cur: float | None, prev: float | None, nen: float) -> float | None:
    if cur is None or prev is None or prev < nen:
        return None
    return (cur - prev) / prev * 100.0


# ───────────────────────── 7 lăng kính ─────────────────────────

def _tinh(points: list[dict], platform: str, ngay_dau_nganh: str, ngay_moi: str, cfg: dict) -> dict:
    """Mọi chỉ số của MỘT sản phẩm, và nó lọt những lăng kính nào."""
    last = points[-1]
    gia = last["price"] or 0.0
    luy_ke = max(last["sold_cumulative"] or 0, last["sold_monthly"] or 0)
    ban_30_san = last["sold_monthly"] or 0
    the = {
        "product_id": last["product_id"], "title": last["title"], "url": last["url"],
        "image_url": last["image_url"], "price": last["price"], "currency": last["currency"],
        "rating": last["rating"], "reviews": last["reviews"],
        "sold_cumulative": last["sold_cumulative"], "sold_monthly": last["sold_monthly"],
        "rank": last["rank"], "doanh_so_30_san": ban_30_san * gia,
        "lan_quet": len(points), "ngay_dau": points[0]["day"], "ngay_cuoi": last["day"],
    }
    vao: dict[str, float] = {"ban_chay": float(ban_30_san)}

    chuoi = _chuoi(points, platform)
    L = len(chuoi)
    the["so_ngay"] = L
    if len(points) < cfg["min_lan_quet"] or L == 0:
        the["lang_kinh"] = vao
        return the

    ban = [x[1] for x in chuoi]
    tien = [x[2] for x in chuoi]
    the["ban_ngay_tb"] = _mean(ban)
    the["doanh_so_30"] = _mean(tien[-int(cfg["on_dinh_cua_so"]):]) * 30

    # 🔥 Tăng tốc: w ngày này so w ngày trước, w = min(7, nửa lịch sử).
    w = min(int(cfg["tang_toc_cua_so"]), L // 2)
    if w >= 1:
        g_ban = _pct(_mean(ban[-w:]), _mean(ban[-2 * w:-w]), NEN_TOI_THIEU)
        g_tien = _pct(_mean(tien[-w:]), _mean(tien[-2 * w:-w]), NEN_TOI_THIEU * gia)
        the.update(tang_toc_cua_so=w, tang_ban_pct=g_ban, tang_doanh_so_pct=g_tien)
        if luy_ke >= cfg["tang_toc_luy_ke"]:
            if g_ban is not None and g_ban >= cfg["tang_toc_pct"]:
                vao["hot_sold"] = g_ban
            if g_tien is not None and g_tien >= cfg["tang_toc_pct"]:
                vao["hot_gmv"] = g_tien

    # ⚡ Đột biến: 2 ngày cuối so nền ~10 ngày ngay trước.
    nhanh = min(int(cfg["dot_bien_nhanh"]), L - 1)
    nen = min(int(cfg["dot_bien_nen"]), L - nhanh)
    if nhanh >= 1 and nen >= 1:
        spike = _pct(_mean(ban[-nhanh:]), _mean(ban[-nhanh - nen:-nhanh]), NEN_TOI_THIEU)
        the.update(dot_bien_pct=spike, dot_bien_nhanh=nhanh, dot_bien_nen=nen)
        if spike is not None and spike >= cfg["dot_bien_pct"] and luy_ke >= cfg["dot_bien_luy_ke"]:
            vao["spike"] = spike

    # 💰 Ổn định + 🎯 Khe hở dùng chung cửa sổ 30 ngày và sàn P20.
    cua_so = ban[-int(cfg["on_dinh_cua_so"]):]
    san = _phan_vi(cua_so, cfg["on_dinh_phan_vi"])
    tb30 = _mean(cua_so)
    tb7 = _mean(cua_so[-7:])
    thuong = median(cua_so)
    the.update(san_ngay=san, tb_7=tb7, tb_30=tb30, muc_thuong=thuong,
               doanh_thu_san_30=(san or 0) * 30 * gia)
    if san is not None and san >= cfg["on_dinh_moc"] and tb30 and tb7 >= tb30 * cfg["on_dinh_giu_nhiet"] / 100:
        vao["steady"] = the["doanh_thu_san_30"]

    rating = last["rating"] or 0
    if (luy_ke > cfg["khe_ho_luy_ke"] and thuong > 0 and san is not None
            and san >= thuong * cfg["khe_ho_deu"] / 100
            and 0 < rating < cfg["khe_ho_rating"]):
        vao["gap"] = the["doanh_so_30"]

    # 🆕 Tân binh: số ngày xuất hiện đếm từ lần đầu thấy nó TRONG NGÀNH NÀY. Sản phẩm có sẵn từ
    # lần quét đầu tiên của ngành thì không biết nó xuất hiện khi nào — không coi là mới.
    if points[0]["day"] > ngay_dau_nganh:
        tuoi = (date.fromisoformat(ngay_moi) - date.fromisoformat(points[0]["day"])).days + 1
        the["ngay_xuat_hien"] = tuoi
        if tuoi <= cfg["tan_binh_ngay"] and luy_ke >= cfg["tan_binh_da_ban"]:
            vao["new"] = luy_ke / tuoi

    the["lang_kinh"] = vao
    return the


_LY_DO = {
    "ban_chay": "Sàn xếp theo lượt bán 30 ngày",
    "hot_gmv":  "Doanh số/ngày {tang_toc_cua_so} ngày gần so {tang_toc_cua_so} ngày trước",
    "hot_sold": "Bán/ngày {tang_toc_cua_so} ngày gần so {tang_toc_cua_so} ngày trước",
    "steady":   "Sàn P20 ≥ mốc tối thiểu, TB 7 ngày ≥ 80% TB 30 ngày",
    "spike":    "Bán/ngày {dot_bien_nhanh} ngày cuối so nền {dot_bien_nen} ngày trước",
    "gap":      "Cầu đều, listing dẫn đầu rating thấp",
    "new":      "Đã bán ÷ số ngày từ khi xuất hiện",
}


#: Kết quả tính của từng ngành, giữ trong tiến trình. Khoá gồm dấu thời gian lượt cào mới nhất
#: của sàn, nên một lượt cào xong (hay đang chạy dở) là tự tính lại — không cần xoá tay.
#: Cần vì "Tất cả ngành" tính lại ~200 ngành mỗi lần bấm: đủ 90 ngày là ~1 triệu dòng một lượt.
_CACHE: dict[tuple, tuple[list[dict], list[str]]] = {}
_CACHE_MAX = 3000


def _dau_cao(platform: str, market: str) -> str:
    with db.connect() as c:
        row = c.execute("SELECT MAX(finished_at) FROM crawl_log WHERE source=? AND market_code=?",
                        (platform, market)).fetchone()
    return row[0] or ""


def _tinh_nganh(s: dict, codes: list[str], cfg: dict, dau: str | None = None) -> tuple[list[dict], list[str]]:
    """Thẻ của mọi sản phẩm trong MỘT ngành, và các ngày ngành đó đã được quét."""
    dau = _dau_cao(s["platform"], s["market"]) if dau is None else dau
    khoa = (s["platform"], s["market"], tuple(codes), tuple(sorted(cfg.items())), dau)
    if khoa in _CACHE:
        the, ngay = _CACHE[khoa]
        # Bản sao nông từng thẻ: `kham_pha` gắn thêm `diem`, `ly_do`, tên ngành vào thẻ, và sửa
        # thẳng lên bản trong bộ đệm thì lần bấm sau thấy điểm của lăng kính trước.
        return [{**t, "lang_kinh": dict(t["lang_kinh"])} for t in the], ngay
    the, ngay = _tinh_nganh_that(s, codes, cfg)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[khoa] = ([{**t, "lang_kinh": dict(t["lang_kinh"])} for t in the], ngay)
    return the, ngay


def _tinh_nganh_that(s: dict, codes: list[str], cfg: dict) -> tuple[list[dict], list[str]]:
    sp, ngay = _nap(s["platform"], s["market"], codes)
    if not ngay:
        return [], ngay
    # Chỉ sản phẩm CÓ MẶT ở lần quét mới nhất: rớt khỏi danh sách hôm nay thì không còn
    # "đang tăng tốc" hay "đột biến" nữa, và chuỗi của nó dừng ở một ngày cũ.
    moi = ngay[-1]
    return [_tinh(pts, s["platform"], ngay[0], moi, cfg)
            for pts in sp.values() if pts[-1]["day"] == moi], ngay


def kham_pha(san: str, main_id: str | None = None, sub_id: str | None = None,
             lens: str = "ban_chay", limit: int = 100, cfg: dict | None = None) -> dict:
    """
    Một ngành × một lăng kính. `main_id` rỗng = TẤT CẢ NGÀNH.

    "Tất cả ngành" vẫn TÍNH RIÊNG TỪNG NGÀNH CON rồi mới gộp, đúng câu "tính riêng cho từng
    ngành" của tài liệu: một sản phẩm "tăng tốc" là so với chính nó, còn "tân binh" là mới
    xuất hiện trong ngành của nó. Sản phẩm hiện ở hai ngành thì giữ một thẻ, lăng kính nào
    cũng lấy điểm cao hơn.
    """
    s = _san(san)
    if lens not in LANG_KINH:
        raise ValueError(f"lăng kính không hợp lệ: {lens!r}")
    cfg = cfg or cau_hinh(san)

    if main_id:
        codes, nguon = _ma_nganh(san, main_id, sub_id)
        the, ngay = _tinh_nganh(s, codes, cfg)
        so_lan = len(ngay)
    else:
        nguon = "tat_ca_nganh_con"
        mains, ma = _cay(san)
        gop: dict[str, dict] = {}
        tat_ca_ngay: set[str] = set()
        so_lan = 0
        dau = _dau_cao(s["platform"], s["market"])
        for m in mains:
            for sub in m["subs"]:
                the_i, ngay_i = _tinh_nganh(s, ma[sub["sub_id"]], cfg, dau)
                tat_ca_ngay.update(ngay_i)
                so_lan = max(so_lan, len(ngay_i))
                for t in the_i:
                    t.update(main_id=m["main_id"], main_name=m["main_name"],
                             sub_id=sub["sub_id"], sub_name=sub["sub_name"])
                    cu = gop.get(t["product_id"])
                    if cu is None:
                        gop[t["product_id"]] = t
                        continue
                    for k, v in t["lang_kinh"].items():
                        cu["lang_kinh"][k] = max(v, cu["lang_kinh"].get(k, v))
        the, ngay = list(gop.values()), sorted(tat_ca_ngay)

    out = {"san": san, "nhan": s["nhan"], "main_id": main_id or None, "sub_id": sub_id,
           "nguon": nguon, "ngay_quet": ngay, "so_lan_quet": so_lan,
           "so_ngay": ((date.fromisoformat(ngay[-1]) - date.fromisoformat(ngay[0])).days
                       if len(ngay) >= 2 else 0),
           "nguong": cfg, "lens": lens, "dem": {k: 0 for k in LANG_KINH},
           "tong_san_pham": len(the), "items": []}
    if not ngay:
        out["ghi_chu"] = "Ngành này chưa có dữ liệu."
        return out
    if so_lan < cfg["min_lan_quet"]:
        out["ghi_chu"] = (f"Mới có {so_lan} lần quét — cần ≥ {cfg['min_lan_quet']} để so sánh. "
                          "Chỉ lăng kính Bán chạy có số.")

    for t in the:
        for k in t["lang_kinh"]:
            out["dem"][k] += 1
    chon = sorted((t for t in the if lens in t["lang_kinh"]),
                  key=lambda t: t["lang_kinh"][lens], reverse=True)[:int(limit)]
    for t in chon:
        t["diem"] = t["lang_kinh"][lens]
        t["ly_do"] = _LY_DO[lens].format(**{**cfg, **t})
    out["items"] = chon
    return out


def toplist(san: str, loai: str = "ban_chay", limit: int | None = None) -> dict:
    """
    Top 100 bán chạy / doanh số của TẤT CẢ ngành trên một sàn — số 30 ngày của sàn, chỉ cần 1 ngày.

    Mỗi sản phẩm lấy lần quét MỚI NHẤT trong 3 ngày cuối: một đêm cào dở (như 11/09) không làm
    Toplist chỉ còn 20 ngành. Sản phẩm hiện ở cả ngành lớn lẫn ngành con thì gắn nhãn ngành con,
    để bấm vào mở đúng chỗ trong Khám phá.
    """
    s = _san(san)
    if loai not in ("ban_chay", "doanh_so"):
        raise ValueError("loai phải là ban_chay hoặc doanh_so")
    cfg = cau_hinh(san)
    limit = int(limit or cfg["top_n"])
    mains, ma = _cay(san)
    ten: dict[str, tuple[dict, dict | None]] = {}      # category_code → (ngành lớn, ngành con)
    for m in mains:
        ten[m["main_id"]] = (m, None)
        for sub in m["subs"]:
            for code in ma[sub["sub_id"]]:
                ten[code] = (m, sub)
    with db.connect() as c:
        moi = c.execute("SELECT MAX(day) FROM listings_snapshot WHERE platform=? AND market=?",
                        (s["platform"], s["market"])).fetchone()[0]
        if not moi:
            return {"san": san, "loai": loai, "items": [], "ghi_chu": "Sàn chưa có dữ liệu."}
        tu = (date.fromisoformat(moi) - timedelta(days=2)).isoformat()
        rows = c.execute(f"SELECT {_COT} FROM listings_snapshot WHERE platform=? AND market=?"
                         f" AND day>=? ORDER BY day", (s["platform"], s["market"], tu)).fetchall()
    best: dict[str, dict] = {}
    for r in rows:
        r = dict(r)
        cu = best.get(r["product_id"])
        la_con = ten.get(r["category_code"], (None, None))[1] is not None
        if cu is None or r["day"] > cu["day"] or (r["day"] == cu["day"] and la_con and not cu["_con"]):
            r["_con"] = la_con
            best[r["product_id"]] = r
    items = []
    for r in best.values():
        m, sub = ten.get(r["category_code"], (None, None))
        ban = r["sold_monthly"] or 0
        items.append({
            "product_id": r["product_id"], "title": r["title"], "url": r["url"],
            "image_url": r["image_url"], "price": r["price"], "currency": r["currency"],
            "rating": r["rating"], "reviews": r["reviews"], "sold_cumulative": r["sold_cumulative"],
            "ban_30": ban, "doanh_so_30": ban * (r["price"] or 0), "ngay": r["day"],
            "main_id": m["main_id"] if m else None, "main_name": m["main_name"] if m else None,
            "sub_id": sub["sub_id"] if sub else None, "sub_name": sub["sub_name"] if sub else None,
        })
    khoa = "ban_30" if loai == "ban_chay" else "doanh_so_30"
    items.sort(key=lambda x: x[khoa], reverse=True)
    return {"san": san, "nhan": s["nhan"], "loai": loai, "ngay_moi_nhat": moi, "tu_ngay": tu,
            "items": items[:limit]}
