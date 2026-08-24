"""
NGUỒN TỪ KHOÁ: TikTok search preview.

Lựa chọn endpoint là kết quả đo: `search/general/sug/` trả về danh sách rỗng;
`preview` mới là cái chạy được.

Đây là nguồn *gợi ý tìm kiếm* của TikTok, hoàn toàn tách biệt với nguồn quảng cáo TikTok
ở `lib/ads/platforms/tiktok.py`. Hai bên không dùng chung code, cũng không dùng chung
phiên — trùng tên nền tảng chỉ là trùng tên.

Giới hạn đã đo ngày 2026-07-28: search organic của TikTok trả về body rỗng cho người gọi
ẩn danh, nên không lấy được lượt xem. Chỉ có gợi ý từ khoá là dùng được.

ENDPOINT NÀY CHỌN THỊ TRƯỜNG THEO IP NGƯỜI GỌI, VÀ CHỈ THEO IP.

Không ép vùng được bằng bất cứ thứ gì ta tự khai. Đo 2026-08-06, đều KHÔNG đổi được kết quả:
tham số `region` / `priority_region`, header `Accept-Language`, cookie `store-country-code`,
cookie định tuyến `tt-target-idc` (bốn trung tâm dữ liệu), `X-Forwarded-For`. Đo tiếp
2026-08-14, cũng không đổi: referer theo đường dẫn locale `/th-TH/`, tham số `app_language`,
đường dẫn API mang tiền tố `/th-TH/` (không tồn tại — trả HTML), và cookie lấy từ trang
`/th-TH/`. `tt-target-idc` là cái gần nhất — nó đổi trung tâm dữ liệu thật — nhưng với từ gốc
`shoes` thì `useast2a` vẫn trả về "shoes ho chi minh city".

Nhưng ĐỔI IP THẬT thì xuyên qua, và đó là điều dùng được. Đo 2026-08-14 trên cùng một trình
duyệt, cùng lọ cookie, hai lượt cách nhau 100 giây, chỉ khác mỗi IP:

    IP Việt Nam          shoes · Shoes For Girl · shoes store · shoes cleaning
    IP Anh (OVH London)  shoes for men · shoes for women · shoes inspo · shoes for school 2026

Không một cụm nào trùng. Payload còn tự khai điều đó: lượt VN có kênh recall
`tiktok_index_global_local_service_geointent_row_query` và `tiktok_orion_sug_ecom_pv`, lượt GB
không có kênh nào trong hai cái ấy.

Đáng chú ý là IP đó thuộc dải DATACENTER (OVH, AS16276) chứ không phải IP dân cư — nên nguồn
này không cần proxy dân cư đắt tiền, một proxy datacenter rẻ mỗi nước là đủ. Xem `PROXY_BY_MARKET`.

Đường Creative Center thì đã dò và đóng: bề mặt Keyword Insights đã bị gỡ khỏi Creative
Center (chỉ còn Top Ads / Trends / Creative Tools), và thứ còn lại là bảng hashtag xu hướng
nội dung — `#liveiseasy` đứng số 1 ở CẢ Việt Nam lẫn Brazil, tức chiến dịch toàn cầu do
TikTok tự đẩy, không phải nhu cầu bản địa.
"""

from __future__ import annotations

import time
from urllib.parse import quote

from lib.core.config import env_map, env_string
from lib.core.http import get_json

from ..market import language_matches_market
from ..provider import KeywordProvider, Suggestion
from ..types import SearchContext

#: Thị trường mà máy chủ này đi ra Internet khi KHÔNG qua proxy.
#:
#: Là biến môi trường chứ không phải hằng số vì nó là thuộc tính của NƠI TRIỂN KHAI, không phải
#: của TikTok: dựng lại hệ thống này trên một máy chủ ở Thái Lan thì cùng đoạn code sẽ phục vụ
#: đúng thị trường Thái, và lúc đó `markets = ["VN"]` viết cứng sẽ thành một lời nói dối.
HOME_MARKET = env_string("TIKTOK_HOME_MARKET", "VN").upper()

def _load_proxies() -> dict[str, list[str]]:
    """
    Đọc `TIKTOK_PROXY_<CC>` và `TIKTOK_PROXY_<CC>_2`, `_3`… thành `{"GB": [url, url, url]}`.

    Nhiều proxy cho một nước là chuyện thường: gói rẻ nhất của các nhà cung cấp thường bán
    theo lô mười IP rải khắp nơi, nên một nước có ba cái là bình thường.

    Đánh số bằng HẬU TỐ chứ không nhét nhiều URL vào một biến ngăn bằng dấu phẩy, vì mật khẩu
    proxy do nhà cung cấp sinh ra hoàn toàn có thể chứa dấu phẩy — lúc đó bản ngăn-bằng-phẩy
    tách sai và hỏng theo kiểu rất khó truy.
    """
    grouped: dict[str, list[str]] = {}
    for key, url in sorted(env_map("TIKTOK_PROXY_").items()):
        grouped.setdefault(key.split("_")[0], []).append(url)
    return grouped


#: Proxy cho từng thị trường: `TIKTOK_PROXY_GB=http://user:pass@host:port` → `{"GB": [...]}`.
#:
#: Khai một dòng là mở thêm một thị trường; xoá dòng đó là đóng lại. Không có dòng nào thì
#: nguồn chạy y như trước khi có phần này — đi thẳng, phục vụ đúng `HOME_MARKET`.
#:
#: PHẢI KIỂM PROXY THẬT SỰ Ở NƯỚC NÓ NHẬN. Một proxy khai là Thái nhưng đặt ở Việt Nam sẽ
#: không báo lỗi gì cả: nó trả về dữ liệu Việt Nam, và dữ liệu đó được xếp hạng, dán nhãn
#: "Thái Lan" rồi hiện ra như thật. Chạy `python -m scripts.probe.proxy_audit <file>` để đối
#: chiếu — script đó so cả IP đi ra lẫn kết quả TikTok của từng proxy.
PROXY_BY_MARKET = _load_proxies()

#: Vị trí bắt đầu vòng xoay của mỗi nước, để 25 lượt gọi của một lần tìm không dồn hết vào
#: một IP. Chỉ là con trỏ chia tải, không phải trạng thái cần bền — mất khi khởi động lại
#: cũng không sao.
_rotation: dict[str, int] = {}

#: Nghỉ chơi một proxy trong bao lâu sau khi nó hỏng.
#:
#: Có lớp này vì đo thấy hai proxy chết tốn 9,9 giây chỉ để phát hiện ra chúng chết — hết thời
#: gian kết nối, tuần tự. Không nhớ lại thì mỗi lượt trong hai mươi lăm lượt gọi đều trả lại
#: cái giá đó khi vòng xoay chạm phải IP chết, cộng thêm gần một phút cho mỗi lần tìm. Nguồn
#: vẫn chạy đúng, chỉ chậm — đúng kiểu hỏng không ai nghĩ là hỏng.
#:
#: Năm phút chứ không phải vĩnh viễn: proxy rẻ chết rồi sống lại là chuyện thường, và loại
#: hẳn một IP vì một lần hỏng mạng thoáng qua sẽ dần bào mòn cả vòng xoay.
PROXY_COOLDOWN_MS = 5 * 60 * 1000

#: Proxy → mốc thời gian được dùng lại. Cùng cách làm với pool phiên Google ở `lib/core/auth.py`.
_cooldown: dict[str, float] = {}


def _proxy_ring(country: str) -> list[str]:
    """
    Danh sách proxy của một nước, đã bỏ cái đang bị phạt và xoay một nấc mỗi lần gọi.

    Cả vòng đang bị phạt thì trả về NGUYÊN vòng chứ không trả rỗng: hết hàng còn hơn không
    thử, và ném lỗi "chưa có proxy cho GB" khi thật ra có ba cái vừa hỏng mạng là báo sai
    nguyên nhân.
    """
    pool = PROXY_BY_MARKET.get(country, [])
    if not pool:
        return []
    now = time.time() * 1000
    ring = [proxy for proxy in pool if _cooldown.get(proxy, 0.0) <= now] or list(pool)
    if len(ring) < 2:
        return ring
    start = _rotation.get(country, 0) % len(ring)
    _rotation[country] = start + 1
    return ring[start:] + ring[:start]


class TikTok(KeywordProvider):
    id = "tiktok"
    label = "TikTok"
    #: Không phải điểm liên quan như Shopee, mà là số kênh đã gọi cụm này ra — xem `_recall_breadth`.
    has_native_score = True
    native_score_note = "{label} gọi cụm này ra qua {value} kênh"
    #: Đúng những thị trường có đường ra tới nơi: thị trường nhà, cộng mỗi nước có proxy.
    #:
    #: Trước đây để `None` (mọi thị trường). Điều đó biến một giới hạn thành một lỗi: chọn Đài
    #: Loan thì bảng hiện gợi ý tiếng Nhật, chọn Brazil thì hiện tiếng Tây Ban Nha của Peru —
    #: đều được xếp hạng và trình bày như từ khoá của thị trường người dùng đã chọn. Danh sách
    #: nay nới ra theo proxy, nhưng nới đúng bằng số đường ra CÓ THẬT chứ không nới thành `None`:
    #: cái bẫy cũ quay lại ngay lần đầu có người chọn một nước không có proxy.
    markets = sorted({HOME_MARKET, *PROXY_BY_MARKET})
    #: Đổi nước CÓ đổi kết quả — nhưng chỉ khi nước đó có proxy, nên cờ này bám theo cấu hình.
    #:
    #: Không viết cứng `True`: chưa khai proxy nào thì ô Quốc gia thật sự không đổi được gì, và
    #: nói ngược lại là để giao diện giải thích sai cho người dùng.
    geo_targeted = bool(PROXY_BY_MARKET)

    async def fetch_suggestions(self, term: str, ctx: SearchContext) -> list[Suggestion]:
        country = ctx.country.upper()
        ring = _proxy_ring(country)
        if not ring:
            # `markets` lẽ ra đã chặn từ trước, nên nhánh này là lưới cuối. Ném lỗi thay vì
            # lặng lẽ đi thẳng: đi thẳng sẽ trả về dữ liệu thị trường nhà và dán nhãn nước
            # người dùng chọn — đúng kiểu hỏng im lặng mà việc thu hẹp `markets` sinh ra để diệt.
            if country != HOME_MARKET:
                raise RuntimeError(
                    f"chưa có proxy cho {country}; khai TIKTOK_PROXY_{country} "
                    "hoặc bỏ chọn nguồn này"
                )
            ring = [""]  # chuỗi rỗng = đi thẳng, đúng client mà các nguồn khác đang dùng

        encoded = quote(term, safe="")
        url = f"https://www.tiktok.com/api/search/general/preview/?keyword={encoded}"
        headers = {"referer": f"https://www.tiktok.com/search?q={encoded}"}

        # Hỏng thì sang proxy kế tiếp của CÙNG nước, và chỉ ném lỗi khi cả vòng đều hỏng.
        # Cần thiết vì `expand_with_provider` dừng hẳn ở lượt lỗi đầu tiên: không có lớp này
        # thì một IP chết cắt ngang cả lượt tìm ở lời gọi thứ hai trên hai mươi lăm, trong khi
        # sáu IP khác của cùng nước vẫn đang sống.
        last_error: Exception | None = None
        for proxy in ring:
            try:
                payload = await get_json(url, headers, proxy=proxy or None)
                _cooldown.pop(proxy, None)
                break
            except Exception as error:
                last_error = error
                if proxy:
                    _cooldown[proxy] = time.time() * 1000 + PROXY_COOLDOWN_MS
        else:
            raise RuntimeError(
                f"cả {len(ring)} proxy của {country} đều hỏng; lỗi cuối: {last_error}"
            )

        out: list[Suggestion] = []
        for item in (payload or {}).get("sug_list") or []:
            keyword = item.get("content")
            if not keyword:
                continue
            extra = item.get("extra_info") or {}

            # Lưới an toàn thứ hai, sau `markets`. Cần cả hai vì chúng chặn hai đường khác nhau:
            # `markets` chặn người dùng chọn nhầm thị trường, còn phép kiểm này chặn chính
            # TikTok trả về cụm lạc ngôn ngữ ngay trong thị trường nhà.
            if not language_matches_market(extra.get("lang") or "", ctx.country):
                continue

            out.append(Suggestion(keyword=keyword, score=_recall_breadth(extra)))
        return out


def _recall_breadth(extra: dict) -> float | None:
    """
    Số kênh mà TikTok đã dùng để gọi cụm này ra — điểm gốc duy nhất nguồn này có.

    Thay cho việc xếp hạng thuần theo vị trí, và lý do là kết quả đo ngày 2026-08-06 trên sáu
    lượt gọi liên tiếp: số kênh recall ỔN ĐỊNH TUYỆT ĐỐI (độ lệch chuẩn 0,00 ở mọi cụm) trong
    khi vị trí thì dao động — phần đuôi danh sách xoay vòng, độ lệch tới 0,40.

    Quan trọng hơn, hai tín hiệu BẤT ĐỒNG: cùng đứng vị trí 7, `váy dài đi biển` được gọi ra
    qua 10 kênh còn `Váy dài đi biển` chỉ qua 2. Vị trí không phân biệt nổi hai cụm đó, nên
    xếp hạng theo vị trí là vứt đi đúng phần thông tin có ích.

    NÓI CHO ĐÚNG BẢN CHẤT: đây là ĐỘ RỘNG KÊNH GỌI LẠI, không phải lượng tìm kiếm. Một cụm
    được mười kênh nêu ra thì chắc chắn là truy vấn có thật hơn một cụm chỉ có hai kênh, nhưng
    nó không trả lời được câu "bao nhiêu người tìm". Các kênh quan sát được gồm
    `tiktok_index_active_7d_query` (có người tìm trong 7 ngày), `darwin_session_qq_14d_recall`
    (cửa sổ 14 ngày) và `tiktok_orion_sug_ecom_pv` (có lượt xem phía thương mại điện tử).
    """
    markers = [part for part in (extra.get("recall_reason") or "").split("|") if part]
    return float(len(markers)) if markers else None


tiktok = TikTok()
