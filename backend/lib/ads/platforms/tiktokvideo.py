"""
NGUỒN: video TikTok THẬT (không phải quảng cáo), tìm qua Bing Videos.

Toàn bộ phần máy móc nằm ở `lib/ads/bingvideo.py` — kể cả lý do vì sao phải đi vòng qua một
công cụ tìm kiếm thay vì hỏi thẳng tiktok.com. Ở đây chỉ còn ba thứ riêng của TikTok.

Đo 2026-09-08 ngay trên VPS, không đăng nhập, không máy-thợ:

    "tai nghe bluetooth"   35 video trang đầu, 77 sau trang hai, 112 sau trang ba
    "kem chống nắng"       17 video
    "massage gun" (US)     25 video

Không có `Creative.url` (file mp4) — TikTok không phát file trần cho người ngoài — nên giao
diện nhúng player theo `permalink`.

GIỚI HẠN: đây là CHỈ MỤC của Bing, không phải bảng xếp hạng TikTok. Video quá mới có thể chưa
được lập chỉ mục, nên nguồn này KHÔNG thay đường tìm thật trong tab TikTok của máy-thợ; nó là
đường chạy được ở MỌI máy, kể cả khi không có máy-thợ nào online.

CHỈ MỤC CŨ HƠN SÀN, nên phải lọc lại — đo 2026-09-10. Bing vẫn trả thẻ đầy đủ (tiêu đề, ảnh
bìa, lượt xem) cho video ĐÃ BỊ GỠ, và thẻ ấy nhìn không khác gì thẻ tốt; chỉ tới lúc bấm ▶ mới
hiện "Video currently unavailable" trong khung nhúng. Nhìn thấy tận mắt trên chính
`tntecom.com`: id `7653092931838037268` mà Bing trả về cho "tai nghe bluetooth" ra đúng màn
hình chết ấy.

oEmbed phân biệt được hai loại, và đó là lý do nó được dùng làm bộ lọc:

    video đã gỡ   `https://www.tiktok.com/oembed?url=…`  →  400 {"message":"Something went wrong"}
    video còn sống                                        →  200 kèm tiêu đề + tác giả
"""

from __future__ import annotations

from ..bingvideo import BingSite, tach_tiktok, tim_video
from ..platform import (
    AdPlatform,
    HealthProbe,
    MediaPolicy,
    PlatformCapabilities,
    PlatformOption,
    PlatformSearchInput,
    PlatformSearchOutcome,
)

PLATFORM_ID = "tiktokvideo"

_SITE = BingSite(
    platform_id=PLATFORM_ID,
    host="tiktok.com",
    doc_id=tach_tiktok,
    dung_link=lambda tác_giả, vid: f"https://www.tiktok.com/@{tác_giả}/video/{vid}",
    ten="TikTok",
    #: Lọc video đã chết trước khi trả về — xem `BingSite.oembed`.
    oembed="https://www.tiktok.com/oembed",
)


class TikTokVideo(AdPlatform):
    id = PLATFORM_ID
    label = "TikTok (video)"
    #: `start_date=False` là khai báo TRUNG THỰC, không phải thiếu sót: Bing có nói "1 tháng
    #: trước", nhưng đó là ngày ĐĂNG video, không phải ngày bắt đầu chạy quảng cáo. Khai bừa
    #: `True` sẽ khiến tầng chấm điểm coi tuổi của một clip review là "đời quảng cáo", tức là
    #: bịa ra một tín hiệu thị trường không tồn tại.
    capabilities = PlatformCapabilities(
        keyword_search=True,
        start_date=False,
        remote_filters=False,
        client_fetch=False,
        video_ads=True,
    )
    #: Bing lập chỉ mục TikTok toàn cầu; nước chỉ đổi thứ tự ưu tiên, không chặn thị trường nào.
    countries = None
    options: list[PlatformOption] = []
    #: Ảnh bìa do Bing phục vụ lại từ CDN của nó, không phải của TikTok.
    media = MediaPolicy(
        host_suffixes=["bing.net", "bing.com", "tiktokcdn.com", "tiktokcdn-us.com"],
        referer="https://www.bing.com/",
    )
    health_probe = HealthProbe(keyword="tai nghe", country="VN")

    def parse_options(self, raw: dict[str, str]) -> None:
        return None

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        return await tim_video(_SITE, request)


tiktokvideo = TikTokVideo()
