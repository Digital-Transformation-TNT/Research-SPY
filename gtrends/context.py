"""Ba ô chọn của giao diện Google Trends, gói thành một vật."""

from __future__ import annotations

from dataclasses import dataclass

#: Cửa sổ thời gian mặc định. Cùng chuỗi mà /explore dùng cho "Năm qua".
DEFAULT_TIME_RANGE = "today 12-m"

#: `country` cho phạm vi "Toàn thế giới".
#:
#: Trends thể hiện toàn cầu bằng cách BỎ HẲN tham số `geo` chứ không bằng một mã riêng. Ở đây
#: nó vẫn cần một tên, vì chuỗi rỗng đi qua vài tầng thì sẽ có tầng đọc ra thành "chưa chọn".
WORLDWIDE = "WORLD"


@dataclass(frozen=True)
class TrendsContext:
    """
    Tìm Ở ĐÂU, TRONG BAO LÂU, trên KHO DỮ LIỆU NÀO.

    Gói thành một vật thay vì ba tham số rời vì chúng luôn đi cùng nhau, và vì để nguyên như
    thế thì thêm một ô chọn thứ tư sau này không phải sửa chữ ký hàm ở mọi tầng.
    """

    #: Mã quốc gia hai chữ (`VN`, `US`, `PH`) hoặc `WORLDWIDE`.
    country: str = "VN"
    #: Cửa sổ thời gian của Trends: `now 1-H`, `now 7-d`, `today 12-m`, `all`, hoặc một khoảng
    #: tuỳ chỉnh dạng `2025-01-01 2025-12-31`.
    time_range: str = DEFAULT_TIME_RANGE
    #: Kho dữ liệu: rỗng = Tìm kiếm trên web, `images`, `news`, `froogle` (Google Mua sắm),
    #: `youtube`.
    gprop: str = ""
