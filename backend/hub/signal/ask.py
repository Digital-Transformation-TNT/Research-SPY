"""
ONE-SHOT AI — một ô hỏi đáp duy nhất cho cả Hub.

Gộp từ chatbot mục "Cơ hội". Vòng hội thoại giữ nguyên `lib/opportunity/demand_map.py`
(đề xuất → hỏi sàn → chấm lại); ở đây chèn thêm, trước khi hỏi, một lượt tóm tắt dữ liệu
TREND·SCOUT đã LỌC THEO CÂU HỎI.

LỌC TRƯỚC RỒI MỚI HỎI AI — chốt 14/09/2026. Kho có ~70.000 dòng và lớn thêm ~52.000 dòng mỗi
ngày; gửi hết cho Gemini là khoảng 3 triệu token một câu hỏi, vượt cửa sổ model và đốt sạch hạn
mức bản miễn phí. Nhưng "sản phẩm nào bán chạy nhất" là việc SẮP XẾP, mà kho làm việc đó trong
0,3 giây và 0 token. Nên: kho lọc và xếp, Gemini chỉ đọc phần đã lọc (~1.000 token) rồi diễn giải.

BỎ Ô CHỌN SÀN (14/09/2026). Trước đây người dùng phải tự chọn Shopee VN / PH / 1688 rồi AI mới
đọc đúng sàn đó. Nay AI đọc CẢ BA:
  · "Bán chạy" GỘP ba sàn, xếp theo LƯỢT BÁN 30 ngày — số đếm nên so được giữa ba sàn.
  · "Doanh số" TÁCH RIÊNG từng sàn — VND, PHP và CNY không cộng vào nhau được.
  · Mỗi dòng luôn kèm nhãn sàn, để không ai đọc nhầm một con số CNY thành tiền Việt.
"""

from __future__ import annotations

import unicodedata

from lib.keywords.types import SearchContext
from lib.core.model import dump
from lib.opportunity.demand_map import ChatTurn, map_demand

from . import scout

#: Bao nhiêu dòng mỗi bảng đi vào lượt tóm tắt. Đủ để định hướng, không đủ để nhấn chìm câu hỏi
#: thật của người dùng — và mỗi dòng tốn khoảng 30 token.
TOP_GOP = 12          # top bán chạy gộp ba sàn
TOP_DOANH_SO = 4      # top doanh số MỖI sàn
TOP_NGANH = 5         # sản phẩm mỗi sàn trong một ngành được hỏi tới
MAX_NGANH = 2         # số ngành đưa vào, tính từ ngành khớp nhất


def _fold(s: str) -> str:
    """Bỏ dấu, thường hoá — để 'Tai Nghe' khớp được với 'tai nghe'."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d").strip()


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


def digest(cau_hoi: str) -> dict:
    """
    Dữ liệu Hub ĐÃ LỌC THEO CÂU HỎI, gói thành một khối chữ cho prompt.

    Ba phần, phần ba chỉ xuất hiện khi câu hỏi gọi tên một ngành cụ thể:
      1. Top bán chạy gộp ba sàn (xếp theo lượt bán — so sánh được).
      2. Top doanh số từng sàn (tiền không gộp).
      3. Ngành mà câu hỏi nhắc tới, top bán chạy của ngành đó trên từng sàn.

    Trả kèm `products` để giao diện vẽ thẻ sản phẩm bằng SỐ THẬT của kho, thay vì tin số do AI
    gõ lại trong câu trả lời.
    """
    parts: list[str] = []
    products: list[dict] = []
    # Thẻ của NGÀNH ĐƯỢC HỎI xếp trước thẻ top chung: danh sách thẻ bị cắt ở 24, mà top chung
    # luôn dài hơn thế — không tách ra thì đúng phần người ta hỏi bị cắt mất. Đo 14/09/2026:
    # hỏi "đồ mẹ và bé" mà 24 thẻ đầu toàn khăn giấy 1688 của bảng top chung.
    products_nganh: list[dict] = []
    ngay = None

    gop = scout.top_ban_chay_gop(TOP_GOP)
    if gop:
        ngay = max((it.get("ngay") for it in gop if it.get("ngay")), default=None)
        parts.append("TOP BÁN CHẠY — GỘP CẢ BA SÀN, xếp theo lượt bán 30 ngày "
                     f"(quét ngày {ngay}; lượt bán là số đếm nên so được giữa ba sàn):\n"
                     + "\n".join(_dong_ban(it) for it in gop))
        products += gop

    khoi: list[str] = []
    for nhom in scout.top_doanh_so_tung_san(TOP_DOANH_SO):
        dong = []
        for it in nhom["items"]:
            it = {**it, "nhan_san": nhom["nhan"], "san": nhom["san"]}
            dong.append(f"- {it.get('title') or it['product_id']} | {_nganh_cua(it)}"
                        f" | {_tien(it)} | doanh số 30 ngày"
                        f" {round(it.get('doanh_so_30') or 0):,} {it.get('currency') or ''}")
            products.append(it)
        if dong:
            khoi.append(f"{nhom['nhan']}:\n" + "\n".join(dong))
    if khoi:
        parts.append("TOP DOANH SỐ — TÁCH RIÊNG TỪNG SÀN (VND, PHP và CNY không cộng được vào "
                     "nhau, đừng so tiền giữa hai sàn):\n" + "\n\n".join(khoi))

    nganh = scout.nganh_lien_quan(cau_hoi, MAX_NGANH)
    for ng in nganh:
        rows = scout.top_theo_nganh(ng["main_id"], ng["sub_id"], ng["san"], TOP_NGANH, ng["ten"])
        if not rows:
            continue
        parts.append(f'NGÀNH "{ng["ten"]}" — câu hỏi nhắc tới ngành này, top bán chạy của nó:\n'
                     + "\n".join(_dong_ban(it) for it in rows))
        products_nganh += rows

    return {"text": "\n\n".join(parts), "index": {},
            "n_top": len(products_nganh) + len(products), "ngay": ngay,
            "nganh": [ng["ten"] for ng in nganh], "products": products_nganh + products}


def _lookup(cand: str, index: dict[str, dict]) -> dict | None:
    """
    Tìm tín hiệu cho một cụm. Khớp đúng trước, rồi mới tới khớp theo CỤM CHA.

    Khớp cha: từ khoá theo dõi nằm trọn trong cụm đề xuất theo đúng thứ tự từ — "kem chống
    nắng" ⊂ "kem chống nắng nâng tông", nhưng KHÔNG khớp "áo chống nắng". Cờ `match` để giao
    diện nói rõ đây là số của cụm rộng hơn.
    """
    folded = _fold(cand)
    if not folded:
        return None
    hit = index.get(folded)
    if hit:
        return {**hit, "match": "exact"}
    words = folded.split()
    for key, val in index.items():
        kw = key.split()
        if len(kw) < 2 or len(kw) >= len(words):
            continue                      # cụm cha một chữ quá dễ trùng bừa — bỏ
        for i in range(len(words) - len(kw) + 1):
            if words[i:i + len(kw)] == kw:
                return {**val, "match": "broader"}
    return None


def _attach(items: list[dict], index: dict[str, dict]) -> list[dict]:
    """
    Gắn tín hiệu THẬT của Hub vào từng món do mô hình đề xuất.

    Khớp theo cả `term` lẫn `searchTerm` (cụm mà sàn thật sự gợi ý) — món nào không khớp
    thì `signal` là None và giao diện hiện "chưa đo", chứ không mượn số của món bên cạnh.
    """
    for it in items:
        hit = None
        for cand in (it.get("searchTerm"), it.get("term")):
            if cand:
                hit = _lookup(cand, index)
                if hit:
                    break
        it["signal"] = hit
    return items


#: Thẻ sản phẩm trả về cho giao diện. CHỈ những trường giao diện vẽ — gửi cả dòng snapshot thì
#: mỗi lượt hỏi chở thêm vài chục KB mà không ai dùng.
_THE = ("product_id", "title", "url", "image_url", "price", "currency", "rating",
        "sold_monthly", "ban_30", "doanh_so_30", "main_name", "sub_name", "nhan_san", "san")


def _the_san_pham(products: list[dict], toi_da: int = 24) -> list[dict]:
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


def _thi_truong(cau_hoi: str) -> str:
    """
    Thị trường để đối chiếu ô tìm kiếm của sàn khi AI đề xuất món hàng.

    Mặc định VN — người dùng là người Việt bán hàng. Chỉ đổi khi câu hỏi nói rõ thị trường khác,
    vì `country` quyết định NGÔN NGỮ của các cụm đem đi hỏi sàn: đoán nhầm sang PH thì cả bảng
    đề xuất trả về tiếng Anh cho một người đang bán ở Việt Nam.
    """
    q = _fold(cau_hoi)
    if any(k in q for k in ("philippines", "phi-lip-pin", "shopee ph", "thi truong ph",
                            "ban o ph", "sang ph")):
        return "PH"
    return "VN"


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
    if dg["text"]:
        # Lượt này do HUB nói, không phải người dùng: đặt vai assistant để mô hình đọc nó
        # như dữ kiện đã có trên bàn, chứ không như một yêu cầu phải trả lời.
        chat.append(ChatTurn(
            role="assistant",
            text="DỮ LIỆU THẬT từ kho Trend Signal Hub (cào từ sàn, đã lọc theo câu hỏi). Khi "
                 "người dùng hỏi về số liệu, TRẢ LỜI BẰNG ĐÚNG NHỮNG DÒNG NÀY và nói rõ sản "
                 "phẩm thuộc sàn nào; đừng bịa thêm sản phẩm, đừng so tiền giữa hai sàn khác "
                 "đơn vị. Không có trong đây thì nói là kho chưa có.\n\n" + dg["text"],
            items=[]))
    for t in turns:
        chat.append(ChatTurn(
            role="assistant" if t.get("role") == "assistant" else "user",
            text=(t.get("text") or "").strip(),
            items=[i for i in (t.get("items") or []) if i]))

    if not chat or chat[-1].role != "user" or not chat[-1].text:
        return {"error": "Thiếu câu hỏi"}

    result = await map_demand(chat, SearchContext(country=_thi_truong(cau_hoi)))
    payload = dump(result)
    payload["items"] = _attach(payload.get("items") or [], dg["index"])
    payload["hubProducts"] = _the_san_pham(dg["products"])
    payload["grounding"] = {"nTop": dg["n_top"], "ngay": dg["ngay"], "nganh": dg["nganh"]}
    return payload
