# Danh mục nguồn "ẢNH sản phẩm → VIDEO liên quan" (research 2025–2026)

Mục tiêu: từ 1 ảnh sản phẩm → gom **nhiều video liên quan** (video quảng cáo TikTok/Douyin, review…) đa sàn để làm tư liệu dựng lại.

## 2 sự thật quyết định kiến trúc

1. **Không tồn tại API "ảnh vào → video ra" trực tiếp.** TikTok/Douyin có visual-search in-app nhưng **không mở API**. Mọi giải pháp thực tế = **2 bước**: ① nhận diện từ ảnh → ② lấy video.
2. **Cách A (in-tab session) là chìa khoá** vượt sign/anti-bot của các sàn (Shopee/Lazada/Temu/Douyin/Taobao). Đây là thế mạnh sẵn có của extension.

## Bản đồ pipeline

```
ẢNH ─① NHẬN DIỆN─▶ keyword / product-id / link ─② GOM VIDEO─▶ ─③ TẢI─▶ ─④ XẾP HẠNG (CLIP)─▶ nhiều video
```

---

## ① NHẬN DIỆN TỪ ẢNH

### A. Reverse-image web mở (ra cả video ngoài sàn)

| Nguồn | Ảnh→Video | Truy cập | Giá | Ghi chú |
|---|---|---|---|---|
| **Google Lens (SerpApi)** | ✅ field `short_videos` (TikTok/YT Shorts/IG/FB) + `visual_matches` | API JSON | Free 250/th; ~$0.009/search | **Tốt nhất** — nguồn duy nhất trả video có cấu trúc. [google-lens-api](https://serpapi.com/google-lens-api) |
| Google Lens (in-tab) | ✅ | Playwright/extension | Free (rủi ro CAPTCHA) | Khớp Cách A |
| **Yandex Images** | ⚠️ lọc domain video từ kết quả ảnh | SerpApi / in-tab | SerpApi hoặc free | **Mạnh nhất nhận diện hàng TQ/no-brand** |
| Baidu 识图 | ⚠️ | scrape / searchapi.io | — | Tốt cho hàng TQ (Taobao/1688) |
| SearchApi.io / Bright Data / Oxylabs / Apify (Google Lens) | ✅ | API | rẻ hơn SerpApi vài tier | Đối thủ SerpApi |
| ~~Bing Visual Search~~ | ❌ | — | — | **Khai tử 11/08/2025** |
| ~~TinEye~~ | ❌ chỉ exact-copy | — | — | Không hợp |

### B. Image-search GỐC của sàn (image → đúng product-id)

| Sàn | Anonymous? | Endpoint / cách | Video từ product-id | GitHub/API |
|---|---|---|---|---|
| **Alibaba.com** | ✅ dễ nhất (đã verify) | ossUpload → `alibaba.com/picture/search.htm?imageAddress=` | detail có video | [Carmenliukang/image_search_products](https://github.com/Carmenliukang/image_search_products) |
| **1688** | cần `_m_h5_tk`+sign | `mtop.1688.imageService.putImage` → `s.1688.com/youyuan?tab=imageSearch&imageId=` | detail `mainVideo.videoUrl` | [Carmenliukang/1688_crawler](https://github.com/Carmenliukang/1688_crawler-image_search_products) (197★) |
| **Taobao/Tmall (Pailitao)** | cần sign | mtop `h5api.m.taobao.com` putImage | `mtop.taobao.detail.getdetail`→videoUrl | dùng chung sign repo trên |
| **Shopee** | in-tab session | `api/v4/search/search_by_image` (camera) | ✅ `api/v4/item/get`→`video_info_list` | Cách A |
| **Lazada** | mtop sign / in-tab | `acs-m.lazada.{tld}/h5/mtop.lazada.search.*` | ✅ PDP `video`/`skuVideo` | hệ Alibaba sign |
| **Temu** | `anti_content` khó → in-tab | `temu.com/api/poppy/v1/search` | ✅ goods detail video | in-tab |
| **Amazon** | ❌ không official | dùng Google Lens lọc amazon | ✅ scrape page video | SerpApi |
| **Pinterest Lens** | cần session/CSRF | Flashlight `visual_search/flashlight` | ✅✅ **trả sẵn video pin** `videos.video_list` | [bstoilov/py3-pinterest](https://github.com/bstoilov/py3-pinterest) |
| **Douyin/Kuaishou store** | sign nặng → in-tab | ec API + X-Bogus/a_bogus | ✅✅ **product→aweme mp4** | [Evil0ctal API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) |

**3rd-party image-search hàng TQ:** [Onebound `item_search_img`](https://www.onebound.net/), [RapidAPI Taobao Image Search](https://rapidapi.com/jaysbum/api/taobao-image-search2) (freemium ~$10–50/th).

> Hầu hết image-search sàn chỉ trả **product-id, KHÔNG kèm video** → cần bước 2 gọi detail API lấy video. Ngoại lệ: **Pinterest** (video pin sẵn) và **Douyin/Kuaishou** (vốn là video).

### C. Ad-spy có input bằng ẢNH (thương mại — trả thẳng video quảng cáo)

| Tool | Ảnh→? | Phủ | Giá/th | API |
|---|---|---|---|---|
| **PiPiADS** | ✅ upload ảnh → TikTok ad + Shop | TikTok (chính) + FB | $49–$900 | ✅ gói Enterprise |
| **Minea** | ✅ reverse-image từ ảnh SP | FB + TikTok + Pinterest | $49–$399 | ❌ |
| Kalodata / BigSpy / Foreplay / Dropispy / AdSpy | ❌ chỉ keyword | tuỳ tool | $9–$458 | phần lớn ❌ |

Chỉ **PiPiADS** và **Minea** nhận ẢNH. PiPiADS mạnh video ad TikTok, tải HD.

---

## ② GOM VIDEO (từ keyword/product-id/link)

### Ad libraries (video quảng cáo)
- **TikTok Creative Center / Top Ads** — không API chính thức. Scraper: [lofe-w/tiktok-creative-center-scraper](https://github.com/lofe-w/tiktok-creative-center-scraper-public), [Apify codebyte](https://apify.com/codebyte/tiktok-creative-center-top-ads/api). Creative không watermark.
- **Meta Ad Library API** — `graph.facebook.com/.../ads_archive`, `media_type=VIDEO`. **Giới hạn: ads thương mại chỉ trả nếu chạy tại EU/UK (DSA), ~1 năm**; political thì toàn cầu 7 năm. Quota 200 call/h. Tải creative: [Swipekit](https://swipekit.app/), [ScrapeCreators](https://scrapecreators.com/).

### Short-video theo keyword/hashtag
| Nền tảng | Công cụ tốt nhất | Chi phí | No-WM |
|---|---|---|---|
| **YouTube/Shorts** | **yt-dlp** `ytsearch50:kw` / Data API v3 (100 search/ngày) | Free | ✅ native |
| **TikTok** | [ScrapeCreators](https://scrapecreators.com/tiktok-api), [tikwm.com](https://www.tikwm.com/), [TikHub](https://tikhub.io/tiktok-api), [omkarcloud](https://github.com/omkarcloud/tiktok-scraper), [Q-Bukold](https://github.com/Q-Bukold/TikTok-Content-Scraper) | Free→$0.001+/req | ✅ |
| **Douyin** | [JoeanAmier/TikTokDownloader](https://github.com/JoeanAmier/TikTokDownloader) (search+hotboard), [Evil0ctal](https://github.com/Evil0ctal/Douyin_TikTok_Download_API), F2 | Free | ✅ |
| **Kuaishou** | Apify [stackrelay](https://apify.com/stackrelay/kuaishou-scraper)/socialdatax, Evil0ctal | pay-per-result | ✅ |
| **Instagram Reels** | Apify [data-slayer/instagram-search-reels](https://apify.com/data-slayer/instagram-search-reels) | pay-per-result | ✅ |
| **Pinterest video** | Apify [simpleapi pins-videos-search](https://apify.com/simpleapi/pinterest-pins-videos-search-scraper) | rẻ | ✅ HD |
| **Bilibili** | yt-dlp / [bilibili-mcp](https://github.com/L-Chris/bilibili-mcp) | Free | ✅ |

### Video từ product-id (sàn)
Shopee `item/get`→`video_info_list` · Lazada PDP `video` · Taobao/1688 detail `videoUrl` · Temu goods video · Amazon page video · Douyin product→aweme mp4 · Kuaishou `photo.mainMvUrls`.

---

## ③ TẢI VỀ

| Tool | Phủ | Ghi chú |
|---|---|---|
| **yt-dlp** | 1.700+ site (YouTube/TikTok/Douyin/FB/IG/X/Bilibili) | Tiêu chuẩn vàng, Python API |
| **F2** ([Johnserf-Seed/f2](https://github.com/Johnserf-Seed/f2)) | Douyin/TikTok/X/Weibo/Bilibili | **No-watermark, async, maintain tốt** — fallback Douyin khi yt-dlp lỗi |
| gallery-dl / you-get | ảnh/gallery / site TQ | bổ sung |

FFmpeg là dependency chung.

---

## ④ XẾP HẠNG theo độ liên quan với ẢNH (CLIP frame)

Cách: trích frame → CLIP encode từng frame → cosine với embedding ảnh truy vấn → rank video theo max/mean similarity.

| Thành phần | Công cụ | Ghi chú |
|---|---|---|
| **Blueprint** | [DewduSendanayake/Video-Similarity-Search](https://github.com/DewduSendanayake/Video-Similarity-Search) | Decord+CLIP ViT-B/32+FAISS. **Khớp nhất**, clone làm nền |
| Scale + API | [rom1504/clip-retrieval](https://github.com/rom1504/clip-retrieval) | inference+index+back(Flask API)+client |
| Turnkey | [marqo-ai/marqo](https://github.com/marqo-ai/marqo) | index video+ảnh+text, REST. **Đã deprecated** nhưng self-host được |
| Trích frame | **PyAV** / **PySceneDetect** (keyframe theo cảnh) | **Tránh decord** (unmaintained, crash video lớn) |
| Dedup cuối | pHash ([Sadiqush/RVSearch](https://github.com/Sadiqush/RVSearch)) | loại re-upload trùng |

> **Đã có sẵn `backend/lib/ads/clipmatch.py`** (CLIP ViT-B/32 ONNX) → chỉ cần gọi cho **nhiều frame** thay vì 1 poster là xong bước ④.

---

## KHUYẾN NGHỊ COMBO

### Combo A — Nhanh nhất, phủ rộng (KHUYÊN BẮT ĐẦU)
1. Ảnh → **Google Lens (SerpApi)** → `short_videos` + `visual_matches` → video TikTok/YT/IG/FB + tên sản phẩm ngay.
2. Song song bung tên sản phẩm sang: **yt-dlp** (YouTube/Shorts) + **Douyin** (TikTokDownloader) + **TikTok** (ScrapeCreators/tikwm).
3. **yt-dlp/F2** tải → **clipmatch (CLIP frame)** xếp hạng theo ảnh → hiển thị top-N.
- Ra ngay hàng chục video đa sàn. Chi phí: SerpApi ~$0.009/ảnh + scraper tuỳ dùng.

### Combo B — Tận dụng Cách A (miễn phí, khớp extension)
1. Ảnh → **image-search sàn in-tab** (Alibaba.com/1688/Shopee/Douyin, session user) → product-id.
2. product-id → **detail API lấy video** (Shopee `video_info_list`, Douyin aweme mp4…).
3. + **Yandex/Google Lens in-tab** bắt video ngoài sàn.
4. CLIP xếp hạng.
- Không tốn phí API; phải wire sign/anti-bot (extension đã làm tốt).

### Combo C — Video ad chất lượng cao (mua tool)
- **PiPiADS** (ảnh→TikTok ad) hoặc **Minea** → kho video ad có sẵn, tải HD. Nhanh, ít code, tốn phí tháng.

---

## Phụ lục — chi tiết sàn video TQ (actionable)

### Temu
- Image-search **chỉ trong app mobile** (web temu.com không có). Gateway thật: **`/api/poppy/v1/search`** (đã verify qua [Closery/temu-global-products-only](https://github.com/Closery/temu-global-products-only)); path `search_by_image` cụ thể **chưa verify** (cần tự capture app bằng mitmproxy+Frida).
- Rào cản = **`anti_content`** (token JS/VM obfuscated, giống X-Bogus) + riskcontrol 6+ loại CAPTCHA → khả thi nhất là **in-tab session** hoặc headless CDP + proxy + captcha-solver.
- Repo: [colindaniels/temu-api-docs](https://github.com/colindaniels/temu-api-docs) (có field `video.videoUrl`), [XIE7654/temu_api](https://github.com/XIE7654/temu_api) (Open API seller-side).
- 3rd-party (keyword/ID, **không** image): Apify [automation-lab/temu-scraper](https://apify.com/automation-lab/temu-scraper/api) (~$1.2/1k, **có video URL**), [Piloterr](https://www.piloterr.com/scrapers/temu) (1 credit/req).
- **Video**: goods detail (`temu.com/goods.html?goods_id=`) trả `video.videoUrl` (CDN `*.kwcdn.com`).

### Douyin store
- Image-search **có, trưởng thành** (pause-to-shop + screenshot 识图) nhưng **không API**. Ký: **a_bogus / X-Bogus / msToken** (web), X-Argus/Gorgon (app). Repo ký: [ohpder/douyin](https://github.com/ohpder/douyin), [NearHuiwen/TiktokDouyinCrawler](https://github.com/NearHuiwen/TiktokDouyinCrawler).
- **product → video 带货**: qua **[TikHub](https://docs.tikhub.io/)** (~$0.001/req): resolve product_id → product detail → video search (`item_search_video`). Hoặc [Evil0ctal API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API): aweme_id → `video.play_addr` mp4.

### Kuaishou store
- **Không rõ có image-search** (product discovery theo keyword/feed/livestream). Ký `sig3/__NS_sig3`.
- **Ưu điểm: endpoint chính thức product→video sạch nhất** — `GET https://open.kuaishou.com/openapi/mp/developer/plc/photo/query` (video gắn mini-program/sản phẩm, tối đa 90 ngày, kèm metadata + đơn hàng). Nhưng **seller-scoped** (content của chính bạn), cần bật capability trong dev backend. Discovery toàn cục thì fallback TikHub `search_video_v2`.

### Kết luận nhóm sàn video TQ
Không sàn nào mở **API image-search**. Muốn "ảnh→video" phải: (a) tự drive app mobile capture endpoint, hoặc (b) tự build visual-embedding search (CLIP) trên catalog đã crawl, hoặc (c) dùng **image-search web mở (Google Lens/Yandex)** rồi bung keyword sang các video-endpoint (TikHub/Evil0ctal/yt-dlp). **(c) là con đường rẻ và khả thi nhất.**

---

*Lưu ý bản quyền: reup nguyên video người khác dễ dính gậy nền tảng; "xây motif giống rồi tự dựng lại" an toàn hơn — tool này để tìm tư liệu tham khảo.*
