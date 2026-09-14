# Kalodata Scraper — extension độc lập

Cào **sản phẩm** và **video** TikTok từ Kalodata theo region, bằng chính phiên đăng nhập của bạn.

Tách hẳn khỏi `extension/` (Research-SPY Fetcher): riêng manifest, riêng quyền, riêng tab.
Nó chỉ xin đúng hai host — `www.kalodata.com` và `img.kalocdn.com` — nên cài kèm nhau cũng
không ai đụng phiên đăng nhập của ai. Đặc tả API ở `../docs/kalodata-api.md`.

## Cài (Chrome/Edge, chế độ dev)

1. `chrome://extensions` → bật **Developer mode**
2. **Load unpacked** → chọn thư mục `extension-kalodata`
3. Đăng nhập `www.kalodata.com` trong cùng trình duyệt
4. Bấm icon extension → bảng cào mở ở tab riêng

Không có popup: bấm icon là mở thẳng bảng. Popup rộng 360px và tự đóng mỗi lần mất focus —
chạy một job nhiều trang trong đó là mất kết quả giữa chừng.

## Hai bộ cào

| | 🛒 Sản phẩm | 🎬 Video |
|---|---|---|
| endpoint | `POST /product/searchList` | `POST /video/searchList` |
| khoá keyword | **`query`** | **`title`** |
| ảnh | `img.kalocdn.com/tiktok.product/{id}/cover.png` | `…/tiktok.video/{id}/cover.png` |
| lệnh | `KD_PRODUCT` | `KD_VIDEO` |

Thêm `KD_SWEEP` (quét nhiều region một lượt) và `KD_STATUS` (kiểm tra phiên, **không** trừ credit).

Region hợp lệ (rút từ bundle của Kalodata):
`US GB ID VN TH MY PH SG MX DE FR IT ES JP BR`

## Ba điều đã đo được, và code dựa vào chúng

- **Nhầm khoá keyword là hỏng câm.** Gửi `title` cho product thì API vẫn trả `success:true`
  kèm danh sách rỗng. Vì thế `kdCrawl` tự chọn khoá theo `kind`, không để chỗ gọi truyền vào.
- **Tiền là chuỗi đã rút gọn** (`"₫3,56tr"`). Số thô nằm ở `revenue_trend` — mảng theo ngày,
  cộng lại bằng đúng `revenue` tới từng đồng. `revenue_raw` là kết quả phép cộng đó; đừng
  parse chuỗi.
- **Ảnh không có trong response.** Trang render bằng CSS `background-image` nên không có thẻ
  `<img>` để bóc. URL suy thẳng từ id và **public** — curl không cookie vẫn ra 200 image/png,
  nên ảnh không tốn lượt gọi lẫn credit.

## Đường truyền hai nấc

Fetch thẳng từ service worker trước (nhanh, không cần tab). Nếu cookie phiên là `SameSite=Lax`
thì request từ extension không mang cookie đi và API trả về **200 kèm HTML đăng nhập** — lúc
đó tự lùi về chạy trong tab `www.kalodata.com`, nơi fetch thành same-origin. Vì Kalodata trả
200 khi phiên hỏng, code phân biệt "chưa đăng nhập" bằng **hình dạng phản hồi** (bắt đầu bằng
`<`) chứ không bằng mã trạng thái.

Nút **Kiểm tra đăng nhập** cho biết đang đi đường nào.

Tab dự phòng: mượn tab kalodata.com bạn đang mở trước; không có mới tự mở tab nền, và **không
tự đóng** — bạn có thể đang xem dở trang đó.

## Xem video ngay trong bảng

Tab Video có nút **▶** ở mỗi dòng, mở khung phát chính thức của TikTok
`tiktok.com/player/v1/{video_id}`. URL dựng thẳng từ id nên **không cần biết creator là ai**
và **không tốn credit** — Kalodata có `/video/detail/getVideoUrl` nhưng đó là một lượt gọi
tính tiền cho mỗi video, đổi lại đúng thứ đang xem miễn phí ở đây.

Ba nấc, tụt xuống khi nấc trên hỏng:

1. **Link của Kalodata** — `GET /video/detail/getVideoUrl?videoId={id}` → `{url}`, phát bằng
   thẻ `<video>`. Đây mới là thứ trang Kalodata dùng để xem tại chỗ, và là nấc **duy nhất đã
   chứng minh chạy**. Không suy được từ id như ảnh: thử
   `img.kalocdn.com/tiktok.video/{id}/{video,play,origin}.mp4` thì **404 cả ba**, dù
   `cover.png` cùng thư mục vẫn 200. `code 1053` = video đã gỡ/riêng tư, không phải lỗi phiên.
2. **Lớp phủ trong TAB KALODATA** — extension tiêm một overlay chứa iframe
   `tiktok.com/player/v1/{id}` vào chính trang kalodata.com rồi đưa tab đó ra trước.
3. **Mở tab mới** — luôn dùng được.

### Vì sao nấc 2 phải mượn tab Kalodata

TikTok chặn theo **origin của trang cha**. Đo 2026-09-08, cùng một video, cùng URL `player/v1`:

| trang cha | kết quả |
|---|---|
| `https://www.kalodata.com` | phát bình thường, có khung hình, `00:00/00:54` |
| tab tiktok.com (mở thẳng) | dựng vỏ (avatar, mô tả) rồi **không tạo thẻ `<video>`** |
| `chrome-extension://` | y hệt — vỏ có, luồng video không |

Đã thử và đã bỏ: chạy `embed.js` chính chủ cho thấy nó truyền trang cha qua tham số
`?referrer=<url đã encode>`, nên tưởng chỉ cần khai báo tham số đó là xong. Đo thật ở origin
`chrome-extension://`: script TikTok chạy được trong iframe, **bấm play vẫn không ra hình**.
Khoá theo origin thật, tham số không cứu được — **đừng thử lại đường đó**. Iframe trong bảng
đã gỡ bỏ hẳn.

Không phải CSP hay `X-Frame-Options`: TikTok **không** đặt `frame-ancestors`, **không** đặt
`X-Frame-Options`. Nó tự từ chối nạp luồng khi trang cha không phải một website thật.
Extension không giả được origin, nên nhúng iframe thẳng vào bảng là vô nghĩa — đã gỡ bỏ.

**`player/v1` chứ không phải `embed/v2`.** Đo 2026-09-08: `embed/v2` trả 503
`overload-protect triggered` — khung hiện ra đen thui mà không báo lỗi gì. `player/v1` là thứ
`embed.js` của chính TikTok nhúng, trả 200 ổn định (40 KB).

Link **Mở tab mới ↗** khởi đầu bằng `/@x/video/{id}` — tên tài khoản bịa vẫn ra đúng video
(đo: HTTP 200) nên dùng được ngay, không phải chờ mạng. Song song đó gọi **oEmbed của TikTok**
(công khai, không auth, không tốn credit) để lấy tên tài khoản thật + tiêu đề, rồi nâng link
lên URL canonical và hiện `@tên · tiêu đề` trên thanh khung. Hỏng thì thôi, link nền vẫn chạy.

Đóng khung bằng nút ✕, bấm nền, hoặc Esc — cả ba đều gỡ `src` về `about:blank` để tắt hẳn
tiếng chứ không chỉ ẩn đi.

Video KHÔNG có field `title`; phần chữ nằm ở `description`. Keyword thì vẫn gửi bằng khoá
`title` — hai thứ khác nhau. Và phải gửi kèm `video.filter.video_type = "WithProduct"`, bằng
không API trả về cả video organic và **mọi cột tiền sẽ bằng 0** — trông y hệt lỗi parse.

## Xem video NGOÀI kho Kalodata — tốn 0 request

Tab Video có ô **dán link TikTok bất kỳ** → `▶ Xem thử`. Nhận link đầy đủ, hoặc id dán trần.

Đường này **không gọi API Kalodata lần nào** — chỉ mở (hoặc dùng lại) một tab trên miền
kalodata.com rồi dựng lớp phủ ở đó, để mượn origin. Hạn mức tìm kiếm của gói không bị đụng.

Quan trọng vì gói hiện tại chỉ cho **10 lượt tìm kiếm/ngày**: phần lớn video cần xem là video
không do bảng này cào ra, mà với chúng thì `getVideoUrl` vô nghĩa (Kalodata không giữ link cho
video ngoài kho) — nên đi thẳng nấc 2.

## Lấy tối đa

Tick **Lấy tối đa** rồi bấm Chạy: panel lật từng trang một, vẽ dần vào bảng, và dừng khi chạm
trần phân trang của gói (tối đa 50 trang/region). Nút Chạy hoá thành **■ Dừng** trong lúc chạy
— cắt ngang được bất cứ lúc nào, vì mỗi trang là một lần trừ credit.

Lật từng trang thay vì giao cả job cho service worker để: thấy dữ liệu hiện dần, dừng được
giữa chừng, và chạm trần ở trang nào thì giữ nguyên những trang đã lấy được thay vì ném đi.

## Cột bảng tự sinh

Bảng đọc key của bản ghi thật rồi dựng cột, không hard-code. Field của `/product/searchList`
đã xác minh; `/video/searchList` thì **chưa bắt được lần nào**, mà hard-code cột cho nó là
đoán mò — đoán sai thì bảng trống trơn trong khi dữ liệu vẫn về đủ. Chạy tab Video phát đầu
là thấy luôn video có những field gì.

CSV xuất **đủ mọi field** kể cả mảng (nối bằng `|`), có BOM để Excel trên Windows đọc đúng
tiếng Việt.

## ⚠️ Credit và ToS

Mỗi `searchList` ăn quota gói thuê bao **y như bấm tay trên web**; tổng lượt gọi = số region ×
số trang. Chống đốt nhầm:

- giao diện hỏi lại khi vượt 6 lượt
- `KD_MAX_PAGES = 50` chặn lỗi gõ `pages: 9999`
- vòng lặp dừng ngay khi `total` cho biết đã hết dữ liệu, không chạy tiếp để nhận mảng rỗng
- nghỉ 900ms giữa các trang

**Paywall phân trang.** Gói thuê bao chặn cỡ trang lớn: `pageSize` 20 trả về
`Exceeded pagination limit` + `actionType.code = "UPGRADE"` (đo 2026-09-08), `pageSize` 10 thì
qua — đúng bằng cỡ web thật gửi. Nên mặc định là 10 (`KD_SAFE_PAGE_SIZE`), và nếu bạn tự nâng
lên thì lần chạm tường đầu tiên code tự hạ về 10 rồi thử lại **một lần**, các trang sau giữ
mức đã hạ. Chạm trần giữa chừng khi đã có dữ liệu thì dừng và ghi chú, không vứt bỏ những
trang đã lấy được.

Đây là **API nội bộ**, không phải API công khai — Kalodata chỉ mở "full API access" ở gói
Enterprise. Tự động hoá ở quy mô lớn vi phạm ToS và có thể bị khoá tài khoản. Số liệu GMV của
Kalodata cũng là **ước lượng AI từ scrape**, không phải số thật từ TikTok Shop
(xem `../docs/nghien-cuu-nguon-du-lieu.md` mục 5).
