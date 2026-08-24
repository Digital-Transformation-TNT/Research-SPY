"""
Điều phối tìm kiếm quảng cáo trên nhiều nguồn và nhiều quốc gia.

File này KHÔNG biết Facebook hay TikTok là gì — nó chỉ làm việc với sổ đăng ký nguồn.
Nhờ vậy thêm một nguồn mới không phải sửa gì ở đây, cũng không phải sửa route.

Mỗi nguồn tự báo cáo trạng thái riêng, để một lần hỏng hiện ra thành cảnh báo đỏ thay vì
một lưới rỗng trông như "sản phẩm này không có ai chạy quảng cáo" — đúng kiểu hỏng dễ
đẩy người dùng đi sai hướng nhất.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Mapping

from lib.core.cache import cache_get, cache_set
from lib.core.jscompat import or_default, to_number

from .platform import PlatformSearchInput
from .platforms import PLATFORM_IDS, get_platform, is_platform_id
from .relevance import phrase_hit
from .scoring import score_and_rank
from .types import Ad, AdSearchParams, AdSearchResult, PlatformStatus

DEFAULT_LIMIT = 30
MAX_LIMIT = 100


def parse_ad_search_params(query: Mapping[str, list[str]]) -> AdSearchParams:
    """
    Đọc tham số từ query string.

    Tuỳ chọn riêng của nguồn đi theo dạng `<nguồn>.<khoá>`, ví dụ `tiktok.period=30` hay
    `facebook.matchMode=exact`. Nhờ tiền tố này, hai nguồn có cùng tên tuỳ chọn cũng không
    đụng nhau, và route không cần biết nguồn nào có tuỳ chọn gì.

    `query` là dạng nhiều-giá-trị-mỗi-khoá; chỉ giá trị đầu được dùng, giống `URLSearchParams.get`.
    """

    def first(name: str) -> str | None:
        values = query.get(name)
        return values[0] if values else None

    def as_list(name: str) -> list[str]:
        return [s.strip() for s in (first(name) or "").split(",") if s.strip()]

    requested = [p for p in as_list("platforms") if is_platform_id(p)]
    countries = [c.upper() for c in as_list("countries")]

    platform_options: dict[str, dict[str, str]] = {}
    for key, values in query.items():
        dot = key.find(".")
        if dot <= 0:
            continue
        platform_id = key[:dot]
        if not is_platform_id(platform_id):
            continue
        platform_options.setdefault(platform_id, {})[key[dot + 1 :]] = values[0]

    return AdSearchParams(
        keyword=(first("keyword") or "").strip(),
        platforms=requested or list(PLATFORM_IDS),
        countries=countries or ["VN"],
        video_only=first("videoOnly") == "true",
        min_days_active=or_default(to_number(first("minDaysActive")), 0),
        # `limit` thì phải là số nguyên vì nó đi thẳng vào phép cắt danh sách; `Array.slice`
        # của JS tự bỏ phần thập phân, `int()` ở đây cho ra đúng cùng số phần tử.
        limit=int(min(MAX_LIMIT, or_default(to_number(first("limit")), DEFAULT_LIMIT))),
        platform_options=platform_options,
    )


def _options_for_key(value: Any) -> Any:
    """Đưa options của một nguồn về dạng so sánh được, để dựng cache key ổn định."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: v for k, v in dataclasses.asdict(value).items() if v is not None}
    return value


def _cache_key(params: AdSearchParams, fetch_size: int) -> str:
    """
    Chỉ những tham số làm thay đổi thứ ta *đi lấy về* mới thuộc về cache key.

    `video_only` và `min_days_active` được áp dụng sau cache, nên đưa chúng vào đây vừa làm
    vỡ vụn cache, vừa — tệ hơn — cho phép một bản cache chưa lọc được trả cho một request có
    lọc. Hình dạng này tránh đúng lỗi đó.
    """
    options = []
    for platform_id in sorted(params.platforms):
        platform = get_platform(platform_id)
        parsed = platform.parse_options(params.platform_options.get(platform_id, {})) if platform else None
        options.append([platform_id, _options_for_key(parsed)])
    return json.dumps(
        ["ads", params.keyword.lower(), sorted(params.countries), fetch_size, options],
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass
class _CachedFetch:
    """Thứ được cache: tập quảng cáo đã gộp, chưa lọc, kèm kết quả từng nguồn."""

    ads: list[Ad]
    statuses: list[PlatformStatus]


def _interleave_by_platform(ranked: list[Ad], limit: int) -> list[Ad]:
    """
    Lấp đầy kết quả bằng cách rút luân phiên từ danh sách đã xếp hạng của từng nguồn.

    Sắp xếp toàn cục đơn thuần sẽ trao gần như mọi suất cho Facebook: điểm dựa nhiều vào đời
    quảng cáo, mà TikTok không công bố ngày bắt đầu, nên quảng cáo của nó về mặt cấu trúc
    không thể đạt điểm cao bằng. Người dùng tick cả hai nguồn sẽ thấy dòng trạng thái ghi
    "tiktok 19" bên trên một lưới không có TikTok nào. Luân phiên giữ mọi nguồn đã chọn đều
    xuất hiện, mà vẫn giữ đúng thứ tự xếp hạng bên trong mỗi nguồn.
    """
    by_platform: dict[str, list[Ad]] = {}
    for ad in ranked:
        by_platform.setdefault(ad.platform, []).append(ad)
    if len(by_platform) <= 1:
        return ranked[:limit]

    buckets = list(by_platform.values())
    out: list[Ad] = []
    i = 0
    while len(out) < limit:
        took = False
        for bucket in buckets:
            if i >= len(bucket):
                continue
            out.append(bucket[i])
            took = True
            if len(out) >= limit:
                break
        if not took:
            break  # mọi nguồn đã cạn
        i += 1
    return out


def _present(fetched: _CachedFetch, params: AdSearchParams, from_cache: bool) -> AdSearchResult:
    """Lọc, chấm điểm và cắt bớt — chạy lại mỗi request, dù dữ liệu từ cache hay lấy mới."""
    ads = fetched.ads

    if params.video_only:
        ads = [ad for ad in ads if any(c.kind == "video" for c in ad.creatives)]
    if params.min_days_active and params.min_days_active > 0:
        ads = [ad for ad in ads if ad.days_active is not None and ad.days_active >= params.min_days_active]

    # ĐỘ LIÊN QUAN TỚI TỪ KHOÁ, tính ở đây chứ không ở `scoring.py`: điểm bên đó trả lời "sản
    # phẩm này có đáng bán không", còn cờ này trả lời "quảng cáo này có đúng thứ tôi vừa tìm
    # không". Trộn hai câu vào một con số thì không đọc lại được cái nào.
    for ad in ads:
        ad.phrase_hit = phrase_hit(
            [ad.body, ad.title, ad.cta_text, ad.advertiser], params.keyword
        )

    # Quảng cáo CHỨA cụm từ lên trước, phần còn lại giữ nguyên thứ tự điểm ở trong nhóm — đúng
    # khuôn `_sorted_matches` của mục Tìm bằng ảnh: xếp lại, không xoá bớt.
    ranked = score_and_rank(ads)
    ranked.sort(key=lambda ad: ad.phrase_hit is False)

    return AdSearchResult(
        ads=_interleave_by_platform(ranked, params.limit),
        statuses=fetched.statuses,
        cached=from_cache,
    )


def _merge_by_identity(ads: list[Ad]) -> list[Ad]:
    """
    Gộp cùng một quảng cáo xuất hiện ở nhiều quốc gia.

    Một advertiser thường chạy cùng creative ở nhiều nước; gộp lại thay vì hiện hai lần,
    nhưng giữ đủ danh sách quốc gia đã thấy — chính độ trải đó là một tín hiệu về việc sản
    phẩm đang đi tới đâu.
    """
    merged: dict[str, Ad] = {}
    for ad in ads:
        key = f"{ad.platform}:{ad.id}"
        existing = merged.get(key)
        if existing is not None:
            for country in ad.countries:
                if country not in existing.countries:
                    existing.countries.append(country)
        else:
            # Bản sao có danh sách quốc gia riêng, để phép gộp bên trên không thò tay vào
            # đúng object mà nguồn vừa trả về.
            merged[key] = ad.model_copy(update={"countries": list(ad.countries)})
    return list(merged.values())


async def run_ad_search(params: AdSearchParams, skip_cache: bool = False) -> AdSearchResult:
    # Bộ lọc hậu kỳ vứt bớt dòng, nên phải lấy dư khi có bộ lọc — nếu không, xin 30 quảng cáo
    # có video sẽ lặng lẽ trả về đúng phần nhỏ trong 30 cái tình cờ có video.
    filtering = params.video_only or params.min_days_active > 0
    fetch_size = math.ceil(params.limit * (2.5 if filtering else 1))
    per_job_limit = math.ceil(fetch_size / len(params.countries))

    key = _cache_key(params, fetch_size)
    if not skip_cache:
        cached = cache_get(key)
        if cached is not None:
            return _present(cached, params, True)

    jobs = [(platform_id, country) for country in params.countries for platform_id in params.platforms]

    async def run_job(platform_id: str, country: str) -> tuple[list[Ad], PlatformStatus]:
        started_at = time.monotonic()
        platform = get_platform(platform_id)
        assert platform is not None  # `params.platforms` đã được lọc qua sổ đăng ký
        try:
            options = platform.parse_options(params.platform_options.get(platform_id, {}))
            outcome = await platform.search(
                PlatformSearchInput(
                    keyword=params.keyword, country=country, limit=per_job_limit, options=options
                )
            )
            return outcome.ads, PlatformStatus(
                platform=platform_id,
                ok=True,
                count=len(outcome.ads),
                message=outcome.notice,
                took_ms=round((time.monotonic() - started_at) * 1000),
            )
        except Exception as error:
            return [], PlatformStatus(
                platform=platform_id,
                ok=False,
                count=0,
                message=f"{country}: {error}",
                took_ms=round((time.monotonic() - started_at) * 1000),
            )

    settled = await asyncio.gather(*(run_job(platform_id, country) for platform_id, country in jobs))

    fetched = _CachedFetch(
        ads=_merge_by_identity([ad for ads, _ in settled for ad in ads]),
        statuses=[status for _, status in settled],
    )

    # Chỉ cache những lần có ít nhất một nguồn chạy được, để một sự cố tạm thời không bị đóng băng.
    if any(status.ok for status in fetched.statuses):
        cache_set(key, fetched)

    return _present(fetched, params, False)
