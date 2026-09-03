# Research-SPY Fetcher (extension — Cách A)

Extension lấy dữ liệu sản phẩm từ các sàn chặn server (Shopee, sau này TikTok Shop) **bằng chính phiên đăng nhập của user**. Cookie **không bao giờ rời trình duyệt** — service worker chỉ mượn để gọi API của sàn rồi trả raw về, khác hẳn kiểu "gửi cookie về server".

## Vì sao cần

Server (kể cả Crawlee) gọi API sản phẩm Shopee đều bị **HTTP 403 / đá về login** — đã đo. Chỉ phiên đăng nhập của user mới qua cửa. Extension chạy trong trình duyệt user nên có sẵn phiên đó.

## Cấu trúc

| File | Vai trò |
|---|---|
| `manifest.json` | MV3, khai `host_permissions` theo tên miền + quyền `scripting`/`tabs`/`cookies`/`storage`/`alarms` + content script cho web app |
| `background.js` | Service worker — điều phối. Chạy fetch **bên trong tab của sàn** qua `executeScript(world:'MAIN')` nên là **same-origin** (fetch từ chính service worker bị Shopee 403 dù có cookie). Tự mở tab nền nếu chưa có |
| `content.js` | Cầu nối: web app `postMessage` → chuyển tiếp tới background → trả kết quả về trang |
| `page-hook.js` | Chộp phản hồi mà **chính trang tự gọi** — dùng cho Taobao/Tmall/Temu, nơi request có chữ ký (`mtop x5sec`, `anti-content`) mà mình không tự ký được |
| `similar-hook.js` | Như trên, cho trang "sản phẩm tương tự" của Shopee |
| `popup.html` / `popup.js` | **Tự test** một sàn: nhập từ khoá → ra sản phẩm thật, không cần web app |
| `tabs.test.js` | Kiểm tra vòng đời tab bằng chrome API giả — `node extension/tabs.test.js`, không cần Chrome |

### Trang Research đã CHUYỂN sang webtool

Trước đây extension có `results.html` / `results.js` — trang research đa sàn mở dạng full tab.
Nó đã chuyển hẳn sang webtool và giờ sống ở `frontend/public/research/`, hiện ra ở đường `/ads`.

**Chuyển chứ không nhân bản**: hai bản của cùng 1.300 dòng chắc chắn sẽ trôi dạt khỏi nhau, và
không có gì tự bắt được lúc chúng lệch. File trong webtool giống bản cũ từng dòng, trừ một lớp
ở đầu file giả lập `chrome.runtime` và `chrome.tabs` bằng cầu postMessage của `content.js`.

Nhờ vậy extension trở lại đúng một việc: **mượn phiên đăng nhập để gọi mạng**. Không giao diện,
không chấm điểm, không trạng thái. Các sàn nó phục vụ: Shopee, TikTok Shop (qua Seller Center),
Amazon, Taobao, 1688, Temu, cùng video TikTok và Douyin.

Chấm điểm trong `public/research/research.js` **soi gương** `backend/lib/ads/scoring.py::_score_product`
— sửa một bên thì nhớ sửa bên kia, vì không có gì tự bắt lỗi lệch nhau giữa hai bản.

> **`all_frames: true` trong `manifest.json` là bắt buộc.** Trang Research nằm trong một
> `<iframe>` của webtool, mà content script mặc định chỉ chạy ở khung trên cùng. Thiếu dòng đó
> thì cầu postMessage không có ai nghe, và trang báo "chưa cài extension" dù đã cài.

## Vòng đời tab — giữ tab, KHÔNG giữ trang

Mỗi sàn có một tab nền thường trú (`keptTab`). Giữ tab là cố ý: mở tab mất vài giây, và tab nền
thừa hưởng cookie đăng nhập của hồ sơ nên không phải đăng nhập lại.

Cái **không** được giữ là **trang**. Đo trên máy thợ ngày 2026-09-03: Chrome chạy liền 6 ngày
ngốn 1.66 GB, trong đó hai renderer nặng nhất là 301 MB và 282 MB — trang kết quả Amazon và
Douyin của lần chạy từ mấy hôm trước, vẫn còn nguyên DOM, ảnh và timer JS. Nên:

| Cơ chế | Khi nào | Làm gì |
|---|---|---|
| `coolTab` | ngay sau khi trả kết quả (`withCooldown`) | đưa tab về `about:blank` — renderer được giải phóng, **tab và phiên đăng nhập vẫn còn** (cookie nằm ở hồ sơ Chrome, không nằm ở tab) |
| `reapTabs` | báo thức mỗi phút | đóng hẳn tab đã rảnh quá 10 phút; các hàm trên tự mở lại khi cần |
| `openVerifyTab` | sàn bắt kéo slider | **một** tab xác minh cho mỗi sàn, dùng lại — trước đây mỗi lượt bị chặn là một cửa sổ mới, mười người dùng chung là mười cửa sổ |

Hai ngoại lệ của `reapTabs`, đều cố ý: tha tab **đang chạy job** (cờ `busySlots` — một lượt tìm
nhiều cụm từ có thể lâu hơn 10 phút) và tha tab **đang hiện trước** (người vận hành đang giải
slider ở đó).

Tab Shopee hạ nhiệt về **trang chủ sàn** chứ không về trang trống: `handleFetch` (lấy giá vốn)
phải fetch same-origin, nên tab cần nằm sẵn trên origin của sàn.

> **Tab id phải ghi ra `chrome.storage.session`, không được để trong biến module.** Service
> worker MV3 bị treo sau ~30 giây rảnh và biến mất theo — nhưng tab thì không. Bản 0.3.0 giữ id
> trong biến, nên mỗi lần service worker sống lại nó mở tab MỚI và bỏ rơi tab cũ.

## Cài (Chrome/Edge, chế độ dev)

1. Mở `chrome://extensions`
2. Bật **Developer mode** (góc phải trên)
3. **Load unpacked** → chọn thư mục `extension/` này
4. Ghim extension cho dễ bấm

Nâng cấp từ bản 0.3.0 trở về trước thì phải bấm **Reload** ở `chrome://extensions` — bản
0.4.0 thêm quyền `storage` và `alarms`, mà quyền mới chỉ có hiệu lực sau khi nạp lại. Tab
"Máy thợ crawl" cũng cần F5 để nối lại cầu postMessage.

## Test nhanh (không cần web app)

1. Mở một tab **shopee.vn** và **đăng nhập** (bắt buộc — nếu không sẽ nhận 403)
2. Bấm icon extension → popup hiện ra
3. Nhập từ khoá (vd "máy hút bụi cầm tay"), chọn region **VN**, bấm **Tìm thử**
4. Nếu đã đăng nhập: hiện danh sách sản phẩm kèm **giá + số đã bán + ảnh** (HTTP 200)
   Nếu chưa: báo **403 — mở shopee.vn đăng nhập rồi thử lại**

> Đây chính là bằng chứng Cách A chạy: cùng request mà server bị 403, chạy trong trình duyệt đã đăng nhập thì ra data thật.

## Nối với web app (đã wiring sẵn)

Luồng trong `frontend/`:

```
/api/ads/search  → trả AdSearchResult.pending (ClientJob cho Shopee)
frontend         → lib/ads/extension.ts: runClientJobs(pending)  ── postMessage ──▶ content.js ▶ background.js ▶ Shopee
                 → POST /api/ads/ingest (raw responses)
/api/ads/ingest  → backend parse_response → chấm điểm → trả ads → gộp vào lưới
```

- `frontend/lib/ads/extension.ts` — bridge client (`extensionAvailable`, `runClientJobs`)
- `AdsResearch.tsx` — sau khi search, nếu có `pending` thì gọi extension rồi ingest; không có extension thì hiện thông báo "cần cài extension".

### Khi deploy lên server thật: BA chỗ phải sửa

Extension đang trỏ cứng vào máy cá nhân. Đổi cả ba, thiếu một chỗ là nó im lặng không chạy:

| Chỗ | Đang là | Sửa thành |
|---|---|---|
| `manifest.json` → `content_scripts[0].matches` | `http://localhost:3000/*` | tên miền web app thật |
| `popup.js` → hằng `WEBAPP` | `http://localhost:3000` | tên miền web app thật |

Chỉ còn hai chỗ. Hằng `BACKEND` không còn phải sửa nữa: trang Research đã nằm trong webtool nên
`/api/...` đi cùng origin, và `frontend/next.config.mjs` lo phần chuyển tiếp.

Nếu web app chạy HTTPS thì cả hai phải là `https://`, và nhớ rằng trang HTTPS không gọi được
`http://` (mixed content) — lỗi ấy chỉ hiện trong console chứ không hiện trên giao diện.

## Thêm sàn mới

Extension **không cần biết Shopee là gì** — nó chỉ chạy `RequestSpec` do backend gửi. Thêm sàn client_fetch = thêm adapter backend (`build_request`/`parse_response`) + thêm domain vào `host_permissions`. Không phải sửa `background.js`/`content.js`.

## Bảo mật / an toàn tài khoản

- Cookie ở lại trình duyệt user; request đi bằng **IP của user** → cookie ↔ IP khớp region, giảm rủi ro bị gắn cờ.
- `background.js` giãn request (400–900ms + jitter) để pattern giống người thật.
- Không lưu cookie, không gửi cookie đi đâu ngoài chính domain sàn.
