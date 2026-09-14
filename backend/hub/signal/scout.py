"""
TREND·SCOUT — Toplist và 6 lăng kính "Khám phá" của mục Top sản phẩm.

Công thức và CÁC MỨC lấy nguyên từ `Trend Signal Hub/Cach-tinh-tung-trang-thai.docx` (các số
tô đỏ trong tài liệu nằm ở `NGUONG`, chỉnh được theo từng sàn). Tài liệu ghi ba điều chung:
quét mỗi ngày một lần · cần ≥ 2 ngày để so sánh · tính riêng cho từng ngành.

    sàn        = Shopee VN · Shopee PH · 1688     (chữ "TikTok" trong file demo là viết nhầm cho 1688)
    lăng kính  = ban_chay · hot · steady · spike · gap · new

CỬA SỔ CHUẨN LÀ 5 NGÀY (chủ dự án chốt 14/09/2026, hạ từ 7/10/30 ngày). Lịch sử thật mới có
3–4 mốc quét nên cửa sổ dài chỉ cho ra những lăng kính rỗng; 5 ngày là mức vừa đủ để so "kỳ này
với kỳ trước" mà dữ liệu hiện có đáp ứng được.

TĂNG TỐC LÀ MỘT LĂNG KÍNH, KHÔNG PHẢI HAI. Trước đây tách `hot_gmv` (doanh số) và `hot_sold`
(lượt bán) thành hai bảng; 14/09/2026 gộp lại thành `hot` với HAI ĐIỀU KIỆN PHẢI ĐẠT CẢ HAI —
bán lũy kế ≥ mức tối thiểu VÀ tốc độ bán/ngày tăng ≥ mức. Doanh số vẫn được tính và hiện ra
(`tang_doanh_so_pct`) nhưng chỉ để đọc thêm, không còn là một bảng riêng.

TÍNH BẰNG BAO NHIÊU NGÀY ĐANG CÓ. Chưa đủ 5 ngày thì cửa sổ co lại theo số ngày thật, công
thức giữ nguyên, và mọi kết quả ghi kèm "tính trên N ngày". Mức sàn duy nhất là mức của tài
liệu — 2 lần quét. Hệ quả đã báo trước và được chấp nhận: khi lịch sử còn ngắn, vài lăng kính
mất độ phân biệt mà không báo lỗi —
  · Ổn định: "TB 3 ngày ≥ 80% TB 5 ngày" gần như luôn đạt vì hai cửa sổ trùng nhau.
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
import re
import unicodedata
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

#: Thứ tự này là thứ tự bày ra trên giao diện — Tân binh ĐỂ CUỐI, theo tài liệu 14/09/2026.
LANG_KINH = ("ban_chay", "hot", "steady", "spike", "gap", "new")

#: Các số đỏ của tài liệu. Tên khoá = lăng kính + ý nghĩa, để trang cấu hình đọc thẳng được.
NGUONG: dict[str, float] = {
    "top_n": 200,                 # Toplist / Khám phá: 200 sản phẩm, giao diện chia 3 trang
    "min_lan_quet": 2,            # "cần ≥ 2 ngày để so sánh"
    # 🔥 Đang tăng tốc — MỘT lăng kính, phải đạt CẢ HAI điều kiện dưới đây
    "tang_toc_pct": 40,           # bán/ngày tăng ≥ 40%
    "tang_toc_luy_ke": 1000,      # VÀ đã bán lũy kế ≥ 1.000
    "tang_toc_cua_so": 5,         # 5 ngày này so 5 ngày trước
    # 💰 Bán khoẻ ổn định
    "on_dinh_moc": 100,           # sàn ≥ 100 sp/ngày
    "on_dinh_phan_vi": 20,        # sàn = mốc 20% từ dưới lên → 80% số ngày bán hơn mức này
    "on_dinh_giu_nhiet": 80,      # chưa hạ nhiệt: TB 3 ngày gần nhất ≥ 80% TB 5 ngày
    "on_dinh_cua_so": 5,
    "on_dinh_gan_day": 3,
    # ⚡ Đột biến
    "dot_bien_pct": 500,          # vọt ≥ 500%
    "dot_bien_luy_ke": 1000,      # đã bán ≥ 1.000
    "dot_bien_nhanh": 1,          # 1 ngày gần nhất
    "dot_bien_nen": 5,            # so với nền 5 ngày trước đó
    # 🎯 Khe hở
    "khe_ho_luy_ke": 1000,        # lũy kế > 1.000
    "khe_ho_deu": 90,             # P20 ≥ 90% mức thường
    "khe_ho_rating": 4.0,         # dẫn đầu có rating < 4.0★
    # 🆕 Tân binh bán chạy (để cuối)
    "tan_binh_ngay": 21,          # xuất hiện không quá 21 ngày
    "tan_binh_da_ban": 300,       # đã bán ≥ 300
    "tan_binh_ty_le": 1.2,        # VÀ lũy kế ≤ 1,2 × bán-30-ngày (xem `_tinh`)
}

BOUNDS: dict[str, tuple[float, float]] = {
    "top_n": (10, 500), "min_lan_quet": (2, 90),
    "tang_toc_pct": (1, 100_000), "tang_toc_luy_ke": (0, 10_000_000), "tang_toc_cua_so": (1, 45),
    "tan_binh_ngay": (1, 90), "tan_binh_da_ban": (0, 10_000_000),
    "tan_binh_ty_le": (1.0, 100.0),
    "on_dinh_moc": (0, 10_000_000), "on_dinh_phan_vi": (1, 99), "on_dinh_giu_nhiet": (1, 200),
    # Cửa sổ ổn định xuống 5 ngày nên cận dưới phải là 2, không còn là 7.
    "on_dinh_cua_so": (2, 90), "on_dinh_gan_day": (1, 60),
    "dot_bien_pct": (10, 100_000), "dot_bien_luy_ke": (0, 10_000_000), "dot_bien_nhanh": (1, 7),
    "dot_bien_nen": (1, 60),
    "khe_ho_luy_ke": (0, 10_000_000), "khe_ho_deu": (1, 100), "khe_ho_rating": (0.1, 5.0),
}

#: Mẫu số tối thiểu (sp/ngày) cho các phép %. Nền 0 → 3 là "+∞%", và xếp thuần theo % thì cả
#: bảng toàn những dòng như thế. Cùng giá trị `floor` của top10.
NEN_TOI_THIEU = 1.0

#: Không tính lịch sử xa hơn kho giữ (db.GIU_NGAY) — cửa sổ dài nhất là 5 ngày cộng nền.
NGAY_TOI_DA = 90


# ───────────────────────── lọc hàng ảo ─────────────────────────
#
# Một phần listing trên sàn KHÔNG PHẢI hàng bán thật: quà tặng kèm đơn, hàng mẫu, ô bù chênh
# lệch, link đặt cọc, ô phí ship lẻ. Giá của chúng là giá ảo — 0đ, 1đ, hoặc chỉ là phần chênh —
# nên hai chỗ hỏng cùng lúc:
#   · doanh số = giá × lượt bán ra gần 0, kéo lệch mọi bảng xếp theo tiền;
#   · lượt bán lại rất lớn (tặng kèm mỗi đơn một cái), nên chúng leo thẳng đầu bảng "bán chạy".
# Chủ dự án chốt 14/09/2026: loại hẳn khỏi mọi bảng.

def _fold(s: str) -> str:
    """
    Bỏ dấu + thường hoá + BỎ DẤU CÂU, để so khớp tên ngành với câu hỏi gõ không dấu.

    Dấu câu phải thành khoảng trắng chứ không được giữ: "đồ mẹ và bé, sắp tựu trường" tách ra
    chữ "be," có dính dấu phẩy, không khớp "bé" của ngành "Mẹ & Bé" — cả ngành biến mất khỏi
    phần lọc chỉ vì một dấu phẩy. Đo 14/09/2026. Tên ngành cũng đầy "&", "/", "," nên cùng một
    phép chuẩn hoá phải chạy cho cả hai phía.
    """
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"[^0-9a-z]+", " ", s).strip()


#: Cụm từ (viết KHÔNG DẤU, đúng dạng `_fold` trả về) tố cáo một listing hàng ảo. Sửa danh sách
#: này là cách duy nhất để nới/siết bộ lọc — đừng rải điều kiện ra các hàm tính.
TU_HANG_AO = (
    # quà tặng / hàng tặng
    "qua tang", "qua tang kem", "hang tang", "tang kem", "khong ban rieng", "gift", "gifts",
    "freebie", "freebies", "giveaway",
    # không bán / không giao
    "khong ban", "ko ban", "khong ship", "khong giao", "not for sale", "do not buy",
    "do not order", "dont buy",
    # hàng mẫu
    "hang mau", "mau thu", "sample only", "free sample",
    # ô bù tiền / đặt cọc / phí ship lẻ
    "bu tien", "bu chenh", "bu chenh lech", "chenh lech gia", "dat coc", "tien coc",
    "phi ship", "phi van chuyen", "cuoc ship", "shipping fee", "deposit only",
    # link phụ
    "link rieng", "link phu", "link bu", "test order", "dummy",
)

#: Tiếng Trung cho 1688 — khớp thẳng trên TÊN GỐC, vì `_fold` bỏ sạch chữ Hán. Chỉ những cụm
#: gần như luôn là link phụ; cố tình KHÔNG có "礼品" (quà tặng) vì trên 1688 đó là cả một ngành
#: hàng thật, đưa vào là quét sạch mấy nghìn sản phẩm bán thật.
TU_HANG_AO_CN = (
    "补差价", "差价链接", "专拍", "勿拍", "不发货", "赠品", "样品链接", "不卖",
    "运费链接", "邮费差", "定金", "订金",
)

_RX_HANG_AO = re.compile(r"\b(?:%s)\b" % "|".join(sorted(set(TU_HANG_AO), key=len, reverse=True)))


def la_hang_ao(title: str | None) -> bool:
    """
    Tên sản phẩm có dấu hiệu là listing hàng ảo (quà tặng, hàng mẫu, ô bù tiền…) hay không.

    Khớp NGUYÊN CHỮ (`\\b`) chứ không khớp chuỗi con: "gift" không được nuốt "gifted", và
    "ko ban" không được nuốt "khoban". Tên rỗng thì KHÔNG kết luận là ảo — không biết thì giữ,
    vì bỏ nhầm một sản phẩm thật tệ hơn là để lọt một sản phẩm ảo.
    """
    if not title:
        return False
    if any(t in title for t in TU_HANG_AO_CN):
        return True
    return bool(_RX_HANG_AO.search(_fold(title)))


def bo_hang_ao(rows: list[dict]) -> tuple[list[dict], int]:
    """(danh sách đã bỏ hàng ảo, số dòng đã bỏ) — để bảng nào cũng khoe được con số đã lọc."""
    giu = [r for r in rows if not la_hang_ao(r.get("title"))]
    return giu, len(rows) - len(giu)


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
    # `nen` có thể bằng 0 khi đo doanh số của listing chưa có giá.  Khi đó
    # `prev < nen` không chặn được `prev == 0`, dẫn tới chia cho 0 và làm hỏng
    # cả truy vấn Khám phá.  Không có nền dương thì không thể kết luận % tăng.
    if cur is None or prev is None or prev <= 0 or prev < nen:
        return None
    return (cur - prev) / prev * 100.0


# ───────────────────────── 6 lăng kính ─────────────────────────

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

    # 🆕 Tân binh: XÉT TRƯỚC cửa "cần ≥ 2 lần quét" bên dưới, vì đây là lăng kính DUY NHẤT không
    # so hai kỳ với nhau — nó chỉ hỏi "xuất hiện bao lâu rồi, đã bán bao nhiêu". Một sản phẩm
    # vừa hiện ra trong lần quét hôm nay mới có đúng 1 mốc, và đó CHÍNH LÀ tân binh điển hình;
    # để nó rơi vào cửa 2-lần-quét thì bảng Tân binh rỗng trơn suốt những ngày kho còn mỏng.
    #
    # Số ngày xuất hiện đếm từ lần đầu thấy nó TRONG NGÀNH NÀY. Sản phẩm có sẵn từ lần quét đầu
    # tiên của ngành thì không biết nó xuất hiện khi nào — không coi là mới.
    #
    # "Lần đầu thấy" KHÔNG ĐỦ để kết luận là hàng mới, và đây là chỗ dễ sai nhất của cả file.
    # Mỗi lượt cào chỉ lấy top-N của ngành, mà độ phủ thay đổi từng đêm (Shopee VN: 17.140 dòng
    # ngày 10/09 → 22.634 dòng ngày 14/09). Một sản phẩm cũ vừa leo vào top sẽ "lần đầu xuất
    # hiện" hôm nay — đo 14/09/2026 thì 7.321/18.859 sản phẩm lọt Tân binh, dòng đầu bảng là
    # hàng đã bán 1,9 triệu lượt bị ghi "xuất hiện 1 ngày".
    #
    # Chốt chặn: hàng thật sự ≤ 21 ngày tuổi thì CẢ ĐỜI nó bán gọn trong 30 ngày qua, nên lũy kế
    # phải xấp xỉ bán-30-ngày của sàn. Lũy kế lớn hơn nhiều lần = hàng cũ, dù ta mới thấy lần đầu.
    # Chủ dự án chọn mức chặt 1,2 lần (14/09/2026). Không có số bán-30-ngày thì không kiểm được
    # tuổi → không nhận, vì nhận nhầm hàng cũ tệ hơn là bỏ sót một tân binh.
    # Đo ngay sau khi thêm chốt: Shopee VN 7.321 → 189, Shopee PH → 66.
    #
    # CHỐT CHẶN NÀY KHÔNG CHẠY TRÊN 1688 và đó là giới hạn của dữ liệu, không phải lỗi: 1688
    # không có bộ đếm lũy kế đáng tin (bị làm tròn theo bậc "1万+"), nên `luy_ke` ở trên rơi về
    # đúng `sold_monthly` và phép so luôn luôn đạt. Tân binh 1688 vì thế vẫn lẫn hàng cũ mới lọt
    # top từ khoá. Muốn siết thì phải có thêm ngày mở shop/ngày đăng, kho hiện chưa cào.
    if points[0]["day"] > ngay_dau_nganh:
        tuoi = (date.fromisoformat(ngay_moi) - date.fromisoformat(points[0]["day"])).days + 1
        the["ngay_xuat_hien"] = tuoi
        if (tuoi <= cfg["tan_binh_ngay"] and luy_ke >= cfg["tan_binh_da_ban"]
                and ban_30_san > 0 and luy_ke <= ban_30_san * cfg["tan_binh_ty_le"]):
            vao["new"] = luy_ke / tuoi

    chuoi = _chuoi(points, platform)
    L = len(chuoi)
    the["so_ngay"] = L
    if len(points) < cfg["min_lan_quet"] or L == 0:
        the["lang_kinh"] = vao
        return the

    ban = [x[1] for x in chuoi]
    tien = [x[2] for x in chuoi]
    the["ban_ngay_tb"] = _mean(ban)

    # 🔥 Đang tăng tốc: w ngày này so w ngày trước, w = min(5, nửa lịch sử).
    #
    # MỘT lăng kính, HAI điều kiện phải đạt CẢ HAI: bán lũy kế ≥ mức, VÀ bán/ngày tăng ≥ mức.
    # Xếp theo mức tăng. `tang_doanh_so_pct` vẫn tính để hiện thêm trên thẻ, nhưng không còn là
    # cửa vào một bảng riêng — tách "tăng tốc doanh số" ra khỏi "tăng tốc lượt bán" cho hai bảng
    # gần trùng nhau, người xem phải đọc hai lần cùng một nhóm sản phẩm.
    w = min(int(cfg["tang_toc_cua_so"]), L // 2)
    if w >= 1:
        g_ban = _pct(_mean(ban[-w:]), _mean(ban[-2 * w:-w]), NEN_TOI_THIEU)
        g_tien = _pct(_mean(tien[-w:]), _mean(tien[-2 * w:-w]), NEN_TOI_THIEU * gia)
        the.update(tang_toc_cua_so=w, tang_ban_pct=g_ban, tang_doanh_so_pct=g_tien)
        if (luy_ke >= cfg["tang_toc_luy_ke"]
                and g_ban is not None and g_ban >= cfg["tang_toc_pct"]):
            vao["hot"] = g_ban

    # ⚡ Đột biến: 1 ngày gần nhất so nền 5 ngày ngay trước.
    nhanh = min(int(cfg["dot_bien_nhanh"]), L - 1)
    nen = min(int(cfg["dot_bien_nen"]), L - nhanh)
    if nhanh >= 1 and nen >= 1:
        spike = _pct(_mean(ban[-nhanh:]), _mean(ban[-nhanh - nen:-nhanh]), NEN_TOI_THIEU)
        the.update(dot_bien_pct=spike, dot_bien_nhanh=nhanh, dot_bien_nen=nen)
        if spike is not None and spike >= cfg["dot_bien_pct"] and luy_ke >= cfg["dot_bien_luy_ke"]:
            vao["spike"] = spike

    # 💰 Ổn định + 🎯 Khe hở dùng chung cửa sổ 5 ngày và sàn P20.
    #
    # `n` là số ngày THẬT nằm trong cửa sổ, không phải mức 5 của cấu hình: khi lịch sử mới có
    # 3 ngày thì doanh thu phải nhân 3, nhân 5 là bịa thêm hai ngày chưa từng được quét.
    cua_so = ban[-int(cfg["on_dinh_cua_so"]):]
    n = len(cua_so)
    san = _phan_vi(cua_so, cfg["on_dinh_phan_vi"])
    tb_cua_so = _mean(cua_so)
    gan = min(int(cfg["on_dinh_gan_day"]), n)
    tb_gan = _mean(cua_so[-gan:])
    thuong = median(cua_so)
    the.update(san_ngay=san, on_dinh_cua_so=n, on_dinh_gan_day=gan,
               tb_gan=tb_gan, tb_cua_so=tb_cua_so, muc_thuong=thuong,
               doanh_thu_san=(san or 0) * n * gia,
               doanh_so_cua_so=sum(tien[-n:]))
    if (san is not None and san >= cfg["on_dinh_moc"] and tb_cua_so
            and tb_gan >= tb_cua_so * cfg["on_dinh_giu_nhiet"] / 100):
        vao["steady"] = the["doanh_thu_san"]

    rating = last["rating"] or 0
    if (luy_ke > cfg["khe_ho_luy_ke"] and thuong > 0 and san is not None
            and san >= thuong * cfg["khe_ho_deu"] / 100
            and 0 < rating < cfg["khe_ho_rating"]):
        vao["gap"] = the["doanh_so_cua_so"]

    the["lang_kinh"] = vao
    return the


_LY_DO = {
    "ban_chay": "Sàn xếp theo lượt bán 30 ngày",
    "hot":      "Bán/ngày {tang_toc_cua_so} ngày gần so {tang_toc_cua_so} ngày trước",
    "steady":   "Sàn P20 ≥ mốc tối thiểu, TB {on_dinh_gan_day} ngày ≥ 80% TB {on_dinh_cua_so} ngày",
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
    #
    # Hàng ảo (quà tặng, ô bù tiền…) loại NGAY TẠI ĐÂY, trước khi tính: vừa khỏi phải nhớ lọc
    # lại ở từng lăng kính, vừa đỡ tính chuỗi cho những sản phẩm sẽ bị vứt.
    moi = ngay[-1]
    return [_tinh(pts, s["platform"], ngay[0], moi, cfg)
            for pts in sp.values()
            if pts[-1]["day"] == moi and not la_hang_ao(pts[-1]["title"])], ngay


def kham_pha(san: str, main_id: str | None = None, sub_id: str | None = None,
             lens: str = "ban_chay", limit: int | None = None, cfg: dict | None = None) -> dict:
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
    limit = int(limit or cfg["top_n"])

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
                  key=lambda t: t["lang_kinh"][lens], reverse=True)[:limit]
    for t in chon:
        t["diem"] = t["lang_kinh"][lens]
        t["ly_do"] = _LY_DO[lens].format(**{**cfg, **t})
    out["items"] = chon
    return out


def toplist(san: str, loai: str = "ban_chay", limit: int | None = None) -> dict:
    """
    Top bán chạy / doanh số của TẤT CẢ ngành trên một sàn — số 30 ngày của sàn, chỉ cần 1 ngày.

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
    # Hàng ảo lọc SAU khi dựng thẻ chứ không lọc lúc đọc kho, để `da_loc` đếm đúng số sản phẩm
    # người dùng đáng lẽ nhìn thấy — mỗi product_id một lần, không phải mỗi dòng snapshot.
    items, da_loc = bo_hang_ao(items)
    khoa = "ban_30" if loai == "ban_chay" else "doanh_so_30"
    items.sort(key=lambda x: x[khoa], reverse=True)
    return {"san": san, "nhan": s["nhan"], "loai": loai, "ngay_moi_nhat": moi, "tu_ngay": tu,
            "da_loc": da_loc, "items": items[:limit]}


# ═══════════════ TRA CỨU CHO ONE-SHOT AI ═══════════════
#
# One-shot AI KHÔNG gửi cả kho cho Gemini — 69.780 dòng ≈ 3 triệu token, vượt cửa sổ model và
# đốt sạch hạn mức miễn phí. Thay vào đó backend LỌC TRƯỚC ngay tại đây: sắp xếp là việc của
# kho (0 token), Gemini chỉ đọc phần đã lọc (~vài trăm token) rồi diễn giải. Chốt 14/09/2026.

#: Chữ quá chung, xuất hiện ở nhiều tên ngành nên không dùng để nhận diện ngành được.
#: CHỈ từ nối và chữ vô nghĩa khi nhận diện ngành. Đừng nhét chữ CÓ NGHĨA vào đây: từng bỏ
#: "nữ", "thể thao" và hậu quả là "Giày Dép Nữ" teo còn {giày, dép}, hoà điểm với "Phụ kiện giày
#: dép" rồi thua nó — câu hỏi "giày dép nữ" trả về phụ kiện. Đo 14/09/2026.
_CHU_CHUNG = set("va cac cho do dung loai khac online other others"
                 # Chữ của CÂU HỎI chứ không của ngành: "sản phẩm nào bán chạy nhất" từng khớp
                 # nhầm ngành "Bộ sản phẩm làm đẹp" chỉ vì hai chữ "sản phẩm".
                 " san pham hang shop mua ban gia".split())


#: Chữ gọi tên một sàn trong câu hỏi. Khớp theo CỤM (đã bỏ dấu) — xem `san_lien_quan`.
_TU_SAN: dict[str, tuple[str, ...]] = {
    "shopee_vn": ("shopee vn", "shopee viet nam", "shopee vietnam", "san vn", "thi truong vn",
                  "viet nam", "trong nuoc"),
    "shopee_ph": ("shopee ph", "shopee philippines", "philippines", "phi lip pin", "san ph",
                  "thi truong ph"),
    # KHÔNG có "hang si" ở đây dù 1688 đúng là sàn sỉ: "hàng sỉ" là chữ thông dụng của người bán
    # Việt, câu "hàng sỉ bán chạy trên Shopee VN" bị kéo thêm cả 1688 vào. "nguồn sỉ" thì cụ thể
    # về việc đi tìm nguồn nhập nên giữ.
    "1688":      ("1688", "alibaba", "taobao", "trung quoc", "nguon si", "nguon hang si"),
}

#: Chữ viết tắt phải khớp NGUYÊN TỪ, không khớp chuỗi con: "vn" nằm trong "tvn", "advn"…
_TU_SAN_NGUYEN = {"vn": "shopee_vn", "ph": "shopee_ph", "1688": "1688"}


def san_lien_quan(cau_hoi: str) -> list[str]:
    """
    Sàn mà câu hỏi nhắm tới. Rỗng = không nói sàn nào → người gọi tự quyết định lấy cả ba.

    CÓ LÝ DO PHẢI LỌC THEO SÀN, không phải chỉ cho gọn. Ba sàn không cùng thang đo: 1688 là sàn
    SỈ, một dòng khăn giấy bán 4,6 triệu cái trong khi quán quân Shopee VN ở mức 68 nghìn. Bảng
    "bán chạy" gộp rồi xếp theo lượt bán vì thế luôn do 1688 chiếm đầu — hỏi "top sản phẩm trên
    Shopee VN" mà sáu thẻ đầu là hàng sỉ Trung Quốc (đo 14/09/2026). Xem thêm
    `top_ban_chay_tung_san` cho nhánh câu hỏi KHÔNG nói sàn nào.

    "shopee" trơn không kèm thị trường = cả hai sàn Shopee, KHÔNG kéo theo 1688.

    KHỚP NGUYÊN TỪ, không khớp chuỗi con — đệm khoảng trắng hai đầu rồi mới tìm. Khớp chuỗi con
    thì cụm "san ph" nằm gọn trong "san pham": câu "sản phẩm nào bán chạy nhất" (không nhắc sàn
    nào) bị nhận là hỏi Shopee PH, và mọi câu có chữ "sản phẩm" đều thế. Đo 14/09/2026.
    """
    q = f" {_fold(cau_hoi)} "
    toks = set(q.split())
    ra: set[str] = set()
    for san, cum in _TU_SAN.items():
        if any(f" {c} " in q for c in cum):
            ra.add(san)
    for tu, san in _TU_SAN_NGUYEN.items():
        if tu in toks:
            ra.add(san)
    if not ra and "shopee" in toks:
        ra = {"shopee_vn", "shopee_ph"}
    return [s for s in SAN if s in ra]          # giữ đúng thứ tự chuẩn của `SAN`


def top_ban_chay_tung_san(limit: int = 5, sans: list[str] | None = None) -> list[dict]:
    """
    Top bán chạy TÁCH RIÊNG từng sàn — mỗi sàn một khối, không có bảng xếp hạng chung.

    TỪNG GỘP BA SÀN VÀO MỘT BẢNG rồi xếp theo lượt bán, và đó là một sai lầm: lượt bán tuy đều
    là "số đếm" nhưng KHÔNG CÙNG THANG ĐO. 1688 là sàn SỈ — một dòng khăn giấy bán 4,6 triệu cái
    trong khi quán quân Shopee VN ở mức 68 nghìn. Bảng gộp vì thế luôn do 1688 chiếm sạch phần
    đầu, và câu "bán chạy nhất" của người bán lẻ Việt Nam không bao giờ được trả lời.

    Suất tối thiểu mỗi sàn (bản cũ giữ 3 dòng đầu bảng cho mỗi sàn) KHÔNG cứu được, vì bước cuối
    vẫn xếp lại cả bảng theo lượt bán: suất đó bảo đảm CÓ MẶT chứ không bảo đảm ĐƯỢC NHÌN THẤY.
    Đo 14/09/2026: 6 thẻ đầu vẫn là 1688.

    Chủ dự án chốt 14/09/2026 — tách khối, đúng nguyên tắc đã áp cho bảng Trends và cho
    `top_doanh_so_tung_san`: hai thang đo khác nhau thì không trộn vào một bảng xếp hạng.
    """
    out = []
    for san in (sans or list(SAN)):
        items = [{**it, "san": san, "nhan_san": SAN[san]["nhan"]}
                 for it in toplist(san, "ban_chay", limit)["items"]]
        if items:
            out.append({"san": san, "nhan": SAN[san]["nhan"], "items": items})
    return out


def top_doanh_so_tung_san(limit: int = 5, sans: list[str] | None = None) -> list[dict]:
    """Top doanh số TÁCH RIÊNG từng sàn — tiền không gộp được nên không trộn."""
    out = []
    for san in (sans or list(SAN)):
        items = toplist(san, "doanh_so", limit)["items"]
        if items:
            out.append({"san": san, "nhan": SAN[san]["nhan"], "items": items})
    return out


#: Chỉ mục tìm-theo-tên của lần quét mới nhất, giữ trong tiến trình. Khoá gồm dấu thời gian lượt
#: cào nên một lượt cào xong là tự dựng lại. Cần vì mỗi câu hỏi tra ~13 cụm, mà dựng lại chỉ mục
#: cho mỗi cụm là đọc 22.000 dòng mười ba lần.
_TIM_CACHE: dict[tuple, list[tuple[str, dict]]] = {}


def _chuan(s: str) -> str:
    """
    Như `_fold` nhưng GIỮ DẤU — chỉ thường hoá và biến dấu câu thành khoảng trắng.

    Phải có bản giữ dấu vì bỏ dấu làm CHẬP những từ tiếng Việt khác hẳn nghĩa: "giày" và "giấy"
    cùng ra "giay", "ủng" và "ứng" cùng ra "ung". Tra "giày" trên bản bỏ dấu ra 1.469 listing mà
    đứng đầu là giấy vệ sinh; tra "ủng" ra 197 listing mà đứng đầu là tai nghe (khớp "ứng dụng").
    Đo 14/09/2026.
    """
    return re.sub(r"[^0-9\w]+", " ", (s or "").lower(), flags=re.UNICODE).strip()


def _chi_muc_tim(san: str) -> list[tuple[str, str, dict]]:
    """(tên giữ dấu, tên bỏ dấu, thẻ) của lần quét mới nhất — cả hai đã đệm khoảng trắng."""
    s = _san(san)
    khoa = (san, _dau_cao(s["platform"], s["market"]))
    if khoa in _TIM_CACHE:
        return _TIM_CACHE[khoa]
    with db.connect() as c:
        moi = c.execute("SELECT MAX(day) FROM listings_snapshot WHERE platform=? AND market=?",
                        (s["platform"], s["market"])).fetchone()[0]
        rows = c.execute(
            f"SELECT {_COT} FROM listings_snapshot WHERE platform=? AND market=? AND day=?",
            (s["platform"], s["market"], moi)).fetchall() if moi else []
    ra: list[tuple[str, str, dict]] = []
    thay: set[str] = set()
    for r in rows:
        r = dict(r)
        if r["product_id"] in thay or la_hang_ao(r["title"]):
            continue
        thay.add(r["product_id"])
        ra.append((f" {_chuan(r['title'])} ", f" {_fold(r['title'])} ", r))
    _TIM_CACHE.clear()                 # chỉ giữ chỉ mục của lượt cào hiện tại
    _TIM_CACHE[khoa] = ra
    return ra


def tim_san_pham(tu_khoa: str, san: str, toi_da: int = 3) -> dict | None:
    """
    Sản phẩm trong kho có tên chứa `tu_khoa` — để gắn SỐ THẬT vào một món do AI gợi ý.

    KHỚP NGUYÊN TỪ. Tra `"ủng"` bằng `LIKE '%ủng%'` ra 57 dòng mà gần hết là rác: nó khớp vào
    "thuần ch**ủng**" và "kh**ủng** long". Cùng họ với lỗi "san ph" ⊂ "san pham" ở
    `san_lien_quan` — tiếng Việt bỏ dấu có rất nhiều từ ngắn nằm lọt trong từ khác.

    Trả `None` khi kho không có món đó. Đó là câu trả lời thật chứ không phải lỗi: kho chỉ cào
    TOP mỗi ngành, nên hàng ngách ("máy sấy quần áo mini") vắng mặt là chuyện bình thường —
    giao diện phải nói "kho chưa đo", đừng nói "sàn không có".
    """
    # Từ khoá CÓ DẤU thì tra trên bản giữ dấu (chính xác); gõ không dấu thì đành tra bản bỏ dấu
    # và chấp nhận chập nghĩa — người gõ không dấu vốn đã không phân biệt được "giày" với "giấy".
    co_dau, khong_dau = _chuan(tu_khoa), _fold(tu_khoa)
    if not khong_dau:
        return None
    giu_dau = co_dau != khong_dau
    chu = (co_dau if giu_dau else khong_dau).split()
    kho = _chi_muc_tim(san)

    # NỚI DẦN TỪ PHẢI SANG TRÁI. Món AI gợi ý thường là một mô tả ("áo mưa bít cánh dơi") chứ
    # không phải tên trên sàn, nên khớp nguyên cụm gần như luôn trượt. Bỏ dần chữ cuối cho tới
    # khi còn 2 chữ: "áo mưa bít cánh dơi" → … → "áo mưa" thì có 49 listing. Dừng ở 2 chữ vì một
    # chữ ("áo", "túi") rộng tới mức con số trả về không còn nói gì về món đang hỏi.
    toi_thieu = 1 if len(chu) == 1 else 2
    for het in range(len(chu), toi_thieu - 1, -1):
        cum = " ".join(chu[:het])
        if giu_dau:
            hit = [r for ten, _, r in kho if f" {cum} " in ten]
        else:
            hit = [r for _, ten, r in kho if f" {cum} " in ten]
        if hit:
            break
    else:
        return None
    if not hit:
        return None
    hit.sort(key=lambda r: r["sold_monthly"] or 0, reverse=True)
    gia = [r["price"] for r in hit if r["price"]]
    top = hit[0]
    return {
        "n": len(hit), "san": san, "nhan_san": SAN[san]["nhan"],
        # `cum` là cụm THẬT SỰ đã khớp. Giao diện phải nói ra khi nó ngắn hơn món được hỏi, nếu
        # không thì "49 listing" đọc thành 49 cái áo mưa bít cánh dơi — trong khi đó là số của
        # "áo mưa" nói chung.
        "cum": cum, "nguyen_cum": het == len(chu),
        "ban_30": top["sold_monthly"] or 0,
        "gia_min": min(gia) if gia else None, "gia_max": max(gia) if gia else None,
        "currency": top["currency"],
        "items": [{"product_id": r["product_id"], "title": r["title"], "url": r["url"],
                   "image_url": r["image_url"], "price": r["price"], "currency": r["currency"],
                   "rating": r["rating"], "sold_monthly": r["sold_monthly"],
                   "ban_30": r["sold_monthly"] or 0,
                   "doanh_so_30": (r["sold_monthly"] or 0) * (r["price"] or 0),
                   "nhan_san": SAN[san]["nhan"], "san": san}
                  for r in hit[:toi_da]],
    }


def tong_quan_kho() -> dict:
    """
    Kho đang có gì — để trả lời câu hỏi về CHÍNH CÁI KHO ("dữ liệu cập nhật đến ngày nào?").

    Những câu đó trước đây rơi vào nhánh tra sản phẩm và được trả lời bằng một bảng hàng hoá
    không liên quan. Chúng cần dữ kiện về kho, mà dữ kiện ấy phải ĐẾM THẬT chứ không viết cứng:
    số ngày quét và số sản phẩm đổi mỗi đêm.
    """
    ra = []
    with db.connect() as c:
        for san, info in SAN.items():
            rows = c.execute(
                "SELECT day, COUNT(DISTINCT product_id) n FROM listings_snapshot"
                " WHERE platform=? AND market=? GROUP BY day ORDER BY day",
                (info["platform"], info["market"])).fetchall()
            if not rows:
                continue
            mains, ma = _cay(san)
            ra.append({
                "san": san, "nhan": info["nhan"],
                "ngay_quet": [r["day"] for r in rows],
                "so_lan_quet": len(rows),
                "ngay_moi_nhat": rows[-1]["day"],
                "san_pham_lan_cuoi": rows[-1]["n"],
                "so_nganh_lon": len(mains),
                "so_nganh_con": sum(len(m["subs"]) for m in mains),
            })
    return {"san": ra, "lang_kinh": list(LANG_KINH)}


def nganh_lien_quan(cau_hoi: str, toi_da: int = 3) -> list[dict]:
    """
    Ngành mà câu hỏi nhắc tới — khớp tên ngành (lớn + con) với chữ trong câu hỏi.

    Chỉ nhận diện được ngành gọi bằng tên trùng cây ngành: cây VN (dùng cho Shopee VN và 1688)
    là tiếng Việt, cây PH là tiếng Anh — nên câu hỏi tiếng Việt thường khớp VN/1688, ít khớp PH.
    PH vẫn hiện ở phần top toàn cảnh. Trả về mỗi ngành kèm sàn tìm thấy nó.

    GIỮ DẤU KHI CÂU CÓ DẤU. Khớp trên bản bỏ dấu làm chập những chữ khác hẳn nghĩa: câu "dữ liệu
    cập nhật đến ngày nào" khớp trúng ngành "Đèn" (vì "đến"→"den") và ngành "Ô/Dù" (vì "dữ"→
    "du") — một câu hỏi về kho bị hiểu thành câu hỏi ngành hàng. Đo 14/09/2026. Câu gõ không dấu
    thì vẫn phải tra bản bỏ dấu, đành chấp nhận chập.
    """
    giu_dau = _fold(cau_hoi) != _chuan(cau_hoi)
    don = (lambda s: _chuan(s)) if giu_dau else (lambda s: _fold(s))
    q = set(t for t in don(cau_hoi).split() if len(t) >= 2)
    if not q:
        return []
    ung: dict[tuple, dict] = {}
    for san in SAN:
        mains, _ = _cay(san)
        for m in mains:
            for cap, mid, sid, ten in ((0, m["main_id"], None, m["main_name"]),
                                       *[(1, m["main_id"], s["sub_id"], s["sub_name"]) for s in m["subs"]]):
                # TẬP HỢP, không phải danh sách: "Giày Oxfords & Giày Buộc Dây" có chữ "giày"
                # hai lần, đếm trùng thành 2 và lọt lưới "≥ 2 chữ trùng" chỉ với mỗi chữ "giày".
                toks = {t for t in don(ten).split()
                        if len(t) >= 2 and _fold(t) not in _CHU_CHUNG}
                if not toks:
                    continue
                trung = {t for t in toks if t in q}
                # Khớp NGUYÊN CHỮ, không khớp chuỗi con: tên một chữ ("Áo") phải có đúng chữ đó
                # trong câu, tên nhiều chữ cần ≥ 2 chữ trùng. Khớp chuỗi con làm "nào" nuốt "áo",
                # "muốn" nuốt "mũ" — đo 14/09/2026, "sản phẩm bán chạy nhất" khớp nhầm ngành "Áo".
                if (len(toks) == 1 and len(trung) == 1) or len(trung) >= 2:
                    # Xếp theo TỶ LỆ PHỦ trước, rồi mới tới SỐ CHỮ TRÙNG. Chỉ dùng số chữ thì tên
                    # dài dễ lên đầu; chỉ dùng tỷ lệ phủ thì "Giày Thể Thao" (còn đúng chữ "giày"
                    # sau khi bỏ chữ chung, phủ 1/1) đứng trên "Giày Dép Nữ" (phủ 3/3) — đo 14/09.
                    diem = (len(trung) / len(toks), len(trung), cap)
                    khoa = (mid, sid)
                    if khoa not in ung or diem > ung[khoa]["diem"]:
                        ung[khoa] = {"main_id": mid, "sub_id": sid, "ten": ten, "cap": cap,
                                     "diem": diem, "san": []}
                    if san not in ung[khoa]["san"]:
                        ung[khoa]["san"].append(san)
    xep = sorted(ung.values(), key=lambda x: x["diem"], reverse=True)
    return xep[:toi_da]


def top_theo_nganh(main_id: str, sub_id: str | None, sans: list[str], moi_san: int = 5,
                   ten_nganh: str = "") -> list[dict]:
    """Top bán chạy của một ngành trên các sàn có nó — cho câu hỏi nhắm vào một ngành."""
    rows: list[dict] = []
    for san in sans:
        try:
            r = kham_pha(san, main_id, sub_id, "ban_chay", moi_san)
        except ValueError:
            continue
        for it in r["items"]:
            # Tên ngành lấy từ CHÍNH lựa chọn đang hỏi: `kham_pha` chỉ gắn `main_name`/`sub_name`
            # khi duyệt tất cả ngành, nên không gắn ở đây thì mọi dòng thành "chưa rõ ngành".
            rows.append({**it, "san": san, "nhan_san": SAN[san]["nhan"],
                         "main_name": it.get("main_name") or ten_nganh,
                         "sub_name": it.get("sub_name")})
    rows.sort(key=lambda x: x.get("sold_monthly") or 0, reverse=True)
    return rows
