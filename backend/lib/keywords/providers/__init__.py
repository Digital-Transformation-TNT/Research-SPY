"""
SỔ ĐĂNG KÝ CÁC NGUỒN TỪ KHOÁ.

ĐÂY LÀ NƠI DUY NHẤT PHẢI SỬA KHI THÊM MỘT NGUỒN GỢI Ý MỚI.

Mọi nơi khác — query string, cache key, bảng xếp hạng, giao diện — đều đọc từ sổ đăng ký
này, nên nguồn mới tự động có mặt ở khắp nơi.
"""

from __future__ import annotations

from ..provider import KeywordProvider
from .ali1688 import ali1688
from .amazon import amazon
from .douyin import douyin
from .expand import DEPTH_CALLS, ExpansionOutcome, expand_with_provider
from .shopee import shopee
from .taobao import taobao
from .tiktok import tiktok
from .trends_related import trends_related

#: Nguồn Google Suggest cũ đã bị gỡ khỏi sổ đăng ký.
#:
#: Nó chỉ hoàn thiện tiền tố nên mọi thứ nó trả về đều bắt đầu bằng chính từ gốc, và nó
#: không có tín hiệu nhu cầu nào — thứ tự gợi ý chỉ phản ánh cách autocomplete hoàn thiện
#: chuỗi, không phản ánh có bao nhiêu người tìm. Google Trends trả lời đúng câu hỏi ấy và
#: còn với tới được vùng từ khoá mà autocomplete về cấu trúc không sinh ra nổi ("shop quần
#: áo nam", "áo sơ mi nam"), nên nó thay hẳn vai trò "nguồn Google".
#: Hai sàn thương mại điện tử đứng cạnh nhau và KHÔNG chồng lấn thị trường: Shopee phục vụ
#: Đông Nam Á, Amazon phục vụ phương Tây cộng Singapore và Nhật. Nhờ vậy mỗi thị trường luôn
#: có ít nhất một sàn để đối chiếu với Google Trends, và `agreement` — thành phần nặng nhất
#: của điểm số — không bị sụp về một nguồn duy nhất khi rời khỏi Việt Nam.
#: BA NGUỒN CUỐI PHỤC VỤ RIÊNG THỊ TRƯỜNG `CN`, và chúng cố ý không thay thế nhau. Đây là thị
#: trường duy nhất người dùng không BÁN vào mà ĐI NHẬP HÀNG từ đó, nên câu hỏi đặt ra ở đây
#: khác hẳn — và mỗi nguồn trả lời một vế:
#:
#:     Taobao   连衣裙女夏          người mua lẻ Trung Quốc gọi món này là gì
#:     1688     连衣裙定制          nhà cung cấp gọi nó là gì (chợ bán buôn, nơi đi nhập hàng)
#:     Douyin   连衣裙穿搭          người ta đang bàn luận gì quanh nó
#:
#: Ba góc nhìn độc lập chứ không phải ba phiếu của cùng một góc, nên `agreement` — thành phần
#: nặng nhất của điểm số (0,45) — mới có việc để làm ở `CN`. Trước khi có 1688 và Douyin, thị
#: trường này chỉ có Taobao nên phần điểm ấy luôn bằng không.
#:
#: Cả ba không bao giờ cùng bật với Shopee hay Amazon: `markets` của chúng chỉ có `CN`.
KEYWORD_PROVIDERS: dict[str, KeywordProvider] = {
    "trends": trends_related,
    "shopee": shopee,
    "amazon": amazon,
    "tiktok": tiktok,
    "taobao": taobao,
    "ali1688": ali1688,
    "douyin": douyin,
}

KEYWORD_SOURCE_IDS: list[str] = list(KEYWORD_PROVIDERS.keys())

#: Nguồn chấm chính, suy từ cờ `is_primary` của chính các provider.
#:
#: Một chỗ duy nhất nói ra điều này, thay vì chuỗi "trends" nằm rải rác ở phần xếp hạng và
#: phần giao diện. Không nguồn nào đặt cờ thì rơi về nguồn đầu tiên trong sổ đăng ký — đủ để
#: hệ thống chạy tiếp thay vì ném lỗi lúc import.
PRIMARY_SOURCE: str = next(
    (sid for sid, provider in KEYWORD_PROVIDERS.items() if provider.is_primary),
    KEYWORD_SOURCE_IDS[0],
)


def is_keyword_source(source_id: str) -> bool:
    return source_id in KEYWORD_PROVIDERS


#: Nhãn hiển thị theo id nguồn, dùng chung cho giao diện và các câu giải thích điểm số.
SOURCE_LABEL: dict[str, str] = {
    source_id: KEYWORD_PROVIDERS[source_id].label for source_id in KEYWORD_SOURCE_IDS
}
    
#: Câu mô tả điểm gốc của từng nguồn — xem `KeywordProvider.native_score_note`.
#:
#: Đi qua sổ đăng ký như `SOURCE_LABEL` để `rank.py` không phải import từng provider, và để
#: thêm một nguồn có điểm gốc vẫn chỉ phải sửa đúng file của nguồn đó.
NATIVE_SCORE_NOTE: dict[str, str] = {
    source_id: KEYWORD_PROVIDERS[source_id].native_score_note for source_id in KEYWORD_SOURCE_IDS
}

#: Mô tả rút gọn cho giao diện — không kèm hàm nên gửi được qua JSON.
#:
#: Khoá viết camelCase vì đây là đường đi thẳng ra JSON, không qua `CamelModel` như các model
#: khác của mục này.
KEYWORD_SOURCE_DESCRIPTORS = [
    {
        "id": source_id,
        "label": KEYWORD_PROVIDERS[source_id].label,
        "markets": KEYWORD_PROVIDERS[source_id].markets,
        "primary": KEYWORD_PROVIDERS[source_id].is_primary,
        "geoTargeted": KEYWORD_PROVIDERS[source_id].geo_targeted,
    }
    for source_id in KEYWORD_SOURCE_IDS
]

__all__ = [
    "DEPTH_CALLS",
    "ExpansionOutcome",
    "KEYWORD_PROVIDERS",
    "KEYWORD_SOURCE_DESCRIPTORS",
    "KEYWORD_SOURCE_IDS",
    "NATIVE_SCORE_NOTE",
    "PRIMARY_SOURCE",
    "SOURCE_LABEL",
    "expand_with_provider",
    "is_keyword_source",
]
