"""
ONE-SHOT AI — một ô hỏi đáp duy nhất cho cả Hub.

Gộp từ chatbot mục "Cơ hội". Vòng hội thoại giữ nguyên `lib/opportunity/demand_map.py`
(đề xuất → hỏi sàn → chấm lại); ở đây chèn thêm, trước khi hỏi, một lượt tóm tắt TOP SẢN PHẨM
của sàn đang chọn (TREND·SCOUT, `scout.py`) để đề xuất bám vào thứ đang bán thật.

ĐỔI 13/09/2026: Google Trends bỏ khỏi Hub, nên lượt tóm tắt không còn đọc `trendsig` (dữ liệu
Trends vẫn đóng băng trong kho). Bước "gắn số Trends vào từng món" cũng thôi — `signal` của mọi
món là None, và giao diện không vẽ dòng đó nữa.
"""

from __future__ import annotations

import unicodedata

from lib.keywords.types import SearchContext
from lib.core.model import dump
from lib.opportunity.demand_map import ChatTurn, map_demand

from . import scout

#: Bao nhiêu dòng mỗi bảng Top đi vào lượt tóm tắt. Đủ để định hướng, không đủ để nhấn chìm
#: câu hỏi thật của người dùng.
MAX_TOP_HINTS = 8

#: Thị trường đối chiếu ô tìm kiếm của sàn, theo từng sàn của TREND·SCOUT.
REGION = {"shopee_vn": "VN", "shopee_ph": "PH", "1688": "CN"}


def _fold(s: str) -> str:
    """Bỏ dấu, thường hoá — để 'Tai Nghe' khớp được với 'tai nghe'."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d").strip()


def digest(san: str | None) -> dict:
    """Top bán chạy + Top doanh số của một sàn, gói thành một khối đọc được."""
    if not san or san not in scout.SAN:
        return {"text": "", "index": {}, "n_top": 0, "ngay": None}
    parts: list[str] = []
    n, ngay = 0, None
    for loai, nhan in (("ban_chay", "bán 30 ngày"), ("doanh_so", "doanh số 30 ngày")):
        tl = scout.toplist(san, loai, MAX_TOP_HINTS)
        ngay = tl.get("ngay_moi_nhat") or ngay
        dong = []
        for it in tl["items"]:
            nganh = " › ".join(x for x in (it.get("main_name"), it.get("sub_name")) if x)
            dong.append(f"- {it.get('title') or it['product_id']} · {nganh or 'không rõ ngành'}"
                        f" · giá {it.get('price') or 0:,.0f} {it.get('currency') or ''}"
                        f" · {nhan} {it['ban_30'] if loai == 'ban_chay' else round(it['doanh_so_30']):,}")
        if dong:
            n += len(dong)
            parts.append(f"TOP {'BÁN CHẠY' if loai == 'ban_chay' else 'DOANH SỐ'} "
                         f"{scout.SAN[san]['nhan']} (quét ngày {ngay}):\n" + "\n".join(dong))
    return {"text": "\n\n".join(parts), "index": {}, "n_top": n, "ngay": ngay}


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


async def ask(turns: list[dict], san: str | None = None) -> dict:
    """
    Một lượt hỏi đáp. `turns` là cả lịch sử, đúng như giao diện đang giữ.

    Không ném lỗi: `map_demand` đã cam kết mọi kết cục đều kèm `message`, và lượt tóm tắt
    chỉ là thêm ngữ cảnh — thiếu nó thì câu trả lời nghèo hơn chứ không hỏng.
    """
    chat: list[ChatTurn] = []
    dg = digest(san)
    if dg["text"]:
        # Lượt này do HUB nói, không phải người dùng: đặt vai assistant để mô hình đọc nó
        # như dữ kiện đã có trên bàn, chứ không như một yêu cầu phải trả lời.
        chat.append(ChatTurn(role="assistant", text=dg["text"], items=[]))
    for t in turns:
        chat.append(ChatTurn(
            role="assistant" if t.get("role") == "assistant" else "user",
            text=(t.get("text") or "").strip(),
            items=[i for i in (t.get("items") or []) if i]))

    if not chat or chat[-1].role != "user" or not chat[-1].text:
        return {"error": "Thiếu câu hỏi"}

    result = await map_demand(chat, SearchContext(country=REGION.get(san or "", "VN")))
    payload = dump(result)
    payload["items"] = _attach(payload.get("items") or [], dg["index"])
    payload["grounding"] = {"san": san, "nTop": dg["n_top"], "ngay": dg["ngay"]}
    return payload
