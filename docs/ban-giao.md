# Research-SPY — Bàn giao (trạng thái & lộ trình)

> Tài liệu bàn giao cho agent/dev tiếp theo. Ghi lại: đã làm gì, đang dở, chưa làm, cần cải
> thiện, cùng các **sự thật đo được** và **quyết định kiến trúc** để không phải dò lại từ đầu.
> Cập nhật: 2026-08-04.

---

## 0. Bối cảnh & mục tiêu

Mở rộng **Research-SPY** từ ads-spy (Facebook/TikTok) sang **product research đa sàn**.
Luồng nghiệp vụ: **keyword nổi → tìm sản phẩm theo keyword (giá/số bán/rating) → tìm content
theo ảnh sản phẩm (image search)**.

Sàn mục tiêu: Shopee, TikTok Shop, Facebook Ads, Amazon, Etsy, Taobao, 1688, Temu.

**Ràng buộc chính:** rẻ (100–200 user, có người search vài trăm lượt/ngày), nhanh, đủ data.

---

## 1. Kiến trúc tổng (QUAN TRỌNG — đọc trước)

Không có 1 cách cho mọi sàn. **Hybrid theo bản chất sàn:**

| Nhóm | Sàn | Cách lấy | Chạy ở |
|---|---|---|---|
| **Login-wall + user có account** | Shopee, TikTok Shop | **Cách A** (extension fetch bằng session user) | **Client** (trình duyệt user) |
| **Công khai** | Amazon, Facebook Ads | scrape (Amazon: extension; FB: backend Playwright) | Amazon=client, FB=server |
| **API key/secret** | Etsy | API chính thức | **Backend** (secret không để lộ ra client) |
| **API trả phí (login-gate)** | Taobao, 1688, Temu | API TMAPI/Elim/Bright Data | Backend (chưa làm) |

**Cách A (cốt lõi tiết kiệm chi phí):** extension fetch bằng cookie đăng nhập sẵn của user →
chi phí ~$0, CPU đổ về máy user, server gần như rảnh. Đổi lại: chỉ phủ region user có account,
rủi ro ban dồn lên user (đã có rate-limit + cache giảm thiểu).

**Hai "cổng" một sàn phải qua với Cách A:** (1) login — account giải quyết; (2) chữ ký chống bot
— account KHÔNG giải quyết (cần navigate+intercept). Shopee search: cổng 1 (đã qua). Shopee
find_similar / TikTok Shop: cổng 2 (khó).

---

## 2. ĐÃ LÀM XONG (verified)

### 2.1 Khung backend 2 pha (client_fetch)
- `backend/lib/ads/platform.py`: thêm `PlatformCapabilities.client_fetch`. Nguồn client_fetch
  hiện thực `build_request()` (server dựng lệnh, không chạm cookie) + `parse_response()` (chuẩn
  hoá raw). Nguồn server-fetch vẫn dùng `search()`.
- `backend/lib/ads/search.py`: `run_ad_search` (pha 1) trả `AdSearchResult.pending: list[ClientJob]`;
  extension chạy rồi POST `/api/ads/ingest` (pha 2 → `ingest_client_results`). `_client_cache_key`
  cache theo (nguồn, quốc gia) = giảm request/tài khoản.
- `backend/lib/ads/types.py`: `Ad` thêm `price, currency, sold_count, monthly_sold, rating,
  rating_count`. `AdScore` thêm `demand_score, quality_score`.
- `backend/app/api/ads.py`: thêm `POST /api/ads/ingest`; `/health` xử lý riêng nguồn client_fetch.

### 2.2 Chấm điểm sản phẩm — `backend/lib/ads/scoring.py::_score_product`
- **Cầu 60% + Chất lượng 40%.** Cầu: ưu tiên `monthly_sold` (nhu cầu hiện tại) hơn tổng luỹ kế.
  Chất: `rating` × độ tin (log của số review). Có cờ "đang lên / bão hoà".
- `score_ad()` rẽ nhánh: có `price/sold_count/monthly_sold` → `_score_product`; không thì
  chấm kiểu quảng cáo cũ (đời quảng cáo/CTR).
- **JS phản chiếu:** `extension/results.js::score()` — SỬA MỘT BÊN NHỚ SỬA BÊN KIA.

### 2.3 Shopee — `backend/lib/ads/platforms/shopee.py` (Cách A, client_fetch)
- 11 region: VN/TH/ID/MY/PH/SG/TW/BR/MX/CO/CL (DOMAIN/IMG_REGION/CURRENCY).
- Endpoint `search_items`. Sort mặc định **sales** (bán chạy — tránh feed toàn quảng cáo).
- **Format 2026 (đo thật):** Shopee đã BỎ `item_basic` (giờ `null`). Product data ở:
  - `item_card_displayed_asset`: name, image, images, shop_location, display_price.price
  - `item_data`: item_card_display_price.price (÷100000), item_card_display_sold_count
    (historical/monthly), item_rating (rating_star, rating_count[0]=tổng), shop_data.shop_name, catid
  - Item có `adsid` = quảng cáo.
- `_normalise` đỡ cả format mới lẫn cũ. Giá chia `PRICE_SCALE=100000`.

### 2.4 Amazon — trong extension (`extension/results.js` + `background.js`)
- **Công khai, không login.** 8 region: US/GB/DE/JP/FR/IT/ES/CA (AMZ_DOMAIN/AMZ_CUR).
- **KHÔNG fetch từ service worker** (bị captcha). Cách chạy: `background.js::amazonSearch` mở
  MỘT tab nền riêng (`amazonTabId`, reuse), điều hướng tới `/s?k=`, đọc DOM qua executeScript.
- Parse: `div[data-component-type="s-search-result"]` → title (h2 span), price (.a-price .a-offscreen),
  strike, image (img.s-image), rating (.a-icon-alt), **số review** (container
  `alf-customer-ratings-count-component` → aria-label, strip số — region-agnostic), **"X bought
  in past month"** → monthly (cầu thật).
- Amazon không có sold → cầu từ monthly (bought) hoặc số review.

### 2.5 Etsy — `backend/lib/ads/platforms/etsy.py` (backend, API v3)
- **Auth: `x-api-key: keystring:shared_secret`** (CẢ HAI — chỉ keystring → 403). Đọc
  `ETSY_KEYSTRING` + `ETSY_SHARED_SECRET` từ `.env.local`.
- **2 lần gọi:** `listings/active` (id + giá + num_favorers) → `listings/batch?includes=Images,Shop`
  (ảnh + shop name + shop review_average/review_count).
- `countries=None` (1 sàn toàn cầu, không region). Giá = price.amount/price.divisor.
- **Cầu = favorites** (Etsy giấu số bán). **Rating = review_average của SHOP** (Etsy không có
  rating theo listing). BÁN/THÁNG & GIẢM luôn "—" (Etsy không công khai).

### 2.6 Facebook Ads — `backend/lib/ads/platforms/facebook.py` (backend, ad-spy)
- Đã có sẵn (nguồn gốc dự án). Playwright harvest query GraphQL đã ký → replay. Là **quảng cáo**
  (advertiser/creative/ngày chạy), KHÔNG phải sản phẩm.
- **Mới thêm `_matches_keyword`:** FB Ad Library khớp lỏng trên ad copy → lọc lại giữ quảng cáo
  chứa đủ từ khoá (cắt rác kiểu "đai lưng" khi search "xe đạp điện").
- Trong extension: nằm ở **tab Content** riêng (không chung bảng product).

### 2.7 Extension — trang research (`extension/results.html` + `results.js`)
Tool chính user đang dùng. Mở full tab từ popup (`extension/popup.*`).
- **2 tab:** 🛍️ Sản phẩm (Shopee/Amazon/Etsy — bảng), 🎬 Content (Facebook — thẻ quảng cáo).
- Bộ lọc: ① chọn Sàn (nhiều = so sánh) ② Region tự đổi theo sàn (ẩn nếu sàn không region) +
  **badge đăng nhập tức thì** qua cookie `SPC_U` (quyền `cookies`), Amazon region = 🌐 công khai
  ③ số lượng + nhiều từ khoá (dấu phẩy).
- Bảng gộp xếp theo điểm, cột Sàn/Từ khoá/giá/giảm, hover ảnh zoom, sort cột, lọc từ khoá.
- **Sàn backend (Etsy/Facebook):** extension gọi `http://localhost:8000/api/ads/search`, ảnh qua
  `/api/media` proxy, dùng điểm backend chấm. Backend không chạy → báo rõ.
- UX: ô keyword rỗng + placeholder "Keyword", KHÔNG auto-research khi mở.

### 2.8 Extension — cơ chế Cách A (Shopee)
- `background.js`: `fetchInTab` chạy fetch trong tab shopee.vn qua
  `chrome.scripting.executeScript({world:'MAIN'})` — **fetch từ service worker là cross-origin →
  Shopee 403 dù có cookie; phải same-origin trong tab.**
- `content.js`: cầu nối postMessage (cho wiring frontend production — chưa dùng ở tool extension).
- `manifest.json`: host_permissions 11 domain Shopee + 8 Amazon + localhost:8000 + quyền
  scripting/tabs/cookies.

---

## 3. ĐANG DỞ / BUG CHƯA SỬA

### 3.1 Lỗi hiển thị — tên sản phẩm tràn đè cột Sàn (✅ ĐÃ SỬA 2026-08-04)
- Tên dài kiểu "Ốp lưng Redmi 15/15T/13x/..." (chuỗi model ngăn bằng `/`, không có dấu cách) là
  một "từ" dài → tràn ngang qua cột Sàn.
- **Đã fix:** `extension/results.html` `<style>` — thêm `.prod > div { min-width: 0; }` (cho phép
  cột co) và `overflow-wrap: anywhere; word-break: break-word;` cho `.prod .name`. Đã đo geometry
  xác nhận cột Sản phẩm không còn tràn qua cột Sàn.

### 3.2 Amazon — một số dòng KHÔNG có giá (✅ ĐÃ SỬA 2026-08-04)
- Vài sản phẩm Amazon cột GIÁ hiện "—" (vd "Amazon Basics Portable Wireless Mouse").
- Nguyên nhân: chỉ đọc `.a-price .a-offscreen`; sản phẩm không buy-box không có node đó. Thêm nữa
  cách strip cũ `replace(/[^0-9.]/g,'')` làm HỎNG định dạng EU ("1.299,00 €" → 1.299).
- **Đã fix:** `background.js::amazonSearch` — thêm parser tiền `money()` nhận diện dấu thập phân
  theo locale (US/EU/JP), và `priceOf()` fallback theo thứ tự `.a-offscreen` → `.a-price-whole`
  (+`.a-price-fraction`) → bất kỳ `.a-offscreen` có số. Strike cũng dùng `money()`. Đã unit-test 9 ca.

### 3.3 Giá vốn (find_similar) — ĐANG ẨN
- `recommend_post` (find_similar) trả **403 cả khi replay trong tab find_similar** (trang không
  tự ký fetch của mình — cần `x-sap-sec` + `device_sz_fingerprint`).
- Đã ẩn cột giá vốn. Logic giữ dead-code: `runCostBatch`/`costCache`/`collectPrices` trong
  results.js + `similar-hook.js` + `RS_COST_BATCH`/`findSimilar` trong background.js.
- Bật lại khi có cách ký (navigate+intercept đọc response của trang thay vì replay), HOẶC bỏ
  hẳn — **giá vốn thật nên đi ảnh→1688** (xem 4.4).

---

## 4. CHƯA LÀM (roadmap)

### 4.1 TikTok Shop (Cách A qua Seller Center) — ✅ ĐÃ LÀM 2026-08-04 (account PH)
- **Endpoint (đo thật):** `POST seller-<region>.tiktok.com/api/v1/product/oc/seller_product_opportunity/seller/lead/list`
  — trang "Product opportunities → High-potential products". **CÓ keyword search** (`search_text` trong
  body) + phân trang (`page_number`/`page_size` ≤100). Body: `{opportunity_type:3, tab_code_filter:
  ["high_potential_products"], sort_field:1, use_like:false, page_number, page_size, search_text, traffic_source:"seller_organic"}`.
- **Chữ ký:** URL có `X-Tts-Oec-Bsid` (đổi mỗi request, SDK `browser.sg.js` sinh) + `fp` (=cookie
  `s_v_web_id`, ổn định). **ĐO ĐƯỢC: fetch same-origin TRONG tab seller → SDK TỰ KÝ** (bỏ Bsid vẫn
  `code:0 success`). Nên làm được kiểu Shopee (build+fetch trong tab), KHỎI navigate+intercept.
- **seller_id** lấy từ cookie `oec_seller_id_unified_seller_env` (mỗi user một id).
- **Response fields:** `data[].lead_name` (tên), `pic_url[0]` (ảnh), `recommend_price_low` "1,099.00"
  (giá), `l30d_sales_volume` "2,140" (bán 30 ngày = cầu), `gmv_l30d` "₱131,065", `level3_cate_name`
  (ngành), `search_volume`, `real_external_product_id`.
- **Chấm điểm (không có rating):** ĐÃ RESEARCH kỹ — TikTok **giấu rating đối thủ** ở toàn bộ Seller
  Center (list + detail đều không có; detail chỉ có chart items-sold + submission guide). Rating chỉ
  nằm ở trang consumer `shop.tiktok.com` (gated + ký) → **KHÔNG lấy free được**. Nguồn có review:
  SocialCrawl/Apify/ScrapeCreators (trả phí) hoặc TikTok Research API (miễn phí nhưng phải xin duyệt,
  thiên US). **Lưu ý:** SocialCrawl **chỉ có TikTok, KHÔNG có Shopee** — nhưng Shopee mình đã có rating
  free rồi nên không cần.
- **Quyết định:** không giả vờ có quality. `score()` dùng **GMV/tháng quy USD** (`FX_USD`) log-normalize
  làm phần 40% (để TikTok không bị thiệt khi xếp chung với Shopee có rating), NHƯNG dòng phụ hiển thị
  **"cầu · GMV <compact>"** (đúng tên doanh thu) thay vì "chất" — xem `scoreSub()` trong results.js.
- **Đa region:** code generic sẵn (8 domain `seller-*.tiktok.com`, `TT_DOMAIN`/`TT_CUR`/`TT_TZ`,
  seller_id đọc từ cookie). Region nào user đăng nhập seller center thì badge ✓ và chạy được — hiện
  chỉ test PH; region khác tự chạy khi có account (không cần sửa code).
- **Code:** `extension/results.js` — `fetchTiktok`/`parseTiktokItem`, `TT_DOMAIN`/`TT_CUR`, `LOGIN`
  (đăng nhập theo từng sàn, cookie `oec_seller_id_unified_seller_env`). `manifest.json` thêm 8 domain
  `seller-*.tiktok.com`. Dùng lại hạ tầng `RS_FETCH`/`fetchInTab` sẵn có (giống Shopee).
- **Giới hạn:** chỉ chạy region user có account seller (hiện PH). Region khác = badge ✕ (chưa login).
  Fetch tab nền "nguội" có thể lỡ nhịp SDK lần đầu → mở sẵn 1 tab seller hoặc thử lại.
- Fallback (nếu cần đa region không có account): API SocialCrawl (£15–49).

### 4.2 1688 — ✅ ĐÃ LÀM (2026-08-11: CHUYỂN SANG API mtop JSON, bỏ DOM-scrape)
- **Đổi cách (2026-08-11):** trang React `s.1688.com`/`www.1688.com` giờ **đá về `login.taobao.com`**
  khi phiên "lạnh"/IP lạ (đã đo lại) → DOM-scrape cũ hỏng. Thay bằng **gọi thẳng API nội bộ mtop JSON**
  mà trang tự gọi — **trả sản phẩm KỂ CẢ ẩn danh (không cần login)**. Đã đo thật: 20 SP/trang, `found`
  tới ~2000, tên/giá(￥)/ảnh/shop sạch, ngay từ IP datacenter chưa đăng nhập.
- **Endpoint:** `GET https://h5api.m.1688.com/h5/mtop.relationrecommend.wirelessrecommend.recommend/2.0/`
  · `appKey=12574478` · `api=mtop.relationrecommend.WirelessRecommend.recommend` · `v=2.0`.
- **Chữ ký:** `sign = md5(token + "&" + t + "&" + appKey + "&" + data)`, `token` = phần trước dấu `_`
  trong cookie `_m_h5_tk`. Bootstrap: gọi lần 1 (token rỗng) → server set cookie `_m_h5_tk` →
  đợi ~400ms → gọi lần 2 đã ký. **Phải chạy trong tab origin `*.1688.com`** để `document.cookie`
  đọc được `_m_h5_tk` (ở `login.taobao.com` không đọc được → `FAIL_SYS_ILLEGAL_ACCESS`).
- **data:** `{"appId":"32517","params":"{keywords, beginPage, pageSize(≤60), method:getOfferList,
  verticalProductFlag:pcmarket, searchScene:pcOfferSearch, charset:GBK, sortType:booked}"}`.
- **Response:** sản phẩm ở `data.data.OFFER.items[].data` → `offerId`, `title` (có thẻ `<font>` bọc
  từ khoá, strip đi), `priceInfo.price` (￥, đã là tệ), `offerPicUrl` (ảnh cbu01.alicdn.com),
  `loginId` (xưởng), `province`/`city`, `bookedCount` (bán — **hay = "0" khi ẩn danh** → `monthly`
  có thể null), `sameDesignUrl` (search cùng mẫu — hữu ích cho image→1688 sau này).
- **Code:** `background.js::search1688(keyword,count)` navigate tab `ali1688TabId` tới origin h5api rồi
  `executeScript(world:'MAIN')` bootstrap+ký+fetch (md5 inline) + `results.js::fetch1688` (`RS_1688`,
  gửi `{keyword,count}`). PLATFORMS.ali1688 active, `regions:[]`, currency CNY. manifest `https://*.1688.com/*`.
- **Rủi ro ban:** ẩn danh (không cookie tài khoản) → **không đặt tài khoản nhân viên vào rủi ro**.
  Rủi ro còn lại chỉ là rate-limit/limit-flow theo IP → ret khác `SUCCESS` thì `blocked=true`, báo thử lại.
- **Bổ sung fields (2026-08-11) — LẤY ĐƯỢC ĐỦ nhờ đổi `sortType`:** sort `booked` trả `bookedCount`
  **toàn "0"**; đổi sang **`sortType: "va_rmdarkgmv30rt"`** (GMV 30 ngày) thì LỘ số bán thật (đo:
  bookedCount 436/864/417…, và `afterPrice.text` = "已售10万+件"/"已售1.9万+件"). Map:
  - **BÁN/THÁNG** = `bookedCount` (thành giao ~30 ngày, parseInt).
  - **TỔNG BÁN** = `afterPrice.text` "已售X万+件" → số (万 = ×10000).
  - **RATING** = `shopAddition.tradeService.compositeNewScore` (điểm shop 0-5, như Etsy).
  - **回头率** = `afterTags.text` (matKey `return_rate`, vd "60%") — tín hiệu cầu phụ, hiện ở dòng scoreSub.
  - **Link Tương tự** = `sameDesignUrl` (tìm cùng mẫu).
  `score()` 1688: rating-không-ratingCount → tin luôn (trust=1); repurchase làm demand fallback. GIẢM: 1688 sỉ
  không công khai. Các field trên cùng tồn tại dưới `va_rmdarkgmv30rt` (đã verify 6 item). Field số bán chia
  AB-bucket nên đọc phòng thủ (bookedCount rỗng thì rơi về afterPrice).

### 4.2b Taobao — ⚠️ CÙNG mtop nhưng BỊ BAXIA CHẶN (đo 2026-08-11)
- Endpoint: `h5api.m.taobao.com/h5/mtop.taobao.wsearch.h5search/1.0/`, appKey `12574478`, **cùng cách ký
  md5(token&t&appKey&data)** như 1688.
- **Đo thật (browser sandbox, chưa login, IP datacenter):** trả `RGV587_ERROR::SM::...被挤爆啦` +
  redirect `login.taobao.com`, **KHÔNG mint được `_m_h5_tk`** dù đã có cookie `x5secdata`/`tfstk`/`cna`.
  Đây là tường chống bot **Baxia** của Taobao — gắt hơn 1688 nhiều (1688 mint token + trả SP ẩn danh ngay).
- **Nghiên cứu GitHub (2026-08-11) — KHẢ THI qua Cách A:** Baxia chặn theo **IP + context**, không chỉ theo
  request. Datacenter IP → deny thẳng (`cloud_ip_bl`, không có captcha để giải). **Tab Chrome user thật đã
  login = IP nhà (residential) + session đã pass Baxia + có sẵn cookie `x5sec`/`_m_h5_tk`** → qua được. Đây
  đúng lý do sandbox (datacenter, logged-out) bị chặn còn máy nhân viên thì không.
- **Cách wire (khuyến nghị): "ký sinh" — KHÔNG tự tính sign.** Hook `XMLHttpRequest`/`fetch` trong tab
  `s.taobao.com` (world MAIN) để **bắt chính response `h5search` mà trang tự gọi** (trang đã lo `_m_h5_tk`,
  sign, `x5sec`, `cookie2`) → chỉ đọc JSON. Không repo nào tự giải `x5sec` slider — khi Baxia thách thức thì
  **user kéo slider 1 lần** (cookie x5sec sống vài giờ). Số bán ("已售"/月销) nằm ngay trong h5search.
- **Repo tham khảo:** [xzh0723/Taobao](https://github.com/xzh0723/Taobao) (56★, sign qua execjs),
  [JeremyDong22/taobao_mcp](https://github.com/JeremyDong22/taobao_mcp) (14★, Playwright session login),
  [ihmily/1688-Decryptor](https://github.com/ihmily/1688-Decryptor) (85★, **`sign.js` md5 thuần JS — port thẳng
  vào extension, dùng chung cho 1688/taobao/tmall vì cùng appKey 12574478**). Response `h5search` path chưa repo
  nào public 1 success mẫu hiện đại → dùng cách hook (log JSON thật rồi map). Việc cần: user chạy search trong
  Chrome đã login Taobao, F12 → Network → chép Response của `h5search` cho mình để map field chuẩn.

### 4.3 Temu — ⛔ login-gate CỨNG (đo lại 2026-08-11) → đi API trả phí
- **Đo thật:** `www.temu.com/search_result.html?search_key=...` **redirect thẳng sang `www.temu.com/login.html`**
  (title "Temu | Login") khi chưa đăng nhập. Search **bắt buộc login** + chống bot `anti-content`. Không Cách A free.
- **Nghiên cứu GitHub (2026-08-11) — CÓ hướng free qua Cách A (nhưng phải "ký sinh anti-content"):** KHÔNG
  repo nào tự sinh được `anti-content` của Temu (Temu xoay thuật toán liên tục). Cách chạy được duy nhất =
  chạy trong **tab đã login để chính JS Temu ký giúp**. Endpoint search: **`POST www.temu.com/api/poppy/v1/search`**
  (body có `search_key`…). Field: `title`, `priceInfo.priceStr` "$290.09", `image.url`, `salesNum`, `comment.goodsScore`.
- **Cách wire:** content script world MAIN hook `XMLHttpRequest` (repo mẫu [Closery/temu-global-products-only](https://github.com/Closery/temu-global-products-only)
  làm đúng vậy) → bắt/replay `anti-content` từ request trang tự gửi (TTL ngắn), HOẶC gọi lại hàm sinh token
  trong webpack runtime. Chắc ăn nhất: **bị động** — mở tab `?search_key=`, để trang tự bắn request, extension
  bắt response. Cần login + throttle (bảo vệ tài khoản). Độ bền TB-thấp, cần bảo trì.
- **Fallback trả phí rẻ nhất (đo 2026):** [Apify `piotrv1001/temu-listings-scraper`](https://apify.com/piotrv1001/temu-listings-scraper)
  **~$1.2/1.000 SP** (PAYG, free credit) > Bright Data $1.5/1K (có 5K free/tháng).
- **KẾT LUẬN NHÓM SÀN TRUNG (sau nghiên cứu):** cả 3 đều **khả thi free qua Cách A** (tab user đã login), khác
  nhau về độ khó & bảo trì: **1688** = dễ nhất (ẩn danh, mtop ổn định, đã xong đủ field). **Taobao** = mtop nhưng
  cần login + đôi khi kéo slider x5sec (hook response). **Temu** = khác cơ chế (PDD), phải ký sinh anti-content
  (hook `/api/poppy/v1/search`), mong manh nhất → nên có fallback Apify $1.2/1K. Kiến trúc chung: **hook
  XHR/fetch world MAIN trong tab đã login** dùng được cho cả taobao lẫn temu.

### 4.4b Tab "Tìm bằng ảnh" — ⏳ UI XONG, chưa wire nguồn (2026-08-04)
- **UI đã dựng** (`results.html` tab thứ 3 + `results.js`): upload/kéo-thả/dán (Ctrl+V) ảnh + preview,
  dùng chung `selectedPlatforms`/`selectedRegions` (chọn ở tab Sản phẩm), bảng kết quả **xếp theo GIÁ
  rẻ nhất** (`renderImage`/`imageResearch`). Mục tiêu: 1 ảnh → tìm cùng SP trên các sàn → nguồn rẻ nhất.
- **Dispatcher `imageSearchFor(pf, region, imgDataURL)` HIỆN LÀ STUB** — trả notice "chưa wire". Wire
  từng sàn ở đây (giống `fetchFor`).
- **Cách wire (2 kiến trúc):**
  - *Free per-sàn (Cách A):* bắt API **upload ảnh + search-by-image** từng sàn rồi replay in-tab.
    Shopee làm được (có account); 1688/Taobao cần login. Upload thường bị ký → khó hơn keyword.
  - *Trả phí, phủ MỌI web:* **Google Lens (SerpApi/ScrapingDog)** hoặc **TMAPI 拍立淘** (1688/Taobao).
    Input là URL ảnh → cần **host ảnh tạm** (R2/S3) lấy URL công khai. Đây là cách đúng cho "tất cả sàn".
- User muốn "tất cả sàn" → thực tế chỉ Google Lens/TMAPI mới phủ hết; native per-sàn là từng mảnh.

### 4.4 Image search → 1688 (MỤC TIÊU CUỐI — giá trị nhất)
- Chụp/upload ảnh sản phẩm → **search ảnh** ra xưởng Trung cùng mẫu + **giá vốn thật** (giá sỉ).
- TMAPI có `search-items-by-image-url` (拍立淘). Input là **URL ảnh** → cần **host tạm ảnh**
  (R2/S3) để lấy URL công khai. Cache theo hash ảnh.
- Phương Tây: Google Lens (SerpApi/ScrapingDog). Đây mới là "giá vốn thật", khác giá đối thủ Shopee.

### 4.5 Cache bền vững (đòn giảm chi phí #1 ở volume cao)
- `backend/lib/core/cache.py` hiện **in-memory, mất khi restart**. Nâng lên SQLite/Redis + TTL
  2 tầng (listing dài, media URL ngắn) + chuẩn hoá keyword (gộp biến thể dấu/hoa-thường).
- Kiêm luôn nhiệm vụ **snapshot-on-view** để dựng biểu đồ trend theo thời gian (xem 5.4).

### 4.6 Wiring / paywall
- Wiring Etsy/FB vào tool extension đã xong (gọi localhost:8000). Khi **deploy** phải đổi
  `BACKEND` const trong results.js + host_permissions + `content_scripts.matches` sang domain thật.
- **Paywall theo COGS:** free tier chỉ mở sàn $0 (Shopee/Amazon extension + Etsy); sàn API đắt +
  image search sau gói Pro (gói Pro phải cao hơn chi phí API của user đó).

---

## 5. CẦN CẢI THIỆN

1. **Rate-limit / jitter per-account** cho Cách A (Shopee) khi volume cao — giảm rủi ro ban.
   `background.js` đã giãn nhẹ nhưng chưa có trần/account/ngày.
2. ✅ **(Đã xử lý 2026-08-04) Region badge nhầm ngữ cảnh:** region giờ chọn theo TỪNG sàn (key
   `pf:CODE`), vẽ gom nhóm theo sàn trong hộp cuộn, ghi rõ tên nước đầy đủ + mã; badge đăng nhập
   chỉ hiện ở nhóm Shopee. Cột "Từ khoá" trong bảng đã bỏ (nhiễu); cột "Sàn" ghi thêm mã nước.
3. **Điểm FB trong tool** dùng nhãn "cầu/chất" (product) cho ads score — hơi lệch nghĩa. Tab
   Content đã tách phần lớn; có thể đổi nhãn cho FB.
4. **Biểu đồ trend theo tháng/năm:** KHÔNG có sẵn từ sàn (public API chỉ snapshot). 3 cách:
   ① đà từ 1 snapshot (ctime + monthly/historical) — free, ngay; ② snapshot-on-view tích luỹ
   (free, chờ); ③ provider có history (Kalodata…) — trả phí, ngay. Chưa làm cái nào.
5. **Giá vốn Shopee** (find_similar) — cần navigate+intercept hoặc bỏ theo hướng ảnh→1688.
6. **CPU máy user:** Cách A đổ tải về client. Nếu muốn nhẹ hơn, đẩy parse Amazon/score sang
   backend (extension chỉ fetch raw) — đánh đổi CPU server (rẻ) lấy máy user mượt.

---

## 6. FILES QUAN TRỌNG

### Backend (`backend/`)
- `lib/ads/platform.py` — hợp đồng AdPlatform (đọc trước khi thêm sàn).
- `lib/ads/platforms/__init__.py` — SỔ ĐĂNG KÝ (thêm sàn = 1 file + 1 dòng).
- `lib/ads/platforms/shopee.py` (Cách A) · `etsy.py` (API) · `facebook.py` (Playwright) · `tiktok.py`.
- `lib/ads/search.py` — điều phối 2 pha, cache key.
- `lib/ads/scoring.py` — chấm điểm (product + ad).
- `lib/ads/types.py` — Ad/AdScore/ClientJob…
- `app/api/ads.py` — routes (search, ingest, health, filters).
- `app/api/media.py` — proxy media (allowlist host từ MediaPolicy từng sàn).
- `lib/core/config.py` — nạp .env.local/.env, env_string/env_number.
- `lib/core/cache.py` — cache in-memory (cần nâng cấp).

### Extension (`extension/`) — MV3
- `results.html` + `results.js` — TRANG RESEARCH CHÍNH (2 tab). File JS lớn nhất, chứa: PLATFORMS
  config, fetchKeyword (Shopee), fetchAmazon, fetchBackend (Etsy/FB), score() (phản chiếu backend),
  render bảng + content, region/login, tab switching.
- `background.js` — service worker: fetchInTab (Shopee same-origin), amazonSearch (tab-scrape),
  findSimilar/costBatch (giá vốn — dead), directFetch cũ (đã bỏ).
- `popup.html` + `popup.js` — popup tự test Shopee + nút mở trang research.
- `content.js` — cầu nối cho frontend production (chưa dùng ở tool).
- `similar-hook.js` — hook find_similar (dead, cho giá vốn).
- `manifest.json` — permissions + host_permissions.
- `README.md` — hướng dẫn cài + test.

### Frontend production (`frontend/`) — Next.js (KHÁC tool extension)
- `components/ads/AdsResearch.tsx` — màn research (đã wiring pending→ingest cho Cách A).
- `components/ads/AdCard.tsx` — thẻ (hiện price/soldCount + creative player cho FB).
- `lib/ads/extension.ts` — bridge client (extensionAvailable/runClientJobs).
- FB Ads dùng ở ĐÂY là "chạy ngon" (thẻ quảng cáo đầy đủ), không phải ở tool extension.

### Docs
- `docs/nghien-cuu-nguon-du-lieu.md` — research nguồn/giá provider (đọc để hiểu bối cảnh sàn).
- `docs/ban-giao.md` — file này.

---

## 7. CÁCH CHẠY

### Backend (cần cho Etsy + Facebook trong tool, và cả frontend production)
```
cd backend
# deps đã cài sẵn (uvicorn/fastapi/playwright/httpx/dotenv). Nếu máy mới: pip install -r requirements.txt
# FB/TikTok cần chromium: playwright install chromium
uvicorn app.main:app --port 8000
```
CORS đã mở (`allow_origin_regex=".*"`, GET) — extension gọi được.

### Extension (Shopee/Amazon client-side)
1. `chrome://extensions` → Developer mode → Load unpacked → thư mục `extension/`.
2. Popup → "📊 Mở trang research đầy đủ".
3. Shopee: cần tab shopee.<region> đã đăng nhập (badge ✓). Amazon: không cần login.

### Frontend production (Next.js)
Xem `frontend/next.config.mjs` (rewrite /api/* về backend 8000).

---

## 8. SECRETS / .env.local

`backend/.env.local` (đã gitignore, KHÔNG commit):
```
ETSY_KEYSTRING=70n04y8v8p5wpkoptoiiiwm9
ETSY_SHARED_SECRET=bwh2vfe2vw
# FB_COOKIE="c_user=...; xs=..."   # tuỳ chọn, ổn định hơn khi search nhiều
# TIKTOK_COOKIE="sessionid=..."     # cho tiktok Creative Center (ads-spy cũ)
```
⚠️ **Etsy shared secret đã lộ trong chat lịch sử → NÊN REGENERATE** trên Etsy dashboard rồi cập
nhật lại .env.local.

---

## 9. SỰ THẬT ĐO ĐƯỢC (gotchas — đừng dò lại)

- **Shopee search từ server = 403** (`{"is_login":false}`). Chỉ session đăng nhập qua được. Fetch
  phải **same-origin trong tab** (executeScript world:MAIN) — service worker cross-origin bị 403.
- **Shopee bỏ `item_basic`** (2026) → dùng `item_card_displayed_asset` + `item_data`.
- **Shopee PH/mọi region = cùng API** VN, chỉ khác domain. Cần login đúng region.
- **Amazon search từ server = 200 + data thật** (85 sản phẩm, không login). NHƯNG fetch trần từ
  extension service worker = **captcha** → phải điều hướng tab.
- **Amazon số review** ở `alf-customer-ratings-count-component` → aria-label (số đầy đủ). Strip số
  = region-agnostic.
- **Etsy**: site chặn scrape (403+captcha) → phải API; API cần `keystring:shared_secret`; search
  không trả ảnh (cần batch); không có sold/rating theo listing (dùng favorites + shop rating).
- **Taobao/1688 = login-gate** từ server → đi API.
- **FB Ad Library** = chỉ quảng cáo (không sản phẩm/giá/số bán); khớp lỏng theo ad copy → cần lọc
  từ khoá phía mình.
- **recommend_post (Shopee find_similar) cần chữ ký** `x-sap-sec`+`device_sz_fingerprint`, replay
  403 → navigate+intercept mới lấy được.

---

## 10. QUYẾT ĐỊNH KIẾN TRÚC (đã chốt, đừng lật lại nếu không có lý do)

1. **Cách A (extension client-fetch)** cho sàn login-wall — không "Cách B" (gửi cookie user về
   server: ban tài khoản user do IP lệch + lỗ hổng bảo mật).
2. **Không server-scrape farm + proxy** ở quy mô 100–200 user (đắt nhất, chậm nhất, dễ ban nhất).
3. **Cookie user không rời trình duyệt** — server chỉ dựng lệnh (build_request).
4. **Sàn cần secret (Etsy) / server-scrape (FB) ở BACKEND**, không nhét vào extension.
5. **FB = ad-spy ở tab Content riêng**, không trộn bảng product.
6. **Chi phí thực (verified 2026):** full setup ~$155–170/tháng (Amazon ScrapingDog $40 nếu không
   tự scrape, Elim sàn Trung $40–60, Google Lens $40, VPS $15); Shopee/Amazon/FB/Etsy phần lớn $0.
   Tier phẳng, không nổ theo volume.

---

## 11. GỢI Ý VIỆC TIẾP THEO (ưu tiên)

1. ✅ **Đã xong: 2 bug đang dở** (3.1 tên tràn cột, 3.2 Amazon thiếu giá). Đợt dọn 2026-08-04 cũng
   tối ưu `results.js`: `render()` gán innerHTML một lần (bớt reflow khi bảng dài), `research()`
   chạy các SÀN song song nhưng job trong 1 sàn vẫn tuần tự (giữ nhịp chống ban Shopee + tab nền
   Amazon). Chưa động: cache SQLite (4.5), dead code giá vốn/find_similar (3.3 — giữ nguyên theo ý user).
2. **TikTok Shop qua Seller Center** — user có account PH sẵn; cần bắt API (F12→Network trong
   seller.tiktok.com, Copy as cURL) rồi viết adapter (giống cách đã làm Shopee).
3. **Cache bền vững (SQLite)** — đòn giảm chi phí lớn nhất khi có traffic.
4. **Image → 1688 (TMAPI)** — mục tiêu cuối, giá trị nhất (giá vốn thật + content theo ảnh).
5. **Sàn Trung + Temu (API)** khi có quote/key.
