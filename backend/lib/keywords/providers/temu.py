"""
NGUỒN TỪ KHOÁ: Temu search suggest — qua MÁY-THỢ, không gọi thẳng.

ĐÂY LÀ NGUỒN DUY NHẤT KHÔNG GỌI HTTP THẲNG, và điều đó là bắt buộc chứ không phải lựa chọn.

Đã đo ba lần, ba thời điểm, cùng một kết luận:

    2026-08-10 (`taobao.py`)  Temu ❌ CAPTCHA ngay trang chủ ("Security Verification")
    2026-09-03 (commit ed8cb33) `/api/poppy/v1/search_suggest` trả `{"intercepted":true}` với
                              MỌI biến thể header/cookie; mở bằng Chrome thật cũng ra trang
                              "Security verification"
    2026-09-03 (lần này)      từ chính VPS: GET → HTTP 500 `error_code 50000`
                              POST → HTTP 403 `error_code 40001`
                              GET `/` → HTTP 200 nhưng body là JS chống bot đã làm rối

IP KHÔNG bị chặn cứng — trang chủ vẫn trả 200. Thứ thiếu là token `anti-content`, do JS của
chính trang sinh ra lúc chạy và xoay liên tục. Viết lại thuật toán ký sẽ hỏng mỗi lần Temu
đổi, nên cách duy nhất bền là để CHÍNH TRANG gọi rồi chộp response — đúng lối mà tab "Sản
phẩm" đã dùng cho Temu từ trước, và chỉ extension trong một trình duyệt thật làm được.

HAI HỆ QUẢ, cả hai đều phải nói ra chứ không được giấu:

1. NGUỒN NÀY CẦN MÁY-THỢ ONLINE. Bảy nguồn kia chạy được cả khi không có trình duyệt nào.
   `app/api/keywords.py::sources` ẩn hẳn Temu khỏi danh sách khi không có thợ, để người dùng
   không chọn được một thứ chắc chắn hỏng.

2. HỎI GỘP MỘT LƯỢT, TRẦN 12 CỤM. Bộ mở rộng hỏi mỗi nguồn 12–45 lượt (`DEPTH_CALLS`). Ở đây
   một lượt là một lần gõ vào trang thật, và cả công ty dùng chung MỘT máy-thợ chạy tuần tự:
   hỏi riêng lẻ thì một người tìm từ khoá chiếm máy-thợ 3,6–13 phút, mọi người khác xếp hàng
   sau. Gộp lại còn khoảng 40 giây cho cả lượt. Đổi lại: mức "Thường" và "Sâu" cũng chỉ được
   12 cụm như mức "Nhanh" — cố ý, và `max_terms` là chỗ nói ra điều đó.
"""

from __future__ import annotations

from lib.core.worker_relay import (
    BATCH_TIMEOUT_S,
    WorkerOffline,
    WorkerTimeout,
    run_on_worker,
)

from ..provider import KeywordProvider, Suggestion
from ..types import SearchContext

#: Trần số cụm cho một lượt. Trùng với `TEMU_SUGGEST_MAX_TERMS` ở `extension/background.js` —
#: chốt ở cả hai đầu, để một payload méo không biến thành một lượt chiếm máy-thợ mười phút.
MAX_TERMS = 12

#: Temu bán xuyên biên giới bằng MỘT tên miền `temu.com`, khác Shopee (mỗi nước một tên miền).
#:
#: Ô Quốc gia vẫn có tác dụng gián tiếp: `expand_with_provider` dùng `ctx.country` để chọn
#: ngôn ngữ của các tiền tố mở rộng, nên chọn VN thì gõ tiền tố tiếng Việt. Nhưng bản thân
#: endpoint gợi ý không nhận tham số vùng nào — nó trả theo phiên của chính máy-thợ. Vì vậy
#: `geo_targeted = False`, giống TikTok: để giao diện GIẢI THÍCH cho đúng chứ không phải để
#: ẩn ô chọn đi.
MARKETS = None


class Temu(KeywordProvider):
    id = "temu"
    label = "Temu"
    #: Endpoint gợi ý không kèm điểm liên quan nào — chỉ có thứ tự. Xếp thuần theo vị trí và
    #: mức độ lặp lại, y như Amazon và Taobao.
    has_native_score = False
    markets = MARKETS
    geo_targeted = False
    #: Hỏi gộp: xem ghi chú đầu file.
    batches_terms = True
    max_terms = MAX_TERMS

    async def fetch_suggestions_batch(
        self, terms: list[str], ctx: SearchContext
    ) -> dict[str, list[Suggestion]]:
        """
        Sai một job xuống máy-thợ, nhận về gợi ý của cả danh sách cụm.

        Đổi ba loại hỏng của relay thành ba câu người vận hành làm được gì đó. Gộp chúng lại
        thành một câu chung là cách chắc chắn khiến người ta đi tìm sai chỗ: "không có thợ"
        thì phải đi mở trang `/worker`, còn "hết giờ" thì phải xem máy-thợ có đang kẹt job
        khác không — hai việc khác hẳn nhau.
        """
        try:
            result = await run_on_worker(
                "RS_TEMU_SUGGEST",
                {"terms": terms[:MAX_TERMS], "region": ctx.country},
                timeout_s=BATCH_TIMEOUT_S,
            )
        except WorkerOffline as e:
            raise RuntimeError(f"Temu cần máy-thợ: {e}") from e
        except WorkerTimeout as e:
            raise RuntimeError(f"Temu không kịp trả gợi ý: {e}") from e

        # `None` KHÔNG phải "dữ liệu lạ" — nó có đúng một nguyên nhân hay gặp, và nói thẳng ra
        # tiết kiệm được một vòng đi tìm nhầm chỗ. Chuỗi đường đi: extension không có handler
        # cho loại job này → `chrome.runtime.lastError` → `content.js` trả `result: null` →
        # trang /worker POST null về. Xảy ra mỗi lần thêm một loại job mới mà quên bấm Reload,
        # vì restart backend không đụng gì tới trình duyệt. Đã mắc đúng lỗi này 2026-09-04.
        if result is None:
            raise RuntimeError(
                "Máy-thợ không trả lời job RS_TEMU_SUGGEST — nhiều khả năng extension chưa nạp "
                "loại job này. Vào chrome://extensions bấm Reload rồi F5 tab Máy thợ."
            )
        if not isinstance(result, dict):
            raise RuntimeError(
                f"Máy-thợ trả về kiểu {type(result).__name__} cho Temu, cần một object"
            )

        # `blocked` kèm `groups` rỗng mới là hỏng thật. Có gợi ý mà vẫn `blocked` nghĩa là
        # extension bị chặn Ở CỤM CUỐI — phần đã lấy được vẫn dùng tốt, vứt đi là phí.
        groups = result.get("groups") or []
        by_term: dict[str, list[Suggestion]] = {}
        for group in groups:
            if not isinstance(group, dict):
                continue
            term = str(group.get("term") or "")
            words = group.get("suggestions") or []
            if not term or not isinstance(words, list):
                continue
            by_term[term] = [
                Suggestion(keyword=str(w).strip())
                for w in words
                if isinstance(w, str) and w.strip()
            ]

        if not any(by_term.values()):
            # Kèm chẩn đoán của extension vào câu lỗi. Không kèm thì thứ duy nhất hiện lên là
            # "Temu không trả gợi ý nào" — đúng nhưng vô dụng, vì nó không phân biệt được ba
            # nguyên nhân cần ba cách xử khác hẳn: không tìm thấy ô search, trang không gọi
            # endpoint nào, hay gọi rồi mà ta chộp nhầm.
            raise RuntimeError(_with_debug(result))
        return by_term

    async def fetch_suggestions(self, term: str, ctx: SearchContext) -> list[Suggestion]:
        """
        Không dùng tới: `batches_terms` bật nên `expand_with_provider` chỉ gọi bản gộp.

        Vẫn phải cài vì `KeywordProvider` khai nó `@abstractmethod`. Gọi bản gộp cho đúng một
        cụm thay vì `raise`: nếu về sau có nơi nào gọi thẳng hàm này, nó chạy đúng chứ không
        vỡ — chỉ chậm hơn, và chậm thì thấy được còn vỡ thì không.
        """
        return (await self.fetch_suggestions_batch([term], ctx)).get(term, [])


def _with_debug(result: dict) -> str:
    """Ghép câu lỗi của extension với phần chẩn đoán, gọn đủ để đọc trên một dòng giao diện."""
    message = str(result.get("error") or "Temu không trả về gợi ý nào")
    debug = result.get("debug")
    if not isinstance(debug, dict):
        return message
    bits: list[str] = []
    # `stage` đứng đầu vì nó trả lời câu hỏi đầu tiên người đọc đặt ra: kẹt ở đâu.
    if debug.get("stage"):
        bits.append(f"kẹt ở bước: {debug['stage']}")
    if debug.get("ranTerms") is not None:
        bits.append(f"đã gõ {debug['ranTerms']}/{debug.get('terms', '?')} cụm")
    if debug.get("inputFound") is not True and debug.get("inputFound") is not None:
        bits.append(str(debug["inputFound"]))
    urls = debug.get("capUrls") or []
    if urls:
        bits.append("endpoint trang đã gọi: " + ", ".join(str(u) for u in urls[:4]))
    return message + (" | " + " | ".join(bits) if bits else "")


temu = Temu()
