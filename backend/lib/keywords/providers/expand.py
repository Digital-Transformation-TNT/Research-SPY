"""
Bộ máy mở rộng long-tail, dùng chung cho mọi nguồn từ khoá.

Ý tưởng: API gợi ý chỉ hoàn thiện phần đuôi của chuỗi, nên muốn thấy biến thể nào thì phải
có thứ trỏ tới nó. Vì vậy ta không hỏi mỗi "quần jeans" mà hỏi "quần jeans", "quần jeans
nam", "quần jeans mùa", "quần jeans a"…

BA TRỤC MỞ RỘNG, và trục thứ ba là trục quan trọng nhất mà bản đầu thiếu:

  1. hậu tố  — "quần jeans" + " nam"     (từ bổ nghĩa bán lẻ)
  2. chữ cái — "quần jeans" + " a"       (độ phủ không thiên lệch)
  3. TIỀN TỐ — "top " + "quần jeans"     (thêm 2026-08-07)

Trục thứ ba tồn tại vì một giới hạn CẤU TRÚC chứ không phải vì hỏi chưa đủ nhiều: chừng nào
từ gốc còn đứng đầu chuỗi thì mọi thứ autocomplete trả về đều bắt đầu bằng từ gốc. Cả vùng
"top …", "review …", "các loại …" nằm ngoài tầm với, và không lượt gọi thêm nào chạm tới được.

Đo 2026-08-07, 5 lượt mỗi trục trên cùng một từ gốc: tiền tố đóng góp 37 cụm mới cho TikTok,
37 cho Shopee, 24 cho Amazon — với Shopee và Amazon thì 100% là cụm chưa từng thấy ở trục
hậu tố. Nghĩa là chia hạn mức cho hai trục thu được nhiều hơn dồn hết vào một trục.

Đo cũ trên một từ gốc: 12 lượt gọi thu về 138 từ khoá duy nhất từ Shopee và 91 từ TikTok,
không lỗi lần nào, với khoảng cách 700ms giữa các lượt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lib.core.http import sleep

from ..market import joins_without_space, merge_by_language
from ..provider import KeywordProvider
from ..types import WORLDWIDE, SearchContext, SourceHit

#: Từ mở rộng.
#:
#: Chỉ dùng chữ cái đơn là không đủ. Đo trên "quần jeans": mở rộng bằng chữ cái không ra
#: được từ khoá theo mùa nào — trong khi đưa thẳng "mùa" vào thì cả Shopee lẫn TikTok đều
#: trả về "quần jeans mùa hè", "quần jeans mùa đông" và 36 biến thể khác.
#:
#: Nên phần mở rộng trộn hai loại: từ bổ nghĩa bán lẻ (chạm thẳng vào phần long-tail có giá
#: trị thương mại) và chữ cái (cho độ phủ không thiên lệch).
#:
#: Danh sách theo ngôn ngữ được GỘP theo chuỗi của thị trường (xem `lib/keywords/market.py`),
#: nên Philippines hỏi cả "pambabae" lẫn "women" trong cùng một lượt chạy — đúng cách người
#: ở đó gõ.
RETAIL_MODIFIERS: dict[str, list[str]] = {
    "vi": [
        "nam",
        "nữ",
        "mùa",
        "mùa hè",
        "mùa đông",
        "giá",
        "đẹp",
        "size",
        "cao cấp",
        "rẻ",
        "big size",
        "form",
        "loại",
        "hot trend",
    ],
    "en": [
        "women",
        "men",
        "kids",
        "size",
        "plus size",
        "cheap",
        "price",
        "sale",
        "best",
        "summer",
        "winter",
        "style",
        "outfit",
        "set",
        "new",
    ],
    "tl": ["pambabae", "panlalaki", "bata", "murang", "presyo", "sale", "cod", "terno", "bagong"],
    # Tiếng Nhật cố ý KHÔNG có bảng riêng: mở rộng theo tiền tố ở đó cần kana, mà đoán bừa
    # vài chữ kana còn tệ hơn là để rơi về tiếng Anh — người Nhật vẫn gõ tên hãng và nhiều
    # danh từ hàng hoá bằng chữ Latin.
    "de": ["damen", "herren", "kinder", "günstig", "preis", "größe", "set", "neu", "schwarz"],
    "id": ["wanita", "pria", "anak", "murah", "harga", "terbaru", "grosir", "promo", "set"],
    "ms": ["wanita", "lelaki", "kanak", "murah", "harga", "terbaru", "borong", "promosi", "set"],
    # Hai bảng dưới đây KHÔNG phải dịch từ bảng tiếng Anh mà lấy từ chính kết quả `search_hint`
    # đo ngày 2026-08-06 trên `shopee.tw` và `shopee.com.br`. Dịch sang sẽ ra "洋裝 便宜" đúng
    # ngữ pháp nhưng lệch thói quen gõ; còn "大尺碼", "正韓", "小個子" thì Shopee TW tự trả về.
    #
    # Không có chữ cái Latin đi kèm cho tiếng Trung — xem `LETTERS`.
    "zh-Hant": [
        "女",
        "男",
        "大尺碼",
        "韓版",
        "正韓",
        "日系",
        "夏天",
        "冬天",
        "顯瘦",
        "現貨",
        "便宜",
        "特價",
        "童裝",
        "小個子",
    ],
    # Giản thể, cho Trung Quốc đại lục. KHÔNG phải bản chuyển tự của bảng phồn thể phía trên
    # mà là kết quả đo trên chính Taobao ngày 2026-08-10 — mỗi mục dưới đây đều trả về 10 gợi
    # ý đầy đủ. Hai mục bị loại sau khi đo: "热门" trả về 0, và "男" chỉ trả 4 nên xuống cuối.
    "zh-Hans": [
        "女",
        "长裙",
        "夏",
        "大码",
        "显瘦",
        "新款",
        "气质",
        "高级感",
        "宽松",
        "雪纺",
        "学生",
        "男",
    ],
    "pt": [
        "feminino",
        "masculino",
        "infantil",
        "barato",
        "preço",
        "promoção",
        "kit",
        "conjunto",
        "plus size",
        "academia",
        "na moda",
        "verão",
        "inverno",
        "novo",
    ],
    # Nhóm châu Âu, vào bảng cùng lúc với các thị trường tương ứng ở `market.py`.
    #
    # Có bảng riêng CHỨ KHÔNG chỉ mượn tiếng Anh qua `LANGUAGE_FALLBACK`, vì thứ tự trong
    # `merge_by_language` là thứ tự thật sự được hỏi: `build_terms` cắt danh sách theo độ sâu
    # người dùng chọn, nên nếu chỉ có mục tiếng Anh thì mọi lượt gọi ở Pháp đều đi hỏi
    # "jean women" thay vì "jean femme". Mượn tiếng Anh vẫn còn đó, chỉ là xếp sau.
    #
    # Mỗi bảng bắt đầu bằng cặp giới tính rồi tới giá và mùa, giống mọi bảng phía trên: đó là
    # ba trục mà ô gợi ý của sàn phân nhánh mạnh nhất.
    "fr": [
        "femme",
        "homme",
        "enfant",
        "pas cher",
        "prix",
        "grande taille",
        "été",
        "hiver",
        "soldes",
        "ensemble",
        "cuir",
        "coton",
    ],
    "it": [
        "donna",
        "uomo",
        "bambino",
        "economico",
        "prezzo",
        "taglie forti",
        "estate",
        "inverno",
        "offerta",
        "set",
        "pelle",
        "cotone",
    ],
    "es": [
        "mujer",
        "hombre",
        "niño",
        "barato",
        "precio",
        "tallas grandes",
        "verano",
        "invierno",
        "oferta",
        "conjunto",
        "piel",
        "algodón",
    ],
    "nl": [
        "dames",
        "heren",
        "kinderen",
        "goedkoop",
        "prijs",
        "grote maten",
        "zomer",
        "winter",
        "aanbieding",
        "set",
        "leer",
        "katoen",
    ],
    "pl": [
        "damskie",
        "męskie",
        "dziecięce",
        "tanie",
        "cena",
        "duże rozmiary",
        "letnie",
        "zimowe",
        "promocja",
        "zestaw",
        "skórzane",
        "bawełniane",
    ],
    "sv": [
        "dam",
        "herr",
        "barn",
        "billig",
        "pris",
        "stora storlekar",
        "sommar",
        "vinter",
        "rea",
        "set",
        "skinn",
        "bomull",
    ],
}

#: Từ đứng TRƯỚC từ gốc.
#:
#: Đây là trục mở rộng thứ hai, và nó gần như không chồng lấn với trục hậu tố. Đo ngày
#: 2026-08-07, mỗi bên 5 lượt gọi trên cùng một từ gốc:
#:
#:     nguồn    hậu tố   tiền tố   gộp lại   tiền tố đóng góp MỚI
#:     TikTok      40       40       77            37
#:     Shopee      60       37       97            37   (100% là cụm mới)
#:     Amazon      30       24       54            24   (100% là cụm mới)
#:
#: Lý do đơn giản: autocomplete HOÀN THIỆN PHẦN ĐUÔI. Chừng nào từ gốc còn đứng đầu chuỗi thì
#: mọi thứ nó trả về đều bắt đầu bằng từ gốc — cả một vùng truy vấn nằm ngoài tầm về mặt cấu
#: trúc, chứ không phải vì hỏi chưa đủ nhiều. Đẩy từ gốc ra sau là cách duy nhất chạm tới
#: "top ...", "review ...", "các loại ...".
#:
#: Danh sách cố ý NGẮN hơn `RETAIL_MODIFIERS`: `DEPTH_CALLS` chia chung một hạn mức lượt gọi
#: cho cả ba trục, nên thêm một tiền tố là bớt một hậu tố hoặc một chữ cái.
PREFIX_MODIFIERS: dict[str, list[str]] = {
    "vi": ["top", "review", "các loại", "cách chọn", "so sánh", "giá"],
    "en": ["best", "top", "cheap", "types of", "how to choose"],
    "tl": ["best", "murang", "anong"],
    "id": ["rekomendasi", "harga", "jenis"],
    "ms": ["terbaik", "harga", "jenis"],
    "de": ["beste", "günstige", "welche"],
    "pt": ["melhor", "top", "tipos de", "como escolher"],
    "fr": ["meilleur", "pas cher", "quel", "comment choisir"],
    "it": ["migliore", "economico", "quale", "come scegliere"],
    "es": ["mejor", "barato", "cuál", "cómo elegir"],
    "nl": ["beste", "goedkope", "welke"],
    "pl": ["najlepszy", "tani", "jaki"],
    "sv": ["bäst", "billig", "vilken"],
    # Tiếng Trung đặt từ bổ nghĩa TRƯỚC danh từ, nên trục này hợp với nó hơn hẳn trục hậu tố —
    # và nó bù lại đúng chỗ `LETTERS` không phục vụ được chữ Hán.
    "zh-Hant": ["推薦", "平價", "好用", "熱門"],
    # Đo trên Taobao: "平價"/"爆款"/"小个子" đều trả 10 gợi ý, "推荐" trả 7. Bản phồn thể
    # "熱門" trả 0 nên bản giản thể "热门" cũng bị loại.
    "zh-Hans": ["平价", "爆款", "小个子", "推荐"],
}

#: Từ bổ nghĩa chỉ có nghĩa ở một nước, xếp TRƯỚC danh sách theo ngôn ngữ.
#:
#: Đứng trước là vì thứ tự quyết định cái gì thật sự được hỏi: `DEPTH_CALLS` cắt danh sách ở
#: 12 lượt gọi cho lần chạy "Nhanh", nên mục nằm cuối chỉ tồn tại trên giấy. Những cụm này
#: đáng chỗ ở đầu vì chúng không suy ra được từ ngôn ngữ — "boxing day" là chuyện của lịch
#: nước Anh, "onhand" là cách người bán Philippines nói "có hàng sẵn".
MARKET_MODIFIERS: dict[str, list[str]] = {
    "US": ["petite", "tall", "free shipping"],
    "GB": ["uk", "next day", "boxing day"],
    "PH": ["onhand", "ukay", "legit", "budget"],
    "ID": ["gratis ongkir", "termurah"],
    "MY": ["termurah", "free postage"],
}

#: Chữ cái dùng để mở rộng, theo tần suất chữ ĐẦU của từ trong ngôn ngữ đó.
#:
#: Tần suất mới là điều đáng quan tâm chứ không phải bảng chữ cái: mỗi chữ tốn một lượt gọi
#: và độ sâu "Nhanh" chỉ có mười hai lượt chia cho cả ba trục, nên thứ tự sai nghĩa là
#: tiêu lượt gọi vào những chữ gần như không mở đầu từ nào. Cũng vì vậy mà "đ" không được
#: xuất hiện ngoài tiếng Việt — không từ tiếng Anh nào bắt đầu bằng nó, nên đó là một lượt
#: gọi chắc chắn trả về rỗng.
#: Tiếng Trung CỐ Ý không có bảng ở đây, cùng lý do với tiếng Nhật ở `RETAIL_MODIFIERS` nhưng
#: dứt khoát hơn: mở rộng theo tiền tố cần một ký tự MỞ ĐẦU được từ, mà chữ Hán có hàng nghìn
#: ký tự như vậy — chọn hai mươi cái là chọn bừa. Vắng mặt ở đây khiến `merge_by_language` trả
#: về danh sách rỗng cho `zh`, và `build_terms` tự động chỉ dùng từ bổ nghĩa. Đó là hành vi
#: đúng, không phải thiếu sót cần vá.
LETTERS: dict[str, list[str]] = {
    "vi": [
        "n", "c", "d", "l", "s", "b", "t", "m", "o", "g",
        "h", "k", "x", "r", "v", "a", "đ", "p", "q", "u",
    ],
    "en": [
        "s", "c", "b", "w", "m", "p", "d", "t", "f", "g",
        "l", "r", "h", "n", "a", "o", "k", "v", "j", "e",
    ],
    # Tiếng Bồ có bảng riêng thay vì mượn tiếng Anh: "w", "k", "j" gần như không mở đầu từ Bồ
    # nào ngoài từ vay mượn, còn "ç" thì không bao giờ đứng đầu từ nên cũng không có mặt.
    "pt": [
        "c", "p", "a", "m", "e", "s", "d", "t", "b", "f",
        "r", "i", "l", "v", "g", "n", "o", "h", "j", "q",
    ],
}


def build_terms(seed: str, country: str) -> list[str]:
    """
    Dựng danh sách truy vấn cho một từ gốc, trộn xen kẽ BA trục mở rộng.

    Trả về truy vấn ĐẦY ĐỦ chứ không phải hậu tố như bản trước. Bắt buộc phải vậy từ khi có
    `PREFIX_MODIFIERS`: một hậu tố thì nơi gọi tự ghép được, còn tiền tố thì không — và để nơi
    gọi tự đoán mục nào ghép trước mục nào ghép sau là chia một quy tắc ra làm hai chỗ.

    Xen kẽ theo vòng, mỗi vòng lấy một mục của mỗi trục theo thứ tự: hậu tố → tiền tố → chữ
    cái. Thứ tự này quyết định thật chứ không phải trang trí, vì `DEPTH_CALLS` CẮT danh sách:
    lần chạy "Nhanh" chỉ có mười hai lượt, nên mục nằm sau vị trí đó không tồn tại. Xếp cả
    một trục lên trước trục kia sẽ khiến lần chạy Nhanh chỉ có đúng một loại độ phủ.

    Đo 2026-08-07: chia đều hạn mức cho hai trục cho ra NHIỀU từ khoá hơn là dồn hết vào một
    trục, vì hai trục gần như không trả về cụm trùng nhau — xem `PREFIX_MODIFIERS`.
    """
    modifiers = MARKET_MODIFIERS.get(country.upper(), []) + merge_by_language(RETAIL_MODIFIERS, country)
    prefixes = merge_by_language(PREFIX_MODIFIERS, country)
    letters = merge_by_language(LETTERS, country)

    # Chữ Hán không đặt dấu cách giữa từ, và với ô gợi ý thì đó không phải chuyện thẩm mỹ:
    # "连衣裙大码" và "连衣裙 大码" trả về hai tập khác hẳn nhau — xem `SPACELESS_LANGUAGES`.
    # Chỉ áp cho hậu tố; tiền tố đo thấy hai cách cho kết quả y hệt.
    gap = "" if joins_without_space(country) else " "

    terms: list[str] = [seed]
    for i in range(max(len(modifiers), len(prefixes), len(letters))):
        if i < len(modifiers):
            terms.append(f"{seed}{gap}{modifiers[i]}")
        if i < len(prefixes):
            terms.append(f"{prefixes[i]}{gap}{seed}")
        if i < len(letters):
            terms.append(f"{seed}{gap}{letters[i]}")
    return terms


#: Số lượt gọi mỗi nguồn theo độ sâu người dùng chọn.
#:
#: Nâng khoảng một phần ba khi trục tiền tố ra đời (9/19/35 → 12/25/45), và con số này đến từ
#: một phép đo chứ không phải cảm tính. Giữ nguyên 9 lượt mà thêm trục thứ ba thì tổng từ khoá
#: GIẢM — đo trên "sữa rửa mặt": Shopee 94 → 87. Lý do là tiền tố có sản lượng mỗi lượt thấp
#: hơn hậu tố (7,4 so với 12 cụm), nên nhét ba trục vào cùng một hạn mức là đổi những lượt gọi
#: năng suất cao lấy những lượt năng suất thấp.
#:
#: Trục tiền tố vẫn đáng có, nhưng nó phải được CẤP THÊM chỗ chứ không phải giành chỗ: các cụm
#: nó tìm ra gần như không trùng hai trục kia, tức là độ phủ mới thật, không phải lặp lại.
DEPTH_CALLS = {"quick": 12, "normal": 25, "deep": 45}

#: Khoảng cách MẶC ĐỊNH giữa hai lượt gọi cùng một nguồn. Đo thấy an toàn ở 700ms với Shopee,
#: TikTok và Amazon. Nguồn nào cần rộng hơn thì tự khai qua `KeywordProvider.call_delay_ms`.
CALL_DELAY_MS = 700


@dataclass
class ExpansionOutcome:
    hits: list[SourceHit] = field(default_factory=list)
    calls: int = 0
    error: str | None = None


async def expand_with_provider(
    provider: KeywordProvider, seed: str, ctx: SearchContext, depth: str
) -> ExpansionOutcome:
    """
    Chạy một nguồn qua toàn bộ danh sách từ mở rộng, tuần tự.

    Lỗi giữa chừng vẫn giữ lại những gì đã thu được: độ phủ từ khoá thiếu một phần vẫn dùng
    được, trong khi vứt hết sẽ biến một nguồn chậm thành một nguồn mất tích.
    """
    country = ctx.country
    if provider.markets is not None and country.upper() not in provider.markets:
        scope = "phạm vi toàn thế giới" if country.upper() == WORLDWIDE else country
        return ExpansionOutcome(hits=[], calls=0, error=f"{provider.label} không hoạt động ở {scope}")

    # Nguồn không mở rộng được thì hỏi đúng một lần bằng chính từ gốc.
    if not provider.expands_terms:
        terms = [seed]
    else:
        terms = build_terms(seed, country)[: DEPTH_CALLS[depth]]

    # Trần riêng của nguồn cắt SAU trần theo mức, không thay thế nó: mức "Nhanh" đã dưới trần
    # thì trần không được phép nới nó rộng ra.
    if provider.max_terms is not None:
        terms = terms[: provider.max_terms]

    hits: list[SourceHit] = []
    calls = 0
    error: str | None = None

    if provider.batches_terms:
        return await _expand_batched(provider, terms, ctx)

    for term in terms:
        try:
            results = await provider.fetch_suggestions(term, ctx)
            calls += 1
            for index, entry in enumerate(results):
                raw = (entry.keyword or "").strip()
                if raw:
                    hits.append(
                        SourceHit(
                            source=provider.id,
                            position=index,
                            via_term=term,
                            native_score=entry.score,
                            demand=entry.demand,
                            rising=entry.rising,
                            change_percent=entry.change_percent,
                            raw=raw,
                        )
                    )
        except Exception as e:
            # `str(e)` rỗng với những ngoại lệ không mang message — `NotImplementedError()` là
            # ví dụ hay gặp nhất. Để nguyên thì `outcome.error` thành chuỗi rỗng, nơi gọi đọc
            # ra là "không có lỗi", và một nguồn chết hẳn lại hiện thành "kết nối được nhưng
            # không trả về từ khoá nào" — sai hoàn toàn về nguyên nhân.
            error = str(e) or f"{type(e).__name__} (không kèm mô tả)"
            break  # một lần hỏng thường kéo theo phần còn lại cũng hỏng; giữ lại những gì đã có
        await sleep(provider.call_delay_ms or CALL_DELAY_MS)

    return ExpansionOutcome(hits=hits, calls=calls, error=error)


async def _expand_batched(
    provider: KeywordProvider, terms: list[str], ctx: SearchContext
) -> ExpansionOutcome:
    """
    Nhánh cho nguồn hỏi gộp: một lời gọi cho cả danh sách cụm.

    Tính là MỘT lượt gọi, vì đó đúng là một lượt: con số này hiện ra giao diện như chi phí
    của lần tìm, và đếm 12 cho một lần đi hỏi sẽ nói dối về chi phí thật.

    Không có `sleep` giữa các cụm — việc giãn nhịp thuộc về nơi thực sự gõ vào trang, tức là
    chính extension. Thêm một lần chờ ở đây chỉ làm chậm mà không đổi được nhịp gọi ra ngoài.
    """
    hits: list[SourceHit] = []
    try:
        by_term = await provider.fetch_suggestions_batch(terms, ctx)
    except Exception as e:
        # Giữ nguyên cách diễn giải lỗi rỗng của nhánh thường — xem ghi chú ở `expand_with_provider`.
        return ExpansionOutcome(hits=[], calls=0, error=str(e) or f"{type(e).__name__} (không kèm mô tả)")

    for term in terms:
        for index, entry in enumerate(by_term.get(term, [])):
            raw = (entry.keyword or "").strip()
            if not raw:
                continue
            hits.append(
                SourceHit(
                    source=provider.id,
                    position=index,
                    via_term=term,
                    native_score=entry.score,
                    demand=entry.demand,
                    rising=entry.rising,
                    change_percent=entry.change_percent,
                    raw=raw,
                )
            )
    return ExpansionOutcome(hits=hits, calls=1, error=None)
