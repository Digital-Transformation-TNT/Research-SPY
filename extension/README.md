# Research-SPY Fetcher (extension — Cách A)

Extension lấy dữ liệu sản phẩm từ các sàn chặn server (Shopee, sau này TikTok Shop) **bằng chính phiên đăng nhập của user**. Cookie **không bao giờ rời trình duyệt** — service worker chỉ mượn để gọi API của sàn rồi trả raw về, khác hẳn kiểu "gửi cookie về server".

## Vì sao cần

Server (kể cả Crawlee) gọi API sản phẩm Shopee đều bị **HTTP 403 / đá về login** — đã đo. Chỉ phiên đăng nhập của user mới qua cửa. Extension chạy trong trình duyệt user nên có sẵn phiên đó.

## Cấu trúc

| File | Vai trò |
|---|---|
| `manifest.json` | MV3, khai `host_permissions` theo tên miền + quyền `scripting`/`tabs`/`cookies` + content script cho web app |
| `background.js` | Service worker — điều phối. Chạy fetch **bên trong tab của sàn** qua `executeScript(world:'MAIN')` nên là **same-origin** (fetch từ chính service worker bị Shopee 403 dù có cookie). Tự mở tab nền nếu chưa có |
| `content.js` | Cầu nối: web app `postMessage` → chuyển tiếp tới background → trả kết quả về trang |
| `page-hook.js` | Chộp phản hồi mà **chính trang tự gọi** — dùng cho Taobao/Tmall/Temu, nơi request có chữ ký (`mtop x5sec`, `anti-content`) mà mình không tự ký được |
| `similar-hook.js` | Như trên, cho trang "sản phẩm tương tự" của Shopee |
| `popup.html` / `popup.js` | **Tự test** một sàn: nhập từ khoá → ra sản phẩm thật, không cần web app |
| `results.html` / `results.js` | **Trang research đầy đủ**, mở dạng full tab: nhiều từ khoá cùng lúc, nhiều sàn, một bảng gộp có cột Từ khoá và Sàn |

Các sàn `results.js` đang phủ: Shopee, TikTok Shop (qua Seller Center), Amazon, Taobao, 1688,
Temu, cộng Etsy và Facebook đi qua backend, và video từ TikTok với Douyin.

Chấm điểm trong `results.js` **soi gương** `backend/lib/ads/scoring.py::_score_product` — sửa
một bên thì nhớ sửa bên kia, vì không có gì tự bắt lỗi lệch nhau giữa hai bản.

## Cài (Chrome/Edge, chế độ dev)

1. Mở `chrome://extensions`
2. Bật **Developer mode** (góc phải trên)
3. **Load unpacked** → chọn thư mục `extension/` này
4. Ghim extension cho dễ bấm

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
| `manifest.json` → `host_permissions` | `http://localhost:8000/*` | tên miền backend thật |
| `results.js` → hằng `BACKEND` | `http://localhost:8000` | tên miền backend thật |

Hai chỗ đầu chỉ ảnh hưởng luồng web app; chỗ thứ ba ảnh hưởng trang `results.html` chạy độc
lập. Nếu backend chạy HTTPS thì cả ba phải là `https://`, vì trang HTTPS không gọi được
`http://` (mixed content) và lỗi ấy chỉ hiện trong console chứ không hiện trên giao diện.

## Thêm sàn mới

Extension **không cần biết Shopee là gì** — nó chỉ chạy `RequestSpec` do backend gửi. Thêm sàn client_fetch = thêm adapter backend (`build_request`/`parse_response`) + thêm domain vào `host_permissions`. Không phải sửa `background.js`/`content.js`.

## Bảo mật / an toàn tài khoản

- Cookie ở lại trình duyệt user; request đi bằng **IP của user** → cookie ↔ IP khớp region, giảm rủi ro bị gắn cờ.
- `background.js` giãn request (400–900ms + jitter) để pattern giống người thật.
- Không lưu cookie, không gửi cookie đi đâu ngoài chính domain sàn.
