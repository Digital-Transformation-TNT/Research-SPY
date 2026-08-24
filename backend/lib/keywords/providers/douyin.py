"""
NGUỒN TỪ KHOÁ: Douyin search suggest.

VAI TRÒ: đây là nguồn NỘI DUNG của thị trường Trung Quốc, và nó lấp đúng chỗ trống mà hai nguồn
CN kia không với tới. Taobao trả lời "người mua lẻ gọi món này là gì", 1688 trả lời "nhà cung
cấp gọi nó là gì", còn Douyin trả lời "người ta ĐANG NÓI GÌ về nó" — thứ đi trước nhu cầu mua
chứ không phản ánh nhu cầu đã hình thành. Đo 2026-08-12, cùng từ gốc trên ba nguồn:

    Taobao   连衣裙女夏, 连衣裙大码        cách gõ vào ô tìm kiếm để MUA
    1688     连衣裙定制, 连衣裙苎麻女      cách gõ để NHẬP HÀNG
    Douyin   连衣裙穿搭, 连衣裙长裙搭配什么鞋  cách người ta BÀN LUẬN

Vì vậy Douyin đóng góp cho `agreement` một phiếu THẬT SỰ ĐỘC LẬP, không phải phiếu thứ ba của
cùng một góc nhìn — đúng điều mà thành phần nặng nhất của điểm số (0,45) cần.

NGUỒN NÀY TỪNG BỊ KẾT LUẬN LÀ KHÔNG LẤY ĐƯỢC, và kết luận đó sai vì một lý do rất nhỏ. Ghi chú
cũ ở `taobao.py` (2026-08-10) viết: "chặn mềm — cả `search/sug`, `suggest_words` lẫn
`search/item` đều trả HTTP 200 kèm body rỗng, và đăng nhập KHÔNG đủ, còn cần chữ ký do JS của
trang tự tính". Triệu chứng mô tả đúng. Chẩn đoán thì sai hoàn toàn.

Đo lại 2026-08-12, thay đổi đúng MỘT header:

    không có `Referer`  →  HTTP 200, body dài 0 byte
    có `Referer`        →  HTTP 200, 25KB, 10 gợi ý kèm điểm

Không cookie, không `msToken`, không `X-Bogus`/`a_bogus`, không đăng nhập. Hai mươi lượt liên
tiếp ở nhịp 700ms: 20/20 thành công, 22 giây.

BA ĐIỀU KIỆN, và chỉ ba:

    `Referer` phải CÓ MẶT   nhưng giá trị không bị kiểm — gửi cả `https://www.google.com/` vẫn
                            trả về đủ 10 gợi ý. Đây là phép kiểm "có header không", không phải
                            phép kiểm nguồn gốc.
    `aid=6383` bắt buộc     thiếu nó thì `sug_list` rỗng (HTTP 200, 379 byte). Đây là mã ứng
                            dụng của bản web Douyin.
    User-Agent không lộ bot `python-requests/2.32` bị trả body rỗng. Lạ ở chỗ User-Agent RỖNG
                            thì lại chạy tốt — nên đây là danh sách chặn, không phải danh sách
                            cho phép. `config.user_agent` là UA trình duyệt nên không dính.

Mọi tham số còn lại mà trang thật gửi (`device_platform`, `browser_version`, `screen_width`…)
đều KHÔNG cần. Cố ý không chép chúng vào đây: mỗi tham số thừa là một thứ có thể đổi và làm
hỏng nguồn, mà không đổi lại được gì.
"""

from __future__ import annotations

from urllib.parse import quote

from lib.core.http import get_json

from ..provider import KeywordProvider, Suggestion
from ..types import SearchContext

#: Douyin phục vụ Trung Quốc đại lục. Phần còn lại của thế giới dùng TikTok, và TikTok đã là
#: một nguồn riêng trong sổ đăng ký — hai nền tảng cùng một công ty nhưng không dùng chung kho
#: nội dung, không dùng chung endpoint, và không trả về cùng thứ tiếng.
MARKETS = ["CN"]

#: Mã ứng dụng của bản web Douyin. Thiếu nó thì endpoint trả `sug_list` rỗng — xem đầu file.
APP_ID = "6383"

ENDPOINT = "https://www.douyin.com/aweme/v1/web/search/sug/"

#: Giá trị Douyin dùng thay cho "không có số liệu" ở các trường điểm.
#:
#: Nó là `-10000.0` chứ không phải `null`, nên đọc thẳng vào điểm số sẽ nhét một số âm khổng lồ
#: vào thang chuẩn hoá của `rank.py` và dìm mọi từ khoá khác xuống đáy. Phần lớn các trường
#: `ecom_*` đều mang đúng giá trị này — chỉ `ecpm_score` là luôn có số thật.
MISSING = -9999.0


class Douyin(KeywordProvider):
    id = "douyin"
    label = "Douyin"
    #: `ecpm_score` — xem `native_score_note` để biết nó KHÔNG phải cái gì.
    has_native_score = True
    #: Nói rõ đơn vị thay vì gọi chung là "điểm liên quan", vì đây là thứ khác hẳn Shopee.
    #:
    #: eCPM là doanh thu quảng cáo kỳ vọng trên một nghìn lượt hiển thị của truy vấn đó. Nó đo
    #: NHÀ QUẢNG CÁO TRẢ BAO NHIÊU để chen vào kết quả của truy vấn này — tức là một phiếu bầu
    #: bằng tiền thật cho giá trị thương mại của từ khoá.
    #:
    #: NÓ KHÔNG PHẢI LƯỢNG TÌM KIẾM, và nhầm hai thứ này là nhầm nguy hiểm: một truy vấn hiếm
    #: nhưng đúng lúc mua có thể có eCPM cao hơn hẳn một truy vấn phổ biến mà không ai bán được
    #: gì. Vì vậy nó vào `native_score` (thành phần `marketplace`, trọng số 0,15) chứ tuyệt đối
    #: không vào `demand` — chỗ đó chỉ dành cho nguồn thật sự đo được khối lượng.
    native_score_note = "{label} chấm eCPM {value} — mức nhà quảng cáo trả cho truy vấn này"
    markets = MARKETS

    async def fetch_suggestions(self, term: str, ctx: SearchContext) -> list[Suggestion]:
        if ctx.country.upper() not in MARKETS:
            raise RuntimeError(f"Douyin không phục vụ {ctx.country}")

        encoded = quote(term, safe="")
        payload = await get_json(
            f"{ENDPOINT}?aid={APP_ID}&keyword={encoded}",
            # Header BẮT BUỘC. Thiếu nó là body rỗng và không có lỗi nào để lần — xem đầu file.
            {"referer": "https://www.douyin.com/"},
        )

        # Douyin báo lỗi trong body chứ không trong mã trạng thái: tìm video khi chưa đăng nhập
        # trả về HTTP 200 kèm `status_code: 2483, "请先登录，再继续搜索吧"`. Ô gợi ý chưa bao giờ
        # trả về mã khác 0 trong lúc đo, nhưng kiểm ở đây thì một ngày nào đó Douyin siết lại sẽ
        # thành một thông báo đọc được, thay vì thành "kết nối được nhưng không có từ khoá nào".
        status = (payload or {}).get("status_code")
        if status not in (0, None):
            raise RuntimeError((payload or {}).get("status_msg") or f"Douyin trả về mã {status}")

        out: list[Suggestion] = []
        for item in (payload or {}).get("sug_list") or []:
            keyword = (item.get("content") or "").strip()
            if not keyword:
                continue
            score = (item.get("extra_info") or {}).get("ecpm_score")
            usable = isinstance(score, (int, float)) and score > MISSING
            out.append(Suggestion(keyword=keyword, score=float(score) if usable else None))
        return out


douyin = Douyin()
