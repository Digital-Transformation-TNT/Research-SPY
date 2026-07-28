"""
Điều phối mở rộng từ khoá trên nhiều nguồn.

Các nguồn chạy song song — chúng là những host độc lập và mỗi nguồn tự giữ nhịp gọi của
mình. Google Trends CỐ Ý không nằm trên đường này: nó rất dễ bị 429 và cần trình duyệt,
nên được lấy riêng qua `/api/keywords/trend`. Nhờ vậy Trends chết cũng không kéo theo
phần khám phá từ khoá.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Mapping

from lib.core.cache import cache_get, cache_set
from lib.core.jscompat import or_default, to_number

from .providers import KEYWORD_PROVIDERS, KEYWORD_SOURCE_IDS, expand_with_provider, is_keyword_source
from .rank import rank_keywords
from .types import (
    KeywordCandidate,
    KeywordResult,
    KeywordSearchParams,
    KeywordSourceStatus,
    SourceHit,
)

DEFAULT_LIMIT = 60
MAX_LIMIT = 300


def parse_keyword_search_params(query: Mapping[str, list[str]]) -> KeywordSearchParams:
    def first(name: str) -> str | None:
        values = query.get(name)
        return values[0] if values else None

    requested = [s.strip() for s in (first("sources") or "").split(",") if is_keyword_source(s.strip())]

    depth_param = first("depth")
    depth = depth_param if depth_param in ("quick", "deep") else "normal"

    return KeywordSearchParams(
        seed=(first("seed") or "").strip(),
        sources=requested or list(KEYWORD_SOURCE_IDS),
        country=(first("country") or "VN").upper(),
        depth=depth,  # type: ignore[arg-type]
        include_informational=first("includeInformational") == "true",
        limit=int(min(MAX_LIMIT, or_default(to_number(first("limit")), DEFAULT_LIMIT))),
    )


@dataclass
class _CachedExpansion:
    """Thứ được cache: các lượt xuất hiện thô, chưa xếp hạng, kèm kết quả từng nguồn."""

    hits: list[SourceHit]
    statuses: list[KeywordSourceStatus]


def _cache_key(params: KeywordSearchParams) -> str:
    """
    Chỉ những gì làm thay đổi thứ ta *đi lấy về* mới thuộc về cache key. Lọc và xếp hạng rẻ
    và được chạy lại mỗi request, nên bật/tắt một bộ lọc không bao giờ nhận về tập cache lệch.
    """
    return json.dumps(
        ["kw", params.seed.lower(), sorted(params.sources), params.depth, params.country],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _apply_limit(
    ranked: list[KeywordCandidate], limit: int, include_informational: bool
) -> list[KeywordCandidate]:
    """
    Áp giới hạn kết quả mà không để một nhóm lặng lẽ xoá sổ nhóm kia.

    Các truy vấn dạng tư vấn bị chấm điểm thấp có chủ đích — chúng là truy vấn thật nhưng
    không phải ứng viên để test sản phẩm — nên toàn bộ đều rơi khỏi ngưỡng cắt. Khi ấy tick
    "hiện từ khoá dạng câu hỏi" trông như không làm gì cả. Vì vậy khi người dùng chủ động
    bật, ta dành riêng một phần hạn ngạch cho chúng để nút bấm làm đúng điều nó nói, trong
    khi thứ tự xếp hạng vẫn đặt từ khoá mua hàng lên trước.
    """
    if not include_informational:
        return ranked[:limit]

    informational = [k for k in ranked if k.intent == "informational"]
    if not informational:
        return ranked[:limit]

    commercial = [k for k in ranked if k.intent == "commercial"]
    reserved = min(len(informational), max(5, math.floor(limit * 0.2)))
    return commercial[: max(0, limit - reserved)] + informational[:reserved]


async def _run_source(
    source: str, params: KeywordSearchParams
) -> tuple[KeywordSourceStatus, list[SourceHit]]:
    """Chạy một nguồn và quy mọi kết cục về một dòng trạng thái đọc được."""
    started_at = time.monotonic()
    try:
        outcome = await expand_with_provider(
            KEYWORD_PROVIDERS[source], params.seed, params.country, params.depth
        )
        if outcome.error:
            message = f"dừng sau {outcome.calls} lượt gọi: {outcome.error}"
        elif not outcome.hits:
            message = "kết nối được nhưng không trả về từ khoá nào"
        else:
            message = None
        return (
            KeywordSourceStatus(
                source=source,
                ok=len(outcome.hits) > 0,
                count=len({hit.raw.lower() for hit in outcome.hits}),
                calls=outcome.calls,
                took_ms=round((time.monotonic() - started_at) * 1000),
                message=message,
            ),
            outcome.hits,
        )
    except Exception as error:
        return (
            KeywordSourceStatus(
                source=source,
                ok=False,
                count=0,
                calls=0,
                took_ms=round((time.monotonic() - started_at) * 1000),
                message=str(error),
            ),
            [],
        )


async def run_keyword_search(params: KeywordSearchParams, skip_cache: bool = False) -> KeywordResult:
    key = _cache_key(params)
    expansion: _CachedExpansion | None = None if skip_cache else cache_get(key)
    from_cache = expansion is not None

    if expansion is None:
        settled = await asyncio.gather(*(_run_source(source, params) for source in params.sources))
        expansion = _CachedExpansion(
            hits=[hit for _, hits in settled for hit in hits],
            statuses=[status for status, _ in settled],
        )
        if any(status.ok for status in expansion.statuses):
            cache_set(key, expansion)

    ranked = rank_keywords(
        expansion.hits,
        seed=params.seed,
        active_sources=params.sources,
        include_informational=params.include_informational,
    )

    return KeywordResult(
        seed=params.seed,
        keywords=_apply_limit(ranked, params.limit, params.include_informational),
        total_found=len(ranked),
        statuses=expansion.statuses,
        cached=from_cache,
    )
