"""
NGUỒN: TikTok Creative Center (Top Ads).

Creative Center không có API công khai. Endpoint nội bộ `top_ads/v2/list` từ chối HTTP
thường với mã 40101, nên phải nhặt header đã ký từ một trang đã làm nóng rồi phát lại.
Đo thực tế: `user-sign` ký trên bộ ba header chứ không ký URL — chính điều đó cho phép
một lần làm nóng phục vụ nhiều truy vấn và nhiều quốc gia.

Hai giới hạn mang tính cấu trúc, được nói thẳng ra giao diện chứ không giấu đi:

 1. KHÔNG CÓ CVR. Creative Center công bố CTR, lượt thích và một chỉ số chi phí tương
    đối. Tỷ lệ chuyển đổi là dữ liệu riêng của advertiser, không lấy được từ bất kỳ bề
    mặt công khai nào.
 2. Search theo từ khoá chạy trên một danh mục brand/product được index sẵn, và phiên ẩn
    danh không truy cập được danh mục đó — `keyword=` khi ấy trả về 0 kết quả *kèm mã
    thành công*. Nếu không xử lý, điều đó đọc thành "sản phẩm này không có nhu cầu", là
    sai lầm nguy hiểm nhất công cụ này có thể mắc. Nên khi search từ khoá không ra gì,
    ta chuyển sang duyệt bảng xếp hạng và tự khớp từ khoá, đồng thời nói rõ trong `notice`.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote, urlencode

from playwright.async_api import Request

from lib.core.browser import SessionRecipe, fetch_in_page, get_session, invalidate_session
from lib.core.config import env_number
from lib.core.jscompat import to_number, vi_sort_key

from lib.core.rate_limit import schedule

from ..platform import (
    AdPlatform,
    FilterGroup,
    FilterOption,
    HealthProbe,
    MediaPolicy,
    PlatformCapabilities,
    PlatformChoice,
    PlatformOption,
    PlatformSearchInput,
    PlatformSearchOutcome,
)
from ..types import Ad, CountryCode, Creative

PLATFORM_ID = "tiktok"
LIST_PATH = "/creative_radar_api/v1/top_ads/v2/list"
FILTERS_PATH = "/creative_radar_api/v1/top_ads/v2/filters"

#: TikTok trả 40100 "too many requests" sau khoảng năm lần gọi nhanh, nên phải giãn rộng.
MIN_INTERVAL_MS = env_number("TIKTOK_MIN_INTERVAL_MS", 9_000)
#: Chữ ký nhặt được đo thấy còn hiệu lực ít nhất ~3,5 phút; làm mới sớm hơn cho chắc.
SESSION_TTL_MS = env_number("TIKTOK_SESSION_TTL_MS", 150_000)

#: Endpoint từ chối giá trị lớn hơn với lỗi
#: `40000 ... 'GetTopAdsMaterialListV2Params.Limit' failed on the 'max' tag`,
#: nên muốn nhiều kết quả thì phải lật trang chứ không xin một lần.
MAX_PAGE_SIZE = 20

#: Các trang được lấy liên tiếp trong cùng một suất rate-limit; vẫn giãn chúng ra.
INTER_PAGE_DELAY_MS = 1_200


# ---------------------------------------------------------------------------
# Tuỳ chọn riêng của TikTok
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TikTokOptions:
    #: Chỉ chấp nhận 7, 30 và 180 — giá trị khác bị từ chối thẳng.
    period: int
    #: Id ngành hàng, lấy từ `/api/ads/filters?platform=tiktok`.
    industry: str | None = None


# ---------------------------------------------------------------------------
# Phiên trình duyệt
# ---------------------------------------------------------------------------


def _warm_url(country: str) -> str:
    return (
        "https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en"
        f"?region={quote(country, safe='')}"
    )


def _capture(request: Request) -> dict[str, str] | None:
    if "creative_radar_api" not in request.url:
        return None
    headers = request.headers
    if not headers.get("user-sign") or not headers.get("anonymous-user-id") or not headers.get("timestamp"):
        return None
    return {
        "anonymous-user-id": headers["anonymous-user-id"],
        "timestamp": headers["timestamp"],
        "user-sign": headers["user-sign"],
        "lang": headers.get("lang") or "en",
        "accept": "application/json, text/plain, */*",
    }


_recipe = SessionRecipe(
    id=PLATFORM_ID,
    locale="en-US",
    ttl_ms=SESSION_TTL_MS,
    warm_url=_warm_url,
    capture=_capture,
    failure_hint="Creative Center có thể đang giới hạn IP này, hoặc đã đổi cấu trúc trang.",
)


# ---------------------------------------------------------------------------
# Bóc tách dữ liệu thô
# ---------------------------------------------------------------------------


def _best_video_url(urls: dict[str, str] | None) -> str | None:
    """Lấy bản dựng có độ phân giải cao nhất đang được cung cấp."""
    if not urls:
        return None
    for key in ("1080p", "720p", "540p", "480p", "360p"):
        if urls.get(key):
            return urls[key]
    values = list(urls.values())
    return values[0] if values else None


def _normalise(material: dict[str, Any], country: CountryCode) -> Ad | None:
    material_id = material.get("id")
    if not material_id:
        return None
    material_id = str(material_id)
    video = material.get("video_info") if isinstance(material.get("video_info"), dict) else None
    url = _best_video_url((video or {}).get("video_url"))

    if url:
        creatives = [
            Creative(
                kind="video",
                url=url,
                poster_url=(video or {}).get("cover"),
                width=(video or {}).get("width"),
                height=(video or {}).get("height"),
                duration_sec=(video or {}).get("duration"),
            )
        ]
    elif (video or {}).get("cover"):
        creatives = [Creative(kind="image", url=(video or {})["cover"])]
    else:
        creatives = []

    brand = material.get("brand_name")
    advertiser = (brand.strip() if isinstance(brand, str) else "") or "Không công bố tên brand"

    return Ad(
        id=material_id,
        platform=PLATFORM_ID,
        # Creative Center để trống brand_name với hầu hết advertiser không phải brand lớn;
        # nói thẳng ra thay vì hiện "Unknown" trông như lỗi parse.
        advertiser=advertiser,
        body=material.get("ad_title") if isinstance(material.get("ad_title"), str) else "",
        permalink=f"https://ads.tiktok.com/business/creativecenter/topads/{material_id}/pc/en",
        creatives=creatives,
        ctr_percent=material.get("ctr"),
        like_count=material.get("like"),
        cost_index=material.get("cost"),
        industry=material.get("industry_key"),
        objective=material.get("objective_key"),
        countries=[country],
    )


def _matches_keyword(ad: Ad, keyword: str) -> bool:
    """Nội dung quảng cáo này có vẻ liên quan tới từ khoá người dùng nhập không?"""
    needle = keyword.lower().strip()
    if not needle:
        return True
    haystack = f"{ad.body} {ad.advertiser}".lower()
    if needle in haystack:
        return True
    # Chấp nhận cả quảng cáo khớp mọi từ trong cụm, cho sản phẩm nhiều chữ.
    terms = [t for t in re.split(r"\s+", needle) if len(t) > 2]
    return len(terms) > 1 and all(t in haystack for t in terms)


# ---------------------------------------------------------------------------
# Tìm kiếm
# ---------------------------------------------------------------------------

LOGIN_LIMIT_NOTE = (
    "TikTok không search được theo từ khoá — Creative Center chỉ mở chức năng này cho "
    "tài khoản đã đăng nhập."
)


class TikTok(AdPlatform):
    id = PLATFORM_ID
    label = "TikTok"
    capabilities = PlatformCapabilities(keyword_search=False, start_date=False, remote_filters=True)
    options = [
        PlatformOption(
            key="industry",
            label="Ngành hàng",
            hint=(
                "TikTok không search được theo từ khoá, nên ngành hàng là cách duy nhất để "
                "nhắm kết quả."
            ),
            kind="remote",
            remote_group="industry",
        ),
        PlatformOption(
            key="period",
            label="Khoảng thời gian",
            kind="choice",
            default_value="30",
            choices=[
                PlatformChoice(value="7", label="7 ngày"),
                PlatformChoice(value="30", label="30 ngày"),
                PlatformChoice(value="180", label="180 ngày"),
            ],
        ),
    ]
    media = MediaPolicy(
        host_suffixes=[
            "tiktokcdn.com",
            "tiktokcdn-us.com",
            "tiktokcdn-eu.com",
            "ibyteimg.com",
            "byteoversea.com",
            "muscdn.com",
            "ttwstatic.com",
        ],
        referer="https://ads.tiktok.com/",
    )
    health_probe = HealthProbe(keyword="", country="VN")
    supports_filters = True

    def parse_options(self, raw: dict[str, str]) -> TikTokOptions:
        period = to_number(raw.get("period"))
        industry = (raw.get("industry") or "").strip() or None
        return TikTokOptions(period=int(period) if period in (7, 180) else 30, industry=industry)

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        keyword, country, limit = request.keyword, request.country, request.limit
        options: TikTokOptions = request.options
        period, industry = options.period, options.industry

        async def run() -> PlatformSearchOutcome:
            session = await get_session(_recipe, country)
            headers = session.harvest

            async def call(query: list[tuple[str, str]]) -> dict[str, Any]:
                response = await fetch_in_page(
                    session, url=f"{LIST_PATH}?{urlencode(query)}", headers=headers
                )
                try:
                    parsed = json.loads(response["text"])
                except ValueError as error:
                    raise RuntimeError(
                        f"TikTok trả về dữ liệu không phải JSON (HTTP {response['status']})"
                    ) from error
                code = parsed.get("code")
                if code == 40101:
                    invalidate_session(PLATFORM_ID, country)
                    raise RuntimeError(
                        "TikTok từ chối chữ ký đã nhặt — phiên đã được dựng lại, thử lại giúp"
                    )
                if code == 40100:
                    raise RuntimeError(
                        "TikTok chặn vì gọi quá nhanh (40100) — chờ một lát hoặc tăng "
                        "TIKTOK_MIN_INTERVAL_MS"
                    )
                if code != 0:
                    raise RuntimeError(f"TikTok lỗi {code}: {parsed.get('msg') or 'không rõ'}")
                return parsed

            def base(page: int) -> list[tuple[str, str]]:
                query = [
                    ("period", str(period)),
                    ("page", str(page)),
                    ("limit", str(MAX_PAGE_SIZE)),
                    ("country_code", country),
                ]
                if industry:
                    query.append(("industry", industry))
                return query

            async def collect(build: Callable[[int], list[tuple[str, str]]]) -> list[Ad]:
                """Lật trang tới khi đủ `limit` hoặc nguồn hết kết quả mới."""
                out: list[Ad] = []
                seen: set[str] = set()
                max_pages = min(4, math.ceil(limit / MAX_PAGE_SIZE))

                page = 1
                while page <= max_pages and len(out) < limit:
                    if page > 1:
                        await asyncio.sleep(INTER_PAGE_DELAY_MS / 1000)
                    response = await call(build(page))
                    materials = (response.get("data") or {}).get("materials") or []
                    if not materials:
                        break

                    for material in materials:
                        ad = _normalise(material, country)
                        if ad is None or ad.id in seen:
                            continue
                        seen.add(ad.id)
                        out.append(ad)
                    if len(materials) < MAX_PAGE_SIZE:
                        break
                    page += 1
                return out

            def searched_query(page: int) -> list[tuple[str, str]]:
                query = base(page)
                query.append(("keyword", keyword))
                query.append(("order_by", "for_you"))
                query.append(("search_id", str(uuid.uuid4())))
                return query

            # Thử đường search thật trước — nó có chạy khi phiên được cấp quyền.
            searched_ads = await collect(searched_query)
            if searched_ads:
                return PlatformSearchOutcome(ads=searched_ads[:limit])

            # Search từ khoá rỗng. Thường là do danh mục đóng chứ không phải thật sự không có
            # nhu cầu, nên duyệt bảng xếp hạng rồi tự lọc.
            await asyncio.sleep(INTER_PAGE_DELAY_MS / 1000)

            def browsed_query(page: int) -> list[tuple[str, str]]:
                query = base(page)
                query.append(("order_by", "ctr"))
                return query

            browsed_ads = await collect(browsed_query)

            # Ngành hàng người dùng chủ động chọn *chính là* phạm vi họ muốn. Lọc thêm bằng
            # từ khoá sẽ vứt đi đúng những quảng cáo họ vừa yêu cầu — và vì TikTok chưa từng
            # khớp từ khoá, bộ lọc đó dù sao cũng chỉ là đoán.
            if industry:
                empty = (
                    " (ngành này hiện không có quảng cáo nào trong khoảng thời gian đã chọn — "
                    "thử nới lên 180 ngày)"
                    if not browsed_ads
                    else ""
                )
                return PlatformSearchOutcome(
                    ads=browsed_ads[:limit],
                    notice=(
                        f"{LOGIN_LIMIT_NOTE} Đang hiển thị Top Ads theo CTR của ngành hàng bạn "
                        f"chọn tại {country}{empty}."
                    ),
                )

            scope_hint = 'chưa lọc ngành hàng — chọn "Ngành hàng" để thu hẹp lại'
            matched = [ad for ad in browsed_ads if _matches_keyword(ad, keyword)]
            if matched:
                return PlatformSearchOutcome(
                    ads=matched[:limit],
                    notice=(
                        f"{LOGIN_LIMIT_NOTE} Đây là kết quả lọc từ bảng xếp hạng Top Ads theo "
                        f"CTR ({scope_hint})."
                    ),
                )

            return PlatformSearchOutcome(
                ads=browsed_ads[:limit],
                notice=(
                    f"{LOGIN_LIMIT_NOTE} Đang hiển thị Top Ads theo CTR của {country}, "
                    f"{scope_hint}. "
                    f'Đây KHÔNG phải kết quả cho "{keyword}" — hãy dựa vào phần Facebook để '
                    "đánh giá nhu cầu sản phẩm."
                ),
            )

        return await schedule(f"{PLATFORM_ID}:{country}", MIN_INTERVAL_MS, run)

    # -----------------------------------------------------------------------
    # Bộ lọc động
    # -----------------------------------------------------------------------

    async def fetch_filters(self, country: CountryCode = "VN") -> list[FilterGroup]:
        """
        Danh mục ngành hàng / quốc gia / mục tiêu, dùng để đổ vào ô chọn trên giao diện.

        Việc gom nhóm 258 ngành hàng theo `parent_id` được làm ở đây — tức là ngay trong file
        của nguồn — để giao diện chỉ cần vẽ một danh sách phẳng có tiêu đề nhóm, không phải
        biết gì về cấu trúc riêng của TikTok.

        TikTok trả `id` và `parent_id` dưới dạng *số* JSON chứ không phải chuỗi. Coi `id` là
        chuỗi từng làm sập cả trang với lỗi "a.id.slice is not a function", nên ép kiểu
        tường minh.
        """

        async def run() -> list[FilterGroup]:
            session = await get_session(_recipe, country)
            response = await fetch_in_page(session, url=FILTERS_PATH, headers=session.harvest)
            parsed = json.loads(response["text"])
            if parsed.get("code") != 0:
                raise RuntimeError(f"TikTok filters lỗi {parsed.get('code')}")

            industries = (parsed.get("data") or {}).get("industry") or []
            name_by_id = {str(item["id"]): item["value"] for item in industries}

            options: list[FilterOption] = []
            for item in industries:
                parent_id = "" if item.get("parent_id") is None else str(item["parent_id"])
                is_top_level = not parent_id or parent_id == str(item["id"])
                options.append(
                    FilterOption(
                        value=str(item["id"]),
                        label=item["value"],
                        # Mục không tra được cha vẫn phải chọn được, nên rơi vào nhóm gom chung.
                        group="Ngành chính"
                        if is_top_level
                        else name_by_id.get(parent_id, "Ngành chính"),
                    )
                )

            options.sort(key=lambda o: (vi_sort_key(o.group or ""), vi_sort_key(o.label)))
            return [FilterGroup(key="industry", label="Ngành hàng", options=options)]

        return await schedule(f"{PLATFORM_ID}:{country}", MIN_INTERVAL_MS, run)


tiktok = TikTok()
