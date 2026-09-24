# Bàn giao ② — Chức năng, function và logic hoạt động

> Trạng thái: **24/09/2026**. Đây là bản mô tả **cái đang chạy**, không phải cái đã từng có.
> Nhiều thứ trong `README.md` gốc đã lệch (nó còn tả bốn mục `/ads /keywords /image
> /opportunity`) — chỗ nào lệch thì tin tài liệu này.
>
> Nguyên tắc đọc: **mỗi mục lớn có một thư mục riêng ở cả ba tầng** (dữ liệu · giao diện ·
> style). Nhìn đường dẫn của một file là biết nó thuộc mục nào.

---

## 0. Sidebar — năm cửa vào, và những cửa đã đóng

| Nhóm | Mục | Route | Backend chính |
|---|---|---|---|
| **Research** | Keyword | `/keywords` | `lib/keywords/` |
| | Image Search | `/image` | `lib/imagesearch/` |
| | Sản phẩm | `/ads` | `lib/ads/` |
| **Tín hiệu thị trường** | Trend Signal Hub | `/trend-signal` | `hub/signal/scout.py` |
| | One-shot AI | `/oneshot` | `hub/signal/ask.py` |
| **Quản trị** (chỉ `admin`/`owner`) | Quản trị | `/admin` | `app/api/admin.py` |

**Đã đóng cửa vào nhưng route còn nguyên** — truy cập thẳng bằng URL vẫn được:

| Route | Đóng khi nào | Vì sao |
|---|---|---|
| `/opportunity` (Cơ hội) | trước 13/09/2026 | Chatbot của nó **là** One-shot AI bây giờ — cùng engine `lib/opportunity/demand_map.py`, thêm phần ground trên dữ liệu Hub. Không để hai cửa vào cho cùng một việc |
| `/guide` (Hướng dẫn) | 22/09/2026 | Theo yêu cầu. Bỏ comment khối trong `components/layout/Sidebar.tsx` để hiện lại |

**Gate đăng nhập nằm ở `Sidebar.tsx`**: không có `rs_token` và không có `rs_email` trong
`localStorage` → `window.location.replace('/research/login')`. Sidebar chỉ render trong layout
`(dashboard)`, không bọc `/login`, nên không có vòng lặp redirect.

---

## 1. Kiến trúc và quy tắc phụ thuộc

```
lib/ads      ──┐
lib/keywords ──┼──►  lib/core        (MỘT CHIỀU, không bao giờ ngược lại)
lib/imagesearch┘

lib/ads  ✗  lib/keywords        (hai mục KHÔNG import lẫn nhau, kể cả kiểu dữ liệu)
hub/     ✗  được import từ lib/  (hub là gói TUỲ CHỌN — xem §1.2)
frontend ──►  backend qua HTTP   (giao diện KHÔNG chứa logic nghiệp vụ nào)
```

`lib/keywords/providers/tiktok.py` và `lib/ads/platforms/tiktok.py` **trùng tên nhưng không
liên quan** — một cái đọc gợi ý tìm kiếm, một cái đọc thư viện quảng cáo.

### 1.1 Kiểu dữ liệu tồn tại ở HAI nơi, cố ý

`frontend/lib/*/types.ts` là bản mô tả hình dạng JSON mà `backend/lib/*/types.py` phát ra.
TypeScript không kiểm tra được qua ranh giới HTTP, nên hai file **giữ đúng thứ tự trường**:
sửa bên Python thì sửa luôn bên TypeScript. Không có gì tự bắt được lúc chúng lệch.

Ba cặp "soi gương" khác, cùng luật:

| Bản A | Bản B | Lệch nhau thì |
|---|---|---|
| `backend/lib/ads/scoring.py::_score_product` | `frontend/public/research/research.js` | hai người xem cùng sản phẩm thấy hai điểm khác nhau |
| `backend/lib/core/bu.py::BU_CHOICES` | `app/(auth)/login/page.tsx::BU_OPTIONS` | user chọn được BU mà server từ chối |
| `backend/hub/signal/scout.py` | `frontend/lib/trendscout.ts` | nhãn lăng kính không khớp công thức |

### 1.2 `hub/` import ĐƯỢC PHÉP TRƯỢT

`app/main.py` bọc `from hub.main import router` trong `try/except`. Gói này kéo theo
pandas/pytrends/anthropic; một máy thiếu chúng mà làm cả backend chết thì **mất luôn Keyword,
Image Search, Sản phẩm** — vốn chẳng liên quan gì. Trượt thì dựng một đường chẩn đoán:

```
GET /api/hub/health  →  { status: "error", reason: "<tên lỗi>: <mô tả>" }
```

**Trả lý do thay vì 404 là cố ý.** `trend-signal-hub.html` coi mọi phản hồi không `ok` là
"backend chết" và rơi về **bộ dữ liệu mẫu nhúng cứng** — trang khi đó đầy ắp số liệu trông rất
thật, không một dấu hiệu nào cho biết chúng là số giả.

### 1.3 Hai kho dữ liệu, không phải một

| Kho | Ở đâu | Chứa gì |
|---|---|---|
| **Supabase** (PostgREST) | cloud | `users`, `role_requests`, `analytics_event` |
| **SQLite** `backend/database/hub_data.db` | đĩa VPS, **349 MB** | toàn bộ dữ liệu cào (`listings_snapshot`, `crawl_log`…) + `favorite_product` |

Yêu thích ở SQLite chứ không ở Supabase (chốt 24/09/2026): service key của Supabase đi qua
PostgREST nên **không chạy được `CREATE TABLE`** — mỗi lần đổi bảng lại phải nhờ người dán SQL
bằng tay, mà máy chủ này không cài PostgreSQL.

> **Hệ quả:** `user_id` trong `favorite_product` là UUID của `users` bên Supabase, lưu dạng
> TEXT, **không có khoá ngoại**. Xoá user ở trang Quản trị không tự dọn danh sách của họ —
> `admin.py` phải gọi `favorites.xoa_theo_user()`.

---

## 2. Xác thực và phân quyền

### 2.1 Luồng đăng nhập ba bước

`app/(auth)/login/page.tsx` → `app/api/auth.py`:

1. Nhập email **@tntecom.com** → `POST /api/auth/login`
   * có token → lưu `localStorage`, vào `/ads`
   * `needsRegistration` → sang bước 2
   * `pending` → sang bước 3
   * **501** → chưa cấu hình Supabase, **fallback dev: coi như đã đăng nhập**
2. Gửi hồ sơ (Tên · Vị trí · **BU**) → `POST /api/auth/register` → `pending`
3. Chờ admin duyệt → poll `/api/auth/login` mỗi **4 giây** tới khi có token hoặc bị từ chối

Không có mật khẩu: định danh là **email thuộc đúng tên miền** + **admin duyệt**.

BU (`BU1`/`BU2`/`BU3`/`HO`) là **ô chọn, không phải ô gõ** — bốn tài khoản đầu đã đẻ ra ba cách
viết cho cùng một đơn vị ("Holding", "Hoding", "HO"). Từ khi BU quyết định ngưỡng xanh của tỷ
giá thì một cách viết lạ không còn chỉ là xấu — nó **lặng lẽ áp sai chính sách** cho người ấy.

### 2.2 JWT middleware là OPTIONAL AUTH, không phải cổng chặn cứng

`app/main.py::jwt_middleware`:

* Có `Authorization: Bearer <token>` **hợp lệ** → gắn `request.state.user`
* **Không có** header → **VẪN CHO QUA** ẩn danh
* Có token nhưng **hỏng/hết hạn** → **401 ngay**, để client biết vé hỏng mà đăng nhập lại thay
  vì âm thầm chạy như ẩn danh

Vì sao không chặn cứng mọi `/api/*`: các route dữ liệu (`ads/search`, `keywords`, `media`,
`imagesearch`, `opportunity`) được gọi bằng plain fetch **không kèm token** — chặn cứng sẽ 401
toàn bộ và làm hỏng app kể cả với người đã đăng nhập.

**Enforce quyền là việc của TỪNG endpoint nhạy cảm:**

| Endpoint | Luật |
|---|---|
| `/api/admin/*` | `_require_admin` → 401 nếu thiếu user, **403** nếu không phải `admin`/`owner` |
| `/api/favorites/*` | 401 nếu chưa đăng nhập. Mọi câu lệnh kèm `WHERE user_id = ?` **lấy từ JWT**, không từ body/query |
| `/api/relay/submit` | 401 khi JWT đã cấu hình — máy-thợ chạy trên IP dân cư đã đăng nhập sàn, không mở cho ẩn danh |
| `/api/auth/me` | 401 nếu chưa có user |

Yêu thích là thứ **riêng tư nhất** trong app (nó nói người ta đang định bán gì). Không có đường
nào cho một người đọc hay sửa danh sách người khác — **kể cả admin**, kể cả khi đoán đúng `id`:
PATCH/DELETE trả **404 chứ không phải 403**, vì 403 đã là một câu xác nhận rằng dòng ấy tồn tại.

`role` có ba bậc: `user` < `admin` < **`owner`**. Kiểm `=== 'admin'` sẽ **khoá đúng người có
nhiều quyền nhất** ra khỏi trang Quản trị — và người duy nhất sửa được việc đó lại chính là họ.

---

## 3. Mục **Keyword** (`/keywords`)

**Việc:** một từ gốc → các biến thể đang được tìm kiếm thật, có xếp hạng, kèm hình dạng nhu cầu
theo thời gian.

### 3.1 Sổ đăng ký nguồn

`backend/lib/keywords/providers/__init__.py` — **nơi DUY NHẤT sửa khi thêm nguồn**:

`trends_related` · `shopee` · `amazon` · `tiktok` · `taobao` · `ali1688` · `douyin` · `temu`

Hợp đồng ở `lib/keywords/provider.py`. Thêm nguồn = tạo một file + thêm một dòng vào sổ. Không
phải sửa route, giao diện hay cấu hình nào.

### 3.2 Đường đi một lượt tìm

```
GET /api/keywords?...
  → search.py       điều phối, các nguồn chạy SONG SONG (host độc lập, mỗi nguồn tự giữ nhịp)
  → expand.py       bộ máy mở rộng long-tail, dùng chung mọi nguồn
  → normalize.py    vốn từ + quy tắc văn bản THEO THỊ TRƯỜNG
  → rank.py         xếp hạng
  → gloss.py        dịch nghĩa về tiếng Việt để ĐỌC (Gemini) — KHÔNG chạm xếp hạng
```

**Google Trends CỐ Ý không nằm trên đường này.** Nó rất dễ 429 và cần trình duyệt, nên lấy
riêng. Nhờ vậy Trends chết cũng không kéo theo phần khám phá từ khoá.

### 3.3 Xếp hạng — đo đồng thuận trên TỪNG CHỮ BỔ NGHĨA

Cách hiển nhiên nhất (xếp theo số nguồn cùng trả về đúng một từ khoá) **không sống nổi với dữ
liệu thật**: trên ba nguồn với một từ gốc thật, chỉ **2 trong 28** từ khoá trùng nhau nguyên
văn — mỗi nền tảng viết cùng một khái niệm một kiểu.

Nên đồng thuận được đo trên từng chữ: "quần jean suông ống rộng" (Shopee), "quần jeans ống
rộng" (Google), "quần jeans nữ ống rộng" (TikTok) đều **bỏ phiếu cho hai chữ "ống" và "rộng"**.
Mỗi thành phần điểm **ghi lại lý do của mình** để người dùng kiểm chứng thay vì tin mù.

### 3.4 Bắc cầu từ gốc (`/api/keywords/bridge`)

`bridge.py`: **Gemini đề cử cách gọi** ở thị trường đích → **Trends chấm điểm**. AI chỉ đề cử
tên, con số vẫn là số đo. Dùng khi từ gốc tiếng Việt không có mặt ở thị trường đang xét.

### 3.5 Ba ô chọn áp cho CẢ HAI việc

**Quốc gia / Thời gian / Loại tìm kiếm** vừa quyết định *tìm ra từ khoá nào*, vừa quyết định
*vẽ đường lượng tìm thế nào*. Đó là ba ô của chính trang Google Trends, nên **đổi chúng là đổi
câu hỏi**, không phải đổi cách hiển thị: bảng truy vấn liên quan của "24 giờ qua" là một tập
từ khoá **khác hẳn** của "Năm qua", và "Google Mua sắm" lại là tập thứ ba.

Mặc định: **Việt Nam · Năm qua · Tìm kiếm trên web**. Chọn thị trường Shopee không có mặt thì
chip Shopee **tự tắt** — nó chỉ chạy ở VN, TH, PH, MY, ID, SG.

### 3.6 Không có lượng search tuyệt đối

Con số đó chỉ nằm trong Google Ads Keyword Planner và cần tài khoản quảng cáo đang tiêu tiền.

* Cột **"Lượng tìm"** vẽ **HÌNH DẠNG** nhu cầu theo thời gian (Google Trends) kèm tháng cao
  điểm — dùng để chọn thời điểm test và so tính mùa vụ, **không dùng thay số liệu khi tính
  ngân sách**.
* Cột **"Bảng xếp hạng"** nói nguồn nào *gợi ý* từ khoá đó và ở vị trí mấy — **không phải doanh
  số**.

Đo 28/07/2026: endpoint tìm sản phẩm của Shopee trả **403** với người gọi ẩn danh, search
organic của TikTok trả **body rỗng** → số lượt bán và lượt xem đều ngoài tầm với.

### 3.7 TikTok và chuyện dịch keyword

TikTok **phải dịch keyword sang ngôn ngữ của nước đang tra** (PH = English), làm ở
`public/research/research.js`. Không dịch thì ra bảng rỗng kèm mã thành công.

**Kalodata đổi nước bằng HTTP `header: country`, KHÔNG phải bằng body** — body bị bỏ qua hoàn
toàn. Header gắn trong `kdSend` (`extension-kalodata/`), nên sửa xong **phải Reload extension**.

### 3.8 Cái bẫy tiếng Việt: bỏ dấu làm chập từ

Bỏ dấu để so khớp biến **giày/giấy**, **ủng/ứng**, **mưa/mua**, **chào/chảo** thành cùng một
chuỗi. Mọi phép khớp chuỗi **phải giữ dấu khi câu có dấu**. Bug loại này **không bao giờ báo
lỗi** — nó chỉ trả về sai thứ.

---

## 4. Mục **Image Search** (`/image`)

**Việc:** một tấm ảnh → tên món + nơi đang bán + sáu tầng giá.

`POST /api/imagesearch` → `lib/imagesearch/search.py`. **Sáu tầng chạy song song và độc lập:**

| Tầng | File | Cho ra | Thời gian | Hạn mức |
|---|---|---|---|---|
| Đọc ảnh | `identify.py` | tên món, thương hiệu, mã model, cụm tìm vi/zh | ~3s | gần như không trượt |
| Google Lens | `lens.py` | sản phẩm tương tự + link, giá, đánh giá | ~20s | **~15 lượt/ngày** · CẦN MÁY-THỢ |
| 1688 | `ali.py` | chào hàng kèm giá sỉ + nhà cung cấp | ~3s | không hạn mức |
| Alibaba.com | `alibaba.py` | bán buôn xuất khẩu kèm giá ₫ + MOQ | ~4s | siết sau vài lượt dồn |
| Taobao | `taobao.py` | hàng bán lẻ TQ kèm giá + lượt mua | ~30s | CẦN MÁY-THỢ |
| AliExpress | `aliexpress.py` | bán lẻ quốc tế kèm giá ₫ ship về VN | ~5s | **~2 lượt rồi nghỉ một ngày** |

Thiết kế xoay quanh đúng một điều: **hạn mức của Lens là tài nguyên khan hiếm nhất**, không
phải tốc độ. Từ đó ra hai luật:

**Luật 1 — HỎNG MỀM.** Lens chạm hạn mức thì trả về phần `identity` kèm một câu nói, **không
ném lỗi**. Người dùng vẫn có tên món và cụm để tự gõ sang sàn; màn hình **không bao giờ trông
như hỏng**. `LensUnavailable` là một kiểu riêng chứ không phải `RuntimeError` trần.

**Luật 2 — CACHE THEO VÂN TAY ẢNH, GHI XUỐNG ĐĨA.** Khoá là `sha256` của chính bytes ảnh → hai
người tải lên cùng một ảnh chỉ tốn **một suất**. Dùng `DiskStore` chứ không `cache.py`: thứ nằm
đây đắt và có hạn mức, không được chết theo một lần restart.

**Độ dài cache theo ĐỘ KHAN HIẾM, không theo độ tươi:** nguồn gọi lại rẻ (1688, Alibaba.com) để
**7 ngày**; nguồn có trần chặt (Lens, AliExpress) để **30 ngày** — với chúng thứ đắt nhất là
suất gọi, không phải vài phần trăm chênh giá. Phần đọc ảnh cache **90 ngày** (nội dung một tấm
ảnh không bao giờ đổi), nhờ vậy các lượt thử lại không phải trả tiền Gemini thêm lần nào.

**Ảnh được thu nhỏ trước khi gửi xuống máy-thợ** (`relay.py`): cạnh dài tối đa **1200px**, JPEG
**q85**. Không phải cho đẹp — cả Lens lẫn Taobao đều tự thu về cỡ này trước khi trích đặc
trưng, nên gửi ảnh gốc 4000px chỉ tốn đường truyền. Một ảnh điện thoại 8MB → khoảng 150KB, và
payload đi qua **hai chặng HTTP** với base64 phình 4/3.

**Mã model chỉ dùng khi đọc được TỪ CHÍNH TẤM ẢNH.** Đo 19/08/2026: tra `site:shopee.vn "<mã>"`
chỉ ra hàng khi đó là **mã HÃNG** (`G304` → 8 trang), còn **mã XƯỞNG** lấy từ tiêu đề 1688 thì
bằng không (`T15S`, `N612`, `KF5135`) — người bán Việt Nam không dịch tiêu đề 1688, họ viết
tiêu đề mới và tự đặt mã riêng.

**Giá giữ NGUYÊN VĂN** ("989.000 đ"), cố ý không parse ra số: đơn vị tiền đổi theo nước, và một
con số không kèm đơn vị là một con số sai.

---

## 5. Mục **Sản phẩm** (`/ads`) — trang Research đa sàn

### 5.1 Nó là một `<iframe>`, và đó là quyết định có chủ đích

`app/(dashboard)/ads/page.tsx` nhúng **nguyên vẹn** `public/research/index.html` (586 dòng) +
`research.js` (3.453 dòng) chứ không viết lại thành React:

* **Giao diện không được lệch.** Viết lại 1.300 dòng thao tác DOM thành React thì chắc chắn
  lệch ở đâu đó, và lệch kiểu khó thấy.
* **CSS không được đụng nhau.** Trang đó khai `body`, `table`, `input`, `.status`, `.chip` —
  nhiều tên trùng với `styles/` của webtool. Trong iframe hai bộ CSS không thấy nhau.

**Đánh đổi phải biết:** `extension/manifest.json` **phải** khai `all_frames: true`. Content
script mặc định chỉ chạy ở khung trên cùng — thiếu dòng đó thì cầu postMessage **không có ai
nghe**, và trang báo "chưa cài extension" dù đã cài.

**Cầu từ tab Keyword:** link "Tìm sản phẩm" gọi `/ads?keyword=...`; page component đọc
`searchParams` rồi chuyền thành `?kw=` vào `src` của iframe — vì query string của khung cha
không thấy được từ trong iframe.

### 5.2 Sổ đăng ký nguồn

`backend/lib/ads/platforms/__init__.py`, hợp đồng ở `lib/ads/platform.py`:

| Nguồn | Chạy ở | Cần gì |
|---|---|---|
| `facebook` | **server** (Playwright) | `FB_COOKIE` |
| `tiktok` | **server** | proxy theo nước |
| `tiktokvideo` | **server** (Bing) | `prefer_bundled=True` — xem doc ① §6 |
| `douyinvideo` | **server** | hay đòi verify (滑块) |
| `youtube` | **server** (API chính thức) | `YOUTUBE_API_KEY` |
| `etsy` | **server** (API chính thức) | `ETSY_KEYSTRING` + `ETSY_SHARED_SECRET` |
| `shopee` | **CLIENT** — server dựng lệnh, extension chạy | extension + phiên đăng nhập |
| `ali1688` | **CLIENT** | extension + phiên đăng nhập |

### 5.3 Hai pha: server fetch, rồi extension nộp raw về

`lib/ads/search.py` điều phối. Nguồn `client_fetch` không tự gọi mạng — nó **dựng `RequestSpec`
/ `ClientJob`** (hợp đồng ở `lib/ads/types.py`), extension chạy trong tab của sàn rồi
`POST /api/ads/ingest` nộp raw về để server chấm điểm.

**Cookie không bao giờ rời trình duyệt.** Service worker chỉ *mượn* phiên để gọi API của sàn —
khác hẳn kiểu "gửi cookie về server".

Vì sao phải vậy: server (kể cả Crawlee) gọi API sản phẩm Shopee đều **403 / đá về login** —
đã đo. Đo 28/08/2026: IP VPS vào `shopee.vn/search` **luôn dính `verify/traffic`**, kể cả đã
đăng nhập.

> Docstring trong `shopee.py` nói extension chạy trên máy *từng người dùng*. Điều đó **chỉ còn
> đúng với người gọi ẩn danh**; mô hình hiện tại là **một máy-thợ dùng chung** (§7), và mục
> tiêu của dự án là chuyển hẳn Shopee sang server-side.

### 5.4 Chấm điểm — hai thang KHÁC NHAU, đừng trộn

`lib/ads/scoring.py`:

**(a) Thẻ QUẢNG CÁO — chấm theo "đời sống".** Ràng buộc trung thực quan trọng nhất: **không
nguồn nào công bố CVR**, đó là dữ liệu riêng của advertiser. `cvr_proxy` là **ước lượng**:

| Thành phần | Trọng số | Ý nghĩa |
|---|---|---|
| Đời quảng cáo (`_longevity`) | **0.55** | Advertiser không trả tiền tiếp cho quảng cáo lỗ. Bão hoà quanh **90 ngày** — quá một quý thì dài thêm không nói thêm gì |
| Số biến thể creative | 0.20 | |
| CTR | 0.15 | nói về *creative*, không nói về *offer* |
| Tương tác | 0.10 | |

**"CVR ước lượng" KHÔNG hiện trên thẻ quảng cáo**, dù thứ tự thẻ dựa vào nó. Với người đi tìm
sản phẩm để bán, một con số trộn sẵn không nói được gì mà số gốc — ngày chạy, biến thể, CTR,
đều in ngay trên thẻ — không nói rõ hơn.

**Độ tin cậy bám theo lượng bằng chứng thật**, để một điểm dựng từ một trường yếu không được
trình bày với cùng uy tín như điểm dựng từ bốn trường.

**(b) Thẻ SẢN PHẨM SÀN — chấm theo *cầu* + *chất lượng*.** Điểm này **CÓ hiện**, vì đó là con
số sàn công bố chứ không phải suy luận:

| Số có được | Thang | Vì sao |
|---|---|---|
| bán/tháng | `log10(monthly)/4×100` — ~10k/tháng ≈ 100 | số của chính sản phẩm |
| tổng đã bán | thấp hơn | không đo được đà |
| **lượt xem** (Etsy) | **thấp hơn hẳn** | *xem không phải mua*. Đo 08/09/2026: trung vị lượt xem (khác 0) là **65**, đỉnh **102.167**. Cho một sản phẩm 65 lượt xem ăn điểm ngang một sản phẩm 65 đơn/tháng là **nói dối về thị trường** |
| bán của **SHOP** | hạ thang | một shop bán 800 đơn không nói được sản phẩm *đang xem* bán bao nhiêu — nó có thể là mẫu ế nhất trong 68 mẫu |
| 回头率 của 1688 (% khách quay lại) | dùng được | trên sàn sỉ, người mua lại là người **bán lẻ đang bán được hàng** |

`relevance.py` — cụm từ có nằm trong chữ đọc được không: **XẾP HẠNG, không lọc**.
`imagematch.py` khớp bằng **pHash** (trùng gần như từng điểm ảnh), `clipmatch.py` khớp bằng
**CLIP** (cùng sản phẩm dù khác góc chụp).

### 5.5 Hai giới hạn phải nói với người dùng

1. **TikTok không search được theo từ khoá.** Creative Center chỉ mở chức năng này cho tài
   khoản đã đăng nhập; phiên ẩn danh nhận về **0 kết quả kèm mã thành công** — trông hệt như
   "sản phẩm không có nhu cầu". Gặp trường hợp này công cụ chuyển sang duyệt Top Ads theo CTR
   và **luôn kèm thông báo nói rõ**. Thấy thông báo đó thì **đừng kết luận về nhu cầu sản
   phẩm**, hãy nhìn phần Facebook.
2. **Chưa dùng proxy cho đa quốc gia.** Tìm kiếm chạy qua bộ lọc quốc gia của chính nền tảng —
   bạn thấy những gì **một người ở Việt Nam** nhìn thấy khi lọc theo nước đó, không phải những
   gì người bản địa nước đó nhìn thấy.

### 5.6 Region của tool Sản phẩm

Tool này **auto-tick VN**, nên tra PH ra lẫn kết quả VN. Chỗ sửa: `autoRegions` trong
`public/research/research.js`.

### 5.7 Video và `/api/media`

`GET /api/ads/video-keywords` rút cụm từ khoá ngắn từ tiêu đề sản phẩm dài (Gemini,
`keyword_extract.py`) rồi tìm video theo cụm đó. `/api/ads/tiktok-stats` và `/douyin-stats` lấy
số liệu video.

Video **KHÔNG lưu**: phát xuyên qua `GET /api/media`, có **danh sách host cho phép**
(`_match_host`), không ghi gì xuống đĩa. Link CDN có chữ ký và **hết hạn sau vài giờ** — mở lại
hôm sau thì search lại để lấy link mới.

Kalodata có `/video/detail/getVideoUrl` (**1 credit / video**) nhưng bảng Video dùng khung phát
chính thức `tiktok.com/player/v1/{id}` dựng thẳng từ id → **không cần biết creator, không tốn
credit**.

---

## 6. Mục **Trend Signal Hub** (`/trend-signal`) — TREND·SCOUT

Mục **độc lập**, database riêng, không dùng chung gì với nhóm Research.

### 6.1 Ba sàn thật

| Key | Nhãn | `country` |
|---|---|---|
| `shopee_vn` | Shopee VN | VN |
| `shopee_ph` | Shopee PH | PH |
| `1688` | 1688 | CN |

> File demo (`Trend Signal Hub/research-tool-demo (1).html`) ghi **"TikTok"** — đó là **viết
> nhầm cho 1688**. Đừng dựng nguồn TikTok cho mục này.

**Ngành VN và PH KHÔNG dùng chung mã.** Cây PH bằng tiếng Anh, `main_id`/`sub_id` khác hẳn VN
nên **không bắc cầu qua ID được**. Câu tiếng Việt hỏi ngành PH được nối bằng **bảng tay
`PH_ALIAS` trong `scout.py`** — không dịch máy. Vì vậy `TrendScout.tsx` **nhớ tab/sàn/cách xếp
nhưng KHÔNG nhớ ngành đang soi**: một mã ngành cũ của Shopee PH đem mở trên Shopee VN là một
lựa chọn không tồn tại.

### 6.2 Hai tab

| Tab | API | Cho ra |
|---|---|---|
| **Toplist** | `GET /api/hub/scout/toplist` | lấy nguyên thứ hạng của sàn, xếp theo `ban_chay` hoặc `doanh_so` |
| **Khám phá** | `GET /api/hub/scout/kham-pha` | lọc theo **lăng kính** |

`GET /api/hub/scout/nganh` trả cây ngành theo sàn · `GET|POST /api/hub/scout/config` đọc/ghi
các số ngưỡng (ô Tùy chỉnh).

**KHÔNG có bảng xếp hạng gộp sàn.** Cả "Bán chạy" lẫn "Doanh số" đều **tách riêng từng sàn**:
doanh số vì **VND/PHP/CNY không cộng được**; lượt bán vì **1688 là sàn SỈ**, số của nó lớn hơn
Shopee hàng chục lần nên gộp vào là nó chiếm sạch đầu bảng. Mỗi dòng luôn kèm nhãn sàn và tiền
gốc. CNY viết bằng ký hiệu **¥** cho khớp cột Giá vốn.

### 6.3 Năm lăng kính đang hiện

| Lăng kính | Điều kiện | Xếp theo |
|---|---|---|
| 📈 **Bán chạy** | nguyên thứ hạng lượt bán 30 ngày của sàn. Chỉ cần một lần quét | thứ hạng sàn |
| 🔥 **Đang tăng tốc** | tốc độ bán/ngày của 5 ngày gần nhất cao hơn 5 ngày trước đó. Phải đạt **CẢ HAI**: tăng ≥ **40%** VÀ đã bán lũy kế ≥ **1.000** | mức tăng |
| ⚡ **Đột biến** | tốc độ 1 ngày gần nhất vọt ≥ **500%** so với nền 5 ngày trước, và đã bán ≥ **1.000** lượt (loại tăng ảo) | mức vọt |
| 🎯 **Khe hở** | cầu đã chứng minh (bán nhiều và đều) nhưng listing dẫn đầu ngách **rating quá thấp** — cửa đang mở để làm hàng tốt hơn | doanh thu 5 ngày |
| 🆕 **Tân binh bán chạy** | mới xuất hiện trong ngành ≤ **7 ngày** mà đã bán ≥ **350** lượt. Hàng cũ vừa leo vào top ngành bị loại bằng phép thử **lũy kế ≈ lượt bán 30 ngày** | bán/ngày kể từ khi xuất hiện |

**"Đang tăng tốc" trước đây là HAI lăng kính** (`hot_gmv` doanh số + `hot_sold` lượt bán) cho ra
hai bảng gần trùng nhau; nay là MỘT, phải đạt cả hai điều kiện.

**💰 "Bán khoẻ ổn định" (`steady`) ĐÃ ẨN** khỏi giao diện 22/09/2026 cho **cả ba sàn** (mảng
`LENSES` dùng chung, không lọc theo sàn). Backend `scout.py` vẫn còn nhánh `steady` nguyên vẹn
— bỏ comment khối trong `frontend/lib/trendscout.ts` để hiện lại.

### 6.4 Cảnh báo quan trọng: lũy kế Shopee cập nhật TRỄ

**33% cặp ngày cho hiệu số = 0.** Hai lăng kính Đột biến và (đã ẩn) Ổn định đọc chênh lệch lũy
kế giữa hai ngày → **đo lại trước khi tin chúng**. Đây là lý do phải đối chiếu lũy kế, và là
một trong hai lý do `steady` bị ẩn.

### 6.5 Google Trends trong Hub: ĐÓNG BĂNG, không xoá

13/09/2026 bỏ Google Trends khỏi giao diện Hub, còn hai mục (TREND·SCOUT + One-shot AI). Dữ
liệu Trends **đóng băng, không xoá**; `sigtrends` đã ra khỏi lịch chạy.

**Bảng "đang tăng" của Trends cố ý KHÔNG hiện** (chốt 05/09/2026): Trends và lượt bán là **hai
thang đo khác nhau**, trộn vào là hỏng bảng xếp hạng.

### 6.6 Lịch cào đêm

`backend/hub/scheduler.py`. Giờ máy chủ, **chỉ còn ba job**:

| Giờ | Job | Làm gì |
|---|---|---|
| **01:00** | `sigcat` | top 100 mỗi ngành Shopee, **VN ‖ PH SONG SONG** (2 luồng) → `listings_snapshot` + `crawl_log`. Đo 11/09: **~3h50**, xong ~04:50 — trước giờ làm 08:30 |
| **06:00** | `dondep` | xoá dòng cào cũ hơn **90 ngày** |
| **09:00** | `sig1688` | top bán chạy **205 ngành** trên 1688, ~18 phút. **Đầu giờ làm việc CÓ CHỦ Ý** — 1688 đòi giải slider định kỳ, cần người trực |

**Bảy job của bản Printway** (`discover`, `listings`, `sales`, `shopnames`, `trends`, `unify`,
`report`) cùng `sigtrends` và `sigsnap` **đã ra khỏi lịch** — code còn, gọi tay được qua
`POST /api/hub/scheduler/run?job=<tên>`.

Vì sao: chúng nuôi phần Etsy/Amazon/gallery đã bỏ khỏi giao diện từ 06/09, vẫn cào mỗi đêm cho
dữ liệu không ai xem. Tệ hơn: `discover` và `trends` mỗi cái mở **một Chromium riêng ngay trong
lúc Shopee đang cào**. Đo 10/09: vòng VN chạy chồng như vậy **hụt trang 2 ở 58/199 ngành
(29%)**, trong khi vòng PH chạy một mình chỉ hụt **2%**.

**Tách LỊCH khỏi danh sách JOB** là điều kiện để tắt một job mà không phải xoá code nó.

### 6.7 Vận hành vòng cào — ba điều đã học

1. **Restart `ResearchSpyFrontend` làm ĐỨT tab máy-thợ**; restart backend thì **không**.
2. **Đếm `ok`, đừng đếm dòng nhật ký.** Số dòng log không bằng số lượt cào thành công.
3. **Hai vòng cào chạy SONG SONG được** — 2 luồng, ~3h50 cho cả 403 ngành.

---

## 7. **Máy-thợ** (relay) — trái tim vận hành

`app/api/relay.py` (lớp HTTP) + `lib/core/worker_relay.py` (hàng đợi, hạn giờ, danh sách loại
job được phép) + `frontend/public/worker/index.html` (trang mở trên máy-thợ).

**Vấn đề nó giải:** các sàn "Cách A" (Shopee, TikTok Shop, Taobao, 1688, Temu) chỉ trả dữ liệu
cho **phiên đăng nhập thật trong trình duyệt**; server tự crawl bị anti-bot chặn. Extension
chạy được nhưng kết quả **kẹt trong chính trình duyệt đó**, không có đường về server.

**Cách hoạt động:**

```
user → POST /api/relay/submit  (GIỮ KẾT NỐI MỞ tới khi có kết quả)
                ↓ hàng đợi
máy-thợ: trang /worker long-poll  GET /api/relay/next
                ↓ postMessage → extension → tab của sàn (same-origin)
máy-thợ → POST /api/relay/result  →  kết quả đi ngược về đúng user
```

Chính **kết nối đang mở** đó định tuyến về đúng user — không cần định danh gì thêm.

| Đường | Ai được gọi |
|---|---|
| `/submit` | **user đã đăng nhập** (401 khi JWT bật) — máy-thợ ở IP dân cư đã đăng nhập sàn, không thể mở cho ẩn danh trên VPS public |
| `/next`, `/result` | máy-thợ, gác bằng header `X-Worker-Token` = `RELAY_WORKER_TOKEN`. **Để trống thì mở cho bất kỳ ai** |
| `/status` | ai cũng được — cho giao diện biết có worker không, và bao nhiêu job đang chờ |

`worker_relay.py` nằm ở tầng `lib` chứ không ở `app` vì **`lib` cũng cần sai job xuống thợ**
(nguồn từ khoá Temu là chỗ đầu tiên), và `lib` không được import ngược lên `app`.

### 7.1 Vòng đời tab trong extension: GIỮ TAB, KHÔNG GIỮ TRANG

Đo trên máy-thợ 03/09/2026: Chrome chạy liền **6 ngày ngốn 1,66 GB**, hai renderer nặng nhất là
**301 MB** và **282 MB** — trang kết quả Amazon và Douyin của mấy hôm trước, vẫn còn nguyên DOM,
ảnh và timer JS. Nên:

| Cơ chế | Khi nào | Làm gì |
|---|---|---|
| `coolTab` | ngay sau khi trả kết quả | đưa tab về `about:blank` — renderer được giải phóng, **tab và phiên đăng nhập vẫn còn** (cookie nằm ở hồ sơ Chrome, không ở tab) |
| `reapTabs` | báo thức mỗi phút | đóng hẳn tab rảnh quá **10 phút**; các hàm trên tự mở lại khi cần |
| `openVerifyTab` | sàn bắt kéo slider | **MỘT** tab xác minh cho mỗi sàn, dùng lại |

Hai ngoại lệ của `reapTabs`, đều cố ý: tha tab **đang chạy job** (`busySlots` — một lượt tìm
nhiều cụm có thể lâu hơn 10 phút) và tha tab **đang hiện trước** (người vận hành đang giải
slider ở đó).

Tab **Shopee** hạ nhiệt về **trang chủ sàn** chứ không về trang trống: `handleFetch` (lấy giá
vốn) phải fetch same-origin nên tab cần nằm sẵn trên origin của sàn.

> **Tab id phải ghi ra `chrome.storage.session`, không để trong biến module.** Service worker
> MV3 bị treo sau ~30 giây rảnh và **biến biến mất theo** — nhưng tab thì không. Bản 0.3.0 giữ
> id trong biến, nên mỗi lần service worker sống lại nó **mở tab MỚI và bỏ rơi tab cũ**.

### 7.2 Hai "cổng" một sàn phải qua

1. **Login** — tài khoản giải quyết được
2. **Chữ ký chống bot** — tài khoản **KHÔNG** giải quyết được (cần navigate + intercept)

Shopee search: qua cổng 1. Shopee `find_similar` / TikTok Shop: **cổng 2, khó**. `page-hook.js`
chộp phản hồi mà **chính trang tự gọi** — dùng cho Taobao/Tmall/Temu, nơi request có chữ ký
(`mtop x5sec`, `anti-content`) mà mình không tự ký được. `similar-hook.js` làm điều tương tự
cho trang "sản phẩm tương tự" của Shopee.

---

## 8. **One-shot AI** (`/oneshot`)

Tách khỏi Trend Signal Hub 13/09/2026 (trước là tab thứ ba). `POST /api/hub/signal/ask` →
`hub/signal/ask.py`, vòng hội thoại giữ nguyên `lib/opportunity/demand_map.py` (đề xuất → hỏi
sàn → chấm lại).

### 8.1 Mặc định là TRÒ CHUYỆN (chốt 22/09/2026)

| Loại câu | Xử lý |
|---|---|
| **cần số** | xuống kho, lọc, rồi Gemini diễn giải phần đã lọc |
| **buôn bán khác** | Gemini trả lời tự nhiên — **cấm bịa số** |
| **ngoài lề** | vẫn từ chối |

### 8.2 LỌC TRƯỚC RỒI MỚI HỎI AI (chốt 14/09/2026)

Kho có ~70.000 dòng và lớn thêm ~52.000 dòng/ngày. Gửi hết cho Gemini là khoảng **3 triệu token
một câu hỏi** — vượt cửa sổ model và đốt sạch hạn mức bản miễn phí. Nhưng "sản phẩm nào bán
chạy nhất" là việc **SẮP XẾP**, mà kho làm việc đó trong **0,3 giây và 0 token**.

Nên: **kho lọc và xếp, Gemini chỉ đọc phần đã lọc (~1.000 token)** rồi diễn giải. Ngân sách:

| Hằng | Giá trị | Nghĩa |
|---|---|---|
| `TOP_BAN_CHAY` | 5 | top bán chạy **mỗi sàn** (tách khối, không gộp) |
| `TOP_DOANH_SO` | 4 | top doanh số mỗi sàn |
| `TOP_NGANH` | 5 | sản phẩm mỗi sàn trong một ngành được hỏi tới |
| `MAX_NGANH` | 2 | số ngành đưa vào, tính từ ngành khớp nhất |

Mỗi dòng tốn khoảng **30 token**.

### 8.3 Bỏ ô chọn sàn, thay bằng ĐỌC TÊN SÀN TỪ CÂU HỎI

Bỏ ô chọn mà không đọc câu hỏi là **mất hẳn cách nhắm sàn** — bản đầu mắc đúng lỗi đó: hỏi "top
sản phẩm trên Shopee VN" vẫn trả về bảng gộp ba sàn.

`scout.san_lien_quan` khớp tên sàn trong câu — **tất định, không gọi AI**. Câu có tên sàn → chỉ
lấy sàn đó; câu không nói → lấy cả ba. Ngoài regex còn có **khớp-mờ `TU_SAN_GAN`** để bắt cách
viết gần đúng.

### 8.4 Gemini KHÔNG có grounding

`google_search` trả **429**, nên One-shot AI **tự đi tìm web** qua `hub/signal/web.py` thay vì
dựa vào grounding của Gemini. Không có LLM thì tóm tắt **heuristic** từ chính số đó.

---

## 9. **Quản trị** (`/admin`) và đo hành vi người dùng

### 9.1 Quản lý người dùng

Gate **hai lớp**: client-side cho UX mượt (không token → `/login`, không phải admin → `/ads`),
nhưng **gate THẬT ở backend** — mọi `/api/admin/*` trả 403 nếu role sai, kể cả gọi bằng curl.

| Đường | Việc |
|---|---|
| `GET /api/admin/users` | `{ users, pending_count }` |
| `POST /api/admin/users` | tạo tay (duyệt sẵn) |
| `PATCH /api/admin/users/{id}` | `{ role }` \| `{ is_active }` \| `{ status }` |
| `DELETE /api/admin/users/{id}` | xoá — **phải gọi `favorites.xoa_theo_user()`** vì không có khoá ngoại |
| `GET|POST /api/admin/role-requests` + `/{id}/decide` | xin và duyệt nâng quyền |

### 9.2 Thống kê sử dụng

| Đường | Cho ra |
|---|---|
| `GET /api/admin/stats?period=today\|yesterday\|week\|month` | `{ current, previous, trends }` |
| `GET /api/admin/stats-by-user` | bảng **Theo nhân sự** / **Theo tool** |
| `GET /api/admin/user-activity?user_id=…` | timeline lịch sử của một người |

`today` = từ 0h hôm nay **giờ VN**, `yesterday` = trọn ngày hôm qua, `week`/`month` = cửa sổ
trượt 7/30 ngày. Backend cắt ngày theo giờ VN nên "hôm nay" đúng với người xem.

### 9.3 Định nghĩa "thành công" — quan trọng khi đọc số

**"Thành công" = lượt chạy RA KẾT QUẢ, kể cả khi kết quả là 0 dữ liệu.** Chỉ tính **FAIL khi có
lỗi thật** (`meta.status`). Một lượt tìm trả về bảng rỗng vì sản phẩm đó thật sự không có hàng
**không phải** là một lần tool hỏng.

### 9.4 Cách đo cắm ở đâu

* `frontend/lib/analytics.ts` + `components/layout/AnalyticsBoot.tsx` (đặt ở layout
  `(dashboard)` chứ không ở từng trang, để nhịp đo cấp phiên chạy cho **mọi** tool và
  `session_start` bắn **đúng một lần**)
* `POST /api/analytics/track` → bảng `analytics_event` bên Supabase
* `session_id` lưu `localStorage` nên **iframe `/research` đọc được cùng phiên**;
  `window.rsTrack` trong `research.js` bắn tới cùng endpoint
* `task_id` theo từng tool — **mở tool = một task mới**, event lẻ gom về đúng task

**FIRE-AND-FORGET: mọi lời gọi đều nuốt lỗi.** Mất 1–2 event tệ hơn treo một thao tác chính, và
**analytics KHÔNG bao giờ được phép làm hỏng tính năng**.

Bộ tên event phải khớp `_RUN_EVENTS` / `_LINK_EVENTS` trong `backend/app/api/admin.py`.

`/api/analytics/track` cố ý ở **gốc tên miền** (không `withBase`) — xem `lib/basePath.ts`.

### 9.5 Đăng xuất phải dọn `rs_bu` và `rs_bu_thresh`

Chúng là chính sách của **MỘT NGƯỜI**, không phải thiết lập của cái máy. Bỏ sót thì người đăng
nhập sau trên cùng trình duyệt (máy dùng chung ở văn phòng) **thừa hưởng ngưỡng xanh của người
trước**, và không có gì trên màn hình nói rằng con số ấy không phải của họ.

---

## 10. Hạ tầng dùng chung (`lib/core/`) — "không biết Facebook/TikTok là gì"

| File | Việc |
|---|---|
| `config.py` | cấu hình chung, nạp `.env.local` |
| `cache.py` | cache TTL **trong bộ nhớ**, `CACHE_TTL_MS=900000` (15 phút), trần 300 entry |
| `store.py` | kho **trên đĩa** cho kết quả tra cứu tốn kém (`DiskStore`) |
| `rate_limit.py` | hàng đợi giữ nhịp gọi ra ngoài (`*_MIN_INTERVAL_MS`) |
| `browser.py` | kho phiên trình duyệt, chạy theo "recipe" nguồn tự khai · `describe_browser_error` dịch lỗi cho đúng |
| `http.py` | gọi JSON cho nguồn không cần trình duyệt |
| `auth.py` | **hồ phiên đăng nhập Google: chọn, phạt, thưởng** — xem doc ③ |
| `mtop.py` | ký request cho cổng MTOP của Alibaba |
| `jwt_util.py` | phát/kiểm JWT |
| `worker_relay.py` | hàng đợi máy-thợ |
| `bu.py` | `BU_CHOICES` |
| `model.py` | nền chung cho kiểu đi ra API (đổi tên trường sang camelCase) |
| `jscompat.py` | những chỗ Python khác JavaScript — **ĐỌC KHI SỬA ĐIỂM SỐ** |

**Cache chia sẻ là lý do chính phải chạy MỘT server dùng chung cho cả team**: nhiều người search
cùng một sản phẩm sẽ nhân số request ra ngoài lên và làm IP chung bị chặn.

**Root logger PHẢI có handler** (`logging.basicConfig(..., force=True)` trong `app/main.py`).
Uvicorn chỉ cấu hình ba logger của chính nó; root không được gắn handler nào — nghĩa là mọi
`logging.getLogger(...)` rải khắp `lib/` và `hub/` **ghi ra rồi biến mất, kể cả `warning`**.
`force=True` vì uvicorn đã gọi `dictConfig` trước đó.

---

## 11. Thêm một nguồn mới

Hướng dẫn đầy đủ kèm ví dụ: [`CONTRIBUTING.md`](../../CONTRIBUTING.md). Tóm tắt:

| Loại | Làm gì |
|---|---|
| **Nguồn sản phẩm/quảng cáo** | tạo `backend/lib/ads/platforms/<tên>.py` kế thừa `AdPlatform` (`lib/ads/platform.py`) + thêm **một dòng** vào `platforms/__init__.py`. Không phải sửa route, giao diện, proxy media hay file cấu hình nào |
| **Nguồn từ khoá** | tạo `backend/lib/keywords/providers/<tên>.py` theo `provider.py` + một dòng vào `providers/__init__.py` |
| **Nguồn tìm-bằng-ảnh** | thêm một tầng trong `lib/imagesearch/`, khai trong `search.py` |

---

## 12. Quy ước code của dự án

* **Comment dài chỉ dành cho backend.** Frontend viết ít chú thích.
* **UI không tự thêm câu gợi ý.** Không tự sinh chữ hướng dẫn trên màn hình.
* **Mỗi con số trong comment phải là số ĐO ĐƯỢC**, kèm ngày đo. Số ước lượng thì nói rõ là ước
  lượng (ví dụ `SESSION_PENALTY_MS` — "nửa tiếng là ước lượng, KHÔNG phải con số đo được").
* **Mỗi thành phần điểm ghi lại lý do của mình** để người dùng kiểm chứng thay vì tin mù.
* **Không commit**: `.env*` (trừ `.example`), `node_modules/`, `.next/`, `__pycache__/`,
  `_archive/`, `.probe/`, `*.log`, `backend/.auth/`, `backend/database/`.

---

## 13. Đi tiếp

* Cài đặt và đưa lên tên miền → **[1-cai-dat-va-deploy.md](1-cai-dat-va-deploy.md)**
* Tài khoản và xử lý sự cố → **[3-tai-khoan-va-su-co.md](3-tai-khoan-va-su-co.md)**
* Nhật ký nghiên cứu từng nguồn (vì sao endpoint gọi được như vậy) → [`docs/`](..)
* Lộ trình và việc còn dở (bản 04/08/2026, đã cũ một phần) → [`docs/tai-lieu-ky-thuat/ban-giao.md`](../tai-lieu-ky-thuat/ban-giao.md)
