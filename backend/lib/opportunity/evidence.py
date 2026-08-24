"""Hỏi các sàn xem một danh sách món hàng có tồn tại ở thị trường này không."""

from __future__ import annotations

import asyncio

from lib.keywords.types import SearchContext

#: Trends cần mở trình duyệt thật, quá chậm cho ~15 món.
EVIDENCE_EXCLUDED = {"trends"}

MAX_SOURCES = 2
PER_SOURCE = 4

#: Bao nhiêu món hỏi cùng lúc trên một sàn. Taobao đo thấy `ConnectTimeout` khi bị hỏi dồn.
_CONCURRENCY = 5


def evidence_sources(country: str) -> list[str]:
    """Các sàn phục vụ thị trường này, suy từ sổ đăng ký của mục Từ khoá."""
    from lib.keywords.providers import KEYWORD_PROVIDERS

    code = country.upper()
    usable = [
        source_id
        for source_id, provider in KEYWORD_PROVIDERS.items()
        if source_id not in EVIDENCE_EXCLUDED
        and (provider.markets is None or code in provider.markets)
    ]
    return usable[:MAX_SOURCES]


async def probe_terms(terms: list[str], ctx: SearchContext) -> dict[str, dict[str, list[str]]]:
    """
    Trả về `{món: {sàn: [gợi ý]}}`. Ánh xạ rỗng là một KẾT QUẢ, không phải lỗi.

    Song song theo món, tuần tự theo sàn. Một lượt gọi hỏng chỉ làm món đó thiếu bằng chứng.
    """
    from lib.keywords.providers import KEYWORD_PROVIDERS

    out: dict[str, dict[str, list[str]]] = {term: {} for term in terms}
    gate = asyncio.Semaphore(_CONCURRENCY)

    for source_id in evidence_sources(ctx.country):
        provider = KEYWORD_PROVIDERS[source_id]

        async def ask(term: str) -> tuple[str, list[str]]:
            async with gate:
                try:
                    results = await provider.fetch_suggestions(term, ctx)
                except Exception:
                    return term, []
            words = [(entry.keyword or "").strip() for entry in results if entry.keyword]
            return term, words[:PER_SOURCE]

        for term, words in await asyncio.gather(*(ask(t) for t in terms)):
            if words:
                out[term][source_id] = words

    return out


def flatten(by_source: dict[str, list[str]]) -> list[str]:
    """Gộp bằng chứng của mọi sàn, giữ thứ tự và bỏ trùng."""
    seen: set[str] = set()
    out: list[str] = []
    for words in by_source.values():
        for word in words:
            key = word.lower()
            if key not in seen:
                seen.add(key)
                out.append(word)
    return out
