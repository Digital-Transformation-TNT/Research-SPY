"""Từ vựng của mục TÌM BẰNG ẢNH. Nguồn sự thật cho `frontend/lib/imagesearch/types.ts`."""

from __future__ import annotations

from pydantic import computed_field

from lib.core.model import CamelModel

from .codes import extract_codes
from .price import price_number


class ImageIdentity(CamelModel):
    """
    Mô hình đọc được gì từ tấm ảnh. Tầng này LUÔN chạy và gần như không bao giờ trượt.

    Nó tồn tại tách khỏi `matches` vì hai tầng có độ tin cậy khác hẳn nhau, và vì tầng kia
    có hạn mức. Khi Lens bị treo thì người dùng vẫn còn tên món, thương hiệu và cụm để gõ —
    tức là vẫn làm được việc, chỉ là phải tự bấm sang sàn.
    """

    product: str
    #: Thương hiệu đọc được TRÊN ẢNH. Rỗng khi không đọc được — cố ý không đoán, vì một
    #: thương hiệu bịa ra trông y hệt một thương hiệu đọc đúng.
    brand: str = ""
    #: Mã model đọc được TRÊN ẢNH ("G304", "PH1627"). Rỗng khi không đọc được, cùng luật với
    #: `brand`.
    #:
    #: Trường này tồn tại vì một số đo, không phải vì nó đẹp: `scripts/probe/code_bridge.py`
    #: ngày 2026-08-19 cho thấy tra `site:shopee.vn "<mã>"` chỉ ra hàng khi mã là mã HÃNG
    #: (`G304` → 8 trang sản phẩm), còn mã XƯỞNG lấy từ tiêu đề 1688 thì bằng không
    #: (`T15S`, `N612`, `KF5135`) — người bán Việt Nam không dịch tiêu đề 1688, họ viết tiêu đề
    #: mới và tự đặt mã riêng. Nên mã dùng được phải đọc từ CHÍNH TẤM ẢNH, không phải rút ra từ
    #: kết quả 1688.
    model: str = ""
    #: Cụm tìm kiếm theo ngôn ngữ: `{"vi": [...], "zh": [...]}`. `vi` là từ gốc mang sang tab
    #: Từ khoá; `zh` là đường tra tay khi tìm-bằng-ảnh trượt.
    #:
    #: Bản ghi cache cũ (90 ngày) còn mang `attributes` và `en` — pydantic bỏ qua khoá thừa,
    #: nên không cần dọn kho hay nâng phiên bản khoá.
    terms: dict[str, list[str]] = {}


class ImageMatch(CamelModel):
    """Một dòng trong bảng kết quả — tương ứng một thẻ ở tab "Hình ảnh trùng khớp"."""

    source: str
    title: str
    link: str
    #: Ảnh thu nhỏ. Google trả về dạng `data:` nên nhúng thẳng được, không cần tải lại.
    thumbnail: str | None = None
    #: Giá NGUYÊN VĂN như Google hiện ("989.000 đ"). Cố ý không parse ra số: đơn vị tiền
    #: đổi theo nước, và một con số không kèm đơn vị là một con số sai.
    price: str | None = None
    rating: float | None = None
    reviews: int | None = None
    in_stock: bool | None = None
    #: Có phải trang bán hàng không. Dùng để xếp trang sàn lên trước bài viết và diễn đàn.
    marketplace: bool = False
    #: Sàn của dòng này: `shopee`, `lazada`, `tiktok`, `other`. TÍNH RA từ `link` mỗi lần đọc
    #: chứ không lưu — xem `platform.py::label_platforms` để biết vì sao.
    platform: str = ""

    # --- các trường dưới chỉ có ở nguồn nhập hàng, xem `ali.py` và `alibaba.py` ---
    #: Tên công ty cung cấp. Google Lens không có khái niệm này.
    supplier: str | None = None
    #: Tỉnh + thành phố của xưởng, ví dụ "广东 深圳市". Với người đi nhập, đây là chi phí vận
    #: chuyển và thời gian giao — không phải thông tin trang trí.
    location: str | None = None
    #: Số lượng đã bán. Là SỐ chứ không phải chuỗi, vì nó dùng để so sánh giữa các nhà cung cấp.
    sold: int | None = None
    #: Số lượng đặt tối thiểu, NGUYÊN VĂN ("Min. order: 500 pieces"). Chỉ sàn bán buôn quốc tế
    #: có — xem `alibaba.py`. Giữ nguyên chữ vì đơn vị đổi theo mặt hàng (piece, set, meter,
    #: carton); tách lấy con số là vứt mất nửa nghĩa, và "500" không kèm đơn vị thì không đặt
    #: hàng được. Với người đi nhập chính ngạch, đây là thứ quyết định TRƯỚC cả giá.
    moq: str | None = None
    #: Con số bán hàng mà nguồn chỉ cho dưới dạng CHỮ — Taobao trả "300+人付款" chứ không trả
    #: một số. Ép về `sold` là bịa ra độ chính xác không có; ghép vào `reviews` cũng sai vì đó
    #: là người MUA chứ không phải người đánh giá.
    note: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def price_value(self) -> float | None:
        """
        `price` rút về SỐ, chỉ để sắp xếp. Đơn vị là đơn vị của chính dòng đó — ¥ với
        1688/Taobao, ₫ với Alibaba.com/AliExpress/Lens — nên CHỈ so được trong cùng một bảng.
        Đó cũng đúng là cách giao diện dùng nó: mỗi bảng có nút sắp xếp riêng, không có bảng
        nào trộn hai loại tiền.

        Là trường TÍNH RA chứ không phải trường lưu, vì hai lý do: kho cache 90 ngày đang có
        sẵn hàng nghìn bản ghi không mang trường này, và năm nguồn dựng `ImageMatch` ở sáu chỗ
        khác nhau — tính ở đây thì cả sáu chỗ và cả bản ghi cũ đều có, không phải dọn kho.

        Giá dạng KHOẢNG ("¥1.20-3.50") rút về cận dưới; xem `price.py` để biết vì sao.
        """
        return price_number(self.price)


class ProductCode(CamelModel):
    """
    Một mã model ứng viên, rút ra từ tiêu đề các bảng kết quả.

    `count` và `sources` KHÔNG phải trang trí, chúng là phần đọc độ tin cậy — xem `codes.py`.
    Một mã 42 lần ở ba bảng là mã thật; một mã 1 lần ở một bảng có thể chỉ là chuỗi ngẫu
    nhiên trong tiêu đề. Công cụ không giấu cái sau đi, nó xếp cái sau xuống dưới.
    """

    code: str
    #: Số DÒNG có nhắc mã này (không phải số lần xuất hiện — xem `extract_codes`).
    count: int
    #: Tên các bảng đã thấy mã. Bảng nào cũng quan trọng, nhưng "Nơi đang bán" quan trọng
    #: nhất: thấy ở đó nghĩa là chính thị trường Việt Nam đang gọi món này bằng mã ấy, tức là
    #: gõ vào ô tìm kiếm của Shopee sẽ ra hàng.
    sources: list[str]
    #: Mã ĐỌC ĐƯỢC TRÊN ẢNH (`identity.model`) thay vì rút từ tiêu đề. Đáng tin hơn hẳn —
    #: nó nằm trên chính sản phẩm — nên nó đứng đầu bảng và được đánh dấu riêng.
    from_image: bool = False


class PlatformCount(CamelModel):
    """
    Một chip lọc trên bảng "Nơi đang bán": tên sàn và số kết quả thuộc sàn đó.

    `count` ĐƯỢC PHÉP bằng không, và đó là lý do kiểu này tồn tại thay vì để giao diện tự đếm.
    "TikTok 0" nói rằng ảnh này không tìm thấy hàng trên TikTok — một câu trả lời có thật, khác
    hẳn với việc thiếu hẳn chip TikTok, thứ người ta sẽ đọc thành "công cụ không tra TikTok".
    """

    id: str
    label: str
    count: int


class ImageSearchResult(CamelModel):
    """
    SÁU TẦNG, sáu câu hỏi khác nhau — đó là lý do chúng là sáu trường chứ không phải một danh
    sách trộn chung:

        identity        món này LÀ GÌ, gọi tên thế nào ở vi/zh/en
        matches         ai đang BÁN LẺ nó ở thị trường đích, giá bao nhiêu  (Google Lens)
        sourcing        NHẬP nó ở đâu, giá sỉ ¥, xưởng ở tỉnh nào           (1688)
        global_sourcing nhập CHÍNH NGẠCH giá ₫ bao nhiêu, đặt tối thiểu bao nhiêu (Alibaba.com)
        china_retail    người Trung Quốc đang MUA nó giá nào, mẫu nào chạy  (Taobao)
        global_retail   khách VN tự đặt về được ở mức giá nào              (AliExpress)

    Trộn chúng vào một bảng là hỏng: ¥29 của xưởng Thâm Quyến, ¥145 của shop Taobao và
    989.000đ của Shopee VN không so sánh được với nhau, mà đặt cạnh nhau thì trông như so sánh
    được. Để riêng thì các con số ấy đọc thành một chuỗi có nghĩa — giá vốn, giá bán ở chợ gốc,
    giá bán ở chợ đích.

    Hai rổ `global_*` là hai đầu của cùng một đường: Alibaba.com cho biết mua buôn về giá nào,
    AliExpress cho biết KHÁCH CỦA NGƯỜI DÙNG tự đặt về được giá nào. Khoảng giữa hai con số ấy
    chính là phần biên còn lại — và khi nó âm thì mặt hàng ấy không có cửa, một câu trả lời
    không nguồn nào khác nói ra được.
    """

    country: str
    identity: ImageIdentity | None = None
    matches: list[ImageMatch] = []
    #: Chào hàng 1688. Rỗng khi nguồn hỏng — không bao giờ là lý do để cả lượt tìm thất bại.
    sourcing: list[ImageMatch] = []
    #: Chào hàng bán buôn XUẤT KHẨU trên Alibaba.com — giá đã quy ra ₫ và KÈM `moq`. Khác
    #: `sourcing` ở chỗ mua được mà không cần người gom hàng trong nước Trung Quốc.
    global_sourcing: list[ImageMatch] = []
    #: Hàng bán lẻ trên Taobao. Rỗng khi chưa đăng nhập — xem `taobao.py`.
    china_retail: list[ImageMatch] = []
    #: Hàng bán lẻ quốc tế trên AliExpress — ship lẻ về Việt Nam, giá ₫ đã gồm đường ra quốc
    #: tế. Đây là TRẦN GIÁ: người mua Việt Nam tự đặt được ở mức này, nên bán cao hơn là khó.
    global_retail: list[ImageMatch] = []
    #: Số đếm mỗi sàn cho dãy chip lọc trên bảng `matches`. Chỉ nói về `matches` — `sourcing`
    #: và `china_retail` mỗi cái đã là một sàn duy nhất nên không có gì để lọc.
    platforms: list[PlatformCount] = []
    #: Câu nói cho người dùng khi thiếu một phần. KHÔNG phải lỗi hệ thống — thường là
    #: "Lens đang bận", và lúc đó `identity` vẫn còn nguyên.
    message: str | None = None
    took_ms: int = 0
    cached: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def codes(self) -> list[ProductCode]:
        """
        Mã model ứng viên, gom từ TẤT CẢ các bảng và xếp theo số lần xuất hiện.

        Trả lời đúng câu người dùng hỏi khi nhìn một bảng chào hàng Trung Quốc: "món này gọi
        là mã gì?" — thứ để nhắn cho xưởng, và thứ để gõ ngược vào ô tìm kiếm của sàn Việt
        Nam. Xem `codes.py` để biết vì sao xếp hạng chứ không lọc.

        Là trường TÍNH RA vì nó không thêm thông tin gì mới: mọi tiêu đề dùng để rút mã đều
        đã nằm sẵn trong các bảng ở trên. Lưu nó là lưu hai bản của cùng một sự thật, và hai
        bản thì sẽ có ngày lệch nhau.
        """
        tables = {
            "1688": self.sourcing,
            "Alibaba.com": self.global_sourcing,
            "Taobao": self.china_retail,
            "AliExpress": self.global_retail,
            "Nơi đang bán": self.matches,
        }
        found = extract_codes({ten: [row.title for row in rows] for ten, rows in tables.items()})
        codes = [ProductCode(code=code, count=count, sources=src) for code, count, src in found]

        # Mã đọc TRÊN ẢNH lên đầu — nó nằm trên chính sản phẩm nên đáng tin hơn mọi tiêu đề
        # do người bán tự viết. Nếu nó cũng có trong danh sách rút từ tiêu đề thì nhấc lên
        # chứ không thêm dòng thứ hai: hai dòng cùng một mã đọc thành hai mã khác nhau.
        from_image = (self.identity.model if self.identity else "").strip().upper()
        if not from_image:
            return codes
        same = next((c for c in codes if c.code == from_image), None)
        if same:
            codes.remove(same)
            return [same.model_copy(update={"from_image": True}), *codes]
        return [ProductCode(code=from_image, count=0, sources=[], from_image=True), *codes]
