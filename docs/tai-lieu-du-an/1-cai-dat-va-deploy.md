# Bàn giao ① — Cài đặt và đưa lên tên miền, từ `git clone` tới `https://tntecom.com/research/`

> Trạng thái kiểm chứng: **24/09/2026**, đo trên chính máy production.
> Bản đang chạy thật: `https://tntecom.com/research/` · VPS Windows `157.66.101.73`.
>
> Tài liệu này viết để **đưa cho Claude Code (hoặc một dev) làm theo từ đầu đến cuối**. Mỗi
> phần ghi *làm gì* + *vì sao*, vì gần hết những cái bẫy ở đây đều **hỏng lặng lẽ**: trang vẫn
> mở, vẫn có số, chỉ là số sai hoặc số cũ.

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

Ba điều **cố ý** và đừng "sửa cho gọn":

1. **`basePath = /research`** (`frontend/next.config.mjs`). Webtool không được chiếm gốc tên
   miền vì `tntecom.com` còn nhiều tool khác.
2. **`/api/*` ở LẠI GỐC tên miền** (`basePath: false` trong `rewrites()`), không đi theo
   `/research`. Lý do: `<video src="/api/media?...">` phải cùng origin để Range + cache đi qua
   được. **Hệ quả cho tool sau: `/api` ở gốc ĐÃ BỊ CHIẾM**, tool thứ hai phải dùng `/tool2/api`.
3. **Chỉ một tiến trình backend.** Cache và kho phiên trình duyệt nằm trong RAM. `--workers`
   nhân số request ra ngoài lên đúng bằng số worker — chính là thứ làm IP chung bị chặn. Và
   trên Windows `--workers`/`--reload` còn làm chết Playwright (xem §6).

---

## 1. Máy cần có gì trước

| Thứ | Bản đang chạy | Ghi chú |
|---|---|---|
| Windows Server | 2022 Standard | Windows 10/11 cũng được |
| Python | **3.12.7** | lúc cài phải tick *Add python.exe to PATH* |
| Node.js | **24.20.0** | LTS ≥ 20 là đủ |
| **Google Chrome thật** | 153.0.8010.54 | **BẮT BUỘC**, không thay bằng Chromium — xem §6 |
| Git | bất kỳ | `C:\AI-TNT-Research-SPY` phải là **bản clone git**, không phải .zip giải nén |
| RAM | ≥ 8 GB | mỗi phiên Chrome ăn 0,4–0,7 GB, trần mềm 4 phiên (`BROWSER_POOL_MAX`) |
| Đĩa | ≥ 30 GB trống | `hub_data.db` hiện **349 MB** và lớn thêm ~52.000 dòng/ngày |

---

## 2. Clone và cấu hình

```powershell
git clone https://github.com/Digital-Transformation-TNT/Research-SPY.git C:\AI-TNT-Research-SPY
cd C:\AI-TNT-Research-SPY
git checkout Titus
```

> **Nhánh làm việc là `Titus`, không phải `main`.** `main` chỉ là bản mirror (fast-forward từ
> `Titus`) để Dependabot soi nhánh mặc định. Đồng bộ lại khi cần:
> `git push origin Titus:main`.

### 2.1 File cấu hình — thứ DUY NHẤT không có trong git

```powershell
Copy-Item backend\.env.example backend\.env.local
notepad backend\.env.local
```

`backend/.env.example` dài ~450 dòng và **chính nó là tài liệu** cho từng biến — đọc comment
trong đó thay vì đoán. Chia theo mức cần thiết:

| Nhóm | Biến | Thiếu thì sao |
|---|---|---|
| **Bắt buộc để có đăng nhập** | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `JWT_SECRET`, `ALLOWED_EMAIL_DOMAIN=tntecom.com`, `JWT_TTL_HOURS=168` | `/api/auth/login` trả **501**, frontend rơi về chế độ dev "coi như đã đăng nhập" — **tuyệt đối không để trạng thái này lên production** |
| **Bắt buộc để có AI** | `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-3.5-flash-lite` | One-shot AI rơi về tóm tắt heuristic (vẫn chạy, nhưng không diễn giải) |
| Nguồn cần khoá | `YOUTUBE_API_KEY`, `ETSY_KEYSTRING` + `ETSY_SHARED_SECRET`, `FB_COOKIE` | nguồn đó tắt, có báo rõ ở thanh trạng thái |
| Cảnh báo vận hành | `SMTP_HOST/PORT/USER/PASS/FROM`, `ALERT_EMAIL` | **1688 dính slider mà không ai biết** — xem doc ③ |
| Proxy TikTok | `TIKTOK_PROXY_*`, `TIKTOK_FREE_PROXY` | TikTok chỉ tra được ở thị trường nhà (`TIKTOK_HOME_MARKET=VN`) |
| Máy-thợ | `RELAY_WORKER_TOKEN` | `/api/relay/next` + `/result` mở cho bất kỳ ai — **nên đặt** trên production |
| Nhịp & cache | `CACHE_TTL_MS=900000`, `*_MIN_INTERVAL_MS`, `BROWSER_POOL_MAX=4`, `HEADLESS=true` | dùng mặc định là được |

`frontend/.env.local` **thường không cần**. Chỉ tạo khi backend nằm ở máy khác:
`BACKEND_URL=http://<ip>:8000`.

---

## 3. Dựng máy lần đầu — một lệnh

```powershell
cd C:\AI-TNT-Research-SPY\deploy
Set-ExecutionPolicy -Scope Process Bypass -Force
.\vps-setup.ps1 -Root C:\AI-TNT-Research-SPY
```

Script (`deploy/vps-setup.ps1`) làm, theo thứ tự: dò Python + Node → `pip install -r
requirements.txt` → `playwright install chromium` → `npm install` + `npm run build` → mở cổng
3000 ở firewall Windows → tải nssm → tạo/ghi đè hai service `ResearchSpyBackend` và
`ResearchSpyFrontend` rồi start. **Chạy lại nhiều lần được**, service cũ bị gỡ rồi tạo lại.

### 3.1 Hai biến môi trường của service PHẢI đặt bằng tay sau đó

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
| `PLAYWRIGHT_BROWSERS_PATH=C:\ms-playwright` | `playwright install` mặc định cất Chromium vào `%LOCALAPPDATA%` của **người chạy lệnh** (Administrator), còn service chạy dưới **LocalSystem** — tài khoản đó không thấy thư mục ấy. Xem §6 để biết cái này làm hỏng gì. |

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

## 4. Đưa ra tên miền — Caddy

Caddy **không** nằm trong `vps-setup.ps1`, dựng bằng tay một lần. Bản đang chạy:
`C:\Caddy\caddy.exe`, config đọc thẳng từ repo (`deploy/Caddyfile`) nên sửa file trong git là
sửa luôn production.

### 4.1 DNS trước, Caddy sau

**`tntecom.com` dùng nameserver Cloudflare, KHÔNG phải iNet.** Bảng bản ghi bên iNet vẫn cho
lưu nhưng hoàn toàn vô tác dụng — sửa ở đó là sửa vào chỗ không ai đọc. Cloudflare đang giữ
cả bản ghi MX cho email Lark, nên đừng dọn dẹp bản ghi lạ khi chưa hỏi.

* Bản ghi `A` của `tntecom.com` → `157.66.101.73`
* **Cổng 80 phải vào được từ Internet** — Let's Encrypt gọi ngược về đó để xác minh
* Mở cổng ở **cả hai nơi**: firewall Windows *và* panel của nhà cung cấp VPS (vpssieutoc)

```powershell
New-NetFirewallRule -DisplayName "Caddy 80"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "Caddy 443" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

### 4.2 Cài Caddy làm service

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

### 4.3 Hai luật cache trong Caddyfile — đừng xoá

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

### 4.4 Thêm webtool thứ hai vào cùng tên miền

Chép khối trong `Caddyfile`, đổi tiền tố và cổng, rồi **đặt `basePath` tương ứng bên app đó**:

```
@tool2 path /tool2 /tool2/*
handle @tool2 { reverse_proxy 127.0.0.1:3100 }
```

Nhớ: `/api` ở gốc đã bị Research SPY chiếm, tool sau phải dùng `/tool2/api`.

---

## 5. Cập nhật code về sau

### 5.1 KHÔNG có khâu deploy — code chạy ngay tại chỗ

`C:\AI-TNT-Research-SPY` **vừa là bản clone git để sửa, vừa là thư mục mà ba service đang
chạy**. Không có máy build riêng, không có bước đẩy file từ nơi khác sang. Sửa file ở đây là
sửa thẳng vào bản đang phục vụ người dùng.

Hai hệ quả phải nắm:

* **Không cần nghĩ tới "deploy".** Việc duy nhất còn lại là **nạp lại cái đang chạy** — §5.2.
* **Cũng không có lưới an toàn.** Một file Python sai cú pháp nằm trên đĩa chưa gây gì, nhưng
  đúng lần restart kế tiếp là backend không bật lên được. Kiểm trước khi restart — §7.1.

### 5.2 Nạp lại sau khi sửa — tra bảng này

| Sửa gì | Phải làm gì |
|---|---|
| file `.py` bất kỳ trong `backend/` | `Restart-Service ResearchSpyBackend` |
| `backend/requirements.txt` | `python -m pip install -r requirements.txt` rồi restart backend |
| file bất kỳ trong `frontend/` | `npm run build` **rồi** `Restart-Service ResearchSpyFrontend` |
| `backend/.env.local` | `Restart-Service ResearchSpyBackend` (config đọc một lần lúc khởi động) |
| `deploy/Caddyfile` | `caddy reload` — **không restart service**, xem §4.3 |
| `extension/` hoặc `extension-kalodata/` | §5.3 — **không** liên quan gì tới ba service |

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
* Sửa backend thì **restart**, đừng bật `--reload` — nó làm chết Playwright trên Windows (§6d).

### 5.2.1 `deploy/redeploy.ps1` — chỉ dùng khi muốn ĐỒNG BỘ ĐÚNG BẰNG REMOTE

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
**nó không được git sao lưu**, xem §8.

### 5.3 Sửa extension KHÔNG tự có hiệu lực

`extension/` và `extension-kalodata/` được **Load unpacked** vào trình duyệt máy-thợ. `git pull`
đổi file trên đĩa nhưng Chrome vẫn chạy bản đã nạp. Sau mỗi lần sửa extension:

1. Vào `chrome://extensions` trên **máy-thợ**, bấm **Reload** ở extension đó
2. **F5 tab "Máy thợ crawl"** để nối lại cầu postMessage

Quên bước này là triệu chứng kinh điển "code đã lên rồi mà vẫn sai y như cũ".

---

## 6. Playwright, Chrome và LocalSystem — cái bẫy nặng nhất

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
# và AppEnvironmentExtra của ResearchSpyBackend phải có PLAYWRIGHT_BROWSERS_PATH — xem §3.1
```

`Test-Path` trả `False` nghĩa là `playwright install` đã cất Chromium vào `%LOCALAPPDATA%` của
người chạy lệnh, còn service (LocalSystem) không thấy nó. Cách sửa ở §3.1.

**(d) KHÔNG dùng `--reload` hay `--workers` trên Windows.** Cả hai bật `use_subprocess`, uvicorn
khi đó chuyển sang `WindowsSelectorEventLoopPolicy`, loop ấy không sinh được tiến trình con →
**Playwright chết ngay lúc khởi động**, mất cả Google Trends lẫn toàn bộ mục Sản phẩm. Lỗi ném
ra là `NotImplementedError` **không kèm mô tả** nên rất dễ hiện thành một thông báo nói sai
nguyên nhân. Sửa backend thì **restart service**, không bật reload.

---

## 7. Chạy trên một máy khác (không phải server)

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

### 7.1 Kiểm TRƯỚC KHI RESTART — quan trọng vì sửa thẳng trên server

Vì không có khâu build trung gian nào chặn lỗi hộ (§5.1), hai lệnh đầu nên chạy **mỗi lần** sửa
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

## 8. Sao lưu — thứ git KHÔNG giữ

| Đường dẫn | Là gì | Mất thì sao |
|---|---|---|
| `backend/database/hub_data.db` | **349 MB** — toàn bộ dữ liệu cào Shopee/1688 + bảng `favorite_product` (Yêu thích của từng người) | Mất lịch sử. Lăng kính Đang tăng tốc / Đột biến / Tân binh **cần chuỗi ngày**, cào lại một đêm không dựng lại được |
| `backend/.env.local` | mọi khoá và bí mật | Phải xin lại từng khoá |
| `backend/.auth/` | phiên đăng nhập Google (`google*.json`) + hồ sơ Chrome | Đăng nhập lại — xem doc ③ |
| `C:\Caddy\data` | chứng chỉ HTTPS | Caddy tự xin lại, nhưng dễ đụng trần tần suất |

Đã có sẵn hai bản `.bak-*` cạnh `hub_data.db`. Nếu chép DB khi backend đang chạy thì **dùng
`VACUUM INTO`**, đừng `Copy-Item` (SQLite đang mở, file chép ra có thể vỡ):

```powershell
python -c "import sqlite3,sys; sqlite3.connect(r'C:\AI-TNT-Research-SPY\backend\database\hub_data.db').execute('VACUUM INTO ?', (sys.argv[1],))" D:\backup\hub_data-20260924.db
```

---

## 9. Nhận diện nhanh khi có sự cố

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
| `tntecom.com` trả 404 kèm câu "chưa có gì ở địa chỉ này" | gõ thiếu `/research` — Caddy **cố ý** trả lời rõ | thêm `/research` |
| Giao diện vẫn là bản cũ sau khi build + restart | cache HTML | kiểm hai luật cache §4.3, rồi `Ctrl+Shift+R` |
| Chấm đỏ ở thanh trạng thái một nguồn | nguồn đó có vấn đề, có thể sàn đã đổi cấu trúc | sửa đúng `backend/lib/ads/platforms/<tên>.py`, **không file nào khác** |
| 502 nhưng vài giây sau lại đúng | tầng nào đó cắt sớm hơn Next | `PROXY_TIMEOUT_MS` (300s) và `transport http` trong Caddyfile phải khớp nhau |
| Sửa extension mà không thấy đổi | chưa Reload extension | §5.3 |
| Trend Signal Hub hiện số nhưng số không đổi nhiều ngày | lịch cào không chạy | kiểm `luong_dang_chay`, xem §3.1 |

---

## 10. Đi tiếp

* Chức năng, function, logic từng mục → **[2-chuc-nang-va-logic.md](2-chuc-nang-va-logic.md)**
* Tài khoản phải đăng nhập, sống bao lâu, hỏng thì xử sao → **[3-tai-khoan-va-su-co.md](3-tai-khoan-va-su-co.md)**
* Thêm một nguồn dữ liệu mới → [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* Nhật ký nghiên cứu nguồn (vì sao từng endpoint gọi được như vậy) → [`docs/tai-lieu-ky-thuat/`](../tai-lieu-ky-thuat/)
