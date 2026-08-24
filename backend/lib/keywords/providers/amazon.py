"""
NGUỒN TỪ KHOÁ: Amazon autocomplete.

Tồn tại để lấp đúng một lỗ hổng: Shopee chỉ chạy ở Đông Nam Á, nên với thị trường Mỹ và Anh
bảng xếp hạng chỉ còn Google Trends và TikTok. Mà `agreement` — thành phần nặng nhất trong
điểm số (0,45) — đo mức độ NHIỀU NGUỒN ĐỘC LẬP cùng nêu ra một chữ bổ nghĩa, nên hai nguồn
là biên dưới của việc "đối chiếu chéo" còn có nghĩa. Amazon trả lại vai trò mà Shopee đang
đóng ở Việt Nam: một sàn thương mại điện tử nói tiếng bản địa, nơi người gõ vào ô tìm kiếm
là người đang định mua.

Đo ngày 2026-08-04, cùng từ gốc "jeans" trên ba thị trường:

    US  → jeans for women, baggy jeans, wrangler jeans for men
    GB  → mens jeans, jeans for men uk
    DE  → jeans damen, jeans herren, jeans shorts damen

Ba tập khác hẳn nhau, và cụm "jeans for men uk" là thứ không bộ dịch nào nghĩ ra hộ. Đây
đúng là loại từ vựng bản địa mà cả tab từ khoá đa thị trường sinh ra để tìm.

BẪY ĐÃ ĐO, và nó im lặng: host phải KHỚP với thị trường. Gọi `completion.amazon.com` kèm mã
sàn của Anh trả về HTTP 200 với danh sách rỗng — không lỗi, không cảnh báo, chỉ là không có
gì. Kết cục đó đi qua `expand_with_provider` thành "kết nối được nhưng không trả về từ khoá
nào", một câu đọc ra là "Amazon không có gợi ý cho ngành hàng này" trong khi sự thật là ta
hỏi sai địa chỉ. Vì vậy `MARKETPLACE` ghép cặp host và mã sàn thành MỘT mục, không phải hai
bảng tra riêng.
"""

from __future__ import annotations

from urllib.parse import quote

from lib.core.http import get_json

from ..provider import KeywordProvider, Suggestion
from ..types import SearchContext

#: Thị trường → (host autocomplete, mã sàn của Amazon).
#:
#: Chỉ liệt kê những nước đã gọi thử và thấy trả về gợi ý thật. Amazon Ấn Độ CỐ Ý vắng mặt:
#: `completion.amazon.in` trả 502 kèm một trang HTML chặn, không phải JSON — nên để nó trong
#: bảng sẽ biến một nước không phục vụ được thành một nguồn báo lỗi mỗi lượt chạy.
#:
#: New Zealand và Ireland cũng vắng vì Amazon không có sàn riêng ở đó. Người mua hai nước này
#: dùng amazon.com.au và amazon.co.uk, nhưng gợi ý của hai sàn kia phản ánh người Úc và người
#: Anh — nên gán bừa vào là dán nhãn sai cho dữ liệu, không phải mở rộng độ phủ.
MARKETPLACE: dict[str, tuple[str, str]] = {
    "US": ("completion.amazon.com", "ATVPDKIKX0DER"),
    "GB": ("completion.amazon.co.uk", "A1F83G8C2ARO7P"),
    "CA": ("completion.amazon.ca", "A2EUQ1WTGCTBG2"),
    "AU": ("completion.amazon.com.au", "A39IBJ37TRP1C6"),
    "SG": ("completion.amazon.sg", "A19VAU5U5O7RUS"),
    "DE": ("completion.amazon.de", "A1PA6795UKMFR9"),
    "JP": ("completion.amazon.co.jp", "A1VC38T7YXB528"),
}

#: `aps` = tìm trong tất cả ngành hàng. Chốt một danh mục cụ thể sẽ cho gợi ý sát hơn nhưng
#: đòi người dùng phải biết trước hàng của mình thuộc danh mục nào của Amazon — một câu hỏi
#: mà chính công cụ này sinh ra để trả lời.
SEARCH_ALIAS = "aps"


class Amazon(KeywordProvider):
    id = "amazon"
    label = "Amazon"
    #: Mọi gợi ý trả về đều có `prior = 0.0` — Amazon không công bố điểm liên quan nào dùng
    #: được, khác Shopee. Thứ duy nhất nguồn này cấp là thứ tự và mức độ lặp lại.
    has_native_score = False
    markets = list(MARKETPLACE.keys())

    async def fetch_suggestions(self, term: str, ctx: SearchContext) -> list[Suggestion]:
        entry = MARKETPLACE.get(ctx.country.upper())
        if entry is None:
            raise RuntimeError(f"Amazon không có sàn riêng ở {ctx.country}")
        host, mid = entry

        encoded = quote(term, safe="")
        payload = await get_json(
            f"https://{host}/api/2017/suggestions"
            f"?mid={mid}&alias={SEARCH_ALIAS}&prefix={encoded}&client-info=amazon-search-ui",
            {"referer": f"https://www.{host.removeprefix('completion.')}/"},
        )

        out: list[Suggestion] = []
        for item in (payload or {}).get("suggestions") or []:
            # `ghost` là gợi ý Amazon vẽ mờ để gợi mở chứ không phải truy vấn người ta gõ, và
            # các `suggType` khác `KeywordSuggestion` là thẻ thương hiệu hay danh mục — cả hai
            # đều không phải từ khoá. Chưa gặp cái nào trong lúc đo, nhưng lọc ở đây rẻ hơn
            # nhiều so với việc một ngày nào đó chúng lọt vào bảng xếp hạng mà không ai biết.
            if item.get("suggType") != "KeywordSuggestion" or item.get("ghost"):
                continue
            keyword = (item.get("value") or "").strip()
            if keyword:
                out.append(Suggestion(keyword=keyword))
        return out


amazon = Amazon()
