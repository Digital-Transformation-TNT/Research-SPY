"""
HỢP ĐỒNG CHUNG CHO MỘT NGUỒN QUẢNG CÁO.

Đây là file cần đọc trước khi thêm Facebook/TikTok/Shopee Ads/Google Ads… hay bất kỳ
nguồn nào khác. Một nguồn mới chỉ cần:

  1. tạo `lib/ads/platforms/<tên>.py` với một lớp kế thừa `AdPlatform`
  2. thêm đúng một dòng vào `lib/ads/platforms/__init__.py`

Không phải sửa route, không phải sửa giao diện, không phải sửa file cấu hình dùng chung.
Mọi thứ đặc thù của nguồn — cách ký request, giới hạn tần suất, bộ lọc riêng, thông báo
khi kết quả bị suy giảm — đều nằm gọn trong file của nguồn đó.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from lib.core.model import CamelModel

from .types import Ad, ClientResponse, CountryCode, RequestSpec


class PlatformCapabilities(CamelModel):
    """
    Những gì nguồn này *thật sự* làm được.

    Khai báo trung thực ở đây quan trọng hơn vẻ đẹp của API: giao diện dựa vào nó để không
    hứa với người dùng những thứ nguồn không có. Ví dụ TikTok Creative Center không search
    được theo từ khoá với phiên ẩn danh, và không công bố ngày bắt đầu chạy quảng cáo.
    """

    #: Có search được theo từ khoá thật sự không.
    keyword_search: bool
    #: Có công bố ngày bắt đầu chạy không — quyết định điểm "đời quảng cáo" có tính được không.
    start_date: bool
    #: Có bộ lọc động lấy từ nguồn (ngành hàng, mục tiêu…) không.
    remote_filters: bool
    #: Nguồn này fetch phía CLIENT hay không (Cách A).
    #:
    #: True  → server chỉ dựng lệnh (`build_request`), extension fetch bằng session user, rồi
    #:         server chuẩn hoá raw qua `parse_response`. Dùng cho sàn chặn 403 người ẩn danh
    #:         (Shopee, TikTok Shop…). Server KHÔNG bao giờ chạm cookie của user.
    #: False → server tự fetch trong `search()` như Facebook/TikTok Creative Center hiện tại.
    #:
    #: Giao diện đọc cờ này để biết khi nào cần extension; `search.py` đọc để định tuyến 2 pha.
    client_fetch: bool = False
    #: Nguồn này có trả về VIDEO quảng cáo (creative video) hay không.
    #:
    #: Giao diện đọc cờ này để biết sàn nào cần hỏi khi người dùng bấm "tìm video quảng cáo cho
    #: sản phẩm này" từ một item trong list: chỉ các nguồn ads-spy (Facebook Ads Library, TikTok
    #: Creative Center) mới có video quảng cáo, còn các sàn TMĐT (Shopee, Etsy) là sản phẩm ảnh.
    #: Khai ở đây thay vì hard-code tên nguồn ở giao diện, để thêm nguồn video mới là nó tự có mặt.
    video_ads: bool = False


class PlatformChoice(CamelModel):
    value: str
    label: str
    hint: str | None = None


class PlatformOption(CamelModel):
    """
    Một tuỳ chọn riêng của nguồn, để giao diện tự dựng ô điều khiển mà không cần biết nguồn
    đó là gì.

     - `choices`: danh sách cố định, biết trước khi chạy (ví dụ khoảng thời gian 7/30/180)
     - `remote_group`: danh sách lấy động qua `/api/ads/filters` (ví dụ 258 ngành hàng TikTok)
    """

    key: str
    label: str
    hint: str | None = None
    kind: str  # 'choice' | 'remote'
    choices: list[PlatformChoice] | None = None
    remote_group: str | None = None
    default_value: str | None = None


class FilterOption(CamelModel):
    value: str
    label: str
    group: str | None = None


class FilterGroup(CamelModel):
    """Một nhóm bộ lọc lấy động từ nguồn, đã được nguồn gom nhóm sẵn cho giao diện."""

    key: str
    label: str
    options: list[FilterOption]


@dataclass
class PlatformSearchInput:
    keyword: str
    country: CountryCode
    limit: int
    #: Kết quả của `parse_options` của chính nguồn đó — mỗi nguồn có hình dạng riêng.
    options: Any
    #: True khi đang chạy luồng KHỚP-ẢNH (`/api/ads/match-image`): ẢNH là bộ lọc chính, nên
    #: nguồn nên NỚI lọc từ khoá văn bản — đừng vứt ứng viên mà CLIP đáng lẽ khớp được
    #: (advertiser hiếm khi viết đúng tên sản phẩm trong ad copy). Mặc định False cho search thường.
    relax_keyword: bool = False


@dataclass
class PlatformSearchOutcome:
    ads: list[Ad] = field(default_factory=list)
    #: Có giá trị khi kết quả rộng hơn hoặc khác với điều người dùng yêu cầu, để giao diện
    #: nói rõ lý do. Một danh sách rỗng im lặng là kiểu hỏng nguy hiểm nhất của công cụ này:
    #: nó đọc thành "sản phẩm không có nhu cầu".
    notice: str | None = None


@dataclass
class MediaPolicy:
    """
    CDN media của một nguồn.

    `/api/media` dựng danh sách host được phép từ đây thay vì giữ một danh sách cứng, nên
    thêm nguồn mới là video của nó phát được ngay. Danh sách này mang tính bảo mật: thiếu
    nó, route media sẽ thành một open proxy trỏ được tới host bất kỳ.
    """

    #: Hậu tố tên miền được phép, ví dụ 'fbcdn.net'. Khớp cả chính nó và các miền con.
    host_suffixes: list[str]
    #: Referer cần gửi kèm, vì CDN của các nền tảng đều chặn hotlink.
    referer: str


@dataclass
class HealthProbe:
    """Truy vấn rẻ tiền để `/api/ads/health` chứng minh nguồn vẫn còn trả lời."""

    keyword: str
    country: CountryCode


class AdPlatform(ABC):
    #: Định danh dùng trong URL, cache key và query string. Không đổi sau khi đã dùng.
    id: str
    #: Tên hiển thị trên giao diện.
    label: str
    capabilities: PlatformCapabilities
    #: Các thị trường nguồn này phục vụ. `None` nghĩa là mọi thị trường.
    #:
    #: Gương với `KeywordProvider.markets` ở mục Từ khoá. Thiếu trường này, giao diện không có
    #: cách nào biết nguồn nào phủ nước nào, nên nó phải giữ một danh sách quốc gia cứng và
    #: người dùng chọn phải một nước nguồn không phục vụ sẽ nhận về một lưới rỗng không lời
    #: giải thích — đúng kiểu hỏng mà `PlatformSearchOutcome.notice` sinh ra để chống.
    countries: list[CountryCode] | None = None
    #: Các tuỳ chọn riêng, giao diện tự dựng ô điều khiển từ danh sách này.
    options: list[PlatformOption]
    health_probe: HealthProbe
    media: MediaPolicy | None = None

    @abstractmethod
    def parse_options(self, raw: dict[str, str]) -> Any:
        """Kiểm tra và chuẩn hoá tham số thô từ query string thành options của nguồn."""

    # Mỗi nguồn hiện thực ĐÚNG MỘT trong hai đường bên dưới, khớp với `capabilities.client_fetch`:
    #
    #   client_fetch=False → `search()`                      (server tự fetch)
    #   client_fetch=True  → `build_request()` + `parse_response()`  (extension fetch, Cách A)
    #
    # Để mặc định báo lỗi rõ ràng thay vì `abstractmethod` — nhờ vậy nguồn client không bị ép
    # viết một `search()` giả, và nguồn server không bị ép viết `build_request()` giả.

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        """Truy vấn chính cho nguồn fetch phía server (`client_fetch=False`)."""
        raise NotImplementedError(
            f"{self.id} không hiện thực search() — nguồn client_fetch dùng build_request()/parse_response()"
        )

    def build_request(self, request: PlatformSearchInput) -> list[RequestSpec]:
        """
        Dựng các lệnh fetch để extension chạy bằng session user (`client_fetch=True`).

        KHÔNG gọi mạng và KHÔNG chạm cookie — chỉ trả về "cần gọi URL nào, header gì". Extension
        thực thi trong trình duyệt user rồi nộp raw về `parse_response`.
        """
        raise NotImplementedError(f"{self.id} không phải nguồn client_fetch")

    def parse_response(
        self, request: PlatformSearchInput, responses: list[ClientResponse]
    ) -> PlatformSearchOutcome:
        """
        Chuẩn hoá raw mà extension nộp về thành danh sách `Ad` (`client_fetch=True`).

        Chạy phía server nên tái dùng được toàn bộ tầng chấm điểm/gộp/cache — chỉ đúng cú
        `fetch` là nằm ở trình duyệt user.
        """
        raise NotImplementedError(f"{self.id} không phải nguồn client_fetch")

    #: Bộ lọc động cho giao diện. Chỉ cần ghi đè khi `capabilities.remote_filters` là True.
    supports_filters: bool = False

    async def fetch_filters(self, country: CountryCode) -> list[FilterGroup]:
        raise NotImplementedError(f"{self.id} không có bộ lọc động")
