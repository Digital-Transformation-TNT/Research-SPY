"""
Rút MÃ SẢN PHẨM ra khỏi tiêu đề của các bảng kết quả.

VÌ SAO CẦN. Tên món ("máy sấy tóc") tra ở đâu cũng ra hàng nghìn thứ khác nhau; mã model
("BHD321") tra ra đúng một món. Với người đi nhập, mã là thứ nhắn cho xưởng để chắc chắn hai
bên đang nói về cùng một sản phẩm, và là thứ gõ vào ô tìm kiếm của sàn để so giá.

VÌ SAO XẾP HẠNG THEO SỐ LẦN XUẤT HIỆN, KHÔNG LỌC BẰNG LUẬT. Không có biểu thức nào phân biệt
được mã model thật với một chuỗi chữ-số ngẫu nhiên trong tiêu đề — "G304" và "A63" trông y
hệt nhau. Nhưng mã THẬT thì lặp lại: người bán nào cũng chép nó vào tiêu đề. Đo trên kho
cache hiện có, cách xếp này tách rất sạch:

    G304    42 lần, 3 bảng      <- mã thật
    BHD321  20 lần              <- mã thật
    TS3429  12 lần              <- mã thật
    A63      1 lần              <- nhiễu
    SPEED    1 lần              <- nhiễu

Nên chỗ này TRẢ VỀ HẾT kèm số đếm và tên bảng, để người dùng tự đọc độ tin cậy — đúng luật
"xếp hạng, đừng lặng lẽ vứt" đang dùng ở khắp repo. Vứt mã một-lần đi thì cũng vứt luôn mã
của những món chỉ có vài người bán.

MÃ HÃNG KHÁC MÃ XƯỞNG, và khác biệt ấy quyết định mã có tra ngược được hay không. Đo ngày
2026-08-19 (`scripts/probe/code_bridge.py`): `G304` tra `site:shopee.vn` ra 8 trang sản
phẩm, còn `T15S`/`N612` lấy từ tiêu đề 1688 ra số không — người bán Việt Nam không dịch tiêu
đề 1688, họ viết tiêu đề mới và tự đặt mã riêng. Vì vậy trường `sources` phải đi kèm: một mã
chỉ thấy ở bảng 1688 là mã xưởng, đừng mong gõ nó vào Shopee; một mã thấy ở cả bảng "Nơi
đang bán" thì chính thị trường Việt Nam đang gọi món này bằng tên đó.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

#: Ứng viên mã: bắt đầu bằng CHỮ, dài 3-14, và phải có ít nhất một CHỮ SỐ.
#:
#: Bắt buộc có chữ số để loại các từ thường ("Wireless", "Gaming"). Bắt buộc bắt đầu bằng chữ
#: để loại thông số kỹ thuật, thứ luôn mở đầu bằng số và luôn trông giống mã: `1800W`,
#: `12000DPI`, `2000mAh`, `180g`. Đây đúng là cái bẫy đã ghi ở `identify.py` khi dặn Gemini.
#:
#: BIÊN TỰ VIẾT TAY, KHÔNG DÙNG `\b`. Trong Unicode, chữ Hán LÀ ký tự từ, nên giữa `境`
#: và `G` của "跨境G304无线游戏鼠标" KHÔNG có ranh giới từ — `\bG304\b` trượt sạch mọi
#: tiêu đề 1688 và Taobao. Bản đầu mắc đúng lỗi này, và nó còn làm sai cả phép đo: "1688
#: chỉ có 2/96 tiêu đề mang mã" hoá ra là 2/96 tiêu đề có mã ĐỨNG CẠNH KHOẢNG TRẮNG, chứ
#: không phải 2/96 tiêu đề có mã. Biên đúng ở đây là "không kề chữ Latin hay chữ số".
_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?=[A-Za-z0-9-]{3,14}(?![A-Za-z0-9]))"
    r"(?=[A-Za-z0-9-]*\d)"
    r"[A-Za-z][A-Za-z0-9-]{2,13}"
    r"(?![A-Za-z0-9])"
)

#: Chuỗi có chữ-và-số nhưng KHÔNG BAO GIỜ là mã model. Danh sách ngắn và chỉ chứa thứ đã thật
#: sự thấy trong dữ liệu — một danh sách đoán trước sẽ vứt nhầm mã thật của hãng nào đó.
_NOT_CODE = {
    "3D", "2D", "4K", "8K", "1080P", "720P",
    "USB2", "USB3", "TYPE-C", "USB-C",
    "MP3", "MP4", "H2O", "PM2",
    "COVID19", "NO1", "NO2", "TOP1",
}


#: "dùng cho…" / "tương thích…" trong tiêu đề Trung Quốc — dấu hiệu đây là PHỤ KIỆN cho một
#: món khác, không phải chính món ấy. "适用罗技g304防滑贴" là miếng dán DÙNG CHO chuột G304,
#: giá ¥4.5, và nó không liên quan gì tới giá bán một con chuột.
#:
#: `(?!于)` là chi tiết quan trọng chứ không phải làm đẹp: "适用于游戏电竞办公" nghĩa là "dùng
#: được cho việc chơi game, văn phòng" — một câu quảng cáo bình thường trên tiêu đề CHUỘT
#: THẬT. Thiếu dấu loại trừ ấy thì một phần hàng thật bị gắn nhãn phụ kiện.
#:
#: Đo trên 96 tiêu đề 1688 đang nằm trong cache, đối chiếu với danh sách từ chỉ phụ kiện
#: (防滑贴, 贴纸, 鼠标垫, 保护套…): trùng khớp 96/96, không sót và không báo oan.
_FOR_OTHER = re.compile(r"适(?:用|配)(?!于)")


def is_accessory(title: str) -> bool:
    """Tiêu đề này là PHỤ KIỆN cho món khác, chứ không phải chính món ấy?"""
    return bool(_FOR_OTHER.search(title or ""))


def codes_in(title: str) -> list[str]:
    """Các mã ứng viên trong MỘT tiêu đề, viết hoa, không trùng, giữ thứ tự xuất hiện."""
    out: list[str] = []
    for raw in _CANDIDATE.findall(title or ""):
        code = raw.upper()
        if code not in _NOT_CODE and code not in out:
            out.append(code)
    return out


def extract_codes(titles_by_table: dict[str, list[str]]) -> list[tuple[str, int, list[str]]]:
    """
    `{tên bảng: [tiêu đề]}` → `[(mã, số lần, [tên bảng])]`, nhiều lần nhất đứng trước.

    Đếm theo DÒNG chứ không theo lần xuất hiện: một tiêu đề nhắc "PH1627" ba lần vẫn chỉ tính
    một. Nếu không, một người bán viết tiêu đề nhồi từ khoá sẽ tự đẩy mã của mình lên đầu.
    """
    counts: Counter[str] = Counter()
    tables: defaultdict[str, set[str]] = defaultdict(set)

    for table, titles in titles_by_table.items():
        for title in titles:
            # `set` cho mỗi tiêu đề — xem ghi chú "đếm theo DÒNG" ở trên.
            for raw in set(_CANDIDATE.findall(title or "")):
                code = raw.upper()
                if code in _NOT_CODE:
                    continue
                counts[code] += 1
                tables[code].add(table)

    # Nhiều lần trước; bằng nhau thì mã xuất hiện ở NHIỀU BẢNG hơn đứng trước (được nhiều
    # nguồn độc lập xác nhận thì đáng tin hơn); vẫn bằng thì theo bảng chữ cái cho ổn định.
    def rank(item: tuple[str, int]) -> tuple[int, int, str]:
        code, count = item
        return (-count, -len(tables[code]), code)

    return [(code, count, sorted(tables[code])) for code, count in sorted(counts.items(), key=rank)]
