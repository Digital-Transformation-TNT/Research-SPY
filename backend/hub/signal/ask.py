"""
ONE-SHOT AI — một ô hỏi đáp duy nhất cho cả Hub.

Gộp từ chatbot mục "Cơ hội". Vòng hội thoại giữ nguyên `lib/opportunity/demand_map.py`
(đề xuất → hỏi sàn → chấm lại); ở đây chèn thêm, trước khi hỏi, một lượt tóm tắt dữ liệu
TREND·SCOUT đã LỌC THEO CÂU HỎI.

LỌC TRƯỚC RỒI MỚI HỎI AI — chốt 14/09/2026. Kho có ~70.000 dòng và lớn thêm ~52.000 dòng mỗi
ngày; gửi hết cho Gemini là khoảng 3 triệu token một câu hỏi, vượt cửa sổ model và đốt sạch hạn
mức bản miễn phí. Nhưng "sản phẩm nào bán chạy nhất" là việc SẮP XẾP, mà kho làm việc đó trong
0,3 giây và 0 token. Nên: kho lọc và xếp, Gemini chỉ đọc phần đã lọc (~1.000 token) rồi diễn giải.

BỎ Ô CHỌN SÀN (14/09/2026), THAY BẰNG ĐỌC TÊN SÀN TỪ CÂU HỎI. Bỏ ô chọn mà không đọc câu hỏi là
mất hẳn cách nhắm sàn — bản đầu mắc đúng lỗi đó: hỏi "top sản phẩm trên Shopee VN" vẫn trả về
bảng gộp ba sàn. Nay `scout.san_lien_quan` khớp tên sàn trong câu (tất định, không gọi AI):
  · Câu có tên sàn  → chỉ lấy dữ liệu của sàn đó.
  · Câu không nói   → lấy cả ba.

KHÔNG CÓ BẢNG XẾP HẠNG GỘP SÀN, cả "Bán chạy" lẫn "Doanh số" đều TÁCH RIÊNG TỪNG SÀN. Doanh số
vì VND/PHP/CNY không cộng được; lượt bán vì 1688 là sàn SỈ, số của nó lớn hơn Shopee hàng chục
lần nên gộp vào là nó chiếm sạch đầu bảng. Mỗi dòng luôn kèm nhãn sàn và tiền gốc.
"""

from __future__ import annotations

from lib.keywords.types import SearchContext
from lib.core.model import dump
from lib.opportunity.demand_map import ChatTurn, map_demand

from . import scout, truy_van

#: Bao nhiêu dòng mỗi bảng đi vào lượt tóm tắt. Đủ để định hướng, không đủ để nhấn chìm câu hỏi
#: thật của người dùng — và mỗi dòng tốn khoảng 30 token.
TOP_BAN_CHAY = 5      # top bán chạy MỖI sàn (tách khối, không gộp — xem scout.top_ban_chay_tung_san)
TOP_DOANH_SO = 4      # top doanh số MỖI sàn
TOP_NGANH = 5         # sản phẩm mỗi sàn trong một ngành được hỏi tới
MAX_NGANH = 2         # số ngành đưa vào, tính từ ngành khớp nhất


def _tien(it: dict) -> str:
    return f"{it.get('price') or 0:,.0f} {it.get('currency') or ''}".strip()


def _nganh_cua(it: dict) -> str:
    return " > ".join(x for x in (it.get("main_name"), it.get("sub_name")) if x) or "chưa rõ ngành"


def _dong_ban(it: dict) -> str:
    """Một dòng sản phẩm cho prompt. Ngắn nhất có thể mà vẫn đủ để đối chiếu và trích dẫn."""
    ban = it.get("ban_30")
    if ban is None:
        ban = it.get("sold_monthly") or 0
    return (f"- [{it.get('nhan_san') or ''}] {it.get('title') or it['product_id']}"
            f" | {_nganh_cua(it)} | {_tien(it)} | bán 30 ngày {ban:,}")


def _co_trong_kho(cum: str) -> bool:
    """Kho có hàng nào tên chứa cụm này không — dùng để nhận ra câu hỏi về MỘT MÓN cụ thể."""
    return scout.tim_san_pham(cum, "shopee_vn") is not None


def _loc_gia(rows: list[dict], yc: truy_van.YeuCau) -> list[dict]:
    """Lọc theo khoảng giá câu hỏi nêu. Dòng không có giá bị loại — không đoán hộ."""
    if yc.gia_min is None and yc.gia_max is None:
        return rows
    ra = []
    for r in rows:
        g = r.get("price")
        if g is None:
            continue
        if yc.gia_min is not None and g < yc.gia_min:
            continue
        if yc.gia_max is not None and g > yc.gia_max:
            continue
        ra.append(r)
    return ra


# ───────────────────────── truy hồi theo từng ý định ─────────────────────────
#
# Mỗi hàm trả về (các khối chữ cho prompt, các thẻ sản phẩm cho giao diện). Tách hẳn từng nhánh
# thay vì một hàm `digest` dài: trước 14/09/2026 mọi ý định dùng CHUNG một khối dữ liệu, nên câu
# "mùa mưa nên bán gì" cũng bị đính bảng top bán chạy toàn sàn và người xem tưởng xốt phô mai là
# hàng nên bán mùa mưa. Lấy đúng thứ được hỏi là việc của tầng này.


def _lay_toplist(yc: truy_van.YeuCau, sans: list[str]) -> tuple[list[str], list[dict], str | None]:
    """Bảng xếp hạng. Có nêu ngành thì lấy trong ngành đó, không thì lấy toàn sàn."""
    parts, the, ngay = [], [], None
    n = yc.so_luong or (TOP_BAN_CHAY if yc.bang == "ban_chay" else TOP_DOANH_SO)

    if yc.nganh:
        for ng in yc.nganh:
            san_ng = [s for s in ng["san"] if s in sans]
            if not san_ng:
                continue
            rows = scout.top_theo_nganh(ng["main_id"], ng["sub_id"], san_ng, n, ng["ten"])
            rows = _loc_gia(rows, yc)
            if not rows:
                continue
            parts.append(f'NGÀNH "{ng["ten"]}" — top bán chạy của riêng ngành này:\n'
                         + "\n".join(_dong_ban(it) for it in rows))
            the += [{**it, "khoi": "nganh", "ten_nganh": ng["ten"]} for it in rows]
        if parts:
            return parts, the, ngay

    lay = scout.top_ban_chay_tung_san if yc.bang == "ban_chay" else scout.top_doanh_so_tung_san
    khoi = []
    for nhom in lay(n, sans=sans):
        rows = _loc_gia([{**it, "nhan_san": nhom["nhan"], "san": nhom["san"]}
                         for it in nhom["items"]], yc)
        if not rows:
            continue
        ngay = max((it.get("ngay") for it in rows if it.get("ngay")), default=ngay)
        if yc.bang == "ban_chay":
            khoi.append(f"{nhom['nhan']}:\n" + "\n".join(_dong_ban(it) for it in rows))
        else:
            khoi.append(f"{nhom['nhan']}:\n" + "\n".join(
                f"- {it.get('title') or it['product_id']} | {_nganh_cua(it)} | {_tien(it)}"
                f" | doanh số 30 ngày {round(it.get('doanh_so_30') or 0):,}"
                f" {it.get('currency') or ''}" for it in rows))
        the += [{**it, "khoi": yc.bang} for it in rows]
    if khoi:
        # Câu dặn "đừng gộp" PHẢI nằm trong prompt: bày ba khối ra mà không nói gì thì mô hình
        # tự trộn lại thành một bảng xếp theo lượt bán, và 1688 (sàn sỉ) lại chiếm sạch đầu.
        nhan = "lượt bán 30 ngày" if yc.bang == "ban_chay" else "doanh số 30 ngày"
        parts.append(
            f"TOP {nhan.upper()} — TÁCH RIÊNG TỪNG SÀN (quét ngày {ngay}). 1688 là sàn SỈ nên số"
            " của nó lớn hơn Shopee hàng chục lần, và VND/PHP/CNY không cộng được vào nhau —"
            " ĐỪNG gộp các sàn thành một bảng xếp hạng, đừng nói sàn nào hơn sàn nào:\n"
            + "\n\n".join(khoi))
    return parts, the, ngay


def _lay_lang_kinh(yc: truy_van.YeuCau, sans: list[str]) -> tuple[list[str], list[dict], str | None]:
    """
    Một lăng kính TREND·SCOUT — "đang tăng tốc", "đột biến", "bán khoẻ ổn định"…

    ĐÂY LÀ NHÁNH TRƯỚC 14/09/2026 KHÔNG HỀ CÓ. Sáu lăng kính là phần có giá trị nhất của công
    cụ, nhưng One-shot AI không đụng tới chúng: hỏi "sản phẩm nào đang tăng tốc" cũng chỉ nhận
    về bảng bán chạy thường. Lăng kính rỗng cũng phải NÓI RA là rỗng và vì sao (chưa đủ ngày
    quét), đừng im lặng trả về bảng khác.
    """
    lens = yc.lang_kinh or "ban_chay"
    ten = {"hot": "ĐANG TĂNG TỐC", "spike": "ĐỘT BIẾN", "steady": "BÁN KHOẺ ỔN ĐỊNH",
           "gap": "KHE HỞ", "new": "TÂN BINH BÁN CHẠY", "ban_chay": "BÁN CHẠY"}[lens]
    parts, the = [], []
    rong: list[str] = []
    n = yc.so_luong or TOP_NGANH
    for san in sans:
        for ng in (yc.nganh or [None]):
            if ng is not None and san not in ng["san"]:
                continue
            try:
                r = scout.kham_pha(san, ng["main_id"] if ng else None,
                                   ng["sub_id"] if ng else None, lens, n)
            except ValueError:
                continue
            rows = _loc_gia([{**it, "san": san, "nhan_san": scout.SAN[san]["nhan"]}
                             for it in r["items"]], yc)
            nhan = scout.SAN[san]["nhan"] + (f' › {ng["ten"]}' if ng else "")
            if not rows:
                rong.append(f"{nhan} (kho mới có {r['so_lan_quet']} lần quét)")
                continue
            parts.append(f"{ten} — {nhan}, tính trên {r['so_ngay']} ngày:\n"
                         + "\n".join(f"{_dong_ban(it)} | {it.get('ly_do') or ''}" for it in rows))
            the += [{**it, "khoi": lens} for it in rows]
    if rong:
        parts.append(f"KHÔNG CÓ sản phẩm nào đạt mức {ten} ở: " + "; ".join(rong)
                     + ". Nói thẳng điều này ra — lăng kính cần ít nhất 3 lần quét mới có nghĩa,"
                       " đừng thay bằng bảng bán chạy rồi coi như đã trả lời.")
    return parts, the, None


def _lay_san_pham(yc: truy_van.YeuCau, sans: list[str]) -> tuple[list[str], list[dict], str | None]:
    """Một món cụ thể: kho có bao nhiêu listing, cái nào bán chạy nhất, giá chạy từ đâu tới đâu."""
    parts, the = [], []
    for kw in yc.tu_khoa:
        for san in sans:
            hit = scout.tim_san_pham(kw, san, toi_da=TOP_NGANH)
            if not hit:
                parts.append(f'KHO CHƯA ĐO "{kw}" trên {scout.SAN[san]["nhan"]}. Nói là KHO CHƯA'
                             " CÓ SỐ, KHÔNG được nói là sàn không bán — kho chỉ cào top mỗi"
                             " ngành nên hàng ngách vắng mặt là chuyện thường.")
                continue
            rows = _loc_gia(hit["items"], yc)
            if not rows:
                continue
            rong = "" if hit["nguyen_cum"] else f' (số của cụm rộng hơn: "{hit["cum"]}")'
            parts.append(
                f'"{kw}" trên {hit["nhan_san"]}: {hit["n"]} listing trong kho{rong}. '
                f'Cái bán chạy nhất bán {hit["ban_30"]:,} trong 30 ngày. Giá từ '
                f'{hit["gia_min"]:,.0f} tới {hit["gia_max"]:,.0f} {hit["currency"] or ""}:\n'
                + "\n".join(_dong_ban(it) for it in rows))
            the += [{**it, "khoi": "san_pham", "ten_nganh": kw} for it in rows]
    return parts, the, None


def _lay_meta() -> tuple[list[str], list[dict], str | None]:
    """Dữ kiện về CHÍNH CÁI KHO — ngày quét, số sản phẩm, số ngành, sàn nào có."""
    tq = scout.tong_quan_kho()
    if not tq["san"]:
        return ["KHO CHƯA CÓ DỮ LIỆU NÀO."], [], None
    dong = [f"- {s['nhan']}: quét {s['so_lan_quet']} lần"
            f" ({', '.join(s['ngay_quet'])}), lần mới nhất {s['ngay_moi_nhat']} có"
            f" {s['san_pham_lan_cuoi']:,} sản phẩm, cây ngành {s['so_nganh_lon']} ngành lớn /"
            f" {s['so_nganh_con']} ngành con" for s in tq["san"]]
    return ["KHO TREND SIGNAL HUB ĐANG CÓ (số đếm thật, không phải ước lượng):\n"
            + "\n".join(dong)
            + "\n\nSáu lăng kính phân tích: " + ", ".join(tq["lang_kinh"])
            + ".\nDữ liệu cào trực tiếp từ trang niêm yết của sàn, mỗi đêm một lần."], [], \
           max(s["ngay_moi_nhat"] for s in tq["san"])


#: Câu dặn riêng cho từng ý định — tầng RÀNG BUỘC SINH của hệ RAG. Không có nó thì mô hình
#: nhận cùng một lời dặn cho mọi loại câu, và nó sẽ bịa ra một bảng khi kho nói "chưa có".
HUONG_DAN = {
    "toplist": "Người dùng hỏi số liệu xếp hạng. Trả lời BẰNG ĐÚNG những dòng trên, nêu rõ sàn"
               " của từng sản phẩm. Đừng bịa thêm dòng nào.",
    "lang_kinh": "Người dùng hỏi về một lăng kính phân tích. Trả lời bằng đúng những dòng trên và"
                 " giải thích ngắn gọn vì sao chúng lọt lăng kính đó. Nếu phần dữ liệu nói KHÔNG"
                 " CÓ sản phẩm nào đạt mức, hãy nói thẳng là chưa có và vì sao — TUYỆT ĐỐI không"
                 " thay bằng danh sách bán chạy thông thường rồi coi như đã trả lời.",
    "san_pham": "Người dùng hỏi về một món cụ thể. Dùng đúng các con số trên. Nếu dữ liệu ghi KHO"
                " CHƯA ĐO, hãy nói là kho chưa có số cho món đó, KHÔNG được kết luận sàn không"
                " bán món đó.",
    "meta": "Người dùng hỏi về chính kho dữ liệu. Trả lời gọn bằng đúng các con số trên. Không"
            " liệt kê sản phẩm.",
    "y_tuong": "Người dùng xin ý tưởng hàng để bán, KHÔNG hỏi bảng xếp hạng. Hãy đề xuất các món"
               " hợp bối cảnh. Đừng bịa số liệu — mỗi món sẽ được hệ thống tự gắn số thật của kho"
               " vào sau.",
    "xa_giao": "Người dùng chào hỏi hoặc hỏi công cụ làm được gì. Trả lời ngắn, thân thiện, rồi"
               " nói rõ có thể hỏi gì: top bán chạy / doanh số theo sàn và ngành, sản phẩm đang"
               " tăng tốc, đột biến, bán ổn định, khe hở ngách, tân binh, hoặc xin ý tưởng hàng"
               " theo mùa. KHÔNG liệt kê sản phẩm.",
    "ngoai_pham_vi": "Câu hỏi nằm ngoài phạm vi công cụ (công cụ chỉ nói về hàng hoá và số liệu"
                     " bán hàng trên Shopee VN, Shopee PH, 1688). Nói thẳng là không trả lời"
                     " được câu này, rồi gợi ý vài câu hỏi đúng phạm vi. KHÔNG bịa câu trả lời.",
    "khong_ro": "Chưa hiểu người dùng muốn gì. HỎI LẠI cho rõ và đưa 2–3 ví dụ câu hỏi cụ thể."
                " KHÔNG đoán bừa rồi đổ ra một bảng dữ liệu không ai xin.",
}


def digest(cau_hoi: str) -> dict:
    """
    Tầng TRUY HỒI của hệ RAG: đọc ý định (`truy_van.doc`) rồi lấy ĐÚNG phần kho tương ứng.

    Trả về khối chữ cho prompt, câu dặn cách trả lời, và `products` để giao diện vẽ thẻ bằng SỐ
    THẬT của kho thay vì tin số do mô hình gõ lại.
    """
    yc = truy_van.doc(cau_hoi, scout.nganh_lien_quan, _co_trong_kho)
    sans = yc.sans or list(scout.SAN)
    pham_vi = ", ".join(scout.SAN[s]["nhan"] for s in yc.sans) if yc.sans else "cả ba sàn"

    parts: list[str] = []
    the: list[dict] = []
    ngay = None
    if yc.y_dinh == "toplist":
        parts, the, ngay = _lay_toplist(yc, sans)
    elif yc.y_dinh == "lang_kinh":
        parts, the, ngay = _lay_lang_kinh(yc, sans)
    elif yc.y_dinh == "san_pham":
        parts, the, ngay = _lay_san_pham(yc, sans)
    elif yc.y_dinh == "meta":
        parts, the, ngay = _lay_meta()
    # y_tuong / xa_giao / ngoai_pham_vi / khong_ro: cố ý KHÔNG kéo bảng nào.

    # Hỏi số liệu mà kho không trả được dòng nào thì phải NÓI RA. Im lặng gửi prompt rỗng là để
    # mô hình tự do bịa một bảng nghe rất thật.
    if yc.can_so_lieu and not parts:
        parts = [f"KHO KHÔNG CÓ DỮ LIỆU khớp câu hỏi này (phạm vi: {pham_vi}"
                 + (f", khoảng giá đã lọc" if yc.gia_min or yc.gia_max else "")
                 + "). Nói thẳng là chưa có, đừng bịa sản phẩm."]

    return {
        "text": "\n\n".join(parts),
        "huong_dan": HUONG_DAN.get(yc.y_dinh, HUONG_DAN["khong_ro"]),
        "y_dinh": yc.y_dinh, "ly_do": yc.ly_do,
        "san": yc.sans, "san_loai": yc.san_loai, "pham_vi": pham_vi,
        "lang_kinh": yc.lang_kinh, "bang": yc.bang, "tu_khoa": yc.tu_khoa,
        "gia_min": yc.gia_min, "gia_max": yc.gia_max,
        "thi_truong": yc.thi_truong,
        "nganh": [n["ten"] for n in yc.nganh],
        "n_top": len(the), "ngay": ngay, "products": the,
    }


def _gan_kho(items: list[dict], san: str) -> list[dict]:
    """
    Gắn SỐ THẬT CỦA KHO vào từng món do mô hình đề xuất.

    Đây là phần trả lời mà một chatbot thuần không làm được: nó nghĩ ra "áo mưa bít cánh dơi",
    còn ta nói được trên Shopee VN đang có bao nhiêu listing như thế, cái bán chạy nhất bán bao
    nhiêu một tháng, giá chạy từ đâu tới đâu — và mở thẳng ra xem được.

    Món nào kho không có thì `signal` là None; giao diện phải nói "kho chưa đo" chứ KHÔNG nói
    "sàn không có". Kho chỉ cào TOP mỗi ngành nên hàng ngách vắng mặt là chuyện thường.

    Thử `term` (tiếng Việt có dấu, khớp chính xác hơn) trước rồi mới tới `searchTerm`.
    """
    for it in items:
        hit = None
        for cand in (it.get("term"), it.get("searchTerm")):
            if cand:
                hit = scout.tim_san_pham(cand, san)
                if hit:
                    break
        it["signal"] = hit
    return items


#: Thẻ sản phẩm trả về cho giao diện. CHỈ những trường giao diện vẽ — gửi cả dòng snapshot thì
#: mỗi lượt hỏi chở thêm vài chục KB mà không ai dùng.
_THE = ("product_id", "title", "url", "image_url", "price", "currency", "rating",
        "sold_monthly", "ban_30", "doanh_so_30", "main_name", "sub_name", "nhan_san", "san",
        # `khoi` để giao diện gom thẻ đúng khối đã gửi cho AI (bán chạy / doanh số / ngành),
        # thay vì đổ một danh sách phẳng không biết dòng nào vì sao có mặt.
        "khoi", "ten_nganh")


def _the_san_pham(products: list[dict], toi_da: int = 40) -> list[dict]:
    """Khử trùng theo (sàn, mã sản phẩm) rồi rút gọn — một sản phẩm có thể nằm ở cả ba bảng."""
    ra: list[dict] = []
    thay: set[tuple] = set()
    for it in products:
        khoa = (it.get("san"), it.get("product_id"))
        if khoa in thay:
            continue
        thay.add(khoa)
        ra.append({k: it.get(k) for k in _THE})
        if len(ra) >= toi_da:
            break
    return ra


async def ask(turns: list[dict]) -> dict:
    """
    Một lượt hỏi đáp. `turns` là cả lịch sử, đúng như giao diện đang giữ.

    Không ném lỗi: `map_demand` đã cam kết mọi kết cục đều kèm `message`, và lượt tóm tắt
    chỉ là thêm ngữ cảnh — thiếu nó thì câu trả lời nghèo hơn chứ không hỏng.
    """
    cau_hoi = ""
    for t in reversed(turns):
        if t.get("role") != "assistant" and (t.get("text") or "").strip():
            cau_hoi = t["text"].strip()
            break

    chat: list[ChatTurn] = []
    # LỌC THEO CHÍNH CÂU VỪA HỎI. Dựng khối dữ liệu sau khi biết câu hỏi chứ không phải trước:
    # đó là cả điểm của "lọc trước rồi hỏi AI".
    dg = digest(cau_hoi)
    # Lượt này do HUB nói, không phải người dùng: đặt vai assistant để mô hình đọc nó như dữ kiện
    # đã có trên bàn, chứ không như một yêu cầu phải trả lời.
    #
    # GỬI CẢ KHI KHÔNG CÓ BẢNG NÀO. Trước đây khối này chỉ gửi khi `text` không rỗng, nên câu
    # chào hỏi và câu ngoài phạm vi đi thẳng tới mô hình trần trụi — và nó trả lời như một trợ lý
    # đa năng, hứa những thứ công cụ không làm được. Câu dặn theo ý định (`huong_dan`) mới là
    # phần luôn phải có; bảng số chỉ là phần tuỳ câu.
    khung = [
        "DỮ LIỆU THẬT từ kho Trend Signal Hub (cào trực tiếp từ sàn, đã lọc theo câu hỏi).",
        f"PHẠM VI SÀN: {dg['pham_vi']}. Chỉ nói về sàn trong phạm vi này."
        + (f" Người dùng đã loại trừ: {', '.join(scout.SAN[s]['nhan'] for s in dg['san_loai'])}."
           if dg["san_loai"] else ""),
        "QUY TẮC CHUNG: chỉ dùng số trong khối này, tuyệt đối không bịa thêm sản phẩm; luôn nói"
        " rõ sản phẩm thuộc sàn nào; không cộng hay so tiền giữa hai sàn khác đơn vị"
        " (VND/PHP/CNY); không có trong khối này thì nói là kho chưa có.",
        f"YÊU CẦU CHO LƯỢT NÀY: {dg['huong_dan']}",
    ]
    if dg["text"]:
        khung.append("DỮ LIỆU:\n" + dg["text"])
    chat.append(ChatTurn(role="assistant", text="\n\n".join(khung), items=[]))
    for t in turns:
        chat.append(ChatTurn(
            role="assistant" if t.get("role") == "assistant" else "user",
            text=(t.get("text") or "").strip(),
            items=[i for i in (t.get("items") or []) if i]))

    if not chat or chat[-1].role != "user" or not chat[-1].text:
        return {"error": "Thiếu câu hỏi"}

    result = await map_demand(chat, SearchContext(country=dg["thi_truong"]))
    payload = dump(result)
    # Tra kho trên MỘT sàn thôi. Gộp ba sàn vào một con số "n listing" là trộn lại đúng hai
    # thang đo vừa tách ra ở trên. Câu có nói sàn thì theo sàn đó; không thì theo thị trường
    # người hỏi đang bán (VN mặc định).
    san_tim = dg["san"][0] if dg["san"] else ("shopee_ph" if dg["thi_truong"] == "PH"
                                              else "shopee_vn")
    payload["items"] = _gan_kho(payload.get("items") or [], san_tim)
    payload["hubProducts"] = _the_san_pham(dg["products"])
    payload["grounding"] = {
        "nTop": dg["n_top"], "ngay": dg["ngay"], "nganh": dg["nganh"],
        "san": dg["san"], "phamVi": dg["pham_vi"],
        # Vì sao hệ thống hiểu câu hỏi như vậy — hiện ra được cho người dùng, và là thứ đọc đầu
        # tiên khi họ bảo "nó trả lời sai câu tôi hỏi".
        "yDinh": dg["y_dinh"], "lyDo": dg["ly_do"], "langKinh": dg["lang_kinh"],
        "bang": dg["bang"], "tuKhoa": dg["tu_khoa"],
        "giaMin": dg["gia_min"], "giaMax": dg["gia_max"],
        "sanLoai": dg["san_loai"],
    }
    return payload
