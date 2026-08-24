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
from ..types import SearchContext

#: Shopee chạy một tên miền riêng cho mỗi thị trường.
#:
#: Danh sách này là kết quả ĐO ngày 2026-08-06, không phải chép từ trang tin nào — và phần
#: bị loại ra mới là phần đáng ghi lại, vì cả ba nhóm đều trả về HTTP 200:
#:
#:   `shopee.jp`, `shopee.cn` — cổng tuyển NGƯỜI BÁN bán sang Đông Nam Á, không phải sàn cho
#:     người mua. `search_hint` ở đó trả 404; không ai tìm kiếm trên hai tên miền này.
#:   `shopee.com.mx`, `shopee.com.ar`, `shopee.cl` — nguy hiểm nhất: chúng trả về đủ 12 gợi ý
#:     trông hoàn toàn hợp lệ, nhưng MX và CL cho kết quả GIỐNG NHAU TỪNG DÒNG và cả ba nhả
#:     tiếng Bồ Đào Nha ("tênis feminino", "tapete sala"). Đó là index của Brazil. Thêm chúng
#:     vào đây nghĩa là người dùng chọn Mexico và nhận dữ liệu Brazil, không một dấu hiệu nào
#:     báo sai.
#:   `shopee.in`, `shopee.fr`, `shopee.es`, `shopee.com` — redirect thẳng về shopee.vn.
#:   `shopee.pl` — chỉ còn trang trợ giúp. `shopee.co.kr` — không phân giải.
#:
#: Nói cách khác: tên miền sống KHÔNG chứng minh thị trường sống. Phép kiểm đáng tin là hỏi
#: `search_hint` bằng chính tiếng bản địa rồi xem ngôn ngữ trả về có khớp không.
DOMAIN: dict[str, str] = {
    "VN": "shopee.vn",
    "TH": "shopee.co.th",
    "PH": "shopee.ph",
    "MY": "shopee.com.my",
    "ID": "shopee.co.id",
    "SG": "shopee.sg",
    "TW": "shopee.tw",
    "BR": "shopee.com.br",
}


class Shopee(KeywordProvider):
    id = "shopee"
    label = "Shopee"
    has_native_score = True
    markets = list(DOMAIN.keys())

    async def fetch_suggestions(self, term: str, ctx: SearchContext) -> list[Suggestion]:
        domain = DOMAIN.get(ctx.country.upper())
        if not domain:
            raise RuntimeError(f"Shopee không hoạt động ở {ctx.country}")

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
