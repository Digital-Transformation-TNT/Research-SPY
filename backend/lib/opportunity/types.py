"""Từ vựng của MỤC CƠ HỘI."""

from __future__ import annotations

from typing import Literal

from lib.core.model import CamelModel

#: Mức ưu tiên của đề xuất đối với đúng bối cảnh người dùng nhập. Tên giá trị được giữ ổn
#: định để không làm hỏng dữ liệu/API cũ: `core` là nên xem trước, `adjacent` là hữu ích tiếp
#: theo, còn `hidden` là gợi ý khám phá thêm.
OpportunityTier = Literal["core", "adjacent", "hidden"]

#: Kết quả đối chiếu một đề xuất với ô tìm kiếm của sàn.
OpportunityStatus = Literal["real", "niche", "wrong", "not_found"]

STATUS_ORDER: dict[str, int] = {"real": 0, "niche": 1, "not_found": 2, "wrong": 3}

#: Ưu tiên độ hữu ích và độ sát truy vấn, không ưu tiên độ lạ.
TIER_ORDER: dict[str, int] = {"core": 0, "adjacent": 1, "hidden": 2}

#: Lượt trả lời này có kèm bảng món hàng hay chỉ có lời.
#:
#: `talk` không phải là một kết cục thất bại. Người dùng gõ vào đây bằng câu nói bình thường,
#: nên rất nhiều lượt là hỏi lại về chính bảng vừa hiện ("vì sao lại có món này", "món nào
#: nhẹ vốn nhất") — những câu ấy đã có đủ dữ kiện để trả lời và đi dựng một bảng mới chỉ làm
#: mất câu trả lời thật trong mười lăm dòng không ai hỏi.
AnswerMode = Literal["products", "talk"]


class OpportunityItem(CamelModel):
    """Một món hàng được đề xuất cho bối cảnh đang xét."""

    #: Viết bằng ngôn ngữ của thị trường đích.
    term: str
    #: Nghĩa tiếng Việt của `term`, RỖNG khi thị trường đã nói tiếng Việt.
    #:
    #: Cùng lý do tồn tại với cột nghĩa ở `keywords/gloss.py`: quét thị trường Thái thì cả
    #: bảng về bằng chữ Thái và người dùng không đọc được dòng nào. Và cùng NGUYÊN TẮC CỨNG
    #: của cột đó — bản dịch chỉ để ĐỌC, không bao giờ để đi tìm: `search_term` vẫn lấy từ
    #: bằng chứng của sàn, không bao giờ lấy từ đây.
    gloss: str = ""
    tier: OpportunityTier
    pain: str
    #: Điểm xếp hạng nội bộ: sát bối cảnh + phổ biến trong bối cảnh + khả năng giải quyết nhu
    #: cầu thực tế. Không phải lượng tìm kiếm và không nên hiển thị như một phép đo thị trường.
    usefulness: int = 0
    status: OpportunityStatus = "not_found"
    #: Cụm mang sang mục Từ khoá. Rỗng khi sàn không gợi ý gì cho món này.
    #:
    #: Đây là thứ DUY NHẤT còn lại của bước đối chiếu ngoài `status`. `chain` (chuỗi hệ quả),
    #: `reason` (câu bằng chứng) và `evidence` (danh sách cụm gợi ý) từng nằm cạnh nó và đã gỡ
    #: cùng lúc với phần mở ra ở giao diện: không chỗ nào đọc chúng nữa, mà hai cái đầu còn
    #: tốn một trường trong mỗi lượt gọi Gemini. `evidence` vẫn được tính TRONG `map_demand`,
    #: chỉ là không đi ra ngoài — `_judge` cần nó để chặn cụm do mô hình tự viết.
    search_term: str = ""


class DemandMap(CamelModel):
    """
    MỘT lượt trả lời trong cuộc trò chuyện.

    Từng là kết quả của đúng một ô nhập "bối cảnh". Nay người dùng gõ câu hỏi bình thường và
    hỏi tiếp được, nên mỗi bản ghi phải tự mang theo phần lời (`reply`) chứ không chỉ mang
    bảng: có những câu mà câu trả lời đúng là một câu nói, không phải mười lăm món hàng.
    """

    #: Câu hỏi vừa được gửi, chép nguyên văn — để lượt này tự đọc được khi lật lại lịch sử.
    seed: str
    country: str
    mode: AnswerMode = "products"
    #: Lời đáp bằng tiếng Việt thường. LUÔN có, kể cả khi có bảng: đây là chỗ nói ra ý chính
    #: mà một bảng không nói được.
    reply: str = ""
    #: Bối cảnh mà mô hình hiểu ra, để người dùng bắt lỗi hiểu sai. Chỉ có ở `mode=products`.
    situation: str = ""
    items: list[OpportunityItem] = []
    #: Vài câu hỏi tiếp theo bấm được. Người dùng mới không biết công cụ này trả lời được gì,
    #: và một danh sách gợi ý dạy điều đó nhanh hơn mọi dòng hướng dẫn.
    follow_ups: list[str] = []
    message: str | None = None
    took_ms: int = 0
