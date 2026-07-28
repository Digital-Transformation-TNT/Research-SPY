"""
NGUỒN TỪ KHOÁ: TikTok search preview.

Lựa chọn endpoint là kết quả đo: `search/general/sug/` trả về danh sách rỗng;
`preview` mới là cái chạy được.

Đây là nguồn *gợi ý tìm kiếm* của TikTok, hoàn toàn tách biệt với nguồn quảng cáo TikTok
ở `lib/ads/platforms/tiktok.py`. Hai bên không dùng chung code, cũng không dùng chung
phiên — trùng tên nền tảng chỉ là trùng tên.

Giới hạn đã đo ngày 2026-07-28: search organic của TikTok trả về body rỗng cho người gọi
ẩn danh, nên không lấy được lượt xem. Chỉ có gợi ý từ khoá là dùng được.
"""

from __future__ import annotations

from urllib.parse import quote

from lib.core.http import get_json

from ..provider import KeywordProvider, Suggestion


class TikTok(KeywordProvider):
    id = "tiktok"
    label = "TikTok"
    has_native_score = False

    async def fetch_suggestions(self, term: str, country: str) -> list[Suggestion]:
        encoded = quote(term, safe="")
        payload = await get_json(
            f"https://www.tiktok.com/api/search/general/preview/?keyword={encoded}",
            {"referer": f"https://www.tiktok.com/search?q={encoded}"},
        )
        return [
            Suggestion(keyword=item["content"])
            for item in (payload or {}).get("sug_list") or []
            if item.get("content")
        ]


tiktok = TikTok()
