# Từng sàn lấy dữ liệu bằng đường nào, và cột nào trống (08/09/2026)

> Trả lời hai câu hỏi: *"các sàn khác ok hết chưa"* và *"có dùng API nội bộ của sàn thay vì
> scrape được không"*.
>
> Câu thứ hai có một tiền đề cần chỉnh: **7/8 sàn đã đang dùng API nội bộ rồi.** Chỉ Amazon là
> đọc DOM, và đó không phải lựa chọn — Amazon không có endpoint tìm kiếm nào để gọi.

---

## 1. Đường lấy dữ liệu

| Sàn | Đường đi | Loại |
|---|---|---|
| **Shopee** | `/api/v4/search/search_items` | API nội bộ · fetch trong tab đã đăng nhập |
| **TikTok Shop** | seller center `product/opportunity` | API nội bộ · SDK của trang tự ký |
| **Taobao** | `mtop.taobao.wsearch.h5search` | API nội bộ · **ký sinh** (trang tự gọi, ta chộp response) |
| **1688** | `mtop.relationrecommend.WirelessRecommend.recommend` | API nội bộ · gọi thẳng trong tab `h5api` |
| **Temu** | `/api/poppy/v1/search` | API nội bộ · ký sinh (cần token `anti-content`) |
| **Etsy** | `openapi.etsy.com/v3` | **API CHÍNH THỨC**, có API key |
| **Facebook** | JSON nhúng sẵn trong HTML trang Ad Library | không phải API, nhưng là JSON có cấu trúc |
| **Amazon** | **đọc DOM trang search** | ❗ sàn DUY NHẤT phải scrape |

**Vì sao ba sàn phải "ký sinh".** Taobao cần chữ ký mtop + cookie chống bot `x5sec` (Baxia),
Temu cần token `anti-content`; cả hai do JS của trang tự sinh lúc chạy và xoay liên tục, viết
lại thì hỏng mỗi lần họ đổi. Nên để CHÍNH TRANG gọi, ta chỉ bọc `fetch`/XHR để chộp response.
Vẫn là dữ liệu API, chỉ khác cách phát request.

### Amazon: vì sao không có API để dùng

- **Product Advertising API** (API duy nhất của Amazon cho dữ liệu sản phẩm) đòi tài khoản
  Associates **đã phát sinh doanh số** mới được cấp quyền, và cấm dùng cho mục đích không phải
  bán hàng cho họ. Không phải thứ bật lên là dùng được.
- Không có endpoint search nội bộ nào để ký sinh: trang `/s?k=` render **SSR** — kết quả nằm
  thẳng trong HTML, không có XHR nào chở danh sách sản phẩm để mà chộp.
- `curl` trần được HTTP 200 nhưng trang bị rút gọn (288 KB so với 1,3 MB từ trình duyệt) —
  Amazon phát bản nghèo cho client không phải trình duyệt.

→ Đọc DOM là đường đúng ở đây, không phải đường tạm.

---

## 2. Cột nào có, cột nào trống

| Sàn | Bán/tháng | Tổng bán | Rating | Số đánh giá | Giá |
|---|---|---|---|---|---|
| Shopee | ✅ | ✅ | ✅ | ✅ | ✅ *(xem mục giá-từ)* |
| TikTok Shop | ✅ 30 ngày | ❌ sàn không có | ❌ | ❌ | ⚠️ `recommend_price_low` = giá sàn |
| Amazon | ⚠️ chỉ món bán chạy | ❌ **sàn không công bố** | ✅ | ✅ | ✅ sau khi sửa (15/16) |
| 1688 | ✅ `bookedCount` | ✅ "已售…件" | ⚠️ điểm **SHOP**, không phải SP | ❌ | ✅ giá sỉ theo bậc |
| Taobao | ✅ | ❌ | ❌ | ❌ | ✅ |
| Temu | ❌ sàn không tách tháng | ✅ "11K+ sold" | ✅ | ❌ | ✅ |
| Etsy | ✅ lượt xem *(đã sửa)* | ✅ của shop *(đã sửa)* | ⚠️ rating **SHOP**, có nhãn | ✅ | ✅ |
| Facebook | — | — | — | — | — không có giá |

Đo thật trên Etsy, 24 listing: giá 24/24 · rating 23/24 · "tổng bán" (favorites) 10/24 ·
bán/tháng 0/24.

### Ô trống KHÔNG phải lỗi

Phần lớn ô trống ở bảng trên là **sàn không công bố**, không phải tool không lấy được:

- Amazon không bao giờ công bố số bán tích luỹ.
- Temu không tách số bán theo tháng, chỉ có tổng.
- TikTok Shop `product/opportunity` không trả rating.
- Etsy giấu số bán theo listing — `num_favorers` là thứ gần nhất, và tool đã ghi rõ điều đó
  trong `notice`.

### Ba chỗ dễ ĐỌC NHẦM — đáng sửa hơn ô trống

1. **1688 và Etsy: cột "Rating" là điểm của SHOP, không phải của sản phẩm.** Một shop 4.9★
   vẫn có thể bán một mẫu tệ. Cột hiện đang không phân biệt hai thứ đó.
2. **Etsy: cột "Tổng bán" là LƯỢT YÊU THÍCH.** Đã có `notice` nói, nhưng con số vẫn nằm chung
   cột với số bán thật của Shopee/Temu — đặt cạnh nhau là so sánh sai.
3. **1688: giá là giá SỈ theo bậc số lượng**, không cùng thang với giá bán lẻ của các sàn khác.
   Cột "Giá đối thủ" gộp cả hai loại vào một chỗ.

Cả ba đều là chuyện **nhãn**, không phải chuyện lấy dữ liệu — và đều chưa sửa.

---

## 2b. ĐÃ SỬA: Etsy lấy đúng chỉ số, và ba cột gọi đúng tên (08/09/2026)

Dò thẳng API bằng app key (không OAuth), mẫu 120 listing / 3 từ khoá:

| Chỉ số | Etsy có | Độ phủ |
|---|---|---|
| `views` — lượt xem listing | ✅ | **47%** ← chỉ số cầu theo LISTING duy nhất |
| `num_favorers` | ✅ | 34% — thưa hơn, và dễ bơm |
| `shop.transaction_sold_count` | ✅ | **90%**, trung vị 827 đơn — số bán THẬT, của SHOP |
| `shop.review_average` | ✅ | 90%, trung vị 139 review |
| `listings/{id}/reviews` | ✅ endpoint chạy | nhưng thường **0-1 review**/listing → vô nghĩa |
| số bán theo listing | ❌ | Etsy giấu hẳn, không có trường nào |
| giá cận trên (biến thể) | ❌ | `inventory` → **401**, đòi OAuth. Và OAuth chỉ cấp quyền đọc kho của shop CHÍNH MÌNH → bất khả |

**Đổi:** cầu = `views`, tổng bán = `shop.transaction_sold_count`, rating = điểm shop (giữ, vì
rating theo listing chỉ có 1 review). Đo lại trên 24 listing:

| Cột | Trước | Sau |
|---|---|---|
| Cầu | **0/24** (không có gì) | **21/24** lượt xem |
| Tổng bán | 10/24 (lượt thích) | **24/24** shop đã bán |

**Và ba cột giờ tự nói con số của mình là của AI** — `sold_is_shop` / `rating_is_shop` /
`view_count` là ba trường riêng, không nhét chỉ số này vào ô của chỉ số khác:

```
Shopee   820          15.400              4,8★ 2.103
Etsy     5.699        36.798              4,81★ 5.915 · shop
         lượt xem     của shop
1688     310          19.000              4,9★ shop
Amazon   9.000        —                   4,4★ 2.403
```

Phần chấm điểm cũng hạ thang cho hai loại số yếu hơn: lượt xem chia 5 (thay vì 4 như số bán
thật) và số bán của shop chia 7 — **xem không phải mua, và một shop 800 đơn không nói gì về mẫu
đang xem; nó có thể là mẫu ế nhất trong 68 mẫu.** Lý do chấm điểm hiện đúng câu đó ra màn hình.

---

## 3. Kết luận

- Không có sàn nào đang scrape mà lẽ ra dùng được API. Đổi sang API nội bộ **không còn gì để
  đổi** — trừ Amazon, nơi không có API nào để đổi sang.
- Ô trống còn lại gần như đều là giới hạn của sàn. Muốn lấp thì phải mở trang chi tiết từng sản
  phẩm (đã đo: 4 trang trong 9,5 giây từ server, lấy được rating + số đánh giá), tức một lượt
  gọi cho mỗi dòng.
- Việc đáng làm tiếp không phải "lấy thêm số", mà là **gọi đúng tên ba con số đang bị đặt nhầm
  cột** ở mục 2.
