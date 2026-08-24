"""
NGUỒN TỪ KHOÁ: Taobao search suggest.

VAI TRÒ: Taobao là chợ BÁN LẺ của Trung Quốc, nên từ khoá ở đây trả lời câu "người mua lẻ
Trung Quốc gõ gì vào ô tìm kiếm". Đứng cạnh nó là 1688 (chợ bán buôn, nơi đi nhập hàng — xem
`ali1688.py`) và Douyin (nội dung — xem `douyin.py`). Xem sổ đăng ký ở `providers/__init__.py`
để biết ba nguồn `CN` chia vai thế nào.

Đo ngày 2026-08-10, dò cả bốn nền tảng Trung Quốc. HAI TRONG BỐN KẾT LUẬN VỀ SAU LÀ SAI, nên
bảng này giữ lại cả phán quyết cũ lẫn phán quyết đúng — một ghi chú "không lấy được" sai còn
tốn thời gian hơn là không có ghi chú nào.

    Taobao   ✅  HTTP thường, không đăng nhập, không captcha
    1688     ✅  SAI ở lần đầu. Kết luận cũ: "chống bot Alibaba, ô gợi ý đi qua cổng MTOP đòi
                 chữ ký". Mô tả đúng, kết luận sai — chữ ký tự tính được và cổng phát token cho
                 khách vãng lai. Gỡ ra 2026-08-12, xem `ali1688.py`.
    Temu     ❌  CAPTCHA ngay trang chủ ("Security Verification", đếm số con vật trong ô)
    Douyin   ✅  SAI ở lần đầu, và sai đắt nhất. Kết luận cũ: "chặn mềm — `search/sug` trả HTTP
                 200 kèm body rỗng, đăng nhập KHÔNG đủ, còn cần chữ ký do JS của trang tự tính".
                 Nguyên nhân thật chỉ là THIẾU HEADER `Referer`. Gỡ ra 2026-08-12, xem
                 `douyin.py`.

BÀI HỌC CHUNG CỦA HAI LẦN SAI, đáng ghi lại vì cả hai mắc đúng một kiểu: "HTTP 200 kèm body
rỗng" bị đọc thành "nền tảng nhận ra bot và chặn mềm". Nó gần như không bao giờ có nghĩa đó.
Cả hai lần, nguyên nhân là một thứ nhỏ và kiểm được bằng phép thử một biến — một header thiếu,
một tham số thiếu. Trước khi kết luận "cần đăng nhập" hay "cần chữ ký", hãy chạy hết bảng đổi
MỘT biến mỗi lần: từng header một, từng tham số một.

Một nguồn Douyin CŨ đã được dựng rồi gỡ ngày 2026-08-10 — bản đó mở Playwright với phiên đăng
nhập rồi nghe mạng bắt `general/search/stream/`, cho 32 từ khoá mỗi lượt trong 13–17 giây và
phải nuôi cookie. Bản hiện tại không cần gì trong số đó, nên bản cũ không còn lý do tồn tại.

NHỊP GỌI PHẢI RỘNG HƠN BA SÀN KIA. Đo thấy 700ms bị `ConnectTimeout`, 1200ms thì 8/8 lượt
thành công. Vì vậy nguồn này tự giãn thêm — xem `CALL_DELAY_MS` ở `expand.py` và ghi chú bên dưới.
"""

from __future__ import annotations

from urllib.parse import quote

from lib.core.http import get_json

from ..provider import KeywordProvider, Suggestion
from ..types import SearchContext

#: Taobao chỉ phục vụ thị trường Trung Quốc đại lục.
#:
#: Không có bản theo nước như Shopee: `suggest.taobao.com` là một endpoint duy nhất, trả về
#: tiếng Trung giản thể, phục vụ người mua trong nước. Khai báo đúng một thị trường nên ô Quốc
#: gia sẽ tự thu về `CN` khi người dùng chọn nguồn này.
MARKETS = ["CN"]


class Taobao(KeywordProvider):
    id = "taobao"
    label = "Taobao"
    #: Cột thứ hai trong mỗi mục LUÔN là chuỗi "100" — đo trên nhiều từ gốc khác nhau đều vậy.
    #: Giống hệt `prior: 0.0` của Amazon: có chỗ để điểm liên quan, nhưng không có điểm nào.
    #: Nên nguồn này xếp thuần theo vị trí và mức độ lặp lại, y như Amazon.
    has_native_score = False
    markets = MARKETS
    #: Rộng hơn mặc định 700ms. Đo 2026-08-10: ở 700ms lượt gọi thứ hai đã `ConnectTimeout`,
    #: ở 1200ms thì 8/8 lượt thành công liên tiếp. Cái giá là mỗi lượt "Thường" chậm thêm
    #: khoảng 12 giây, và đó là cái giá đúng — một nguồn chạy chậm vẫn hơn một nguồn báo lỗi.
    call_delay_ms = 1200

    async def fetch_suggestions(self, term: str, ctx: SearchContext) -> list[Suggestion]:
        if ctx.country.upper() not in MARKETS:
            raise RuntimeError(f"Taobao không phục vụ {ctx.country}")

        encoded = quote(term, safe="")
        payload = await get_json(
            f"https://suggest.taobao.com/sug?code=utf-8&q={encoded}",
            {"referer": "https://www.taobao.com/"},
        )

        out: list[Suggestion] = []
        # Định dạng: {"result": [["连衣裙女夏", "100"], ["连衣裙女", "100"], ...]}
        # Mỗi mục là một MẢNG chứ không phải object, nên phải kiểm độ dài trước khi đọc — một
        # mục rỗng hay một chuỗi trần sẽ ném IndexError giữa vòng lặp và mất cả lượt gọi.
        for item in (payload or {}).get("result") or []:
            if not isinstance(item, list) or not item:
                continue
            keyword = str(item[0]).strip()
            if keyword:
                out.append(Suggestion(keyword=keyword))
        return out


taobao = Taobao()
