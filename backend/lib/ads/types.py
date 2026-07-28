"""
Từ vựng chung của MỤC QUẢNG CÁO.

Mọi nền tảng (Facebook, TikTok, và các nguồn thêm sau) đều ánh xạ dữ liệu thô của mình
về các kiểu ở đây, nhờ vậy tầng chấm điểm và giao diện không bao giờ phải rẽ nhánh theo
nguồn. Mục Từ khoá có từ vựng riêng ở `lib/keywords/types.py` và hai bên không dùng
chung kiểu nào.
"""

from __future__ import annotations

from typing import Literal

from lib.core.model import CamelModel

#: Mã quốc gia ISO-3166 alpha-2, ví dụ 'VN' | 'US' | 'PH'.
CountryCode = str

#: Id nguồn quảng cáo, do sổ đăng ký ở `lib/ads/platforms/__init__.py` quyết định.
PlatformId = str

MediaKind = Literal["video", "image", "none"]


class Creative(CamelModel):
    """Một creative xem/phát được thuộc về một quảng cáo."""

    kind: MediaKind
    #: Link CDN trực tiếp. Có chữ ký và hết hạn nhanh ở mọi nguồn — không bao giờ lưu lại.
    url: str | None = None
    poster_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None


class AdScore(CamelModel):
    """
    Kết quả chấm điểm.

    `cvr_proxy` KHÔNG phải tỷ lệ chuyển đổi. Không nền tảng nào công bố CVR — đó là dữ liệu
    riêng của advertiser. Đây là chỉ số 0-100 suy ra từ độ dài đời quảng cáo, mức độ lặp
    creative và tương tác; giao diện luôn phải ghi rõ đây là ước lượng.
    """

    total: int
    cvr_proxy: int
    content_score: int
    longevity_score: int
    #: Lý do đọc được, hiện trên giao diện để người dùng tự kiểm chứng con số.
    reasons: list[str]
    #: Điểm dựa trên bao nhiêu dữ liệu thật so với bao nhiêu trường bị thiếu.
    confidence: Literal["high", "medium", "low"]


class Ad(CamelModel):
    """Bản ghi quảng cáo đã chuẩn hoá."""

    id: str
    platform: PlatformId
    #: Tên advertiser / brand đúng như nền tảng hiển thị.
    advertiser: str
    #: Nội dung quảng cáo chính. TikTok chỉ công bố caption.
    body: str
    title: str | None = None
    cta_text: str | None = None
    landing_url: str | None = None
    #: Link về đúng quảng cáo đó trên nền tảng gốc, để kiểm chứng bằng tay.
    permalink: str | None = None
    creatives: list[Creative] = []
    #: Unix giây. Facebook có công bố; TikTok thì không.
    started_at: int | None = None
    ended_at: int | None = None
    #: Số ngày quảng cáo đã chạy. Đây là chỉ báo gián tiếp tốt nhất cho "sản phẩm này thật sự
    #: bán được" — không ai trả tiền tiếp cho quảng cáo đang lỗ. Bỏ trống với những nền tảng
    #: không công bố ngày bắt đầu (xem `capabilities.start_date`).
    days_active: int | None = None
    is_active: bool | None = None
    #: Số biến thể creative trong cùng một nhóm. Nhiều = advertiser đang test/scale mạnh.
    variant_count: int | None = None
    #: Riêng Facebook.
    page_like_count: int | None = None
    #: Riêng TikTok: tỷ lệ click, theo Creative Center công bố.
    ctr_percent: float | None = None
    #: Riêng TikTok: lượt thích trên creative.
    like_count: int | None = None
    #: Riêng TikTok: chỉ số chi phí tương đối (không phải số tiền).
    cost_index: float | None = None
    industry: str | None = None
    objective: str | None = None
    countries: list[CountryCode] = []
    platforms: list[str] | None = None
    #: Do `lib/ads/scoring.py` điền vào.
    score: AdScore | None = None


class AdSearchParams(CamelModel):
    """Tham số tìm kiếm dùng chung cho mọi nền tảng."""

    keyword: str
    platforms: list[PlatformId]
    countries: list[CountryCode]
    #: Chỉ giữ quảng cáo có video phát được. Lọc sau khi lấy dữ liệu.
    video_only: bool = False
    #: Số ngày chạy tối thiểu. Loại luôn quảng cáo không có ngày bắt đầu khi > 0.
    #: Để `float` vì đây thuần tuý là một ngưỡng so sánh, và `Number()` của JS không cắt phần
    #: thập phân — `minDaysActive=30.7` phải loại quảng cáo chạy đúng 30 ngày, y như bản cũ.
    min_days_active: float = 0
    limit: int = 30
    #: Tuỳ chọn riêng của từng nền tảng, dạng thô từ query string.
    #: Ví dụ: `{'tiktok': {'period': '30'}, 'facebook': {'matchMode': 'exact'}}`.
    #: Mỗi nền tảng tự kiểm tra phần của mình — xem `AdPlatform.parse_options`.
    platform_options: dict[PlatformId, dict[str, str]] = {}


class PlatformStatus(CamelModel):
    platform: PlatformId
    ok: bool
    #: Số quảng cáo nguồn này trả về cho truy vấn hiện tại.
    count: int
    #: Có giá trị khi nguồn lỗi hoặc trả kết quả kém hơn yêu cầu — hiện lên giao diện thay
    #: cho một danh sách rỗng im lặng.
    message: str | None = None
    took_ms: int


class AdSearchResult(CamelModel):
    ads: list[Ad]
    statuses: list[PlatformStatus]
    #: True khi kết quả lấy từ cache thay vì gọi mới.
    cached: bool
