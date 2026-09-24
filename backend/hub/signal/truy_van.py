"""
HIỂU CÂU HỎI — tầng đọc ý định của One-shot AI. Không gọi AI, không đọc kho.

Đây là tầng đầu của một hệ RAG: câu hỏi vào, một bản mô tả có cấu trúc ra, rồi `ask.py` mới
dựa vào đó mà đi lấy đúng phần kho và dặn Gemini đúng cách. Tách hẳn ra khỏi `ask.py` vì ba
việc — HIỂU, LẤY, TRẢ LỜI — trước đây trộn vào nhau nên không kiểm được cái nào sai.

VÌ SAO KHÔNG DÙNG AI ĐỂ PHÂN LOẠI (chủ dự án chốt 14/09/2026):
  · Mỗi lượt gọi Gemini là một suất hạn mức miễn phí, mà phân loại là việc xảy ra TRƯỚC mỗi
    câu hỏi — nhân đôi số lượt gọi.
  · Khớp chuỗi là TẤT ĐỊNH: cùng một câu luôn ra cùng một kết quả, và sai thì mở ra sửa được.
    Một bộ phân loại bằng AI sai thì chỉ có cách đổi prompt rồi cầu may.
  · Bộ này kiểm bằng bảng câu mẫu (`kiem_tra()` ở cuối file), chạy trong một phần nghìn giây.

MÔ HÌNH: MỘT Ý ĐỊNH + NHIỀU BỘ LỌC. Đây là chỗ bản đầu sai. Ban đầu mọi thứ nhét chung vào một
phép phân loại phẳng, nên "top bán chạy ngành Mẹ & Bé trên Shopee VN" không xếp được vào đâu —
nó vừa là "toplist", vừa là "ngành", vừa là "sàn". Thật ra chỉ có MỘT ý định (toplist), còn
ngành và sàn là BỘ LỌC chồng lên nó.

    ý định  = toplist · lang_kinh · san_pham · meta · y_tuong · khong_ro     (chọn đúng một)
    bộ lọc  = sàn · ngành · lăng kính · bảng · khoảng giá · số lượng          (cộng dồn)

THỨ TỰ XÉT có ý nghĩa, xem `doc()`. Chữ càng đặc thù càng được xét trước: "đang tăng tốc" là
tên một lăng kính nên phải thắng chữ "bán chạy" chung chung nằm cùng câu.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


# ═══════════════════════════ chuẩn hoá ═══════════════════════════

def fold(s: str) -> str:
    """Bỏ dấu + thường hoá + dấu câu thành khoảng trắng. Dùng cho mọi phép khớp không dấu."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    return re.sub(r"[^0-9a-z]+", " ", s).strip()


def co(q: str, *cum: str) -> bool:
    """
    Câu `q` (đã fold VÀ đã đệm khoảng trắng hai đầu) có chứa cụm nào trong `cum` không.

    KHỚP NGUYÊN TỪ. Đây là cái bẫy đã cắn hai lần trong ngày 14/09/2026: khớp chuỗi con thì
    "san ph" (sàn PH) nằm gọn trong "san pham" — mọi câu có chữ "sản phẩm" bị nhận là hỏi
    Shopee PH; và "ung" (ủng) nằm trong "ung dung". Đệm khoảng trắng rồi tìm " cụm " là hết.
    """
    return any(f" {c} " in q for c in cum)


def khoang_cach(a: str, b: str, toi_da: int) -> int:
    """
    Khoảng cách chỉnh sửa (Levenshtein) giữa `a` và `b`, CÓ CHẶN TRÊN.

    Trả về đúng khoảng cách nếu ≤ `toi_da`, ngược lại trả `toi_da + 1` (không tính tiếp cho phí).
    Dùng để khớp MỜ tên sàn: "philippnes" cách "philippines" 1 ký tự thì vẫn về đúng sàn, mà
    không phải liệt kê tay từng lỗi gõ. Tự viết thay vì kéo thư viện ngoài — chuỗi ở đây rất ngắn.
    """
    la, lb = len(a), len(b)
    if abs(la - lb) > toi_da:
        return toi_da + 1
    truoc = list(range(lb + 1))
    for i in range(1, la + 1):
        nay = [i] + [0] * lb
        tot = nay[0]
        for j in range(1, lb + 1):
            phi = 0 if a[i - 1] == b[j - 1] else 1
            nay[j] = min(truoc[j] + 1, nay[j - 1] + 1, truoc[j - 1] + phi)
            tot = min(tot, nay[j])
        if tot > toi_da:                     # cả hàng đã vượt ngưỡng → không thể cứu
            return toi_da + 1
        truoc = nay
    return truoc[lb]


# ═══════════════════════════ kết quả ═══════════════════════════

#: Mọi ý định. `khong_ro` không phải lỗi — nó là một kết cục hợp lệ, và cách xử lý đúng là
#: HỎI LẠI chứ không phải đoán bừa rồi đổ một bảng dữ liệu không ai xin.
Y_DINH = ("toplist", "lang_kinh", "san_pham", "meta", "y_tuong", "xa_giao",
          "ngoai_pham_vi", "khong_ro")


@dataclass
class YeuCau:
    """Câu hỏi đã được đọc thành cấu trúc. `ask.py` chỉ đọc dataclass này, không đọc lại câu."""

    cau_hoi: str
    y_dinh: str = "khong_ro"

    # ── bộ lọc ──
    #: Sàn câu hỏi nhắm tới. Rỗng = không nói sàn nào.
    sans: list[str] = field(default_factory=list)
    #: Sàn bị câu hỏi loại ra ("đừng lấy 1688"). Đã trừ khỏi `sans` rồi, giữ lại để giải thích.
    san_loai: list[str] = field(default_factory=list)
    #: Ngành khớp được trong câu — mỗi phần tử là kết quả của `scout.nganh_lien_quan`.
    nganh: list[dict] = field(default_factory=list)
    #: Lăng kính TREND·SCOUT được gọi tên, chỉ có nghĩa khi `y_dinh == "lang_kinh"`.
    lang_kinh: str | None = None
    #: Xếp theo lượt bán hay theo tiền.
    bang: str = "ban_chay"
    #: Cụm sản phẩm cụ thể được hỏi, chỉ có nghĩa khi `y_dinh == "san_pham"`.
    tu_khoa: list[str] = field(default_factory=list)
    gia_min: float | None = None
    gia_max: float | None = None
    #: "top 20" → 20. None = để người gọi dùng mức mặc định của nó.
    so_luong: int | None = None
    #: Thị trường cho ô tìm kiếm của sàn — quyết định NGÔN NGỮ cụm đem đi hỏi, không phải nguồn số.
    thi_truong: str = "VN"

    #: Vì sao lại phân loại như vậy. Trả về giao diện được, và là thứ đọc đầu tiên khi nghi sai.
    ly_do: list[str] = field(default_factory=list)

    def ghi(self, *cau: str) -> None:
        self.ly_do.extend(cau)

    @property
    def can_so_lieu(self) -> bool:
        """Ý định này có cần kéo bảng số từ kho ra không."""
        return self.y_dinh in ("toplist", "lang_kinh", "san_pham", "meta")


# ═══════════════════════════ từ điển nhận diện ═══════════════════════════

#: Tên sàn. Khớp theo CỤM nguyên từ.
TU_SAN: dict[str, tuple[str, ...]] = {
    "shopee_vn": ("shopee vn", "shopee viet nam", "shopee vietnam", "san vn", "thi truong vn",
                  "viet nam", "trong nuoc", "noi dia"),
    "shopee_ph": ("shopee ph", "shopee philippines", "philippines", "phi lip pin", "san ph",
                  "thi truong ph"),
    # KHÔNG có "hang si": đó là chữ thông dụng của người bán Việt, câu "hàng sỉ bán chạy trên
    # Shopee VN" bị kéo thêm cả 1688 vào. "nguồn sỉ" thì cụ thể về việc đi tìm nguồn nhập.
    "1688": ("1688", "alibaba", "taobao", "trung quoc", "nguon si", "nguon hang si", "hang tau"),
}

#: Viết tắt — phải là MỘT TỪ RIÊNG, không khớp chuỗi con ("vn" nằm trong "advn").
TU_SAN_NGUYEN = {"vn": "shopee_vn", "ph": "shopee_ph", "1688": "1688"}

#: Biến thể CHÍNH TẢ của tên nước, khớp bằng regex trên TỪNG TỪ (đã bỏ dấu).
#:
#: Liệt kê tay không bao giờ đủ: người Việt gõ "Philippines" ra đủ kiểu — philipin, philippin,
#: philipine, philippines, pilipinas (Tagalog)… Đo 22/09/2026, câu "bán chạy nhất thị trường
#: philipin" rơi về CẢ BA SÀN vì "philipin" không khớp "philippines" cũng không khớp
#: "phi lip pin". Regex bắt trọn họ "phi…pin/pine/pines" và "pilipin…" trong một từ.
#: Dạng CÓ DẤU CÁCH ("phi lip pin") vẫn nằm ở `TU_SAN` vì regex một-từ không bắt qua khoảng trắng.
TU_SAN_REGEX = {
    "shopee_ph": re.compile(r"^(phi|pi)li?p+in(e|es|as)?$"),
}

#: Khớp MỜ tên sàn — mỗi khoá là một dạng chuẩn (đã bỏ dấu), giá trị là sàn. Một từ trong câu
#: khớp nếu KHOẢNG CÁCH CHỈNH SỬA tới dạng chuẩn nằm trong ngân sách (xem `_budget_gan`).
#:
#: VÌ SAO CÓ THÊM TẦNG NÀY dù đã có `TU_SAN_REGEX`: regex bắt họ tên theo ÂM (rụng chữ:
#: "philipin"), còn tầng này bắt lỗi GÕ PHÍM (thừa/thiếu/sai 1–2 ký tự: "philippnes", "vietnamm",
#: "alibba") — hai loại lỗi khác nhau, không cái nào phủ hết cái kia. Liệt kê tay không bao giờ đủ;
#: một dạng chuẩn + ngân sách chỉnh sửa phủ được cả một vùng lỗi quanh nó.
#:
#: CHỈ tên ĐỦ DÀI VÀ ĐẶC THÙ mới đặt ở đây. Không đưa "ph"/"vn" (quá ngắn, khớp mờ sẽ dính bừa) —
#: chúng đã nằm ở `TU_SAN_NGUYEN` khớp nguyên từ.
TU_SAN_GAN = {
    "philippines": "shopee_ph",
    "pilipinas":   "shopee_ph",   # tên Tagalog, dân Phi hay tự gõ
    "vietnam":     "shopee_vn",
    "alibaba":     "1688",
    "taobao":      "1688",
}

#: Chỉ xét khớp mờ cho từ dài từ ngần này trở lên. Ngắn hơn thì một hai ký tự sai đã đủ biến nó
#: thành từ khác hẳn, khớp mờ chỉ tổ nhận nhầm ("phi", "phe", "mua"…).
DAI_TOI_THIEU_GAN = 5


def _budget_gan(chuan_ten: str) -> int:
    """Ngân sách chỉnh sửa cho một dạng chuẩn: tên càng dài càng chịu được nhiều lỗi gõ hơn."""
    return 2 if len(chuan_ten) >= 9 else 1

#: Chữ phủ định đứng TRƯỚC tên sàn thì đó là loại sàn đó ra.
TU_PHU_DINH = ("khong", "dung", "chang", "bo qua", "bo", "tru", "ngoai tru", "loai",
               "khoi", "khong can", "khong quan tam", "khong lay", "khong tinh", "ngoai")

#: Sáu lăng kính của TREND·SCOUT. Khoá trùng `scout.LANG_KINH`.
TU_LANG_KINH: dict[str, tuple[str, ...]] = {
    "hot":    ("tang toc", "dang tang", "tang truong", "tang manh", "tang nhanh", "len nhanh",
               "da tang", "tang doanh so", "dang len", "xu huong tang"),
    "spike":  ("dot bien", "vot", "vot len", "bung no", "tang soc", "nhay vot", "tang dot ngot",
               "bat ngo tang"),
    "steady": ("on dinh", "ban deu", "ban khoe", "deu dan", "khong lo ton", "khong om hang",
               "cau on dinh", "ban khoe on dinh", "an chac"),
    "gap":    ("khe ho", "ngach", "ngach trong", "rating thap", "doi thu yeu", "de canh tranh",
               "cho trong", "co hoi ngach", "danh gia thap"),
    "new":    ("tan binh", "moi ra", "hang moi", "moi xuat hien", "san pham moi", "moi len",
               "moi noi"),
}

#: Câu hỏi về CHÍNH CÁI KHO, không phải về hàng trong kho.
#:
#: Nhận bằng LUẬT "chủ ngữ + nghi vấn" chứ không liệt kê cả câu: liệt kê thì "dữ liệu cập nhật
#: đến ngày nào" trượt chỉ vì bảng có "cập nhật khi nào" mà thiếu đúng biến thể ấy — và số biến
#: thể của một câu tiếng Việt là vô hạn.
META_CHU_NGU = ("du lieu", "kho", "he thong", "cong cu", "tool", "so lieu", "thong tin")
META_NGHI_VAN = ("ngay nao", "bao gio", "khi nao", "bao lau", "bao nhieu", "tu dau", "o dau",
                 "the nao", "gi", "nao")
#: Câu meta hỏi thẳng, không cần chủ ngữ.
TU_META = ("co nhung san nao", "nhung san nao", "bao nhieu san", "bao nhieu nganh",
           "quet ngay nao", "cao ngay nao", "moi nhat la ngay nao", "nguon du lieu")

#: Câu TRA CỨU SỐ — hỏi kho xếp hạng, không phải xin ý tưởng.
TU_TOPLIST = ("top", "ban chay", "banchay", "cao nhat", "nhieu nhat", "lon nhat", "xep hang",
              "bang xep hang", "thong ke", "so lieu", "best seller", "bestseller",
              "dan dau", "hot nhat", "dang hot", "nhieu luot ban", "ban nhieu nhat")

#: Chữ chỉ TIỀN — đổi bảng xếp hạng từ lượt bán sang doanh số.
TU_DOANH_SO = ("doanh so", "doanh thu", "gmv", "ra tien", "nhieu tien", "tien nhat", "thu ve")

#: Câu XIN Ý TƯỞNG — không có số nào để tra, cần AI nghĩ ra món.
TU_Y_TUONG = ("nen ban gi", "ban gi", "ban mat hang gi", "kinh doanh gi", "nhap gi", "lay gi ve ban",
              "y tuong", "goi y", "tu van", "nen nhap gi", "bat dau ban", "mo shop", "mo gian hang",
              "san pham nao nen", "co gi hot khong", "nen lam gi", "dau tu gi", "chon san pham")

#: Chữ chỉ một MÓN cụ thể đang được hỏi ("áo mưa bán thế nào").
TU_HOI_MON = ("ban the nao", "the nao", "co tot khong", "co nen ban", "gia bao nhieu",
              "bao nhieu tien", "co ai ban", "co hang khong", "thi truong", "danh gia",
              "tinh hinh", "ra sao", "co on khong", "dang the nao")

#: Chữ vô nghĩa khi đi tìm TÊN MÓN trong câu. Bỏ hết, còn lại mới là món.
#:
#: VIẾT CÓ DẤU, và so khớp trên bản có dấu. Viết không dấu thì "mua" (động từ) nuốt luôn "mưa"
#: — câu "áo mưa bán thế nào" rút còn mỗi "áo", rồi khớp vào ngành "Áo" và trả về bảng thời
#: trang thay vì áo mưa. Đo 14/09/2026. Cùng họ với "giày"/"giấy" và "ủng"/"ứng".
TU_BO = set(
    "tôi muốn cần hỏi cho xin bạn các những một vài ở tại trên dưới trong ngoài với và là thì mà"
    " này đó kia ấy gì nào sao thế như của đến từ theo về được có không chưa đã đang sẽ"
    " nên phải rất quá lắm hơn nhất cũng đều chỉ mới tất cả hiện giờ bây đây hôm tháng năm tuần"
    " sản phẩm hàng mặt hàng món đồ shop sàn ngành thị trường bán mua giá lượt"
    " top danh sách bảng ra sao tình hình phân tích xem giúp mình em anh chị".split())

#: Bản KHÔNG DẤU của `TU_BO`, chỉ dùng khi CẢ CÂU gõ không dấu — khi đó người gõ vốn đã không
#: phân biệt "mưa" với "mua", nên ta cũng không thể.
TU_BO_KHONG_DAU = {fold(t) for t in TU_BO}

#: Chủ đề rõ ràng KHÔNG thuộc phạm vi công cụ. Cần liệt kê vì vài chữ trong số này vẫn khớp được
#: tên sản phẩm thật: "thời tiết" có trong tên mấy cái đồng hồ đo thời tiết, nên nếu không chặn
#: thì câu "hôm nay thời tiết thế nào" được trả lời bằng một bảng đồng hồ đo.
TU_NGOAI_PHAM_VI = ("thoi tiet", "du bao thoi tiet", "bong da", "the thao hom nay", "tin tuc",
                    "chinh tri", "chung khoan", "bitcoin", "tinh yeu", "suc khoe cua toi",
                    "ban may tuoi", "ke chuyen", "cau chuyen", "ke mot cau", "lam tho", "bai tho",
                    "dich giup", "dich sang", "code", "lap trinh", "viet ho bai", "giai toan",
                    "nau an the nao", "cong thuc nau")


# ═══════════════════════════ trích bộ lọc ═══════════════════════════

def _doc_san(q: str, yc: YeuCau) -> None:
    """
    Sàn nào được nhắc tới, và sàn nào bị loại ra.

    PHỦ ĐỊNH XÉT THEO KHOẢNG CÁCH. "top Shopee VN, đừng lấy 1688" — chữ "đừng lấy" đứng ngay
    trước "1688" nên loại 1688, mà không đụng tới Shopee VN ở đầu câu. Bản trước không xét phủ
    định nên câu này trả về cả hai sàn, đúng cái người hỏi vừa bảo đừng lấy.
    """
    nhan: dict[str, int] = {}                       # sàn → vị trí (theo từ) nơi nó được nhắc
    tu = q.split()

    def ghi_nhan(san: str, vi_tri: int) -> None:
        nhan.setdefault(san, vi_tri)

    for san, cum in TU_SAN.items():
        for c in cum:
            i = q.find(f" {c} ")
            if i >= 0:
                ghi_nhan(san, len(q[:i].split()))
    for t, san in TU_SAN_NGUYEN.items():
        if t in tu:
            ghi_nhan(san, tu.index(t))
    # Biến thể chính tả tên nước — xem `TU_SAN_REGEX`. Xét theo từng từ để "philipin",
    # "philippin", "pilipinas"… đều về đúng Shopee PH thay vì rơi về cả ba sàn.
    for i, t in enumerate(tu):
        for san, pat in TU_SAN_REGEX.items():
            if pat.match(t):
                ghi_nhan(san, i)

    # Khớp MỜ — bắt lỗi GÕ PHÍM quanh một dạng chuẩn ("philippnes", "vietnamm", "alibba"). Chỉ xét
    # từ đủ dài (xem `DAI_TOI_THIEU_GAN`); với mỗi từ chọn dạng chuẩn GẦN NHẤT còn trong ngân sách,
    # tránh việc một từ mơ hồ bị gán cho nhiều sàn. Xem `TU_SAN_GAN`.
    for i, t in enumerate(tu):
        if len(t) < DAI_TOI_THIEU_GAN:
            continue
        tot: tuple[int, str] | None = None
        for chuan_ten, san in TU_SAN_GAN.items():
            d = khoang_cach(t, chuan_ten, _budget_gan(chuan_ten))
            if d <= _budget_gan(chuan_ten) and (tot is None or d < tot[0]):
                tot = (d, san)
        if tot:
            ghi_nhan(tot[1], i)

    # "shopee" trơn không kèm thị trường = cả hai sàn Shopee, KHÔNG kéo theo 1688.
    if not nhan and "shopee" in tu:
        vt = tu.index("shopee")
        nhan = {"shopee_vn": vt, "shopee_ph": vt}
        yc.ghi("Câu nói 'shopee' nhưng không nói thị trường → lấy cả Shopee VN và Shopee PH.")

    # "chỉ X thôi" — giới hạn dương, mạnh hơn mọi thứ khác trong câu.
    chi_mot = None
    for san, vt in nhan.items():
        truoc = " ".join(tu[max(0, vt - 3):vt])
        if re.search(r"\b(chi|duy nhat|rieng)\b", truoc):
            chi_mot = san
    if chi_mot:
        yc.sans = [chi_mot]
        yc.san_loai = [s for s in nhan if s != chi_mot]
        yc.ghi(f"Câu nói 'chỉ …' nên chỉ lấy {chi_mot}.")
        return

    giu, loai = [], []
    for san, vt in nhan.items():
        # Cửa sổ 4 từ ngay trước chỗ nhắc sàn. Rộng hơn thì "không" ở đầu câu phủ định nhầm một
        # cái tên sàn nằm mãi cuối câu; hẹp hơn thì hụt "đừng có lấy hàng 1688".
        truoc = " ".join(tu[max(0, vt - 4):vt])
        if any(re.search(rf"\b{re.escape(p)}\b", truoc) for p in TU_PHU_DINH):
            loai.append(san)
        else:
            giu.append(san)
    yc.san_loai = loai
    if loai:
        yc.ghi("Câu loại trừ: " + ", ".join(loai) + ".")
    # Loại hết mà không giữ cái nào ("không lấy 1688") → các sàn CÒN LẠI mới là thứ người ta muốn.
    if loai and not giu:
        giu = [s for s in TU_SAN if s not in loai]
        yc.ghi("Chỉ nói sàn KHÔNG muốn, nên lấy các sàn còn lại.")
    yc.sans = [s for s in TU_SAN if s in giu]


def _doc_gia(q: str, yc: YeuCau) -> None:
    """
    Khoảng giá: "dưới 100k", "trên 1 triệu", "từ 50k đến 200k", "tầm 300 nghìn".

    Chỉ nhận số ĐI KÈM ĐƠN VỊ TIỀN hoặc đi sau chữ chỉ giá. Nhận số trần thì "top 20 sản phẩm"
    thành "giá 20", và "1688" thành giá 1688.
    """
    don_vi = {"k": 1_000, "ngan": 1_000, "nghin": 1_000, "tr": 1_000_000, "trieu": 1_000_000,
              "m": 1_000_000, "ty": 1_000_000_000, "d": 1, "dong": 1, "vnd": 1}
    so = r"(\d+(?:[.,]\d+)?)\s*(k|ngan|nghin|tr|trieu|m|ty|d|dong|vnd)\b"

    def tien(m: re.Match) -> float:
        return float(m.group(1).replace(",", ".")) * don_vi[m.group(2)]

    khoang = re.search(rf"\btu\s+{so}\s+(?:den|toi|-)\s+{so}", q)
    if khoang:
        a = float(khoang.group(1).replace(",", ".")) * don_vi[khoang.group(2)]
        b = float(khoang.group(3).replace(",", ".")) * don_vi[khoang.group(4)]
        yc.gia_min, yc.gia_max = min(a, b), max(a, b)
        yc.ghi(f"Khoảng giá {yc.gia_min:,.0f}–{yc.gia_max:,.0f}.")
        return
    d = re.search(rf"\b(duoi|it hon|re hon|khong qua|toi da)\s+{so}", q)
    if d:
        yc.gia_max = tien(re.search(so, d.group(0)))
        yc.ghi(f"Giá tối đa {yc.gia_max:,.0f}.")
    t = re.search(rf"\b(tren|hon|cao hon|tu)\s+{so}", q)
    if t and not d:
        yc.gia_min = tien(re.search(so, t.group(0)))
        yc.ghi(f"Giá tối thiểu {yc.gia_min:,.0f}.")


def _doc_so_luong(q: str, yc: YeuCau) -> None:
    """"top 20", "20 sản phẩm", "10 món" → 20/20/10. Chặn trên để một câu không kéo cả kho ra."""
    m = re.search(r"\btop\s+(\d{1,3})\b", q) or re.search(r"\b(\d{1,3})\s+(?:san pham|mon|dong|cai)\b", q)
    if m:
        yc.so_luong = max(1, min(200, int(m.group(1))))
        yc.ghi(f"Câu xin {yc.so_luong} dòng.")


def _doc_lang_kinh(q: str, yc: YeuCau) -> None:
    """Lăng kính được gọi tên. Cụm DÀI HƠN thắng, để 'đang tăng' không cướp mất 'tăng đột biến'."""
    tot: tuple[int, str] | None = None
    for lens, cum in TU_LANG_KINH.items():
        for c in cum:
            if f" {c} " in q and (tot is None or len(c) > tot[0]):
                tot = (len(c), lens)
    if tot:
        yc.lang_kinh = tot[1]


def chuan(s: str) -> str:
    """Như `fold` nhưng GIỮ DẤU — chỉ thường hoá và biến dấu câu thành khoảng trắng."""
    return re.sub(r"[^0-9\w]+", " ", (s or "").lower(), flags=re.UNICODE).strip()


def _ten_mon(cau_hoi: str) -> str:
    """
    Phần còn lại của câu sau khi bỏ hết chữ chức năng — ứng viên cho TÊN MÓN được hỏi.

    TRẢ VỀ BẢN GIỮ DẤU. Đây là chỗ đã sai một lần: lược trên chuỗi đã bỏ dấu thì "xin chào" rút
    còn "chao", đem tra kho khớp trúng "chảo" (chảo rán) — và câu chào hỏi bị hiểu thành câu hỏi
    về đồ nhà bếp. Tiếng Việt bỏ dấu có quá nhiều từ chập nhau để làm việc này.

    Cách làm: tách câu thành từ, giữ SONG SONG hai bản (có dấu / không dấu) khớp 1–1 theo chỉ số,
    đánh dấu vị trí cần bỏ trên bản không dấu, rồi ghép lại từ bản có dấu.
    """
    tu_dau = chuan(cau_hoi).split()
    tu_khong = [fold(t) for t in tu_dau]
    bo = [False] * len(tu_dau)

    # Cụm nhiều chữ: tìm dãy từ khớp trên bản không dấu rồi đánh dấu đúng những vị trí đó.
    bo_cum = [c for cum in TU_SAN.values() for c in cum]
    bo_cum += list(TU_TOPLIST) + list(TU_Y_TUONG) + list(TU_HOI_MON) + list(TU_META)
    bo_cum += [c for cum in TU_LANG_KINH.values() for c in cum]
    for c in sorted(set(bo_cum), key=len, reverse=True):
        ct = c.split()
        for i in range(len(tu_khong) - len(ct) + 1):
            if tu_khong[i:i + len(ct)] == ct:
                for j in range(i, i + len(ct)):
                    bo[j] = True

    # Câu gõ CÓ DẤU thì chặn theo bản có dấu (chính xác). Câu gõ không dấu thì đành chặn theo
    # bản không dấu — người gõ không dấu vốn đã không phân biệt "mưa" với "mua".
    khong_dau = fold(cau_hoi) == chuan(cau_hoi)
    chan = TU_BO_KHONG_DAU if khong_dau else TU_BO

    con = [t for i, t in enumerate(tu_dau)
           if not bo[i] and (tu_khong[i] if khong_dau else t) not in chan
           and tu_khong[i] not in TU_SAN_NGUYEN and not tu_khong[i].isdigit()]
    return " ".join(con).strip()


#: Chào hỏi và nói chuyện phiếm — KHÔNG phải câu hỏi dữ liệu, và cũng không phải câu không hiểu
#: được. Trả lời lịch sự rồi mời hỏi tiếp, đừng đổ bảng số nào.
TU_XA_GIAO = ("xin chao", "chao ban", "chao", "hello", "hi", "alo", "cam on", "thanks", "thank you",
              "ban la ai", "ban lam duoc gi", "giup gi duoc", "co the lam gi", "huong dan",
              "ban ten gi", "tam biet", "ok", "oke")


# ═══════════════════════════ phân loại ═══════════════════════════

def doc(cau_hoi: str, tim_nganh=None, co_trong_kho=None) -> YeuCau:
    """
    Đọc một câu hỏi thành `YeuCau`.

    `tim_nganh(cau_hoi, n)` và `co_trong_kho(cum)` được TIÊM VÀO chứ không import thẳng: module
    này phải chạy được mà không đụng cơ sở dữ liệu, để bảng câu mẫu ở `kiem_tra()` chạy trong
    một phần nghìn giây và không phụ thuộc kho có dữ liệu hay không.

    THỨ TỰ XÉT — chữ càng đặc thù xét càng sớm, vì một câu thường dính nhiều dấu hiệu:
      1. meta      — hỏi về chính cái kho, không phải về hàng trong kho.
      2. lang_kinh — "đang tăng tốc", "đột biến"… là TÊN một bảng có sẵn, rất đặc thù.
      3. y_tuong   — "nên bán gì" là lời xin nghĩ hộ, không có gì để tra.
      4. toplist   — "top", "bán chạy", "doanh số".
      5. san_pham  — còn lại một cụm danh từ mà kho có hàng khớp.
      6. khong_ro  — không dấu hiệu nào. HỎI LẠI, đừng đoán.

    `y_tuong` đứng TRƯỚC `toplist` là có chủ ý: "mùa mưa nên bán gì cho chạy" có chữ "chạy"
    nhưng vẫn là câu xin ý tưởng. Ngược lại "top sản phẩm bán chạy" không có cụm xin ý tưởng
    nào nên không bị bắt nhầm.
    """
    yc = YeuCau(cau_hoi=cau_hoi or "")
    q = f" {fold(cau_hoi)} "
    if not q.strip():
        yc.ghi("Câu rỗng.")
        return yc

    _doc_san(q, yc)
    _doc_gia(q, yc)
    _doc_so_luong(q, yc)
    _doc_lang_kinh(q, yc)
    if co(q, *TU_DOANH_SO):
        yc.bang = "doanh_so"
        yc.ghi("Xếp theo doanh số (câu nhắc tới tiền).")
    yc.thi_truong = "PH" if "shopee_ph" in yc.sans and "shopee_vn" not in yc.sans else "VN"

    if tim_nganh:
        # KHỬ TRÙNG THEO TÊN. Cây ngành có những tên lặp ở hai ngành lớn khác nhau ("Áo" nằm cả
        # trong Thời Trang Nam lẫn Thời Trang Nữ), nên câu hỏi khớp chữ "áo" trả về hai dòng y
        # hệt nhau — đọc như hệ thống nhận nhầm hai lần.
        thay: set[str] = set()
        for n in tim_nganh(cau_hoi, 3) or []:
            if n["ten"] in thay:
                continue
            thay.add(n["ten"])
            yc.nganh.append(n)
        yc.nganh = yc.nganh[:2]
        if yc.nganh:
            yc.ghi("Ngành nhận ra: " + ", ".join(n["ten"] for n in yc.nganh) + ".")

    # ── 0. xã giao và ngoài phạm vi. Xét TRƯỚC mọi thứ: câu chào không được rơi xuống tầng tra
    # kho, vì ở đó "xin chào" rút còn "chào" rồi khớp trúng "chảo" rán.
    if co(q, *TU_XA_GIAO) and len(q.split()) <= 6:
        yc.y_dinh = "xa_giao"
        yc.ghi("Câu chào hỏi / hỏi về công cụ — không tra kho.")
        return yc
    if co(q, *TU_NGOAI_PHAM_VI):
        yc.y_dinh = "ngoai_pham_vi"
        yc.ghi("Chủ đề ngoài phạm vi công cụ — nói thẳng là không trả lời được, đừng tra kho.")
        return yc

    # ── 1. meta. "Chủ ngữ là cái kho" + "một chữ nghi vấn" = hỏi về kho. Phải KHÔNG có tên
    # ngành và KHÔNG có cụm sản phẩm, nếu không thì "ngành nào bán chạy" cũng thành câu meta.
    la_meta = co(q, *TU_META) or (co(q, *META_CHU_NGU) and co(q, *META_NGHI_VAN)
                                  and not yc.nganh and not co(q, *TU_TOPLIST))
    if la_meta:
        yc.y_dinh = "meta"
        yc.ghi("Hỏi về chính kho dữ liệu, không phải về hàng trong kho.")
        return yc

    # ── 2. lăng kính
    if yc.lang_kinh:
        yc.y_dinh = "lang_kinh"
        yc.ghi(f"Gọi tên lăng kính '{yc.lang_kinh}'.")
        return yc

    # ── 3. ý tưởng
    if co(q, *TU_Y_TUONG):
        yc.y_dinh = "y_tuong"
        yc.ghi("Câu xin ý tưởng, không có bảng số nào để tra.")
        return yc

    # ── 4. toplist
    if co(q, *TU_TOPLIST) or yc.so_luong:
        yc.y_dinh = "toplist"
        yc.ghi("Câu tra cứu bảng xếp hạng.")
        return yc

    mon = _ten_mon(cau_hoi)

    # ── 5. NGÀNH trước SẢN PHẨM khi cụm còn lại chính là tên ngành. "ngành thời trang nữ" khớp
    # cả hai đường: kho có hàng tên "thời trang nữ", mà đó cũng là tên một ngành. Hỏi tên một
    # ngành thì câu trả lời đúng là BẢNG của ngành đó, không phải vài listing lẻ.
    if yc.nganh:
        ten_nganh_tu = {fold(t) for n in yc.nganh for t in chuan(n["ten"]).split()}
        mon_tu = {fold(t) for t in mon.split()} if mon else set()
        if not mon_tu or mon_tu <= ten_nganh_tu:
            yc.y_dinh = "toplist"
            yc.ghi("Cụm còn lại chính là tên ngành → trả bảng của ngành đó.")
            return yc

    # ── 6. một món cụ thể.
    #
    # MỘT CHỮ THÌ CHƯA ĐỦ. Cụm một chữ ("giày", "túi") khớp hàng nghìn listing nên con số trả về
    # chẳng nói gì về ý người hỏi, mà lại rất dễ khớp bừa. Chỉ nhận cụm một chữ khi câu có kèm
    # dấu hiệu đang hỏi về một món ("bán thế nào", "giá bao nhiêu").
    du_dai = len(mon.split()) >= 2 or (mon and co(q, *TU_HOI_MON))
    if mon and du_dai and co_trong_kho and co_trong_kho(mon):
        yc.y_dinh = "san_pham"
        yc.tu_khoa = [mon]
        # BỎ NGÀNH ĐI. Nhánh này tra theo TÊN MÓN, không dùng ngành — mà ngành khớp được ở đây
        # thường là rác: "giá túi chống nước điện thoại" khớp trúng "Bao bì, túi đựng rác" chỉ vì
        # chung chữ "túi". Giữ lại thì nó hiện ra cho người dùng như một kết luận của hệ thống.
        yc.nganh = []
        yc.ghi(f"Kho có hàng khớp cụm “{mon}” → hiểu là hỏi về món này.")
        return yc

    yc.ghi("Không có dấu hiệu nào nhận ra được — nên hỏi lại thay vì đoán."
           + (f" (cụm còn lại sau khi lược: '{mon}')" if mon else ""))
    return yc


# ═══════════════════════════ tự kiểm ═══════════════════════════

#: Bảng câu mẫu — (câu hỏi, ý định mong đợi). Đây là lưới an toàn của cả tầng này: sửa từ điển
#: mà làm hỏng một dòng nào ở đây thì biết ngay, thay vì phát hiện lúc đang demo.
MAU: tuple[tuple[str, str], ...] = (
    # toplist
    ("top sản phẩm bán chạy", "toplist"),
    ("top 20 sản phẩm bán chạy Shopee VN", "toplist"),
    ("sản phẩm nào có doanh số cao nhất", "toplist"),
    ("bảng xếp hạng bán chạy 1688", "toplist"),
    ("mặt hàng nào bán nhiều nhất tháng này", "toplist"),
    ("đồ mẹ và bé bán chạy nhất", "toplist"),
    ("ngành thời trang nữ", "toplist"),
    # lăng kính
    ("sản phẩm nào đang tăng tốc", "lang_kinh"),
    ("hàng nào đột biến hôm nay", "lang_kinh"),
    ("có món nào bán ổn định không", "lang_kinh"),
    ("khe hở ngách nào đang mở", "lang_kinh"),
    ("tân binh nào mới lên", "lang_kinh"),
    ("sản phẩm mới xuất hiện mà bán tốt", "lang_kinh"),
    # ý tưởng
    ("mùa mưa nên bán gì ?", "y_tuong"),
    ("tôi muốn mở shop bán quần áo", "y_tuong"),
    ("gợi ý sản phẩm cho mùa tựu trường", "y_tuong"),
    ("sắp Tết nên nhập gì", "y_tuong"),
    ("tư vấn cho tôi vài món dễ bán", "y_tuong"),
    # meta
    ("kho có bao nhiêu sản phẩm", "meta"),
    ("dữ liệu cập nhật đến ngày nào", "meta"),
    ("có những sàn nào", "meta"),
    # không rõ
    ("hôm nay thời tiết thế nào", "ngoai_pham_vi"),
    ("kể cho tôi một câu chuyện", "ngoai_pham_vi"),
    ("", "khong_ro"),
    ("abc xyz qwerty", "khong_ro"),
    # xã giao
    ("xin chào", "xa_giao"),
    ("bạn làm được gì", "xa_giao"),
    ("cảm ơn nhé", "xa_giao"),
    # một món cụ thể
    ("áo mưa bán thế nào", "san_pham"),
    ("giá túi chống nước điện thoại bao nhiêu", "san_pham"),
    # sàn + phủ định (kiểm bộ lọc, không phải ý định)
    ("top bán chạy Shopee VN, đừng lấy 1688", "toplist"),
    ("top sản phẩm bán chạy dưới 100k", "toplist"),
)


#: Bảng kiểm phần SÀN — (câu hỏi, danh sách sàn mong đợi). Tách khỏi `MAU` vì `MAU` chỉ soi ý
#: định, mà lỗi "hỏi Philippines ra cả ba sàn" (22/09/2026) nằm ở khâu đọc sàn nên lọt lưới trọn.
#: Nhiều cách gõ sai của "Philippines" ở đây là cố ý — đó chính là thứ regex `TU_SAN_REGEX` giữ.
MAU_SAN: tuple[tuple[str, list[str]], ...] = (
    # họ tên theo ÂM — regex `TU_SAN_REGEX` giữ
    ("bán chạy nhất thị trường philipin tháng qua", ["shopee_ph"]),
    ("top bán chạy philippin", ["shopee_ph"]),
    ("top bán chạy philipines", ["shopee_ph"]),
    ("top bán chạy pilipinas", ["shopee_ph"]),
    # lỗi GÕ PHÍM — chỉ tầng khớp mờ `TU_SAN_GAN` bắt được (regex ở trên không khớp)
    ("top bán chạy philippnes", ["shopee_ph"]),      # thiếu 'i'
    ("hàng bán chạy ở vietnamm", ["shopee_vn"]),     # thừa 'm', "viet nam" không khớp
    ("bán chạy trên alibba", ["1688"]),              # thiếu 'a'
    # viết tắt / tên chuẩn
    ("hàng bán chạy ở PH", ["shopee_ph"]),
    ("top bán chạy Shopee VN", ["shopee_vn"]),
    ("top bán chạy 1688", ["1688"]),
    # chống nhận nhầm
    ("phí ship rẻ nhất", []),                        # "phí" KHÔNG phải Philippines
    ("cà phê sữa đá bán chạy", []),                  # "phê" KHÔNG phải Philippines
    ("điện thoại philips còn bán không", []),        # thương hiệu Philips ≠ Philippines
    ("top sản phẩm bán chạy", []),                   # không nói sàn → rỗng, ask.py tự lấy cả ba
)


def kiem_tra(tim_nganh=None, co_trong_kho=None) -> list[str]:
    """Chạy bảng câu mẫu, trả về danh sách dòng SAI (rỗng = tất cả đúng)."""
    sai = []
    for cau, mong in MAU:
        ra = doc(cau, tim_nganh, co_trong_kho).y_dinh
        if ra != mong:
            sai.append(f"{cau!r}: mong ý định {mong}, ra {ra}")
    for cau, mong in MAU_SAN:
        ra = doc(cau, tim_nganh, co_trong_kho).sans
        if ra != mong:
            sai.append(f"{cau!r}: mong sàn {mong}, ra {ra}")
    return sai
