"""
NGUỒN: YouTube — tìm VIDEO qua API chính thức (YouTube Data API v3).

Vì sao là nguồn video đầu tiên của luồng "ảnh sản phẩm → video sống": YouTube là nền tảng
video DUY NHẤT có API keyword-search chính thức, MIỄN PHÍ (10.000 quota/ngày ~ 100 lần
search), và trả về **URL video THẬT** — khác hẳn grounding LLM (bịa URL). Đây là nguồn để
chứng minh cả pipeline cho ra link bấm-được-thật trước khi mở sang TikTok/Douyin (phải scrape).

Giống Etsy: có API chính thức nên đi thẳng server-fetch, không cần extension/login user.
Khác Etsy: đây là VIDEO nên `capabilities.video_ads=True` và creative có `kind="video"`.

Mô hình 2 lần gọi (như Etsy):
  1. search.list  → id video + snippet (tiêu đề, kênh, thumbnail)
  2. videos.list  → statistics (view/like) + contentDetails (thời lượng) cho đúng các id đó

YouTube KHÔNG trả link file mp4 trực tiếp — không có `Creative.url` (CDN). Ta để `url=None`,
đặt `poster_url` = thumbnail (đủ để `clipmatch`/`imagematch` so ảnh) và `permalink` = trang
watch (link người dùng bấm vào xem). `video_only` lọc theo `kind=="video"` nên vẫn qua.
"""

from __future__ import annotations

from urllib.parse import quote

from lib.core.config import env_string
from lib.core.http import get_json

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

PLATFORM_ID = "youtube"
BASE = "https://www.googleapis.com/youtube/v3"

_API_KEY = env_string("YOUTUBE_API_KEY")

#: `order` của YouTube search. 'relevance' = liên quan (mặc định tốt cho research);
#: 'viewCount' để lấy video nhiều view nhất; 'date' cho mới nhất.
ORDER = {"relevance": "relevance", "popular": "viewCount", "latest": "date"}

#: search.list trả tối đa 50 item mỗi trang; xin lớn hơn bị cắt về 50.
MAX_RESULTS = 50

NO_KEY_NOTE = (
    "YouTube chưa cấu hình API key. Khai YOUTUBE_API_KEY trong backend/.env.local "
    "(lấy free tại console.cloud.google.com → bật YouTube Data API v3 → tạo API Key)."
)


def _thumb(snippet: dict) -> str | None:
    """Ảnh đại diện video, ưu tiên độ phân giải cao (để so khớp ảnh chính xác hơn)."""
    thumbs = snippet.get("thumbnails")
    if not isinstance(thumbs, dict):
        return None
    for size in ("high", "medium", "default"):
        t = thumbs.get(size)
        if isinstance(t, dict) and isinstance(t.get("url"), str):
            return t["url"]
    return None


def _parse_duration(iso: object) -> float | None:
    """ISO-8601 (vd 'PT1M30S') → giây. Trả None nếu không đọc được (video vẫn hợp lệ)."""
    if not isinstance(iso, str) or not iso.startswith("PT"):
        return None
    num = ""
    total = 0.0
    for ch in iso[2:]:
        if ch.isdigit():
            num += ch
        elif ch in "HMS" and num:
            total += int(num) * {"H": 3600, "M": 60, "S": 1}[ch]
            num = ""
    return total or None


def _int(*values: object) -> int | None:
    """YouTube trả số dạng chuỗi ('12345') trong statistics — ép về int an toàn."""
    for v in values:
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


class YouTube(AdPlatform):
    id = PLATFORM_ID
    label = "YouTube"
    #: `keyword_search` theo sự thật: có key thì search được, không key thì tắt (không ảnh hưởng
    #: nguồn khác). `video_ads=True` để giao diện biết đây là nguồn có VIDEO cho luồng theo-ảnh.
    capabilities = PlatformCapabilities(
        keyword_search=bool(_API_KEY),
        start_date=False,
        remote_filters=False,
        client_fetch=False,
        video_ads=True,
    )
    #: Một nền tảng toàn cầu — không tách domain theo nước. `regionCode` chỉ để ưu tiên kết quả
    #: bản địa, không chặn nước nào, nên `countries=None`.
    countries = None
    options = [
        PlatformOption(
            key="order",
            label="Sắp xếp",
            hint="“Liên quan” hợp research; “Nhiều view” lấy video hot; “Mới nhất” cho trend gần đây.",
            kind="choice",
            default_value="relevance",
            choices=[
                PlatformChoice(value="relevance", label="Liên quan"),
                PlatformChoice(value="popular", label="Nhiều view"),
                PlatformChoice(value="latest", label="Mới nhất"),
            ],
        ),
    ]
    #: Thumbnail YouTube nằm trên i.ytimg.com — khai để `/api/media` cho poster hiển thị/tải được.
    media = MediaPolicy(host_suffixes=["ytimg.com"], referer="https://www.youtube.com/")
    health_probe = HealthProbe(keyword="portable blender", country="US")

    def parse_options(self, raw: dict[str, str]) -> str:
        order = (raw.get("order") or "").strip()
        return order if order in ORDER else "relevance"

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        if not _API_KEY:
            return PlatformSearchOutcome(ads=[], notice=NO_KEY_NOTE)

        order = request.options if isinstance(request.options, str) else "relevance"
        limit = min(MAX_RESULTS, max(1, request.limit))
        keyword = request.keyword.strip()
        if not keyword:
            return PlatformSearchOutcome(ads=[], notice="YouTube cần từ khoá để tìm.")

        # regionCode chỉ nhận mã 2 ký tự hợp lệ; bỏ qua nếu không phải để tránh 400.
        region = request.country.strip().upper()
        region_param = f"&regionCode={region}" if len(region) == 2 and region.isalpha() else ""

        # --- Lần 1: search.list lấy id + snippet (chưa có view/like/thời lượng) ---
        search_url = (
            f"{BASE}/search?part=snippet&type=video&maxResults={limit}"
            f"&q={quote(keyword, safe='')}&order={ORDER[order]}{region_param}&key={_API_KEY}"
        )
        try:
            data = await get_json(search_url)
        except Exception as error:
            # 403 hay gặp nhất = key sai hoặc hết quota ngày. Nói thẳng để user biết đường sửa.
            return PlatformSearchOutcome(
                ads=[], notice=f"YouTube lỗi ({error}). Kiểm tra API key/quota."
            )

        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            return PlatformSearchOutcome(ads=[], notice=f'YouTube không có video cho "{keyword}".')

        order_ids: list[str] = []
        snippet_by_id: dict[str, dict] = {}
        for it in items:
            vid = (it.get("id") or {}).get("videoId") if isinstance(it, dict) else None
            snip = it.get("snippet") if isinstance(it, dict) else None
            if isinstance(vid, str) and isinstance(snip, dict):
                order_ids.append(vid)
                snippet_by_id[vid] = snip

        # --- Lần 2: videos.list lấy view/like + thời lượng cho đúng các id trên ---
        stats_by_id: dict[str, dict] = {}
        details_by_id: dict[str, dict] = {}
        if order_ids:
            try:
                detail = await get_json(
                    f"{BASE}/videos?part=statistics,contentDetails"
                    f"&id={','.join(order_ids)}&key={_API_KEY}"
                )
                for r in (detail.get("items") or []) if isinstance(detail, dict) else []:
                    rid = r.get("id")
                    if isinstance(rid, str):
                        if isinstance(r.get("statistics"), dict):
                            stats_by_id[rid] = r["statistics"]
                        if isinstance(r.get("contentDetails"), dict):
                            details_by_id[rid] = r["contentDetails"]
            except Exception:
                pass  # thiếu view/like vẫn trả được video; thà có link còn hơn rỗng

        ads: list[Ad] = []
        for vid in order_ids:
            snip = snippet_by_id[vid]
            stats = stats_by_id.get(vid, {})
            details = details_by_id.get(vid, {})
            title = snip.get("title") if isinstance(snip.get("title"), str) else ""
            channel = snip.get("channelTitle") if isinstance(snip.get("channelTitle"), str) else "YouTube"
            duration = _parse_duration(details.get("duration"))
            ads.append(
                Ad(
                    id=vid,
                    platform=PLATFORM_ID,
                    advertiser=channel,
                    body=title,
                    title=title,
                    permalink=f"https://www.youtube.com/watch?v={vid}",
                    creatives=[
                        Creative(kind="video", poster_url=_thumb(snip), duration_sec=duration)
                    ],
                    like_count=_int(stats.get("likeCount")),
                    countries=[request.country],
                )
            )

        return PlatformSearchOutcome(ads=ads)


youtube = YouTube()
