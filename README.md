# Research SPY

Công cụ nội bộ cho phòng test sản phẩm. Hai mục lớn, hoàn toàn độc lập với nhau:

| Mục | Đường dẫn | Làm gì | Lấy dữ liệu từ |
|---|---|---|---|
| **Quảng cáo** | `/ads` | Tìm content quảng cáo đang chạy, chấm điểm ứng viên sản phẩm | Facebook Ads Library, TikTok Creative Center *(sẽ thêm nguồn khác)* |
| **Từ khoá** | `/keywords` | Mở rộng từ khoá gốc ra biến thể đang được tìm kiếm, đo xu hướng | Google Suggest, Shopee, TikTok, Google Trends |

Ngoài ra có `/guide` — trang hướng dẫn đọc số liệu, **nên đọc trước khi ra quyết định test sản phẩm**.

---

## Chạy dự án

```bash
npm install          # tự cài luôn Chromium cho Playwright
cp .env.example .env.local   # tuỳ chọn — chạy được mà không cần sửa gì
npm run dev          # http://localhost:3000
```

Lệnh khác:

```bash
npm run build          # build production
npm run start          # chạy bản build, mở cổng 3000 cho cả LAN
npm run typecheck      # tsc --noEmit
npm run smoke:ads      # test đầu-cuối mục Quảng cáo (cần dev server đang chạy)
npm run smoke:keywords # test đầu-cuối mục Từ khoá
npm run smoke:ui       # mở trình duyệt thật, click hết các nút, bắt lỗi client
npm run audit:keywords # đối chiếu độc lập: dữ liệu tool hiện có khớp nguồn gốc không
```

---

## Cấu trúc thư mục

Nguyên tắc: **mỗi mục lớn có một thư mục riêng ở cả ba tầng** (dữ liệu, giao diện, style).
Nhìn đường dẫn của một file là biết ngay nó thuộc mục nào, nên đọc commit cũng dễ và hai
người làm hai mục khác nhau gần như không đụng file của nhau.

```
lib/
├── core/                    # HẠ TẦNG DÙNG CHUNG — không biết Facebook/TikTok là gì
│   ├── config.ts            #   cấu hình chung (cache, timeout, user-agent)
│   ├── cache.ts             #   cache TTL trong bộ nhớ
│   ├── rate-limit.ts        #   hàng đợi giữ nhịp gọi ra ngoài
│   ├── browser.ts           #   kho phiên trình duyệt, chạy theo "recipe" nguồn tự khai
│   └── http.ts              #   fetch JSON cho nguồn không cần trình duyệt
│
├── ads/                     # ===== MỤC QUẢNG CÁO =====
│   ├── platform.ts          #   HỢP ĐỒNG một nguồn quảng cáo phải thoả  ← đọc file này trước
│   ├── platforms/
│   │   ├── index.ts         #   SỔ ĐĂNG KÝ — nơi duy nhất sửa khi thêm nguồn
│   │   ├── facebook.ts      #   toàn bộ đặc thù Facebook nằm gọn ở đây
│   │   └── tiktok.ts        #   toàn bộ đặc thù TikTok nằm gọn ở đây
│   ├── types.ts             #   Ad, AdScore, tham số tìm kiếm
│   ├── scoring.ts           #   chấm điểm ứng viên sản phẩm
│   └── search.ts            #   điều phối: fan-out, gộp, lọc, xếp hạng
│
└── keywords/                # ===== MỤC TỪ KHOÁ =====
    ├── provider.ts          #   HỢP ĐỒNG một nguồn từ khoá phải thoả
    ├── providers/
    │   ├── index.ts         #   SỔ ĐĂNG KÝ — nơi duy nhất sửa khi thêm nguồn
    │   ├── expand.ts        #   bộ máy mở rộng long-tail, dùng chung mọi nguồn
    │   ├── google.ts  shopee.ts  tiktok.ts
    ├── types.ts  normalize.ts  rank.ts  trends.ts  search.ts

app/
├── ads/page.tsx             # trang Quảng cáo (server component, chỉ truyền dữ liệu xuống)
├── keywords/page.tsx        # trang Từ khoá
├── guide/page.tsx           # trang Hướng dẫn
├── page.tsx                 # chuyển hướng về /ads
└── api/
    ├── ads/search  ads/health  ads/filters
    ├── keywords    keywords/trend
    └── media                 # proxy phát video, có danh sách host cho phép

components/
├── ads/                     # AdsResearch, AdCard, HealthBar, PlatformOptions
├── keywords/                # KeywordResearch, KeywordTable, Sparkline, relevance
└── layout/                  # Sidebar

styles/                      # CSS tách theo đúng ranh giới trên: ads.css, keywords.css, …
scripts/
├── smoke/                   # test đầu-cuối: ads.ts, keywords.ts, ui.ts
└── audit/                   # đối chiếu độc lập với nguồn gốc
```

### Quy tắc phụ thuộc

```
lib/ads  ──┐
           ├──►  lib/core        (một chiều, không bao giờ ngược lại)
lib/keywords ┘

lib/ads  ✗  lib/keywords        (hai mục KHÔNG import lẫn nhau, kể cả kiểu dữ liệu)
```

Hai mục dùng chung đúng ba thứ: cache, hàng đợi rate-limit, và cấu hình chung. Không dùng
chung kiểu dữ liệu nào. `lib/keywords/providers/tiktok.ts` và `lib/ads/platforms/tiktok.ts`
trùng tên nhưng là hai file không liên quan — một cái đọc gợi ý tìm kiếm, một cái đọc thư
viện quảng cáo.

---

## Thêm một nguồn mới

Xem hướng dẫn đầy đủ kèm ví dụ ở **[CONTRIBUTING.md](CONTRIBUTING.md)**. Tóm tắt:

* **Nguồn quảng cáo mới** (Shopee Ads, Google Ads, Lazada…): tạo `lib/ads/platforms/<tên>.ts`
  theo hợp đồng ở `lib/ads/platform.ts`, rồi thêm một dòng vào `lib/ads/platforms/index.ts`.
  Không phải sửa route, giao diện, proxy media hay file cấu hình nào.
* **Nguồn từ khoá mới**: tạo `lib/keywords/providers/<tên>.ts` theo `lib/keywords/provider.ts`,
  thêm một dòng vào `lib/keywords/providers/index.ts`.

---

## File và thư mục KHÔNG commit

Đã khai báo sẵn trong [.gitignore](.gitignore). Liệt kê lại ở đây để rõ lý do:

| Đường dẫn | Vì sao không commit |
|---|---|
| `node_modules/` | Dựng lại được từ `package-lock.json`, hàng trăm MB |
| `.next/` | Kết quả build, luôn dựng lại được |
| `next-env.d.ts`, `*.tsbuildinfo` | Next.js và TypeScript tự sinh mỗi lần chạy |
| `.env`, `.env.local` | **Chứa bí mật** (cookie Facebook). Chỉ commit `.env.example` |
| `_archive/` | Kho script thăm dò một lần và dữ liệu dump — xem giải thích bên dưới |
| `.probe/` | Ảnh chụp và JSON dump từ các lần thăm dò |
| `*.log`, `screenshots/`, `coverage/` | Sản phẩm phụ khi chạy |
| `.vscode/`, `.idea/`, `.DS_Store`, `Thumbs.db` | Cấu hình máy cá nhân và rác hệ điều hành |

**Về `_archive/`:** thư mục này chứa 34 script thăm dò một lần đã dùng để tìm ra cách gọi
được từng endpoint, cộng với ảnh và JSON dump của chúng. Chúng là *ghi chép nghiên cứu*,
không phải phần mềm đang chạy — mỗi file chỉ trả lời đúng một câu hỏi rồi hết việc, và
**mọi kết luận rút ra từ chúng đã được ghi thành comment ngay trong file của nguồn tương
ứng** (ví dụ vì sao TikTok chỉ nhận `period` là 7/30/180, vì sao Shopee phải dùng
`search_hint` chứ không phải `search_suggestion`). Giữ lại trên máy để tra khi một nền tảng
đổi cấu trúc, nhưng đưa lên GitHub thì chỉ làm repo khó đọc.

Nếu muốn xoá hẳn cho gọn: `rm -rf _archive`.

---

## Giới hạn cần biết (quan trọng)

Ba điều này ảnh hưởng trực tiếp tới việc đọc số liệu — trang `/guide` giải thích kỹ hơn:

1. **"CVR ước lượng" không phải CVR thật.** Không nền tảng công khai nào cung cấp tỷ lệ
   chuyển đổi; đó là dữ liệu riêng trong tài khoản advertiser. Con số trên mỗi thẻ suy ra từ
   số ngày quảng cáo đã chạy (55%), số biến thể creative (20%), CTR (15%) và tương tác (10%).
   Dùng để **xếp hạng ứng viên với nhau**, không dùng thay số liệu thật khi tính ngân sách.

2. **TikTok không search được theo từ khoá.** Creative Center chỉ mở chức năng này cho tài
   khoản đã đăng nhập; phiên ẩn danh nhận về *0 kết quả kèm mã thành công* — trông hệt như
   "sản phẩm không có nhu cầu". Khi gặp trường hợp này công cụ chuyển sang duyệt Top Ads theo
   CTR và **luôn kèm thông báo nói rõ**. Thấy thông báo đó thì đừng kết luận về nhu cầu sản
   phẩm, hãy nhìn phần Facebook.

3. **Điểm ở mục Từ khoá là độ phù hợp, không phải lượng search.** Không nguồn miễn phí nào
   cho volume thật. Cột "Có mặt trên" nói nguồn nào *gợi ý* từ khoá đó và ở vị trí mấy — không
   phải doanh số. (Đo ngày 2026-07-28: endpoint tìm sản phẩm của Shopee trả 403 với người gọi
   ẩn danh, search organic của TikTok trả body rỗng, nên số lượt bán và lượt xem đều ngoài
   tầm với.) Nút "Đo xu hướng" dùng Google Trends để cho con số **tương đối so với từ gốc** —
   đó là tín hiệu nhu cầu thật duy nhất công cụ có.

**Chưa dùng proxy.** Tìm kiếm đa quốc gia chạy qua bộ lọc quốc gia của chính nền tảng, nghĩa
là bạn thấy những gì một người ở Việt Nam nhìn thấy khi lọc theo nước đó, không phải những gì
người bản địa nước đó nhìn thấy. Khi nào cần so sánh thị trường chính xác hơn thì bàn tiếp.

---

## Vận hành

* **Chạy một server dùng chung cho cả team.** Cache 15 phút được chia sẻ, đó là lý do chính:
  nhiều người search cùng một sản phẩm sẽ nhân số request ra ngoài lên và làm IP chung bị chặn.
* **Không lưu video.** Media được phát xuyên qua `/api/media`, không ghi gì xuống đĩa. Link CDN
  có chữ ký và hết hạn sau vài giờ — mở lại hôm sau thì search lại để lấy link mới.
* **Chấm đỏ ở thanh trạng thái** nghĩa là nguồn đó đang có vấn đề, có thể nền tảng đã đổi cấu
  trúc. File cần sửa khi đó chính là `lib/ads/platforms/<tên nguồn>.ts` và không file nào khác.
