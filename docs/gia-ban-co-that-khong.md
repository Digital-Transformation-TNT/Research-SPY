# Cột "Giá bán" có phải giá thật không — soi từng sàn (08/09/2026)

> Câu hỏi: bấm vào một dòng, chọn đúng sản phẩm, thì có trả đúng con số tool hiện không?
>
> Câu trả lời ngắn: **phần lớn là KHÔNG.** Sàn nào có biến thể thì thẻ tìm kiếm chỉ đưa lên
> MỘT con số, và con số đó luôn là **cái rẻ nhất**. Người bán biết thế, nên hay gắn thêm một
> biến thể 1-2k (dây buộc, sticker, "mẫu thử") để tụt lên đầu bảng sắp theo giá — cái áo vẫn
> 99k như thường.

---

## 1. Bảng soi

| Sàn | Trường tool đang đọc | Có phải giá thật | Bằng chứng |
|---|---|---|---|
| **Etsy** | `price` (API v3) | ❌ **giá sàn** | Đo trực tiếp: **11/12 listing** trả về có `has_variations: true`. Listing 1657090788: API nói 6,70 GBP, trang bán ghi **"187.313₫+"** |
| **TikTok Shop** | `recommend_price_low` | ❌ **giá sàn** | Chính tên trường. `docs/ban-giao.md:157` cũng ghi vậy |
| **Shopee** | `item_card_display_price.price` | ❌ (rất nhiều khả năng) | **CHƯA ĐO ĐƯỢC** — Shopee chặn IP máy chủ (`/verify/traffic`). Xem mục 3 |
| **Amazon** | `.a-price .a-offscreen` đầu tiên | ⚠️ cận dưới khi thẻ có khoảng giá | Đo `amazon.com/s?k=men t shirt`: 2/48 thẻ có hai `.a-price`, code lấy cái đầu |
| **Amazon — TIỀN TỆ** | gán cứng theo tên miền | ❌ **SAI HẲN** | Xem mục 2 |
| **1688** | `priceInfo.price` | ⚠️ giá sỉ theo bậc số lượng | chỉ soi code |
| **Taobao** | `price` / `view_price` | ⚠️ | chỉ soi code |
| **Temu** | `price_info.price_str` | ⚠️ | chỉ soi code |
| **Facebook** | — | không có giá | Ad Library không công bố |

---

## 2. Lỗi nặng nhất KHÔNG phải chuyện biến thể: Amazon ghi sai loại tiền

Đo 2026-09-08, mở `amazon.com/s?k=men t shirt` từ IP Việt Nam. Thẻ ghi:

```
VND 693,173        ← không phải $26.65
```

Amazon đổi tiền theo địa chỉ giao hàng nó **đoán từ IP**, không theo tên miền. Mà
`research.js` gán cứng `AMZ_CUR = { US: 'USD', GB: 'GBP', … }`, còn hàm đọc số thì bóc sạch
ký hiệu tiền trước khi parse. Kết quả: **693.173 được ghi là "693.173 USD"** — lệch hai vạn
sáu nghìn lần, và máy-thợ thì cũng đang ngồi ở Việt Nam.

Không có gì trên màn hình cho thấy sai: cột giá vẫn là một con số. Đây là kiểu hỏng tệ nhất —
bảng vẫn đẹp, chỉ là mọi so sánh giá dựa trên nó đều vô nghĩa.

**Đã sửa:** extension nay gửi kèm nguyên văn chuỗi giá (`priceText`), `research.js` đọc loại
tiền từ chính chuỗi đó (`curTuChu`), chỉ rơi về bảng theo tên miền khi không nhận ra. Bảng ký
hiệu đã thử: `VND 693,173`→VND, `US$26.65`→USD (không nhầm thành SGD), `CA$`→CAD, `NT$`→TWD,
`RM`→MYR, `Rp`→IDR, `£ € ₫ ฿ ₱ ¥`.

---

## 3. Shopee — chưa đo được, và vì sao

Shopee trả `/verify/traffic/error` cho IP máy chủ (đã thử trực tiếp), còn endpoint search thì
đòi phiên đăng nhập. Nên **không kiểm chứng được tên trường từ máy này**.

Phần đã làm là loại thêm-vào-không-hỏng-gì: `parseItem` giờ đọc thêm cặp `price_min`/`price_max`
ở `item_basic` và ở khối giá của thẻ. **Có** thì cột giá lấy MAX (xem mục 4); **không có** thì
mọi thứ chạy y hệt trước.

**Cần một lượt đo trên máy có đăng nhập Shopee** để chốt: tìm một sản phẩm có biến thể rẻ, mở
DevTools ở tab shopee.vn, xem response `search_items` của item đó có những khoá giá nào. Biết
tên khoá thật thì sửa đúng một dòng.

---

## 4. Đã sửa: có cặp min/max thì LẤY MAX làm giá hiển thị

```
có cả min/max        →  99.000 VND
                        thấp nhất 2.000 VND      ← giữ ở dòng nhỏ
chỉ biết là cận dưới →  từ 6,7 GBP               (Etsy has_variations, TikTok recommend_price_low)
giá đơn              →  50 USD                   (như cũ)
```

Cận trên là con số gần với giá phải trả cho món hàng thật. Vẫn giữ cận dưới ở dòng nhỏ chứ
không vứt: khoảng cách giữa hai đầu chính là dấu hiệu người bán đang gắn biến thể mồi — 2k↔99k
nói nhiều hơn bất kỳ con số đơn nào.

Sàn không trả cận trên (Etsy, TikTok Shop) thì vẫn chỉ ghi "từ X" — ở đó đổi số là đoán.

**MỘT hàm quyết định, dùng cho cả ba chỗ** (`giaDung`): cột hiện, sắp xếp theo giá, và so với
giá vốn. Tách ra ba chỗ tự tính là kiểu lỗi khó thấy nhất — cột hiện 99k mà sort xếp theo 2k
thì nhìn ra đúng như bảng bị sắp sai.

Nhờ vậy **cái bẫy "gắn biến thể 1k để leo đầu bảng" hết tác dụng**: sắp theo giá tăng dần, cái
áo giờ nằm ở đúng 99k chứ không lẫn vào nhóm phụ kiện 2k.

---

## 4b. Amazon — soi lại từng cột (08/09/2026)

Chạy đúng mã bóc của extension trên `amazon.com/s?k=razer blackshark v2 x`, 21 thẻ:

| Cột | Nguồn | Lấy được | Ghi chú |
|---|---|---|---|
| Giá đối thủ | `.a-price .a-offscreen` | 15/21 → 18/21 → **15/16** | ba lớp sửa, xem dưới |
| Bán/tháng | chữ "X+ bought in past month" | 15/21 | thẻ không có câu đó thì `—`, đúng |
| Tổng bán | — | **luôn `—`** | Amazon không công bố tích luỹ. Không phải lỗi |
| Rating | `.a-icon-alt` | 19/21 | |
| Số đánh giá | `alf-customer-ratings-count-component` | 19/21 | |
| Ảnh | `img.s-image` | 21/21 | |

### Giá `—`: SÁU thẻ, HAI nguyên nhân

Gộp chúng làm một là lý do trước giờ không ai sửa:

- **3 thẻ — lỗi của ta.** Giá hiện rõ trên màn hình ("VND 2,712,585") nhưng nằm trong một
  `<span class="a-color-base">` trần: `.a-price` và `.a-offscreen` đều bằng **0**. Amazon có
  một bố cục thẻ thứ hai không dùng component giá.
- **3 thẻ — `—` là câu trả lời ĐÚNG.** Thẻ "See options" / hết hàng, không có giá nào. Bịa số
  vào đây còn tệ hơn để trống.

Đã thêm nhánh vớt: nhận node mà **toàn bộ** chữ của nó là một con số có ký hiệu tiền, bỏ qua
node trong `.a-text-price` (giá gạch). Chặt như vậy để không vớt nhầm "50mm", "7.1 Surround",
"70 Hr Battery". Kết quả: 15 → **18/21**.

### Vì sao KHÔNG lấp nốt ba ô cuối

Mở trang chi tiết của đúng ba ASIN ấy, buy-box ghi:

> *"This item cannot be shipped to your selected delivery location."*

**Amazon không bán món đó tới nơi giao hàng của máy-thợ.** Không có giá nào tồn tại để mà lấy.
Trang vẫn đầy số VND, nhưng đó là giá của các thẻ GỢI Ý bên cạnh — điền chúng vào là lặp lại
đúng cái bệnh "giá không thật" mà mục 1-4 vừa chữa. Ô trống ở đây là câu trả lời ĐÚNG.

Đổi lại, ô trống nay **tự nói vì sao**: rê chuột vào dấu `—` thì hiện *"Sàn không hiện giá cho
sản phẩm này — thường là hết hàng, phải chọn phiên bản, hoặc không giao tới nước đang chọn."*

### ĐẶT TIỀN TỆ TỪ NGUỒN — sửa được cả hai vấn đề cùng lúc

Amazon nhớ lựa chọn tiền tệ ở cookie `i18n-prefs`. Đặt nó trước khi crawl thì không phải đoán
xem vừa nhận được thứ gì. Đo cùng truy vấn `razer blackshark v2 x` từ IP Việt Nam:

| | tiền | thẻ có giá |
|---|---|---|
| không cookie | VND | 15/21 |
| `i18n-prefs=USD` | **USD** ($39.99, $71.99…) | **15/16** |

Cookie này vừa trả đúng loại tiền, vừa làm phần lớn ô trống biến mất — vì với địa chỉ giao hàng
Mỹ thì những món "không giao tới VN" lại có giá. Còn đúng **1 thẻ** trống, và đó là hàng hết.

`curTuChu` (đọc loại tiền từ chuỗi giá) vẫn giữ làm lưới đỡ, phòng khi Amazon bỏ qua cookie.

### Ô "Sàn" in tên nước hai lần

Ô ghi `Amazon 🇺🇸 US` — cờ **và** mã nước. Windows không vẽ được emoji cờ (nó dựng từ hai chữ
cái vùng) nên trên máy người dùng nó tụt xuống thành hai chữ thường: **"Amazon us US"**, nhìn
như lỗi dữ liệu. Trùng lặp này có ở mọi hệ điều hành, Windows chỉ làm nó lộ ra. Nay còn
`Amazon · US`.

---

## 5. Việc còn để lại

- **Sàn nào không trả cận trên thì vẫn kẹt ở cận dưới** — Etsy và TikTok Shop chỉ nói được
  "từ X". Muốn ra số thật phải gọi thêm endpoint chi tiết cho từng dòng (Etsy `inventory` đòi
  OAuth, không dùng được với app key), tức là một lượt gọi mỗi sản phẩm.

- **1688 / Taobao / Temu** mới chỉ soi code, chưa đo. 1688 là giá sỉ theo bậc số lượng nên
  "giá thật" ở đó vốn đã là một khoảng, không phải một số.

- **Extension phải Reload trên máy-thợ** thì phần sửa tiền tệ Amazon mới có hiệu lực
  (`chrome://extensions` → Reload → F5 tab `/worker`).
