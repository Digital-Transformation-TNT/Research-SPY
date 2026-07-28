"""
NGUỒN TỪ KHOÁ: Shopee search hint.

Lựa chọn endpoint là kết quả đo, không phải phỏng đoán: `search_suggestion` trả về các
ô quảng bá danh mục không liên quan ("Áo Nữ"), còn `search_hint` trả về biến thể từ khoá
thật — và là nguồn duy nhất kèm điểm liên quan.

Lưu ý về giới hạn đã đo ngày 2026-07-28: endpoint *tìm sản phẩm* của Shopee trả 403 với
người gọi ẩn danh, kể cả từ một trang trình duyệt đã làm nóng. Nghĩa là không lấy được
số lượt bán. Ở đây ta chỉ lấy gợi ý từ khoá, và giao diện phải nói đúng như vậy chứ
không được ngụ ý có dữ liệu doanh số.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from lib.core.http import get_json

from ..provider import KeywordProvider, Suggestion

#: Shopee chạy một tên miền riêng cho mỗi thị trường.
DOMAIN: dict[str, str] = {
    "VN": "shopee.vn",
    "TH": "shopee.co.th",
    "PH": "shopee.ph",
    "MY": "shopee.com.my",
    "ID": "shopee.co.id",
    "SG": "shopee.sg",
}


class Shopee(KeywordProvider):
    id = "shopee"
    label = "Shopee"
    has_native_score = True
    markets = list(DOMAIN.keys())

    async def fetch_suggestions(self, term: str, country: str) -> list[Suggestion]:
        domain = DOMAIN.get(country.upper())
        if not domain:
            raise RuntimeError(f"Shopee không hoạt động ở {country}")

        encoded = quote(term, safe="")
        payload = await get_json(
            f"https://{domain}/api/v4/search/search_hint?keyword={encoded}",
            {
                "referer": f"https://{domain}/search?keyword={encoded}",
                "x-api-source": "pc",
                "x-requested-with": "XMLHttpRequest",
            },
        )

        out: list[Suggestion] = []
        for entry in (payload or {}).get("keywords") or []:
            # Điểm liên quan của Shopee nằm trong một chuỗi JSON lồng, không phải một trường thật.
            score = None
            try:
                rank_scores = json.loads(entry.get("search_info") or "{}").get("rank_scores")
                if isinstance(rank_scores, list) and rank_scores:
                    score = rank_scores[0]
            except (ValueError, AttributeError):
                pass  # một số bản ghi không có
            out.append(Suggestion(keyword=entry.get("keyword"), score=score))
        return out


shopee = Shopee()
