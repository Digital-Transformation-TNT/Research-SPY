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

import asyncio
import re
from typing import Any
from urllib.parse import quote

from lib.core.browser import browser_lane, describe_browser_error
from lib.core.config import env_string
from lib.core.http import get_json

from ..humancount import parse_count
from ..platform import request_with

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


# ---------------------------------------------------------------------------
# ĐƯỜNG KHÔNG CẦN API KEY — đọc thẳng trang kết quả YouTube
# ---------------------------------------------------------------------------
#
# VÌ SAO PHẢI CÓ. Không khai `YOUTUBE_API_KEY` thì nguồn này trả về đúng một câu hướng dẫn xin
# key, và cửa sổ video hiện "YouTube 0" — nghĩa là nguồn video ỔN ĐỊNH NHẤT trong cả tool
# (không đăng nhập, không chống bot, không cần máy-thợ) lại là nguồn duy nhất không bao giờ
# chạy. Người dùng không phân biệt được "chưa cấu hình" với "không có video".
#
# Trang kết quả nhúng sẵn `ytInitialData`, và mỗi lần cuộn tới đáy trang tự gọi
# `/youtubei/v1/search` cho trang tiếp — cùng hình dạng `videoRenderer`. Đo 2026-09-08 từ VPS,
# "tai nghe bluetooth review": 20 video ngay lần đầu, 79 sau bốn lượt cuộn, đủ tiêu đề / kênh /
# lượt xem / ngày đăng / ảnh bìa. Có key thì vẫn ưu tiên key (nhanh hơn, không tốn trình duyệt).

#: Bộ lọc "chỉ VIDEO" của YouTube (`sp=EgIQAQ%3D%3D`). Thiếu nó, kết quả lẫn kênh và playlist.
_ONLY_VIDEO = "EgIQAQ%3D%3D"

#: Gom `videoRenderer` từ CẢ HAI nguồn: `ytInitialData` (trang đầu) và các response cuộn mà
#: `__rsYt` giữ lại. Duyệt cây thay vì cố định đường dẫn — YouTube đổi lớp bọc luôn.
_COLLECT_JS = """() => {
  const out = [], seen = new Set();
  const runs = (x) => (x && (x.simpleText || (x.runs && x.runs.map(r => r.text).join('')))) || '';
  const push = (v) => {
    if (!v || !v.videoId || seen.has(v.videoId)) return;
    seen.add(v.videoId);
    out.push({
      id: v.videoId,
      title: runs(v.title),
      channel: runs(v.ownerText) || runs(v.longBylineText) || runs(v.shortBylineText),
      views: runs(v.viewCountText),
      published: runs(v.publishedTimeText),
      length: runs(v.lengthText),
      thumb: (v.thumbnail && v.thumbnail.thumbnails && v.thumbnail.thumbnails.slice(-1)[0].url) || '',
    });
  };
  const walk = (n, d) => {
    if (d > 30 || !n) return;
    if (Array.isArray(n)) { for (const x of n) walk(x, d + 1); return; }
    if (typeof n !== 'object') return;
    if (n.videoRenderer) push(n.videoRenderer);
    for (const k in n) walk(n[k], d + 1);
  };
  walk(window.__rsYt || [], 0);
  walk(window.ytInitialData, 0);
  return out;
}"""

#: Mỗi lượt cuộn = một trang ~20 video. Trần 8 để một lượt tìm không kéo dài quá nửa phút.
_MAX_SCROLL = 8

#: Trần số video, ĐỘC LẬP với số nơi gọi xin.
#:
#: `search.py` xin dư 2,5× vì bộ lọc hậu kỳ sẽ vứt bớt — nhưng ở nguồn này KHÔNG có gì để vứt:
#: mọi kết quả đều là video, nên `videoOnly` không loại cái nào. Xin 60 thành đi lấy 150, và
#: cuộn thêm cho 90 cái không bao giờ lên màn hình: cửa sổ video luân phiên theo nguồn nên
#: YouTube chỉ chiếm được ~1/3 số ô.
#:
#: Đo 2026-09-08, cùng truy vấn:  150 video → 30,5 s   ·   80 video → 19,3 s
_MAX_ITEMS = 80


#: Nhịp hỏi lại sau mỗi lượt cuộn, và trần chờ cho MỘT lượt.
_POLL_MS = 400
_CHO_TRANG_MS = 7_000


async def _cho_trang_moi(page: Any, đã_có: int) -> int:
    """
    Cuộn xuống rồi CHỜ TỚI KHI có thêm video, tối đa `_CHO_TRANG_MS`. Trả về số video mới nhất.

    Thay cho một `wait_for_timeout` cố định, và không phải để cho đẹp: khi máy đang bận (ba
    nguồn video chạy song song, mỗi nguồn một trình duyệt) thì response trang tiếp về chậm hơn
    mốc chờ cứng, vòng lặp đọc ra "không tăng" rồi dừng. Đo 2026-09-08 trong lượt bắn 4 request
    cùng lúc: YouTube trả 7 video, trong khi chạy riêng cùng truy vấn ấy ra 20-40.

    Hỏi lại mỗi 400 ms nên lúc rảnh nó vẫn nhanh y như cũ — chỉ lúc bận mới chờ lâu hơn.
    """
    await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    hạn = _CHO_TRANG_MS
    while hạn > 0:
        await page.wait_for_timeout(_POLL_MS)
        hạn -= _POLL_MS
        bây_giờ = len(await page.evaluate(_COLLECT_JS))
        if bây_giờ > đã_có:
            return bây_giờ
    return đã_có


async def _collect(page: Any, limit: int) -> list[dict]:
    items = await page.evaluate(_COLLECT_JS)
    đứng_yên = 0
    for _ in range(_MAX_SCROLL):
        if len(items) >= limit:
            break
        if await _cho_trang_moi(page, len(items)) > len(items):
            items = await page.evaluate(_COLLECT_JS)
            đứng_yên = 0
            continue
        # KHÔNG bỏ cuộc ngay ở lượt đầu không tăng. Đo 2026-09-08: lượt cuộn thứ nhất thường
        # chưa kịp kéo trang tiếp (20 → 20), lượt thứ hai mới nhảy lên 40. Cắt sau một lượt
        # đứng yên nghĩa là luôn dừng ở đúng 20 video, bất kể xin bao nhiêu.
        đứng_yên += 1
        if đứng_yên >= 2:
            break
    return items


async def _scrape_search(request: PlatformSearchInput) -> PlatformSearchOutcome:
    keyword = request.keyword.strip()
    if not keyword:
        return PlatformSearchOutcome(ads=[], notice="YouTube cần từ khoá để tìm.")

    region = request.country.strip().upper()
    hl = "vi" if region == "VN" else "en"
    url = (
        f"https://www.youtube.com/results?search_query={quote(keyword, safe='')}"
        f"&sp={_ONLY_VIDEO}&hl={hl}&gl={region if len(region) == 2 and region.isalpha() else 'US'}"
    )

    try:
        async with browser_lane() as browser:
            context = await browser.new_context(locale="vi-VN" if region == "VN" else "en-US")
            page = await context.new_page()
            # Giữ response của các trang cuộn NGAY TRONG TRANG: `_COLLECT_JS` duyệt một cây duy
            # nhất, nên trang đầu và trang cuộn đi qua đúng một bộ luật bóc tách.
            await page.add_init_script("window.__rsYt = [];")

            async def giữ(response: Any) -> None:
                if "/youtubei/v1/search" not in response.url:
                    return
                try:
                    await page.evaluate("d => window.__rsYt.push(d)", await response.json())
                except Exception:
                    pass  # response hỏng/đóng sớm — trang đầu vẫn dùng được

            page.on("response", lambda r: asyncio.ensure_future(giữ(r)))

            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_function("() => window.ytInitialData", timeout=20_000)
            items = await _collect(page, min(request.limit, _MAX_ITEMS))
    except Exception as error:
        return PlatformSearchOutcome(
            ads=[], notice=f"YouTube đọc trang hỏng: {describe_browser_error(error)}"
        )

    if not items:
        return PlatformSearchOutcome(ads=[], notice=f'YouTube không có video cho "{keyword}".')

    ads = [
        Ad(
            id=it["id"],
            platform=PLATFORM_ID,
            advertiser=it.get("channel") or "YouTube",
            body=it.get("title") or "",
            title=it.get("title") or None,
            permalink=f"https://www.youtube.com/watch?v={it['id']}",
            creatives=[Creative(kind="video", poster_url=it.get("thumb") or None)],
            play_count=parse_count(it.get("views") or ""),
            countries=[request.country],
        )
        for it in items[: request.limit]
        if isinstance(it, dict) and isinstance(it.get("id"), str)
    ]
    return PlatformSearchOutcome(ads=ads)


class YouTube(AdPlatform):
    id = PLATFORM_ID
    label = "YouTube"
    #: `keyword_search=True` KHÔNG điều kiện: không có API key thì vẫn ĐỌC TRANG kết quả
    #: (`_scrape_search`), nên năng lực này không còn phụ thuộc vào env. `video_ads=True` để giao
    #: diện biết đây là nguồn có VIDEO cho luồng theo-ảnh.
    capabilities = PlatformCapabilities(
        keyword_search=True,
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
        out = await self._search_one(request)
        if out.ads:
            return out
        # Cụm bọc nháy không ra gì → thử lại cụm trần. Xem `_bo_nhay`.
        if (tran := _bo_nhay(request.keyword)) is not None:
            lai = await self._search_one(request_with(request, tran))
            if lai.ads:
                return PlatformSearchOutcome(
                    ads=lai.ads,
                    notice=f'Không có video khớp đúng cụm — nới ra "{tran}".',
                )
        return out

    async def _search_one(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        if not _API_KEY:
            return await _scrape_search(request)

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
