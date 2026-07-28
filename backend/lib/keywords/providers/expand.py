"""
Bộ máy mở rộng long-tail, dùng chung cho mọi nguồn từ khoá.

Ý tưởng: API gợi ý chỉ hoàn thiện một tiền tố, nên muốn thấy biến thể nào thì phải có
thứ trỏ tới nó. Vì vậy ta không hỏi mỗi "quần jeans" mà hỏi "quần jeans", "quần jeans
nam", "quần jeans mùa", "quần jeans a"…

Đo thực tế trên một từ gốc: 12 lượt gọi thu về 138 từ khoá duy nhất từ Shopee và 91 từ
TikTok, không lỗi lần nào, với khoảng cách 700ms giữa các lượt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lib.core.http import sleep

from ..provider import KeywordProvider
from ..types import SourceHit

#: Từ mở rộng.
#:
#: Chỉ dùng chữ cái đơn là không đủ. Đo trên "quần jeans": mở rộng bằng chữ cái không ra
#: được từ khoá theo mùa nào — trong khi đưa thẳng "mùa" vào thì cả Shopee lẫn TikTok đều
#: trả về "quần jeans mùa hè", "quần jeans mùa đông" và 36 biến thể khác.
#:
#: Nên phần mở rộng trộn hai loại: từ bổ nghĩa bán lẻ (chạm thẳng vào phần long-tail có giá
#: trị thương mại) và chữ cái (cho độ phủ không thiên lệch).
RETAIL_MODIFIERS: dict[str, list[str]] = {
    "vi": [
        "nam",
        "nữ",
        "mùa",
        "mùa hè",
        "mùa đông",
        "giá",
        "đẹp",
        "size",
        "cao cấp",
        "rẻ",
        "big size",
        "form",
        "loại",
        "hot trend",
    ],
    "en": ["men", "women", "summer", "winter", "price", "cheap", "size", "plus size", "best", "style"],
}

LETTERS = [
    "n", "c", "d", "l", "s", "b", "t", "m", "o", "g",
    "h", "k", "x", "r", "v", "a", "đ", "p", "q", "u",
]

#: Ngôn ngữ dùng để gieo từ bổ nghĩa, theo từng thị trường.
MARKET_LANGUAGE: dict[str, str] = {
    "VN": "vi",
    "PH": "en",
    "MY": "en",
    "SG": "en",
    "TH": "en",
    "ID": "en",
    "US": "en",
}


def build_terms(country: str) -> list[str]:
    """
    Trộn xen kẽ từ bổ nghĩa và chữ cái, để ngay cả lần chạy "Nhanh" cũng có cả hai loại độ
    phủ, với các từ bổ nghĩa giá trị nhất đứng trước.
    """
    modifiers = RETAIL_MODIFIERS[MARKET_LANGUAGE.get(country.upper(), "vi")]
    terms: list[str] = [""]
    for i in range(max(len(modifiers), len(LETTERS))):
        if i < len(modifiers):
            terms.append(f" {modifiers[i]}")
        if i < len(LETTERS):
            terms.append(f" {LETTERS[i]}")
    return terms


#: Số lượt gọi mỗi nguồn theo độ sâu người dùng chọn.
DEPTH_CALLS = {"quick": 9, "normal": 19, "deep": 35}

#: Khoảng cách giữa hai lượt gọi cùng một nguồn. Đo thấy an toàn ở 700ms với cả ba nguồn.
CALL_DELAY_MS = 700


@dataclass
class ExpansionOutcome:
    hits: list[SourceHit] = field(default_factory=list)
    calls: int = 0
    error: str | None = None


async def expand_with_provider(
    provider: KeywordProvider, seed: str, country: str, depth: str
) -> ExpansionOutcome:
    """
    Chạy một nguồn qua toàn bộ danh sách từ mở rộng, tuần tự.

    Lỗi giữa chừng vẫn giữ lại những gì đã thu được: độ phủ từ khoá thiếu một phần vẫn dùng
    được, trong khi vứt hết sẽ biến một nguồn chậm thành một nguồn mất tích.
    """
    if provider.markets is not None and country.upper() not in provider.markets:
        return ExpansionOutcome(hits=[], calls=0, error=f"{provider.label} không hoạt động ở {country}")

    terms = [seed + suffix for suffix in build_terms(country)[: DEPTH_CALLS[depth]]]

    hits: list[SourceHit] = []
    calls = 0
    error: str | None = None

    for term in terms:
        try:
            results = await provider.fetch_suggestions(term, country)
            calls += 1
            for index, entry in enumerate(results):
                raw = (entry.keyword or "").strip()
                if raw:
                    hits.append(
                        SourceHit(
                            source=provider.id,
                            position=index,
                            via_term=term,
                            native_score=entry.score,
                            raw=raw,
                        )
                    )
        except Exception as e:
            error = str(e)
            break  # một lần hỏng thường kéo theo phần còn lại cũng hỏng; giữ lại những gì đã có
        await sleep(CALL_DELAY_MS)

    return ExpansionOutcome(hits=hits, calls=calls, error=error)
