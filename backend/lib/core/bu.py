"""
ĐƠN VỊ KINH DOANH (BU) — danh sách chốt, và chính sách đi theo từng BU.

ĐÂY LÀ NƠI DUY NHẤT PHẢI SỬA khi công ty thêm/bớt một BU. Ba nơi đọc nó: ô đăng ký, ô admin
tạo tay, và ngưỡng xanh của bảng Giá vốn.

VÌ SAO PHẢI CHỐT DANH SÁCH. Trước 2026-09-10 `bu` là một ô CHỮ TỰ DO, và bốn tài khoản đầu
tiên đã đẻ ra ba cách viết cho cùng một đơn vị:

    "Holding"  ×2      "Hoding"  ×1  (gõ thiếu chữ)      "HO"  ×1

Với một ô hồ sơ để hiển thị thì ba cách viết ấy chỉ hơi xấu. Nhưng từ lúc BU quyết định một
CON SỐ — ngưỡng xanh của tỷ giá — thì nó thành lỗi thật: "Hoding" không khớp khoá nào, nên
người ấy âm thầm rơi về ngưỡng mặc định, và không có gì trên màn hình nói rằng họ vừa được
áp một chính sách khác đồng nghiệp cùng phòng. Ô chọn thay ô gõ là cách rẻ nhất để chặn.

NGƯỠNG XANH KHÔNG PHẢI MỘT CON SỐ CHUNG. Nó là mức chênh giá vốn tối thiểu để một sản phẩm
được tô xanh (đáng nhập). BU1 đặt 20%, các đơn vị còn lại 30% — khác nhau vì cơ cấu chi phí
khác nhau, không phải vì ai đó quên đồng bộ.

ĐÂY CHỈ LÀ MẶC ĐỊNH, KHÔNG PHẢI KHOÁ. Người dùng vẫn tự chỉnh được trong modal Giá vốn và lựa
chọn của họ được nhớ lại; BU chỉ quyết định con số họ thấy ở lần đầu. Xem
`frontend/public/research/research.js::costThresh`.
"""

from __future__ import annotations

#: Ngưỡng xanh mặc định (%) theo từng BU. Khoá của dict CHÍNH LÀ danh sách BU hợp lệ — giữ
#: một chỗ thay vì một danh sách và một bảng tra rời nhau, vì hai cái rời nhau thì thêm BU mới
#: sẽ sửa được một chỗ và quên chỗ kia.
BU_FX_GREEN_THRESHOLD: dict[str, int] = {
    "BU1": 20,
    "BU2": 30,
    "BU3": 30,
    "HO": 30,
}

#: Thứ tự hiện trong ô chọn. Không sắp lại theo bảng chữ cái — BU1/BU2/BU3 rồi HO là thứ tự
#: người trong công ty vẫn đọc.
BU_CHOICES: list[str] = list(BU_FX_GREEN_THRESHOLD)

#: Dùng khi hồ sơ chưa có BU, hoặc BU ghi bằng một cách viết không còn nhận ra. Bằng đúng con
#: số của phần lớn BU, nên một hồ sơ hỏng không tự nhiên được ưu ái hơn ai.
FX_GREEN_THRESHOLD_DEFAULT = 30


def normalize_bu(raw: str | None) -> str | None:
    """
    Chuỗi thô → một mã trong `BU_CHOICES`, hoặc `None` nếu không nhận ra.

    So khớp KHÔNG phân biệt hoa thường và bỏ khoảng trắng, vì "bu1" / "BU 1" là cùng một đơn
    vị và bắt người dùng gõ đúng từng ký tự chỉ đẻ thêm dữ liệu rác.
    """
    gọn = (raw or "").strip().upper().replace(" ", "").replace("-", "").replace("_", "")
    return gọn if gọn in BU_FX_GREEN_THRESHOLD else None


def fx_green_threshold(raw_bu: str | None) -> int:
    """Ngưỡng xanh (%) cho một BU. BU lạ hoặc trống → `FX_GREEN_THRESHOLD_DEFAULT`."""
    mã = normalize_bu(raw_bu)
    return BU_FX_GREEN_THRESHOLD.get(mã or "", FX_GREEN_THRESHOLD_DEFAULT)
