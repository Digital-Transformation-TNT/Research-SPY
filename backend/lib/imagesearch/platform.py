"""
Xếp kết quả Lens vào SÀN nào, để giao diện dựng được dãy chip lọc kèm số đếm.

MỘT LƯỢT LENS, LỌC TẠI CHỖ. Đây là cả lý do file này tồn tại. Lens không nhận tham số sàn, nên
dù người dùng muốn xem Shopee hay Lazada thì ta vẫn gửi đúng một tấm ảnh và vẫn nhận về đúng
một bảng. Bắt chọn sàn TRƯỚC khi gọi chỉ có một tác dụng: vứt bớt thứ vừa trả một suất hạn mức
để lấy về. Vì vậy việc phân nhóm nằm ở đây — tầng đọc — chứ không nằm trong `SOURCES`.

Hệ quả bắt buộc, và nó ràng buộc cả `search.py`: **khoá cache không được mang tên sàn.** Bảng
đầy đủ vào cache, lọc lúc đọc. Nhét sàn vào khoá (`v2:{key}:{country}:shopee`) thì người dùng
bấm từ Shopee sang Lazada là đốt thêm một suất Lens cho đúng tấm ảnh vừa tra xong.

KHỚP TÊN MIỀN CHÍNH XÁC, KHÔNG KHỚP CHUỖI CON. Đo trên cache thật ngày 2026-08-19: cùng một
lượt tìm trả về `shopee.vn`, `shopee.ph`, `shopee.com.br` VÀ `shopee.com.ar`. Một phép kiểm
`"shopee" in host` sẽ gom cả bốn vào một chỗ, và người bán hàng Việt Nam nhận được giá của
Philippines mà không có dấu hiệu nào báo sai — đúng họ với cái bẫy `shopee.com.mx` trả về dữ
liệu Brazil đã ghi ở `lib/keywords/providers/shopee.py`.

SỐ KHÔNG CŨNG PHẢI HIỆN. `TikTok 0` là một câu trả lời có thật ("ảnh này không tìm thấy hàng
trên TikTok"), khác hẳn với việc không có chip TikTok nào — thứ mà người đọc sẽ hiểu thành
"công cụ không tra TikTok". Vì vậy `tally` luôn trả về đủ mọi sàn, kể cả sàn rỗng.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .types import ImageMatch, PlatformCount

#: Khoá dành cho mọi thứ không thuộc sàn nào — và nó KHÔNG phải rác.
#:
#: `dienmayxanh`, `cellphones`, `fptshop` là giá bán lẻ chính hãng ở Việt Nam, tức là mốc để so
#: với giá trên sàn. Vứt chúng đi là vứt mất nửa câu chuyện về giá.
OTHER = "other"

#: Các sàn, kèm tên miền được tính là thuộc sàn đó. Thứ tự ở đây là thứ tự chip trên giao diện.
#:
#: Chỉ tên miền VIỆT NAM. `shopee.ph` là một sàn có thật, chỉ là không phải thị trường mà người
#: dùng đang hỏi — nó rơi vào `OTHER` chứ không bị xoá, để ai tò mò vẫn bấm thấy.
PLATFORMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("shopee", "Shopee", ("shopee.vn",)),
    ("lazada", "Lazada", ("lazada.vn",)),
    # TikTok gộp cả `tiktok.com` lẫn `shop.tiktok.com`. Cần biết trước khi đọc con số này: phần
    # lớn link TikTok mà Lens trả về là VIDEO chứ không phải trang hàng TikTok Shop — đo
    # 2026-08-19 thấy `tiktok.com/@hi.shop_168/video/…`. Con số vẫn có ích (ai đang review món
    # này), nhưng đừng đọc nó thành "bao nhiêu shop TikTok đang bán".
    ("tiktok", "TikTok", ("tiktok.com",)),
)

OTHER_LABEL = "Nơi khác"


def _host(link: str) -> str:
    """Tên miền của một đường dẫn, đã bỏ `www.`. Chuỗi rỗng khi đường dẫn hỏng."""
    try:
        host = urlparse(link).netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def platform_of(link: str) -> str:
    """
    Sàn của một đường dẫn: `shopee`, `lazada`, `tiktok`, hoặc `other`.

    Khớp bằng "đúng tên miền, hoặc là tên miền con của nó" — `shop.tiktok.com` thuộc TikTok,
    còn `shopee.ph` thì không thuộc Shopee. Xem lập luận ở đầu file.
    """
    host = _host(link)
    if not host:
        return OTHER
    for key, _, domains in PLATFORMS:
        for domain in domains:
            if host == domain or host.endswith(f".{domain}"):
                return key
    return OTHER


def label_platforms(matches: list[ImageMatch]) -> list[ImageMatch]:
    """
    Gắn `platform` cho từng dòng, TÍNH RA chứ không đọc từ kho.

    Cố ý suy lại mỗi lần đọc thay vì lưu vào cache: bảng Lens có TTL ba mươi ngày, nên nếu
    trường này được lưu thì mọi bản ghi cũ sẽ mang `platform` rỗng cho tới tận tháng sau — và
    cách chữa duy nhất là nâng khoá cache, tức là đốt lại hạn mức Lens cho những tấm ảnh đã tra
    rồi. Suy từ `link` thì bản ghi cũ chạy đúng ngay lập tức.
    """
    for item in matches:
        item.platform = platform_of(item.link)
    return matches


def tally(matches: list[ImageMatch]) -> list[PlatformCount]:
    """
    Số đếm mỗi sàn, LUÔN đủ mọi sàn kể cả sàn bằng không — xem lập luận ở đầu file.

    Không kèm mục "Tất cả": nó là tổng của phần còn lại, và một con số suy ra được mà vẫn gửi
    kèm là một con số có thể lệch với phần còn lại. Giao diện tự cộng.
    """
    counts = {key: 0 for key, _, _ in PLATFORMS}
    counts[OTHER] = 0
    for item in matches:
        counts[platform_of(item.link)] += 1

    rows = [PlatformCount(id=key, label=label, count=counts[key]) for key, label, _ in PLATFORMS]
    rows.append(PlatformCount(id=OTHER, label=OTHER_LABEL, count=counts[OTHER]))
    return rows
