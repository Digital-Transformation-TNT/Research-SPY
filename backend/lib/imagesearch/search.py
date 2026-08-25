"""
Ghép các tầng lại thành một câu trả lời, và giữ hạn mức của những nguồn khan hiếm.

SÁU TẦNG CHẠY SONG SONG VÀ ĐỘC LẬP NHAU:

    identify.py    ảnh → tên món, thương hiệu, cụm tìm vi/zh/en      ~3s, gần như không trượt
    lens.py        ảnh → sản phẩm tương tự kèm link, giá, đánh giá   ~20s, CÓ HẠN MỨC
    ali.py         ảnh → chào hàng 1688 kèm giá sỉ và nhà cung cấp   ~3s, không hạn mức
    alibaba.py     ảnh → bán buôn xuất khẩu kèm giá ₫ và MOQ         ~4s, siết sau vài lượt dồn
    taobao.py      ảnh → hàng bán lẻ Trung Quốc kèm giá và lượt mua  ~30s, CẦN ĐĂNG NHẬP
    aliexpress.py  ảnh → bán lẻ quốc tế kèm giá ₫ ship về VN         ~5s, CÓ HẠN MỨC THEO IP

Thiết kế xoay quanh đúng một điều: **hạn mức của Lens là tài nguyên khan hiếm nhất**, không
phải tốc độ. Từ đó ra hai luật ở file này.

LUẬT 1 — HỎNG MỀM. Lens chạm hạn mức thì trả về phần `identity` kèm một câu nói, chứ KHÔNG
ném lỗi. Người dùng vẫn có tên món và cụm để tự gõ sang sàn; màn hình không bao giờ trông như
hỏng. Đây là lý do `LensUnavailable` là một kiểu riêng chứ không phải `RuntimeError` trần.

LUẬT 2 — CACHE THEO VÂN TAY ẢNH, GHI XUỐNG ĐĨA. Khoá là `sha256` của chính bytes ảnh, nên hai
người tải lên cùng một ảnh sản phẩm chỉ tốn MỘT suất. Dùng `DiskStore` chứ không phải
`cache.py` vì đúng lập luận đã viết ở `store.py`: thứ nằm đây đắt và có hạn mức, không được
chết theo một lần restart — mà backend thì chạy không có `--reload` nên mỗi lần sửa code là
một lần xoá sạch bộ nhớ.

MỖI NGUỒN MỘT RỔ RIÊNG, cố ý. Kết quả chỉ được cache KHI CÓ, để lượt sau còn thử lại sau khi
hết treo. Phần đọc ảnh thì cache riêng và lâu hơn nhiều, vì nội dung một tấm ảnh không bao giờ
đổi — nhờ vậy những lượt thử lại ấy không phải trả tiền Gemini thêm lần nào.

ĐỘ DÀI CACHE THEO ĐỘ KHAN HIẾM, không theo độ tươi của dữ liệu. Nguồn gọi lại rẻ (1688,
Alibaba.com) để bảy ngày; nguồn có trần chặt (Lens ~15 lượt/ngày, AliExpress ~2 lượt rồi nghỉ
một ngày) để ba mươi ngày, vì với chúng thứ đắt nhất là SUẤT GỌI chứ không phải vài phần trăm
chênh giá.

TẦNG 1688 KHÔNG ĐƯỢC PHÉP LÀM HỎNG CẢ LƯỢT TÌM, và nó cũng không cần được nâng niu như Lens:
không hạn mức, không trình duyệt, một lượt chỉ hai request. Vì vậy nó cache ngắn hơn hẳn —
giá sỉ và tồn kho của xưởng đổi nhanh hơn nhiều so với bảng "ai đang bán món này".
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from lib.core.store import DiskStore

from .ali import search_offers
from .alibaba import AlibabaUnavailable, search_offers as search_global_offers
from .aliexpress import AliexpressUnavailable, search_products
from .identify import identify
from .lens import LensUnavailable, MAX_MATCHES, fetch_cards, parse_card
from .taobao import TaobaoUnavailable, fetch_items
from .platform import label_platforms, tally
from lib.core.config import env_number

from .types import ImageIdentity, ImageMatch, ImageSearchResult

#: Nội dung một tấm ảnh không đổi, nên bản đọc của nó cũng vậy. Để rất lâu.
IDENTITY_TTL_MS = 90 * 24 * 60 * 60 * 1000

#: Bảng hàng tương tự thì có đổi, nhưng chậm — món mới lên sàn không làm sai bảng cũ trong
#: một tháng. Ba mươi ngày là đổi độ tươi lấy hạn mức, và ở đây hạn mức đắt hơn nhiều.
MATCHES_TTL_MS = 30 * 24 * 60 * 60 * 1000

#: Giá sỉ và nhà cung cấp đổi nhanh hơn bảng bán lẻ — bảy ngày là đủ để đỡ gọi lại trong một
#: buổi làm việc, và đủ ngắn để không đưa ra một mức giá đã cũ cả tháng.
SOURCING_TTL_MS = 7 * 24 * 60 * 60 * 1000

#: Các nguồn CHỌN ĐƯỢC, kèm cái giá thật của mỗi nguồn — đó là lý do chúng chọn được chứ không
#: chạy hết mọi lượt:
#:
#:     1688        ~3s    HTTP thuần, không hạn mức, không đăng nhập
#:     alibaba     ~4s    HTTP thuần, không đăng nhập, KHÔNG cần ký MTOP, CÓ siết theo tần suất
#:     aliexpress  ~5s    HTTP thuần, không đăng nhập, nhưng CÓ tường tần suất theo IP
#:     taobao      ~30s   mở một cửa sổ Chrome, CẦN phiên đăng nhập
#:     lens        ~20s   mở một cửa sổ Chrome, HẠN MỨC ~15 lượt/IP/buổi
#:
#: Trước đây cả ba luôn chạy, nên một lượt chỉ cần bảng giá sỉ vẫn đốt một suất Lens và mở hai
#: cửa sổ trình duyệt. Với nguồn khan hiếm nhất của cả hệ thống thì đó là lãng phí có thật.
SOURCES = ("1688", "alibaba", "aliexpress", "taobao", "lens")

#: Tỷ giá ¥ → ₫ mặc định, đổi được bằng `CNY_VND_RATE` trong `.env.local`.
#:
#: Là một SỐ CỐ ĐỊNH chứ không gọi API tỷ giá, và đó là lựa chọn có chủ ý: thêm một nguồn
#: mạng nữa là thêm một thứ có thể chết, mà khi nó chết thì mọi bội số trên trang sai cùng
#: lúc và không ai nhận ra. Con số này hiện thẳng lên giao diện nên người đọc luôn biết mình
#: đang nhìn một giả định, và sửa nó mất đúng một dòng.
DEFAULT_CNY_VND = 3700.0

#: Chỉ nguồn RẺ được bật sẵn. Hai nguồn kia phải người dùng tự bật — mặc định bật một thứ có
#: hạn mức là cách chắc chắn để tiêu hết hạn mức vào những lượt không ai cần tới nó.
DEFAULT_SOURCES = ("1688",)

_identities = DiskStore("imagesearch-identity")
_matches = DiskStore("imagesearch-matches")
_sourcing = DiskStore("imagesearch-sourcing")
_global_sourcing = DiskStore("imagesearch-alibaba")
_china_retail = DiskStore("imagesearch-taobao")
_global_retail = DiskStore("imagesearch-aliexpress")


def fingerprint(image: bytes) -> str:
    """Vân tay của ảnh. Rút gọn còn 16 ký tự — đủ để không đụng nhau, ngắn để đọc được khi debug."""
    return hashlib.sha256(image).hexdigest()[:16]


def _sorted_matches(cards) -> list[ImageMatch]:
    """
    Trang bán hàng lên trước, phần còn lại giữ nguyên thứ tự của Google.

    Không LOẠI BỎ trang không phải sàn: một bài đánh giá hay một trang hãng vẫn có ích, nó chỉ
    không nên đứng trên một chỗ mua được. `enumerate` giữ thứ tự gốc trong mỗi nhóm — đó là thứ
    tự liên quan mà Google đã xếp, và ta không có thông tin gì tốt hơn để xếp lại.
    """
    parsed = [p for p in (parse_card(card) for card in cards) if p]

    seen: set[str] = set()
    unique = []
    for item in parsed:
        if item["link"] in seen:
            continue
        seen.add(item["link"])
        unique.append(item)

    ranked = sorted(enumerate(unique), key=lambda pair: (not pair[1]["marketplace"], pair[0]))
    return [ImageMatch(**item) for _, item in ranked[:MAX_MATCHES]]


async def _read_identity(image: bytes, mime: str, key: str) -> tuple[ImageIdentity | None, str | None]:
    cached = _identities.get(key)
    if cached is not None:
        return ImageIdentity(**cached), None
    try:
        found = await identify(image, mime)
    except Exception as error:
        return None, f"Chưa đọc được ảnh: {error}"
    if found is None:
        return None, "Chưa cấu hình GEMINI_API_KEY nên chưa đọc được ảnh"
    _identities.set(key, found.model_dump(), IDENTITY_TTL_MS)
    return found, None


async def _read_matches(image: bytes, mime: str, key: str) -> tuple[list[ImageMatch], str | None]:
    cached = _matches.get(key)
    if cached is not None:
        return [ImageMatch(**item) for item in cached], None
    try:
        cards = await fetch_cards(image, mime)
    except LensUnavailable as error:
        # Hạn mức, không phải hỏng. Câu này đi thẳng ra giao diện nên nó phải nói được việc
        # người dùng làm tiếp — xem LUẬT 1 ở đầu file.
        return [], str(error)
    except Exception as error:
        return [], f"Chưa lấy được sản phẩm tương tự: {error}"

    matches = _sorted_matches(cards)
    if matches:
        _matches.set(key, [m.model_dump() for m in matches], MATCHES_TTL_MS)
    return matches, None if matches else "Không tìm thấy sản phẩm nào giống ảnh này"


async def _read_sourcing(image: bytes, key: str) -> tuple[list[ImageMatch], str | None]:
    """
    Chào hàng 1688. Lỗi ở đây trả về câu nói chứ KHÔNG ném ra ngoài.

    Nguồn này không có hạn mức nên không cần kiểu lỗi riêng như `LensUnavailable`: mọi thứ
    hỏng ở đây đều là hỏng thật (ảnh sai định dạng, cổng đổi tham số, mạng gãy), và cách xử lý
    giống hệt nhau — nói ra rồi để hai tầng kia chạy tiếp.
    """
    cached = _sourcing.get(key)
    if cached is not None:
        return [ImageMatch(**item) for item in cached], None
    try:
        rows = await search_offers(image)
    except Exception as error:
        return [], f"Chưa lấy được nguồn hàng 1688: {error}"

    offers = [ImageMatch(**row) for row in rows]
    if offers:
        _sourcing.set(key, [o.model_dump() for o in offers], SOURCING_TTL_MS)
    return offers, None


async def _read_china_retail(
    image: bytes, mime: str, key: str
) -> tuple[list[ImageMatch], str | None]:
    """
    Hàng bán lẻ Taobao. Cùng luật hỏng-mềm với Lens, và vì cùng một lý do: nguồn này cần một
    thứ bên ngoài code (phiên đăng nhập) nên nó SẼ vắng mặt, đều đặn, chứ không phải hi hữu.
    """
    cached = _china_retail.get(key)
    if cached is not None:
        return [ImageMatch(**item) for item in cached], None
    try:
        rows = await fetch_items(image, mime)
    except TaobaoUnavailable as error:
        return [], str(error)
    except Exception as error:
        return [], f"Chưa lấy được hàng Taobao: {error}"

    items = [ImageMatch(**row) for row in rows]
    if items:
        _china_retail.set(key, [i.model_dump() for i in items], SOURCING_TTL_MS)
    return items, None


async def _read_global_sourcing(image: bytes, key: str) -> tuple[list[ImageMatch], str | None]:
    """
    Chào hàng bán buôn quốc tế trên Alibaba.com. Cùng luật nuốt-lỗi-thành-câu-nói với 1688.

    `AlibabaUnavailable` đi ra NGUYÊN VĂN, không bọc thêm chữ: câu của nó đã nói rõ đây là siết
    tần suất chứ không phải ảnh sai, và bọc nó vào "Chưa lấy được nguồn hàng Alibaba.com: …"
    chỉ làm loãng đúng phần người dùng cần đọc.
    """
    cached = _global_sourcing.get(key)
    if cached is not None:
        return [ImageMatch(**item) for item in cached], None
    try:
        rows = await search_global_offers(image)
    except AlibabaUnavailable as error:
        return [], str(error)
    except Exception as error:
        return [], f"Chưa lấy được nguồn hàng Alibaba.com: {error}"

    offers = [ImageMatch(**row) for row in rows]
    if offers:
        _global_sourcing.set(key, [o.model_dump() for o in offers], SOURCING_TTL_MS)
    return offers, None


async def _read_global_retail(
    image: bytes, key: str, country: str
) -> tuple[list[ImageMatch], str | None]:
    """
    Hàng bán lẻ quốc tế trên AliExpress. Hỏng mềm như Lens, và vì cùng một lý do: bước lấy kết
    quả có tường tần suất theo IP nên nó SẼ vắng mặt đều đặn chứ không phải hi hữu.

    CACHE LÂU BẰNG BẢNG LENS chứ không bằng bảng 1688 — cùng `MATCHES_TTL_MS`. Nguồn có hạn
    mức thì thứ đắt nhất không phải độ tươi của giá mà là suất gọi: một bản ghi ba mươi ngày
    cũ vẫn trả lời được "khách tự đặt về khoảng bao nhiêu", còn một lượt gọi bị chặn thì không
    trả lời được gì.
    """
    cached = _global_retail.get(key)
    if cached is not None:
        return [ImageMatch(**item) for item in cached], None
    try:
        rows = await search_products(image, country=country)
    except AliexpressUnavailable as error:
        return [], str(error)
    except Exception as error:
        return [], f"Chưa lấy được hàng AliExpress: {error}"

    items = [ImageMatch(**row) for row in rows]
    if items:
        _global_retail.set(key, [i.model_dump() for i in items], MATCHES_TTL_MS)
    return items, None


async def _skip() -> tuple[list[ImageMatch], str | None]:
    """Nguồn không được chọn: rỗng và KHÔNG có câu nói nào.

    Cố ý không trả về "bạn chưa bật nguồn này" — người dùng vừa tự tắt nó, nhắc lại là nói cho
    họ nghe điều họ vừa làm."""
    return [], None


async def search_by_image(
    image: bytes,
    mime: str,
    country: str = "VN",
    sources: tuple[str, ...] | None = None,
) -> ImageSearchResult:
    """
    Tìm sản phẩm từ một tấm ảnh, chỉ hỏi những nguồn được chọn.

    `sources` là tập con của `SOURCES`; `None` nghĩa là dùng `DEFAULT_SOURCES`. Tầng đọc ảnh
    (Gemini) LUÔN chạy và không nằm trong danh sách chọn: nó rẻ, gần như không trượt, và nó là
    thứ duy nhất còn lại khi mọi nguồn khác vắng mặt — cho tắt nó là cho phép một lượt tìm trả
    về hoàn toàn trống.

    `country` hiện chỉ đi vào khoá cache và vào kết quả trả về, KHÔNG đổi được vùng kết quả:
    Lens bám theo IP của máy chạy server, không theo tham số nào. Giữ trường này vì nó nói ra
    sự thật đó ở chỗ người đọc code sẽ nhìn, thay vì để một tham số câm.
    """
    started_at = time.monotonic()
    country = (country or "VN").upper()
    key = fingerprint(image)
    chosen = set(sources if sources is not None else DEFAULT_SOURCES)

    # Chạy song song: Gemini ~3s, 1688 ~3s, Alibaba ~4s, AliExpress ~5s, Lens ~20s, Taobao
    # ~30s. Nối tiếp thì cả lượt dài bằng TỔNG thay vì bằng tầng chậm nhất — hơn một phút
    # thay vì ba mươi giây, và khoảng cách ấy chỉ nới ra khi thêm nguồn.
    # `gather` không dùng `return_exceptions` vì cả sáu hàm đã tự nuốt lỗi thành câu nói.
    (
        identity_result,
        matches_result,
        sourcing_result,
        china_result,
        global_sourcing_result,
        global_retail_result,
    ) = await asyncio.gather(
        # `id2:` — `identify.py` giờ đọc thêm `model`, mà bản ghi cũ thì không có nó và
        # TTL của rổ này dài tới chín mươi ngày. Không nâng khoá thì mọi ảnh đã từng tra sẽ
        # trả về `model` rỗng suốt ba tháng, và đường tra theo mã hãng lặng lẽ không chạy.
        _read_identity(image, mime, f"id2:{key}"),
        # `v3` trong khoá: bộ bóc thẻ giờ đọc GIÁ từ nhãn dán trên ảnh (xem `lens.py::_CARDS_JS`).
        # Bản v2 đo được 168/168 dòng KHÔNG có giá, nên bảng đã cache vừa sai vừa còn sống ba
        # mươi ngày nữa — và nút sắp theo giá sẽ lặng lẽ không hiện với đúng những ảnh người
        # dùng đã tra rồi. Cùng lý do đã nâng v1 lên v2 khi vá phần ảnh thu nhỏ.
        _read_matches(image, mime, f"v3:{key}:{country}") if "lens" in chosen else _skip(),
        # KHÔNG kèm `country` vào khoá cho hai nguồn Trung Quốc: cả 1688 lẫn Taobao đều là chợ
        # trong nước, kết quả không đổi theo thị trường đích. Nhét `country` vào chỉ làm cùng
        # một tấm ảnh bị hỏi lại mỗi lần người dùng đổi ô Quốc gia.
        _read_sourcing(image, key) if "1688" in chosen else _skip(),
        _read_china_retail(image, mime, key) if "taobao" in chosen else _skip(),
        # Alibaba.com KHÔNG kèm `country` vào khoá: lượt gọi của nó không mang tham số quốc gia
        # nào cả, nên nhét vào chỉ tạo ra hai bản ghi giống hệt nhau. AliExpress thì CÓ —
        # `country` đi thẳng vào `shipToCountry`/`shpt_co` của lượt upload, tức là hai quốc gia
        # là hai lượt gọi khác nhau và phải là hai bản ghi khác nhau. (Kết quả có đổi tới đâu
        # thì CHƯA đo được, vì trần của nguồn này quá chặt để chạy phép so hai chiều — nhưng
        # gộp chung khoá là giả định NGƯỢC LẠI, và giả định ấy nguy hiểm hơn.)
        _read_global_sourcing(image, key) if "alibaba" in chosen else _skip(),
        _read_global_retail(image, f"{key}:{country}", country) if "aliexpress" in chosen else _skip(),
    )
    found_identity, identity_note = identity_result
    matches, matches_note = matches_result

    # Phân sàn Ở ĐÂY, sau cache và trước khi trả về. Bảng vào kho là bảng ĐẦY ĐỦ, và khoá cache
    # vẫn là `v2:{key}:{country}` không mang tên sàn — nhờ vậy người dùng bấm đổi chip Shopee /
    # Lazada / TikTok là lọc tại chỗ, không tốn thêm một suất Lens nào.
    matches = label_platforms(matches)
    sourcing, sourcing_note = sourcing_result
    china_retail, china_note = china_result
    global_sourcing, global_sourcing_note = global_sourcing_result
    global_retail, global_retail_note = global_retail_result

    # Thứ tự ưu tiên = xác suất vắng mặt, cao xuống thấp: Lens (~15 lượt/ngày) → AliExpress
    # (~2 lượt rồi nghỉ một ngày) → Taobao (hết phiên đăng nhập) → Alibaba.com (~9 lượt dồn) →
    # 1688 (chưa thấy trần). Xếp vậy vì câu của nguồn hay vắng nói được việc cần làm tiếp
    # ("nghỉ ít phút", "đăng nhập lại"); câu về Gemini gần như không bao giờ tới lượt.
    message = (
        matches_note
        or global_retail_note
        or china_note
        or global_sourcing_note
        or sourcing_note
        or identity_note
    )

    return ImageSearchResult(
        country=country,
        cny_vnd_rate=env_number("CNY_VND_RATE", DEFAULT_CNY_VND),
        identity=found_identity,
        matches=matches,
        platforms=tally(matches),
        sourcing=sourcing,
        global_sourcing=global_sourcing,
        china_retail=china_retail,
        global_retail=global_retail,
        message=message,
        took_ms=round((time.monotonic() - started_at) * 1000),
        cached=False,
    )
