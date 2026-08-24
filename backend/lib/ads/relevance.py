"""
Cụm từ người dùng tìm có THẬT SỰ nằm trong nội dung quảng cáo không?

VÌ SAO CẦN TẦNG NÀY, đo ngày 2026-08-19 bằng `scripts/probe/fb_quotes.py` trên "kem chống nắng":

    ✅ Cỏ Mềm    🌞 Kem chống nắng Hây Hây - "Chân ái" cho nàng lười makeup
    ❌ Nội Y 02  sale 99K/3 MŨ CHỐNG NẮNG …            ← mũ, không phải kem
    ❌ Cỏ mềm    🥰Kem dưỡng mắt Sâm 1700 …             ← kem mắt
    ❌ Arencia   ✨ Routine dưỡng da sáng mịn ngày&đêm  ← không có cụm này ở đâu cả

`keyword_exact_phrase` của Facebook khớp cụm từ ở ĐÂU ĐÓ trong dữ liệu quảng cáo — tên trang,
đường dẫn, trang đích — chứ KHÔNG bắt buộc nằm trong phần chữ người xem đọc được. Đó là lý do
chế độ chính xác nhất của họ vẫn chỉ đạt 60–80% đúng chủ đề (con số ghi ở `SEARCH_TYPE` trong
`platforms/facebook.py`). Tầng này bù đúng phần còn thiếu ấy, ở phía mình.

XẾP HẠNG, TUYỆT ĐỐI KHÔNG LOẠI BỎ. Một quảng cáo không chứa cụm từ vẫn có thể là quảng cáo đáng
xem — cùng nhà quảng cáo, cùng ngành hàng, hoặc cụm từ nằm trong ảnh mà ta không đọc được. Và
quan trọng hơn: bảng ngắn đi thì người dùng đọc thành "sản phẩm này không ai chạy quảng cáo",
đúng kiểu hỏng mà `PlatformSearchOutcome.notice` được sinh ra để tránh. Nên thứ ở đây là một cờ
để xếp thứ tự và để giao diện ghi chú, không phải một bộ lọc.

BA BƯỚC CHUẨN HOÁ, mỗi bước vì một thứ có thật trong dữ liệu quảng cáo tiếng Việt:

    NFKC        quảng cáo Facebook đầy chữ Unicode kiểu cách: `𝗖𝗵𝘂 𝘁𝗿𝗶̀𝗻𝗵` là chữ toán học in
                đậm, không phải `Chu trinh`. NFKC gấp chúng về chữ Latin thường — thiếu bước này
                thì mọi quảng cáo trình bày kiểu ấy đều bị coi là lệch chủ đề
    bỏ dấu       người bán gõ "kem chong nang" cũng nhiều như "kem chống nắng"
    gộp khoảng   emoji, gạch đầu dòng và xuống dòng chen vào giữa cụm từ
"""

from __future__ import annotations

import re
import unicodedata

#: Mọi thứ không phải chữ-số đều thành một khoảng trắng. Nhờ vậy "Kem-chống-nắng" và
#: "Kem 🌞 chống nắng" đều gộp về cùng một dạng.
_NOT_WORD = re.compile(r"[^0-9a-z]+")


def normalize(text: str) -> str:
    """
    Dạng so sánh được của một đoạn chữ: `" kem chong nang "`, có khoảng trắng ở hai đầu.

    Giữ khoảng trắng bao quanh là chi tiết quan trọng chứ không phải làm đẹp: nhờ nó, phép kiểm
    `cụm in chuỗi` mới là so theo TỪ. Không có nó thì "nắng" khớp vào "nắng" của "mũ chống
    nắng" đã đành, mà "kem" còn khớp vào "kemono" — tức khớp giữa từ, một kiểu dương tính giả
    rất khó nhìn ra khi đọc bảng kết quả.
    """
    if not text:
        return " "
    folded = unicodedata.normalize("NFKC", text).casefold()
    # Tách dấu ra thành ký tự riêng rồi bỏ chúng đi. `NFD` sau `NFKC` là đúng thứ tự: gấp chữ
    # kiểu cách về Latin trước, rồi mới bóc dấu.
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", folded) if not unicodedata.combining(ch)
    )
    return f" {_NOT_WORD.sub(' ', stripped).strip()} "


def phrase_hit(haystack_parts: list[str | None], keyword: str) -> bool:
    """
    Cụm từ khoá có xuất hiện trong một trong các đoạn chữ đó không.

    Từ khoá rỗng thì trả về `True` cho mọi quảng cáo — không có gì để đối chiếu thì không có cơ
    sở nào để nói cái nào lệch chủ đề, và mặc định "mọi thứ đều lệch" sẽ đảo lộn cả bảng.
    """
    needle = normalize(keyword).strip()
    if not needle:
        return True
    return any(f" {needle} " in normalize(part or "") for part in haystack_parts)
