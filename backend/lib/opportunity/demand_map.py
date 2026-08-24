"""
GỢI Ý THEO BỐI CẢNH: hỏi bằng câu nói bình thường, nhận về các món hàng nên bán.

Ba bước, cùng khuôn với `keywords/bridge.py`:

    1. đề xuất    mô hình nghĩ ra các món theo chuỗi hệ quả   (trí nhớ — sai được)
    2. hỏi sàn    ô tìm kiếm của sàn hoàn thiện từng món      (dữ liệu thật)
    3. chấm lại   mô hình ĐỌC dữ liệu đó, không nhớ lại nữa   (kiểm được)

Bước 2 chỉ chứng minh SÀN CÓ BÁN món đó, không chứng minh có bao nhiêu người mua. Muốn biết
lượng cầu thì bấm sang mục Từ khoá qua `OpportunityItem.search_term`.

VÀO BẰNG CẢ CUỘC TRÒ CHUYỆN, không phải một ô "bối cảnh". Ô đơn ấy buộc người dùng tự dịch
câu hỏi trong đầu — "shop mình bán đồ mẹ và bé, sắp tựu trường thì nên nhập gì" — thành một
cụm hai chữ mà công cụ chịu ăn, rồi vứt sạch mọi chi tiết vừa bỏ đi. Nhận nguyên câu hỏi thì
những chi tiết ấy đi thẳng vào phần đề xuất, và câu hỏi tiếp theo không phải nhắc lại từ đầu.

Đổi lại, bước 1 phải quyết thêm một việc trước khi làm gì khác: câu vừa gõ có cần một BẢNG
MỚI không. Xem `AnswerMode` ở `types.py`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from lib.keywords.gloss import GEMINI_API_KEY, call_gemini
from lib.keywords.types import SearchContext

from .evidence import flatten, probe_terms
from .types import STATUS_ORDER, TIER_ORDER, DemandMap, OpportunityItem

MAP_TTL_MS = 24 * 60 * 60 * 1000

MAX_ITEMS = 15

#: Phần lớn diện tích dành cho những món sát và hữu ích nhất. Nhóm khám phá vẫn còn, nhưng
#: không được lấn át câu hỏi thực tế của người dùng.
TIER_QUOTA = {"core": 7, "adjacent": 5, "hidden": 3}

#: Bao nhiêu lượt gần nhất được đưa vào prompt.
#:
#: Cắt bớt vì hai lý do, và lý do thứ hai mới là lý do chính: một cuộc trò chuyện dài chỉ tốn
#: token thì còn chịu được, nhưng mười lượt bối cảnh cũ nằm trong prompt sẽ kéo câu trả lời về
#: phía những gì đã nói, đúng lúc người dùng vừa đổi hẳn sang chuyện khác.
MAX_TURNS = 8

#: Bao nhiêu câu hỏi tiếp theo được bày ra dưới mỗi lượt trả lời.
MAX_FOLLOW_UPS = 3


@dataclass
class ChatTurn:
    """Một lượt trong cuộc trò chuyện, đúng như giao diện đang giữ."""

    role: str
    text: str = ""
    #: Tên các món của lượt đó — chỉ có ở lượt trả lời. Đưa vào prompt để câu hỏi kiểu "món
    #: thứ hai bán ở đâu" có cái để trỏ vào.
    items: list[str] = field(default_factory=list)


_ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["products", "talk"]},
        "reply": {"type": "string"},
        "situation": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "gloss": {"type": "string"},
                    "tier": {"type": "string", "enum": ["core", "adjacent", "hidden"]},
                    "pain": {"type": "string"},
                    "usefulness": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["term", "gloss", "tier", "pain", "usefulness"],
            },
        },
        "followUps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["mode", "reply", "situation", "items", "followUps"],
}


def _market_language(country: str) -> str:
    """
    Mệnh đề nói tên món phải viết bằng thứ tiếng gì, hoặc một câu chung khi không biết chắc.

    GỌI TÊN NGÔN NGỮ RA thay vì để mô hình suy từ mã nước. Đo 2026-08-18: hỏi thị trường `PH`
    thì tên món về bằng TIẾNG TÂY BAN NHA ("linterna LED recargable de emergencia") — mô hình
    đi từ "Philippines" qua lịch sử thuộc địa chứ không qua thứ tiếng người ta đang gõ. Lượt
    chạy vẫn thành công, vẫn ra mười lăm món, chỉ là không cụm nào tìm được ở thị trường đó.

    Thị trường KHÔNG có trong `LANGUAGE_BY_MARKET` thì trả về câu chung, cố ý. Bảng ấy không
    phủ hết danh sách ISO, và ép một cái mặc định — tiếng Việt — vào prompt sẽ bảo mô hình
    viết tên món tiếng Việt cho thị trường Bỉ. Đó là thay một phỏng đoán thường đúng bằng một
    mệnh lệnh chắc chắn sai. Xem `market.language_names`.
    """
    from lib.keywords.market import language_names

    names = language_names(country)
    if not names:
        return f"viết bằng NGÔN NGỮ của thị trường {country}"
    if len(names) == 1:
        return f"viết bằng {names[0].upper()}"
    # Nhiều ngôn ngữ là chuyện thật chứ không phải phòng hờ: người Philippines gõ lẫn Tagalog
    # với tiếng Anh trong cùng một phiên, và ép về đúng một thứ tiếng là vứt nửa vốn từ của
    # thị trường đó. Để mô hình chọn theo từng món, nhưng chỉ trong khung này.
    joined = " hoặc ".join(name.upper() for name in names)
    return (
        f"viết bằng {joined} — chọn thứ tiếng mà người mua ở đó THẬT SỰ gõ cho đúng món này, "
        f"không dịch máy móc sang một thứ tiếng khác"
    )


def _transcript(turns: list[ChatTurn]) -> str:
    """Cuộc trò chuyện dưới dạng chữ, lượt cũ nhất trước."""
    lines: list[str] = []
    for turn in turns[-MAX_TURNS:]:
        if turn.role == "user":
            lines.append(f"NGƯỜI DÙNG: {turn.text}")
            continue
        body = turn.text or "(đã trả lời)"
        if turn.items:
            body += f"\n    [bảng đã đưa ra: {', '.join(turn.items)}]"
        lines.append(f"BẠN: {body}")
    return "\n".join(lines)


def _ask_prompt(turns: list[ChatTurn], country: str) -> str:
    """Chọn kiểu trả lời trước, rồi mới mở rộng theo chuỗi hệ quả nếu cần một bảng."""
    return (
        f"Bạn là trợ lý tìm hàng cho một người Việt bán hàng online ở thị trường {country}. "
        f"Bạn nói tiếng Việt thường, ngắn gọn, như một người trong nghề — không gạch đầu dòng "
        f"dài, không khẩu hiệu, không hứa hẹn doanh thu.\n\n"
        f"CUỘC TRÒ CHUYỆN ĐẾN LÚC NÀY (lượt cuối là câu vừa gõ):\n"
        f"{_transcript(turns)}\n\n"
        f"BƯỚC ĐẦU TIÊN — chọn `mode` cho lượt cuối:\n"
        f'- "products": câu này hỏi NÊN BÁN GÌ / NHẬP GÌ cho một bối cảnh, một mùa, một dịp, '
        f"một nhóm khách, một ngành hàng; hoặc xin đổi lại bảng theo một điều kiện mới (rẻ "
        f"hơn, nhẹ vốn hơn, cho khách nam, cho miền Bắc...). Cần một bảng món hàng MỚI.\n"
        f'- "talk": mọi câu còn lại — hỏi về chính bảng vừa đưa ra, hỏi cách bán, hỏi công cụ '
        f"này làm được gì, chào hỏi, hoặc câu quá mơ hồ chưa đủ để đề xuất. KHÔNG dựng bảng; "
        f"trả lời thẳng bằng lời, và nếu câu còn mơ hồ thì hỏi lại ĐÚNG MỘT câu cho rõ.\n"
        f'Nghi ngờ thì chọn "talk". Một bảng mười lăm món không ai hỏi thì tệ hơn một câu trả '
        f"lời đúng chỗ.\n\n"
        f"`reply` — LUÔN phải có, tối đa 3 câu tiếng Việt. Với talk thì đây chính là câu trả "
        f"lời. Với products thì nói ra ý mà một cái bảng không nói được: bạn hiểu họ đang ở "
        f"tình huống nào, và vì sao nhóm món bên dưới hợp với tình huống đó. Đừng liệt kê lại "
        f"tên các món — chúng đã nằm ngay bên dưới.\n\n"
        f"`followUps` — {MAX_FOLLOW_UPS} câu hỏi TIẾP THEO, viết ở ngôi của NGƯỜI DÙNG, mỗi "
        f"câu tối đa 8 chữ, bấm vào là gửi đi được luôn. Phải bám đúng chuyện vừa nói, và "
        f"không được lặp lại câu họ vừa hỏi.\n\n"
        f'Nếu mode là "talk": để `situation` rỗng, `items` là mảng rỗng, và DỪNG ở đây.\n\n'
        f'=== PHẦN DƯỚI CHỈ ÁP DỤNG KHI mode LÀ "products" ===\n\n'
        f"`situation`: viết lại tình huống của họ thành MỘT CÂU tiếng Việt, gộp cả những chi "
        f"tiết đã nói ở các lượt trước (ngành đang bán, vốn, nhóm khách, vùng miền). Câu này "
        f"để họ bắt lỗi nếu bạn hiểu sai ý.\n\n"
        f"Rồi liệt kê các MÓN HÀNG KHÁC NHAU mà tình huống này sinh ra nhu cầu. Mục tiêu số "
        f"một là HỮU ÍCH VÀ SÁT Ý ĐỊNH của người vừa hỏi; độ lạ không phải một lợi thế.\n\n"
        f"CÁCH NGHĨ — đi theo CHUỖI HỆ QUẢ, đừng liệt kê 'sản phẩm liên quan'. Hỏi liên tục "
        f"'rồi chuyện gì xảy ra tiếp?' cho tới khi ra một món hàng:\n"
        f"    mùa mưa → quần áo phơi không khô → ẩm và hôi mốc → XỊT THƠM QUẦN ÁO, MÁY SẤY MINI\n"
        f"    mùa mưa → sàn nhà trơn ướt → ngã, bẩn → THẢM CHÙI CHÂN SIÊU THẤM, DÉP CHỐNG TRƯỢT\n"
        f"    mùa mưa → đồ điện tử dính nước → hỏng → TÚI CHỐNG NƯỚC ĐIỆN THOẠI, HỘP HÚT ẨM\n\n"
        f"BA MỨC ƯU TIÊN:\n"
        f"- core ({TIER_QUOTA['core']} món): nên xem trước — nhu cầu trực tiếp, phổ biến và có "
        f"khả năng mua cao trong đúng bối cảnh.\n"
        f"- adjacent ({TIER_QUOTA['adjacent']} món): hữu ích tiếp theo — liên hệ rõ ràng nhưng "
        f"chỉ cần ở một phần tình huống.\n"
        f"- hidden ({TIER_QUOTA['hidden']} món): khám phá thêm — hệ quả bậc hai vẫn hợp lý, "
        f"nhưng ít phổ biến hoặc ít cấp thiết hơn.\n"
        f"Ví dụ với 'sinh viên nhập học', bàn học gấp gọn, đèn bàn, vali và ổ cắm phục vụ "
        f"trực tiếp hơn các vấn đề ngẫu nhiên của một phòng trọ cũ. Không được suy diễn từ "
        f"'sinh viên' thành mọi bất tiện có thể xảy ra khi ở trọ.\n\n"
        f"Với MỖI món:\n"
        f"- term: tên món hàng {_market_language(country)}, đúng như người ta gõ vào ô tìm "
        f"kiếm. Không kèm chữ bổ nghĩa như giá rẻ / loại tốt.\n"
        f"- gloss: nghĩa TIẾNG VIỆT của term, tối đa 6 chữ, chỉ gọi tên món hàng. Để CHUỖI "
        f"RỖNG khi term đã là tiếng Việt — người đọc là người Việt, nên dịch tiếng Việt sang "
        f"tiếng Việt chỉ tốn một dòng để nói lại đúng chữ ngay bên trên nó.\n"
        f"- tier: core | adjacent | hidden\n"
        f"- pain: nhu cầu món này giải quyết, tiếng Việt, tối đa 10 chữ\n"
        f"- usefulness: số nguyên 0-100. Chấm theo độ sát câu người dùng vừa hỏi, tỷ lệ người "
        f"trong đúng bối cảnh có nhu cầu, mức cấp thiết và khả năng giải quyết bằng món hàng. "
        f"KHÔNG cộng điểm vì bất ngờ hoặc độc lạ. 90-100 là gần như thiết yếu; 70-89 là rất "
        f"hữu ích; 50-69 là hữu ích cho một nhóm; dưới 50 là gợi ý phụ.\n\n"
        f"BẮT BUỘC:\n"
        f"- chỉ HÀNG VẬT LÝ gửi được qua chuyển phát. Không dịch vụ, không đồ ăn tươi, không "
        f"hàng quá khổ.\n"
        f"- KHÔNG tên thương hiệu, không tên shop.\n"
        f"- mỗi món một dòng, không trùng nhau, không phải hai cách gọi của cùng một thứ.\n"
        f"- nếu người dùng vừa xin đổi bảng theo một điều kiện, ĐỪNG chép lại các món của lượt "
        f"trước trừ khi chúng vẫn thoả điều kiện mới.\n"
        f"- trả các món theo usefulness giảm dần trong từng mức ưu tiên. Loại bỏ món có chuỗi "
        f"gượng ép hoặc chỉ dựa trên định kiến chung, không do chính bối cảnh tạo ra."
    )


@dataclass
class _Proposal:
    term: str
    gloss: str
    tier: str
    pain: str
    usefulness: int


@dataclass
class _Answer:
    mode: str = "talk"
    reply: str = ""
    situation: str = ""
    items: list[_Proposal] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    error: str | None = None


async def _ask(turns: list[ChatTurn], country: str) -> _Answer:
    payload = {
        "contents": [{"parts": [{"text": _ask_prompt(turns, country)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _ASK_SCHEMA,
            # Giữ một chút đa dạng giữa các lần chạy, nhưng không quá cao để thứ tự ưu tiên
            # của cùng một bối cảnh bị đảo lộn mạnh.
            "temperature": 0.5,
        },
    }
    try:
        data = await call_gemini(payload)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except Exception as error:
        return _Answer(error=str(error) or type(error).__name__)

    items: list[_Proposal] = []
    seen: set[str] = set()
    for entry in parsed.get("items", []):
        term = (entry.get("term") or "").strip()
        tier = (entry.get("tier") or "").strip()
        if not term or tier not in TIER_ORDER or term.lower() in seen:
            continue
        seen.add(term.lower())
        items.append(
            _Proposal(
                term=term,
                gloss=_clean_gloss(term, entry.get("gloss")),
                tier=tier,
                pain=(entry.get("pain") or "").strip(),
                usefulness=_clamp_score(entry.get("usefulness")),
            )
        )

    # `mode` do mô hình khai, nhưng một lượt khai "products" mà không đẻ ra món nào thì trên
    # thực tế là một lượt nói chuyện — tin theo nhãn đó chỉ dựng ra một khối bảng rỗng.
    mode = "products" if parsed.get("mode") == "products" and items else "talk"

    follow_ups = [
        line.strip()
        for line in parsed.get("followUps", [])
        if isinstance(line, str) and line.strip()
    ]
    return _Answer(
        mode=mode,
        reply=(parsed.get("reply") or "").strip(),
        situation=(parsed.get("situation") or "").strip() if mode == "products" else "",
        items=items[:MAX_ITEMS],
        follow_ups=follow_ups[:MAX_FOLLOW_UPS],
    )


_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "status": {"type": "string", "enum": ["real", "niche", "wrong"]},
                    "searchTerm": {"type": "string"},
                    "usefulness": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["term", "status", "searchTerm", "usefulness"],
            },
        }
    },
    "required": ["verdicts"],
}


def _verify_prompt(seed: str, country: str, evidence: dict[str, dict[str, list[str]]]) -> str:
    """`not_found` không có trong danh sách nhãn — trạng thái đó do code gán ở `_judge`."""
    blocks = []
    for term, by_source in evidence.items():
        lines = [f'\n"{term}"']
        if not by_source:
            lines.append("  (không sàn nào ở thị trường này có gợi ý cho cụm này)")
        for source_id, words in by_source.items():
            lines.append(f"  {source_id} hoàn thiện thành: {' / '.join(words)}")
        blocks.append("\n".join(lines))

    return (
        f'Một mô hình vừa đề xuất các món hàng dưới đây cho yêu cầu "{seed}" ở thị trường '
        f"{country}. Kèm theo là DỮ LIỆU THẬT: chính ô tìm kiếm của các sàn ở thị trường đó "
        f"hoàn thiện mỗi cụm thành những gì.\n\n"
        f"ĐỌC DỮ LIỆU ĐÓ để phán xét, đừng dựa vào trí nhớ. Cách một sàn hoàn thiện một cụm cho "
        f"biết ở đó người ta có thật sự mua bán món này không, và mua bán dưới tên gì.\n"
        f"{''.join(blocks)}\n\n"
        f"Với MỖI cụm, trả về:\n"
        f"- term: chép lại NGUYÊN VĂN\n"
        f"- status:\n"
        f"    real   sàn hoàn thiện thành nhiều biến thể của ĐÚNG món đó — ngành hàng có thật, "
        f"đang được bán\n"
        f"    niche  sàn có nhận nhưng gợi ý ít, hoặc lệch sang thứ chỉ gần giống — ngách hẹp\n"
        f"    wrong  gợi ý nói về MỘT MÓN KHÁC HẲN — mô hình đã đặt tên sai cho món này\n"
        # `reason` — một câu 12 chữ chép ra các cụm gợi ý làm bằng chứng — từng nằm ngay đây.
        # Gỡ cùng lúc với phần mở ra ở giao diện, vì đó là chỗ duy nhất đọc nó. Prompt cũ còn
        # phải cấm mô hình mở đầu bằng "Sàn gợi ý"; cả đoạn dặn dò ấy giờ không phải trả tiền
        # nữa. Nhãn trạng thái vẫn còn, và nó vẫn do chính dữ liệu sàn quyết định.
        f"- searchTerm: CHÉP NGUYÊN VĂN một trong các gợi ý ở trên — cụm mô tả đúng món hàng "
        f"nhất và có nhiều người gõ nhất. KHÔNG được tự viết ra một cụm không có trong danh "
        f"sách. Để chuỗi rỗng nếu status là wrong.\n"
        f'- usefulness: chấm lại 0-100 cho độ HỮU ÍCH của món đối với đúng yêu cầu "{seed}". '
        f"Ưu tiên (1) sát ý định, (2) nhiều người trong bối cảnh thật sự cần, (3) cấp thiết, "
        f"(4) giải quyết được bằng hàng vật lý. Giảm mạnh món chỉ liên quan tới một giả định "
        f"phụ hoặc chuỗi hệ quả gượng ép. Không cộng điểm vì lạ. Dữ liệu sàn chỉ chứng minh "
        f"có mặt hàng, không tự động chứng minh món đó hữu ích cho bối cảnh."
    )


async def _verify(
    seed: str, country: str, evidence: dict[str, dict[str, list[str]]]
) -> dict[str, tuple[str, str, str, int]]:
    """Chấm cả bảng trong một lượt gọi. Hỏng thì trả về rỗng — bảng vẫn hiện."""
    payload = {
        "contents": [{"parts": [{"text": _verify_prompt(seed, country, evidence)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _VERIFY_SCHEMA,
            "temperature": 0,
        },
    }
    try:
        data = await call_gemini(payload)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except Exception:
        return {}

    out: dict[str, tuple[str, str, int]] = {}
    for entry in parsed.get("verdicts", []):
        term = (entry.get("term") or "").strip()
        status = (entry.get("status") or "").strip()
        if term and status in STATUS_ORDER:
            out[term] = (
                status,
                (entry.get("searchTerm") or "").strip(),
                _clamp_score(entry.get("usefulness")),
            )
    return out


def _judge(
    term: str,
    samples: list[str],
    verdicts: dict[str, tuple[str, str, int]],
    proposed_usefulness: int,
) -> tuple[str, str, int]:
    """
    HAI LUẬT CỨNG mà prompt không được ghi đè.

    Không bằng chứng thì `not_found`. Và `search_term` phải là MỘT TRONG các chuỗi bằng chứng —
    cụm này chảy thẳng sang mục Từ khoá làm từ gốc, một cụm do mô hình tự viết sẽ hỏng ở tận
    bên kia, nơi triệu chứng chỉ là "bảng rỗng".
    """
    if not samples:
        return "not_found", "", proposed_usefulness

    status, search_term, usefulness = verdicts.get(
        term, ("not_found", "", proposed_usefulness)
    )
    if status == "not_found":
        return status, "", usefulness

    allowed = {word.lower(): word for word in samples}
    picked = allowed.get(search_term.lower(), "")
    if not picked and status != "wrong":
        picked = samples[0]
    return status, picked, usefulness


def _clean_gloss(term: str, value: object) -> str:
    """
    Dòng nghĩa, đã bỏ những lượt dịch không nói thêm được gì.

    Mô hình vẫn thỉnh thoảng chép nguyên `term` sang ô `gloss` khi thị trường nói tiếng Việt,
    bất kể prompt bảo để rỗng. Một dòng lặp lại đúng chữ ngay bên trên nó thì tệ hơn không có
    dòng nào, nên luật này nằm ở CODE chứ không nằm ở prompt.
    """
    gloss = (value or "").strip() if isinstance(value, str) else ""
    return "" if gloss.lower() == term.strip().lower() else gloss


def _clamp_score(value: object) -> int:
    """Giữ đầu ra mô hình trong miền hợp lệ, kể cả khi provider bỏ qua JSON Schema."""
    try:
        return max(0, min(100, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


#: Điểm hữu ích tối thiểu để một món được hiện ra.
#:
#: Dưới ngưỡng này thì món đó bị BỎ HẲN, không phải xếp xuống cuối bảng. Nhóm "khám phá thêm"
#: từng làm việc xếp-xuống-cuối ấy và nó không dùng được: người dùng hỏi "nên bán gì", mà một
#: danh sách kèm mấy dòng tự khai là kém hữu ích thì chỉ tốn chỗ và tốn lượt đọc.
#:
#: Chỉ chặn ở khâu HIỂN THỊ. `TIER_QUOTA` — số món mô hình được đề xuất ở mỗi mức xa gần —
#: giữ nguyên, vì đó là bộ máy tìm ra những món lệch khỏi từ gốc (mùa mưa → máy sấy giày).
#: Bóp phần đề xuất là bóp đúng thứ làm nên tính năng này.
USEFULNESS_FLOOR = 50


def _priority_tier(usefulness: int) -> str:
    """Biến điểm thành các nhóm hiển thị có thứ tự đơn điệu theo độ hữu ích."""
    return "core" if usefulness >= 75 else "adjacent"


async def map_demand(turns: list[ChatTurn], ctx: SearchContext) -> DemandMap:
    """Trả lời một lượt trò chuyện. Không ném lỗi — mọi kết cục đều kèm `message`."""
    started_at = time.monotonic()
    country = ctx.country.upper()
    question = next((t.text for t in reversed(turns) if t.role == "user"), "")

    def elapsed() -> int:
        return round((time.monotonic() - started_at) * 1000)

    if not GEMINI_API_KEY:
        return DemandMap(
            seed=question,
            country=country,
            mode="talk",
            message="Chưa cấu hình GEMINI_API_KEY nên chưa trả lời được",
            took_ms=elapsed(),
        )

    answer = await _ask(turns, country)
    if answer.error:
        return DemandMap(
            seed=question,
            country=country,
            mode="talk",
            message=f"Không trả lời được: {answer.error}",
            took_ms=elapsed(),
        )

    # Lượt nói chuyện dừng ở đây: không hỏi sàn, không chấm lại, nên nó về trong khoảng một
    # giây thay vì mười — đúng nhịp mà một câu hỏi ngắn cần.
    if answer.mode == "talk":
        return DemandMap(
            seed=question,
            country=country,
            mode="talk",
            reply=answer.reply or "Bạn đang muốn tìm hàng cho tình huống nào?",
            follow_ups=answer.follow_ups,
            took_ms=elapsed(),
        )

    terms = [p.term for p in answer.items]
    evidence = await probe_terms(terms, ctx)
    verdicts = await _verify(question, country, evidence)

    items: list[OpportunityItem] = []
    for proposal in answer.items:
        samples = flatten(evidence.get(proposal.term, {}))
        status, search_term, usefulness = _judge(
            proposal.term, samples, verdicts, proposal.usefulness
        )
        if usefulness < USEFULNESS_FLOOR:
            continue
        items.append(
            OpportunityItem(
                term=proposal.term,
                gloss=proposal.gloss,
                tier=_priority_tier(usefulness),  # type: ignore[arg-type]
                pain=proposal.pain,
                usefulness=usefulness,
                status=status,  # type: ignore[arg-type]
                search_term=search_term,
            )
        )

    # Điểm hữu ích quyết định cả nhóm lẫn thứ tự. Trạng thái sàn chỉ phá hoà: autocomplete
    # chứng minh mặt hàng có bán, không chứng minh nó phù hợp hơn với bối cảnh người dùng.
    items.sort(
        key=lambda i: (
            TIER_ORDER.get(i.tier, 9),
            -i.usefulness,
            STATUS_ORDER.get(i.status, 9),
        )
    )

    # CHỈ MỘT `message`, cho đúng một tình huống: không có bảng nào cả.
    #
    # Từng có thêm một dòng nữa, báo khi cả bảng không món nào đối chiếu được với sàn. Bỏ đi
    # vì nó nói lại điều mà chính cái bảng đã nói: nhãn xanh "sàn có bán" vắng mặt ở mọi dòng
    # là đã đủ thấy. Một khung cảnh báo vàng nằm trên đầu câu trả lời để nhắc lại chuyện đó
    # chỉ làm mỗi lượt trả lời trông như một lượt hỏng.
    message = None
    if not items:
        # Có đề xuất nhưng không món nào qua ngưỡng. Nói thẳng ra, vì một bảng rỗng không kèm
        # lý do đọc thành "công cụ hỏng" — trong khi đây là câu trả lời đúng: câu hỏi này
        # không sinh ra nhu cầu mua bán nào đủ rõ.
        message = (
            f"Đã nghĩ ra {len(answer.items)} món cho câu này nhưng không món nào đủ hữu ích "
            "để đề xuất. Thử mô tả tình huống cụ thể hơn."
        )

    return DemandMap(
        seed=question,
        country=country,
        # Đề xuất có mà không món nào qua ngưỡng thì đây là một lượt nói chuyện kèm lời giải
        # thích, không phải một bảng rỗng.
        mode="products" if items else "talk",
        reply=answer.reply,
        situation=answer.situation,
        items=items,
        follow_ups=answer.follow_ups,
        message=message,
        took_ms=elapsed(),
    )
