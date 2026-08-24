# gtrends

Bảng **"truy vấn liên quan"** của Google Trends — lấy được thật, kèm cột lượng tìm tương đối
và cột % thay đổi.

Gói tự chứa. Copy nguyên thư mục `gtrends/` vào dự án bất kỳ, dùng xong xoá đi là sạch.

```python
from gtrends import TrendsContext, fetch_related_queries

out = await fetch_related_queries("kem chống nắng", TrendsContext(country="VN"))
for row in out.queries:
    print(row.query, row.value, row.change_percent, "tăng" if row.rising else "hàng đầu")
```

Đo thật ngày 2026-08-20: **100 dòng trong 15,5 giây**.

---

## Cài đặt

```bash
pip install playwright
playwright install chromium     # driver của Playwright
python -m gtrends.login         # đăng nhập Google một lần, mở cửa sổ thật
python -m gtrends.example       # kiểm tra
```

`python-dotenv` là tuỳ chọn — có thì gói đọc thêm `gtrends/.env`, không có thì bỏ qua.

### Máy phải có **Google Chrome thật**

Không phải Chromium đi kèm Playwright. Đây không phải sở thích — đo 2026-08-04, cùng phiên
đăng nhập, cùng máy, cùng IP, cùng `storage_state`, đổi đúng một biến:

| trình duyệt | kết quả |
|---|---|
| Chrome thật, chạy ẩn | 100 truy vấn |
| Chrome thật, có cửa sổ | 100 truy vấn |
| **Chromium đi kèm Playwright** | **payload rỗng** |

Google phân biệt được hai bản và trả rỗng cho bản đi kèm — **im lặng, HTTP 200, không lỗi**.
Nếu mọi từ khoá đều ra bảng rỗng thì hãy kiểm chỗ này TRƯỚC, đừng đi tìm ở phiên đăng nhập.
Gói sẽ in một dòng cảnh báo khi phải rơi về bản đi kèm.

---

## Vì sao không dùng `pytrends` hay thư viện tương tự

Chúng dựng lại request tới `/trends/api/widgetdata/*`. **Họ endpoint đó đã chết.** Đo
2026-07-29, và đã loại từng giả thuyết một bằng một phép đo riêng:

- không phải giới hạn theo IP → thử qua 5G với IP hoàn toàn mới, y nguyên 429
- không phải bị nhận diện tự động → `navigator.webdriver = false` + Chrome thật, y nguyên 429
- không phải thiếu đăng nhập → phiên đã đăng nhập, y nguyên 429

Google đã bỏ họ endpoint đó; giao diện `/explore` bản mới không gọi `widgetdata` một lần nào.

Gói này đi đường khác: **mở đúng trang `/explore` bằng Chrome thật rồi bắt lấy phản hồi RPC
`fXqlme` mà chính trang đó phát ra.** Không dựng lại request nào bằng tay, nên nó không hỏng
khi Google đổi cách ký.

---

## Ba điều kiện, thiếu một là bảng rỗng

Cả ba đều trả về **HTTP 200 kèm danh sách rỗng**, không lỗi, không mã trạng thái lạ. Đây là
kiểu chặn nguy hiểm nhất vì nó trông y hệt "từ khoá này không có dữ liệu".

| | |
|---|---|
| **1. Chrome thật** | xem bảng ở trên |
| **2. Phiên đăng nhập** | ẩn danh thì `/explore` dừng ở màn hình mời đăng nhập, không phát RPC nào |
| **3. Tên miền quốc gia** | mặc định `trends.google.com.vn`. Phiên **không** tự lan từ `.com` sang tên miền quốc gia — `login.py` lo phần này |

---

## Hạn mức: nhỏ, và nó bám theo **TÀI KHOẢN**

Đo 2026-08-14 — phép đo sạch: cùng IP, cùng lúc, cùng trình duyệt, đổi đúng một biến là tài
khoản Google. Tài khoản đang dùng trả bảng rỗng, tài khoản khác trả bảng đầy đủ.

**Hệ quả:** xoay tài khoản là cách chia tải đúng. **Proxy thì vô ích** — IP đã được chứng minh
không phải biến số.

Thêm tài khoản: chạy `python -m gtrends.login` nhiều lần, mỗi lần một tài khoản. Gói tự quét
`google.json`, `google-2.json`, `google-cty.json`… và tự chọn phiên nghỉ lâu nhất. Phiên vừa
trả rỗng bị treo 30 phút rồi mới được dùng lại, và một lượt gọi sẽ tự thử tối đa 3 tài khoản.

Gói cũng tự **giãn nhịp 20 giây** giữa hai lần tải trang (`TRENDS_MIN_INTERVAL_MS`). Đây mới
là thứ thật sự giữ cho Trends không chặn — nó chặn theo nhịp, không cần đoán, không chặn nhầm.

### Phân biệt "từ khoá quá nhỏ" với "tài khoản bị chặn"

Hai thứ này trông giống hệt nhau trên giao diện. Gói tách được bằng cách đọc thêm RPC của
**biểu đồ** (`g4kJzf`):

| biểu đồ | bảng cụm từ | nghĩa | `exhausted` |
|---|---|---|---|
| vẽ được | rỗng | từ khoá quá ít lượt tìm | `False` |
| trống trơn | rỗng | tài khoản này bị chặn | `True` — sẽ tự xoay tài khoản |

Nhờ vậy một từ khoá thật sự không có bảng sẽ dừng ngay ở tài khoản đầu tiên, thay vì đốt sạch
cả hồ để nhận về đúng câu trả lời "không có gì" ba lần.

---

## API

```python
async def fetch_related_queries(seed: str, ctx: TrendsContext) -> RelatedOutcome
```

**`TrendsContext`**

| trường | mặc định | |
|---|---|---|
| `country` | `"VN"` | mã hai chữ, hoặc `WORLDWIDE` |
| `time_range` | `"today 12-m"` | `now 1-H`, `now 7-d`, `all`, hoặc `2025-01-01 2025-12-31` |
| `gprop` | `""` | rỗng = web · `images` · `news` · `froogle` (Mua sắm) · `youtube` |

**`RelatedOutcome`**

| trường | |
|---|---|
| `queries` | `list[RelatedQuery]` |
| `message` | câu cho người dùng đọc — `None` khi mọi thứ bình thường |
| `needs_login` | thiếu hoặc hết hạn phiên. Sửa trong hai phút, khác hẳn mọi lỗi khác |
| `exhausted` | tài khoản hết suất — cờ **duy nhất** đáng thử lại bằng tài khoản khác |
| `took_ms` | |

**`RelatedQuery`**

| trường | |
|---|---|
| `query` | |
| `value` | bảng hàng đầu: 0–100 tương đối. Bảng tăng: % tăng trưởng (5000 = nhãn "Đột biến") |
| `rising` | `False` = bảng hàng đầu, `True` = bảng đang tăng |
| `change_percent` | đúng con số cột "Thay đổi" của giao diện |

Hàm thuần, kiểm thử được **không cần Google**: `parse_related(raw)`, `parse_batchexecute(raw,
rpc_id)`, `explore_url(terms, geo, time_range, gprop)`.

Vận hành: `session_pool_status()`, `session_paths("google")`, `close_playwright()`.

---

## Biến môi trường

| biến | mặc định | |
|---|---|---|
| `TRENDS_HOST` | `trends.google.com.vn` | đổi khi triển khai ngoài Việt Nam |
| `TRENDS_MIN_INTERVAL_MS` | `20000` | nhịp tối thiểu giữa hai lần tải trang |
| `GTRENDS_AUTH_DIR` | `gtrends/.auth` | để phiên ra ngoài gói |
| `HEADLESS` | `true` | `false` để nhìn trình duyệt chạy |
| `USER_AGENT` | Chrome 141 | |

---

## Trên Windows: đừng chạy kèm `--reload`

Nếu nhúng vào một server uvicorn: cờ `--reload` (và `--workers`) làm uvicorn đổi sang
`SelectorEventLoop`, mà Playwright thì cần `ProactorEventLoop` để mở tiến trình con. Lỗi ném
ra là `NotImplementedError` **không kèm mô tả**, nên mọi lớp xử lý lỗi phía trên đọc ra thành
"không có lỗi". Gói đã dịch nó thành câu người đọc hiểu được, nhưng cách sửa vẫn là bỏ `--reload`.

---

## Cấu trúc

```
gtrends/
  __init__.py     API công khai
  core.py         lõi — mở /explore, bắt RPC, bóc bảng          (679 dòng)
  login.py        đăng nhập bằng tay, chạy một lần               (472 dòng)
  context.py      TrendsContext
  _browser.py     mở Chrome thật, dựng lại driver khi nó chết
  _auth.py        hồ phiên: chọn, phạt, thưởng
  _ratelimit.py   hàng đợi có giãn nhịp
  example.py      chạy thử
  .auth/          phiên đăng nhập — ĐÃ gitignore, đừng commit
```

Gói **không** phụ thuộc gì ngoài `playwright`. Xoá thư mục là xoá sạch, kể cả phiên đăng nhập.

---

## Lưu ý khi copy

Đây là một **bản tách rời**, không phải thư viện dùng chung. Sửa lỗi ở dự án gốc sẽ không tự
chảy sang bản copy, và ngược lại. Với một gói ổn định như thế này thì đó là đánh đổi đáng —
nhưng nếu Google đổi giao diện `/explore` thì phải sửa ở cả hai nơi.

Phiên đăng nhập: chạy `python -m gtrends.login` ở dự án mới, hoặc copy các tệp
`google*.json` sang `gtrends/.auth/`. Cách sau nhanh hơn nhưng nhớ rằng **hai tiến trình
không được dùng chung một tệp phiên** — Google xoay vòng cookie `__Secure-1PSIDTS` liên tục và
chỉ chấp nhận bản mới nhất, nên hai bên ghi đè lẫn nhau sẽ giết cả hai phiên. Mỗi tệp phiên,
một tiến trình.
