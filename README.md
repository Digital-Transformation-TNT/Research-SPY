# Research SPY

Công cụ nội bộ cho phòng test sản phẩm. Bốn mục lớn, độc lập với nhau:

| Mục | Đường dẫn | Làm gì | Lấy dữ liệu từ |
|---|---|---|---|
| **Sản phẩm & Content** | `/ads` | Top sản phẩm đa sàn, content quảng cáo đang chạy, video theo sản phẩm | Facebook Ads Library, YouTube, Etsy *(qua server)* · **Shopee, TikTok Shop, Amazon, Taobao, 1688, Temu, video TikTok/Douyin** *(qua extension)* |
| **Từ khoá** | `/keywords` | Mở rộng từ khoá gốc ra biến thể đang được tìm kiếm, đo xu hướng | Google Suggest, Shopee, TikTok, Google Trends, 1688, Amazon, Douyin |
| **Tìm bằng ảnh** | `/image` | Một tấm ảnh, ra nguồn hàng và giá ở năm sàn | 1688, Alibaba.com, AliExpress, Taobao, Google Lens |
| **Cơ hội** | `/opportunity` | Hỏi đáp về khoảng trống thị trường trên dữ liệu đã thu | tổng hợp từ ba mục trên |

Ngoài ra có `/guide` — trang hướng dẫn đọc số liệu, **nên đọc trước khi ra quyết định test sản phẩm**.

> **Chỉ muốn chạy thử?** Đọc [QUICKSTART.md](QUICKSTART.md) — mười phút, không cần hiểu phần còn lại.

**Một số nguồn chạy trong trình duyệt của bạn, không phải trên server.** Shopee và TikTok Shop
trả 403 cho mọi lượt gọi ẩn danh từ server, nhưng trả dữ liệu bình thường cho chính phiên đăng
nhập của bạn. Phần đó do [extension/](extension/) đảm nhiệm, và cookie không bao giờ rời trình
duyệt. Xem [extension/README.md](extension/README.md) để cài — hai phút, chế độ dev của Chrome.

---

## Hai tiến trình

Dự án chia làm hai phần chạy song song:

| Thư mục | Ngôn ngữ | Việc | Cổng |
|---|---|---|---|
| [backend/](backend/) | Python + FastAPI | Toàn bộ tầng dữ liệu: gọi nguồn, chấm điểm, cache, proxy media | 8000 |
| [frontend/](frontend/) | TypeScript + Next.js | Chỉ giao diện. Không có logic nghiệp vụ nào | 3000 |

Trình duyệt chỉ nói chuyện với cổng 3000. Mọi đường `/api/*` được Next chuyển tiếp sang
backend (xem [frontend/next.config.mjs](frontend/next.config.mjs)), nên không có CORS và
video vẫn phát được từ cùng một origin.

---

## Chạy dự án

Cài một lần:

```bash
cd backend
python -m pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env.local        # tuỳ chọn — chạy được mà không cần sửa gì

cd ../frontend
npm install
```

**Cài extension** (chỉ cần nếu muốn dùng Shopee / TikTok Shop / Amazon / 1688 trong mục Quảng cáo):

1. Mở `chrome://extensions`
2. Bật **Developer mode** ở góc phải trên
3. **Load unpacked**, chọn thư mục [extension/](extension/)
4. Đăng nhập sẵn một tab của sàn bạn định tra — extension mượn đúng phiên đó

Không cài cũng không sao: Facebook, TikTok Creative Center, YouTube và Etsy chạy thẳng từ
server. Thiếu extension thì mục Quảng cáo báo rõ ra chứ không lặng lẽ bỏ trống Shopee.

Chạy hằng ngày: **nhấp đúp `start.bat`** ở thư mục gốc. Nó bật cả hai tiến trình trong hai
cửa sổ riêng rồi mở trình duyệt. Muốn chạy bằng tay — hoặc cần đọc log của một bên — thì
**dùng hai cửa sổ terminal**:

```bash
# cửa sổ 1
cd backend
python -m uvicorn app.main:app --port 8000

# cửa sổ 2
cd frontend
npm run dev                       # http://localhost:3000
```

> **Đừng thêm `--reload` cho backend trên Windows.** Cờ đó khiến uvicorn chuyển sang
> `WindowsSelectorEventLoopPolicy`, loop không sinh được tiến trình con, nên Playwright chết
> ngay khi khởi động — mất cả Google Trends lẫn toàn bộ mục Quảng cáo. Sửa backend thì tắt
> rồi bật lại bằng tay. (`--workers` dính đúng lỗi này.)

Lệnh khác:

```bash
# backend/
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000   # mở cổng cho cả LAN
python scripts/smoke/ads.py             # test đầu-cuối mục Quảng cáo
python scripts/smoke/keywords.py        # test đầu-cuối mục Từ khoá
python scripts/smoke/ui.py              # mở trình duyệt thật, click hết các nút, bắt lỗi client
python scripts/audit/keyword_sources.py # đối chiếu độc lập: dữ liệu tool có khớp nguồn gốc không

# frontend/
npm run build                           # build production
npm run start                           # chạy bản build, mở cổng 3000 cho cả LAN
npm run typecheck                       # tsc --noEmit
```

Ba script đầu mặc định gọi backend ở cổng 8000; `ui.py` gọi giao diện ở cổng 3000. Đặt
`BASE=http://localhost:3000` để chạy smoke qua đúng đường mà người dùng thật đi.

> **Chỉ chạy một tiến trình backend.** Cache và kho phiên trình duyệt nằm trong bộ nhớ, nên
> `--workers` sẽ nhân số request ra ngoài lên đúng bằng số worker — chính là thứ làm IP
> chung bị chặn.

---

## Cấu trúc thư mục

Nguyên tắc: **mỗi mục lớn có một thư mục riêng ở cả ba tầng** (dữ liệu, giao diện, style).
Nhìn đường dẫn của một file là biết ngay nó thuộc mục nào, nên đọc commit cũng dễ và hai
người làm hai mục khác nhau gần như không đụng file của nhau.

```
backend/
├── app/                     # TẦNG HTTP — mỏng, không chứa logic nghiệp vụ
│   ├── main.py              #   dựng FastAPI, đóng trình duyệt khi tắt
│   └── api/
│       ├── ads.py           #   /api/ads/{platforms,search,ingest,match-image,video-keywords}
│       ├── keywords.py      #   /api/keywords{,/sources,/markets,/gloss,/bridge}
│       ├── imagesearch.py   #   /api/imagesearch — một ảnh, năm sàn
│       ├── opportunity.py   #   /api/opportunity/ask
│       └── media.py         #   proxy phát video, có danh sách host cho phép
│
└── lib/
    ├── core/                # HẠ TẦNG DÙNG CHUNG — không biết Facebook/TikTok là gì
    │   ├── config.py        #   cấu hình chung (cache, timeout, user-agent), nạp .env
    │   ├── cache.py         #   cache TTL trong bộ nhớ
    │   ├── rate_limit.py    #   hàng đợi giữ nhịp gọi ra ngoài
    │   ├── browser.py       #   kho phiên trình duyệt, chạy theo "recipe" nguồn tự khai
    │   ├── http.py          #   gọi JSON cho nguồn không cần trình duyệt
    │   ├── model.py         #   nền chung cho kiểu đi ra API (đổi tên trường sang camelCase)
    │   ├── auth.py          #   hồ phiên đăng nhập Google: chọn, phạt, thưởng
    │   ├── mtop.py          #   ký request cho cổng MTOP của Alibaba
    │   ├── store.py         #   kho trên đĩa cho kết quả tra cứu tốn kém
    │   └── jscompat.py      #   những chỗ Python khác JavaScript  ← ĐỌC KHI SỬA ĐIỂM SỐ
    │
    ├── ads/                 # ===== MỤC QUẢNG CÁO =====
    │   ├── platform.py      #   HỢP ĐỒNG một nguồn quảng cáo phải thoả  ← đọc file này trước
    │   ├── platforms/
    │   │   ├── __init__.py  #   SỔ ĐĂNG KÝ — nơi duy nhất sửa khi thêm nguồn
    │   │   ├── facebook.py  #   fetch phía SERVER
    │   │   ├── tiktok.py    #   fetch phía SERVER
    │   │   ├── youtube.py   #   fetch phía SERVER (API chính thức, cần YOUTUBE_API_KEY)
    │   │   ├── etsy.py      #   fetch phía SERVER (API chính thức, cần ETSY_*)
    │   │   └── shopee.py    #   fetch phía CLIENT — server dựng lệnh, extension chạy
    │   ├── types.py         #   Ad, AdScore, RequestSpec/ClientJob (hợp đồng với extension)
    │   ├── scoring.py       #   quảng cáo chấm theo đời sống, sản phẩm chấm theo cầu và chất lượng
    │   ├── relevance.py     #   cụm từ có nằm trong chữ đọc được không — XẾP HẠNG, không lọc
    │   ├── imagematch.py    #   khớp ảnh bằng pHash (trùng gần như từng điểm ảnh)
    │   ├── clipmatch.py     #   khớp ảnh bằng CLIP (cùng sản phẩm dù khác góc chụp)
    │   ├── keyword_extract.py  # tiêu đề sản phẩm dài thành cụm từ khoá ngắn (Gemini)
    │   └── search.py        #   điều phối hai pha: server fetch, rồi extension nộp raw về
    │
    ├── imagesearch/         # ===== MỤC TÌM BẰNG ẢNH =====
    │   ├── ali.py  alibaba.py  aliexpress.py  taobao.py  lens.py
    │   ├── types.py         #   ImageMatch, ImageSearchResult (sáu tầng giá)
    │   └── search.py        #   điều phối năm nguồn, cache cả danh sách rồi lọc lúc đọc
    │
    └── keywords/            # ===== MỤC TỪ KHOÁ =====
        ├── provider.py      #   HỢP ĐỒNG một nguồn từ khoá phải thoả
        ├── providers/
        │   ├── __init__.py  #   SỔ ĐĂNG KÝ — nơi duy nhất sửa khi thêm nguồn
        │   ├── expand.py    #   bộ máy mở rộng long-tail, dùng chung mọi nguồn
        │   └── trends_related.py  shopee.py  amazon.py  tiktok.py
        ├── market.py        #   thị trường nào nói ngôn ngữ nào (một bản duy nhất)
        ├── normalize.py     #   vốn từ + quy tắc văn bản THEO THỊ TRƯỜNG
        ├── gloss.py         #   dịch nghĩa về tiếng Việt để ĐỌC (Gemini) — không chạm xếp hạng
        ├── bridge.py        #   bắc cầu từ gốc: Gemini đề cử cách gọi, Trends chấm điểm
        └── types.py  rank.py  trends.py  search.py

frontend/
├── app/
│   ├── ads/page.tsx         # trang Quảng cáo (server component, hỏi backend danh sách nguồn)
│   ├── keywords/page.tsx    # trang Từ khoá
│   ├── image/page.tsx       # trang Tìm bằng ảnh
│   ├── opportunity/page.tsx # trang Cơ hội
│   ├── guide/page.tsx       # trang Hướng dẫn
│   └── page.tsx             # chuyển hướng về /ads
├── components/
│   ├── keywords/            # KeywordResearch, KeywordTable, SeedTrend, TrendChart, Dropdown
│   ├── imagesearch/         # ImageSearchWorkspace
│   └── layout/              # Sidebar, BackendDown
├── public/
│   └── research/            # TRANG RESEARCH — HTML/JS thuần, nhúng nguyên vào /ads
│                            #   chuyển từ extension sang, cố ý KHÔNG viết lại thành React
├── lib/
│   ├── api.ts               # địa chỉ backend cho server component
│   ├── ads/                 # kiểu dữ liệu + extension.ts (cầu nối tới extension)
│   ├── keywords/            # kiểu dữ liệu, gương của backend/lib/keywords/types.py
│   └── imagesearch/         # kiểu dữ liệu, gương của backend/lib/imagesearch/types.py
└── styles/                  # CSS tách theo đúng ranh giới trên: ads.css, keywords.css, …

extension/                   # ===== EXTENSION CHROME (MV3) =====
├── manifest.json            # quyền theo tên miền, content script cho web app
├── background.js            # service worker: chạy fetch TRONG tab của sàn, nên same-origin
├── content.js               # cầu nối web app với service worker qua postMessage
├── page-hook.js             # chộp phản hồi mà chính trang tự gọi (Taobao, Temu)
├── similar-hook.js          # tương tự, cho trang "sản phẩm tương tự" của Shopee
└── popup.*                  # tự test một sàn, không cần web app

gtrends/                     # gói Google Trends TÁCH RỜI — copy sang dự án khác được
docs/                        # ghi chép nghiên cứu nguồn dữ liệu, không phải phần mềm chạy
```

### Quy tắc phụ thuộc

```
lib/ads  ──┐
           ├──►  lib/core        (một chiều, không bao giờ ngược lại)
lib/keywords ┘

lib/ads  ✗  lib/keywords        (hai mục KHÔNG import lẫn nhau, kể cả kiểu dữ liệu)

frontend  ──►  backend qua HTTP  (giao diện không chứa logic nghiệp vụ nào)
```

Hai mục dùng chung đúng ba thứ: cache, hàng đợi rate-limit, và cấu hình chung. Không dùng
chung kiểu dữ liệu nào. `lib/keywords/providers/tiktok.py` và `lib/ads/platforms/tiktok.py`
trùng tên nhưng là hai file không liên quan — một cái đọc gợi ý tìm kiếm, một cái đọc thư
viện quảng cáo.

**Kiểu dữ liệu tồn tại ở hai nơi.** `frontend/lib/*/types.ts` là bản mô tả hình dạng JSON mà
`backend/lib/*/types.py` phát ra. TypeScript không kiểm tra được qua ranh giới HTTP, nên hai
file cố ý giữ đúng thứ tự trường: sửa bên Python thì sửa luôn bên TypeScript, và đối chiếu
bằng mắt là ra ngay.

---

## Thêm một nguồn mới

Xem hướng dẫn đầy đủ kèm ví dụ ở **[CONTRIBUTING.md](CONTRIBUTING.md)**. Tóm tắt:

* **Nguồn quảng cáo mới** (Shopee Ads, Google Ads, Lazada…): tạo
  `backend/lib/ads/platforms/<tên>.py` kế thừa lớp `AdPlatform` ở
  [backend/lib/ads/platform.py](backend/lib/ads/platform.py), rồi thêm một dòng vào
  `backend/lib/ads/platforms/__init__.py`. Không phải sửa route, giao diện, proxy media hay
  file cấu hình nào.
* **Nguồn từ khoá mới**: tạo `backend/lib/keywords/providers/<tên>.py` theo
  `backend/lib/keywords/provider.py`, thêm một dòng vào
  `backend/lib/keywords/providers/__init__.py`.

---

## File và thư mục KHÔNG commit

Đã khai báo sẵn trong [.gitignore](.gitignore). Liệt kê lại ở đây để rõ lý do:

| Đường dẫn | Vì sao không commit |
|---|---|
| `frontend/node_modules/` | Dựng lại được từ `package-lock.json`, hàng trăm MB |
| `frontend/.next/` | Kết quả build, luôn dựng lại được |
| `next-env.d.ts`, `*.tsbuildinfo` | Next.js và TypeScript tự sinh mỗi lần chạy |
| `__pycache__/`, `*.pyc` | Python tự sinh |
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
`search_hint` chứ không phải `search_suggestion`). Chúng viết bằng TypeScript vì có từ trước
khi dự án chuyển sang Python, nên không còn chạy được với repo hiện tại — giá trị nằm ở phần
ghi chép, không ở phần code.

Nếu muốn xoá hẳn cho gọn: `rm -rf _archive`.

---

## Giới hạn cần biết (quan trọng)

Ba điều này ảnh hưởng trực tiếp tới việc đọc số liệu — trang `/guide` giải thích kỹ hơn:

1. **"CVR ước lượng" không phải CVR thật.** Không nền tảng công khai nào cung cấp tỷ lệ
   chuyển đổi; đó là dữ liệu riêng trong tài khoản advertiser. Con số này suy ra từ số ngày
   quảng cáo đã chạy (55%), số biến thể creative (20%), CTR (15%) và tương tác (10%). Nó vẫn
   được tính vì **thứ tự thẻ dựa vào nó**, nhưng cố ý KHÔNG hiện trên thẻ quảng cáo: với người
   đi tìm sản phẩm để bán, một con số trộn sẵn không nói được gì mà số gốc — ngày chạy, biến
   thể, CTR, đều in ngay trên thẻ — không nói rõ hơn.

   Thẻ **sản phẩm sàn** thì có hiện điểm, và là điểm khác: *cầu* (số bán) và *chất lượng*
   (rating cùng số lượt đánh giá). Đó là con số sàn công bố chứ không phải suy luận, nên nó
   nói thêm chứ không trộn lẫn. Xem `backend/lib/ads/scoring.py`.

2. **TikTok không search được theo từ khoá.** Creative Center chỉ mở chức năng này cho tài
   khoản đã đăng nhập; phiên ẩn danh nhận về *0 kết quả kèm mã thành công* — trông hệt như
   "sản phẩm không có nhu cầu". Khi gặp trường hợp này công cụ chuyển sang duyệt Top Ads theo
   CTR và **luôn kèm thông báo nói rõ**. Thấy thông báo đó thì đừng kết luận về nhu cầu sản
   phẩm, hãy nhìn phần Facebook.

3. **Không có lượng search tuyệt đối.** Con số đó chỉ nằm trong Google Ads Keyword Planner và
   cần tài khoản quảng cáo đang tiêu tiền. Cột "Lượng tìm" vẽ **hình dạng** nhu cầu theo thời
   gian lấy từ Google Trends, kèm tháng cao điểm — dùng để chọn thời điểm test và so tính mùa
   vụ giữa các từ khoá, không dùng thay số liệu khi tính ngân sách. Cột "Bảng xếp hạng" nói
   nguồn nào *gợi ý* từ khoá đó và ở vị trí mấy — không phải doanh số. (Đo ngày 2026-07-28:
   endpoint tìm sản phẩm của Shopee trả 403 với người gọi ẩn danh, search organic của TikTok
   trả body rỗng, nên số lượt bán và lượt xem đều ngoài tầm với.)

4. **Ba ô chọn Quốc gia / Thời gian / Loại tìm kiếm áp cho CẢ hai việc** — tìm ra từ khoá, và
   vẽ đường lượng tìm. Đó là ba ô của chính trang Google Trends, nên đổi chúng là đổi câu hỏi
   chứ không phải đổi cách hiển thị: bảng truy vấn liên quan của "24 giờ qua" là một tập từ
   khoá khác hẳn của "Năm qua", và "Google Mua sắm" lại là tập thứ ba. Mặc định là
   **Việt Nam · Năm qua · Tìm kiếm trên web**. Chọn thị trường Shopee không có mặt thì chip
   Shopee tự tắt — nó chỉ chạy ở VN, TH, PH, MY, ID, SG.

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
  trúc. File cần sửa khi đó chính là `backend/lib/ads/platforms/<tên nguồn>.py` và không file
  nào khác.
* **Trang báo "Chưa kết nối được tầng dữ liệu"** nghĩa là backend Python chưa chạy, không phải
  công cụ hỏng. Bật lại `python -m uvicorn app.main:app` trong `backend/` rồi tải lại trang.
