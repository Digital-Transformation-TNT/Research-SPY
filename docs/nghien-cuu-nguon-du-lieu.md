# Research-SPY — Nghiên cứu nguồn dữ liệu cho product search đa sàn

> Tài liệu tổng hợp phần research: chọn nhà cung cấp (provider) rẻ + uy tín để search sản phẩm
> theo từ khoá / theo ảnh, trả về ảnh + video theo từng sàn. Giá là mức đo được năm 2026 —
> **phải xác minh lại trên trang giá + free trial trước khi cam kết trả tiền.**

---

## 0. Bối cảnh & mục tiêu

- Mở rộng Research-SPY từ **ads-spy** (Facebook/TikTok) sang **product search đa sàn**:
  Amazon, Etsy, Shopee, TikTok Shop, 1688/Taobao/Tmall, Temu.
- Chức năng: nhập **từ khoá** (hoặc **ảnh**) → trả về listing sản phẩm kèm **ảnh + video** theo từng sàn.
- Mục tiêu của research: tìm nguồn **rẻ hơn + uy tín/chất lượng hơn** so với bản kế hoạch gốc
  (Rainforest / Elim / Apify / Piloterr).

---

## 1. Ba điều cần chỉnh trong kế hoạch gốc

1. **"Ảnh + video theo từ khoá" thực chất là 2 lần gọi API.**
   Ảnh (thumbnail) có ngay trong kết quả `search`; **URL video chỉ nằm ở endpoint chi tiết
   sản phẩm** (theo id/ASIN) và thường tốn thêm credit.
   → Kiến trúc đúng: `search` (ảnh + id) → `product_detail` (video) **chỉ cho sản phẩm user bấm vào**.
   Đừng gọi detail cho cả trang — đội chi phí 20–30×.

2. **Giá Rainforest thực tế cao hơn ước tính.** Sàn thật ~**$66–83/tháng cho 10.000 credit**
   (không phải ~$50/5.000 req), và credit ≠ request (tham số ảnh/video ăn 2–3× credit).

3. **Không nhà cung cấp nào phủ tốt cả phương Tây lẫn Trung Quốc.**
   Bright Data / Oxylabs phủ Amazon + Temu + Shopee + TikTok Shop **nhưng KHÔNG phủ
   1688/Taobao/Tmall**. Sàn Trung phải dùng nhà chuyên Trung (TMAPI/Elim/Onebound).
   → Gom về **2 nhà cung cấp + 1 API chính thức**, thay vì 5 nhà.

---

## 2. Nguồn tốt hơn theo từng sàn (giá thực 2026)

### Amazon — rẻ hơn & uy tín hơn Rainforest
| Nhà cung cấp | Giá thực @5.000 req/tháng | Ghi chú |
|---|---|---|
| **ScrapingDog (Lite)** ⭐ | **$40/tháng**, dư nhiều credit | Rẻ nhất trong nhóm uy tín, REST đơn giản |
| **Canopy API (PAYG)** | ~$49 ($0.01/req, không cam kết) | Thay Rainforest sạch nhất, có media qua GraphQL |
| **DataForSEO** | ~$10 ($0.002/SERP) | Rẻ nhất tuyệt đối, nhưng API async/task, code khó hơn |
| **Oxylabs** | $75 (sàn tối thiểu) | Uy tín nhất, phủ US/UK/EU/JP tốt nhất |
| Bright Data | **5.000 record/tháng MIỄN PHÍ** | Thử miễn phí phủ trọn nhu cầu hiện tại |

**Chọn:** ScrapingDog $40 hoặc Canopy ~$49. Muốn rẻ nhất & chịu code khó: DataForSEO ~$10.

### 1688 / Taobao / Tmall — rẻ hơn Elim/Tmapi
| Nhà cung cấp | Giá | Ghi chú |
|---|---|---|
| **RapidAPI "Taobao 1688 API" (seller VN)** | **$35/25.000 req = $1,40/1.000** | Rẻ nhất, phủ cả 3 sàn. **Nhược:** service level 79%, latency 2,6s, vận hành cá nhân → test kỹ |
| **TMAPI (tmapi.top)** ⭐ | Phải xin báo giá | Chất lượng tốt nhất: đã xác minh keyword search + ảnh + `video_url` trên cả 3 sàn, docs xuất sắc, **có search bằng ảnh** |
| **Elim.asia** | $40/10k · $60/20k · $120/50k | Uy tín nhất cho VN (đối tác chính thức, giá minh bạch, hỗ trợ tiếng Việt) |
| Onebound / OTCommerce | $1/1.000 ở scale | Enterprise nhưng **sàn tối thiểu $150/tháng** → loại ở volume thấp |

**Chọn:** Xin quote TMAPI (feature tốt nhất) + giữ Elim làm dự phòng ổn định.

### Shopee + TikTok Shop — không nhà nào phủ tốt cả hai
**Loại ngay:** Unwrangle (Shopee chưa live), EnsembleData (không có endpoint TikTok Shop),
Kalodata/FastMoss (chỉ dashboard, không phải API search).

- **TikTok Shop (SEA + US):** **Oxylabs $49/tháng** ($0,25–0,45/1.000, rẻ nhất đáng tin)
  hoặc **SocialCrawl £15** (đã xác nhận đủ VN/TH/ID/MY/PH).
  ScrapeCreators $47/25k có docs ảnh+video tốt nhất nhưng **chưa xác nhận vùng SEA**.
- **Shopee (SEA):** **Bright Data ~$1/1.000, 5.000 record/tháng miễn phí** (ổn định nhất)
  hoặc Apify `fatihtahta` $29,99/tháng.

**Chọn gọn:** Bright Data lo cả Shopee + TikTok Shop (một nhà). Muốn rẻ hơn cho TTS: tách Oxylabs.

### Temu — rẻ hơn & ổn định hơn Piloterr
| Nhà cung cấp | Giá | Ổn định | Ghi chú |
|---|---|---|---|
| **Bright Data** ⭐ | ~$0,70–1/1.000, **5.000 free/tháng** | Cao nhất | Ổn định nhất khi Temu đổi bảo mật |
| **Oxylabs** | $0,40–0,45/1.000 (+$1,35 render JS) | Cao | Rẻ hơn Piloterr ~4× |
| Apify `crw/temu-products-scraper` | $10/1.000 | TB | **Nhà duy nhất document rõ có `video_url`** |
| Piloterr (baseline) | ~$1,88–2,72/1.000, $49/tháng | TB-Cao | Đắt hơn 2 nhà trên |

**Chọn:** Bright Data (ổn định + free tier) hoặc Oxylabs (rẻ nhất).

### Etsy — kế hoạch đúng, nhưng có bẫy phê duyệt
- **Etsy Open API v3 vẫn miễn phí 2026:** 10.000 req/ngày, 10 req/giây, keyword search qua
  `GET /v3/application/listings/active?keywords=...&includes=Images,Videos`
  → **ra cả ảnh và video trong một lần gọi.**
- ⚠️ **Bẫy:** "Seller App" duyệt tự động vài phút nhưng **chỉ query shop của chính bạn**.
  Để search toàn sàn phải dùng "Personal App" → **review thủ công, có report chờ ~13 ngày**,
  không đảm bảo được duyệt.
- **Việc cần làm:** đăng ký Personal App **sớm ngay từ đầu**; giữ Apify Etsy actor ($5/tháng
  free credit) làm dự phòng.

---

## 3. Đề xuất: gom về 2 nhà cung cấp + 1 API chính thức

| Nhóm sàn | Nguồn | Chi phí ước tính |
|---|---|---|
| Amazon, Temu, Shopee, TikTok Shop | **Bright Data** (~$1/1.000, 5.000 free/sàn/tháng) | ~$30–50/tháng khi có traffic |
| 1688, Taobao, Tmall | **TMAPI** (xin quote) hoặc **Elim** $40–60 | ~$40–60/tháng |
| Etsy | **API chính thức** | $0 |
| Hạ tầng | VPS (Hetzner rẻ hơn DigitalOcean) | ~$5–15/tháng |

**Tổng ~$80–130/tháng (≈ 2–3,3 triệu đ)** — thấp hơn nhiều so với ước tính 5–8 triệu ban đầu,
nhờ (a) gom nhà cung cấp, (b) tier miễn phí Bright Data, (c) cache 24h đã có trong `search.py`.
Lợi ích phụ: ít nhà cung cấp = ít điểm hỏng, dễ quản lý, uy tín cao hơn.

---

## 4. Search bằng ẢNH — sàn nào có?

**Chỉ mạnh ở sàn Trung Quốc; phương Tây phải đi vòng qua Google Lens.**

### Sàn Trung (1688/Taobao/AliExpress) — search ảnh gốc, mạnh nhất
Tính năng gốc của Taobao/1688 (拍立淘). Dùng để **chụp sản phẩm → tìm xưởng bán cùng mẫu** —
điểm bán hàng mạnh cho thị trường VN.

| Provider | Endpoint search ảnh |
|---|---|
| **TMAPI** ⭐ | `1688 search items by image URL` + tool `image-URL-convert` |
| **Onebound / OTAPI** | `otapi-1688` search by image |
| **Apify** | `devcake/scraper-by-image`, `dev00/alibaba-1688-aliexpress-reverse-image-search-api` |
| Elim.asia | Chưa xác nhận — phải hỏi trực tiếp |

### Amazon / phương Tây — không có search ảnh trực tiếp
Các API Amazon (Rainforest, ScrapingDog, Canopy) **không có** endpoint tìm bằng ảnh.
Đường duy nhất là reverse image qua **Google Lens**: SerpApi (~$75/5.000 search),
SearchApi.io, ScrapeBadger. Phủ rộng web/thương hiệu nhưng không lặn sâu vào một sàn cụ thể.

### Hai điều kỹ thuật phải biết
1. **Input là URL ảnh, không phải upload file.** Luồng thật: user upload → **host tạm ảnh**
   (S3/R2/VPS) lấy URL công khai → gửi URL cho API. TMAPI có sẵn `image-URL-convert`.
2. **Tốn credit như request thường** (đôi khi hơn) → nên cache theo hash ảnh.

---

## 5. Phân tích Kalodata (để định hình mô hình kinh doanh)

### Cách Kalodata lấy data
- **Scrape dữ liệu công khai** của TikTok/TikTok Shop (listing, lượt xem, tương tác, "đã bán"),
  rồi **dùng AI ước lượng** GMV/doanh số/ad spend (những số TikTok không công khai).
- **Không dùng official API, không phải TikTok Shop Partner chính thức.** Chính Kalodata
  khuyến cáo không dùng cho việc cần chính xác cao (quyết toán hoa hồng, đánh giá hiệu suất).
- Lý do cấu trúc: **official API của TikTok Shop chỉ trả data shop của chính bạn** → muốn quét
  toàn thị trường/đối thủ thì *bắt buộc* phải scrape. (Đối chiếu: Kixmon là Partner chính thức,
  có API thật nhưng chỉ trong phạm vi được cấp quyền.)
- **Lưu ý nguồn:** khẳng định "scrape + ước lượng" mạnh nhất đến từ Kixmon (đối thủ, có động cơ).
  Phần Kalodata tự xác nhận chỉ là: thu từ "public channels", "AI models", "số có thể lệch nhẹ".

### Có phải scrape realtime hàng ngày?
- **Không realtime.** Data Kalodata là "periodic, not real-time": chạy **crawl hàng loạt theo
  lịch** trên hàng triệu sản phẩm → **lưu DB riêng** → dashboard đọc từ DB. Không scrape mỗi lần
  user bấm.
- Quy mô: hạ tầng crawl khổng lồ chạy liên tục + proxy residential + pipeline AI → là **cả một
  công ty**, không phải một tính năng.

### Mô hình kinh doanh Kalodata
- **Là SaaS/dashboard bán cho người dùng cuối**, KHÔNG phải data provider kiểu Bright Data.
  Nó ngồi *trên* tầng data, bán **quyền truy cập theo gói thuê bao**.
- Giá 2026: Starter **$45,90/tháng**, Professional **$99/tháng**, Enterprise custom
  (mới có "full API access").
- **Nguồn thu chính = subscription theo tầng** (freemium → paywall phần giá trị nhất:
  lọc sâu, lịch sử 500 ngày, export, GMV chi tiết). Biên lãi = giá thuê bao − (crawl + proxy + AI).

### Ý nghĩa cho Research-SPY
- Web của bạn đứng **cùng tầng Kalodata** (sản phẩm cho end-user), bên dưới *mua* data từ tầng
  provider. Bạn **nhẹ hơn Kalodata nhiều**:
  - Crawl **on-demand** (chỉ khi user bấm search) thay vì nuôi crawler 24/7 — provider gánh hộ.
  - **Không cần** phần khó & kém chính xác nhất của Kalodata là *ước lượng GMV/doanh số*.
    Bạn chỉ cần listing/ảnh/video/giá (đều công khai, scrape ổn định).
- Công thức kinh doanh: **Doanh thu** = gói thuê bao (Free/Pro/VIP) + **affiliate** (hoa hồng
  link sản phẩm, bù chi phí API). **COGS** = tiền API/request (đã có cache 24h kéo xuống).
  **Chìa khoá lãi:** để sàn/region đắt sau paywall; free tier chỉ mở sàn rẻ (Etsy = $0) + cache mạnh.

---

## 6. Khớp với kiến trúc hiện có (`AdPlatform`)

Hợp đồng `AdPlatform` (xem `backend/lib/ads/platform.py`) gần như dùng được ngay cho product search.
Mỗi sàn mới = **một file + một dòng** trong `platforms/__init__.py`. Chỉ cần điều chỉnh nhỏ:

1. Thêm field **`price`** (và `currency`, `sold_count`) vào model `Ad`/`Product`.
   Model `Creative(kind="video"|"image", url, poster_url)` hiện tại dùng lại nguyên vẹn cho ảnh/video.
2. **Video = lazy load:** `search()` trả `Creative(kind="image")`; chỉ khi mở chi tiết mới gọi
   lấy video (khớp mô hình "2 lần gọi", bảo vệ ngân sách).
3. **`MediaPolicy.host_suffixes`** phải khai host CDN từng sàn (giống đã làm cho `tiktokcdn.com`)
   để `/api/media` proxy được ảnh/video mà không thành open proxy.
4. Cho search ảnh: thêm `capabilities.image_search: bool` để UI biết sàn nào bật nút "tìm bằng ảnh";
   `search()` nhận thêm `image_url` thay cho `keyword`.

**Khác biệt so với TikTok/Facebook hiện tại:** hai nguồn đó tự scrape bằng Playwright (miễn phí,
mong manh); các sàn e-commerce này gọi API trả phí (ổn định, tốn tiền) → `capabilities.keyword_search`
luôn `True`, không phụ thuộc cookie như TikTok.

---

## 7. Việc cần làm trong tuần đầu (trước khi trả tiền)

- [ ] **Đăng ký Etsy Personal App ngay** (review lâu nhất) + xin quote TMAPI.
- [ ] Free trial để **xác minh có `video_url`**: Bright Data (Temu/Shopee/TikTok Shop),
      TMAPI (Taobao/Tmall). Docs public xác nhận ảnh nhưng **chưa xác nhận video** → test tận tay.
- [ ] Xác nhận **vùng SEA** cho TikTok Shop (SocialCrawl đã xác nhận; ScrapeCreators chưa).
- [ ] Test service level RapidAPI VN 1688 nếu muốn tiết kiệm — 79% uptime có thể không đủ cho production.
- [ ] (Nếu làm search ảnh) chuẩn bị chỗ **host tạm ảnh upload** để lấy URL công khai.

---

## 8. Lộ trình triển khai (giữ như plan gốc, chỉnh nguồn)

- **GĐ 1:** Etsy (official, $0) + Amazon (ScrapingDog/Canopy) — nguồn sạch, ổn định để dựng khung.
- **GĐ 2:** 1688/Taobao/Tmall (TMAPI/Elim) — nguồn hàng Trung (thị trường VN chuộng) + search ảnh.
- **GĐ 3:** Shopee/TikTok Shop SEA (Bright Data/Oxylabs).
- **GĐ 4:** Mở rộng TikTok US / Temu khi web đã có doanh thu.

---

## Nguồn tham khảo chính
- Amazon: trajectdata.com (Rainforest), canopyapi.co, scrapingdog.com/pricing, dataforseo.com, oxylabs.io, brightdata.com
- China: elim.asia, tmapi.top/docs, rapidapi.com (chuyenhangsieutocvn), otcommerce.com, open.onebound.cn
- Shopee/TTS: oxylabs.io, socialcrawl.dev, scrapecreators.com, brightdata.com, apify.com
- Temu: piloterr.com, oxylabs.io/products/scraper-api/ecommerce/temu, brightdata.com, apify.com/crw/temu-products-scraper
- Etsy: developer.etsy.com (rate-limits, authentication)
- Kalodata: kixmon.com/blog/kalodata-vs-kixmon, kalodata.com, simptok.com/how-much-is-kalodata
- Search ảnh: tmapi.top/docs/ali/search/search-items-by-image-url, serpapi.com/google-lens-api

> ⚠️ Mọi con số giá là mức đo 2026 từ trang giá/blog nhà cung cấp — **xác minh lại trên trang chính
> thức + free trial trước khi cam kết**, đặc biệt: có `video_url` không, vùng SEA, và bội số credit.
