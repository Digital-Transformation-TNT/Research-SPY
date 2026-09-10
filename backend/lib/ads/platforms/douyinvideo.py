"""
NGUỒN: video Douyin (抖音), tìm qua Bing Videos.

Cùng máy với `tiktokvideo` — xem `lib/ads/bingvideo.py`. Ở đây chỉ có phần riêng của Douyin, và
phần riêng ấy nhiều hơn TikTok đúng hai chỗ, cả hai đều từng làm nguồn này trả rỗng:

1. PHẢI HỎI BẰNG TIẾNG TRUNG. Douyin gần như không có nội dung tiếng Việt. Đo 2026-09-08:
   `site:douyin.com tai nghe bluetooth` → Bing trả toàn kết quả YouTube, 0 link Douyin;
   `site:douyin.com 蓝牙耳机`            → 20 thẻ, đủ tiêu đề / tài khoản / ảnh bìa.
   Cụm tiếng Trung do `extract_video_terms(title, "CN")` dịch — xem `_video_keywords`
   trong `app/api/ads.py`.

2. PHẢI ÉP THỊ TRƯỜNG `zh-CN`. Bing chọn chỉ mục theo `mkt`; để `vi-VN` thì nó tìm trong chỉ
   mục Việt Nam, nơi gần như không có trang douyin.com nào. Nên `mkt_ep` bỏ qua nước người
   dùng chọn — Douyin là sàn nội địa Trung Quốc, chọn nước ở đây không có nghĩa gì.

Link Douyin KHÔNG mang tên tài khoản (`douyin.com/video/<id>`), nên `advertiser` lấy từ tên
kênh Bing hiển thị trên thẻ.

CÓ player nhúng công khai, đã xem tận mắt 2026-09-10: `open.douyin.com/player/video?vid=<id>`
nhận thẳng `aweme_id` mình đang có, không có `X-Frame-Options` cũng không có `frame-ancestors`,
và nhúng trong chính `tntecom.com` thì 8/8 video của lượt đo phát ra hình thật. Ghi chú cũ
("Douyin không mở player cho người ngoài") đã hết đúng — xem `research.js::vidEmbed`.

KHÔNG LỌC ĐƯỢC VIDEO CHẾT Ở SERVER, khác TikTok. Đây là ngõ cụt đã đo, chép lại để không ai đi
lại — cả ba đường đều không phân biệt nổi id thật với id bịa:

    open.douyin.com/player/video?vid=…   ❌ vỏ SPA, trả 200 và ĐÚNG 45.620 byte cho cả id thật
                                            lẫn id bịa; video được nạp bằng JS ở phía trình duyệt
    iesdouyin.com/share/video/<id>/      ❌ luôn 302 về douyin.com/video/<id>, không tra gì cả
    /aweme/v1/web/aweme/detail/          ❌ 200 kèm thân RỖNG (đòi chữ ký, chặn người gọi ngoài)

Nên nguồn này KHÔNG khai `oembed`. Chấp nhận được vì phép đo cùng ngày cho thấy 8/8 video Bing
trả về đều còn sống — chỉ mục Douyin của Bing mới hơn hẳn chỉ mục TikTok. Nếu sau này thấy thẻ
Douyin chết, thứ cần tìm là một điểm tra CÔNG KHAI, đừng quay lại ba đường trên.
"""

from __future__ import annotations

from ..bingvideo import BingSite, tach_douyin, tim_video
from ..platform import (
    AdPlatform,
    HealthProbe,
    MediaPolicy,
    PlatformCapabilities,
    PlatformOption,
    PlatformSearchInput,
    PlatformSearchOutcome,
)

PLATFORM_ID = "douyinvideo"

_SITE = BingSite(
    platform_id=PLATFORM_ID,
    host="douyin.com",
    doc_id=tach_douyin,
    dung_link=lambda _tác_giả, vid: f"https://www.douyin.com/video/{vid}",
    ten="Douyin",
    mkt_ep=("zh-CN", "zh-hans"),
)


class DouyinVideo(AdPlatform):
    id = PLATFORM_ID
    label = "Douyin (video)"
    capabilities = PlatformCapabilities(
        keyword_search=True,
        start_date=False,
        remote_filters=False,
        client_fetch=False,
        video_ads=True,
    )
    #: `None` chứ không phải `["CN"]`: nguồn này luôn hỏi chỉ mục Trung Quốc bất kể người dùng
    #: chọn nước nào, nên chặn theo nước ở giao diện sẽ nói sai về thứ nó làm.
    countries = None
    options: list[PlatformOption] = []
    media = MediaPolicy(
        host_suffixes=["bing.net", "bing.com", "douyinpic.com", "douyinstatic.com"],
        referer="https://www.bing.com/",
    )
    health_probe = HealthProbe(keyword="蓝牙耳机", country="CN")

    def parse_options(self, raw: dict[str, str]) -> None:
        return None

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        return await tim_video(_SITE, request)


douyinvideo = DouyinVideo()
