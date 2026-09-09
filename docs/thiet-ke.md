# Luật thiết kế giao diện (08/09/2026)

> Lấy **cấu trúc** từ `DESIGN.md` của Linear
> (<https://github.com/VoltAgent/awesome-design-md> → `design-md/linear.app/`), **bỏ bảng màu**
> của họ. Giữ nguyên cam `#f26522` và bộ chữ hiện có.
>
> Phải nói rõ chỗ này vì tài liệu gốc chống lại đúng hai lựa chọn ấy: phần "Don't" của nó ghi
> *"đừng làm bản nền sáng"* và *"đừng thêm màu nhấn thứ hai (cam…)"*. Cả hai câu đó nói về
> trang **marketing nền tối** của Linear. Thứ tool này cần không phải bảng màu của Linear mà là
> cách họ xếp thông tin — và phần ấy thì trung tính với màu nền.

---

## 1. Bệnh cần chữa

Nhận xét của chủ dự án: *"nhìn bên ngoài trông lôm côm và hơi xấu, bố cục và sắp xếp nhìn không
đẹp mắt còn dài dòng"*. Cụ thể hoá được thành ba thứ đo đếm được:

| Triệu chứng | Nguyên nhân |
|---|---|
| Cột trái dài gần hết màn hình cho 5 mục | Mỗi mục là một khối 3 dòng: nhãn + câu mô tả xuống dòng |
| Khối điều khiển tab Sản phẩm chiếm nửa trên | Ba "bước" đánh số, mỗi bước một dải ngang có tiêu đề riêng |
| Các khối cạnh nhau không thẳng hàng | Mỗi chỗ tự chọn một khoảng cách: 3px, 9px, 10px, 13px, 14px, 18px, 20px… |

## 2. Luật đã áp

### Thang cách — đơn vị gốc 4px

`--s-1` 4 · `--s-2` 8 · `--s-3` 12 · `--s-4` 16 · `--s-6` 24 · `--s-8` 32 · `--s-12` 48.
Mọi khoảng cách mới lấy từ đây. Số lẻ tự chọn là thứ tạo cảm giác "lôm côm" rõ nhất, và nó
không sửa được bằng cách chỉnh từng chỗ một.

### Thang bo góc

`--r-xs` 4 (chip, badge) · `--r-sm` 6 (thẻ nhỏ, chip chọn) · `--r-md` 8 (**nút và ô nhập**) ·
`--r-lg` 12 (panel). **Không bo pill cho nút** — pill để dành cho chip trạng thái.

### Độ sâu: bề mặt + viền, KHÔNG bóng đổ

Nguyên tắc mạnh nhất lấy từ Linear, và là thứ chữa được chữ "bẩn": thứ bậc do **nền** và **viền
1px** gánh, không phải bóng. Nhiều khối cùng đổ bóng thì tất cả cùng trôi nổi, mắt không còn
biết khối nào đang được trỏ.

- `--shadow: none` (tên biến giữ lại để CSS cũ không vỡ). Panel vốn đã có `border` nên bỏ bóng
  đi không mất ranh giới nào.
- Rê chuột đổi **viền / nền**, không nhấc thẻ lên.
- Cần nổi hơn thì **lên một bậc bề mặt**: `--bg` → `--surface` → `--surface-2` → `--surface-3`.

### Chữ

Một giọng duy nhất, phân cấp bằng **cỡ và sắc độ**, không bằng màu. Nhãn nhóm dùng chữ hoa nhỏ
11px `letter-spacing .04em` màu mờ — đó là "eyebrow" của Linear, đánh dấu phân loại chứ không
tranh chỗ với nội dung.

## 3. Đã sửa những gì

**Thanh bên** — mỗi mục còn **một dòng**, cao 30px. Câu mô tả chuyển sang `title`, hiện khi rê
chuột, nên không mất thông tin nào. Cột hẹp lại 268 → 232px, icon 19 → 16px và mờ đi khi không
được chọn.

**Tab Sản phẩm** — bỏ ba "bước" đánh số. Việc chính (gõ từ khoá + Research) lên hàng đầu; ba
hàng còn lại là nhãn-bên-trái + điều khiển, cột nhãn rộng cố định 66px để **ba hàng thẳng nhau**.
Chip chọn: pill → bo 6px, thấp hơn (đệm 6/12 → 4/10), chữ 600 → 500.

**Tab Image Search** — bỏ số tròn cam y như trên, tiêu đề bước thành nhãn chữ hoa nhỏ cùng dáng
với tab Sản phẩm. Hai tab giờ đọc giống nhau thay vì mỗi tab một kiểu.

**Thẻ video** — bỏ nhãn nguồn TRÙNG LẶP (tên sàn từng in hai lần trên một thẻ ba dòng: một lần
đè lên ảnh bìa, một lần ở pill dưới thân). Bỏ bóng + hiệu ứng nhấc thẻ khi rê chuột. Dòng
eyebrow của cửa sổ sửa lại cho đúng sự thật: nó ghi "(Facebook Ad Library)" từ thời chỉ có một
nguồn, giờ có năm.

## 3b. Chọn nước: nút gọn + bảng thả xuống (09/09/2026)

Bản trước trải HẾT chip nước của MỌI sàn đang chọn ra màn hình. Bốn sàn là bốn khối xếp dọc —
Shopee 11 nước, Amazon 8, TikTok Shop 8, Temu 5 — **hơn ba mươi chip** cho một lựa chọn mà phần
lớn lượt dùng chỉ đụng tới một nước. Nó đẩy bảng kết quả xuống dưới màn hình đầu tiên.

Nay mỗi sàn là **một nút mang sẵn câu trả lời**; bấm mới mở danh sách có cuộn:

```
SÀN    [Shopee] [TikTok Shop] [Amazon] [Etsy] [Taobao] [1688] [Temu]
NƯỚC   Shopee 3 nước ▾   TikTok Shop 🇻🇳 Việt Nam ▾   Amazon 🇺🇸 Mỹ ▾   Temu 🇺🇸 Mỹ ▾
```

Bốn sàn nằm gọn **một hàng**. Khối điều khiển: **207px** (bốn khối chip cũ chiếm 335px, và ảnh
người dùng gửi còn dài hơn nữa vì mỗi sàn tràn hai hàng chip).

Dáng chép từ `.dd-*` của webtool (tab Keyword) để hai bên là một thứ, không phải hai kiểu.

### Đóng lại thế nào

**Không còn công tắc "Một nước / Nhiều nước".** Tick một nước ra một, tick mấy nước ra mấy —
không có gì để người dùng phải khai báo trước. Công tắc ấy sinh ra từ thời mỗi sàn là một hàng
chip trải ngang, khi bấm-để-thay-thế đỡ được vài cú bấm; từ lúc danh sách nằm trong bảng thả
xuống thì nó chỉ còn là một trạng thái thừa mà người dùng phải nhớ.

| Việc | Hành vi | Vì sao |
|---|---|---|
| Tick / bỏ tick | **giữ bảng mở** | không đoán được người ta đã xong hay còn tick tiếp, nên đừng đoán |
| Bấm ra ngoài · Esc · nút "Xong" | đóng | ba lối thoát người ta thử theo phản xạ |
| Bỏ tick nước CUỐI của một sàn | từ chối | sàn không còn nước nào thì không chạy được; muốn bỏ hẳn thì bỏ chọn sàn ở hàng SÀN |

Nhãn trên nút tự đổi theo: một nước thì hiện tên nước, nhiều thì đếm ("3 nước"). Dấu ✕ chỉ hiện
khi **nước ĐANG CHỌN** chưa đăng nhập — một nước chưa đăng nhập mà không ai chọn thì không phải
việc của người dùng lúc này.

### Một cái bẫy đã sập, ghi lại

Bấm nút mở bảng → không mở. Nguyên nhân: cú bấm ấy **vẽ lại toàn bộ `#regions`**, nên tới lượt
bộ lắng nghe "bấm ra ngoài thì đóng" (nằm ở `document`, chạy sau) thì `e.target` đã bị gỡ khỏi
tài liệu — `closest('#regions')` trên một node mồ côi trả về `null`, và nó kết luận là bấm ra
ngoài. Bảng mở ra rồi đóng lại trong cùng một cú bấm, nhìn y như nút không ăn.

Chữa bằng `e.stopPropagation()` trong bộ lắng nghe của `#regions`.

Cùng lý do, `rgOpen` (sàn nào đang mở) phải là **biến ngoài hàm**, không phải trạng thái nằm
trong DOM: `refreshLogin` vẽ lại sau MỖI nước nó kiểm (11-19 lượt), nên trạng thái để trong DOM
sẽ tự đóng bảng giữa chừng ngay dưới tay người dùng.

---

## 4. Chưa làm

- **Bảng kết quả** chưa đụng nhiều (mới nới lại khoảng đệm). Nó vốn đã gần với Linear sẵn: đầu
  bảng dính, chữ hoa mono, viền tóc từng hàng, số canh phải dạng `tabular-nums`. Nhưng **chưa
  xem được với dữ liệu thật** — Shopee chặn IP máy chủ nên tôi không dựng được một bảng đầy để
  soi. Cần chủ dự án chạy một lượt rồi nói chỗ nào còn chướng.
- **Trend Signal Hub / Hướng dẫn / Quản trị** mới ăn theo tầng token, chưa xem lại bố cục từng
  trang.
- `styles/opportunity.css`, `keywords.css` mới đổi theo token, chưa rà từng khối.
