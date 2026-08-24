"""
Thị trường nào nói ngôn ngữ nào.

Tách riêng khỏi cả `normalize.py` lẫn `providers/expand.py` vì cả hai đều cần bảng này mà
không bên nào nên phụ thuộc bên kia: một bên xử lý văn bản đã lấy về, bên kia dựng truy vấn
để đi lấy.

Trả về một CHUỖI ngôn ngữ chứ không phải một ngôn ngữ đơn lẻ, vì mọi thị trường ngoài Việt
Nam mà công cụ này phục vụ đều pha trộn. Người Philippines gõ "damit pambabae" và "dress for
women" trong cùng một phiên; người Malaysia gõ "baju wanita" lẫn "women blouse". Ép mỗi nước
về đúng một ngôn ngữ là vứt đi một nửa vốn từ của nó — nên `"tl"` ở đây có nghĩa "Tagalog
TRƯỚC, rồi tới tiếng Anh", và mọi bảng từ vựng đều được gộp theo đúng thứ tự đó.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Mapping, Sequence

from .types import WORLDWIDE

#: Ngôn ngữ dùng khi thị trường không có tên trong bảng.
#:
#: Tiếng Việt, vì đó là thị trường mặc định của công cụ và là nơi mọi heuristic được đo đạc.
#: Xem `LANGUAGE_BY_MARKET` để biết vì sao cái mặc định này từng là một cái bẫy.
DEFAULT_LANGUAGE = "vi"

#: Ngôn ngữ chính của từng thị trường.
#:
#: Phải liệt kê MỌI nước mà người dùng chọn được, không chỉ những nước có nguồn mở rộng theo
#: tiền tố. Bảng trước đây chỉ có bảy nước Đông Nam Á cộng US, trong khi ô chọn quốc gia ở
#: giao diện là toàn bộ danh sách ISO — nên chọn Anh (`GB`) sẽ rơi về mặc định tiếng Việt, và
#: TikTok (phục vụ mọi thị trường) đi mở rộng "jeans" bằng các hậu tố " nữ", " mùa hè", " đ".
#: Lượt chạy vẫn thành công, vẫn trả về từ khoá, chỉ là hỏi sai câu hỏi — kiểu lỗi tệ nhất.
LANGUAGE_BY_MARKET: dict[str, str] = {
    "VN": "vi",
    "PH": "tl",
    "ID": "id",
    "MY": "ms",
    "SG": "en",
    # Tiếng Thái chưa có bảng từ vựng nào trong dự án này, nên nó rơi về tiếng Anh qua
    # `LANGUAGE_FALLBACK` và các cụm tiếng Thái không được phân loại ý định hay nhận diện
    # mùa vụ. Nhưng mã ngôn ngữ vẫn PHẢI là "th" chứ không phải "en".
    #
    # Từng để thẳng "en" và nó đẻ ra một lỗi rất khó chịu: `DIACRITIC_FREE_LANGUAGES` chứa
    # "en", nên gõ "เสื้อกันหนาว" — đúng tiếng bản địa của thị trường đó — bị báo là "tiếng
    # Việt, người Thái không tìm bằng tiếng Việt". Mã ngôn ngữ ở đây không chỉ để tra bảng từ
    # vựng; nó còn trả lời câu "thị trường này viết bằng chữ gì".
    "TH": "th",
    "US": "en",
    "GB": "en",
    "AU": "en",
    "CA": "en",
    "NZ": "en",
    "IE": "en",
    "IN": "en",
    # Hai thị trường này vào bảng cùng lúc với nguồn Amazon. Thiếu chúng ở đây thì chọn Đức
    # sẽ mở rộng "jacke" bằng hậu tố " nữ", " mùa hè", " đ" — đúng cái bẫy mà `GB` đã dính.
    "DE": "de",
    "JP": "ja",
    # Hai thị trường Shopee ngoài Đông Nam Á, vào bảng cùng lúc với `shopee.tw` và
    # `shopee.com.br`.
    "TW": "zh-Hant",
    "BR": "pt",
    # Trung Quốc đại lục, vào bảng cùng lúc với nguồn Taobao.
    #
    # PHẢI là mã riêng chứ không dùng chung với Đài Loan, dù cùng gọi là "tiếng Trung". Đại lục
    # viết GIẢN THỂ, Đài Loan viết PHỒN THỂ, và với ô gợi ý tìm kiếm thì đó là hai chuỗi khác
    # nhau chứ không phải hai cách hiển thị: "大码" và "大尺碼" đều nghĩa là "cỡ lớn" nhưng
    # không ký tự nào trùng, nên gieo từ bổ nghĩa phồn thể vào Taobao sẽ trả về rỗng.
    "CN": "zh-Hans",
    # Châu Âu ngoài Đức. Thêm vào 2026-08-18 vì cả nhóm này đang rơi về mặc định tiếng Việt —
    # đúng cái bẫy mà chú thích đầu bảng mô tả cho `GB`, chỉ là chưa ai thêm nốt. Triệu chứng
    # đo được: chọn Pháp rồi mở rộng "jeans" thì các từ bổ nghĩa là " nữ", " mùa hè", " đ".
    #
    # `AT` dùng chung tiếng Đức với `DE`; `PT` dùng chung tiếng Bồ với `BR` — hai thứ tiếng đó
    # có khác biệt vùng miền thật, nhưng không ở mức đổi chuỗi truy vấn như giản thể/phồn thể.
    "FR": "fr",
    "IT": "it",
    "ES": "es",
    "NL": "nl",
    "PL": "pl",
    "SE": "sv",
    "PT": "pt",
    "AT": "de",
    # BỈ VÀ THỤY SĨ CỐ Ý VẮNG MẶT, và đó là một quyết định chứ không phải một chỗ quên.
    #
    # Cả hai đều đa ngữ thật sự — Bỉ chia giữa tiếng Hà Lan và tiếng Pháp, Thụy Sĩ giữa Đức,
    # Pháp và Ý — trong khi bảng này chỉ nhận MỘT ngôn ngữ chính cho mỗi nước. Chọn bừa một
    # bên là làm sai cho nửa thị trường còn lại một cách âm thầm, mà hai nước này lại nhỏ tới
    # mức chưa đáng để đi đo xem bên nào áp đảo trong truy vấn mua sắm. Rơi về mặc định thì
    # `demand_map._market_language` im lặng và mô hình tự quyết — thà vậy còn hơn.
    WORLDWIDE: "en",
}

#: Ngôn ngữ nào mượn thêm vốn từ của ngôn ngữ nào.
#:
#: Một chiều và chỉ một bậc, cố ý. Tiếng Anh có mặt trong mọi truy vấn ở Philippines,
#: Indonesia và Malaysia, nhưng chiều ngược lại thì không — thị trường Mỹ không bao giờ nên
#: nhận "murang" vào bảng dấu hiệu ý định mua của nó.
#: `zh` và `pt` CỐ Ý vắng mặt, và vắng vì hai lý do khác nhau.
#:
#: Tiếng Trung: mượn vốn từ tiếng Anh sẽ đẻ ra các cụm mở rộng kiểu "洋裝 women" — không ai
#: gõ như vậy. Người Đài Loan có gõ tên hãng bằng chữ Latin ("nike襪子" là kết quả đo thật),
#: nhưng đó là chuyện của TỪ GỐC, không phải của chữ bổ nghĩa mà ta ghép thêm.
#:
#: Tiếng Bồ: đủ vốn từ riêng nên không cần mượn, và mượn thì tốn lượt gọi. `DEPTH_CALLS` cắt
#: ở 12 lượt cho lần chạy "Nhanh", nên mỗi mục tiếng Anh chen vào là một mục tiếng Bồ bị đẩy
#: ra ngoài — xem chú thích thứ tự ở `MARKET_MODIFIERS`.
LANGUAGE_FALLBACK: dict[str, str] = {
    "tl": "en",
    "id": "en",
    "ms": "en",
    "de": "en",
    "ja": "en",
    "th": "en",
    # Nhóm châu Âu. Dự phòng tiếng Anh ở đây làm HAI việc, và việc thứ hai mới là việc gấp:
    # người mua ở những nước này có gõ lẫn tiếng Anh thật, NHƯNG quan trọng hơn là mọi bảng từ
    # vựng tra qua `merge_by_language` — dấu hiệu ý định, dấu hiệu mùa vụ, bảng chữ cái mở
    # rộng — đều chưa có mục cho các thứ tiếng này. Không có dự phòng thì chúng trả về RỖNG,
    # và một thị trường không phân loại được ý định thì tệ hơn một thị trường phân loại bằng
    # vốn từ tiếng Anh.
    "fr": "en",
    "it": "en",
    "es": "en",
    "nl": "en",
    "pl": "en",
    "sv": "en",
}

#: Ngôn ngữ mà truy vấn của thị trường đó viết bằng chữ Latin THUẦN ASCII.
#:
#: Dùng để bắt một sai lầm rất dễ mắc và rất khó tự nhận ra: gõ từ gốc tiếng Việt rồi chọn
#: thị trường nước ngoài. Google trả lời trung thực — người Philippines không gõ "áo khoác",
#: nên bảng rỗng là ĐÚNG — nhưng người dùng đọc bảng rỗng đó thành "công cụ hỏng".
#:
#: TÊN GỌI QUAN TRỌNG: đây không phải "ngôn ngữ không có dấu" mà là "viết bằng ASCII thuần".
#: Hiểu sai một chữ là lọt cả tiếng Thái, tiếng Nhật, tiếng Nga vào danh sách — chúng đâu có
#: "dấu", nhưng chúng cũng chẳng phải ASCII, và phép kiểm bên dưới sẽ báo chữ bản địa của
#: chính thị trường đó là "không thuộc thị trường này".
#:
#: `IN` cố ý vẫn là `en` dù tiếng Hindi dùng chữ Devanagari: truy vấn mua sắm ở Ấn Độ áp đảo
#: là tiếng Anh hoặc Hinglish viết bằng chữ Latin, nên coi thị trường đó là ASCII thuần đúng
#: hơn là sai. Đổi lại, gõ Devanagari vào thị trường Ấn sẽ bị nhắc nhầm — đã cân nhắc và chấp
#: nhận, vì chiều ngược lại bỏ lọt trường hợp thường gặp hơn nhiều.
#: `nl` nằm ở đây chứ không ở `LATIN_DIACRITIC_LANGUAGES`: tiếng Hà Lan CÓ ë và ï, nhưng truy
#: vấn mua sắm thì gần như không bao giờ dùng tới ("dames jas", "heren schoenen"). Xếp nó vào
#: nhóm ASCII thuần thì bắt được "áo khoác" gõ nhầm vào thị trường Hà Lan; xếp vào nhóm kia
#: thì mất phép kiểm ấy để đổi lấy một trường hợp hiếm. Đã cân nhắc và chọn cái thứ nhất.
DIACRITIC_FREE_LANGUAGES = frozenset({"en", "tl", "id", "ms", "nl"})

#: Ngôn ngữ viết bằng chữ Latin CÓ dấu.
#:
#: Bổ cho `DIACRITIC_FREE_LANGUAGES` để bịt một lỗ hổng mà chính bản vá tiếng Thái mở ra: khi
#: Thái Lan thôi là "ASCII thuần", gõ "áo khoác" vào thị trường đó không còn bị nhắc nữa —
#: chữ Thái không phải ASCII nên phép kiểm kia im lặng.
#:
#: Luật thứ hai vá đúng chỗ đó: từ gốc có dấu KIỂU LATIN, mà thị trường lại không viết bằng
#: chữ Latin có dấu, thì gần như chắc chắn là gõ nhầm ngôn ngữ. Bắt được "áo khoác" ở Thái
#: Lan và Nhật Bản, trong khi vẫn để yên chữ Thái ở Thái Lan.
#:
#: Tiếng Đức có mặt ở đây nên "áo khoác" ở thị trường Đức KHÔNG bị bắt — hai ngôn ngữ dùng
#: chung dải ký tự Latin có dấu thì không tách được bằng phép kiểm ký tự. Đã cân nhắc: bỏ
#: sót một trường hợp hiếm còn hơn nhắc nhầm mỗi khi người dùng gõ "größe".
#:
#: `pt` BẮT BUỘC có mặt, không phải tuỳ chọn. Thiếu nó thì luật 2 bắt ngay chính tiếng bản
#: địa của thị trường: "tênis" — từ khoá thời trang phổ biến nhất Brazil và là cụm đo thật
#: trên `shopee.com.br` — có "ê" nằm trong dải Latin có dấu, nên sẽ bị báo là "người Brazil
#: không tìm bằng thứ chữ này". Đúng kiểu lỗi mà bản vá tiếng Thái từng mắc, chỉ khác ngôn ngữ.
#:
#: Tiếng Trung (cả `zh-Hant` lẫn `zh-Hans`) KHÔNG được vào đây: chữ Hán không nằm trong dải
#: Latin nên luật 2 im lặng với "洋裝" và "连衣裙" (đúng), trong khi vẫn bắt được "áo khoác"
#: gõ nhầm vào thị trường Đài Loan hay Trung Quốc (cũng đúng).
#: `fr`, `it`, `es`, `pl`, `sv` BẮT BUỘC có mặt, cùng lý do đã bắt buộc `pt`: thiếu chúng thì
#: luật 2 bắt ngay chính tiếng bản địa của thị trường. "vêtement", "camicia più", "años",
#: "spódnica", "väska" đều mang ký tự trong dải Latin có dấu, nên sẽ bị báo là "người Pháp
#: không tìm bằng thứ chữ này" — đúng kiểu lỗi mà bản vá tiếng Thái từng mắc.
#:
#: Cái giá đi kèm cũng giống hệt tiếng Đức: "áo khoác" gõ nhầm vào thị trường Pháp KHÔNG bị
#: bắt, vì hai ngôn ngữ dùng chung dải ký tự thì không tách được bằng phép kiểm ký tự.
LATIN_DIACRITIC_LANGUAGES = frozenset({"vi", "de", "pt", "fr", "it", "es", "pl", "sv"})

#: Ngôn ngữ KHÔNG đặt dấu cách giữa các từ, nên ghép từ mở rộng phải nối liền.
#:
#: Đo trên Taobao ngày 2026-08-10, cùng một từ bổ nghĩa cho ra hai tập khác hẳn nhau:
#:
#:     "连衣裙大码"   → 连衣裙大码女胖mm, 连衣裙大码女胖mm遮肚子轻奢高级感
#:     "连衣裙 大码"  → 连衣裙 大码 收腰, 连衣裙 大码 a字, 连衣裙 大码 长袖
#:
#: Bản có dấu cách vẫn trả về mười mục nên nhìn qua tưởng ổn, nhưng nó là những chuỗi rời rạc
#: chứ không phải cách người Trung Quốc thật sự gõ — và nó không phải tập đã dùng để chọn bảng
#: `RETAIL_MODIFIERS["zh-Hans"]`. Đây đúng kiểu hỏng im lặng: đủ số lượng, sai nội dung.
#:
#: CHỈ chứa hai biến thể tiếng Trung, vì đó là những gì đã ĐO. Tiếng Nhật và tiếng Thái cũng
#: không dùng dấu cách giữa từ nên nhiều khả năng thuộc về đây, nhưng cả hai đang chạy với
#: dấu cách và chưa được đo lại — thêm vào mà không đo là đổi hành vi của thị trường đang
#: hoạt động dựa trên một suy luận.
#:
#: Chỉ áp cho HẬU TỐ. Với tiền tố thì đo thấy hai cách cho kết quả y hệt ("平价连衣裙" và
#: "平价 连衣裙" trùng khít), nên chỗ đó không cần phân biệt.
SPACELESS_LANGUAGES = frozenset({"zh-Hant", "zh-Hans"})


def joins_without_space(country: str) -> bool:
    """Thị trường này ghép từ mở rộng có cần dấu cách không."""
    return language_for(country) in SPACELESS_LANGUAGES


#: Các dải ký tự Latin có dấu: Latin-1 Supplement, Latin Extended-A/B, Latin Extended
#: Additional. Dải cuối là nơi chứa phần lớn nguyên âm có dấu của tiếng Việt.
#:
#: Cố ý KHÔNG chứa dải nào của tiếng Thái, kana hay chữ Hán — với những chữ đó, "có dấu hay
#: không" là một câu hỏi vô nghĩa.
_LATIN_DIACRITIC_RANGES = ((0x00C0, 0x024F), (0x1E00, 0x1EFF))


def _has_latin_diacritics(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in _LATIN_DIACRITIC_RANGES) for char in text
    )


@lru_cache(maxsize=None)
def language_chain(country: str) -> tuple[str, ...]:
    """
    Các ngôn ngữ của một thị trường, theo thứ tự ưu tiên giảm dần.

    `PH` cho `("tl", "en")`, `US` cho `("en",)`, `VN` cho `("vi",)`.
    """
    language = LANGUAGE_BY_MARKET.get(country.upper(), DEFAULT_LANGUAGE)
    chain = [language]
    fallback = LANGUAGE_FALLBACK.get(language)
    if fallback and fallback not in chain:
        chain.append(fallback)
    return tuple(chain)


#: Tên tiếng Việt của từng mã ngôn ngữ.
#:
#: Chỉ để VIẾT RA — cho người đọc, hoặc cho một mô hình đọc. Mục Cơ hội gọi `language_names`
#: để nói thẳng vào prompt rằng thị trường này viết bằng thứ tiếng gì, thay vì để mô hình tự
#: suy từ mã nước và thỉnh thoảng suy trượt (đo 2026-08-18: `PH` ra tên món tiếng Tây Ban Nha).
#:
#: Mọi giá trị của `LANGUAGE_BY_MARKET` đều PHẢI có mặt ở đây; `language_names` bỏ qua mã lạ
#: thay vì ném lỗi, nên một mã thiếu sẽ hỏng im lặng thành "không nói gì về ngôn ngữ".
LANGUAGE_NAME_VI: dict[str, str] = {
    "vi": "tiếng Việt",
    "en": "tiếng Anh",
    "tl": "tiếng Tagalog",
    "id": "tiếng Indonesia",
    "ms": "tiếng Mã Lai",
    "th": "tiếng Thái",
    "de": "tiếng Đức",
    "ja": "tiếng Nhật",
    "pt": "tiếng Bồ Đào Nha",
    "fr": "tiếng Pháp",
    "it": "tiếng Ý",
    "es": "tiếng Tây Ban Nha",
    "nl": "tiếng Hà Lan",
    "pl": "tiếng Ba Lan",
    "sv": "tiếng Thuỵ Điển",
    "zh-Hant": "tiếng Trung phồn thể",
    "zh-Hans": "tiếng Trung giản thể",
}


def language_names(country: str) -> tuple[str, ...]:
    """
    Tên các ngôn ngữ của thị trường, theo thứ tự ưu tiên. RỖNG khi thị trường không có trong
    bảng.

    Rỗng là một câu trả lời, không phải một lỗi: `LANGUAGE_BY_MARKET` không phủ hết danh sách
    ISO, và nước nào không có trong đó thì `language_chain` trả về tiếng Việt theo mặc định.
    Đem cái mặc định ấy đi khai với một mô hình sẽ thành "viết tên món bằng tiếng Việt cho thị
    trường Bỉ" — tệ hơn hẳn việc không nói gì và để mô hình tự biết. Nên nơi gọi phải phân biệt
    được "biết chắc" với "không có trong bảng", và đó là lý do hàm này tồn tại tách khỏi
    `language_chain`.
    """
    if country.upper() not in LANGUAGE_BY_MARKET:
        return ()
    return tuple(
        LANGUAGE_NAME_VI[code] for code in language_chain(country) if code in LANGUAGE_NAME_VI
    )


def language_for(country: str) -> str:
    """Ngôn ngữ chính của thị trường — dùng khi chỉ cần chọn một biến thể xử lý, không phải vốn từ."""
    return language_chain(country)[0]


#: Ngôn ngữ hiểu lẫn nhau tới mức người mua ở thị trường này vẫn gõ bằng ngôn ngữ kia.
#:
#: HẸP có chủ đích. Đây không phải bảng "ngôn ngữ gần giống nhau" mà là danh sách các cặp mà
#: bỏ đi sẽ vứt nhầm dữ liệu thật: đo trên TikTok với từ gốc "baju" ở Indonesia, 4/8 gợi ý
#: được khai là `ms` — và chúng là gợi ý đúng, vì tiếng Mã Lai với tiếng Indonesia gần như là
#: một khi nói chuyện mua bán quần áo. Không có cặp nào khác đủ gần để vào đây.
NEIGHBOUR_LANGUAGES: dict[str, tuple[str, ...]] = {
    "id": ("ms",),
    "ms": ("id",),
}


@lru_cache(maxsize=None)
def _accepted_languages(country: str) -> frozenset[str]:
    accepted: set[str] = set()
    for language in language_chain(country):
        accepted.add(language)
        accepted.update(NEIGHBOUR_LANGUAGES.get(language, ()))
    return frozenset(accepted)


def language_matches_market(tag: str, country: str) -> bool:
    """
    Một kết quả tự khai ngôn ngữ `tag` có thuộc về thị trường này không?

    Dành cho nguồn nào tự nói ra ngôn ngữ của TỪNG kết quả — hiện chỉ TikTok, qua
    `extra_info.lang`. Nó là cách duy nhất bắt được kiểu sai thầm lặng nhất mà nguồn đó mắc:
    endpoint gợi ý của TikTok trả kết quả theo IP máy chủ, nên đo ngày 2026-08-06 thấy từ gốc
    `洋裝` ở thị trường Đài Loan nhận về 6/8 gợi ý TIẾNG NHẬT (kể cả `洋服の青山`, tên một chuỗi
    cửa hàng Nhật), còn `vestido` ở Brazil nhận về 7/8 gợi ý TIẾNG TÂY BAN NHA của Peru và
    Colombia. Không có gì báo lỗi; chúng chỉ lặng lẽ được xếp hạng như từ khoá của thị trường
    người dùng đã chọn.

    Thẻ rỗng thì CHO QUA. Thiếu dữ liệu không phải bằng chứng sai — vứt kết quả vì nguồn quên
    khai ngôn ngữ là tự bịa ra một kết luận từ sự im lặng.

    So ở phần gốc của thẻ BCP 47: `zh-Hant` và `zh-Hans` đều là `zh`, `pt-BR` là `pt`.
    """
    base = (tag or "").strip().lower().split("-")[0]
    if not base:
        return True
    return base in _accepted_languages(country.upper())


def market_descriptors() -> dict[str, dict[str, object]]:
    """
    Bảng ngôn ngữ theo thị trường, dạng gửi được qua JSON.

    Tồn tại để giao diện kiểm được "từ gốc có thuộc thị trường này không" ngay trong trình
    duyệt — tức thì, không request nào cho mỗi lần gõ phím hay đổi ô Quốc gia. Giao diện lấy
    bảng này ĐÚNG MỘT LẦN lúc tải trang.

    Cố ý công bố bảng thay vì để giao diện tự chép một danh sách "nước nói tiếng Việt": chép
    là tạo ra bản thứ hai của cùng một sự thật, và hai bản đó sẽ lệch nhau ngay lần đầu có
    người thêm một thị trường mà chỉ sửa một bên.

    Khoá viết camelCase vì đây là đường đi thẳng ra JSON, không qua `CamelModel`.
    """
    return {
        code: {
            "language": language,
            #: Truy vấn của thị trường này viết bằng chữ Latin thuần ASCII.
            "diacriticFree": language in DIACRITIC_FREE_LANGUAGES,
            #: Thị trường này viết bằng chữ Latin CÓ dấu — khi đó "từ gốc có dấu" không nói
            #: lên điều gì. Gửi cả hai cờ ĐÃ TÍNH SẴN để giao diện không phải chép lại luật.
            "latinDiacritics": language in LATIN_DIACRITIC_LANGUAGES,
        }
        for code, language in LANGUAGE_BY_MARKET.items()
    }


def seed_looks_out_of_market(seed: str, country: str) -> bool:
    """
    Từ gốc viết bằng thứ chữ mà thị trường này không dùng — gần như chắc chắn là gõ nhầm.

    HAI luật, và cần cả hai vì chúng bắt hai kiểu nhầm khác nhau:

      1. Thị trường viết ASCII thuần (Mỹ, Philippines…) mà từ gốc có ký tự ngoài ASCII.
         Bắt "áo khoác" ở Philippines, và cả "เสื้อกันหนาว" ở Mỹ.
      2. Thị trường không viết chữ Latin có dấu (Thái, Nhật…) mà từ gốc lại có dấu kiểu Latin.
         Bắt "áo khoác" ở Thái Lan — trường hợp mà luật 1 bỏ sót, vì chữ Thái cũng không phải
         ASCII nên Thái Lan không nằm trong nhóm ASCII thuần.

    Không luật nào chạy ở thị trường Việt Nam, và luật 2 không chạy ở Đức — xem
    `LATIN_DIACRITIC_LANGUAGES`.
    """
    language = language_for(country)
    if language in DIACRITIC_FREE_LANGUAGES and any(ord(char) > 127 for char in seed):
        return True
    return language not in LATIN_DIACRITIC_LANGUAGES and _has_latin_diacritics(seed)


def merge_by_language(table: Mapping[str, Sequence[str]], country: str) -> list[str]:
    """
    Gộp một bảng từ vựng theo chuỗi ngôn ngữ của thị trường, giữ nguyên thứ tự và bỏ trùng.

    Thứ tự có ý nghĩa ở cả hai nơi dùng bảng: `build_terms` cắt danh sách theo độ sâu người
    dùng chọn nên mục đứng trước là mục thật sự được hỏi, còn `detect_season` xét lần lượt
    nên mục đứng trước là mục thắng. Cả hai trường hợp đều muốn tiếng bản địa đứng trước
    tiếng Anh.
    """
    merged: dict[str, None] = {}
    for language in language_chain(country):
        for entry in table.get(language, ()):
            merged[entry] = None
    return list(merged)
