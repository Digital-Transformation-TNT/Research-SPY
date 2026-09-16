"""
POOL PROXY MIỄN PHÍ, TỰ LÀM MỚI — hiện chỉ phục vụ nguồn từ khoá TikTok.

VÌ SAO KHÔNG KHAI VÀO `.env` NHƯ PROXY TRẢ TIỀN. Proxy miễn phí chết theo phút chứ không theo
tháng, và đây là phép đo chứ không phải cảm tính: 16/09/2026 lấy 14 proxy PH vừa kết nối được,
chạy LẠI ĐÚNG BÀI TEST ĐÓ sau 5 phút thì còn 1. `.env` đọc đúng một lần lúc khởi động, nên một
dòng khai tay ở đó chết trước cả lần tìm thứ hai. Cái khai bằng tay được chỉ là BẬT hay TẮT —
`TIKTOK_FREE_PROXY=PH`; còn địa chỉ thì phải tự dò, liên tục, và tự vứt cái đã chết.

HAI PHA KIỂM, rộng trước hẹp sau. Thứ tự này KHÔNG phải để cho gọn, nó là điều kiện để pool có
gì cả — xem `lam_moi` để biết bản xếp sai thứ tự đã cho ra 0 proxy ba lượt liền ra sao.
  Pha 1 — còn sống VÀ đúng nước, một lời gọi `ipwho.is` qua proxy, chạy cho TẤT CẢ ứng viên.
     Phần "đúng nước" không bỏ được: danh sách miễn phí gắn nhãn nước rất hay sai, và
     `tiktok.py` đã cảnh báo rằng proxy sai nước KHÔNG báo lỗi gì — nó trả dữ liệu nước khác,
     rồi dữ liệu đó đi thẳng vào bảng xếp hạng dưới nhãn nước người dùng đã chọn.
  Pha 2 — TikTok qua proxy đó có trả gợi ý thật không (`sug_list` không rỗng), chỉ chạy trên
     nhóm vừa sống và chạy NGAY. Đo 16/09/2026 qua 4 vòng: 18 proxy sống thì 5 qua được (28%).

ĐIỀU KHÔNG KIỂM ĐƯỢC, và phải nói thẳng: chủ một proxy miễn phí hoàn toàn có thể trả JSON TỰ CHẾ.
Khi đó bảng từ khoá "Philippines" trông rất thật nhưng do người lạ viết ra. Bước 3 chặn được proxy
CHẾT, không chặn được proxy NÓI DỐI. Lượt gọi này không mang cookie hay phiên đăng nhập nào nên
không mất gì về bảo mật; cái mất là ĐỘ TIN của dữ liệu.

DÒ NỀN LIÊN TỤC, không bao giờ chặn lượt tìm của người dùng. `_vong_do_nen` chạy suốt vòng đời
tiến trình, khoảng ba phút một lượt; lượt tìm chỉ đọc pool đang có. Đây không phải tối ưu hoá mà
là điều kiện cần: proxy sống tính bằng phút, nên "dò khi có người hỏi" thì luôn luôn muộn.

MỨC PHỤC VỤ ĐO ĐƯỢC, để ai đọc file này biết trước mình mua cái gì: chạy vòng dò nền 25 phút
ngày 16/09/2026 với PH, lấy mẫu mỗi 20 giây — pool có proxy 77% số mẫu, nhiều nhất 3 cái cùng
lúc, 6/7 vòng tìm được ít nhất một cái. Nghĩa là khoảng một phần tư số lượt tìm sẽ gặp pool
rỗng và nhận thông báo thử lại. Đó là trần của proxy miễn phí, không phải lỗi cấu hình.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from urllib.parse import quote

import httpx

from lib.core.config import config, env_string
from lib.core.store import DiskStore

#: Danh sách công khai, mỗi nguồn một file theo NƯỚC. Ba nguồn chứ không một, vì một nguồn chết
#: (đường dẫn đổi, 404) không được phép làm cả lượt làm mới thành rỗng — và điều đó đã xảy ra
#: thật. Đo 16/09/2026 với PH: proxifly 97 IP, geonode 46, proxyscrape 16; gộp lại 137 IP.
#:
#: ĐÃ QUÉT THỬ 12 NGUỒN, chín cái còn lại không dùng được, nên đừng mất công thêm lại:
#:   • proxy-list.download 502, monosans và mmpx12 trả 404 (đường dẫn đã bỏ), openproxylist có
#:     file nhưng không IP nào ở PH;
#:   • TheSpeedX, proxyspace, hookzof, sunny9577, clarketm cộng lại 10.811 IP nhưng KHÔNG GẮN
#:     NHÃN NƯỚC. Lọc ra PH phải tra địa lý từng IP; bản miễn phí của các dịch vụ tra cho khoảng
#:     45 lượt/phút, tức hơn bốn tiếng — trong khi proxy chết sau vài phút. Nhiều IP ở đây không
#:     có nghĩa là nhiều proxy dùng được.
NGUON = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies&country={cc_thuong}&protocol=http&proxy_format=ipport&format=text",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/countries/{cc}/data.txt",
    # Trả JSON chứ không phải danh sách dòng — `_lay_ung_vien` tự nhận ra và đọc bằng nhánh riêng.
    "https://proxylist.geonode.com/api/proxy-list"
    "?limit=500&page=1&sort_by=lastChecked&sort_type=desc&country={cc}&protocols=http",
)


def _nuoc_bat() -> list[str]:
    """Nước nào bật pool miễn phí: `TIKTOK_FREE_PROXY=PH` hoặc `PH,ID`. Rỗng = tắt hẳn."""
    raw = env_string("TIKTOK_FREE_PROXY", "")
    return [x.strip().upper() for x in raw.split(",") if x.strip()]


NUOC_BAT = _nuoc_bat()

#: Kiểm tối đa ngần này ứng viên mỗi lượt.
#:
#: Rộng hơn tổng nguồn cung PH đang có (đo 16/09/2026: 141–147 IP từ cả ba nguồn), và đó là chủ
#: ý — trần cũ 120 CẮT MẤT hai ba chục ứng viên cuối trong khi tỉ lệ sống chỉ ~4%, tức là vứt đi
#: đúng cái thứ mình đang thiếu. Pha 1 chạy 30 luồng nên thêm vài chục ứng viên gần như không
#: thêm giây nào; cái đắt là pha 2, mà pha đó chỉ chạm vào nhóm đã sống.
TOI_DA_UNG_VIEN = 200

#: Dò KẾT NỐI mấy cái một lúc. Cao được vì lượt này rẻ và không đụng hạn mức của ai: mỗi ứng
#: viên là một lời gọi đi qua chính nó. Đo 16/09/2026: 141 ứng viên, 30 luồng, hết 106 giây.
SONG_SONG_DO = 30

#: Kiểm TIKTOK mấy cái một lúc. Thấp hơn hẳn vì lượt này đắt (tới 25 giây) và chỉ chạy trên nhóm
#: đã sống — đo được 2–6 cái mỗi vòng, nên 8 luồng là đã chạy hết cùng lúc.
SONG_SONG_TT = 8

#: Pool tụt dưới mức này thì châm một lượt làm mới nền. HAI chứ không phải một: vòng xoay của
#: `tiktok.py` chỉ cứu được khi CÓ cái thứ hai để nhảy sang.
TOI_THIEU = 2

#: Đủ ngần này thì dừng kiểm, khỏi đốt thời gian và hạn mức.
DU_DUNG = 6

#: Khoảng cách tối thiểu giữa hai lượt làm mới của cùng một nước.
CACH_LAM_MOI_MS = 5 * 60 * 1000

#: Proxy sống bao lâu trong kho đĩa.
#:
#: SÁU PHÚT, và con số này là kết quả đo chứ không phải ước lượng: 16/09/2026 lấy 14 proxy PH vừa
#: kết nối được, chạy LẠI ĐÚNG BÀI TEST ĐÓ sau 5 phút thì còn 1. Bản đầu để 30 phút — tức là kho
#: đĩa sẽ vui vẻ đưa ra một proxy đã chết từ 25 phút trước, và người dùng lĩnh trọn một lượt tìm
#: hỏng. Thà pool rỗng và báo thẳng còn hơn pool đầy rác.
TTL_MS = 6 * 60 * 1000

#: Nghỉ bao lâu giữa hai vòng dò nền. Một vòng đã mất ~2,5 phút, nên đây là phần nghỉ THÊM.
#:
#: NGẮN, vì cái quyết định trải nghiệm không phải vòng trúng mà là vòng HỤT. Đo 25 phút ngày
#: 16/09/2026: 6/7 vòng tìm được proxy, và toàn bộ 23% thời gian pool rỗng đến từ đúng một vòng
#: hụt — pool cạn rồi phải chờ trọn một chu kỳ nữa. Rút chỗ nghỉ này là rút thẳng thời gian
#: người dùng phải chờ sau mỗi lần xui.
CHU_KY_NEN_S = 15.0

#: Hạn chờ khi kiểm. RỘNG TAY LÀ CỐ Ý, và đây là chỗ bản đầu tự bắn vào chân mình: proxy PH duy
#: nhất chạy được sáng 16/09/2026 mất 19,8 giây cho lượt gọi TikTok, trong khi hạn đặt 15 giây —
#: bộ kiểm loại đúng cái proxy dùng được, rồi báo "không tìm thấy cái nào". Proxy miễn phí vốn
#: chậm; đo tốc độ ở đây bằng thước của proxy trả tiền là tự làm pool rỗng.
CHO_KET_NOI_S = 12.0
CHO_TIKTOK_S = 25.0

#: Lượt tìm chịu chờ pool bao lâu khi pool đang rỗng. Xem `cho_co_proxy`.
#:
#: 75 giây, chọn theo nhịp vòng dò (~2,5 phút) chứ không theo cảm giác: chờ trọn một vòng thì
#: quá lâu cho một request web, còn không chờ gì thì vứt đi lượt dò đang chạy dở. Bảy mươi lăm
#: giây phủ được phần lớn quãng còn lại của một vòng đang chạy.
CHO_POOL_S = 75.0

log = logging.getLogger(__name__)

_kho = DiskStore("proxy-free")
_pool: dict[str, list[str]] = {}
_lan_lam_moi: dict[str, float] = {}
_dang_chay: dict[str, asyncio.Task] = {}


def _nguon_cho(nuoc: str) -> list[str]:
    return [u.format(cc=nuoc.upper(), cc_thuong=nuoc.lower()) for u in NGUON]


def _doc_dong(dong: str, nuoc: str) -> str | None:
    """Một dòng của danh sách → `ip:port`, hoặc None nếu không dùng được / không thuộc nước này."""
    dong = dong.strip()
    if not dong or dong.startswith("#"):
        return None
    # monosans ghi kèm nước: `ip:port|PH|...`. Lọc ngay ở đây cho khỏi kiểm cả thế giới.
    if "|" in dong:
        phan = dong.split("|")
        if len(phan) < 2 or phan[1].strip().upper() != nuoc.upper():
            return None
        dong = phan[0]
    # CHỈ NHẬN HTTP. proxifly trộn cả `socks5://`, `socks4://`, `https://` trong cùng một file
    # (đo 16/09/2026 với PH: 97 http, 14 socks5, 5 https, 1 socks4). Bản đầu CẮT tiền tố rồi coi
    # tất cả là HTTP — mà SOCKS không nói được giao thức HTTP proxy, nên chúng chắc chắn trượt ở
    # bước kết nối và chỉ tổ đốt hạn mức kiểm. `https://` ở đây nghĩa là proxy đòi TLS ở chặng
    # tới nó; `httpx.AsyncClient(proxy=...)` của ta dựng đường theo `http://`, nên cũng bỏ.
    if "://" in dong:
        giao_thuc, _, phan_con = dong.partition("://")
        if giao_thuc.lower() != "http":
            return None
        dong = phan_con
    dong = dong.strip()
    if dong.count(":") != 1:
        return None
    host, _, cong = dong.partition(":")
    return dong if cong.isdigit() and host.replace(".", "").isdigit() else None


def _doc_than(than: str, nuoc: str) -> list[str]:
    """Thân phản hồi của một nguồn → danh sách `ip:port`. Tự nhận JSON hay danh sách dòng."""
    if than.lstrip().startswith("{"):
        try:
            data = (json.loads(than) or {}).get("data") or []
        except ValueError:
            return []
        return [f"{it['ip']}:{it['port']}" for it in data if it.get("ip") and it.get("port")]
    return [x for x in (_doc_dong(d, nuoc) for d in than.splitlines()) if x]


async def _lay_ung_vien(nuoc: str) -> list[str]:
    ra: list[str] = []
    thay: set[str] = set()
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        for url in _nguon_cho(nuoc):
            try:
                r = await client.get(url)
                r.raise_for_status()
            except Exception:
                continue            # một nguồn hỏng không được làm hỏng cả lượt
            for ip_cong in _doc_than(r.text, nuoc):
                if ip_cong not in thay:
                    thay.add(ip_cong)
                    ra.append(ip_cong)
    return ra[:TOI_DA_UNG_VIEN]


async def _do_song(ip_cong: str, nuoc: str, sem: asyncio.Semaphore) -> str | None:
    """
    Bước 1+2 GỘP LÀM MỘT: còn sống VÀ đi ra đúng nước. Trả `ip:port` nếu đạt.

    Gộp được vì `ipwho.is` trả cả IP lẫn mã nước trong một lời gọi — nên chỗ này nay tốn một
    request thay vì hai, và quan trọng hơn là BỎ ĐƯỢC `ip-api.com`: nguồn đó chỉ phục vụ qua
    `http://` ở bản miễn phí và giới hạn 45 lượt/phút, hai thứ đều cản việc dò nền liên tục.
    """
    async with sem:
        try:
            async with httpx.AsyncClient(
                proxy=f"http://{ip_cong}", timeout=CHO_KET_NOI_S, follow_redirects=True
            ) as c:
                j = (await c.get("https://ipwho.is/")).json() or {}
        except Exception:
            return None
    return ip_cong if j.get("success") and j.get("country_code") == nuoc.upper() else None


async def _do_tiktok(ip_cong: str, sem: asyncio.Semaphore) -> str | None:
    """
    Pha 2: TikTok qua proxy này có trả gợi ý THẬT không. Trả URL proxy nếu đạt.

    GỌI ĐÚNG NHƯ `providers/tiktok.py` SẼ GỌI, tới từng header. Bản đầu tự dựng lấy lời gọi và
    quên `user-agent`; TikTok đáp lại HTTP 200 với `sug_list` rỗng — không lỗi, không mã lạ, chỉ
    là bảng trắng. Hậu quả: bộ kiểm loại sạch proxy tốt rồi báo "0 dùng được", đúng kiểu hỏng
    im lặng. Một bộ kiểm gọi khác cái nó bảo vệ thì không kiểm gì cả.

    Header lấy lại từ `lib/core/http.get_json` thay vì gọi thẳng hàm đó, vì `get_client` giữ
    một client sống mãi cho MỖI proxy — mà dò nền thì nếm hàng trăm proxy chết mỗi ngày.
    """
    duong = f"http://{ip_cong}"
    kw = quote("shoes", safe="")
    dau = {
        "user-agent": config.user_agent,
        "accept": "application/json, text/plain, */*",
        "referer": f"https://www.tiktok.com/search?q={kw}",
    }
    async with sem:
        try:
            async with httpx.AsyncClient(
                proxy=duong, timeout=CHO_TIKTOK_S, follow_redirects=True
            ) as c:
                r = await c.get(
                    f"https://www.tiktok.com/api/search/general/preview/?keyword={kw}",
                    headers=dau,
                )
            return duong if ((r.json() or {}).get("sug_list") or []) else None
        except Exception:
            return None


async def lam_moi(nuoc: str) -> list[str]:
    """
    Lấy danh sách mới, kiểm, thay pool của nước đó. Trả về pool sau khi làm mới.

    HAI PHA, RỘNG TRƯỚC HẸP SAU — và đây chính là chỗ bản đầu làm sai, theo cách không lộ ra:
    nó chạy cả ba bước trên TỪNG ứng viên theo lô 10, nên bước TikTok của lô sau xảy ra hàng
    PHÚT sau lượt dò của lô đầu. Với proxy miễn phí, hàng phút là quá muộn — đo 16/09/2026:
    14 proxy vừa kết nối được, 5 phút sau chỉ còn 1. Bản đầu vì thế báo "0 proxy dùng được"
    ba lượt liền, và kết luận sai là TikTok chặn.

    Tách đôi thì lượt dò rộng chạy MỘT LẦN cho cả trăm ứng viên (30 luồng, ~106 giây), rồi
    bước TikTok đắt tiền nổ NGAY trên nhóm vừa sống. Đo lại theo hình dạng này, 4 vòng:
    18 proxy sống → 5 qua được TikTok (28%), 3/4 vòng có ít nhất một cái dùng được.
    """
    nuoc = nuoc.upper()
    _lan_lam_moi[nuoc] = time.time() * 1000
    ung_vien = await _lay_ung_vien(nuoc)
    # Cái ĐANG SỐNG kiểm trước: rẻ hơn, và giữ pool ổn định giữa hai lượt làm mới thay vì thay
    # sạch bằng một lứa lạ mỗi lần.
    cu = [p.removeprefix("http://") for p in pool(nuoc)]
    ung_vien = cu + [x for x in ung_vien if x not in cu]

    sem_do = asyncio.Semaphore(SONG_SONG_DO)
    song = [x for x in await asyncio.gather(*(_do_song(x, nuoc, sem_do) for x in ung_vien)) if x]

    # CÔNG BỐ NGAY từng cái vừa đạt, không đợi cả pha 2 xong. Có người đang CHỜ ở
    # `cho_co_proxy` — bắt họ đợi thêm hai chục giây cho những lượt kiểm chẳng liên quan là
    # phí đúng thứ đắt nhất ở đây: quãng đời còn lại của proxy.
    sem_tt = asyncio.Semaphore(SONG_SONG_TT)
    tot: list[str] = []
    for xong in asyncio.as_completed([_do_tiktok(x, sem_tt) for x in song[:DU_DUNG * 3]]):
        if (kq := await xong) :
            tot.append(kq)
            _pool[nuoc] = [kq] + [p for p in _pool.get(nuoc, []) if p != kq]

    log.info("proxy free %s: %d ung vien -> %d song -> %d dung duoc", nuoc, len(ung_vien), len(song), len(tot))
    _pool[nuoc] = tot
    _kho.set(nuoc, tot, TTL_MS)
    return tot


async def cho_co_proxy(nuoc: str, han_s: float = CHO_POOL_S) -> list[str]:
    """
    Chờ tới khi pool có proxy, tối đa `han_s` giây. Trả pool (có thể vẫn rỗng nếu hết hạn).

    VÌ SAO ĐÁNG CHỜ chứ không báo lỗi ngay. Vòng dò nền chạy ~2,5 phút một lượt, nên lúc pool
    rỗng thì gần như luôn có một lượt ĐANG chạy dở — báo lỗi ngay là vứt đi cơ hội đó. Đo
    16/09/2026 ngay trên máy chủ: vòng 10:56 tìm được 3 proxy, vòng 10:59 tìm được 0 và xoá
    sạch pool; một lượt tìm rơi vào đúng khe 11:00 nhận lỗi, dù ba phút trước hệ thống có hàng.

    Chờ được vì `max_terms_for` đã ghìm nước dùng pool miễn phí xuống MỘT lượt gọi: tổng thời
    gian một lượt tìm PH vẫn là chờ-rồi-gọi-một-lần, chứ không phải chờ rồi gọi mười hai lần.
    """
    nuoc = nuoc.upper()
    if (co := pool(nuoc)):
        return co
    het = time.time() + han_s
    while time.time() < het:
        await asyncio.sleep(2.0)
        if (co := pool(nuoc)):
            log.info("proxy free %s: cho %.0fs thi co proxy", nuoc, han_s - (het - time.time()))
            return co
    return []


def pool(nuoc: str) -> list[str]:
    """Pool đang có của một nước. Đọc kho đĩa ở lần gọi đầu để không mất sau mỗi lần restart."""
    nuoc = nuoc.upper()
    if nuoc not in _pool:
        _pool[nuoc] = list(_kho.get(nuoc) or [])
    return list(_pool[nuoc])


def bo(nuoc: str, proxy: str) -> None:
    """Bỏ hẳn một proxy vừa hỏng. `tiktok.py` gọi khi lượt gọi qua nó thất bại."""
    nuoc = nuoc.upper()
    con = [p for p in pool(nuoc) if p != proxy]
    _pool[nuoc] = con
    _kho.set(nuoc, con, TTL_MS)


def cham_lam_moi(nuoc: str) -> None:
    """
    Châm một lượt làm mới CHẠY NỀN nếu pool mỏng và chưa có lượt nào đang chạy.

    Không `await`: lượt tìm của người dùng không được phép chờ một hai phút kiểm proxy. Không có
    vòng sự kiện (gọi từ script đồng bộ) thì im lặng bỏ qua — nơi gọi tự chạy `lam_moi` được.
    """
    nuoc = nuoc.upper()
    if len(pool(nuoc)) >= TOI_THIEU:
        return
    if (task := _dang_chay.get(nuoc)) and not task.done():
        return
    if time.time() * 1000 - _lan_lam_moi.get(nuoc, 0.0) < CACH_LAM_MOI_MS:
        return
    try:
        _dang_chay[nuoc] = asyncio.get_running_loop().create_task(lam_moi(nuoc))
    except RuntimeError:
        pass


_vong_nen: asyncio.Task | None = None


async def _vong_do_nen() -> None:
    """
    Dò lại không ngừng, mỗi nước một lượt, cho tới khi tiến trình tắt.

    VÌ SAO PHẢI DÒ NỀN chứ không chỉ dò khi có người tìm. Proxy miễn phí sống tính bằng phút,
    nên "dò khi cần" luôn luôn muộn: người dùng bấm tìm, pool rỗng, họ chờ hai phút dò rồi
    vẫn có thể ra tay trắng. Dò nền đổi câu hỏi từ "lúc này có dò ra proxy không" thành "lúc
    bạn bấm tìm, pool có đang giữ cái nào còn hạn không" — và câu sau trả lời được bằng cách
    dò liên tục, vì tỉ lệ mỗi vòng đo được là 3/4 vòng có ít nhất một proxy dùng được.

    Không bao giờ để một lỗi làm chết vòng: một lượt hỏng thì ngủ rồi chạy tiếp. Vòng này mà
    chết lặng lẽ thì pool cạn dần và triệu chứng hiện ra ở tận nguồn TikTok, rất khó lần ra.
    """
    log.info("proxy free: bat dau vong do nen cho %s", ", ".join(NUOC_BAT))
    while True:
        for nuoc in NUOC_BAT:
            try:
                await lam_moi(nuoc)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("proxy free %s: vong do hong: %s", nuoc, e)
        await asyncio.sleep(CHU_KY_NEN_S)


def bat_dau_nen() -> None:
    """
    Bật vòng dò nền. `app/main.py` gọi trong lifespan; không khai `TIKTOK_FREE_PROXY` thì im.

    Gọi lại nhiều lần cũng không sao — lượt thứ hai thấy vòng còn chạy thì bỏ qua.
    """
    global _vong_nen
    if not NUOC_BAT:
        return
    if _vong_nen and not _vong_nen.done():
        return
    try:
        _vong_nen = asyncio.get_running_loop().create_task(_vong_do_nen())
    except RuntimeError:
        pass


async def dung_nen() -> None:
    """Dừng vòng dò nền lúc tắt máy, để không bỏ lại một task đang chờ mạng."""
    global _vong_nen
    if not _vong_nen or _vong_nen.done():
        return
    _vong_nen.cancel()
    try:
        await _vong_nen
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _vong_nen = None
