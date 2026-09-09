"""
NGUỒN: Facebook Ads Library.

API Ad Library chính thức của Facebook chỉ phủ quảng cáo chính trị và vấn đề xã hội, nên vô
dụng với research sản phẩm thương mại. Ba đường lấy dữ liệu, thử theo đúng thứ tự này:

  1. ĐỌC TRANG (`_search_via_page`) — Facebook nhúng sẵn trang kết quả đầu vào HTML của trang
     Ad Library. Không cần máy-thợ, không cần truy vấn đã ký, ~5 giây, 23–30 quảng cáo.
  2. MÁY-THỢ (`_search_via_worker`) — Chrome thật ở IP dân cư, cho lúc IP server bị captcha.
  3. PHÁT LẠI TRUY VẤN ĐÃ KÝ (`run` trong `search`) — nhặt POST `AdLibrarySearchPaginationQuery`
     rồi phát lại với `variables` viết lại. Đường DUY NHẤT phân trang được (`end_cursor`), nhưng
     Facebook soft-block việc phát lại (HTTP 200 kèm 0 kết quả), nên nó đứng cuối.

Thứ tự này ĐẢO so với bản trước, và đảo vì một phép đo chứ không phải vì gu — xem ghi chú
trong `_read_library_page` và `docs/nguon-video-cho-san-pham.md`.

Nếu Facebook đổi hình dạng dữ liệu, đây là file duy nhất cần sửa.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, quote, urlencode

from playwright.async_api import Request

from lib.core.browser import (
    SessionRecipe,
    browser_lane,
    describe_browser_error,
    fetch_in_page,
    get_session,
    invalidate_session,
)
from lib.core.config import env_number, env_string
from lib.core.jscompat import jround
from lib.core.rate_limit import schedule
from lib.core.worker_relay import (
    BATCH_TIMEOUT_S,
    WorkerOffline,
    WorkerTimeout,
    run_on_worker,
    worker_error,
    worker_online,
)

from ..platform import (
    AdPlatform,
    HealthProbe,
    MediaPolicy,
    PlatformCapabilities,
    PlatformChoice,
    PlatformOption,
    PlatformSearchInput,
    PlatformSearchOutcome,
    request_with,
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


#: Độ sâu tối đa khi duyệt cây JSON của Facebook.
#:
#: 16 là con số của bản chỉ đọc RESPONSE GraphQL, nơi quảng cáo nằm khá nông. Trang Ad Library
#: nhúng sẵn trang kết quả đầu vào HTML, và ở đó cùng bản ghi ấy bị bọc thêm mấy lớp
#: `ScheduledServerJS → __bbox → RelayPrefetchedStreamCache` — đo 2026-09-08:
#:
#:     end_cursor      độ sâu 15   ← lọt qua giới hạn 16, nên vẫn đọc được con trỏ
#:     ad_archive_id   độ sâu 19   ← BỊ CẮT
#:
#: Đúng cái bẫy tệ nhất: hàm trả về "0 quảng cáo, có con trỏ", trông y hệt một truy vấn thật
#: sự không có kết quả. 26 chừa dư cho việc Facebook bọc thêm một hai lớp nữa.
_WALK_DEPTH = 26


def _extract_ads(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """
    Phản hồi về dưới dạng nhiều dòng JSON, bản ghi quảng cáo nằm ở độ sâu không ổn định —
    nên duyệt cả cây thay vì cố định một đường dẫn chắc chắn sẽ đổi.
    """
    raw: list[dict[str, Any]] = []
    cursor: str | None = None

    def walk(node: Any, depth: int = 0) -> None:
        nonlocal cursor
        if depth > _WALK_DEPTH or node is None:
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


# ---------------------------------------------------------------------------
# Đọc thẳng TRANG Ad Library (không cần máy-thợ, không cần truy vấn đã ký)
# ---------------------------------------------------------------------------

#: Facebook giờ NHÚNG SẴN trang kết quả đầu tiên vào chính HTML của trang Ad Library, trong một
#: `<script type="application/json">` chứa `search_results_connection.edges[].node.collated_results[]`
#: — cùng hình dạng mà `_extract_ads` vốn đã đọc được từ response GraphQL.
#:
#: Đây là đường RẺ NHẤT và nó đổi hẳn kết luận cũ ("playwright trên VPS bị soft-block"). Cái bị
#: chặn là POST `AdLibrarySearchPaginationQuery` tự phát lại, không phải bản thân trang. Đo
#: 2026-09-08 NGAY TRÊN VPS, 8 lượt (2 bản trình duyệt × 4 truy vấn VN/US): 7 lượt ra 23–30
#: quảng cáo, 1 lượt trượt vì chờ mù bằng `wait_for_timeout` — nên ở đây chờ ĐÚNG cái script ấy
#: xuất hiện, không chờ theo đồng hồ.
#:
#: Cùng lúc đó, đường máy-thợ trả 0 cho MỌI từ khoá: nó ngồi đợi `/api/graphql` mà trang không
#: còn gọi nữa (đo: gql=1, cap=0). Nên đường này chạy TRƯỚC, máy-thợ chỉ còn là lưới đỡ.
_PAGE_READY_JS = (
    "() => [...document.querySelectorAll('script[type=\"application/json\"]')]"
    ".some(s => s.textContent && s.textContent.includes('ad_archive_id'))"
)
_PAGE_SCRIPTS_JS = (
    "els => els.map(e => e.textContent).filter(t => t && t.includes('ad_archive_id'))"
)

#: Trang nhúng đúng MỘT trang kết quả (đo: 30 bản ghi) và cuộn KHÔNG kéo thêm — đo 2026-09-08,
#: cuộn 10 lần chỉ làm trang cao thêm, số `ad_archive_id` đứng yên ở 30 và không có `/api/graphql`
#: nào chở quảng cáo. Nên đừng thêm vòng cuộn ở đây: nó chỉ tốn thời gian chờ.
PAGE_LOAD_TIMEOUT_MS = 45_000
PAGE_READY_TIMEOUT_MS = 25_000


def _library_url(keyword: str, country: str, active_status: str, search_type: str) -> str:
    """URL trang Ad Library — đúng thứ người dùng gõ vào trình duyệt, không phải endpoint nội bộ."""
    query = urlencode(
        {
            "active_status": active_status,
            "ad_type": "all",
            "country": country,
            "media_type": "all",
            "q": keyword,
            "search_type": search_type,
        }
    )
    return f"https://www.facebook.com/ads/library/?{query}"


async def _read_library_page(url: str, locale: str) -> tuple[list[str], str | None]:
    """
    Mở trang Ad Library bằng trình duyệt thật rồi trả về nội dung các script JSON có quảng cáo.

    Trả `([], lý_do)` khi không đọc được. Lý do phải NÓI ĐƯỢC nó hỏng ở đâu — một danh sách rỗng
    im lặng ở đây đọc thành "sản phẩm này không ai chạy quảng cáo", là kiểu sai đắt nhất của tool.

    THỬ HAI LẦN, và không phải để cho chắc. Đo 2026-09-08: cùng một truy vấn, cùng một máy, lượt
    này ra 30 quảng cáo lượt kia ra 0 — Facebook thỉnh thoảng trả bản HTML chưa kèm kết quả.
    Một lần trượt như vậy hiện lên giao diện thành "không có quảng cáo nào", tức là một câu trả
    lời SAI về thị trường, nên nó đáng giá thêm một lượt mở trang.
    """
    for _ in (1, 2):
        pages, why = await _read_library_page_once(url, locale)
        if pages or why:
            return pages, why
    return [], None


async def _read_library_page_once(url: str, locale: str) -> tuple[list[str], str | None]:
    try:
        async with browser_lane() as browser:
            context = await browser.new_context(locale=locale)
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
                try:
                    await page.wait_for_function(_PAGE_READY_JS, timeout=PAGE_READY_TIMEOUT_MS)
                except Exception:
                    # Không có script quảng cáo nào sau ngần ấy giây: hoặc truy vấn thật sự
                    # rỗng, hoặc gặp tường chặn. Phân biệt được bằng chữ trên trang.
                    body = ""
                    try:
                        body = await page.inner_text("body")
                    except Exception:
                        pass
                    if "captcha" in body.lower():
                        return [], "Facebook đòi captcha ở IP này"
                    if not body.strip():
                        return [], "trang Ad Library không tải được (nội dung rỗng)"
                    return [], None  # trang lên bình thường mà không có quảng cáo ⇒ rỗng THẬT
                scripts = await page.eval_on_selector_all(
                    'script[type="application/json"]', _PAGE_SCRIPTS_JS
                )
                return [t for t in scripts if isinstance(t, str)], None
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
    except Exception as error:
        return [], describe_browser_error(error)


def _bo_nhay(keyword: str) -> str | None:
    """Bỏ cặp nháy bọc ngoài, hoặc `None` nếu cụm vốn không bọc nháy. Gương với hai nguồn video."""
    cắt = keyword.strip()
    return cắt[1:-1].strip() or None if len(cắt) > 2 and cắt[0] == '"' and cắt[-1] == '"' else None


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

    async def _search_via_worker(self, request: PlatformSearchInput) -> PlatformSearchOutcome | None:
        """
        Lấy quảng cáo qua MÁY-THỢ (Chrome thật): bảo thợ mở tab Ad Library của keyword, để chính
        trang bắn query đã ký, chộp RESPONSE thô rồi trả về đây parse bằng `_extract_ads` sẵn có.

        Trả `None` = thợ vừa rớt giữa chừng → nơi gọi để playwright thử. Trả Outcome (kể cả rỗng
        kèm notice) = đã đi đường thợ, đừng đụng playwright nữa.
        """
        options: FacebookOptions = request.options
        try:
            result = await run_on_worker(
                "RS_FB_ADLIB",
                {
                    "keyword": request.keyword,
                    "country": request.country,
                    "activeStatus": options.active_status,
                    "searchType": SEARCH_TYPE[options.match_mode],
                    "maxPages": MAX_PAGES,
                },
                timeout_s=BATCH_TIMEOUT_S,
            )
        except WorkerOffline:
            return None
        except WorkerTimeout:
            return PlatformSearchOutcome(ads=[], notice="Máy-thợ FB không kịp trả (quá 90s).")

        # Thợ có nhận job nhưng không chạy xong (extension treo / hết giờ bên trang `/worker`).
        # Câu "chưa nạp job" bên dưới CHỈ đúng cho `None`, và nói nhầm nó ở đây là đẩy người ta đi
        # bấm Reload trong khi extension vẫn đang chạy tốt.
        if (why := worker_error(result)) is not None:
            return PlatformSearchOutcome(ads=[], notice=f"Máy-thợ không lấy được Facebook: {why}")

        if not isinstance(result, dict) or result.get("pages") is None:
            return PlatformSearchOutcome(
                ads=[],
                notice="Máy-thợ chưa nạp job Facebook — vào chrome://extensions bấm Reload rồi F5 tab Máy thợ.",
            )

        collected: list[Ad] = []
        seen: set[str] = set()
        pages = [text for text in (result.get("pages") or []) if isinstance(text, str)]
        raw_count = 0
        for text in pages:
            raw, _cursor = _extract_ads(text)
            raw_count += len(raw)
            for raw_ad in raw:
                ad = _normalise(raw_ad, request.country)
                if ad is None or ad.id in seen:
                    continue
                seen.add(ad.id)
                collected.append(ad)

        # RỖNG THÌ PHẢI NÓI RỖNG Ở ĐÂU. Ba nguyên nhân dưới đây trông giống hệt nhau từ ngoài
        # ("Facebook 0") mà phải đi sửa ba chỗ khác nhau:
        #
        #   0 trang            → tab máy-thợ không chộp được response GraphQL nào (FB chặn máy
        #                        đó, hoặc trang chưa kịp bắn query trước khi hết 45s)
        #   có trang, 0 raw    → chộp được nhưng trong đó không có `ad_archive_id` — FB trả lưới
        #                        rỗng cho cụm này, hoặc hình dạng response đã đổi
        #   có raw, 0 ad       → `_normalise` vứt hết (thiếu trường bắt buộc)
        #
        # Con số kèm theo là thứ phân biệt được chúng, và nó rẻ: chỉ là độ dài của thứ đã có.
        if not collected:
            chars = sum(len(t) for t in pages)
            note = (
                f"máy-thợ trả {len(pages)} trang ({chars:,} ký tự), đọc ra {raw_count} quảng cáo thô "
                f"→ 0 dùng được cho “{request.keyword}” {request.country}"
            )
            # `debug` chỉ có khi thợ không chộp được trang nào; nó nói tab đó đã ở tình trạng gì
            # (hook chạy chưa, trang có gọi /api/graphql không, có đúng trang Ad Library không).
            dbg = result.get("debug")
            if isinstance(dbg, dict):
                note += " · tab: " + ", ".join(f"{k}={v}" for k, v in dbg.items())
            return PlatformSearchOutcome(ads=[], notice=note)

        limit = request.limit
        if request.relax_keyword:
            return PlatformSearchOutcome(
                ads=collected[:limit],
                notice=f"Khớp ảnh: {len(collected)} ứng viên FB (máy-thợ) — để ảnh quyết định, không lọc chữ.",
            )
        return PlatformSearchOutcome(ads=collected[:limit])

    async def _search_via_page(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        """
        Đọc trang Ad Library bằng trình duyệt của CHÍNH server. Không máy-thợ, không extension,
        không truy vấn đã ký — xem ghi chú ở `_read_library_page`.
        """
        options: FacebookOptions = request.options
        url = _library_url(
            request.keyword,
            request.country,
            options.active_status,
            SEARCH_TYPE[options.match_mode],
        )
        pages, why = await _read_library_page(url, "vi-VN" if request.country == "VN" else "en-US")

        collected: list[Ad] = []
        seen: set[str] = set()
        raw_count = 0
        for text in pages:
            raw, _cursor = _extract_ads(text)
            raw_count += len(raw)
            for raw_ad in raw:
                ad = _normalise(raw_ad, request.country)
                if ad is None or ad.id in seen:
                    continue
                seen.add(ad.id)
                collected.append(ad)

        if not collected:
            # Cùng ba nhánh như đường máy-thợ, và cũng vì cùng lý do: "Facebook 0" không nói
            # được nó rỗng vì trang không mở nổi, vì hình dạng dữ liệu đổi, hay vì đúng là
            # không ai chạy quảng cáo cụm này.
            chars = sum(len(t) for t in pages)
            note = (
                f"đọc trang Ad Library: {len(pages)} khối JSON ({chars:,} ký tự), "
                f"{raw_count} quảng cáo thô → 0 dùng được cho “{request.keyword}” {request.country}"
            )
            return PlatformSearchOutcome(ads=[], notice=f"{note} · {why}" if why else note)

        limit = request.limit
        if request.relax_keyword:
            return PlatformSearchOutcome(
                ads=collected[:limit],
                notice=f"Khớp ảnh: {len(collected)} ứng viên FB — để ảnh quyết định, không lọc chữ.",
            )
        return PlatformSearchOutcome(ads=collected[:limit])

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        # BỌC NHÁY, và chỉ bọc ở đây — không đụng `params.keyword` ở tầng trên, vì cụm trần
        # còn được dùng cho cache key và cho `relevance.py` (cờ `phrase_hit` đi so cụm với chữ
        # trong quảng cáo; bọc nháy vào đó là đi tìm dấu nháy trong ad copy, không bao giờ khớp).
        #
        # Nói thẳng: đo 2026-09-08 thì Facebook BỎ QUA dấu nháy — `massage gun` và
        # `"massage gun"` đều ra đúng 1.522 kết quả, `tai nghe bluetooth` đều ra 890, cụm dài
        # đều ra 1. Độ chặt của phép khớp do `search_type` quyết định, không do dấu nháy.
        # Giữ nháy ở đây là theo yêu cầu của chủ dự án; nó vô hại theo số đo hiện tại, và nhánh
        # thử-lại bên dưới là cái chặn nếu một ngày Facebook đổi ý và coi nháy là ký tự thường.
        if not (request.keyword.startswith('"') and request.keyword.endswith('"')):
            request = request_with(request, f'"{request.keyword.strip()}"')

        out = await self._search_qua_ba_duong(request)
        if out.ads:
            return out
        if (tran := _bo_nhay(request.keyword)) is not None:
            lai = await self._search_qua_ba_duong(request_with(request, tran))
            if lai.ads:
                return PlatformSearchOutcome(
                    ads=lai.ads,
                    notice=f'Bọc nháy không ra quảng cáo nào — đã tìm lại bằng cụm trần "{tran}".',
                )
        return out

    async def _search_qua_ba_duong(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        keyword, country, limit = request.keyword, request.country, request.limit
        options: FacebookOptions = request.options

        # THỨ TỰ ĐÃ ĐẢO, 2026-09-08. Trước đây máy-thợ đi trước vì tin rằng playwright bị FB
        # soft-block. Đo lại thì ngược: đọc TRANG Ad Library bằng trình duyệt của server ra
        # 23–30 quảng cáo ngay trên VPS, còn máy-thợ trả 0 cho mọi từ khoá (nó đợi
        # `/api/graphql` mà trang không còn gọi). Xem `_read_library_page`.
        #
        # Máy-thợ vẫn giữ làm lưới đỡ: nó chạy Chrome ở IP dân cư, nên khi IP server bị FB
        # đưa vào diện captcha thì nó là đường duy nhất còn lại.
        page_out = await self._search_via_page(request)
        if page_out.ads:
            return page_out

        if worker_online():
            out = await self._search_via_worker(request)
            if out is not None and out.ads:
                return out

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

        # ĐƯỜNG THỨ BA: nhặt POST `AdLibrarySearchPaginationQuery` đã ký rồi phát lại. Đây là
        # đường CŨ, và nó vẫn ở đây vì nó là đường duy nhất PHÂN TRANG được (`end_cursor`) —
        # trang nhúng chỉ cho đúng 30 quảng cáo. Nó đứng cuối vì Facebook soft-block việc phát
        # lại: HTTP 200 kèm 0 kết quả, không báo lỗi gì.
        #
        # Nuốt lỗi ở đây là CÓ CHỦ Ý: để nó ném lên thì thông báo cuối cùng người dùng đọc
        # được sẽ là "Facebook GraphQL trả về HTTP 4xx" của đường phụ, che mất chẩn đoán của
        # đường chính (`page_out.notice`) — thứ nói đúng chỗ cần đi sửa.
        try:
            replay = await schedule(f"{PLATFORM_ID}:{country}", MIN_INTERVAL_MS, run)
        except Exception:
            replay = PlatformSearchOutcome(ads=[])
        return replay if replay.ads else page_out


facebook = Facebook()
