"""
NGUỒN TỪ KHOÁ: bảng truy vấn liên quan của Google Trends.

Khác hẳn ba nguồn còn lại về bản chất. Google Suggest, Shopee và TikTok đều là API *gợi ý*:
chúng hoàn thiện một tiền tố, nên mọi thứ chúng trả về đều bắt đầu bằng cụm ta gõ vào. Đó
là một giới hạn cấu trúc, không phải chuyện xếp hạng — với từ gốc "quần áo nam", chúng
không bao giờ đẻ ra được "shop quần áo nam" hay "áo sơ mi nam", dù đó chính là những cụm
người Việt tìm nhiều nhất trong ngành hàng ấy.

Trends thì trả lời một câu hỏi khác: những người tìm từ gốc này còn tìm gì nữa, và nhiều
tới đâu. Vì vậy nó vừa mở ra vùng từ khoá nằm ngoài tầm autocomplete, vừa là nguồn duy nhất
mang theo khối lượng tìm kiếm thật.

Đổi lại có hai cái giá, và cả hai đều được nói thẳng ra chứ không giấu:
  - Phải đăng nhập. Ẩn danh thì widget trả HTTP 200 kèm danh sách rỗng — im lặng, không
    báo lỗi. `lib/keywords/trends.py` quy trường hợp đó về "phiên hỏng" và kèm cách sửa.
  - Số cụm có hạn. Đo 2026-07-30 trên "bút bi": 100 cụm cho cả hai bảng cộng lại. Đây là
    nguồn CHẤT LƯỢNG CAO / SỐ LƯỢNG THẤP, dùng để chấm điểm và bổ sung cho phần long-tail
    do các nguồn gợi ý sinh ra, không phải để thay thế.
"""

from __future__ import annotations

from lib.core.store import DiskStore

from ..provider import KeywordProvider, Suggestion
from ..trends import RelatedQuery, fetch_related_queries
from ..types import SearchContext

#: Cache dài hơn hẳn cache chung của phần mở rộng (mặc định 15 phút).
#:
#: Hai lý do. Bảng truy vấn liên quan tính trên cửa sổ 12 tháng nên hình dạng của nó không
#: đổi theo giờ. Và mỗi lần lấy lại là một lần chạm vào nguồn duy nhất trong hệ thống vừa
#: bị giới hạn tần suất theo IP vừa cần phiên đăng nhập — thứ đáng tiết kiệm nhất ở đây
#: không phải thời gian mà là số lần gọi.
CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000

#: GHI XUỐNG ĐĨA, không dùng `lib/core/cache.py` như mọi nguồn khác.
#:
#: Cái TTL bảy ngày ở trên trước đây là một lời hứa suông: cache chung nằm trong bộ nhớ, mà
#: backend chạy không có `--reload` nên mỗi lần sửa code là một lần xoá sạch. Đo 2026-08-13,
#: một ngày làm việc bình thường có hàng chục lần restart, nên bảy ngày thực tế thành vài phút.
#:
#: Rổ riêng cũng vá lỗ thứ hai: cache chung giới hạn 300 mục cho CẢ Quảng cáo, Từ khoá, Media
#: và Cơ hội, dọn theo thứ tự chèn. Một buổi lướt mục Quảng cáo đủ để đá văng đúng cái bảng
#: vừa tốn một phút mở trình duyệt và một suất hạn mức để lấy.
_STORE = DiskStore("trends")


def _encode(queries: list[RelatedQuery]) -> list[dict]:
    """`RelatedQuery` → JSON. Kho trên đĩa chỉ nhận kiểu JSON thuần, không nhận dataclass."""
    return [
        {"q": e.query, "v": e.value, "r": e.rising, "c": e.change_percent} for e in queries
    ]


def _decode(raw: object) -> list[RelatedQuery] | None:
    """
    JSON → `RelatedQuery`, và `None` khi bản ghi không đọc được.

    Nuốt bản ghi hỏng thay vì ném lỗi: file trên đĩa sống qua nhiều lần đổi code, nên một
    ngày nào đó nó sẽ chứa hình dạng cũ. Khi ấy điều đúng là đi lấy lại dữ liệu, không phải
    làm hỏng lượt tìm của người dùng bằng một lỗi về định dạng cache.
    """
    if not isinstance(raw, list) or not raw:
        return None
    try:
        return [
            RelatedQuery(
                query=str(e["q"]),
                value=float(e["v"]),
                rising=bool(e["r"]),
                change_percent=float(e.get("c") or 0.0),
            )
            for e in raw
        ]
    except (KeyError, TypeError, ValueError):
        return None


class TrendsRelated(KeywordProvider):
    id = "trends"
    #: Hiển thị là "Google" chứ không phải "Google Trends": với người dùng, đây LÀ nguồn
    #: Google của công cụ — nguồn Suggest cũ đã bị gỡ. Giữ nguyên id `trends` để khoá cache
    #: và các đoạn code xử lý riêng nguồn này không phải đổi theo.
    label = "Google"
    has_native_score = False
    #: Nguồn duy nhất ĐO được lượng tìm, nên nó là nguồn chấm chính và được tick sẵn.
    is_primary = True
    # Một lời gọi là đã trọn bảng; hỏi lại với từng hậu tố chỉ nhận đúng kết quả đó nhiều
    # lần và lĩnh thêm 429.
    expands_terms = False

    async def fetch_suggestions(self, term: str, ctx: SearchContext) -> list[Suggestion]:
        # Cả ba ô chọn đều nằm trong khoá cache. Bảng truy vấn liên quan của "Năm qua" và của
        # "24 giờ qua" là hai tập khác hẳn nhau, và Google Mua sắm lại là tập thứ ba — dùng
        # chung một khoá thì lần chọn sau nhận nguyên kết quả của lần chọn trước.
        key = f"trendsrel:{ctx.country.upper()}:{ctx.time_range}:{ctx.gprop}:{term.lower()}"

        queries = _decode(_STORE.get(key))
        if queries is None:
            outcome = await fetch_related_queries(term, ctx)

            # Không có gì VÀ có lý do — báo lên để nó thành một dòng trạng thái người dùng
            # đọc được, thay vì lặng lẽ đóng góp con số 0 vào bảng kết quả. Cố ý KHÔNG cache
            # thất bại: phiên hết hạn được sửa trong hai phút, và cache lỗi bảy ngày sẽ biến
            # một lần đăng nhập lại thành một tuần tưởng như nguồn đã chết.
            if not outcome.queries:
                raise RuntimeError(
                    outcome.message or "Google Trends không trả về truy vấn liên quan nào"
                )

            queries = outcome.queries
            _STORE.set(key, _encode(queries), CACHE_TTL_MS)

        return [
            Suggestion(
                keyword=entry.query,
                demand=entry.value,
                rising=entry.rising,
                # Chỉ có nghĩa ở bảng hàng đầu. Với cụm "đang tăng" thì `value` đã là phần
                # trăm tăng, nên chở thêm một phần trăm nữa là mời gọi hiển thị hai con số
                # tăng trưởng cạnh nhau cho cùng một cụm.
                change_percent=None if entry.rising else entry.change_percent,
            )
            for entry in queries
        ]


trends_related = TrendsRelated()
