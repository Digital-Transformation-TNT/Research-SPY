"""
NGUỒN TỪ KHOÁ: 1688 search suggest.

VAI TRÒ: 1688 là chợ BÁN BUÔN, nơi người dùng đi nhập hàng. Nó đứng cạnh Taobao chứ không
thay Taobao, dù hai nguồn cùng phục vụ đúng một thị trường (`CN`): Taobao là cách người MUA LẺ
Trung Quốc gọi món hàng, 1688 là cách NHÀ CUNG CẤP gọi nó. Khác biệt ấy hiện ra ngay trong dữ
liệu — đo 2026-08-12 trên "宠物用品", 1688 trả về 一件待发 (dropship), 供应商 (nhà cung cấp),
拿货 (lấy hàng sỉ), 贴牌 (gia công nhãn riêng). Không cụm nào trong số đó là từ khoá bán lẻ, và
không nguồn nào khác trong sổ đăng ký với tới được chúng.

Nhờ có hai nguồn, thị trường Trung Quốc mới có `agreement` — thành phần nặng nhất của điểm số
(0,45). Trước đây chỉ có Taobao nên phần điểm ấy luôn bằng không ở `CN`.

TÌM RA ĐƯỜNG VÀO NÀY MẤT NHIỀU CÔNG, nên chép lại đủ những ngõ cụt để không ai đi lại. Đo
2026-08-12:

    suggest.1688.com/sug.htm           ❌  302 → page.1688.com/shtml/static/wrongpage.html
    suggest.1688.com/js_1688_sug.htm   ❌  302 → cùng trang 404 đó
    suggest.1688.com/sug_1688.htm      ❌  302 → cùng trang 404 đó
    sug./asearch./search./s.1688.com   ❌  302 về trang chặn
    www.1688.com (Chrome sạch)         ❌  đá thẳng sang login.taobao.com
    s.1688.com, search.1688.com        ❌  chống bot Alibaba: `_____tmd_____/punish` + x5secdata
    m.1688.com (bấm vào ô tìm kiếm)    ❌  hiện captcha kéo trượt ngay lần chạm đầu tiên
    global.1688.com                    ⚠️  mở được không cần đăng nhập, nhưng ô tìm kiếm của nó
                                           KHÔNG có gợi ý — gõ vào không phát ra request nào

Cái chạy được nằm ở chỗ không ai đoán ra bằng cách thử tên miền: cổng MTOP `h5api.m.1688.com`,
CÙNG một API với ô tìm kiếm chào hàng, chỉ khác `appId` và `bizName`. Quét ba mươi tên API kiểu
`mtop.alibaba.cbu.pc.search.suggest` đều trả `FAIL_SYS_API_NOT_FOUNDED` — vì tên API không hề
chứa chữ "suggest" nào. Nó là `mtop.relationrecommend.WirelessRecommend.recommend` với
`appId = 39799`.

KHÔNG CẦN ĐĂNG NHẬP, và điều đó đã được kiểm cả hai chiều. Cổng phát cookie `_m_h5_tk` cho
khách vãng lai: lượt gọi đầu trả `FAIL_SYS_TOKEN_EMPTY` kèm Set-Cookie, lượt thứ hai ký bằng
`md5(token & t & appKey & data)` là qua. Phiên browser đã bắt được request này mang
`__cn_logon__=false`, và chạy lại từ một phiên trắng hoàn toàn cũng ra đúng kết quả ấy. Cách ký
lấy từ https://github.com/ihmily/1688-Decryptor và https://github.com/netkaruma/search1688api.

MỘT NGUỒN "ĐÀO TỪ TIÊU ĐỀ CHÀO HÀNG" ĐÃ ĐƯỢC DỰNG XONG RỒI THAY BẰNG FILE NÀY, cùng ngày. Bản
đó gọi `appId 32517` lấy 60 tiêu đề mỗi lượt rồi tách từ bằng jieba và đếm cụm — chạy thật,
12 lượt cho 155 từ khoá. Ghi lại vì nó vẫn là phương án dự phòng đúng nếu endpoint gợi ý chết,
nhưng ba con số dưới đây nói vì sao nó không đáng giữ khi có bản này:

    băng thông   1,3MB mỗi lượt so với 51KB — gấp hai mươi lăm lần
    phụ thuộc    cần jieba, và cần một mỏ neo đoán từ dữ liệu để cụm đào ra còn chứa từ gốc
    chất lượng   tiêu đề cho ra 吊带连衣裙, 无袖连衣裙 — đúng nhưng là mô tả sản phẩm; ô gợi ý
                 cho ra 蓝牙耳机外卖骑手专用, 蓝牙耳机司机开车专用, 蓝牙耳机骨传导不入耳 —
                 tức là thứ NGƯỜI TA GÕ, không phải thứ người bán viết
"""

from __future__ import annotations

from typing import Any

from lib.core.mtop import call as mtop_call

from ..provider import KeywordProvider, Suggestion
from ..types import SearchContext

#: 1688 chỉ phục vụ Trung Quốc đại lục, y như Taobao — đây là chợ bán buôn trong nước.
MARKETS = ["CN"]

#: Mã ứng dụng TPP của ô GỢI Ý. Đây là tham số phân biệt duy nhất giữa nguồn này và ô tìm kiếm
#: chào hàng (`appId 32517`, trả về sản phẩm — và cũng là mã mà tìm-bằng-ảnh dùng, xem
#: `lib/imagesearch/ali.py`). Cùng một API, ba mặt hàng dữ liệu khác hẳn nhau.
SUGGEST_APP_ID = 39799


class Ali1688(KeywordProvider):
    id = "ali1688"
    label = "1688"
    #: Mỗi gợi ý có trường `count`, và nó LUÔN bằng 0 — đo trên nhiều từ gốc khác nhau đều vậy.
    #: Giống hệt cột "100" của Taobao và `prior: 0.0` của Amazon: có chỗ để điểm liên quan,
    #: nhưng không có điểm nào. Nên nguồn này xếp thuần theo vị trí và mức độ lặp lại.
    has_native_score = False
    markets = MARKETS

    async def fetch_suggestions(self, term: str, ctx: SearchContext) -> list[Suggestion]:
        if ctx.country.upper() not in MARKETS:
            raise RuntimeError(f"1688 không phục vụ {ctx.country}")

        payload = await self._call(term)

        out: list[Suggestion] = []
        # Định dạng: {"data": {"items": [{"data": {"keyword": "蓝牙耳机华强北", ...}}, ...]}}
        #
        # Từ khoá nằm ở `items[].data.keyword` chứ KHÔNG lấy từ `trackInfoModel.exposeInfos`,
        # dù chỗ đó cũng có đủ mười bốn cụm ghép bằng dấu chấm phẩy và nhìn thì dễ bóc hơn.
        # Chuỗi ấy là dữ liệu THEO DÕI — nó tồn tại để gửi lên máy chủ đo lường, nên không có
        # gì bảo đảm nó còn nguyên hình dạng đó ở lần đổi giao diện sau, và một cụm chứa dấu
        # chấm phẩy sẽ lặng lẽ bị tách làm đôi.
        for item in ((payload.get("data") or {}).get("items")) or []:
            keyword = (((item or {}).get("data") or {}).get("keyword") or "").strip()
            if keyword:
                out.append(Suggestion(keyword=keyword))
        return out

    async def _call(self, term: str) -> dict[str, Any]:
        """
        Gọi cổng MTOP. Việc ký, cookie `_m_h5_tk` và vòng thử lại nằm ở `lib/core/mtop.py`.

        Lớp chung ấy được tách ra khi dựng tìm-bằng-ảnh 1688: hai chỗ dùng đúng một cách ký,
        đúng một cổng, chỉ khác `appId` và bộ tham số.
        """
        return await mtop_call(
            SUGGEST_APP_ID,
            {
                "bizName": "input_suggest",
                "keyword": term,
                "verticalProductFlag": "pcmarket",
                "integrateTrace": True,
                "type": "offer",
                "appName": "nodeSearchWork",
            },
        )


ali1688 = Ali1688()
