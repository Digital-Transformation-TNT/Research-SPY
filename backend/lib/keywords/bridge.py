"""
Bắc cầu từ gốc: từ một cụm tiếng Việt sang cụm mà người bản địa thật sự gõ.

Đây là bước cuối của việc mở tab từ khoá ra thị trường ngoài, và nó giải quyết vấn đề mà ba
bước trước không chạm tới: người dùng biết mình muốn bán quần jeans ở Philippines, nhưng
không biết gõ gì vào ô từ gốc. Dịch từ điển thì hỏng ngay ở món hàng đầu tiên — người
Philippines gọi quần jeans là "maong pants", người Mỹ gõ "wide leg jeans" chứ không ai gõ
"loose jeans". Dịch đúng ngữ pháp và đúng thứ người ta gõ là hai chuyện khác nhau.

CÁCH LÀM: ĐỀ CỬ NHANH, ĐỂ NGƯỜI DÙNG CHỌN.

Gemini sinh tối đa năm cách gọi (nghĩa đen, tiếng lóng bản địa, tên tiếng Anh phổ thông),
Amazon lọc bỏ những cụm không sàn nào từng nghe tới, và bảng hiện ra trong khoảng ba giây để
người dùng chọn.

BẢN ĐẦU CÓ MỘT BƯỚC ĐO BẰNG GOOGLE TRENDS, VÀ NÓ ĐÃ BỊ GỠ. Ý tưởng khi đó là để Trends làm
trọng tài chấm điểm các đề cử. Đo lại ngày 2026-08-04 thì bước ấy tốn khoảng tám giây trong
tổng mười bốn giây, và thứ nó mua về không giúp ra quyết định: với từ gốc "áo khoác", Gemini
đề cử `jacket · hoodie · windbreaker · sweater · bomber` — NĂM SẢN PHẨM KHÁC NHAU, đều có
thật, đều có người mua. Trends nói được `jacket` nhiều lượt tìm nhất, nhưng nếu người dùng
định bán áo gió thì con số đó vô nghĩa.

Không phép đo nào trả lời được câu "bạn định bán cái gì". Nên bước đo bị gỡ, và thứ thay thế
nó là một cú bấm chọn — thứ vốn đã cần có ở đó.

Trends không mất đi: cụm được chọn sẽ đi qua chính `/api/keywords`, nơi nó được đo bằng cả
bảng truy vấn liên quan, đầy đủ hơn hẳn một con số trung bình. Đo hai lần cùng một thứ, một
lần trước và một lần sau, là trả tiền hai lần cho một câu trả lời.

Vẫn giữ nguyên tắc của `gloss.py`: hàm này KHÔNG tự thay từ gốc — nó trả về cả bảng, người
dùng bấm chọn.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Literal

from lib.core.model import CamelModel

from .gloss import GEMINI_API_KEY, GEMINI_ENDPOINT, GEMINI_MODEL
from .market import language_for
from .types import SearchContext

#: Số cách gọi đề cử.
#:
#: Vẫn là năm dù bước đo bằng Trends đã bị gỡ — không phải vì sức chứa một nhóm so sánh nữa,
#: mà vì đây là số dòng người ta còn đọc và so được bằng mắt. Mười cách gọi cho một ngành
#: hàng là bắt người dùng làm việc thay vì giúp họ.
MAX_CANDIDATES = 5

#: Bản dịch không cũ đi, và đây là bảng người dùng hay mở lại nhiều lần trong một buổi.
BRIDGE_TTL_MS = 24 * 60 * 60 * 1000


#: Cụm này có đúng là ngành hàng người dùng hỏi không, sau khi đối chiếu với dữ liệu sàn.
#:
#: Sáu nhãn chứ không phải "đúng/sai", vì bốn kiểu lệch dưới đây đòi bốn cách xử lý khác nhau
#: và gộp chúng lại là vứt đi đúng phần thông tin có ích. `subtype` vẫn đáng chọn nếu người
#: dùng định bán đúng loại đó; `different` thì không bao giờ.
BridgeVerdict = Literal["same", "subtype", "broader", "brand", "different", "misspelling", "unknown"]

#: Thứ tự hiển thị theo phán quyết. Nhỏ hơn là lên trước.
#:
#: `unknown` nằm giữa chứ không nằm cuối: nó nghĩa là CHƯA ĐỐI CHIẾU ĐƯỢC (thị trường không có
#: sàn nào trong sổ đăng ký, hoặc lượt chấm lỗi), và đẩy một cụm xuống đáy vì ta không kiểm
#: được nó thì cũng sai như đẩy nó lên đầu.
VERDICT_ORDER: dict[str, int] = {
    "same": 0,
    "subtype": 1,
    "broader": 2,
    "unknown": 3,
    "brand": 4,
    "different": 5,
    "misspelling": 6,
}


class SeedCandidate(CamelModel):
    """Một cách gọi ngành hàng ở thị trường đích."""

    term: str
    #: Vì sao Gemini đề cử cụm này — "nghĩa đen", "tiếng lóng bản địa", "tên tiếng Anh".
    #:
    #: ĐO THẤY KHÔNG ĐÁNG TIN, 2026-08-12, nên giao diện không hiện nó nữa: `风衣` (áo gió, từ
    #: điển chuẩn) bị gán "tiếng lóng bản địa", `保温壶` bị gán "tên địa phương", `球鞋` và `耳塞`
    #: cũng vậy. Mô hình tự khai vì sao nó nghĩ ra một cụm, và lời khai đó không kiểm được.
    #: Giữ lại trong dữ liệu vì nó là thứ duy nhất còn khi `verdict` là `unknown`.
    note: str
    #: Phán quyết sau khi đối chiếu với chính ô tìm kiếm của sàn ở thị trường đó.
    verdict: BridgeVerdict = "unknown"
    #: Một câu tiếng Việt DẪN RA bằng chứng — "sàn hoàn thiện thành mút trang điểm".
    #:
    #: Đây mới là thứ người dùng đọc. Nó thay hẳn `note`, và khác `note` ở chỗ kiểm được: mọi
    #: câu ở đây đều nói về dữ liệu có thật trong `evidence`.
    reason: str = ""
    #: Vài gợi ý thật mà sàn trả về cho cụm này — bằng chứng thô, chưa dịch.
    #:
    #: Đi kèm để người dùng rê chuột xem được thứ mà phán quyết dựa vào, thay vì phải tin.
    evidence: list[str] = []


class BridgeResult(CamelModel):
    seed: str
    country: str
    #: Đã xếp: đo được đứng trước, trong đó cụm mạnh nhất đứng đầu.
    candidates: list[SeedCandidate] = []
    #: Cụm đáng dùng làm từ gốc, hoặc `None` khi không cụm nào đo được.
    #:
    #: Chỉ là ĐỀ CỬ. Không có gì trong hệ thống tự thay từ gốc bằng nó — người dùng bấm chọn,
    #: vì họ là người biết mình định bán cái gì còn công cụ chỉ biết cụm nào nhiều người gõ.
    chosen: str | None = None
    message: str | None = None
    took_ms: int = 0


_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["term", "note"],
            },
        }
    },
    "required": ["candidates"],
}


def _prompt(seed: str, country: str) -> str:
    """
    Yêu cầu ĐA DẠNG chứ không yêu cầu ĐÚNG, và đó là điểm khác biệt với `gloss.py`.

    Ở đây một đề cử sai không tốn gì: người dùng nhìn qua là bỏ. Còn một đề cử bị bỏ sót thì
    mất luôn — không có bước nào phía sau tìm lại được cách gọi mà mô hình không nghĩ ra. Nên
    hướng dẫn đẩy về phía phủ rộng: bắt buộc có cả tiếng lóng lẫn tên tiếng Anh phổ thông, vì
    hai loại đó thắng ở hai kiểu thị trường khác nhau.

    ĐÃ THỬ SIẾT CHO CHÍNH XÁC HƠN VÀ NÓ PHẢN TÁC DỤNG, đo 2026-08-12. Prompt được thêm một cảnh
    báo "tiếng lóng phải đúng THỊ TRƯỜNG chứ không chỉ đúng ngôn ngữ", kèm hai ví dụ sai có thật
    (波鞋 là tiếng Quảng Đông chứ không phải Đài Loan; "celana" là tiếng Indonesia chứ không
    phải Philippines). Kết quả sửa được hai chỗ và làm hỏng hai chỗ khác:

        TW  bỏ được 波鞋, nhưng đẻ ra 布鞋 — giày vải, một mặt hàng khác hẳn
        CN  mất 风衣 (áo gió, hàng riêng có thật), thay bằng 外套儿 không ai gõ
        ID  mất "lipstik" — đúng cách viết phổ biến nhất của thị trường đó
        PH  bỏ được "pants" quá chung, và đẩy "maong pants" lên đầu (chỗ này thật sự tốt hơn)

    Khác hẳn `MARKET_JARGON` ở `gloss.py`, nơi cùng một kiểu can thiệp lại hiệu quả tuyệt đối.
    Lý do: ở đó ta bơm vào những CÂU TRẢ LỜI ĐÃ BIẾT cho những cụm đã biết, còn ở đây mô hình
    phải nghĩ ra cái ta chưa biết. Bảo nó "đừng đoán sai" chỉ làm nó rụt rè, và cái nó bỏ đi
    là những cụm đúng mà ta không có cách nào tìm lại.
    """
    return (
        f'Người dùng muốn bán ngành hàng "{seed}" (tiếng Việt) ở thị trường {country}.\n\n'
        f"Liệt kê tối đa {MAX_CANDIDATES} CÁCH GỌI mà người mua hàng ở {country} thật sự gõ "
        f"vào ô tìm kiếm cho ngành hàng này.\n\n"
        f"Bắt buộc phủ đủ các loại sau, mỗi loại ít nhất một cụm nếu có:\n"
        f"- tên thông dụng nhất ở thị trường đó\n"
        f"- tiếng lóng hoặc từ địa phương (ví dụ người Philippines gọi quần jeans là "
        f'"maong pants")\n'
        f"- tên tiếng Anh phổ thông, kể cả khi thị trường không nói tiếng Anh\n\n"
        f"Mỗi cụm kèm `note`: một cụm từ TIẾNG VIỆT tối đa 6 chữ nói đó là loại nào "
        f'(ví dụ "tên thông dụng", "tiếng lóng bản địa", "tên tiếng Anh").\n\n'
        f"Chỉ trả về cụm dùng để tìm ngành hàng, KHÔNG kèm chữ bổ nghĩa như nam/nữ/giá rẻ — "
        f"phần đó do bước mở rộng lo. Không giải thích gì thêm."
    )


#: Nguồn KHÔNG dùng để lấy bằng chứng, dù nó phục vụ mọi thị trường.
#:
#: Google Trends cần một trình duyệt thật và mất hàng chục giây cho mỗi lượt; nhân với năm đề
#: cử thì cả bảng này không còn là "công cụ trợ giúp cạnh ô nhập liệu" nữa. Nó cũng trả lời
#: sai câu hỏi ở đây — ta cần biết một CỤM được dùng cho mặt hàng nào, không cần biết nó có
#: bao nhiêu lượt tìm.
EVIDENCE_EXCLUDED = {"trends"}

#: Nhiều nhất mấy sàn được hỏi cho mỗi đề cử.
#:
#: Hai, và con số này có lý do chứ không phải cho tròn. Thị trường Trung Quốc có ba nguồn
#: (Taobao, 1688, Douyin) nên không giới hạn thì mỗi lượt bấm là 5 × 3 = 15 lượt gọi. Quan
#: trọng hơn: hai sàn đã đủ để lộ ra kiểu lỗi mà một sàn không bắt được — xem `_verify`.
MAX_EVIDENCE_SOURCES = 2

#: Lấy mấy gợi ý đầu của mỗi sàn làm bằng chứng. Sáu là đủ để thấy cụm đó nói về mặt hàng gì,
#: và ngắn để lượt chấm không phải đọc một khối văn bản dài hơn phần hướng dẫn.
EVIDENCE_PER_SOURCE = 6


def _evidence_sources(country: str) -> list[str]:
    """
    Các sàn phục vụ thị trường này, dùng để đối chiếu đề cử.

    Suy từ chính sổ đăng ký thay vì viết cứng, nên thêm một nguồn mới là bảng bắc cầu tự có
    thêm bằng chứng ở thị trường đó. Trước đây chỗ này viết cứng "amazon", và hậu quả không
    hiện thành lỗi mà thành một cột trống: đo 2026-08-12 trên sáu thị trường thì năm trong sáu
    (PH, CN, ID, TW, BR) không có lấy một mẩu bằng chứng nào, vì Amazon không phục vụ chúng.

    Nhập tại chỗ chứ không ở đầu file: `providers/__init__.py` là sổ đăng ký nạp toàn bộ các
    nguồn, và bắt nó chạy chỉ vì `bridge` được import là buộc mọi thứ phụ thuộc chặt hơn mức cần.
    """
    from .providers import KEYWORD_PROVIDERS

    code = country.upper()
    usable = [
        source_id
        for source_id, provider in KEYWORD_PROVIDERS.items()
        if source_id not in EVIDENCE_EXCLUDED
        and (provider.markets is None or code in provider.markets)
    ]
    return usable[:MAX_EVIDENCE_SOURCES]


async def _gather_evidence(
    terms: list[str], ctx: SearchContext
) -> dict[str, dict[str, list[str]]]:
    """
    Hỏi từng sàn xem nó hoàn thiện mỗi đề cử thành những gì.

    ĐÂY LÀ THỨ THAY CHO PHÉP ĐẾM CŨ, và lý do thay nằm ở một phép đo: đếm số gợi ý không phân
    biệt được gì cả. Cụm bịa "celana jeans" (tiếng Indonesia) hỏi ở Philippines vẫn trả về 12
    gợi ý; "son môi" hỏi ở Indonesia cũng 12. Mọi sàn đều cắt danh sách ở một con số cố định
    nên cụm nào cũng chạm trần, và con số ấy chỉ khác 0 trong những ca hiếm tới mức vô dụng.

    Thứ PHÂN BIỆT ĐƯỢC là NỘI DUNG các gợi ý: `耳塞` được Taobao hoàn thiện thành
    "耳塞睡眠睡觉专用超级隔音" — nút bịt tai để ngủ, không phải tai nghe. Không con số nào nói
    được điều đó, còn sáu chuỗi thì nói ngay.

    Song song theo ĐỀ CỬ, tuần tự theo SÀN. Giữ đúng lập luận của bản cũ — năm lượt gọi vào một
    endpoint autocomplete là chuyện nó phục vụ suốt ngày — nhưng không dồn cả hai sàn cùng lúc,
    vì như vậy là mười lượt đồng thời và Taobao đã đo thấy `ConnectTimeout` khi bị hỏi dồn.

    Một lượt gọi hỏng chỉ làm cụm đó thiếu bằng chứng, không làm hỏng cả bảng.
    """
    from .providers import KEYWORD_PROVIDERS

    out: dict[str, dict[str, list[str]]] = {term: {} for term in terms}
    for source_id in _evidence_sources(ctx.country):
        provider = KEYWORD_PROVIDERS[source_id]

        async def ask(term: str) -> tuple[str, list[str]]:
            try:
                results = await provider.fetch_suggestions(term, ctx)
            except Exception:
                return term, []
            words = [(e.keyword or "").strip() for e in results if e.keyword]
            return term, words[:EVIDENCE_PER_SOURCE]

        for term, words in await asyncio.gather(*(ask(t) for t in terms)):
            if words:
                out[term][source_id] = words
    return out


_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["same", "subtype", "broader", "brand", "different", "misspelling"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["term", "verdict", "reason"],
            },
        }
    },
    "required": ["verdicts"],
}


def _verify_prompt(seed: str, country: str, evidence: dict[str, dict[str, list[str]]]) -> str:
    """
    Lượt gọi thứ hai: chấm lại các đề cử, lần này KÈM dữ liệu thật.

    KHÁC HẲN VIỆC BẢO MÔ HÌNH "CẨN THẬN HƠN" ở `_prompt`, và khác biệt ấy là toàn bộ lý do
    bước này tồn tại. Đã thử thêm cảnh báo vào lượt đề cử và nó phản tác dụng — xem ghi chú ở
    `_prompt`. Nguyên nhân: ở đó mô hình vẫn phải NHỚ LẠI, cảnh báo chỉ làm nó nhớ rụt rè hơn
    nên bỏ mất cả những cụm đúng.

    Ở đây nó không phải nhớ gì cả. Nó đọc "彩妆蛋 → 彩妆蛋收纳盒 / 彩妆蛋不吃粉超软" và kết luận
    đó không phải son môi. Đó là việc đọc hiểu, không phải việc truy hồi kiến thức — nên một
    model nhẹ cũng làm được, và làm nhanh.

    Đo 2026-08-12 trên 19 đề cử có thật của năm ngành hàng: 17/19 phán quyết đúng, mỗi lượt
    1,1–1,5 giây. Quan trọng hơn con số tổng: CẢ BỐN lỗi nguy hiểm đều bị bắt — `彩妆蛋` (mút
    tán nền, không phải son), `耳塞` (nút bịt tai, không phải tai nghe), `水杯` (cốc thường,
    không giữ nhiệt) và `牛子裤` (viết sai của 牛仔裤). Hai ca lệch còn lại là ranh giới thật
    (`唇膏` vừa là son màu vừa là son dưỡng), không phải lỗi.

    HAI SÀN CHỨ KHÔNG PHẢI MỘT, vì lỗi chính tả chỉ lộ ra khi chúng mâu thuẫn: Taobao hoàn
    thiện `牛子裤` bình thường (đủ người gõ sai để autocomplete học được), còn 1688 lặng lẽ đổi
    về `牛仔裤`. Một sàn thì không thấy gì.
    """
    blocks = []
    for term, by_source in evidence.items():
        lines = [f'\n"{term}"']
        if not by_source:
            lines.append("  (không sàn nào ở thị trường này có gợi ý cho cụm này)")
        for source_id, words in by_source.items():
            lines.append(f"  {source_id} hoàn thiện thành: {' / '.join(words)}")
        blocks.append("\n".join(lines))

    return (
        f'Người Việt muốn bán ngành hàng "{seed}" ở thị trường {country}. Một mô hình đã đề cử '
        f"các cách gọi dưới đây, KÈM dữ liệu thật: chính ô tìm kiếm của các sàn ở thị trường đó "
        f"hoàn thiện mỗi cụm thành những gì.\n\n"
        f"ĐỌC DỮ LIỆU ĐÓ để phán xét, đừng dựa vào trí nhớ. Cách một sàn hoàn thiện một cụm cho "
        f"biết người ở đó thật sự dùng cụm ấy cho mặt hàng nào.\n"
        f"{''.join(blocks)}\n\n"
        f"Với MỖI cụm, trả về:\n"
        f'- term: chép lại NGUYÊN VĂN\n'
        f'- verdict:\n'
        f'    same        đúng là "{seed}"\n'
        f"    subtype     một LOẠI CON hoặc kiểu dáng riêng của ngành hàng đó\n"
        f"    broader     danh mục RỘNG HƠN, bao trùm ngành hàng đó nhưng không riêng nó\n"
        f"    brand       tên một THƯƠNG HIỆU, không phải tên ngành hàng\n"
        f"    different   MẶT HÀNG KHÁC hẳn\n"
        f"    misspelling viết sai của một cụm khác. Dấu hiệu mạnh: một sàn hoàn thiện được "
        f"nhưng sàn kia lại tự đổi sang chữ khác\n"
        f"- reason: một câu TIẾNG VIỆT tối đa 12 chữ, DẪN RA chính bằng chứng ở trên. Không "
        f"nhận xét chung chung."
    )


async def _verify(
    seed: str, country: str, evidence: dict[str, dict[str, list[str]]]
) -> dict[str, tuple[str, str]]:
    """
    Chấm lại toàn bộ đề cử trong MỘT lượt gọi. Hỏng thì trả về rỗng, không ném lỗi.

    Cả bảng vào chung một lượt vì cùng lý do với `gloss.BATCH_SIZE`: phần hướng dẫn dài hơn
    phần dữ liệu, nên hỏi từng cụm một là trả tiền cho hướng dẫn năm lần.

    Hỏng thì bảng vẫn hiện, chỉ là mọi cụm mang `unknown` — bước này làm bảng ĐÁNG TIN HƠN chứ
    không phải điều kiện để bảng tồn tại.
    """
    from .gloss import call_gemini

    payload = {
        "contents": [{"parts": [{"text": _verify_prompt(seed, country, evidence)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _VERDICT_SCHEMA,
            # Đọc bằng chứng và phân loại là việc phải lặp lại được: cùng một bảng dữ liệu phải
            # cho cùng một phán quyết ở lượt sau. Khác `_prompt`, nơi cần phủ rộng nên để 0.3.
            "temperature": 0,
        },
    }
    try:
        data = await call_gemini(payload)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except Exception:
        return {}

    out: dict[str, tuple[str, str]] = {}
    for entry in parsed.get("verdicts", []):
        term = (entry.get("term") or "").strip()
        verdict = (entry.get("verdict") or "").strip()
        if term and verdict in VERDICT_ORDER:
            out[term] = (verdict, (entry.get("reason") or "").strip())
    return out


@dataclass
class _Proposal:
    term: str
    note: str


@dataclass
class _ProposalOutcome:
    items: list[_Proposal] = field(default_factory=list)
    error: str | None = None


async def _propose(seed: str, country: str) -> _ProposalOutcome:
    """Xin Gemini các cách gọi ứng viên. Chưa có bằng chứng nào ở bước này."""
    # Nhập tại chỗ để bài kiểm tra thay được `gloss.post_json` — cùng một đường mạng, và
    # nhập ở đầu file sẽ ghim vào tham chiếu cũ trước khi bài kiểm tra kịp thay.
    from .gloss import call_gemini

    payload = {
        "contents": [{"parts": [{"text": _prompt(seed, country)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
            # Khác `gloss.py` (temperature 0): ở đó cần lặp lại được, ở đây cần phủ rộng. Vẫn
            # để thấp vì bảng ứng viên nhảy múa giữa hai lần bấm cùng một nút thì người dùng
            # không còn cách nào đối chiếu hai lượt chạy với nhau.
            "temperature": 0.3,
        },
    }
    try:
        data = await call_gemini(payload)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except Exception as error:
        return _ProposalOutcome(error=str(error) or type(error).__name__)

    items: list[_Proposal] = []
    seen: set[str] = set()
    for entry in parsed.get("candidates", []):
        term = (entry.get("term") or "").strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            items.append(_Proposal(term=term, note=(entry.get("note") or "").strip()))
    return _ProposalOutcome(items=items[:MAX_CANDIDATES])


async def bridge_seed(seed: str, ctx: SearchContext) -> BridgeResult:
    """
    Đề cử các cách gọi ngành hàng ở thị trường đích, để người dùng chọn.

    KHÔNG ĐO GÌ CẢ, dù tên hàm nghe như có. Câu cũ ở đây viết "ĐO từng cách để biết cách nào có
    người gõ" và nó đã sai từ lúc bước Trends bị gỡ (xem docstring đầu file). Thứ duy nhất chạy
    sau phần đề cử là `_amazon_support`, mà nó chỉ bắt được con số 0 — xem ghi chú ở hàm đó.

    Không bao giờ ném lỗi. Mọi kết cục — chưa có khoá Gemini, Amazon từ chối, không cụm nào đề
    cử được — đều là một `BridgeResult` kèm `message` nói rõ chuyện gì, vì đây là một công cụ
    trợ giúp cạnh ô nhập liệu chứ không phải một bước bắt buộc của lượt tìm.
    """
    started_at = time.monotonic()
    country = ctx.country.upper()

    def elapsed() -> int:
        return round((time.monotonic() - started_at) * 1000)

    if language_for(country) == "vi":
        # Im lặng, giống `gloss_keywords`. Nhánh này gần như không tới được — giao diện giấu
        # hẳn nút "Tìm cách gọi bản địa" ở thị trường Việt Nam — nên câu giải thích ở đây chỉ
        # chờ để hiện ra trong đúng cái trường hợp mà nó không nói thêm được gì.
        return BridgeResult(seed=seed, country=country, took_ms=elapsed())
    if not GEMINI_API_KEY:
        return BridgeResult(
            seed=seed,
            country=country,
            message="Chưa cấu hình GEMINI_API_KEY nên chưa đề cử được cách gọi bản địa",
            took_ms=elapsed(),
        )

    proposed = await _propose(seed, country)
    if proposed.error:
        return BridgeResult(
            seed=seed, country=country, message=f"Không đề cử được: {proposed.error}", took_ms=elapsed()
        )
    if not proposed.items:
        return BridgeResult(
            seed=seed, country=country, message="Gemini không đề cử được cách gọi nào", took_ms=elapsed()
        )

    terms = [p.term for p in proposed.items]
    evidence = await _gather_evidence(terms, ctx)
    verdicts = await _verify(seed, country, evidence)

    def judge(term: str, samples: list[str]) -> tuple[str, str]:
        """
        Phán quyết của một cụm, nhưng KHÔNG BAO GIỜ chấm một cụm không có bằng chứng.

        Luật cứng ở đây chứ không phải một câu dặn trong prompt, vì đã đo thấy prompt không giữ
        được: ở thị trường Ấn Độ — nơi sổ đăng ký chưa có sàn nào — mô hình vẫn chấm `same` và
        `misspelling` cho từng cụm, kèm lý do "Không sàn nào có gợi ý cho cụm này". Tức là nó
        quay về ĐOÁN THEO TRÍ NHỚ, đúng thứ mà cả bước chấm này sinh ra để chặn, chỉ khác là
        lần này lời đoán được đóng dấu một huy hiệu trông như có căn cứ.

        Không bằng chứng thì `unknown`, và giao diện không vẽ huy hiệu nào. Nói "tôi chưa kiểm
        được" đúng hơn là nói một câu chắc nịch dựng trên không khí.
        """
        if not samples:
            return "unknown", ""
        return verdicts.get(term, ("unknown", ""))

    candidates = []
    for p in proposed.items:
        samples = [w for words in evidence.get(p.term, {}).values() for w in words]
        verdict, reason = judge(p.term, samples)
        candidates.append(
            SeedCandidate(
                term=p.term,
                note=p.note,
                verdict=verdict,  # type: ignore[arg-type]
                reason=reason,
                evidence=samples,
            )
        )

    # Xếp theo PHÁN QUYẾT trước, rồi mới tới thứ tự Gemini đưa ra.
    #
    # Đây là điểm khác bản cũ. Bản cũ chỉ đẩy các cụm "không sàn nào biết" xuống cuối, mà điều
    # kiện đó gần như không bao giờ đúng — mọi sàn đều trả về đủ số gợi ý cho cả những cụm bịa.
    # Nên trên thực tế thứ tự bảng chính là thứ tự Gemini đưa ra, tức là không có căn cứ nào.
    #
    # Nay `different` và `misspelling` xuống đáy, `same` lên đầu. Vẫn KHÔNG ẩn cụm nào: một
    # phán quyết là phán quyết của mô hình, và người dùng có thể biết điều mà nó không biết.
    order = {p.term: i for i, p in enumerate(proposed.items)}
    candidates.sort(key=lambda c: (VERDICT_ORDER.get(c.verdict, 3), order[c.term]))

    # "Chọn" là cụm ĐÚNG NGÀNH HÀNG đầu tiên, không còn là cụm đầu bảng của Gemini. Nếu không
    # cụm nào được chấm `same` thì rơi về cụm đầu bảng — có một điểm khởi đầu vẫn hơn không.
    #
    # Vẫn chỉ là ĐỀ CỬ. Người dùng mới là người biết mình định bán 夹克 hay 风衣, và phán quyết
    # ở đây trả lời câu "cụm này có phải ngành hàng đó không", không trả lời câu "bạn bán gì".
    chosen = next((c.term for c in candidates if c.verdict == "same"), None)
    if chosen is None and candidates:
        chosen = candidates[0].term

    return BridgeResult(
        seed=seed,
        country=country,
        candidates=candidates,
        chosen=chosen,
        took_ms=elapsed(),
    )
