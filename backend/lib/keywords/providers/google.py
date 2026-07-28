"""
NGUỒN TỪ KHOÁ: Google Suggest.

Endpoint gợi ý của thanh tìm kiếm, gọi được bằng HTTP thường và không cần khoá. Đây là
nguồn rộng nhất trong ba nguồn, nhưng cũng là nguồn lẫn nhiều truy vấn tìm hiểu ("… là
gì", "… mặc với gì") nhất — phần phân loại ý định ở `lib/keywords/normalize.py` lo việc đó.
"""

from __future__ import annotations

from urllib.parse import quote

from lib.core.http import get_json

from ..provider import KeywordProvider, Suggestion

#: Tham số vùng của Google theo từng nước.
LOCALE: dict[str, dict[str, str]] = {
    "VN": {"hl": "vi", "gl": "vn"},
    "US": {"hl": "en", "gl": "us"},
    "PH": {"hl": "en", "gl": "ph"},
    "TH": {"hl": "th", "gl": "th"},
    "ID": {"hl": "id", "gl": "id"},
    "MY": {"hl": "ms", "gl": "my"},
}


class Google(KeywordProvider):
    id = "google"
    label = "Google"
    has_native_score = False

    async def fetch_suggestions(self, term: str, country: str) -> list[Suggestion]:
        locale = LOCALE.get(country.upper(), LOCALE["VN"])
        payload = await get_json(
            "https://suggestqueries.google.com/complete/search"
            f"?client=firefox&hl={locale['hl']}&gl={locale['gl']}&q={quote(term, safe='')}"
        )
        if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list):
            return [Suggestion(keyword=keyword) for keyword in payload[1]]
        return []


google = Google()
