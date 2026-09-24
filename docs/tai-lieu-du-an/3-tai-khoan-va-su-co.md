# Bàn giao ③ — Tài khoản đăng nhập, tuổi thọ phiên, và xử lý khi phát sinh

> Trạng thái kiểm chứng: **24/09/2026** trên chính máy production.
>
> **Đọc phần này trước khi đọc bảng nào bên dưới.** Gần như mọi kiểu hỏng trong tài liệu này
> **KHÔNG báo lỗi**. Chúng trả về HTTP 200 kèm một danh sách rỗng, và người đọc kết luận nhầm
> rằng "sản phẩm này không có nhu cầu" hoặc "nguồn này không có dữ liệu". Đó là lý do mỗi
> nguồn ở đây đều có một **phép thử sống** riêng, và tại sao không được tin cột "không thấy
> lỗi nào".

---

## 0. Bảng tổng — mười thứ phải đăng nhập / cấu hình khi deploy

| # | Tài khoản / khoá | Cần cho | Ở đâu | Phiên sống bao lâu | Ai làm lại được |
|---|---|---|---|---|---|
| 1 | **Supabase** (project + service key) | đăng nhập webtool, phân quyền, analytics | `backend/.env.local` | **không hết hạn** (chỉ đổi khi rotate key) | dev |
| 2 | **Gemini API key** | One-shot AI, đọc ảnh, dịch nghĩa, rút từ khoá | `backend/.env.local` | **không hết hạn**, nhưng **quota theo ngày** | dev |
| 3 | **Google** (cho Google Trends) | mục Keyword, cột Lượng tìm | `backend/.auth/google*.json` + hồ sơ Chrome | **vài tuần → vài tháng**, không có mốc cứng · **bình chứa cạn theo giờ** | người vận hành, chạy script trên VPS |
| 4 | **Shopee VN + Shopee PH** | Trend Signal Hub, Sản phẩm, Từ khoá | **máy-thợ** (hồ sơ Chrome) | **nhiều tuần** nếu tab được mở đều | người vận hành, trên máy-thợ |
| 5 | **1688** | Trend Signal Hub (job `sig1688`), Từ khoá, giá vốn | **máy-thợ** | **nhiều tuần**, nhưng **đòi giải slider định kỳ** (gần như mỗi ngày) | người vận hành, trên máy-thợ |
| 6 | **Taobao** | Image Search (tầng Taobao) | **máy-thợ** | **ngắn nhất trong nhóm — vài ngày tới ~2 tuần** | người vận hành, trên máy-thợ |
| 7 | **Kalodata** | dữ liệu TikTok (sản phẩm + video) | **máy-thợ** + extension riêng | **theo phiên**, và **gói thuê bao trừ credit** | người vận hành |
| 8 | **YouTube Data API key** | nguồn video YouTube | `backend/.env.local` | không hết hạn · **10.000 quota/ngày (~100 search)** | dev |
| 9 | **Etsy** (keystring + shared secret) | nguồn Etsy | `backend/.env.local` | không hết hạn | dev |
| 10 | **SMTP** (Gmail app password) + Facebook cookie | mail cảnh báo captcha · ổn định hoá Facebook Ads Library | `backend/.env.local` | app password: **không hết hạn** · FB cookie: **vài tuần** | dev |

**Ba mức nghiêm trọng:**

| Mức | Nghĩa | Gồm |
|---|---|---|
| 🔴 **Chặn cả app** | thiếu là không ai vào được | Supabase |
| 🟠 **Chặn một mục** | mục đó rỗng hoặc chạy nửa vời | Google · Shopee · 1688 · Gemini |
| 🟡 **Mất một nguồn** | các nguồn khác vẫn chạy, có báo rõ | Taobao · Kalodata · YouTube · Etsy · Facebook · SMTP |

---

## 1. 🔴 Supabase — đăng nhập webtool

### Cần gì

```ini
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key>
JWT_SECRET=<chuỗi dài ngẫu nhiên, TỰ ĐẶT>
JWT_TTL_HOURS=168
ALLOWED_EMAIL_DOMAIN=tntecom.com
```

Ba bảng: `users`, `role_requests`, `analytics_event`.

### Tuổi thọ

`service_role` key **không hết hạn**. `JWT_TTL_HOURS=168` = **vé đăng nhập của user sống 7
ngày**, sau đó phải đăng nhập lại (chỉ cần nhập email, không mật khẩu).

### Hỏng thì trông như thế nào

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `/api/auth/login` trả **501** | thiếu `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` | điền `.env.local` rồi `Restart-Service ResearchSpyBackend` |
| **Vào app được mà không cần đăng nhập** | đúng cái 501 ở trên — frontend có **fallback dev** "coi như đã đăng nhập" | **nguy hiểm nhất trên production.** Xử như trên |
| Mọi request kèm token trả **401** | `JWT_SECRET` đã đổi → mọi vé cũ vô hiệu | user đăng nhập lại. **Đừng đổi `JWT_SECRET` khi không cần** |
| Đăng nhập rồi vẫn về `/login` | `localStorage` bị chặn hoặc bị xoá | thử cửa sổ thường (không private), kiểm `rs_token` trong DevTools |
| Không ai duyệt được user mới | admin/owner duy nhất mất quyền | sửa `role` thẳng trong bảng `users` trên Supabase |

> **`role` có ba bậc: `user` < `admin` < `owner`.** Đoạn code nào kiểm `=== 'admin'` sẽ khoá
> đúng người có nhiều quyền nhất ra khỏi trang Quản trị.

---

## 2. 🟠 Google — cho Google Trends (phần tinh tế nhất của cả hệ thống)

### 2.1 Vì sao phải đăng nhập

Đo **29/07/2026**: với phiên ẩn danh, widget `RELATED_QUERIES` của Google Trends trả **HTTP 200
kèm body 35 byte** — một danh sách rỗng — trong khi cùng từ khoá đó trên trình duyệt đã đăng
nhập thì hiện đầy đủ.

**Đây là kiểu chặn nguy hiểm nhất: nó không báo lỗi, nó trả về "không có gì".** Chính nó đã
từng khiến cả hướng đi này bị kết luận nhầm là "Trends không có dữ liệu cho cụm bán lẻ tiếng
Việt".

### 2.2 Đăng nhập — làm trên VPS, qua RDP, dưới tài khoản Administrator

```powershell
cd C:\AI-TNT-Research-SPY\backend
python -m scripts.auth.google_login
```

Script mở **một cửa sổ Chrome thật** và dừng lại chờ. Bạn **tự đăng nhập bằng tay** — script
không đọc, không nhập và không lưu mật khẩu. Nó chờ tới khi trình duyệt có cookie đăng nhập,
**gọi thật một lần vào Trends**, và **chỉ lưu phiên khi lời gọi đó trả về truy vấn thật**.

> Vì sao phải kiểm chứng bằng một lời gọi thật: **một file phiên hợp lệ về hình thức nhưng vô
> dụng khi chạy còn tệ hơn là không có file nào.**

Kết quả ghi ra `backend/.auth/google.json` (đã trong `.gitignore` — nó **tương đương một mật
khẩu đang mở**).

**Dùng tài khoản Google RIÊNG cho việc này, đừng dùng tài khoản chính hay tài khoản công ty.**
Tự động hoá Trends bằng phiên đăng nhập là thứ Google có thể gắn cờ, và hậu quả rơi vào đúng
tài khoản đó.

### 2.3 Tuổi thọ — hai chuyện khác nhau, đừng lẫn

| | Thời gian | Bản chất |
|---|---|---|
| **Bình chứa của một tài khoản** | cạn sau **vài lượt gọi**, nạp lại sau **~30 phút** (ước lượng) | bảng truy vấn liên quan trả rỗng, **tài khoản vẫn còn đăng nhập** |
| **Phiên đăng nhập** | **vài tuần tới vài tháng** — không có mốc cứng, phụ thuộc Google | phải chạy lại script |

`SESSION_PENALTY_MS = 30 phút` trong `lib/core/auth.py` là **ước lượng, KHÔNG phải con số đo
được** — chưa ai đo bình nạp lại mất bao lâu. Chọn thừa còn hơn thiếu: đặt ngắn quá thì cả hồ
bị đốt cùng lúc.

### 2.4 Hạn mức bám theo TÀI KHOẢN, không theo IP

Đo **14/08/2026**, phép đo do người dùng chạy — cùng IP, cùng lúc, cùng trình duyệt, **đổi đúng
một biến là tài khoản Google**: tài khoản đang dùng trả bảng rỗng, tài khoản khác trả bảng đầy
đủ.

> Trước đó đã kết luận **nhầm** "tài khoản không phải biến số", dựa trên việc cùng một tài khoản
> lúc 11:50 ra dữ liệu còn 11:52 thì rỗng. Cách đọc đúng là **bình chứa theo tài khoản, và bình
> rất nhỏ** — hai quan sát ấy không mâu thuẫn, chúng cùng đúng.

**Hệ quả:** xoay tài khoản là cách chia tải hợp lý; **proxy dân cư thì vô ích** vì IP đã được
chứng minh không phải biến số.

### 2.5 Thêm tài khoản vào hồ

**Nên có 2–3 tài khoản trong hồ, đừng để một.** Bình chứa bám theo tài khoản và rất nhỏ (§2.4),
nên một tài khoản duy nhất nghĩa là mục Keyword trả bảng rỗng mỗi khi bình cạn — mà nó cạn im
lặng, không báo lỗi. Đếm bằng:

```powershell
Get-ChildItem C:\AI-TNT-Research-SPY\backend\.auth\google*.json | Measure-Object | % Count
```

Thêm tài khoản:

```powershell
cd C:\AI-TNT-Research-SPY\backend
python -m scripts.auth.google_login --name 2 --no-verify
python -m scripts.auth.google_login --name 3 --no-verify
```

`--name <tên>` ghi ra `google-<tên>.json` và dùng **một hồ sơ Chrome RIÊNG**. `--no-verify` bỏ
bước gọi thật ở cuối — **nên dùng khi đang gom tài khoản**, vì bước kiểm chứng tiêu đúng một
suất của chính tài khoản vừa tạo, mà cái ta cần là giữ nó đầy.

**Không phải restart backend.** `session_paths()` **quét thư mục mỗi lần gọi**, nên file mới có
hiệu lực ngay ở lượt gọi kế tiếp.

### 2.6 Hồ chọn phiên THEO TRẠNG THÁI, không xoay vòng đều

Xoay vòng đều sẽ rải đều lượt gọi lên cả hồ và làm **mọi tài khoản cạn cùng lúc** — lúc đó có
mười tài khoản cũng như có một. `pick_session()`:

* phiên **đang bị phạt** → bỏ qua hẳn
* trong số còn lại → chọn phiên **nghỉ lâu nhất**
* cả hồ đang bị phạt → vẫn trả phiên **hết treo sớm nhất** (có thể bình đã nạp sớm hơn ước
  lượng; thử một lượt rẻ hơn nhiều so với từ chối phục vụ dựa trên một con số chưa đo)
* `penalise_session` khi trả bảng rỗng · `reward_session` khi lấy được dữ liệu

### 2.7 Kiểm tra hồ

```powershell
cd C:\AI-TNT-Research-SPY\backend
python -m scripts.auth.pool_status
```

**Bài kiểm quan trọng nhất là CỘT TRÙNG LẶP.** Đăng nhập ba lần rồi nhận về ba file phiên của
**CÙNG một tài khoản** là lỗi im lặng: mọi thứ trông đúng, hồ vẫn xoay, nhưng cả ba **chia
chung một bình** nên xoay cũng như không. Nó xảy ra khi hai lần đăng nhập dùng chung một hồ sơ
Chrome, hoặc khi Chrome tự đăng nhập lại tài khoản vừa dùng.

Nhận ra bằng cookie `SID` (mỗi tài khoản một giá trị). Script **không in giá trị đó** — nó
tương đương mật khẩu — chỉ in **vân tay băm tám ký tự** đủ để so hai file.

### 2.8 Khi Google THU HỒI phiên — phải dùng `--fresh`

```powershell
python -m scripts.auth.google_login --fresh
```

Cookie bị thu hồi **vẫn nằm nguyên trong hồ sơ Chrome và vẫn còn hạn cả năm** — nó chỉ mất hiệu
lực ở phía Google. Chạy lại kiểu thường khi đó **đi vào một cái bẫy**: script thấy cookie `SID`
có sẵn, kết luận "đã đăng nhập" ngay, và **bạn không bao giờ được đưa tới màn hình đăng nhập**.
`--fresh` xoá hồ sơ nên buộc phải đăng nhập thật.

### 2.9 Chrome THẬT, không phải Chromium đi kèm

Đo **04/08/2026** trên `trends.google.com.vn/explore` — cùng phiên, cùng máy, cùng IP, cùng
`storage_state`, chỉ khác bản trình duyệt:

| | Kết quả |
|---|---|
| **Chrome thật** (ẩn hoặc có cửa sổ) | **100 truy vấn liên quan** |
| Chromium đi kèm Playwright | **payload rỗng** |

Google **phân biệt được hai bản** và trả về rỗng cho bản đi kèm — im lặng, HTTP 200, không lỗi.
Phép đo này ngốn trọn một ngày đi tìm nguyên nhân ở phiên đăng nhập, ở tài khoản và ở giới hạn
tần suất. Nên **Chrome phải được cài trên VPS** (xem doc ① §1).

### 2.10 Cache lỗi CỐ Ý ngắn

`trends_related.py` **không cache thất bại 7 ngày**: phiên hết hạn được sửa trong hai phút, mà
cache lỗi bảy ngày sẽ **biến một lần đăng nhập lại thành một tuần tưởng như nguồn đã chết**.

### Triệu chứng → xử lý

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Cột "Lượng tìm" trống, không lỗi | bình của tài khoản đang cạn | chờ ~30 phút, hoặc **thêm tài khoản vào hồ** (§2.5) |
| "Google Trends hiện màn hình mời đăng nhập — phiên đã hết hạn" | phiên hết hạn | `python -m scripts.auth.google_login` |
| Chạy script mà **không thấy màn hình đăng nhập** | Google đã thu hồi, cookie cũ vẫn nằm đó | thêm `--fresh` |
| Có 3 file phiên mà vẫn cạn như một | ba file cùng một tài khoản | `pool_status` xem cột trùng lặp, đăng nhập lại bằng hồ sơ riêng |
| Trends rỗng **chỉ trên VPS**, máy dev thì tốt | thiếu Chrome thật, đang chạy Chromium đi kèm | cài Chrome (doc ① §1) |

---

## 3. 🟠 Máy-thợ — Shopee, 1688, Taobao, Temu, Kalodata

### 3.1 Vì sao KHÔNG đăng nhập trên VPS được — và đừng thử lại

Đo **04/09/2026** trên chính VPS, hai đường đều tắc, mỗi đường một lý do:

| Nguồn | Hỏng thế nào |
|---|---|
| **Google Lens** | lớp phủ mở được, ảnh thả được, rồi Google **đá thẳng sang `/sorry`** — chặn theo IP. Kết quả Lens **bám theo IP**: đó vừa là giá trị của nguồn (IP Việt Nam ra Shopee VN, Điện Máy XANH kèm giá VNĐ) vừa là lý do một IP datacenter không dùng được |
| **Taobao** | MTOP trả đúng mẫu chưa đăng nhập; cookie trong hồ sơ chỉ còn loại khách vãng lai |
| **Shopee** | Đo 28/08/2026: IP VPS vào `shopee.vn/search` **luôn dính `verify/traffic`**, kể cả đã đăng nhập |

Và một **nguyên nhân nền** làm cả hai không thể tự chữa tại chỗ:

> Backend chạy như Windows Service dưới **LocalSystem**, còn script đăng nhập tay chạy dưới
> **Administrator**. **Chrome mã hoá cookie bằng khoá DPAPI gắn theo tài khoản Windows**, nên
> phiên người vận hành dựng bằng tay **không đọc lại được từ phía service**.
>
> Dấu vết đo được: hai hồ sơ dựng từ 28/8 nhưng **không còn một cookie nào cũ hơn ngày đang
> đo** — mọi cookie đều do chính các lượt chạy của service tạo ra, trong khi cookie giữa hai
> lượt chạy CỦA SERVICE thì sống sót bình thường. **Tức là đăng nhập lại bằng tay cũng mất
> ngay, lần nào cũng vậy.**

**Kết luận: đừng mất thời gian đăng nhập Shopee/Taobao trên VPS.** Máy-thợ là cách giải, và nó
giải cả ba vấn đề: Chrome thật, máy thật, **IP dân cư**, đã đăng nhập sẵn.

> Mục tiêu của dự án là **chuyển Shopee sang server-side** để bỏ mô hình này. Chưa xong.
> Docstring trong `shopee.py` nói extension chạy trên máy từng người dùng — điều đó chỉ còn
> đúng với người gọi ẩn danh.

### 3.2 Dựng một máy-thợ — checklist

Máy-thợ là **một máy tính thường ở văn phòng** (IP dân cư), bật liên tục:

1. Cài **Chrome**
2. `chrome://extensions` → bật **Developer mode**
3. **Load unpacked** → chọn `extension/` (Research-SPY Fetcher) → **ghim lại**
4. **Load unpacked** → chọn `extension-kalodata/` (nếu cần dữ liệu TikTok)
5. **Đăng nhập từng sàn, mỗi sàn một tab:** `shopee.vn` · `shopee.ph` · `1688.com` ·
   `taobao.com` · `temu.com` · `kalodata.com`
6. Mở **`https://tntecom.com/research/worker/index.html`** và **GIỮ TAB ĐÓ MỞ**
   (phải đủ `index.html` — bỏ đi thì Next trả 308 rồi 404)
7. Kiểm: hai chấm **Extension** và **Kết nối server** phải xanh

Kiểm từ phía server:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/relay/status
```

### 3.3 Quy tắc vận hành máy-thợ

| Luật | Vì sao |
|---|---|
| **Restart `ResearchSpyFrontend` làm ĐỨT tab máy-thợ**; restart backend thì **không** | trang `/worker` được `next start` phục vụ |
| **Sửa extension KHÔNG tự lên theo deploy** — phải **Reload** ở `chrome://extensions` rồi **F5 tab máy-thợ** | Chrome vẫn chạy bản đã nạp |
| **Đếm `ok`, đừng đếm dòng nhật ký** | số dòng log không bằng số lượt cào thành công |
| **Hai vòng cào chạy SONG SONG được** (2 luồng, ~3h50 cho cả 403 ngành) | VN ‖ PH |
| **Đừng đóng tab đang hiện trước** | người vận hành có thể đang giải slider ở đó |
| **Nên đặt `RELAY_WORKER_TOKEN`** | không đặt thì `/next` + `/result` mở cho bất kỳ ai cướp job / nhét kết quả giả |

Extension tự dọn bộ nhớ: đưa tab về `about:blank` sau mỗi job (`coolTab`), đóng hẳn tab rảnh
quá 10 phút (`reapTabs`). Đo 03/09/2026: Chrome chạy liền 6 ngày **ngốn 1,66 GB** trước khi có
hai cơ chế này.

---

## 4. 🟠 Shopee VN + Shopee PH

| | |
|---|---|
| **Đăng nhập ở** | máy-thợ, tab `shopee.vn` và `shopee.ph` |
| **Phiên sống** | **nhiều tuần** nếu tab được dùng đều — cookie nằm ở hồ sơ Chrome, không ở tab, nên `coolTab` không làm mất phiên |
| **Dùng cho** | job `sigcat` (01:00, ~3h50), mục Sản phẩm, nguồn từ khoá Shopee, lấy giá vốn |

### Triệu chứng → xử lý

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| "Shopee trả 403 — extension chưa đăng nhập Shopee hoặc phiên đã hết hạn" | đúng như câu báo | đăng nhập lại tab Shopee trên máy-thợ |
| Nguồn Shopee **trống** mà không báo gì | chưa cài extension, hoặc `all_frames: true` bị mất | trang Sản phẩm **báo rõ ra** chứ không lặng lẽ bỏ trống — nếu nó báo "chưa cài extension" dù đã cài thì kiểm `all_frames` trong `manifest.json` |
| Vòng cào đêm hụt trang 2 nhiều ngành | có job khác mở Chromium riêng chạy chồng | đo 10/09: chạy chồng **hụt 29%** vs chạy một mình **hụt 2%**. Đừng thêm job vào khung 01:00–05:00 |
| Trend Signal Hub không có dữ liệu ngày mới | `sigcat` không chạy | kiểm `luong_dang_chay` (doc ① §3.1) |

### Cảnh báo khi đọc số Shopee

**Lũy kế Shopee cập nhật TRỄ — 33% cặp ngày cho hiệu số = 0.** Lăng kính Đột biến (và Ổn định
đã ẩn) đọc chênh lệch lũy kế giữa hai ngày → **đo lại trước khi tin chúng**.

---

## 5. 🟠 1688 — sàn duy nhất cần NGƯỜI TRỰC

| | |
|---|---|
| **Đăng nhập ở** | máy-thợ, tab `1688.com` |
| **Phiên sống** | **nhiều tuần** — nhưng **slider Baxia bật gần như mỗi ngày** |
| **Dùng cho** | job `sig1688` (09:00, ~18 phút, 205 ngành), nguồn từ khoá 1688, Image Search tầng 1688, giá vốn |

### 5.1 Vì sao job đặt vào ĐẦU GIỜ LÀM VIỆC

**Cố ý.** 1688 bật slider định kỳ và **CHỈ NGƯỜI giải được**. Đặt 09:00 để lúc nó bật thì có
người ở đó.

### 5.2 Sự cố 18/09/2026 và cơ chế sinh ra từ đó

Sáng 18/09, slider bật ở ngành thứ ~20 và **182/205 ngành hỏng liền một mạch** — vòng cào cứ
thế đi tiếp, mỗi ngành một lỗi `FAIL_SYS_USER_VALIDATE`. **Không ai biết cho tới khi nhìn bảng
lỗi.**

Đi tiếp là vô ích (slider đã bật thì ngành nào sau đó cũng hỏng); dừng hẳn thì phải chạy lại
tay. Nên cơ chế hiện tại là **chờ + báo mail**:

| Hằng | Giá trị | Nghĩa |
|---|---|---|
| `CHO_CAPTCHA_S` | **60 phút** | chờ người giải tối đa ngần này, vòng cào **tự chạy nốt** sau khi giải |
| `NHIP_THU_CAPTCHA_S` | **120 giây** | thử lại đúng ngành đang dở. **Không dày hơn**: mỗi lần thử lại extension mở lại tab xác minh với địa chỉ mới, thử dày quá thì **tab bị nạp lại đúng lúc người ta đang kéo** |
| `DUNG_SAU_DANG_NHAP` | **3** | ba lần liền thì là tường thật; một lần đơn lẻ có thể là trang xác minh thoáng qua |

### 5.3 Mail cảnh báo — PHẢI cấu hình, nếu không cả cơ chế trên là vô nghĩa

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<tài khoản gửi>
SMTP_PASS=<MẬT KHẨU ỨNG DỤNG, không phải mật khẩu đăng nhập>
SMTP_FROM=<địa chỉ gửi>
ALERT_EMAIL=aiteam.tnt@gmail.com
```

Gmail cần **"Mật khẩu ứng dụng"** (App Password), không phải mật khẩu thường. Nhiều người nhận
thì ngăn bằng dấu phẩy. **Thiếu `SMTP_USER`/`SMTP_PASS` thì KHÔNG gửi được và chỉ ghi log** —
không làm hỏng vòng cào, nhưng cũng **không ai biết 1688 đang chờ**.

`SMTP_FROM` để trống thì mặc định bằng `SMTP_USER`. `ALERT_EMAIL` để trống thì mặc định
`aiteam.tnt@gmail.com` (hằng `ALERT_EMAIL_MAC_DINH` trong `hub/canh_bao.py`) — đổi người nhận là
sửa biến đó rồi restart backend.

Muốn biết máy đang gửi từ đâu và gửi cho ai mà không lộ mật khẩu:

```powershell
Select-String -Path C:\AI-TNT-Research-SPY\backend\.env.local -Pattern '^(SMTP_USER|SMTP_FROM|ALERT_EMAIL)='
```

### 5.4 Khi nhận mail "1688 dính CAPTCHA"

1. Sang máy-thợ, tìm tab xác minh (extension mở **một** tab cho mỗi sàn, dùng lại)
2. **Kéo slider bằng tay**
3. Không làm gì thêm — vòng cào tự thử lại mỗi 2 phút và chạy nốt
4. Quá 60 phút không ai giải → vòng cào bỏ; chạy lại bằng
   `POST /api/hub/scheduler/run?job=sig1688`

---

## 6. 🟡 Taobao — phiên ngắn nhất

| | |
|---|---|
| **Đăng nhập ở** | máy-thợ, tab `taobao.com` |
| **Phiên sống** | **ngắn nhất trong nhóm — vài ngày tới ~2 tuần** |
| **Dùng cho** | Image Search tầng Taobao, nguồn từ khoá Taobao |

### Cái bẫy đặc thù: cookie sống LÂU HƠN phiên

Đo **13/09/2026**: cookie `tracknick`/`_nk_` **sống lâu hơn phiên thật**, nên phép thử cookie ở
`taobaoImageRun` **qua**, rồi Taobao bung hộp 密码登录 **che kín trang** — cú thả ảnh rơi vào
dưới hộp, **không API nào được gọi**, nguồn treo tới hết giờ.

Code nay đọc **cả iframe login lẫn chữ trong hộp** (`loginModal`), vì chữ nằm quá xa 400 ký tự
đầu của `body` để lọt vào phép thử cũ.

### Triệu chứng → xử lý

| Triệu chứng | Xử lý |
|---|---|
| "treo ở bước `<tên bước>` quá 80s" | mở tab `taobao.com` trên máy-thợ, xem có hộp đăng nhập không → đăng nhập lại |
| "mtop trả: …" / "trang chưa gọi API nào" | thường là phiên hết — đăng nhập lại |
| Tầng Taobao trống nhưng 1688/Alibaba/AliExpress vẫn có | **hỏng mềm, đúng thiết kế** — một lượt tìm không bao giờ trống trơn |

**Ngân sách thời gian:** máy-thợ dừng ở **80s** (`IMAGE_JOB_BUDGET_MS`), backend chờ tới **100s**
(`IMAGE_TIMEOUT_S`), chênh **12s** (`IMAGE_REPORT_MARGIN_MS`) để câu chẩn đoán về được tới
backend. **Đừng nâng ngân sách máy-thợ lên ≥ 100s** — backend sẽ bỏ cuộc trước và người dùng
nhận "hết giờ" trong khi máy-thợ vẫn đang chạy ngon lành.

Cũng có script đăng nhập tay, **nhưng chỉ hữu ích trên máy dev**:
`python -m scripts.auth.taobao_login` · `python -m scripts.auth.temu_login`.

---

## 7. 🟡 Kalodata — dữ liệu TikTok, và nó TIÊU TIỀN

| | |
|---|---|
| **Đăng nhập ở** | máy-thợ, `www.kalodata.com`, extension **riêng** (`extension-kalodata/`) |
| **Phiên sống** | **theo phiên** — nhưng cái đáng lo là **credit của gói thuê bao** |

### 7.1 Kiểm phiên KHÔNG tốn credit

Nút **Kiểm tra đăng nhập** trong bảng gọi `POST /user/features` — endpoint này **không nằm trong
nhóm bị trừ credit**. Nó cũng cho biết đang đi đường nào (fetch trực tiếp hay qua tab).

### 7.2 Phiên hỏng nhưng trả HTTP 200

Nếu cookie phiên là `SameSite=Lax` thì request từ extension **không mang cookie đi** và API trả
**200 kèm HTML đăng nhập**. Lúc đó extension **tự lùi về chạy trong tab** `www.kalodata.com`,
nơi fetch thành same-origin.

Vì Kalodata trả 200 khi phiên hỏng, code phân biệt "chưa đăng nhập" bằng **hình dạng phản hồi**
(bắt đầu bằng `<`) **chứ không bằng mã trạng thái**.

### 7.3 Điều gì tốn credit, điều gì không

| Tốn credit | Không tốn |
|---|---|
| `POST /product/searchList` · `POST /video/searchList` — **ăn quota y như bấm tay trên web** | ảnh: `img.kalocdn.com/tiktok.product/{id}/cover.png` — **public**, curl không cookie vẫn ra 200 |
| `GET /video/detail/getVideoUrl` — **1 credit / video** | khung phát `tiktok.com/player/v1/{id}` — dựng thẳng từ id |
| `KD_SWEEP` quét nhiều region — **credit nhân lên theo số region** | `POST /user/features` (kiểm phiên) · oEmbed của TikTok |

Hai chốt chặn: `KD_MAX_PAGES = 50` (trần cứng, chặn lỗi gõ `pages: 9999` đốt sạch credit) và
bảng **hỏi xác nhận** khi sắp gọi > 6 lượt `searchList`. **Bấm nút lần nữa là DỪNG** giữa chừng
— nút cố ý không bị disable, vì mỗi trang là một lần trừ credit.

### 7.4 Hai cái bẫy đã đo

**Nhầm khoá keyword là hỏng CÂM.** Gửi `title` cho product thì API vẫn trả `success: true` kèm
**danh sách rỗng**. Nên `kdCrawl` **tự chọn khoá theo `kind`** (`query` cho product, `title` cho
video), không để chỗ gọi truyền vào.

**Đổi nước bằng HTTP `header: country`, KHÔNG phải bằng body** — body bị bỏ qua hoàn toàn.
Header gắn trong `kdSend`. Sửa xong **phải Reload extension**. Và **TikTok phải dịch keyword
sang ngôn ngữ của nước** (PH = English) — làm ở `research.js`.

**Tiền là chuỗi đã rút gọn** (`"₫3,56tr"`). Số thô nằm ở `revenue_trend` (mảng theo ngày, cộng
lại bằng đúng `revenue` tới từng đồng) → dùng `revenue_raw`, **đừng parse chuỗi**.

`code 1053` = video đã gỡ/riêng tư, **không phải lỗi phiên**.

Region hợp lệ: `US GB ID VN TH MY PH SG MX DE FR IT ES JP BR`.

---

## 8. 🟡 Các khoá API — YouTube, Etsy, Gemini, Facebook

| Khoá | Lấy ở | Hạn mức | Thiếu thì |
|---|---|---|---|
| `YOUTUBE_API_KEY` | `console.cloud.google.com` → bật *YouTube Data API v3* → Credentials → API Key | **10.000 quota/ngày (~100 search)**, miễn phí | nguồn YouTube tắt (`keyword_search=false`), **không ảnh hưởng nguồn khác** |
| `ETSY_KEYSTRING` + `ETSY_SHARED_SECRET` | `etsy.com/developers/your-apps` (Personal App) | miễn phí | nguồn Etsy tắt. **Chỉ keystring → 403 "Shared secret is required"** — header là `x-api-key: keystring:shared_secret`, cần CẢ HAI |
| `GEMINI_API_KEY` | Google AI Studio | **quota theo ngày** ở bản miễn phí | One-shot AI rơi về tóm tắt heuristic; mất dịch nghĩa, đọc ảnh, rút từ khoá |
| `FB_COOKIE` | DevTools → Application → Cookies trên `facebook.com` (cần `c_user` **và** `xs`) | — | **tuỳ chọn** — Ads Library đọc được ẩn danh. Cookie của một **tài khoản phụ** làm kết quả ổn định hơn khi nhiều người search cùng lúc. Sống **vài tuần** |

### Gemini — hai điều phải biết

**Không có grounding.** `google_search` trả **429**, nên One-shot AI **tự đi tìm web**
(`hub/signal/web.py`). Đừng dựa vào grounding của Gemini.

**Đừng khai bừa tên model.** Đo 25/08/2026 trên khoá đang dùng: `gemini-2.5-flash` và
`gemini-2.0-flash` **đã bị Google gỡ** (404 "no longer available"), `gemini-pro-latest` trả
**429 hết quota**. Bản đang chạy: `GEMINI_MODEL=gemini-3.5-flash-lite`.

Muốn đổi nhà cung cấp khác (BytePlus Ark/DeepSeek, OpenAI, Qwen, GLM) thì khai `LLM_BASE_URL` +
`LLM_API_KEY`/`LLM_AUTH_TOKEN` + `MODEL_CHEAP`/`MODEL_SMART` — khai tường minh thì **thắng** khoá
Gemini. **Dùng tên `LLM_*`, KHÔNG dùng `ANTHROPIC_*`**: Claude Code đặt sẵn biến `ANTHROPIC_*`
trên máy và sẽ đụng nhau.

---

## 9. Lịch bảo dưỡng đề nghị

| Nhịp | Việc | Lệnh / nơi làm |
|---|---|---|
| **Mỗi ngày (sáng)** | xem mail cảnh báo captcha 1688; nhìn tab máy-thợ còn xanh không | hộp thư `aiteam.tnt@gmail.com` + máy-thợ |
| **Mỗi ngày (sau 10:00)** | `sig1688` chạy xong chưa | `/api/hub/scheduler/status` → `last_run.sig1688` |
| **Mỗi tuần** | `pool_status` — hồ Google còn mấy phiên, có trùng lặp không | `python -m scripts.auth.pool_status` |
| **Mỗi tuần** | sao lưu `hub_data.db` bằng `VACUUM INTO` | doc ① §8 |
| **Mỗi tuần** | đăng nhập lại Taobao trên máy-thợ (phiên ngắn nhất) | máy-thợ |
| **Mỗi tháng** | đăng nhập lại Shopee VN/PH + 1688 cho chắc | máy-thợ |
| **Mỗi tháng** | `/api/ads/health` — nguồn nào đang đỏ | PowerShell |
| **Mỗi tháng** | credit Kalodata còn bao nhiêu | `GET /api/credit/log/list` hoặc web Kalodata |
| **Khi nhận 429 Gemini nhiều** | xem lại quota, cân nhắc đổi model hoặc nhà cung cấp | `.env.local` |

---

## 10. Cây quyết định khi "tool hỏng"

```
Trang trắng / "Chưa kết nối được tầng dữ liệu"
    → backend chưa chạy.  Restart-Service ResearchSpyBackend
    → KHÔNG phải tool hỏng.

Vào được nhưng KHÔNG cần đăng nhập
    → Supabase chưa cấu hình (fallback dev).  §1

Một nguồn có chấm ĐỎ ở thanh trạng thái
    → sàn đổi cấu trúc.  Sửa backend/lib/ads/platforms/<tên>.py, KHÔNG file nào khác.

Một nguồn TRỐNG mà không báo lỗi          ← nguy hiểm nhất
    → gần như chắc chắn là phiên đăng nhập.
      · Cột Lượng tìm trống       → hồ Google.        §2
      · Shopee trống              → máy-thợ / 403.    §4
      · TikTok 0 kết quả          → BÌNH THƯỜNG, có thông báo kèm. Đọc §11
      · Tầng Taobao trống         → phiên Taobao.     §6
      · Kalodata trả mảng rỗng    → sai khoá keyword hoặc thiếu header country.  §7

Trend Signal Hub số không đổi nhiều ngày
    → lịch không chạy.  Kiểm luong_dang_chay (doc ① §3.1)

1688 hỏng hàng loạt cùng lúc
    → slider Baxia.  Kéo slider trên máy-thợ.  §5

Sửa code rồi mà vẫn sai y như cũ
    → extension chưa Reload, hoặc cache HTML.  doc ① §5.3 + §4.3

Trang Hub đầy số liệu nhưng số trông lạ
    → có thể đang là DỮ LIỆU MẪU nhúng cứng.  Gọi /api/hub/health xem status.
```

---

## 11. Bốn thứ KHÔNG phải sự cố — đừng đi sửa

1. **TikTok trả 0 kết quả kèm thông báo.** Creative Center chỉ mở search theo từ khoá cho tài
   khoản đã đăng nhập; phiên ẩn danh nhận **0 kết quả kèm mã thành công**. Công cụ chuyển sang
   duyệt Top Ads theo CTR và **luôn kèm thông báo nói rõ**. Thấy thông báo đó thì **đừng kết
   luận về nhu cầu sản phẩm** — nhìn phần Facebook.

2. **Video mở lại hôm sau không phát được.** Link CDN **có chữ ký và hết hạn sau vài giờ**.
   Media phát xuyên qua `/api/media`, **không lưu gì xuống đĩa**, cố ý. Search lại để lấy link
   mới.

3. **`tntecom.com` (không có `/research`) trả 404.** Caddy **cố ý** trả lời rõ *"chưa có gì ở
   địa chỉ này. Research SPY nằm ở /research"* thay vì để trắng — để người gõ thiếu biết mình
   gõ thiếu chứ không tưởng server chết.

4. **Lens / Taobao trống khi máy-thợ offline.** Các nguồn HTTP thuần (1688, Alibaba.com,
   AliExpress) và tầng đọc ảnh vẫn chạy, nên **một lượt tìm không bao giờ trống trơn** — đúng
   thiết kế "hỏng mềm".

---

## 12. Bảo mật — những chỗ dễ làm sai

| Việc | Luật |
|---|---|
| `backend/.auth/*.json` | **tương đương mật khẩu đang mở.** Trong `.gitignore`. Đừng chép ra ngoài, đừng đưa vào ticket |
| `backend/.env.local` | không commit. Khi cần chia sẻ khoá thì gửi qua kênh bí mật, không dán vào chat |
| `pool_status` | **không in giá trị `SID`**, chỉ in vân tay băm 8 ký tự — giữ nguyên thiết kế đó |
| Danh sách Yêu thích | thứ riêng tư nhất trong app (nó nói người ta đang định bán gì). PATCH/DELETE trả **404 chứ không 403** — 403 đã là một câu xác nhận rằng dòng ấy tồn tại. **Kể cả admin không đọc được của người khác** |
| `RELAY_WORKER_TOKEN` | để trống = ai cũng cướp được job và nhét kết quả giả. **Nên đặt** |
| Tài khoản Google cho Trends | **tài khoản riêng**, không phải tài khoản chính hay tài khoản công ty. Google có thể gắn cờ, và hậu quả rơi vào đúng tài khoản đó |
| Xoá user ở Quản trị | **phải dọn cả `favorite_product`** — không có khoá ngoại giữa SQLite và Supabase |

---

## 13. Đi tiếp

* Cài đặt và deploy → **[1-cai-dat-va-deploy.md](1-cai-dat-va-deploy.md)**
* Chức năng và logic → **[2-chuc-nang-va-logic.md](2-chuc-nang-va-logic.md)**
* Đặc tả API Kalodata → [`docs/kalodata-api.md`](../kalodata-api.md)
* Nguồn dữ liệu từng sàn, và giá có thật không → [`docs/nguon-du-lieu-tung-san.md`](../nguon-du-lieu-tung-san.md) · [`docs/gia-ban-co-that-khong.md`](../gia-ban-co-that-khong.md)
