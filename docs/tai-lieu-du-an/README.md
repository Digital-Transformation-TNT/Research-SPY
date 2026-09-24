# Tài liệu dự án Research SPY — ba bản bàn giao

Bản đang chạy: **https://tntecom.com/research/** · VPS Windows `157.66.101.73` ·
thư mục `C:\AI-TNT-Research-SPY` · nhánh làm việc **`Titus`**.

Viết ngày **24/09/2026**, mọi con số trong đây đo trên chính máy production hôm đó.

| | Tài liệu | Đọc khi nào |
|---|---|---|
| ① | **[Cài đặt và đưa lên tên miền](1-cai-dat-va-deploy.md)** | dựng lại từ `git clone` tới lúc cả công ty dùng được. Mỗi bước gắn nhãn 🤖 **AI làm** / 👤 **chỉ người làm được** |
| ② | **[Chức năng và logic](2-chuc-nang-va-logic.md)** | cần hiểu app làm gì, function nào ở đâu, vì sao tính điểm như vậy |
| ③ | **[Tài khoản và sự cố](3-tai-khoan-va-su-co.md)** | phải đăng nhập những gì, phiên sống bao lâu, hỏng thì xử sao |

## Đọc theo mục đích

**Người mới nhận bàn giao, chưa biết gì** → ① §0 (bản đồ một phút) → ② §0 (sidebar) → ③ §0
(bảng mười tài khoản). Ba trang đó là toàn bộ bức tranh.

**Phải dựng lại server từ đầu** → ① từ đầu đến cuối, rồi ③ §2–§7 để đăng nhập lại từng nguồn.
Đọc **① §1 trước tiên**: nó tách rõ việc nào giao cho Claude Code và việc nào **chỉ người làm
được** (tạo Supabase, chạy SQL, lấy khoá API, trỏ DNS, đăng nhập Google, dựng máy-thợ). Nhiều
việc trong nhóm sau cần xin quyền hoặc mất tiền — biết sớm thì đỡ tắc giữa đường.

**Cài xong rồi mà nguồn vẫn trống** → ① §7 (đăng nhập Google + dựng máy-thợ). Đây là phần hay bị
bỏ quên nhất: ba service `Running` **không** có nghĩa là có dữ liệu.

**Mở cho cả công ty dùng** → ① §8: thông báo địa chỉ, duyệt user, ba giới hạn phải nói trước, và
ai trực hằng ngày. Kèm checklist đánh dấu ở **① §14**.

**Vừa sửa code, cần nạp lại** → ① §9. Lưu ý `C:\AI-TNT-Research-SPY` **vừa là bản clone để
sửa, vừa là thư mục ba service đang chạy** — không có khâu deploy, chỉ có build (nếu sửa
frontend) rồi restart service.

**Đang trực vận hành, tool báo lỗi** → ③ §10 (cây quyết định) → ③ §11 (bốn thứ KHÔNG phải sự
cố, đừng đi sửa).

**Sắp sửa code** → ② §1 (quy tắc phụ thuộc) và ② §12 (quy ước). Đặc biệt đọc ② §1.1: **ba cặp
file "soi gương" nhau**, sửa một bên mà quên bên kia thì không có gì tự bắt được.

## Tài liệu liên quan trong repo

| Đường dẫn | Là gì |
|---|---|
| [`../../README.md`](../../README.md) | README gốc — **đã lệch một phần** (còn tả bốn mục `/ads /keywords /image /opportunity`). Chỗ nào lệch thì tin ② |
| [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md) | thêm một nguồn dữ liệu mới, kèm ví dụ đầy đủ |
| [`../ban-giao.md`](../tai-lieu-ky-thuat/ban-giao.md) | bản bàn giao **04/08/2026** — trạng thái & lộ trình, đã cũ một phần nhưng còn giá trị ở mục "chưa làm" |
| [`../kalodata-api.md`](../tai-lieu-ky-thuat/kalodata-api.md) | đặc tả API Kalodata |
| [`../nguon-du-lieu-tung-san.md`](../tai-lieu-ky-thuat/nguon-du-lieu-tung-san.md) · [`../gia-ban-co-that-khong.md`](../tai-lieu-ky-thuat/gia-ban-co-that-khong.md) | nhật ký nghiên cứu: từng sàn cho số gì, và giá có thật không |
| [`../../extension/README.md`](../../extension/README.md) · [`../../extension-kalodata/README.md`](../../extension-kalodata/README.md) | hai extension, cài và vận hành |
| `backend/.env.example` | **tài liệu duy nhất mô tả từng biến môi trường** — đọc comment trong đó, đừng đoán |
