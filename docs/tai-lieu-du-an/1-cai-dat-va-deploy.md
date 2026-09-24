# Bàn giao ① — Cài đặt và đưa lên tên miền, từ `git clone` tới `https://tntecom.com/research/`

> Trạng thái kiểm chứng: **24/09/2026**, đo trên chính máy production.
> Bản đang chạy thật: `https://tntecom.com/research/` · VPS Windows `157.66.101.73`.

## Cách dùng tài liệu này

Đây là **dàn ý để đưa cho Claude Code làm**, nhưng một nửa công việc thì **AI không làm được** —
không phải vì khó, mà vì chúng đòi tài khoản thật, thẻ thanh toán thật, giải CAPTCHA, và một cái
máy vật lý ở văn phòng luôn bật. Nên mỗi mục ở đây đều gắn nhãn:

| Nhãn | Nghĩa |
|---|---|
| 🤖 **AI** | Giao cho Claude Code, nó chạy được một mình |
| 👤 **NGƯỜI** | **Chỉ người làm được.** AI sẽ dừng lại và chờ ở đúng chỗ này |
| 🤝 **CẢ HAI** | Người làm một bước (lấy khoá, kéo slider), AI làm phần còn lại |

Thứ tự trong tài liệu là **thứ tự nên làm**. Đọc §1 trước để biết sẽ phải tự tay làm những gì —
nhiều việc trong đó cần xin quyền, chờ duyệt, hoặc mất tiền, nên biết sớm thì đỡ tắc giữa đường.

Mỗi phần ghi *làm gì* + *vì sao*, vì gần hết những cái bẫy ở đây đều **hỏng lặng lẽ**: trang vẫn
mở, vẫn có số, chỉ là số sai hoặc số cũ.

---

## 0. Bản đồ một phút

Ba tiến trình, đều là Windows Service do **nssm** dựng, đều chạy dưới **LocalSystem**, đều
`Automatic` (tự bật khi VPS khởi động lại):

| Service | Chạy cái gì | Cổng | Ra ngoài Internet? |
|---|---|---|---|
| `ResearchSpyBackend` | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` | 8000 | **không** — kín trong máy |
| `ResearchSpyFrontend` | `node .../next/dist/bin/next start -H 0.0.0.0 -p 3000` | 3000 | qua Caddy |
| `ResearchSpyCaddy` | `caddy run --config C:\AI-TNT-Research-SPY\deploy\Caddyfile` | 80/443 | **có** |

Đường đi của một request:

```
trình duyệt  →  Caddy :443  →  next start :3000  →  (rewrite /api/*)  →  uvicorn :8000
                  ↑ HTTPS            ↑ basePath = /research              ↑ FastAPI + SQLite
```

Nhưng **ba service không phải toàn bộ hệ thống**. Còn hai thứ nằm ngoài VPS và không service
nào thay được:

```
        ┌─ VPS 157.66.101.73 ─────────────────┐
        │  Caddy · Next · FastAPI · SQLite    │
        │  + phiên Google (.auth/google*.json)│
        └──────────────┬──────────────────────┘
                       │ /api/relay/*
        ┌──────────────┴──────────────────────┐
        │  MÁY-THỢ — máy thật ở văn phòng,     │  ← §7.2
        │  IP dân cư, Chrome mở suốt, đã đăng  │
        │  nhập Shopee/1688/Taobao/Kalodata    │
        └─────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────────────┐
        │  SUPABASE (cloud) — users, quyền,    │  ← §3.1
        │  analytics                           │
        └─────────────────────────────────────┘
```

Ba điều **cố ý** và đừng "sửa cho gọn":

1. **`basePath = /research`** (`frontend/next.config.mjs`). Webtool không được chiếm gốc tên
   miền vì `tntecom.com` còn nhiều tool khác.
2. **`/api/*` ở LẠI GỐC tên miền** (`basePath: false` trong `rewrites()`), không đi theo
   `/research`. Lý do: `<video src="/api/media?...">` phải cùng origin để Range + cache đi qua
   được. **Hệ quả cho tool sau: `/api` ở gốc ĐÃ BỊ CHIẾM**, tool thứ hai phải dùng `/tool2/api`.
3. **Chỉ một tiến trình backend.** Cache và kho phiên trình duyệt nằm trong RAM. `--workers`
   nhân số request ra ngoài lên đúng bằng số worker — chính là thứ làm IP chung bị chặn. Và
   trên Windows `--workers`/`--reload` còn làm chết Playwright (xem §10).

---

## 1. Phân vai — AI làm gì, người phải tự làm gì

### 1.1 🤖 Giao hết cho Claude Code được

| Việc | Ở mục |
|---|---|
| `git clone`, checkout nhánh `Titus` | §4 |
| Điền `backend/.env.local` **sau khi người đã đưa khoá** | §4.1 |
| `pip install`, `npm install`, `playwright install`, `next build` | §5 |
| Tạo ba Windows Service bằng nssm, đặt biến môi trường | §5, §5.1 |
| Viết/sửa `Caddyfile`, cài Caddy làm service, `caddy reload` | §6 |
| Mở cổng ở **firewall Windows** | §5, §6.1 |
| Build lại + restart service sau khi sửa code | §9 |
| Chạy `compileall`, `import app.main`, smoke test, đọc log | §11.1, §13 |
| Sao lưu `hub_data.db` bằng `VACUUM INTO` | §12 |
| Chẩn đoán: `/api/health`, `/api/ads/health`, `scheduler/status`, `relay/status` | §13 |

### 1.2 👤 AI KHÔNG làm được — bắt buộc người

| Việc | Vì sao AI không làm được | Ở mục |
|---|---|---|
| **Tạo project Supabase** | cần tài khoản + xác minh email của công ty | §3.1 |
| **Chạy 4 file SQL trong Supabase** | service key đi qua PostgREST, **không chạy được `CREATE TABLE`**; phải dán vào SQL Editor trên web | §3.1 |
| **Tạo tài khoản admin đầu tiên** | mọi lượt đăng ký đều ra `role=user, status=pending`, mà **người duyệt lại phải là admin** — vòng tròn, chỉ gỡ được bằng tay trong Supabase | §3.2 |
| **Lấy khoá Gemini / YouTube / Etsy** | đăng nhập Google Cloud, Etsy Developers, AI Studio — tài khoản của công ty | §3.3 |
| **Lấy `FB_COOKIE`** | phải đăng nhập Facebook bằng một tài khoản phụ rồi copy cookie từ DevTools | §3.3 |
| **Tạo Gmail App Password cho SMTP** | trong phần bảo mật tài khoản Google, cần 2FA | §3.3 |
| **Trỏ DNS ở Cloudflare** | tài khoản Cloudflare của công ty, và **sai một bản ghi là sập email Lark** | §3.4 |
| **Mở cổng 80/443 ở panel VPS** | tài khoản nhà cung cấp (vpssieutoc) | §3.4 |
| **Đăng nhập Google cho Trends** | Google hỏi mật khẩu + 2FA + có thể CAPTCHA. Script mở cửa sổ Chrome rồi **chờ người tự gõ** | §7.1 |
| **Dựng máy-thợ**: cài extension, đăng nhập 6 sàn, **giữ tab mở** | cần một máy vật lý ở văn phòng có IP dân cư; AI không có máy đó, và không đăng nhập hộ tài khoản sàn | §7.2 |
| **Mua/gia hạn gói Kalodata** | thanh toán | §3.3 |
| **Kéo slider Baxia của 1688** | CAPTCHA — cố tình thiết kế để chỉ người giải được | §8.4 |
| **Duyệt user mới hằng ngày** | quyết định ai được dùng là quyết định của con người | §8.2 |

> **Đọc bảng trên như một danh sách mua sắm.** Gom đủ nó trước rồi mới gọi AI vào cài, thì cả
> quá trình là một buổi. Thiếu giữa đường thì mỗi lần thiếu là một lần chờ xin quyền.

---

## 2. Máy cần có gì trước — 🤖 AI kiểm, 👤 người cài nếu thiếu

| Thứ | Bản đang chạy | Ghi chú |
|---|---|---|
| Windows Server | 2022 Standard | Windows 10/11 cũng được |
| Python | **3.12.7** | lúc cài phải tick *Add python.exe to PATH* |
| Node.js | **24.20.0** | LTS ≥ 20 là đủ |
| **Google Chrome thật** | 153.0.8010.54 | **BẮT BUỘC**, không thay bằng Chromium — xem §10 |
| Git | bất kỳ | `C:\AI-TNT-Research-SPY` phải là **bản clone git**, không phải .zip giải nén |
| RAM | ≥ 8 GB | mỗi phiên Chrome ăn 0,4–0,7 GB, trần mềm 4 phiên (`BROWSER_POOL_MAX`) |
| Đĩa | ≥ 30 GB trống | `hub_data.db` hiện **349 MB** và lớn thêm ~52.000 dòng/ngày |
| **Quyền Administrator** | | cần để tạo service + mở firewall |

Ngoài VPS, còn cần **một máy tính ở văn phòng** làm máy-thợ (§7.2): Chrome, IP dân cư (mạng
văn phòng bình thường là được), và **bật suốt ngày làm việc**.

---

## 3. 👤 NGƯỜI: chuẩn bị trước khi gọi AI vào cài

Bốn việc dưới đây phải xong trước. AI không làm được việc nào trong số này.

### 3.1 Supabase — tạo project và chạy 4 file SQL

Supabase giữ **`users`, `role_requests`, `analytics_event`**. Thiếu nó thì `/api/auth/login`
trả **501** và frontend rơi về chế độ dev "coi như đã đăng nhập" — **tuyệt đối không để trạng
thái đó lên production**.

1. Tạo project ở `supabase.com` (bản miễn phí đủ dùng).
2. **SQL Editor** → dán và Run **bốn file, ĐÚNG THỨ TỰ NÀY**. Thứ tự không phải tuỳ ý: file sau
   `ALTER TABLE` bảng mà file trước tạo ra, và file 4 `CREATE TABLE role_requests` sau khi đã
   dọn cột `bu`. Cả bốn đều **idempotent** — chạy lại nhiều lần không lỗi.

   | # | File (trong `docs/tai-lieu-ky-thuat/`) | Dựng ra |
   |---|---|---|
   | 1 | `supabase-schema.sql` | bảng `users` + `analytics_event` + index |
   | 2 | `supabase-migration-approval.sql` | cột `status` (`pending`/`approved`/`rejected`) |
   | 3 | `supabase-migration-email-profile.sql` | cột `email`, `full_name`, `position`, `bu` |
   | 4 | `supabase-migration-owner-bu.sql` | vai trò `owner`, CHECK bốn mã BU, bảng `role_requests` |

3. **Settings → API** → copy hai thứ, đưa cho AI để nó điền vào `.env.local`:
   * `SUPABASE_URL` — dạng `https://<project>.supabase.co`
   * `SUPABASE_SERVICE_KEY` — khoá **`service_role`**, không phải `anon`

> ⚠️ `service_role` **vượt qua mọi Row Level Security**. Nó chỉ được nằm ở `backend/.env.local`
> trên server, không bao giờ đi vào frontend, không dán vào chat hay ticket.

### 3.2 Tài khoản admin đầu tiên — cái bẫy con-gà-quả-trứng

**Đây là chỗ dễ tắc nhất của cả quá trình, và nó không có lối thoát nào trong giao diện.**

`app/api/auth.py::register` **luôn** tạo bản ghi `role: "user"`, `status: "pending"` — không có
ngoại lệ cho người đầu tiên. Mà người duyệt `pending` lại phải là `admin`/`owner`. Nên nếu chỉ
dùng giao diện, **không ai vào được app, mãi mãi**.

Gỡ bằng tay, một lần:

1. Mở `https://tntecom.com/research/login`, đăng ký bằng email `@tntecom.com` của bạn, khai
   Tên · Vị trí · BU. Màn hình sẽ nói "chờ duyệt" — đúng như vậy, đừng chờ.
2. Supabase → **Table Editor** → bảng `users` → tìm dòng email của bạn → sửa **hai cột**:
   * `role` → `owner`
   * `status` → `approved`
3. Quay lại trang login, nhập lại email → vào được, và sidebar hiện thêm nhóm **Quản trị**.
4. Từ đây mọi user sau **duyệt được trong giao diện** `/admin`, không cần mở Supabase nữa.

> Dùng `owner` chứ không phải `admin` cho người đầu tiên: `owner` là bậc cao nhất
> (`user` < `admin` < `owner`), và nó là vai duy nhất chắc chắn không bị người khác hạ quyền.

### 3.3 Sáu khoá cần đi lấy — lấy ở đâu, thiếu thì mất gì

| Khoá | Lấy ở | Mất gì nếu thiếu | Bắt buộc? |
|---|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio | One-shot AI rơi về tóm tắt heuristic; mất dịch nghĩa, đọc ảnh, rút từ khoá | **gần như bắt buộc** |
| `JWT_SECRET` | **tự đặt** — một chuỗi dài ngẫu nhiên | không đăng nhập được | **bắt buộc** |
| `YOUTUBE_API_KEY` | `console.cloud.google.com` → bật *YouTube Data API v3* → Credentials → API Key | nguồn YouTube tắt (10.000 quota/ngày, miễn phí) | không |
| `ETSY_KEYSTRING` + `ETSY_SHARED_SECRET` | `etsy.com/developers/your-apps` (Personal App) | nguồn Etsy tắt. **Phải có CẢ HAI** — chỉ keystring thì 403 "Shared secret is required" | không |
| `SMTP_USER` + `SMTP_PASS` | Gmail → **Mật khẩu ứng dụng** (App Password, cần bật 2FA trước), **không phải** mật khẩu đăng nhập | **không ai biết 1688 dính CAPTCHA** — vòng cào chờ 60 phút rồi bỏ | **nên có** |
| `FB_COOKIE` | DevTools → Application → Cookies trên `facebook.com`, cần `c_user` **và** `xs`. Dùng **tài khoản phụ** | Facebook Ads Library vẫn đọc được ẩn danh, chỉ kém ổn định khi nhiều người search cùng lúc | không |

Cộng thêm một thứ **mất tiền**: **gói Kalodata** cho dữ liệu TikTok (§8.3). Không có thì mục
TikTok trong tool Sản phẩm không có số.

Đưa cả xấp này cho AI một lần, nó điền vào `backend/.env.local` rồi restart backend.

### 3.4 Tên miền và tường lửa ngoài VPS

**`tntecom.com` dùng nameserver Cloudflare, KHÔNG phải iNet.** Bảng bản ghi bên iNet vẫn cho
lưu nhưng hoàn toàn vô tác dụng — sửa ở đó là sửa vào chỗ không ai đọc.

> ⚠️ **Cloudflare đang giữ cả bản ghi MX cho email Lark.** Dọn "bản ghi lạ" ở đó là có thể
> **sập email toàn công ty**. Chỉ thêm/sửa đúng bản ghi mình cần, không xoá gì khi chưa hỏi.

Hai việc, làm **trước khi** AI cài Caddy:

1. **Cloudflare**: bản ghi `A` của `tntecom.com` → `157.66.101.73`
2. **Panel nhà cung cấp VPS (vpssieutoc)**: mở cổng **80** và **443**. Firewall Windows thì AI
   mở được, nhưng tường lửa ở panel thì không — và thiếu nó thì Let's Encrypt không gọi ngược
   về được, HTTPS **hỏng lặng lẽ**: Caddy cứ thử lại theo chu kỳ, không báo gì lên trang.

---

## 4. 🤖 Clone và cấu hình

```powershell
git clone https://github.com/Digital-Transformation-TNT/Research-SPY.git C:\AI-TNT-Research-SPY
cd C:\AI-TNT-Research-SPY
git checkout Titus
```

> **Nhánh làm việc là `Titus`, không phải `main`.** `main` chỉ là bản mirror (fast-forward từ
> `Titus`) để Dependabot soi nhánh mặc định. Đồng bộ lại khi cần:
> `git push origin Titus:main`.

### 4.1 File cấu hình — thứ DUY NHẤT không có trong git

```powershell
Copy-Item backend\.env.example backend\.env.local
notepad backend\.env.local
```

`backend/.env.example` dài ~450 dòng và **chính nó là tài liệu** cho từng biến — đọc comment
trong đó thay vì đoán. Chia theo mức cần thiết:

| Nhóm | Biến | Ai cung cấp | Thiếu thì sao |
|---|---|---|---|
| **Đăng nhập** | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `JWT_SECRET`, `ALLOWED_EMAIL_DOMAIN=tntecom.com`, `JWT_TTL_HOURS=168` | 👤 §3.1, §3.3 | `/api/auth/login` trả **501**, app mở cho mọi người |
| **AI** | `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.5-flash-lite` | 👤 §3.3 | One-shot AI rơi về heuristic |
| Nguồn cần khoá | `YOUTUBE_API_KEY`, `ETSY_KEYSTRING` + `ETSY_SHARED_SECRET`, `FB_COOKIE` | 👤 §3.3 | nguồn đó tắt, có báo ở thanh trạng thái |
| Cảnh báo vận hành | `SMTP_HOST/PORT/USER/PASS/FROM`, `ALERT_EMAIL` | 👤 §3.3 | **1688 dính slider mà không ai biết** |
| Proxy TikTok | `TIKTOK_PROXY_*`, `TIKTOK_FREE_PROXY` | 👤 nếu có mua | TikTok chỉ tra được ở thị trường nhà (`TIKTOK_HOME_MARKET=VN`) |
| Máy-thợ | `RELAY_WORKER_TOKEN` | 🤖 tự sinh chuỗi ngẫu nhiên | `/api/relay/next` + `/result` mở cho bất kỳ ai — **nên đặt**, và nhớ đưa chuỗi đó cho người dựng máy-thợ (§7.2) |
| Nhịp & cache | `CACHE_TTL_MS=900000`, `*_MIN_INTERVAL_MS`, `BROWSER_POOL_MAX=4`, `HEADLESS=true` | 🤖 | dùng mặc định là được |

`frontend/.env.local` **thường không cần**. Chỉ tạo khi backend nằm ở máy khác:
`BACKEND_URL=http://<ip>:8000`.

---

## 5. 🤖 Dựng máy lần đầu — một lệnh

```powershell
cd C:\AI-TNT-Research-SPY\deploy
Set-ExecutionPolicy -Scope Process Bypass -Force
.\vps-setup.ps1 -Root C:\AI-TNT-Research-SPY
```

Script (`deploy/vps-setup.ps1`) làm, theo thứ tự: dò Python + Node → `pip install -r
requirements.txt` → `playwright install chromium` → `npm install` + `npm run build` → mở cổng
3000 ở firewall Windows → tải nssm → tạo/ghi đè hai service `ResearchSpyBackend` và
`ResearchSpyFrontend` rồi start. **Chạy lại nhiều lần được**, service cũ bị gỡ rồi tạo lại.

### 5.1 Hai biến môi trường của service PHẢI đặt bằng tay sau đó

`nssm set ... AppEnvironmentExtra` **THAY THẾ** cả danh sách chứ không cộng thêm. Nghĩa là đặt
`HUB_SCHEDULER` một mình sẽ **xoá mất** `PLAYWRIGHT_BROWSERS_PATH` mà `vps-setup.ps1` đã đặt, và
ngược lại. Luôn đặt cả hai trong **MỘT lệnh**:

```powershell
cd C:\AI-TNT-Research-SPY\deploy
.\nssm.exe set ResearchSpyBackend AppEnvironmentExtra HUB_SCHEDULER=1 PLAYWRIGHT_BROWSERS_PATH=C:\ms-playwright
Restart-Service ResearchSpyBackend
```

| Biến | Vì sao |
|---|---|
| `HUB_SCHEDULER=1` | Lịch cào đêm **mặc định TẮT trong code** — một máy dev bật backend lên để sửa CSS không được tự đi cào Shopee bốn tiếng. Thiếu nó trên production thì **database đóng băng mà không ai biết**: `/api/hub/scheduler/status` vẫn báo `enabled: true`. **Kiểm bằng `luong_dang_chay`, không bằng `enabled`.** |
| `PLAYWRIGHT_BROWSERS_PATH=C:\ms-playwright` | `playwright install` mặc định cất Chromium vào `%LOCALAPPDATA%` của **người chạy lệnh** (Administrator), còn service chạy dưới **LocalSystem** — tài khoản đó không thấy thư mục ấy. Xem §10 để biết cái này làm hỏng gì. |

Rồi cài Chromium vào đúng chỗ dùng chung:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "C:\ms-playwright"
cd C:\AI-TNT-Research-SPY\backend
python -m playwright install chromium
```

Kiểm:

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/api/hub/scheduler/status).luong_dang_chay   # phải là True
Test-Path C:\ms-playwright                                                          # phải là True
```

---

## 6. 🤝 Đưa ra tên miền — Caddy

Caddy **không** nằm trong `vps-setup.ps1`, dựng bằng tay một lần. Bản đang chạy:
`C:\Caddy\caddy.exe`, config đọc thẳng từ repo (`deploy/Caddyfile`) nên sửa file trong git là
sửa luôn production.

### 6.1 👤 DNS trước, 🤖 Caddy sau

Phần DNS + firewall panel đã làm ở **§3.4**. Kiểm lại trước khi chạy Caddy, vì thiếu thì Caddy
không xin được chứng chỉ và **không báo gì lên trang**:

* Bản ghi `A` của `tntecom.com` → `157.66.101.73`
* **Cổng 80 vào được từ Internet** — Let's Encrypt gọi ngược về đó để xác minh
* Cổng mở ở **cả hai nơi**: firewall Windows *và* panel nhà cung cấp VPS

🤖 Phần firewall Windows:

```powershell
New-NetFirewallRule -DisplayName "Caddy 80"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "Caddy 443" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

### 6.2 🤖 Cài Caddy làm service

```powershell
New-Item -ItemType Directory C:\Caddy, C:\Caddy\data, C:\Caddy\config -Force
# tải caddy.exe (bản windows amd64) vào C:\Caddy\

cd C:\AI-TNT-Research-SPY\deploy
.\nssm.exe install ResearchSpyCaddy C:\Caddy\caddy.exe "run --config C:\AI-TNT-Research-SPY\deploy\Caddyfile"
.\nssm.exe set ResearchSpyCaddy AppDirectory C:\Caddy
.\nssm.exe set ResearchSpyCaddy Start SERVICE_AUTO_START
.\nssm.exe set ResearchSpyCaddy AppEnvironmentExtra XDG_DATA_HOME=C:\Caddy\data XDG_CONFIG_HOME=C:\Caddy\config
.\nssm.exe set ResearchSpyCaddy AppStdout C:\Caddy\caddy.out.log
.\nssm.exe set ResearchSpyCaddy AppStderr C:\Caddy\caddy.err.log
.\nssm.exe start ResearchSpyCaddy
```

`XDG_DATA_HOME` **phải đặt**: đó là nơi Caddy cất chứng chỉ Let's Encrypt. Bỏ trống thì nó ghi
vào hồ sơ LocalSystem, và mỗi lần đổi tài khoản service là xin lại chứng chỉ từ đầu — dễ đụng
trần tần suất của Let's Encrypt.

HTTPS **tự xin và tự gia hạn**, không phải làm gì mỗi 90 ngày. Chưa ra được thì:

```powershell
Get-Content C:\Caddy\caddy.err.log -Tail 40
```

### 6.3 Hai luật cache trong Caddyfile — đừng xoá

Đo 14/09/2026, mất gần một tiếng tưởng code chưa lên server: Next gắn
`Cache-Control: s-maxage=31536000` (một năm) cho trang tĩnh, nên build xong người đã từng mở
trang vẫn thấy giao diện cũ cho tới khi tự bấm `Ctrl+Shift+R`. **F5 thường không đủ.**

```
@bundle path /research/_next/static/*     →  >Cache-Control "public, max-age=31536000, immutable"
@dong not path /research/_next/static/*   →  >Cache-Control "no-store"
```

Dấu `>` là **bắt buộc** (nghĩa là "thay thế"). Không có nó thì Caddy **cộng thêm** vào header
của Next, ra `no-store, s-maxage=31536000` — hai chỉ thị đá nhau trong cùng một dòng.

Sửa ở Caddy chứ không ở `next.config.mjs` là có lý do: sửa Next thì phải build lại + restart
`ResearchSpyFrontend`, mà việc đó **cắt đứt tab máy-thợ đang cào**. Caddy thì `reload` được:

```powershell
C:\Caddy\caddy.exe reload --config C:\AI-TNT-Research-SPY\deploy\Caddyfile
```

### 6.4 Thêm webtool thứ hai vào cùng tên miền

Chép khối trong `Caddyfile`, đổi tiền tố và cổng, rồi **đặt `basePath` tương ứng bên app đó**:

```
@tool2 path /tool2 /tool2/*
handle @tool2 { reverse_proxy 127.0.0.1:3100 }
```

Nhớ: `/api` ở gốc đã bị Research SPY chiếm, tool sau phải dùng `/tool2/api`.

---

## 7. 👤 NGƯỜI: đăng nhập các tài khoản sống

**Tới đây app đã mở được ở tên miền, nhưng phần lớn nguồn dữ liệu vẫn TRỐNG.** Hai việc dưới
đây là thứ biến một trang chạy được thành một công cụ có số. AI không làm được cả hai.

Chi tiết từng tài khoản, tuổi thọ phiên và cách xử khi hỏng: **[doc ③](3-tai-khoan-va-su-co.md)**.

### 7.1 Đăng nhập Google cho Google Trends — làm TRÊN VPS

Không có bước này thì mục **Keyword** trả bảng rỗng: đo 29/07/2026, phiên ẩn danh nhận **HTTP
200 kèm body 35 byte**. Nó không báo lỗi, nó trả về "không có gì" — kiểu chặn đã từng khiến cả
hướng đi này bị kết luận nhầm là "Trends không có dữ liệu cho cụm tiếng Việt".

**Vào VPS bằng RDP**, mở PowerShell (tài khoản Administrator):

```powershell
cd C:\AI-TNT-Research-SPY\backend
python -m scripts.auth.google_login
```

Script mở **một cửa sổ Chrome thật** rồi **dừng lại chờ bạn tự gõ tài khoản và mật khẩu**. Nó
không đọc, không nhập và không lưu mật khẩu. Sau khi bạn đăng nhập xong, nó **gọi thật một lần
vào Trends** và chỉ lưu phiên khi lời gọi đó trả về truy vấn thật — vì một file phiên hợp lệ về
hình thức nhưng vô dụng khi chạy còn tệ hơn là không có file nào.

**Ba điều phải biết:**

* **Dùng một tài khoản Google RIÊNG**, đừng dùng tài khoản chính hay tài khoản công ty. Tự động
  hoá Trends bằng phiên đăng nhập là thứ Google có thể gắn cờ.
* **Nên đăng nhập 2–3 tài khoản**, không phải một. Hạn mức Trends bám theo **tài khoản** (đo
  14/08/2026: cùng IP, đổi đúng một biến là tài khoản → một cái rỗng, cái khác đầy đủ), và bình
  chứa rất nhỏ. Thêm tài khoản: `python -m scripts.auth.google_login --name 2 --no-verify`
* **Phải làm lại sau vài tuần tới vài tháng.** Không có mốc cứng. Khi Google đã thu hồi phiên
  thì phải thêm `--fresh`, nếu không script thấy cookie cũ và tưởng đã đăng nhập.

### 7.2 Dựng máy-thợ — và GIỮ TAB ĐÓ MỞ

**Đây là việc quan trọng nhất trong cả tài liệu, và cũng là việc hay bị bỏ quên nhất.**

Không có máy-thợ thì mất: Trend Signal Hub (không cào được gì), nguồn Shopee/1688/Taobao/Temu
trong tool Sản phẩm và Từ khoá, hai tầng Google Lens + Taobao của Image Search.

**Vì sao không làm trên VPS được** — đo 04/09/2026 trên chính VPS, cả ba đường đều tắc:

| Nguồn | Hỏng thế nào |
|---|---|
| Shopee | IP VPS vào `shopee.vn/search` **luôn dính `verify/traffic`**, kể cả đã đăng nhập |
| Google Lens | ảnh thả được, rồi Google **đá thẳng sang `/sorry`** — chặn theo IP datacenter |
| Taobao | MTOP trả đúng mẫu chưa đăng nhập |

Và một nguyên nhân nền làm cả ba **không thể tự chữa tại chỗ**: backend chạy dưới **LocalSystem**,
còn người đăng nhập tay thì dưới **Administrator**. Chrome mã hoá cookie bằng khoá DPAPI **gắn
theo tài khoản Windows**, nên phiên dựng bằng tay không đọc lại được từ phía service. Đăng nhập
lại bằng tay cũng mất ngay, lần nào cũng vậy.

**Máy-thợ giải cả ba**: Chrome thật, máy thật, **IP dân cư**, đã đăng nhập sẵn.

#### Checklist dựng máy-thợ

Chọn **một máy tính ở văn phòng** (không phải VPS), bật suốt giờ làm việc:

| # | Việc | Ghi chú |
|---|---|---|
| 1 | Cài **Google Chrome** | |
| 2 | `chrome://extensions` → bật **Developer mode** | góc phải trên |
| 3 | **Load unpacked** → chọn thư mục `extension/` | Research-SPY Fetcher. Ghim lại cho dễ bấm |
| 4 | **Load unpacked** → chọn thư mục `extension-kalodata/` | chỉ cần nếu dùng dữ liệu TikTok |
| 5 | **Đăng nhập từng sàn, mỗi sàn một tab** | `shopee.vn` · `shopee.ph` · `1688.com` · `taobao.com` · `temu.com` · `kalodata.com` |
| 6 | Mở **`https://tntecom.com/research/worker/index.html`** | phải đủ `index.html` — bỏ đi thì Next trả 308 rồi 404 |
| 7 | Nếu backend đã đặt `RELAY_WORKER_TOKEN`: dán cùng chuỗi đó vào máy-thợ | DevTools → Console: `localStorage.wk_token='<chuỗi>'` rồi **F5** |
| 8 | **GIỮ TAB ĐÓ MỞ** | đây là điều kiện sống của cả hệ thống |
| 9 | Tắt sleep/hibernate của máy | Settings → Power → *Never*. Máy ngủ là máy-thợ offline |

Kiểm từ phía server:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/relay/status
```

Trên chính trang `/worker`: hai chấm **Extension** và **Kết nối server** phải **xanh**.

#### Bốn luật vận hành máy-thợ

| Luật | Vì sao |
|---|---|
| **Giữ tab mở.** Đóng tab = máy-thợ offline, không báo gì lên webtool | trang long-poll lấy job; không có tab thì không ai nhận job |
| **Sau khi máy khởi động lại, phải mở lại tab** | không có gì tự mở hộ |
| **`Restart-Service ResearchSpyFrontend` làm ĐỨT tab máy-thợ** → F5 lại | trang `/worker` do `next start` phục vụ |
| **Sửa file trong `extension/` KHÔNG tự có hiệu lực** → Reload extension rồi F5 tab | Chrome vẫn chạy bản đã nạp — xem §9.3 |

Extension tự dọn bộ nhớ hộ: đưa tab về `about:blank` sau mỗi job, đóng tab rảnh quá 10 phút.
Đo 03/09/2026: trước khi có hai cơ chế đó, Chrome chạy liền 6 ngày **ngốn 1,66 GB**.

---

## 8. 👤 Mở cho toàn công ty dùng

App đã chạy và đã có dữ liệu. Còn bốn việc để nó thật sự phục vụ được cả công ty.

### 8.1 Thông báo địa chỉ và cách vào

Gửi cho mọi người đúng ba thông tin:

* **Địa chỉ: `https://tntecom.com/research/`**
* Đăng nhập **bằng email `@tntecom.com`**, **không có mật khẩu** — nhập email, lần đầu khai
  Tên · Vị trí · BU, rồi chờ duyệt.
* Vé đăng nhập sống **7 ngày** (`JWT_TTL_HOURS=168`), sau đó nhập lại email.

> Gõ thiếu `/research` sẽ ra trang 404 nói rõ *"chưa có gì ở địa chỉ này. Research SPY nằm ở
> /research"*. Đó là **cố ý**, không phải server chết.

### 8.2 Duyệt user — việc hằng ngày của admin

Người mới đăng ký → bản ghi `pending`, **chưa vào được**. Admin vào `/admin`:

| Việc | Ở đâu |
|---|---|
| Xem danh sách + số người đang chờ | `/admin`, mục người dùng |
| Duyệt / từ chối | đổi `status` → `approved` / `rejected` |
| Nâng quyền | đổi `role` → `admin` hoặc `owner` |
| Vô hiệu hoá người đã nghỉ | `is_active` → false |
| Xoá hẳn | nút xoá — **nhớ nó cũng phải dọn danh sách Yêu thích của người đó** |

**Chọn BU cho đúng.** BU là ô chọn bốn mã `BU1`/`BU2`/`BU3`/`HO`, và **nó quyết định ngưỡng xanh
của tỷ giá** cho người ấy. Bốn tài khoản đầu tiên đã từng đẻ ra ba cách viết cho cùng một đơn vị
("Holding", "Hoding", "HO") — một cách viết lạ không chỉ xấu, nó **lặng lẽ áp sai chính sách**.

### 8.3 Ba thứ cần nói trước với người dùng

Nếu không nói, họ sẽ tưởng tool hỏng — và tệ hơn, có thể **ra quyết định sai**:

1. **TikTok trả "0 kết quả" là bình thường.** Creative Center chỉ mở search theo từ khoá cho
   tài khoản đã đăng nhập; phiên ẩn danh nhận 0 kết quả **kèm mã thành công**. Tool chuyển sang
   duyệt Top Ads theo CTR và **luôn kèm thông báo**. Thấy thông báo đó thì **đừng kết luận sản
   phẩm không có nhu cầu** — nhìn phần Facebook.
2. **Video mở lại hôm sau không phát được.** Link CDN có chữ ký, hết hạn sau vài giờ, và tool
   **cố ý không lưu video**. Search lại để lấy link mới.
3. **"CVR ước lượng" không phải CVR thật.** Không sàn nào công khai tỷ lệ chuyển đổi. Con số đó
   suy ra từ số ngày quảng cáo đã chạy, số biến thể creative, CTR và tương tác — nên nó **không
   hiện trên thẻ**, chỉ dùng để xếp thứ tự.

### 8.4 Ai trực, và trực cái gì

Ba việc phải có người, không tự động được:

| Nhịp | Việc | Vì sao người |
|---|---|---|
| **Mỗi ngày, ~09:00** | Xem hộp thư `ALERT_EMAIL` (mặc định `aiteam.tnt@gmail.com`). Có mail *"1688 dính CAPTCHA"* → sang máy-thợ **kéo slider bằng tay** | CAPTCHA thiết kế để chỉ người giải được. Vòng cào **chờ tối đa 60 phút** rồi tự chạy nốt; quá giờ thì bỏ cả đêm dữ liệu 1688 |
| **Mỗi ngày** | Nhìn tab máy-thợ còn xanh không | máy ngủ / Chrome bị đóng / frontend vừa restart → offline mà webtool không báo |
| **Mỗi ngày** | Duyệt user mới (§8.2) | quyết định của con người |

Sự cố 18/09/2026 là lý do cơ chế này tồn tại: slider bật ở ngành thứ ~20 và **182/205 ngành hỏng
liền một mạch**, không ai biết cho tới khi nhìn bảng lỗi. Nay có mail đi ngay lúc dính.

Lịch bảo dưỡng đầy đủ theo tuần/tháng: **[doc ③ §9](3-tai-khoan-va-su-co.md)**.

---

## 9. 🤖 Cập nhật code về sau

### 9.1 KHÔNG có khâu deploy — code chạy ngay tại chỗ

`C:\AI-TNT-Research-SPY` **vừa là bản clone git để sửa, vừa là thư mục mà ba service đang
chạy**. Không có máy build riêng, không có bước đẩy file từ nơi khác sang. Sửa file ở đây là
sửa thẳng vào bản đang phục vụ người dùng.

Hai hệ quả phải nắm:

* **Không cần nghĩ tới "deploy".** Việc duy nhất còn lại là **nạp lại cái đang chạy** — §9.2.
* **Cũng không có lưới an toàn.** Một file Python sai cú pháp nằm trên đĩa chưa gây gì, nhưng
  đúng lần restart kế tiếp là backend không bật lên được. Kiểm trước khi restart — §11.1.

### 9.2 Nạp lại sau khi sửa — tra bảng này

| Sửa gì | Phải làm gì |
|---|---|
| file `.py` bất kỳ trong `backend/` | `Restart-Service ResearchSpyBackend` |
| `backend/requirements.txt` | `python -m pip install -r requirements.txt` rồi restart backend |
| file bất kỳ trong `frontend/` | `npm run build` **rồi** `Restart-Service ResearchSpyFrontend` |
| `backend/.env.local` | `Restart-Service ResearchSpyBackend` (config đọc một lần lúc khởi động) |
| `deploy/Caddyfile` | `caddy reload` — **không restart service**, xem §6.3 |
| `extension/` hoặc `extension-kalodata/` | §9.3 — **không** liên quan gì tới ba service |

```powershell
# frontend: build TRƯỚC, restart SAU. Build gãy thì đừng restart — bản đang chạy vẫn tốt.
cd C:\AI-TNT-Research-SPY\frontend
npm run build
if ($?) { Restart-Service ResearchSpyFrontend }
```

Ba điều cần nhớ khi restart:

* **`ResearchSpyFrontend` restart là ĐỨT tab máy-thợ đang cào**; backend thì không. Tránh
  restart frontend trong lúc vòng cào đang chạy (01:00–05:00 và 09:00–09:20).
* Backend giữ **cache 15 phút + kho phiên trình duyệt trong RAM** → restart là xoá sạch chúng.
  Đó là cái giá bình thường, nhưng đừng restart liên tục.
* Sửa backend thì **restart**, đừng bật `--reload` — nó làm chết Playwright trên Windows (§10d).

### 9.2.1 `deploy/redeploy.ps1` — chỉ dùng khi muốn ĐỒNG BỘ ĐÚNG BẰNG REMOTE

Script còn trong repo và vẫn chạy được, nhưng nó **không dành cho lối làm việc trực tiếp trên
server**:

> ⚠️ Bước đầu tiên của nó là **`git reset --hard origin/Titus`** — **mọi sửa đổi chưa commit
> trên máy này bị xoá sạch, không hỏi lại.**

Chỉ dùng khi bạn *chủ đích* muốn ném bỏ thay đổi cục bộ và về đúng bằng nhánh trên GitHub. Khi
đó nó làm nốt phần cơ học giúp bạn: `pip install` nếu `requirements.txt` đổi, `npm ci` +
`next build` nếu có file `frontend/` đổi (**build gãy thì KHÔNG restart**), restart đúng service
có phần đổi, rồi kiểm `/api/health`.

```powershell
cd C:\AI-TNT-Research-SPY\deploy
.\redeploy.ps1 -Root C:\AI-TNT-Research-SPY -Branch Titus
```

`.env.local` nằm trong `.gitignore` nên `reset --hard` không chạm tới — nhưng đó cũng có nghĩa
**nó không được git sao lưu**, xem §12.

### 9.3 👤 Sửa extension KHÔNG tự có hiệu lực

`extension/` và `extension-kalodata/` được **Load unpacked** vào trình duyệt máy-thợ. `git pull`
đổi file trên đĩa **VPS**, nhưng Chrome trên **máy-thợ** vẫn chạy bản đã nạp. Sau mỗi lần sửa
extension, phải có người ra máy-thợ:

1. Vào `chrome://extensions`, bấm **Reload** ở extension đó
2. **F5 tab "Máy thợ crawl"** để nối lại cầu postMessage

Quên bước này là triệu chứng kinh điển "code đã lên rồi mà vẫn sai y như cũ".

---

## 10. Playwright, Chrome và LocalSystem — cái bẫy nặng nhất

Ba sự thật đã đo, và code đang dựa vào cả ba:

**(a) `channel="chrome"` — Chrome THẬT, không phải Chromium đi kèm.** Đo 04/08/2026 trên
`trends.google.com.vn/explore`, cùng phiên, cùng máy, cùng IP, chỉ khác bản trình duyệt:

| | Kết quả |
|---|---|
| Chrome thật (ẩn hoặc có cửa sổ) | **100 truy vấn liên quan** |
| Chromium đi kèm Playwright | **payload rỗng** (HTTP 200, không lỗi) |

**(b) Một nguồn cần điều NGƯỢC LẠI.** Bing phục vụ hai bố cục khác nhau — đo 08/09/2026, cùng
truy vấn, lật ba trang:

| | Kết quả |
|---|---|
| Chrome thật | 30 thẻ/trang, `first=31/61` trả **lại đúng 30 thẻ ấy** → phân trang không tồn tại |
| Chromium đi kèm | 50 → 70 → 70 thẻ, **luỹ kế 112 video khác nhau** |

Nên `lib/ads/platforms/tiktokvideo.py` xin `prefer_bundled=True`.

**(c) Thiếu bản nào thì `browser.py` tự đổi sang bản kia** thay vì chết. Nghĩa là **thiếu
Chromium đi kèm KHÔNG gây lỗi** — nó chỉ làm nguồn video TikTok qua Bing mất phân trang, im
lặng, không một dòng log nào.

Nên đây là thứ **phải tự đi kiểm chứ không đợi nó báo**. Hai điều kiện đủ, thiếu một là rơi vào
tình trạng trên:

```powershell
Test-Path C:\ms-playwright                     # thư mục dùng chung phải tồn tại
# và AppEnvironmentExtra của ResearchSpyBackend phải có PLAYWRIGHT_BROWSERS_PATH — xem §5.1
```

`Test-Path` trả `False` nghĩa là `playwright install` đã cất Chromium vào `%LOCALAPPDATA%` của
người chạy lệnh, còn service (LocalSystem) không thấy nó. Cách sửa ở §5.1.

**(d) KHÔNG dùng `--reload` hay `--workers` trên Windows.** Cả hai bật `use_subprocess`, uvicorn
khi đó chuyển sang `WindowsSelectorEventLoopPolicy`, loop ấy không sinh được tiến trình con →
**Playwright chết ngay lúc khởi động**, mất cả Google Trends lẫn toàn bộ mục Sản phẩm. Lỗi ném
ra là `NotImplementedError` **không kèm mô tả** nên rất dễ hiện thành một thông báo nói sai
nguyên nhân. Sửa backend thì **restart service**, không bật reload.

---

## 11. Chạy trên một máy khác (không phải server)

```powershell
# cài một lần
cd backend;  python -m pip install -r requirements.txt;  python -m playwright install chromium
cd ..\frontend;  npm install

# chạy — HAI cửa sổ terminal
cd backend;   python -m uvicorn app.main:app --port 8000
cd frontend;  npm run dev                                  # http://localhost:3000/research
```

Hoặc nhấp đúp `start.bat` ở thư mục gốc (bật cả hai rồi mở trình duyệt).

Trên máy dev **lịch cào đêm tắt** (không có `HUB_SCHEDULER`) — đúng như mong muốn. Muốn chạy thử
một job: `POST /api/hub/scheduler/run?job=<tên>`.

### 11.1 Kiểm TRƯỚC KHI RESTART — quan trọng vì sửa thẳng trên server

Vì không có khâu build trung gian nào chặn lỗi hộ (§9.1), hai lệnh đầu nên chạy **mỗi lần** sửa
backend, trước khi restart:

```powershell
cd C:\AI-TNT-Research-SPY\backend
python -m compileall -q .                    # cú pháp — bắt lỗi gõ
python -c "import app.main"                  # import graph — bắt lỗi import, thiếu thư viện
```

Hai lệnh đó chạy vài giây và là ranh giới giữa "restart xong vẫn chạy" và "backend không bật lên
được". Nặng hơn, chạy khi sửa vào phần nguồn dữ liệu:

```powershell
python scripts\smoke\ads.py                  # đầu-cuối mục Sản phẩm
python scripts\smoke\keywords.py             # đầu-cuối mục Từ khoá
python scripts\smoke\ui.py                   # mở trình duyệt thật, click hết nút
python scripts\audit\keyword_sources.py      # đối chiếu độc lập với nguồn gốc
cd ..\frontend;  npm run typecheck           # trước khi npm run build
```

Nhóm `smoke/` cần Chrome + mạng ngoài, nên **đỏ vì môi trường cũng được** — đọc câu báo trước
khi kết luận là lỗi code.

---

## 12. Sao lưu — thứ git KHÔNG giữ

| Đường dẫn | Là gì | Mất thì sao |
|---|---|---|
| `backend/database/hub_data.db` | **349 MB** — toàn bộ dữ liệu cào Shopee/1688 + bảng `favorite_product` (Yêu thích của từng người) | Mất lịch sử. Lăng kính Đang tăng tốc / Đột biến / Tân binh **cần chuỗi ngày**, cào lại một đêm không dựng lại được |
| `backend/.env.local` | mọi khoá và bí mật | Phải xin lại từng khoá — §3.3 |
| `backend/.auth/` | phiên đăng nhập Google (`google*.json`) + hồ sơ Chrome | Đăng nhập lại — §7.1 |
| `C:\Caddy\data` | chứng chỉ HTTPS | Caddy tự xin lại, nhưng dễ đụng trần tần suất |
| **Supabase** | `users`, `role_requests`, `analytics_event` | nằm ở cloud, Supabase tự sao lưu — nhưng nhớ **ai giữ tài khoản Supabase** |

Đã có sẵn hai bản `.bak-*` cạnh `hub_data.db`. Nếu chép DB khi backend đang chạy thì **dùng
`VACUUM INTO`**, đừng `Copy-Item` (SQLite đang mở, file chép ra có thể vỡ):

```powershell
python -c "import sqlite3,sys; sqlite3.connect(r'C:\AI-TNT-Research-SPY\backend\database\hub_data.db').execute('VACUUM INTO ?', (sys.argv[1],))" D:\backup\hub_data-20260924.db
```

---

## 13. Nhận diện nhanh khi có sự cố

```powershell
Get-Service ResearchSpy*                                   # ba cái phải Running
Invoke-RestMethod http://127.0.0.1:8000/api/health          # {ok: true}
Invoke-RestMethod http://127.0.0.1:8000/api/ads/health      # trạng thái từng nguồn
(Invoke-RestMethod http://127.0.0.1:8000/api/hub/scheduler/status).luong_dang_chay
Invoke-RestMethod http://127.0.0.1:8000/api/relay/status    # máy-thợ online chưa
Get-Content C:\AI-TNT-Research-SPY\backend\service.err.log -Tail 60
Get-Content C:\AI-TNT-Research-SPY\frontend\service.err.log -Tail 60
Get-Content C:\Caddy\caddy.err.log -Tail 40
```

| Triệu chứng | Nghĩa là | Làm gì |
|---|---|---|
| "Chưa kết nối được tầng dữ liệu" | backend Python chưa chạy — **không phải tool hỏng** | `Restart-Service ResearchSpyBackend` |
| Vào app được mà **không cần đăng nhập** | Supabase chưa cấu hình → `/api/auth/login` trả 501, frontend rơi về fallback dev | §3.1 — **nguy hiểm nhất trên production** |
| `tntecom.com` trả 404 kèm câu "chưa có gì ở địa chỉ này" | gõ thiếu `/research` — Caddy **cố ý** trả lời rõ | thêm `/research` |
| Giao diện vẫn là bản cũ sau khi build + restart | cache HTML | kiểm hai luật cache §6.3, rồi `Ctrl+Shift+R` |
| Chấm đỏ ở thanh trạng thái một nguồn | nguồn đó có vấn đề, có thể sàn đã đổi cấu trúc | sửa đúng `backend/lib/ads/platforms/<tên>.py`, **không file nào khác** |
| Nguồn Shopee/1688/Taobao **trống** | 👤 máy-thợ offline hoặc phiên sàn hết | §7.2, và doc ③ |
| Cột "Lượng tìm" trống | 👤 hồ phiên Google cạn hoặc hết hạn | §7.1 |
| 502 nhưng vài giây sau lại đúng | tầng nào đó cắt sớm hơn Next | `PROXY_TIMEOUT_MS` (300s) và `transport http` trong Caddyfile phải khớp nhau |
| Sửa extension mà không thấy đổi | 👤 chưa Reload extension trên máy-thợ | §9.3 |
| Trend Signal Hub số không đổi nhiều ngày | lịch cào không chạy | kiểm `luong_dang_chay`, xem §5.1 |
| Trang Hub đầy số liệu nhưng số trông lạ | có thể đang là **dữ liệu mẫu nhúng cứng** | gọi `/api/hub/health` xem `status` |

---

## 14. Checklist bàn giao — đánh dấu từng dòng

### 🤖 Phần giao cho Claude Code

- [ ] Clone repo, checkout `Titus` (§4)
- [ ] `.env.local` điền đủ khoá người đã đưa (§4.1)
- [ ] `vps-setup.ps1` chạy xong, hai service `Running` (§5)
- [ ] `HUB_SCHEDULER=1` **và** `PLAYWRIGHT_BROWSERS_PATH` cùng trong một lệnh nssm (§5.1)
- [ ] `Test-Path C:\ms-playwright` → `True` (§5.1)
- [ ] Caddy chạy, `https://tntecom.com/research/` mở được, có ổ khoá HTTPS (§6)
- [ ] `RELAY_WORKER_TOKEN` đã đặt, và **đã đưa chuỗi đó cho người dựng máy-thợ** (§4.1)
- [ ] `/api/health` `ok` · `luong_dang_chay` `True` · `/api/ads/health` không đỏ hàng loạt (§13)
- [ ] Lịch sao lưu `hub_data.db` (§12)

### 👤 Phần chỉ người làm được

- [ ] Project Supabase tạo xong, **4 file SQL chạy đúng thứ tự** (§3.1)
- [ ] `SUPABASE_URL` + `service_role` key đã đưa cho AI (§3.1)
- [ ] **Tài khoản `owner` đầu tiên sửa tay trong Supabase** — không có bước này thì không ai vào
      được app (§3.2)
- [ ] Sáu khoá: Gemini · JWT_SECRET · YouTube · Etsy (2 khoá) · SMTP app password · FB cookie (§3.3)
- [ ] Gói **Kalodata** còn credit (§3.3)
- [ ] Cloudflare: `A` → `157.66.101.73`, **không đụng bản ghi MX của Lark** (§3.4)
- [ ] Panel VPS: cổng **80** và **443** đã mở (§3.4)
- [ ] **Google cho Trends: 2–3 tài khoản riêng** đã đăng nhập trên VPS (§7.1)
- [ ] **Máy-thợ**: 2 extension cài, 6 sàn đã đăng nhập, `wk_token` đã dán (§7.2)
- [ ] **Tab `/worker/index.html` ĐANG MỞ**, hai chấm xanh, máy tắt sleep (§7.2)
- [ ] `/api/relay/status` báo có worker (§7.2)
- [ ] Đã thông báo địa chỉ + cách đăng nhập cho công ty (§8.1)
- [ ] Đã nói ba giới hạn cho người dùng (§8.3)
- [ ] **Đã chỉ định người trực hằng ngày**: mail CAPTCHA 1688, tab máy-thợ, duyệt user (§8.4)
- [ ] Đã ghi lại **ai giữ tài khoản Supabase, Cloudflare, Kalodata, Google-cho-Trends** — mất
      người là mất quyền

---

## 15. Đi tiếp

* Chức năng, function, logic từng mục → **[2-chuc-nang-va-logic.md](2-chuc-nang-va-logic.md)**
* Tài khoản phải đăng nhập, sống bao lâu, hỏng thì xử sao → **[3-tai-khoan-va-su-co.md](3-tai-khoan-va-su-co.md)**
* Thêm một nguồn dữ liệu mới → [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* Nhật ký nghiên cứu nguồn (vì sao từng endpoint gọi được như vậy) → [`docs/tai-lieu-ky-thuat/`](../tai-lieu-ky-thuat/)
