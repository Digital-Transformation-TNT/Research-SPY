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
    #: Riêng product search (Shopee…): điểm cầu (số bán) và chất lượng (rating). `None` với
    #: quảng cáo, để giao diện hiện đúng ngữ cảnh — sản phẩm không có CVR, quảng cáo không có cầu.
    demand_score: int | None = None
    quality_score: int | None = None
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
    #: Giá niêm yết. Có ở các sàn thương mại điện tử (Shopee/Amazon…), vắng ở ads-spy
    #: (Facebook/TikTok Creative Center) — nên để trống thay vì 0 khi nguồn không công bố.
    price: float | None = None
    #: Mã tiền tệ ISO-4217, ví dụ 'VND' | 'THB'. Đi kèm `price` để giao diện định dạng đúng.
    currency: str | None = None
    #: Số lượng đã bán (tổng luỹ kế) nếu sàn công bố. Tín hiệu nhu cầu trực tiếp nhất cho
    #: product search — mạnh hơn cả đời quảng cáo, vì là con số bán thật chứ không phải suy luận.
    sold_count: int | None = None
    #: Số bán trong ~30 ngày gần nhất. Quan trọng hơn tổng luỹ kế để đo "đang hot bây giờ":
    #: một sản phẩm bán 700/tháng đáng research hơn cái tổng 400k nhưng nhịp gần đây đã nguội.
    monthly_sold: int | None = None
    #: Điểm đánh giá trung bình (0-5) nếu sàn công bố.
    rating: float | None = None
    #: Số lượt đánh giá — quyết định độ tin của `rating` (rating cao mà 3 review thì chưa chắc).
    rating_count: int | None = None
    countries: list[CountryCode] = []
    platforms: list[str] | None = None
    #: Do `lib/ads/scoring.py` điền vào.
    score: AdScore | None = None
    #: Độ trùng ẢNH (0-100) khi quảng cáo này được lọc qua luồng "tìm video theo ảnh sản phẩm"
    #: (`lib/ads/imagematch.py`). 100 = poster y hệt ảnh sản phẩm nguồn. Vắng ở search thường.
    match_score: int | None = None
    #: Cụm từ khoá có xuất hiện trong phần chữ ĐỌC ĐƯỢC của quảng cáo không (tiêu đề, nội dung,
    #: CTA, tên nhà quảng cáo). Do `lib/ads/relevance.py` điền vào ở `search.py`.
    #:
    #: `False` KHÔNG có nghĩa là quảng cáo rác: cụm từ có thể nằm trong ảnh, hoặc Facebook khớp
    #: nó ở trang đích mà ta không đọc được. Nó chỉ được dùng để XẾP quảng cáo ấy xuống dưới và
    #: để giao diện ghi chú — không bao giờ để loại bỏ. Xem lập luận ở `relevance.py`.
    phrase_hit: bool | None = None


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
    #: True cho luồng khớp-ảnh (`/api/ads/match-image`): nguồn nới lọc từ khoá văn bản vì
    #: ẢNH (CLIP) mới là bộ lọc chính. Không đến từ query string — do route match-image tự bật.
    relax_keyword: bool = False


class PlatformStatus(CamelModel):
    platform: PlatformId
    ok: bool
    #: Số quảng cáo nguồn này trả về cho truy vấn hiện tại.
    count: int
    #: Có giá trị khi nguồn lỗi hoặc trả kết quả kém hơn yêu cầu — hiện lên giao diện thay
    #: cho một danh sách rỗng im lặng.
    message: str | None = None
    took_ms: int


# ---------------------------------------------------------------------------
# Fetch phía client (Cách A) — nguồn chạy bằng session đăng nhập của user
# ---------------------------------------------------------------------------
#
# Một số sàn (Shopee, TikTok Shop…) chặn 403 mọi người gọi ẩn danh từ server, nhưng lại trả
# dữ liệu bình thường cho chính trình duyệt user đã đăng nhập. Với các nguồn này, server chỉ
# *dựng* lệnh fetch (`RequestSpec`) rồi để extension chạy bằng cookie của user; raw trả về
# (`ClientResponse`) được gửi ngược lên server để `parse_response` chuẩn hoá. Cookie KHÔNG bao
# giờ rời trình duyệt user — đây là điểm khác cốt lõi so với "gửi cookie về server".


class RequestSpec(CamelModel):
    """Một lệnh fetch để extension thực thi bằng session đăng nhập của user."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = {}
    body: str | None = None
    #: Nhãn để `parse_response` ghép đúng response với spec đã gửi (ví dụ 'page-1').
    tag: str | None = None


class ClientResponse(CamelModel):
    """Kết quả của một `RequestSpec`, do extension trả về sau khi fetch."""

    tag: str | None = None
    status: int
    text: str


class ClientJob(CamelModel):
    """
    Việc server giao cho extension: chạy các spec này bằng session của user.

    Đi trong `AdSearchResult.pending`. Extension chạy xong sẽ nộp lại một `ClientSubmission`.
    """

    platform: PlatformId
    country: CountryCode
    requests: list[RequestSpec] = []


class ClientSubmission(CamelModel):
    """Extension nộp lại raw responses cho một cặp (nguồn, quốc gia)."""

    platform: PlatformId
    country: CountryCode
    responses: list[ClientResponse] = []


class AdSearchResult(CamelModel):
    ads: list[Ad]
    statuses: list[PlatformStatus]
    #: True khi kết quả lấy từ cache thay vì gọi mới.
    cached: bool
    #: Từ khoá THỰC SỰ đã dùng để search. Khi đầu vào là `title` (tiêu đề SP dài), đây là cụm
    #: Gemini rút ra — để giao diện hiện "đang tìm bằng từ khoá nào". `None` với search thường.
    keyword: str | None = None
    #: Việc cần extension chạy (Cách A). Rỗng khi mọi nguồn fetch phía server, hoặc khi nguồn
    #: client_fetch đã trúng cache và không phải gọi lại. Giao diện đọc danh sách này để biết
    #: có cần nhờ extension fetch tiếp rồi POST về `/api/ads/ingest` hay không.
    pending: list[ClientJob] = []
