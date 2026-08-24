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
from .types import (
    Ad,
    AdSearchParams,
    AdSearchResult,
    ClientJob,
    ClientSubmission,
    PlatformStatus,
)

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


def params_from_mapping(data: Mapping[str, Any]) -> AdSearchParams:
    """
    Dựng `AdSearchParams` từ body JSON — dùng cho `/api/ads/ingest`, nơi tham số đến qua POST
    chứ không phải query string. Vẫn lọc nguồn qua sổ đăng ký để một id lạ không lọt vào.
    """
    requested = [p for p in (data.get("platforms") or []) if isinstance(p, str) and is_platform_id(p)]
    countries = [str(c).upper() for c in (data.get("countries") or []) if str(c).strip()]

    raw_options = data.get("platformOptions") or data.get("platform_options") or {}
    platform_options: dict[str, dict[str, str]] = {}
    if isinstance(raw_options, dict):
        for platform_id, opts in raw_options.items():
            if is_platform_id(platform_id) and isinstance(opts, dict):
                platform_options[platform_id] = {str(k): str(v) for k, v in opts.items()}

    # Body JSON có thể gửi số dưới dạng int/float, còn `to_number` nói ngữ nghĩa `Number(x)`
    # của JS và chỉ nhận chuỗi — ép về chuỗi trước để cùng một đường xử lý với query string.
    def num(*keys: str) -> float:
        for key in keys:
            value = data.get(key)
            if value is not None:
                return to_number(str(value))
        return math.nan

    return AdSearchParams(
        keyword=str(data.get("keyword") or "").strip(),
        platforms=requested or list(PLATFORM_IDS),
        countries=countries or ["VN"],
        video_only=bool(data.get("videoOnly") or data.get("video_only") or False),
        min_days_active=or_default(num("minDaysActive", "min_days_active"), 0),
        limit=int(min(MAX_LIMIT, or_default(num("limit"), DEFAULT_LIMIT))),
        platform_options=platform_options,
    )


def _options_for_key(value: Any) -> Any:
    """Đưa options của một nguồn về dạng so sánh được, để dựng cache key ổn định."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: v for k, v in dataclasses.asdict(value).items() if v is not None}
    return value


def _cache_key(params: AdSearchParams, fetch_size: int, platform_ids: list[str]) -> str:
    """
    Chỉ những tham số làm thay đổi thứ ta *đi lấy về* mới thuộc về cache key.

    `video_only` và `min_days_active` được áp dụng sau cache, nên đưa chúng vào đây vừa làm
    vỡ vụn cache, vừa — tệ hơn — cho phép một bản cache chưa lọc được trả cho một request có
    lọc. Hình dạng này tránh đúng lỗi đó.

    `platform_ids` được truyền vào tường minh (thay vì đọc `params.platforms`) vì nguồn
    client_fetch cache riêng theo từng nguồn — bản cache "server" chỉ được ôm đúng những
    nguồn server đã thật sự gộp chung, nếu không một request lẫn cả hai loại sẽ trả nhầm.
    """
    options = []
    for platform_id in sorted(platform_ids):
        platform = get_platform(platform_id)
        parsed = platform.parse_options(params.platform_options.get(platform_id, {})) if platform else None
        options.append([platform_id, _options_for_key(parsed)])
    return json.dumps(
        # `relax_keyword` đổi TẬP được lấy về (nới vs chặt lọc từ khoá) nên phải nằm trong key —
        # nếu không, bản cache của search thường (chặt) có thể trả nhầm cho match-image (nới).
        ["ads", params.keyword.lower(), sorted(params.countries), fetch_size, params.relax_keyword, options],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _client_cache_key(platform_id: str, country: str, keyword: str, options: Any, limit: int) -> str:
    """
    Cache theo TỪNG (nguồn, quốc gia) cho các nguồn client_fetch.

    Đây chính là "áo giáp" bảo vệ tài khoản user: khi user B search cùng từ khoá user A vừa
    tìm, kết quả lấy từ cache và tài khoản user B KHÔNG phải phát thêm request nào ra sàn.
    Vì mỗi lần fetch đi qua đúng một tài khoản thật, giảm số lần gọi là giảm rủi ro bị khoá.
    """
    return json.dumps(
        ["ads-client", platform_id, country, keyword.lower(), limit, _options_for_key(options)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _is_client_fetch(platform_id: str) -> bool:
    platform = get_platform(platform_id)
    return platform is not None and platform.capabilities.client_fetch


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


def _note_days_filter_wipeout(statuses: list[PlatformStatus]) -> list[PlatformStatus]:
    """
    Nói ra chuyện bộ lọc "số ngày chạy tối thiểu" vừa xoá sạch một nguồn.

    Nguồn không công bố ngày bắt đầu (`capabilities.start_date` là False) luôn có
    `days_active` rỗng, nên bất kỳ ngưỡng nào lớn hơn 0 cũng loại 100% quảng cáo của nó —
    kể cả ngưỡng bằng 1. Không có dòng này, dòng trạng thái vẫn ghi "tiktok 19" bên trên một
    lưới không có TikTok nào, đúng kiểu im lặng mà cả file này được viết ra để chống.
    """
    out: list[PlatformStatus] = []
    for status in statuses:
        platform = get_platform(status.platform)
        if status.ok and platform is not None and not platform.capabilities.start_date:
            note = (
                f"Bộ lọc “số ngày chạy tối thiểu” đã loại toàn bộ {status.count} quảng cáo của "
                f"{platform.label}: nguồn này không công bố ngày bắt đầu chạy. Đặt về 0 để thấy lại."
            )
            status = status.model_copy(
                update={"message": f"{status.message} {note}" if status.message else note}
            )
        out.append(status)
    return out


def _present(fetched: _CachedFetch, params: AdSearchParams, from_cache: bool) -> AdSearchResult:
    """Lọc, chấm điểm và cắt bớt — chạy lại mỗi request, dù dữ liệu từ cache hay lấy mới."""
    ads = fetched.ads
    statuses = fetched.statuses

    if params.video_only:
        ads = [ad for ad in ads if any(c.kind == "video" for c in ad.creatives)]
    if params.min_days_active and params.min_days_active > 0:
        ads = [ad for ad in ads if ad.days_active is not None and ad.days_active >= params.min_days_active]
        statuses = _note_days_filter_wipeout(statuses)

    # ĐỘ LIÊN QUAN TỚI TỪ KHOÁ, tính ở đây chứ không ở `scoring.py`: điểm bên đó trả lời "sản
    # phẩm này có đáng bán không", còn cờ này trả lời "quảng cáo này có đúng thứ tôi vừa tìm
    # không". Trộn hai câu vào một con số thì không đọc lại được cái nào.
    #
    # Bỏ qua ở luồng khớp-ảnh (`relax_keyword`): ở đó từ khoá chỉ là lưới vét để lấy ứng viên,
    # còn ẢNH mới là thứ quyết định. Xếp theo cụm từ khi ấy sẽ đẩy đúng thứ CLIP vừa khớp
    # xuống dưới, chỉ vì advertiser không viết tên sản phẩm trong nội dung quảng cáo.
    ranked = score_and_rank(ads)
    if not params.relax_keyword:
        for ad in ranked:
            ad.phrase_hit = phrase_hit(
                [ad.body, ad.title, ad.cta_text, ad.advertiser], params.keyword
            )
        # Quảng cáo CHỨA cụm từ lên trước, phần còn lại giữ nguyên thứ tự điểm ở trong nhóm —
        # đúng khuôn `_sorted_matches` của mục Tìm bằng ảnh: xếp lại, không xoá bớt.
        ranked.sort(key=lambda ad: ad.phrase_hit is False)

    return AdSearchResult(
        ads=_interleave_by_platform(ranked, params.limit),
        statuses=statuses,
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


def _sizes(params: AdSearchParams) -> tuple[int, int]:
    """(fetch_size, per_job_limit) — dùng chung cho cả hai pha để cache key khớp nhau."""
    # Bộ lọc hậu kỳ vứt bớt dòng, nên phải lấy dư khi có bộ lọc — nếu không, xin 30 quảng cáo
    # có video sẽ lặng lẽ trả về đúng phần nhỏ trong 30 cái tình cờ có video.
    filtering = params.video_only or params.min_days_active > 0
    fetch_size = math.ceil(params.limit * (2.5 if filtering else 1))
    per_job_limit = math.ceil(fetch_size / len(params.countries))
    return fetch_size, per_job_limit


async def run_ad_search(params: AdSearchParams, skip_cache: bool = False) -> AdSearchResult:
    """
    Pha 1. Nguồn server tự fetch tại đây; nguồn client_fetch chỉ được dựng lệnh (`pending`)
    trừ khi đã trúng cache. Extension chạy `pending` rồi POST raw về `/api/ads/ingest` (pha 2).
    """
    fetch_size, per_job_limit = _sizes(params)

    server_ids = [p for p in params.platforms if not _is_client_fetch(p)]
    client_ids = [p for p in params.platforms if _is_client_fetch(p)]

    ads: list[Ad] = []
    statuses: list[PlatformStatus] = []
    from_cache = False

    # --- Nguồn fetch phía server (Facebook, TikTok Creative Center…) ---
    if server_ids:
        key = _cache_key(params, fetch_size, server_ids)
        cached = None if skip_cache else cache_get(key)
        if cached is not None:
            ads.extend(cached.ads)
            statuses.extend(cached.statuses)
            from_cache = True
        else:
            jobs = [(pid, c) for c in params.countries for pid in server_ids]

            async def run_job(platform_id: str, country: str) -> tuple[list[Ad], PlatformStatus]:
                started_at = time.monotonic()
                platform = get_platform(platform_id)
                assert platform is not None  # `params.platforms` đã được lọc qua sổ đăng ký
                try:
                    options = platform.parse_options(params.platform_options.get(platform_id, {}))
                    outcome = await platform.search(
                        PlatformSearchInput(
                            keyword=params.keyword, country=country, limit=per_job_limit, options=options,
                            relax_keyword=params.relax_keyword,
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

            settled = await asyncio.gather(*(run_job(pid, c) for pid, c in jobs))
            server_fetched = _CachedFetch(
                ads=_merge_by_identity([ad for job_ads, _ in settled for ad in job_ads]),
                statuses=[status for _, status in settled],
            )
            # Chỉ cache khi có ít nhất một nguồn chạy được, để sự cố tạm thời không bị đóng băng.
            if any(status.ok for status in server_fetched.statuses):
                cache_set(key, server_fetched)
            ads.extend(server_fetched.ads)
            statuses.extend(server_fetched.statuses)

    # --- Nguồn fetch phía client (Shopee, TikTok Shop… — Cách A) ---
    # Trúng cache thì lấy luôn (không tốn request tài khoản user); trượt thì dựng lệnh cho extension.
    pending: list[ClientJob] = []
    for platform_id in client_ids:
        platform = get_platform(platform_id)
        assert platform is not None
        options = platform.parse_options(params.platform_options.get(platform_id, {}))
        for country in params.countries:
            ckey = _client_cache_key(platform_id, country, params.keyword, options, per_job_limit)
            cached_ads = None if skip_cache else cache_get(ckey)
            if cached_ads is not None:
                ads.extend(cached_ads)
                statuses.append(
                    PlatformStatus(platform=platform_id, ok=True, count=len(cached_ads), message="cache", took_ms=0)
                )
            else:
                specs = platform.build_request(
                    PlatformSearchInput(
                        keyword=params.keyword, country=country, limit=per_job_limit, options=options
                    )
                )
                pending.append(ClientJob(platform=platform_id, country=country, requests=specs))

    fetched = _CachedFetch(ads=_merge_by_identity(ads), statuses=statuses)
    result = _present(fetched, params, from_cache)
    return result.model_copy(update={"pending": pending})


async def ingest_client_results(
    params: AdSearchParams, submissions: list[ClientSubmission]
) -> AdSearchResult:
    """
    Pha 2. Nhận raw mà extension fetch bằng session user, chuẩn hoá → chấm điểm → cache.

    Ở đây KHÔNG có gọi mạng: mọi thứ tốn tiền/tốn tài khoản đã xảy ra ở trình duyệt user.
    Kết quả được cache theo (nguồn, quốc gia) để user sau khỏi phải fetch lại.
    """
    _, per_job_limit = _sizes(params)

    ads: list[Ad] = []
    statuses: list[PlatformStatus] = []
    for sub in submissions:
        platform = get_platform(sub.platform)
        if platform is None or not platform.capabilities.client_fetch:
            statuses.append(
                PlatformStatus(
                    platform=sub.platform, ok=False, count=0,
                    message=f"{sub.platform} không phải nguồn client_fetch", took_ms=0,
                )
            )
            continue
        try:
            options = platform.parse_options(params.platform_options.get(sub.platform, {}))
            outcome = platform.parse_response(
                PlatformSearchInput(
                    keyword=params.keyword, country=sub.country, limit=per_job_limit, options=options
                ),
                sub.responses,
            )
            ads.extend(outcome.ads)
            statuses.append(
                PlatformStatus(
                    platform=sub.platform, ok=True, count=len(outcome.ads),
                    message=outcome.notice, took_ms=0,
                )
            )
            ckey = _client_cache_key(sub.platform, sub.country, params.keyword, options, per_job_limit)
            cache_set(ckey, outcome.ads)
        except Exception as error:
            statuses.append(
                PlatformStatus(
                    platform=sub.platform, ok=False, count=0,
                    message=f"{sub.country}: {error}", took_ms=0,
                )
            )

    fetched = _CachedFetch(ads=_merge_by_identity(ads), statuses=statuses)
    return _present(fetched, params, False)
