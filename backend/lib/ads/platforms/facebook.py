"""
NGUỒN: Facebook Ads Library.

API Ad Library chính thức của Facebook chỉ phủ quảng cáo chính trị và vấn đề xã hội,
nên vô dụng với research sản phẩm thương mại. File này dùng đúng endpoint GraphQL mà
giao diện Ads Library công khai đang dùng: nhặt một POST `AdLibrarySearchPaginationQuery`
đã ký từ trang đã làm nóng, rồi phát lại nó với `variables` được viết lại cho từ khoá,
quốc gia và con trỏ phân trang bất kỳ.

Nếu Facebook đổi hình dạng truy vấn, đây là file duy nhất cần sửa.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, quote, urlencode

from playwright.async_api import Request

from lib.core.browser import SessionRecipe, fetch_in_page, get_session, invalidate_session
from lib.core.config import env_number, env_string
from lib.core.jscompat import jround
from lib.core.rate_limit import schedule

from ..platform import (
    AdPlatform,
    HealthProbe,
    MediaPolicy,
    PlatformCapabilities,
    PlatformChoice,
    PlatformOption,
    PlatformSearchInput,
    PlatformSearchOutcome,
)
from ..types import Ad, CountryCode, Creative

PLATFORM_ID = "facebook"
GRAPHQL_PATH = "/api/graphql/"

#: Facebook chịu được gọi liên tiếp; khoảng cách nhỏ chỉ để lịch sự.
MIN_INTERVAL_MS = env_number("FB_MIN_INTERVAL_MS", 1_500)
SESSION_TTL_MS = env_number("FB_SESSION_TTL_MS", 600_000)

#: Số trang tối đa lật qua trong một lần search, tránh vòng lặp vô hạn khi con trỏ lỗi.
MAX_PAGES = 6


# ---------------------------------------------------------------------------
# Tuỳ chọn riêng của Facebook
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FacebookOptions:
    match_mode: Literal["exact", "broad"]
    active_status: Literal["active", "all"]


#: Hai chế độ khớp từ khoá của Facebook.
#:
#: `keyword_unordered` khớp rời từng chữ ở bất kỳ đâu, nên kéo về cả những advertiser hoàn
#: toàn không liên quan — đo thực tế: "AF1" đúng chủ đề 10%, "máy massage cổ" đúng 0%.
#: `keyword_exact_phrase` đạt 80% và 60% trên cùng hai truy vấn đó, và với cụm tiếng Việt
#: nó còn trả về *nhiều* quảng cáo hơn — tức là chính xác hơn mà không mất độ phủ.
SEARCH_TYPE = {"exact": "keyword_exact_phrase", "broad": "keyword_unordered"}


# ---------------------------------------------------------------------------
# Phiên trình duyệt
# ---------------------------------------------------------------------------

#: Cookie tuỳ chọn ("c_user=...; xs=..."). Ads Library đọc được ẩn danh — cookie chỉ làm
#: kết quả ổn định hơn khi nhiều người cùng search.
_cookie_header = env_string("FB_COOKIE")


def _warm_url(country: str) -> str:
    return (
        "https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
        f"&country={quote(country, safe='')}&media_type=all&q=a&search_type=keyword_unordered"
    )


def _capture(request: Request) -> dict[str, str] | None:
    if "/api/graphql" not in request.url:
        return None
    post = request.post_data
    if not post or "AdLibrarySearchPaginationQuery" not in post:
        return None
    return {"post_body": post}


_recipe = SessionRecipe(
    id=PLATFORM_ID,
    locale="vi-VN",
    ttl_ms=SESSION_TTL_MS,
    cookie_header=_cookie_header or None,
    cookie_domain=".facebook.com",
    # Facebook chỉ phát truy vấn phân trang khi danh sách được cuộn tới.
    scroll_to_trigger=True,
    warm_url=_warm_url,
    capture=_capture,
    failure_hint="Ads Library có thể đang chặn IP này, hoặc đã đổi tên truy vấn GraphQL.",
)


# ---------------------------------------------------------------------------
# Bóc tách dữ liệu thô
# ---------------------------------------------------------------------------


def _extract_ads(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """
    Phản hồi về dưới dạng nhiều dòng JSON, bản ghi quảng cáo nằm ở độ sâu không ổn định —
    nên duyệt cả cây thay vì cố định một đường dẫn chắc chắn sẽ đổi.
    """
    raw: list[dict[str, Any]] = []
    cursor: str | None = None

    def walk(node: Any, depth: int = 0) -> None:
        nonlocal cursor
        if depth > 16 or node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        if isinstance(node.get("ad_archive_id"), str):
            raw.append(node)
        if not cursor and isinstance(node.get("end_cursor"), str):
            cursor = node["end_cursor"]
        for value in node.values():
            walk(value, depth + 1)

    for line in text.split("\n"):
        trimmed = line.strip()
        if not trimmed.startswith("{"):
            continue
        try:
            parsed = json.loads(trimmed)
        except ValueError:
            continue
        walk(parsed)

    return raw, cursor


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _to_creatives(snapshot: dict[str, Any] | None) -> list[Creative]:
    creatives: list[Creative] = []
    if not snapshot:
        return creatives

    for video in snapshot.get("videos") or []:
        if not isinstance(video, dict):
            continue
        url = video.get("video_hd_url") or video.get("video_sd_url")
        if url:
            creatives.append(
                Creative(kind="video", url=url, poster_url=video.get("video_preview_image_url") or None)
            )
    for image in snapshot.get("images") or []:
        if not isinstance(image, dict):
            continue
        url = image.get("original_image_url") or image.get("resized_image_url")
        if url:
            creatives.append(Creative(kind="image", url=url))
    # Quảng cáo carousel để media trong `cards` chứ không phải hai mảng ở trên.
    for card in snapshot.get("cards") or []:
        if not isinstance(card, dict):
            continue
        video = card.get("video_hd_url") or card.get("video_sd_url")
        if video:
            creatives.append(
                Creative(kind="video", url=video, poster_url=card.get("video_preview_image_url") or None)
            )
            continue
        image = card.get("original_image_url") or card.get("resized_image_url")
        if image:
            creatives.append(Creative(kind="image", url=image))
    return creatives


def _normalise(raw_ad: dict[str, Any], country: CountryCode) -> Ad | None:
    ad_id = _as_str(raw_ad.get("ad_archive_id"))
    if not ad_id:
        return None
    snapshot = raw_ad.get("snapshot") if isinstance(raw_ad.get("snapshot"), dict) else None
    started_at = _as_int(raw_ad.get("start_date"))
    days_active = (
        max(0, jround((time.time() - started_at) / 86_400))
        if started_at is not None and started_at > 0
        else None
    )

    body = (snapshot or {}).get("body")
    body_text = body.get("text") if isinstance(body, dict) else None
    advertiser = (snapshot or {}).get("page_name")
    if advertiser is None:
        advertiser = raw_ad.get("page_name")
    if advertiser is None:
        advertiser = "Unknown"

    title = (snapshot or {}).get("title")
    if title is None:
        title = (snapshot or {}).get("caption")

    publisher_platform = raw_ad.get("publisher_platform")

    return Ad(
        id=ad_id,
        platform=PLATFORM_ID,
        advertiser=str(advertiser),
        body=body_text if isinstance(body_text, str) else "",
        title=_as_str(title),
        cta_text=_as_str((snapshot or {}).get("cta_text")),
        landing_url=_as_str((snapshot or {}).get("link_url")),
        permalink=f"https://www.facebook.com/ads/library/?id={ad_id}",
        creatives=_to_creatives(snapshot),
        started_at=started_at,
        ended_at=_as_int(raw_ad.get("end_date")),
        days_active=days_active,
        is_active=raw_ad.get("is_active") if isinstance(raw_ad.get("is_active"), bool) else None,
        variant_count=_as_int(raw_ad.get("collation_count")),
        page_like_count=_as_int((snapshot or {}).get("page_like_count")),
        countries=[country],
        platforms=publisher_platform if isinstance(publisher_platform, list) else None,
    )


# ---------------------------------------------------------------------------
# Tìm kiếm
# ---------------------------------------------------------------------------


def _rewrite_variables(post_body: str, mutate: dict[str, Any]) -> str:
    """
    Viết lại trường `variables` trong body POST đã nhặt, giữ nguyên mọi trường khác.

    Body chứa token phiên và tên truy vấn mà chỉ Facebook mới sinh đúng được, nên nó được
    dùng lại nguyên vẹn; chỉ phần mô tả truy vấn là của ta.
    """
    pairs = parse_qsl(post_body, keep_blank_values=True)
    variables: dict[str, Any] = {}
    for key, value in pairs:
        if key == "variables":
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    variables = parsed
            except ValueError:
                variables = {}
            break

    variables.update(mutate)
    encoded = json.dumps(variables, ensure_ascii=False, separators=(",", ":"))

    out: list[tuple[str, str]] = []
    replaced = False
    for key, value in pairs:
        if key == "variables":
            out.append((key, encoded))
            replaced = True
        else:
            out.append((key, value))
    if not replaced:
        out.append(("variables", encoded))
    return urlencode(out)


class Facebook(AdPlatform):
    id = PLATFORM_ID
    label = "Facebook"
    capabilities = PlatformCapabilities(
        keyword_search=True, start_date=True, remote_filters=False, video_ads=True
    )
    options = [
        PlatformOption(
            key="matchMode",
            label="Cách khớp từ khoá",
            kind="choice",
            default_value="exact",
            choices=[
                PlatformChoice(
                    value="exact",
                    label="Đúng cụm từ",
                    hint="Khớp đúng cụm từ. Đo thực tế: 60–80% kết quả đúng chủ đề.",
                ),
                PlatformChoice(
                    value="broad",
                    label="Rộng (nhiều rác)",
                    hint=(
                        "Khớp rời từng chữ, bất kể thứ tự. Nhiều kết quả hơn nhưng đo được "
                        "chỉ 0–10% đúng chủ đề."
                    ),
                ),
            ],
        ),
        PlatformOption(
            key="activeStatus",
            label="Trạng thái quảng cáo",
            kind="choice",
            default_value="active",
            choices=[
                PlatformChoice(value="active", label="Đang chạy", hint="Chỉ quảng cáo hiện còn hoạt động"),
                PlatformChoice(value="all", label="Tất cả", hint="Bao gồm cả quảng cáo đã dừng"),
            ],
        ),
    ]
    media = MediaPolicy(
        host_suffixes=["fbcdn.net", "facebook.com"],
        referer="https://www.facebook.com/",
    )
    health_probe = HealthProbe(keyword="kem", country="VN")

    def parse_options(self, raw: dict[str, str]) -> FacebookOptions:
        return FacebookOptions(
            match_mode="broad" if raw.get("matchMode") == "broad" else "exact",
            active_status="all" if raw.get("activeStatus") == "all" else "active",
        )

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        keyword, country, limit = request.keyword, request.country, request.limit
        options: FacebookOptions = request.options

        async def run() -> PlatformSearchOutcome:
            session = await get_session(_recipe, country)
            post_body = session.harvest["post_body"]

            collected: list[Ad] = []
            seen: set[str] = set()
            cursor: str | None = None

            page = 0
            while page < MAX_PAGES and len(collected) < limit:
                page += 1
                body = _rewrite_variables(
                    post_body,
                    {
                        "queryString": keyword,
                        "countries": [country],
                        "activeStatus": options.active_status,
                        "cursor": cursor,
                        "first": min(30, max(10, limit)),
                        "searchType": SEARCH_TYPE[options.match_mode],
                        "sessionID": str(uuid.uuid4()),
                        # Đo thực tế: `mediaType` không được server tôn trọng; lọc video làm
                        # ở tầng trên.
                        "mediaType": "all",
                    },
                )

                response = await fetch_in_page(
                    session,
                    url=GRAPHQL_PATH,
                    method="POST",
                    headers={"content-type": "application/x-www-form-urlencoded"},
                    body=body,
                )

                if response["status"] != 200:
                    invalidate_session(PLATFORM_ID, country)
                    raise RuntimeError(f"Facebook GraphQL trả về HTTP {response['status']}")

                raw, next_cursor = _extract_ads(response["text"])
                if not raw:
                    # Trang đầu rỗng và không có con trỏ thường nghĩa là truy vấn đã nhặt bị
                    # từ chối.
                    if page == 1 and not next_cursor:
                        invalidate_session(PLATFORM_ID, country)
                    break

                for raw_ad in raw:
                    ad = _normalise(raw_ad, country)
                    if ad is None or ad.id in seen:
                        continue
                    seen.add(ad.id)
                    collected.append(ad)

                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor

            # XẾP HẠNG, KHÔNG LOẠI BỎ — và việc đó không xảy ra ở đây.
            #
            # Ads Library khớp cụm từ ở ĐÂU ĐÓ trong dữ liệu quảng cáo (tên trang, đường dẫn,
            # trang đích) chứ không bắt buộc trong phần chữ người xem đọc được, nên bảng trả về
            # luôn lẫn 20-40% quảng cáo lệch chủ đề. Cách chữa nằm ở `lib/ads/relevance.py`: nó
            # gắn cờ `phrase_hit` rồi ĐẨY XUỐNG DƯỚI, giữ nguyên số dòng.
            #
            # Ở đây từng có một bộ lọc thật sự cắt bỏ, và nó hỏng theo đúng kiểu tệ nhất: xin 8
            # quảng cáo về 3 (đo "kem chống nắng" 2026-08-24, cắt 7/10) mà người dùng chỉ thấy
            # một lưới ngắn — đọc thành "sản phẩm này không ai chạy quảng cáo". Một cụm từ nằm
            # trong ẢNH quảng cáo là chuyện thường, và không có cách nào đọc được nó từ đây.
            if request.relax_keyword:
                return PlatformSearchOutcome(
                    ads=collected[:limit],
                    notice=f"Khớp ảnh: {len(collected)} ứng viên FB — để ảnh quyết định, không lọc chữ.",
                )
            return PlatformSearchOutcome(ads=collected[:limit])

        return await schedule(f"{PLATFORM_ID}:{country}", MIN_INTERVAL_MS, run)


facebook = Facebook()
