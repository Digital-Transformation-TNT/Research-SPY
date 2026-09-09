# Lấy VIDEO cho một sản phẩm — đo lại toàn bộ nguồn (08/09/2026)

> Ghi lại phép đo thật chứ không phải phỏng đoán. Mọi con số dưới đây đo **ngay trên VPS
> production** (157.66.101.73, Windows Server 2022), không đăng nhập, không extension, không
> máy-thợ — trừ chỗ nào nói rõ là cần máy-thợ.
>
> Lý do có tài liệu này: nút 🎬 **Video** ở tab Sản phẩm trả về **rỗng trên mọi nền tảng**, và
> mỗi nguồn rỗng vì một lý do khác nhau. Ba trong bốn lý do đó là kết luận CŨ đã hết đúng.

---

## 1. Vì sao trước đó không ra gì

| Nguồn | Trạng thái cũ | Nguyên nhân thật |
|---|---|---|
| Facebook Ads Library | luôn 0 | Máy-thợ ngồi đợi response `/api/graphql` — nhưng Facebook **đã chuyển sang nhúng sẵn trang kết quả đầu vào HTML**. Debug của chính máy-thợ nói rõ: `gql=1, cap=0, bodyLen=36295`. Trang có dữ liệu, chỗ đi lấy thì nhìn sai chỗ. |
| Facebook (đường server) | không bao giờ chạy | Bị xếp sau máy-thợ vì kết luận "playwright trên VPS bị soft-block". Kết luận ấy đúng với **POST GraphQL tự phát lại**, không đúng với **trang**. |
| YouTube | luôn 0 | Chưa khai `YOUTUBE_API_KEY`, mà nguồn này không có đường nào khác. Nguồn ỔN ĐỊNH NHẤT lại là nguồn duy nhất chắc chắn không chạy. |
| TikTok / Douyin qua Google | 0 nếu không có máy-thợ | Google chặn hẳn IP máy chủ — mọi truy vấn rơi vào `/sorry/index`. |
| TikTok Creative Center | đã gỡ khỏi cửa sổ | Tìm-theo-từ-khoá có chữ ký; chỉ đọc được ~20 top-ads cả nước → gần như luôn lệch sản phẩm. |
| Sàn TMĐT | chỉ khi list có `videoUrl` | Đúng như thiết kế, không phải lỗi. |

Cộng lại: **không có nguồn nào chạy được nếu không có máy-thợ, và nguồn đi qua máy-thợ thì
hỏng.** Đó là lý do "tìm gì cũng không ra".

---

## 2. Đo từng nguồn

### 2.1 Facebook Ads Library — CHẠY ĐƯỢC THẲNG TỪ SERVER

Trang Ad Library nhúng trang kết quả đầu vào một `<script type="application/json">`, đường
`search_results_connection.edges[].node.collated_results[]` — **cùng hình dạng** mà
`_extract_ads` vốn đã đọc từ response GraphQL.

`curl` trần: **HTTP 403**. Trình duyệt thật (headless): ra dữ liệu. 8 lượt, 2 bản trình duyệt ×
4 truy vấn:

| Truy vấn | Chromium đi kèm | Chrome thật |
|---|---|---|
| `kem chống nắng` VN | 0 *(trượt)* | 30 quảng cáo |
| `tai nghe bluetooth` VN | 30 (884 kết quả) | 30 |
| `sunscreen` US | 23 (17.797) | 23 |
| `massage gun` US | 30 (1.523) | 30 |

→ 7/8 ra dữ liệu. Lượt trượt là do **chờ mù bằng đồng hồ**; chờ đúng cái script xuất hiện thì
6/6 thành công, mỗi lượt 4–7 giây.

**Một cái bẫy đã sập:** `_extract_ads` chặn duyệt cây ở độ sâu 16. Trong HTML, bản ghi bị bọc
thêm mấy lớp `ScheduledServerJS → __bbox → RelayPrefetchedStreamCache`:

```
end_cursor      độ sâu 15   ← lọt qua, nên vẫn đọc được con trỏ
ad_archive_id   độ sâu 19   ← BỊ CẮT
```

Hàm trả về "0 quảng cáo, có con trỏ" — trông y hệt một truy vấn thật sự không có kết quả.

**Phân trang: KHÔNG CÓ.** Cuộn 10 lần: trang cao thêm, số `ad_archive_id` đứng yên ở 30, không
một `/api/graphql` nào chở quảng cáo. Trần của nguồn này là **30 quảng cáo mỗi truy vấn**.

### 2.2 YouTube — nguồn đông nhất, không cần API key

Trang kết quả nhúng `ytInitialData`; mỗi lần cuộn tới đáy trang tự gọi `/youtubei/v1/search`
cho trang tiếp, **cùng hình dạng `videoRenderer`**. Giữ luôn response ấy trong trang rồi duyệt
một cây duy nhất.

| | số video |
|---|---|
| lần đầu | 20 |
| sau 2 lượt cuộn | 40 |
| sau 4 lượt cuộn | 79 |
| trần đã đặt (8 lượt) | ~150 |

Mỗi thẻ có tiêu đề, kênh, **lượt xem**, ngày đăng, thời lượng, ảnh bìa. Có API key thì vẫn ưu
tiên key (nhanh hơn, không tốn trình duyệt).

**Bẫy đã sập:** lượt cuộn THỨ NHẤT thường chưa kịp kéo trang tiếp (20 → 20), lượt thứ hai mới
nhảy lên 40. Bỏ cuộc sau một lượt đứng yên ⇒ luôn dừng ở đúng 20 video, xin bao nhiêu cũng vậy.

### 2.3 TikTok — đi qua Bing Videos

Ba đường thẳng đều tắc từ server:

| Đường | Kết quả đo |
|---|---|
| `tiktok.com/search/video?q=` | trang lên 456 KB, **0 link video** |
| `tiktok.com/tag/…` | 0 |
| `douyin.com/search/…` | 0 |
| Google `site:tiktok.com` (web + hình ảnh) | **`/sorry/index`** — captcha, mọi truy vấn |
| DuckDuckGo | HTTP 418 |
| Bing **web** `site:tiktok.com` | 0 link video |
| Bing **Videos** `site:tiktok.com` | ✅ **30–112 video** |

Bing Videos gói sẵn mọi thứ vào thuộc tính `mmeta` của mỗi thẻ: `murl` là **link video TikTok
thật**, kèm ảnh bìa, tiêu đề, tài khoản, lượt xem, thời điểm đăng.

**Hai tham số quyết định số lượng** — cả hai đều từng làm nguồn này trông như "thị trường đó
không có video":

1. `&mkt=…&setlang=…` — thiếu là gần như rỗng:

   | `site:tiktok.com massage gun` | thẻ |
   |---|---|
   | locale trình duyệt `en-US`, không `mkt` | **5** (lặp 2 lượt, không phải nhiễu) |
   | thêm `&mkt=en-US&setlang=en` | **50** |

2. **Bản trình duyệt** — Bing phục vụ hai bố cục khác nhau:

   | `site:tiktok.com tai nghe bluetooth`, lật 3 trang | luỹ kế video |
   |---|---|
   | Chrome thật | 30 → 30 → 30 *(phân trang bị bỏ qua)* |
   | Chromium đi kèm Playwright | 35 → 77 → **112** |

   Đây là nơi **duy nhất** trong tool cần bản đi kèm thay vì Chrome thật (`launch_browser(prefer_bundled=True)`).

Trong 50 thẻ Bing trả về chỉ ~30 là link VIDEO, số còn lại trỏ về trang hồ sơ — nên phải lọc
**trước** khi đếm, không thì vòng lật trang tưởng đã đủ và dừng sớm.

**Giới hạn:** đây là chỉ mục của Bing, không phải bảng xếp hạng TikTok. Video quá mới có thể
chưa được lập chỉ mục — nên nguồn này **không thay** đường tìm thật trong tab TikTok của
máy-thợ, nó chỉ là đường chạy được ở mọi máy.

### 2.4 Douyin — vẫn phải có máy-thợ

Bing `site:douyin.com` trả về… kết quả YouTube (19 thẻ, 0 link Douyin). Không có đường server
nào. Giữ nguyên nút 🎥 Douyin đi qua extension/máy-thợ.

---

## 3. Kết quả sau khi sửa

Một lượt `/api/ads/search?platforms=facebook,youtube,tiktokvideo&videoOnly=true&limit=60`,
tiêu đề `"Kem chống nắng Anessa Perfect UV"`, chạy qua service production:

```
facebook     29 quảng cáo   110 s (lượt nguội, gồm cả lần thử lại)
youtube     150 video        43 s
tiktokvideo  17 video        19 s
→ 60 thẻ sau khi luân phiên theo nguồn
```

Lượt sau (trình duyệt đã ấm): **37 giây cho cả ba nguồn.**

Trước khi sửa: **0 thẻ, 45 giây, không lời giải thích.**

---

## 3b. Ra video KHÔNG LIÊN QUAN — nguyên nhân và dấu `""`

Sau khi ba nguồn đã chạy, lưới vẫn đầy video lệch sản phẩm. Nguyên nhân **không phải** cú pháp
tìm kiếm, mà là **cụm từ khoá dùng chung**.

Từ tiêu đề sản phẩm, Gemini rút hai cụm — `broad` và `specific`:

```
"Tai nghe bluetooth Redmi Buds 6 Play chính hãng"
   specific = "tai nghe redmi buds 6 play"
   broad    = "tai nghe bluetooth"
```

`app/api/ads.py` gán **broad** cho `params.keyword`, tức là cho MỌI nguồn. Với Facebook thì
đúng — nhưng với nguồn video thì hỏng hẳn. Đếm số thẻ có đúng tên sản phẩm trong 30 thẻ đầu:

| Cụm đem đi tìm | TikTok (Bing) | YouTube | Facebook |
|---|---|---|---|
| `broad` | **0/30** | **1/30** | 892 kết quả |
| `specific` | 28/30 | 25/30 | **1 kết quả trên toàn Ad Library** |

Facebook **bắt buộc** dùng broad, nguồn video **bắt buộc** dùng specific. Ép chung một cụm là
phải chọn: hoặc Facebook rỗng, hoặc lưới video toàn rác. → thêm
`AdSearchParams.keyword_by_platform` để mỗi bên dùng cụm của mình.

**CHỜ MÙ, lần thứ ba.** Ba nguồn chạy song song nên có lúc ba trình duyệt cùng khởi động; đúng
lượt ấy Bing về chậm hơn `_SETTLE_MS` và nguồn TikTok trả 0 — trong khi chạy riêng thì 4/4 lượt
ra 30 thẻ. Đã đổi sang chờ đúng thẻ `.mc_vtvc` xuất hiện. Cùng một bài học đã gặp ở trang Ad
Library và ở vòng cuộn YouTube: **chờ đúng thứ cần, đừng chờ theo đồng hồ.**

### Dấu `""` — có tác dụng ở đâu

| | không nháy | có `""` |
|---|---|---|
| Facebook, `massage gun` | 1.522 kết quả | 1.522 |
| Facebook, `kem chống nắng` | 8.646 | 8.649 *(chênh do quảng cáo lên/xuống giữa 2 lượt)* |
| Facebook, `tai nghe bluetooth` | 890 | 890 |
| Facebook, cụm specific dài | 1 | 1 |
| Bing, đúng SP trong 30 thẻ | 28 | 28 |
| YouTube, đúng SP trong 30 thẻ | 25 (lặp 2 lượt) | **27** (lặp 2 lượt) |

**Facebook bỏ qua hoàn toàn dấu nháy** — nó không dùng cú pháp `"..."` như Google; độ chặt do
tham số `search_type` quyết định (`keyword_exact_phrase` vs `keyword_unordered`).

**Cả ba nguồn đều bọc nháy** (Facebook là quyết định của chủ dự án, 08/09/2026 — theo số đo thì
vô hại chứ không có lợi). Mỗi nguồn kèm lưới đỡ giống nhau: cụm bọc nháy không ra gì thì tự tìm
lại bằng cụm trần và nói rõ trên dòng trạng thái (`_bo_nhay`) — đó cũng là cái chặn nếu một ngày
Facebook đổi ý và bắt đầu coi nháy là ký tự thường.

Facebook giữ cụm **chung chung** (`broad`), không đổi: cụm specific chỉ ra 1 quảng cáo trên
toàn Ad Library. Đã đo lại sau khi bọc nháy: 30 quảng cáo, 9 giây.

### Sau khi sửa

`"Tai nghe bluetooth Redmi Buds 6 Play chính hãng"`, 60 thẻ:

```
YouTube      20/22 thẻ đúng sản phẩm   (trước: 1/30)
TikTok       20/21 thẻ đúng sản phẩm   (trước: 0/30)
Facebook      0/17 thẻ đúng sản phẩm
```

**Facebook vẫn 0, và đó không phải lỗi:** cả Ad Library Việt Nam chỉ có **đúng 1** quảng cáo
khớp cụm `tai nghe redmi buds 6 play`. 17 thẻ kia là quảng cáo tai nghe nói chung, trả lời cho
câu hỏi "ngành này có ai chạy quảng cáo không", không phải "món này có ai chạy không". Muốn
lưới sạch hẳn thì phải **đẩy các thẻ không khớp cụm xuống dưới** (`lib/ads/relevance.py` đã
gắn cờ `phrase_hit`, chỉ chưa dùng nó ở cửa sổ video) — chưa làm.

---

## 3c. Hàng đợi — chống request đẩy chồng lên nhau

### Vấn đề

`launch_browser` không có trần nào. Một lượt bấm 🎬 Video mở ba nguồn song song, mỗi nguồn lại
có nhánh thử-lại riêng ⇒ **tới 8 lượt mở trình duyệt cho một request, 3 lượt cùng lúc ở đỉnh**.
Hai người bấm cùng lúc là 6 Chrome; cộng thêm một người đang tìm từ khoá (mục Từ khoá mở gần
chục lượt mỗi lần) là nghẹt hẳn.

Cái vỡ trước **không phải RAM mà là ĐỘ TRỄ**, và nó vỡ im lặng: trang về chậm hơn mốc chờ cứng,
nguồn đọc ra rỗng, người dùng đọc thành "không có video".

### Ba lớp đã thêm

**1. Trần số trình duyệt chạy cùng lúc** (`browser_lane`, mặc định 3, đổi bằng `BROWSER_LANES`).
`asyncio.Semaphore` đánh thức người chờ theo thứ tự nên đây đúng nghĩa là hàng đợi: request thứ
tư xếp hàng thay vì cùng lao vào rồi tất cả cùng chậm. Lane chỉ nhả khi trình duyệt đã ĐÓNG.
Mọi nơi mở trình duyệt dùng-một-lần đều đã chuyển sang: Facebook, YouTube, Bing, thống kê
TikTok, và cả Google Trends của mục Từ khoá — hai mục dùng chung một cái máy nên phải chung
một trần. Kho phiên (`get_session`) giữ trần riêng `BROWSER_POOL_MAX=4`.

**2. Gộp request TRÙNG NHAU** (`_gop_luot_trung`). Cache chỉ chặn được lượt thứ hai khi lượt đầu
đã xong — mà một lượt kéo dài 30-40 giây, và đó đúng là lúc người dùng bấm lại vì tưởng máy
treo. Giờ lượt thứ hai chờ ké kết quả của lượt đầu. `shield` để người chờ ké đóng tab không
kéo theo lượt đang chạy.

**3. Bỏ chờ mù, chờ đúng thứ cần.** Ba chỗ, cùng một bệnh:

| Chỗ | Trước | Sau |
|---|---|---|
| Trang Ad Library | `wait_for_timeout` | chờ script có `ad_archive_id` |
| Cuộn YouTube | ngủ 2,2 s mỗi lượt | chờ tới khi số video TĂNG (hỏi lại mỗi 400 ms) |
| Thẻ Bing | ngủ 3,5 s | chờ thẻ đầu, rồi chờ số thẻ ĐỨNG YÊN |

**4. Bỏ phần lấy thừa.** `search.py` xin dư 2,5× vì bộ lọc hậu kỳ sẽ vứt bớt — nhưng ở YouTube
không có gì để vứt (mọi kết quả đều là video), nên xin 60 thành đi lấy 150 và cuộn thêm cho 90
cái không bao giờ lên màn hình. Trần `_MAX_ITEMS = 80`: **30,5 s → 19,3 s**.

### Đo: bắn 4 request cùng lúc (2 cặp trùng nhau)

| | trước | sau |
|---|---|---|
| số lượt đi lấy thật | 4 | **2** (hai cặp trùng gộp lại) |
| Chrome cùng lúc | tới 12 | **≤ 3** |
| SP A | 60 thẻ | 60 thẻ |
| SP B | **22 thẻ** (YouTube 7, TikTok 0) | **52 thẻ** (FB 29 · TikTok 30 · YouTube 7) |
| tổng thời gian | 48,1 s | **38,1 s** |

Hai request trùng nhau về đích cùng một giây với kết quả y hệt — dấu hiệu chúng đã dùng chung
một lượt lấy dữ liệu.

*(YouTube 7 ở SP B là thật, không phải nghẽn: chạy riêng cùng truy vấn cũng ra 7. Cụm specific
của sản phẩm đó quá dài — xem mục 4.)*

`/api/ads/health` giờ trả thêm `browserLanes: {lanes, running, waiting}`. `waiting > 0` kéo dài
nghĩa là đang xếp chồng — trước đây chỉ đoán được qua việc nguồn nào đó bỗng trả rỗng.

---

## 3d. Douyin và "Sàn" — hai chip luôn bằng 0

### Douyin: phép đo cũ SAI vì hỏi sai thứ tiếng

Kết luận trước ("Bing `site:douyin.com` trả về kết quả YouTube, không dùng được") là đúng với
truy vấn đã thử, và truy vấn đó hỏi bằng **tiếng Việt**. Douyin gần như không có nội dung tiếng
Việt, nên Bing rơi về YouTube. Hỏi bằng tiếng của chính nền tảng thì ra ngay:

| truy vấn | kết quả |
|---|---|
| `site:douyin.com tai nghe bluetooth` | 0 link Douyin (toàn YouTube) |
| `site:douyin.com 蓝牙耳机` + `mkt=zh-CN` | **20 thẻ**, đủ tiêu đề / tài khoản / ảnh bìa |

Còn Baidu và Sogou đều chặn IP máy chủ (captcha / antispider), nên Bing vẫn là đường duy nhất.

### Và cụm tiếng Trung phải NGẮN

Dịch cả tiêu đề sản phẩm sang tiếng Trung thì Gemini trả một cụm ghép dài, và Douyin không có
gì khớp. Đo trên chính hai cụm nó sinh ra:

| cụm | Douyin |
|---|---|
| `红米耳机redmi buds 6 play` | **0** (4,2 giây — Bing thật sự không có, không phải nghẽn) |
| `小猫印花纯棉T恤` | **0** |
| `蓝牙耳机` (dịch từ cụm **broad**) | **19** |
| `猫咪T恤` | **20** |

Douyin là sàn **nội địa Trung Quốc**: một mã máy bán ở Việt Nam thường không tồn tại ở đó, còn
ngành hàng thì luôn có. Nên riêng nguồn này, cụm broad không phải là hạ tiêu chuẩn — nó là cụm
duy nhất hỏi được một câu có câu trả lời.

Thêm lưới đỡ trong máy chung: cụm rỗng thì **nới dần** — bỏ nháy, rồi bỏ phần Latin
(`红米耳机redmi buds 6 play` → `红米耳机`), giữ lại chữ cái đơn lẻ vì "T恤" mà cắt chữ T thì thành
một từ không tồn tại.

### "Sàn": trước đây chỉ lấy từ bảng đang hiện

`marketAds` gom từ `rows` — tức là chỉ có khi người dùng đã chạy một lượt tìm sản phẩm TRƯỚC
đó, và chỉ với sàn nào chở sẵn `videoUrl`. Nên nó gần như luôn bằng 0.

Etsy trả thẳng **file `.mp4`** của video do người bán quay, qua API, chỉ cần thêm `includes=Videos`
— đo: 4/20 listing đầu của "t shirt" có video. Nhưng lúc đầu vẫn rỗng, vì Etsy nhận cụm **tiếng
Việt**: "Etsy không có kết quả cho tai nghe bluetooth" đọc thành "món này không ai bán trên
Etsy", trong khi thứ sai là ngôn ngữ của câu hỏi. Cho nó cụm tiếng Anh thì ra 100 listing.

Bốn nhóm ngôn ngữ hiện tại của `keyword_by_platform`:

```
facebook             cụm broad tiếng Việt   (Ad Library chỉ ra kết quả với cụm ngắn)
youtube, tiktokvideo cụm specific, bọc nháy
douyinvideo          cụm broad dịch sang TIẾNG TRUNG, không bọc nháy
etsy                 cụm dịch sang TIẾNG ANH
```

### Đo lại, cùng một lượt gọi

```
"Tai nghe bluetooth Redmi Buds 6 Play"   FB 30 · YouTube 98 · TikTok 30 · Douyin 19 · Etsy 0
                                          → lưới 60: 15/15/15/15
"Áo thun in hình mèo cotton"             FB 30 · YouTube 20 · TikTok 0 · Douyin 20 · Etsy 100
                                          → lưới 60: 11/17/16/16
```

Etsy 0 ở dòng đầu là **câu trả lời đúng**: không ai bán tai nghe Redmi trên Etsy. Cùng logic,
Douyin đầy ở cả hai dòng vì cả hai ngành hàng đều có mặt ở Trung Quốc.

---

## 4. Việc còn để lại

- **`PLAYWRIGHT_BROWSERS_PATH`.** `playwright install` cất Chromium vào `%LOCALAPPDATA%` của
  tài khoản chạy lệnh (Administrator), còn service chạy dưới **LocalSystem** nên không thấy nó
  → nguồn Bing rơi về Chrome thật và mất phân trang (112 → 30 video). `deploy/vps-setup.ps1` đã
  sửa để cài vào `C:\ms-playwright` và khai biến ấy cho service; **máy đang chạy thì chưa áp
  dụng** — cần chạy lại setup, hoặc:

  ```powershell
  $env:PLAYWRIGHT_BROWSERS_PATH = "C:\ms-playwright"; python -m playwright install chromium
  nssm set ResearchSpyBackend AppEnvironmentExtra "PLAYWRIGHT_BROWSERS_PATH=C:\ms-playwright"
  Restart-Service ResearchSpyBackend
  ```

- **Cụm specific quá dài.** Backend đã có `extract_video_terms` rút cụm ngắn dành riêng cho
  video (`"kem chống nắng anessa"`), hiện chỉ nhánh TikTok qua máy-thợ dùng. Đo: cụm dài →
  YouTube 7-20 video; cụm ngắn → 30. Đổi `_video_keywords` để dùng nó là xong.

- **`_MAX_ITEMS` của YouTube (80) là cần gạt tốc độ.** Cửa sổ luân phiên theo nguồn nên YouTube
  chỉ chiếm ~1/3 số ô; hạ xuống 40 thì nhanh thêm ~9 s, đổi lại ít ứng viên để xếp hạng hơn.

- **Facebook trần 30/truy vấn.** Muốn nhiều hơn thì phải chạy nhiều cụm từ khoá (Gemini vốn đã
  rút được cả cụm `specific` lẫn `broad`), chứ phân trang không có.

- **Bing không lọc theo nước.** `mkt` chỉ đổi thứ tự ưu tiên, không chặn. Video trả về có thể
  lệch ngôn ngữ — giống hệt vấn đề mà nhánh TikTok của máy-thợ đã có cờ `langMatch` để cảnh báo.
