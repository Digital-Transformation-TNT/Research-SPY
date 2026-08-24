# Bắt đầu trong 10 phút

Hướng dẫn ngắn để chạy thử. Chi tiết đầy đủ ở [README.md](README.md).

## Cần có sẵn

- **Google Chrome** (bản thật, không phải Edge/Cốc Cốc)
- **Python 3.12+** — cài nhớ tick *"Add Python to PATH"*
- **Node.js 20+**

## Cài — làm một lần

```bash
git clone https://github.com/Digital-Transformation-TNT/Research-SPY.git
cd Research-SPY/backend

python -m pip install -r requirements.txt
python -m playwright install chromium
```

Xong. Phần `frontend` để `start.bat` tự lo.

## Chạy

**Nhấp đúp `start.bat`** ở thư mục gốc.

Nó mở hai cửa sổ đen (backend + frontend) rồi tự mở trình duyệt vào
**http://localhost:3000**. Lần đầu chờ khoảng 2–3 phút vì còn cài `node_modules`.

Tắt: đóng cả hai cửa sổ đen đó.

## Bốn mục dùng được ngay, không cần cài gì thêm

| Mục | Làm gì |
|---|---|
| **Keyword** | Mở rộng từ khoá, đo xu hướng |
| **Cơ hội** | Hỏi đáp về khoảng trống thị trường |
| **Image Search** | Một tấm ảnh, ra nguồn hàng và giá ở 5 sàn |
| **Sản phẩm & Content** → tab *Content (FB Ads)* | Quảng cáo Facebook đang chạy |

## Muốn dùng tab *Sản phẩm* (Shopee, TikTok Shop, Amazon…) thì cài thêm extension

Các sàn này chặn máy chủ, chỉ chấp nhận phiên đăng nhập thật. Nên phần đó chạy trong
chính trình duyệt của bạn:

1. Mở `chrome://extensions`
2. Bật **Developer mode** — nút gạt **góc phải trên cùng**. *(Không bật thì không thấy nút ở bước sau.)*
3. Bấm **Load unpacked** → chọn thư mục `extension` trong dự án → **Select Folder**
4. Đăng nhập sẵn sàn bạn định tra: `shopee.vn`, `seller-vn.tiktok.com`…
5. Quay lại `localhost:3000/ads`, bấm **⟳ Kiểm tra đăng nhập**

Chip nước nào hiện **✓** là chạy được, **✕** là chưa đăng nhập — bấm vào chip đó, nó tự mở
trang cho bạn đăng nhập. Amazon và 1688 không cần đăng nhập.

## Ba lỗi hay gặp

| Hiện tượng | Cách xử |
|---|---|
| Trang báo *"Chưa thấy extension"* | Chưa cài, hoặc vừa cập nhật code — vào `chrome://extensions` bấm **⟳** trên thẻ extension rồi F5 lại trang |
| Bảng thiếu hẳn một sàn, không báo gì | Nước đó đang **✕** nên bị bỏ qua. Đăng nhập rồi bấm ⟳ Kiểm tra đăng nhập |
| Cửa sổ đen báo cổng 8000 đang bận | Công cụ đã chạy rồi. Đóng cửa sổ cũ trước khi chạy lại |

## Hai điều nên biết

- **Tab 🔍 Tìm bằng ảnh** bên trong mục *Sản phẩm & Content* chưa hoàn thiện — dùng mục
  **Image Search** ở thanh bên trái.
- Một số nguồn cần khoá API (Gemini, YouTube, Etsy). Không có vẫn chạy, chỉ thiếu vài
  chức năng — xem [backend/.env.example](backend/.env.example) nếu cần bật.
