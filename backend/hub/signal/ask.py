"""
③ ONE-SHOT AI — một ô hỏi đáp duy nhất cho cả Hub.

Gộp từ chatbot mục "Cơ hội". Vòng hội thoại giữ nguyên `lib/opportunity/demand_map.py`
(đề xuất → hỏi sàn → chấm lại); ở đây thêm hai việc nó không biết:

    trước  — chèn một lượt tóm tắt tín hiệu của Hub vào đầu hội thoại, để đề xuất bám vào
             thứ đang thật sự tăng chứ không phải thứ mô hình nhớ là hay tăng
    sau    — đối chiếu ngược từng món với `trends_daily`, gắn số thật vào món Hub đã đo

Món không khớp gì thì `signal` để None và giao diện hiện "chưa đo" — không suy ra con số.
"""

from __future__ import annotations

import unicodedata

from lib.keywords.types import SearchContext
from lib.core.model import dump
from lib.opportunity.demand_map import ChatTurn, map_demand

from . import store, top10, trendsig

#: Bao nhiêu từ khoá tín hiệu được đưa vào lượt tóm tắt. Đủ để định hướng, không đủ để
#: nhấn chìm câu hỏi thật của người dùng.
MAX_SIGNAL_HINTS = 12
#: Bao nhiêu dòng Top 10 đi kèm.
MAX_TOP_HINTS = 6


def _fold(s: str) -> str:
    """Bỏ dấu, thường hoá — để 'Tai Nghe' khớp được với 'tai nghe'."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d").strip()


def digest(trends_region: str, platform: str | None, market: str | None) -> dict:
    """
    Những gì Hub đang biết, gói lại thành một khối đọc được.

    `trends_region` là KHOÁ LƯU của `trends_daily` ('ALL', 'VN-HN'…), KHÔNG phải mã quốc gia
    của thị trường — truyền nhầm 'VN' vào đây thì `build` trả 0 dòng và One-shot AI mất sạch
    phần ground mà vẫn trả lời trôi chảy.

    Trả cả `text` (cho prompt) lẫn `index` (cho bước đối chiếu ngược) từ cùng một bộ số:
    dựng riêng hai lần là mở đường cho lời đáp nói một đằng, bảng hiện một nẻo.
    """
    watch = (store.get_config("watchlist") or {}).get("keywords") or []
    sig = trendsig.build(trends_region, store.get_config("trends"),
                         up_only=True, only=watch)
    lines: list[str] = []
    index: dict[str, dict] = {}

    for row in sig["rows"][:MAX_SIGNAL_HINTS]:
        pct = lambda x: "—" if x is None else f"{x * 100:+.0f}%"  # noqa: E731
        lines.append(
            f"- {row['keyword']} · {row['kind']} · chỉ số 7 ngày {row['L']} "
            f"· tăng bền {pct(row['m_sustain'])} · vọt ngắn {pct(row['m_short'])} "
            f"· cùng kỳ năm ngoái {pct(row['yoy'])}")
        index[_fold(row["keyword"])] = {
            "source": "trends", "keyword": row["keyword"],
            "kind": row["kind"], "heat": row["heat"],
            "L": row["L"], "mSustain": row["m_sustain"], "mShort": row["m_short"],
            "yoy": row["yoy"],
        }

    top_lines: list[str] = []
    if platform and market:
        tk = top10.build(platform, market, store.get_config(f"{platform}:{market}"))
        for row in tk["hot"][:MAX_TOP_HINTS]:
            top_lines.append(f"- [nổi bật] {row.get('title') or row['product_id']} "
                             f"· đột biến {row['spike_pct']:+.0f}% · đã bán {row['sold_cumulative']:,}")
            if row.get("keyword"):
                index.setdefault(_fold(row["keyword"]), {})[
                    "source"] = "top10"
        for row in tk["main"][:MAX_TOP_HINTS]:
            top_lines.append(f"- [chính] {row.get('title') or row['product_id']} "
                             f"· tăng lũy kế {row['growth_long_pct']:+.1f}% "
                             f"· đã bán {row['sold_cumulative']:,}")

    parts = []
    if lines:
        parts.append("TỪ KHOÁ ĐANG LÊN (Google Trends, đã lọc bỏ đi ngang & đi xuống):\n"
                     + "\n".join(lines))
    if top_lines:
        parts.append(f"TOP SẢN PHẨM {platform}·{market} (từ snapshot bán lũy kế):\n"
                     + "\n".join(top_lines))
    return {
        "text": "\n\n".join(parts),
        "index": index,
        "n_signals": len(sig["rows"]),
        "value_kind": sig["value_kind"],
        "comparable": sig["comparable"],
    }


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


async def ask(turns: list[dict], region: str = "VN",
              platform: str | None = None, market: str | None = None) -> dict:
    """
    Một lượt hỏi đáp. `turns` là cả lịch sử, đúng như giao diện đang giữ.

    Không ném lỗi: `map_demand` đã cam kết mọi kết cục đều kèm `message`, và lượt tóm tắt
    tín hiệu chỉ là thêm ngữ cảnh — thiếu nó thì câu trả lời nghèo hơn chứ không hỏng.
    """
    chat: list[ChatTurn] = []
    # Vùng LƯU của chuỗi Trends lấy từ danh sách theo dõi, không lấy từ `region` của lượt
    # hỏi: `region` ở đây là thị trường để đối chiếu sàn ('VN', 'PH'), còn chuỗi Trends
    # được lưu dưới khoá do người dùng khai (mặc định 'ALL'). Xem `digest`.
    trends_region = (store.get_config("watchlist") or {}).get("region") or "ALL"
    dg = digest(trends_region, platform, market)
    if dg["text"]:
        # Lượt này do HUB nói, không phải người dùng: đặt vai assistant để mô hình đọc nó
        # như dữ kiện đã có trên bàn, chứ không như một yêu cầu phải trả lời.
        chat.append(ChatTurn(role="assistant", text=dg["text"],
                             items=list(dg["index"].keys())[:MAX_SIGNAL_HINTS]))
    for t in turns:
        chat.append(ChatTurn(
            role="assistant" if t.get("role") == "assistant" else "user",
            text=(t.get("text") or "").strip(),
            items=[i for i in (t.get("items") or []) if i]))

    if not chat or chat[-1].role != "user" or not chat[-1].text:
        return {"error": "Thiếu câu hỏi"}

    result = await map_demand(chat, SearchContext(country=(region or "VN").upper()))
    payload = dump(result)
    payload["items"] = _attach(payload.get("items") or [], dg["index"])
    payload["grounding"] = {
        "nSignals": dg["n_signals"],
        "valueKind": dg["value_kind"],
        "comparable": dg["comparable"],
        "region": trends_region,
        "partition": (f"{platform}·{market}" if platform and market else None),
    }
    return payload
