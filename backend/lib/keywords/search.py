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
import re
import time
from dataclasses import dataclass
from typing import Mapping

from lib.core.cache import cache_get, cache_set
from lib.core.jscompat import or_default, to_number

from .market import seed_looks_out_of_market
from .providers import KEYWORD_PROVIDERS, KEYWORD_SOURCE_IDS, expand_with_provider, is_keyword_source
from .rank import rank_keywords
from .types import (
    DEFAULT_TIME_RANGE,
    KeywordCandidate,
    KeywordResult,
    KeywordSearchParams,
    KeywordSourceStatus,
    SourceHit,
)

#: Các kho dữ liệu Google Trends nhận ở tham số `gprop`. Rỗng = Tìm kiếm trên web.
#:
#: Chốt danh sách chứ không cho đi thẳng: một `gprop` lạ không làm Trends báo lỗi mà im lặng
#: rơi về web search, nên gõ sai sẽ cho ra một bảng trông hợp lệ nhưng không phải thứ đã hỏi.
TRENDS_PROPERTIES = ("", "images", "news", "froogle", "youtube")

#: Số dòng hiển thị. Cố định 30 cho mọi trường hợp — một nền tảng hay cả ba — và giao diện
#: không có nút chỉnh. Danh sách dài không giúp gì khi phần đầu đã được xếp theo nhu cầu đo
#: được: từ dòng thứ ba mươi trở đi thì lượng tìm đã nhỏ tới mức không còn để ra quyết định.
DEFAULT_LIMIT = 30
MAX_LIMIT = 300


#: Các cửa sổ dựng sẵn của /explore, đúng chuỗi mà trang đó dùng.
TRENDS_PRESET_RANGES = (
    "now 1-H",
    "now 4-H",
    "now 1-d",
    "now 7-d",
    "today 1-m",
    "today 3-m",
    "today 12-m",
    "today 5-y",
    "all",
)

#: Khoảng tuỳ chỉnh: hai ngày ISO cách nhau một dấu cách, ví dụ `2025-01-01 2025-12-31`.
_CUSTOM_RANGE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{4}-\d{2}-\d{2}$")


def clean_time_range(raw: str | None) -> str:
    """
    Chỉ cho qua những cửa sổ Trends thật sự hiểu, còn lại rơi về mặc định.

    Cùng lý do với `TRENDS_PROPERTIES`: một chuỗi `date` lạ không làm Trends báo lỗi mà im
    lặng rơi về cửa sổ mặc định của nó, nên gõ sai sẽ cho ra một bảng trông hợp lệ nhưng
    không phải khoảng thời gian người dùng đã chọn.
    """
    value = (raw or "").strip()
    if value in TRENDS_PRESET_RANGES or _CUSTOM_RANGE.match(value):
        return value
    return DEFAULT_TIME_RANGE


def parse_keyword_search_params(query: Mapping[str, list[str]]) -> KeywordSearchParams:
    def first(name: str) -> str | None:
        values = query.get(name)
        return values[0] if values else None

    requested = [s.strip() for s in (first("sources") or "").split(",") if is_keyword_source(s.strip())]

    depth_param = first("depth")
    depth = depth_param if depth_param in ("quick", "deep") else "normal"

    gprop = (first("gprop") or "").strip().lower()

    return KeywordSearchParams(
        seed=(first("seed") or "").strip(),
        sources=requested or list(KEYWORD_SOURCE_IDS),
        country=(first("country") or "VN").upper(),
        depth=depth,  # type: ignore[arg-type]
        include_informational=first("includeInformational") == "true",
        limit=int(min(MAX_LIMIT, or_default(to_number(first("limit")), DEFAULT_LIMIT))),
        time_range=clean_time_range(first("date")),
        gprop=gprop if gprop in TRENDS_PROPERTIES else "",
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

    Cửa sổ thời gian và kho dữ liệu THÌ thuộc về: chúng đổi hẳn tập từ khoá Trends trả về, nên
    thiếu chúng thì đổi sang "24 giờ qua" hay "Google Mua sắm" sẽ nhận nguyên bảng của lần
    trước — im lặng, và trông hoàn toàn hợp lý.
    """
    return json.dumps(
        [
            "kw",
            params.seed.lower(),
            sorted(params.sources),
            params.depth,
            params.country,
            params.time_range,
            params.gprop,
        ],
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


def _assign_display_ranks(shown: list[KeywordCandidate]) -> None:
    """
    Đánh số lại 1..N cho ĐÚNG những dòng sẽ hiện ra, cho từng nguồn.

    Chạy SAU khi đã xếp và đã cắt, và cố ý không đụng tới `source_ranks` — thứ hạng thật vẫn
    được dùng để chấm điểm và vẫn hiện trong tooltip kèm mẫu số.

    Giữ nguyên THỨ TỰ của thứ hạng thật chứ không đánh theo thứ tự dòng: với một nguồn duy
    nhất thì hai cách cho cùng kết quả, nhưng khi bật nhiều nguồn thì bảng được xếp theo điểm
    gộp, và lúc đó "dòng Google ưu tiên thứ 5" là một thông tin thật — còn đánh theo thứ tự
    dòng chỉ chép lại cột số thứ tự bên trái.
    """
    sources = {source for candidate in shown for source in candidate.source_ranks}
    for source in sources:
        members = [c for c in shown if source in c.source_ranks]
        members.sort(key=lambda c: c.source_ranks[source])
        for position, candidate in enumerate(members, start=1):
            candidate.display_ranks[source] = position


async def _run_source(
    source: str, params: KeywordSearchParams
) -> tuple[KeywordSourceStatus, list[SourceHit]]:
    """Chạy một nguồn và quy mọi kết cục về một dòng trạng thái đọc được."""
    started_at = time.monotonic()
    try:
        outcome = await expand_with_provider(
            KEYWORD_PROVIDERS[source], params.seed, params.context, params.depth
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
        country=params.country,
    )

    shown = _apply_limit(ranked.items, params.limit, params.include_informational)
    _assign_display_ranks(shown)

    return KeywordResult(
        seed=params.seed,
        keywords=shown,
        total_found=len(ranked.items),
        source_totals=ranked.source_totals,
        statuses=expansion.statuses,
        seed_notice=_seed_notice(params),
        cached=from_cache,
    )


def _seed_notice(params: KeywordSearchParams) -> str | None:
    """
    Nhắc khi chính từ gốc không thuộc về thị trường đang chọn.

    Tính LUÔN LUÔN, kể cả khi lượt tìm có kết quả: gõ từ gốc tiếng Việt vào thị trường nước
    ngoài mà vẫn ra vài dòng thì còn dễ nhầm hơn là ra bảng rỗng — mấy dòng đó đến từ các sàn
    khớp chuỗi lỏng, không phải từ nhu cầu có thật ở nước đó.
    """
    if not seed_looks_out_of_market(params.seed, params.country):
        return None
    # Nói theo THỊ TRƯỜNG, không khẳng định từ gốc thuộc ngôn ngữ nào. Phép kiểm chỉ biết
    # "không phải ASCII thuần"; suy tiếp ra "đây là tiếng Việt" là bịa thêm một kết luận mà
    # nó không có căn cứ — và đã bịa sai thật: một cụm tiếng Thái từng bị báo là tiếng Việt.
    return (
        f'Từ gốc "{params.seed}" không viết bằng thứ chữ mà người ở {params.country} dùng để '
        "tìm kiếm, nên bảng này gần như chắc chắn rỗng hoặc sai. "
        'Bấm "Tìm cách gọi bản địa" để lấy cụm mà người bản địa thật sự gõ.'
    )
