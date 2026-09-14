# Kalodata — API nội bộ (reverse-engineered)

> Nguồn: bundle SPA `production/assets/index-*.js` + bắt Network trên tài khoản thật (2026-09-08).
> Đây là **API nội bộ**, không phải API công khai. Xem mục Rủi ro ở cuối.

## Base URL

```
https://www.kalodata.com
```

Không có prefix `/api` cho nhóm endpoint dữ liệu (`/video/*`, `/product/*`...).
Prefix `/api/` chỉ dùng cho nhóm phụ trợ (`/api/credit/log/list`, `/api/tiktok/column/*`, `/api/pilot/*`).

Envelope chung của mọi response:

```json
{ "success": true, "data": ..., "message": null, "cached": null, "code": null }
```

## Cơ chế 2 pha

Bundle ghép URL động: `/${module}/searchList`, `/${module}/enrich`, `/${module}/count`
với `module` ∈ `video | product | creator | shop | livestream`.

1. **`POST /{module}/searchList`** → danh sách ID + field cơ bản
2. **`POST /{module}/enrich`** → số liệu chi tiết cho các ID đó (view, GMV, sale...)
3. **`POST /{module}/count`** → tổng số kết quả (để phân trang)

Khi **không** có keyword, UI gọi `/{module}/queryList` thay cho `searchList`.

## Video — search theo keyword

`POST https://www.kalodata.com/video/searchList`

```json
{
  "country": "VN",
  "startDate": "2026-08-09",
  "endDate": "2026-09-07",
  "cateIds": [],
  "showCateIds": [],
  "pageNo": 1,
  "pageSize": 10,
  "sort": [{ "field": "sale", "type": "DESC" }],
  "video.filter.video_type": "WithProduct",
  "video.filter.ad.daily_roas": "",
  "title": "mũ lưỡi trai"
}
```

| Field | Ý nghĩa |
|---|---|
| `country` | **mã region** — xem bảng bên dưới |
| `startDate` / `endDate` | khoảng ngày `YYYY-MM-DD` |
| `title` | keyword tìm kiếm |
| `cateIds` / `showCateIds` | lọc theo ngành hàng (rỗng = tất cả) |
| `pageNo` / `pageSize` | phân trang |
| `sort` | `[{field, type: ASC\|DESC}]`, vd `sale` |
| `video.filter.*` | filter nâng cao, kiểu chuỗi so sánh: `">5"`, `"<50000"`, `"<0"` |

Pha 2:

`POST https://www.kalodata.com/video/enrich`

```json
{ "ids": ["7666854005661895957", "..."],
  "country": "VN", "startDate": "2026-08-09", "endDate": "2026-09-07",
  "cateIds": [] }
```

## Product — search theo keyword

`POST https://www.kalodata.com/product/searchList`

```json
{
  "country": "VN",
  "startDate": "2026-08-09",
  "endDate": "2026-09-07",
  "cateIds": [], "showCateIds": [],
  "pageNo": 1, "pageSize": 10,
  "query": "tai nghe bluetooth"
}
```

⚠️ Product dùng key **`query`**, video dùng **`title`**. Đừng nhầm.

### Field trả về (đã xác minh trên response thật)

```
id, product_title, revenue, sale, unit_price, min_real_price, max_real_price,
commission_rate, product_rating, launch_date, shipping_fee, creator_num,
creator_conversion_ratio, video_revenue, live_revenue, showcase_revenue,
revenue_trend, revenue_grouping_rate, total,
pri_cate_id, sec_cate_id, ter_cate_id, delivery_type,
is_full_service, is_overseas, is_tokopedia
```

Mẫu 1 bản ghi:

```json
{
  "id": "1730778421072202679",
  "product_title": "Tai nghe Bluetooth Pro3, Pin 8H, Bass Mạnh...",
  "revenue": "₫3,56tr", "sale": 10, "unit_price": "₫355,94k",
  "min_real_price": "₫330,00k", "max_real_price": "₫330,00k",
  "commission_rate": "1%", "product_rating": 4.8,
  "launch_date": "2024-10-18", "shipping_fee": "₫0,00",
  "creator_num": 10, "creator_conversion_ratio": 0.2,
  "video_revenue": "₫0,00", "live_revenue": "₫3,18tr", "showcase_revenue": "₫382,78k",
  "revenue_grouping_rate": "-100%",
  "revenue_trend": [702567, 0, 332263, 0, 0, 365320, ...],
  "total": 324,
  "pri_cate_id": 601739, "sec_cate_id": 909320, "ter_cate_id": 601990,
  "delivery_type": "local", "is_overseas": 0, "is_tokopedia": 0, "is_full_service": 0
}
```

### ⚠️ Số tiền trả về là CHUỖI đã format

`revenue: "₫3,56tr"` — đã áp ký hiệu tiền tệ theo `country` và rút gọn (`k`, `tr`).
**Đừng parse chuỗi này.** Dùng `revenue_trend` thay thế:

- là **mảng số nguyên thô**, mỗi phần tử = doanh thu 1 ngày, độ dài = số ngày trong khoảng lọc
- `sum(revenue_trend)` == `revenue` chính xác tới từng đồng
  (đã kiểm: 702567+332263+365320+382431+346829+351808+362948+382781+332409 = 3.559.356 → "₫3,56tr")
- đồng thời dùng luôn để vẽ biểu đồ xu hướng

`total` = tổng số kết quả khớp query → dùng phân trang, khỏi gọi `/product/count`.

### `/product/enrich` KHÔNG trả ảnh

```json
POST /product/enrich → {"id": "...", "videos": []}
```

Nó chỉ bổ sung **danh sách video gắn với sản phẩm**. Ảnh lấy từ CDN, xem mục dưới.

## Video — field trả về (đã xác minh 2026-09-14)

Bắt từ `POST /video/searchList` thật (VN, `title: "tai nghe"`, `video.filter.video_type: "WithProduct"`,
qua extension `extension/kalodata.js`): 10 dòng / `total` 620.

```
id, description, handle, creator_uid, follower_count, views, views_trend,
revenue, revenue_trend, sale, total, publish_date, duration, original_duration,
content_type, ai_video, collect_day, gpm, revenueDiff,
ad, ad_view_ratio, ad_revenue_ratio, ad_cpa, ad2Cost, ad2Roas, image
```

- Video **không có `title`** — chữ nằm ở `description`. Keyword vẫn gửi bằng khoá `title`.
- `views`, `follower_count`, `ad_cpa`, `ad2Cost` là **chuỗi đã rút gọn** (`"55,01k"`, `"₫56,44tr"`).
  Lượt xem số thô = `sum(views_trend)`; doanh thu thô = `sum(revenue_trend)` (có thể là số thực).
- `publish_date` dạng `"2026/01/26 01:02:24"`.
- `ad_view_ratio` (vd `">90%"`) = tỉ lệ lượt xem đến từ quảng cáo — phân biệt video đẩy tiền với video tự lan.
- Hậu tố tiền tiếng Việt là **`tỉ`** (`"₫1,02tỉ"`), không phải `tỷ`.

## Ảnh — public, không cần đăng nhập

Ảnh render bằng CSS `background-image` (không phải thẻ `<img>`), suy ra được thẳng từ id:

```
https://img.kalocdn.com/tiktok.product/{product_id}/cover.png
https://img.kalocdn.com/tiktok.video/{video_id}/cover.png
```

Đã kiểm bằng curl **không cookie** → HTTP 200, `image/png` (~66 KB ảnh SP, ~121 KB ảnh video).
Chỉ có đuôi `.png`; `.jpg` trả 404. Namespace `tiktok.creator` / `tiktok.shop` chưa đúng tên (404).

→ **Không tốn lượt gọi API nào để lấy ảnh**, cũng không tốn credit.

## Region hỗ trợ

`country` nhận các mã sau (rút từ bundle):

```
US, GB, ID, VN, TH, MY, PH, SG, MX, DE, FR, IT, ES, JP, BR
```

Một số tính năng chỉ mở cho 8 nước: `US, GB, ID, VN, TH, MY, PH, SG`.

Tiền tệ tương ứng: `USD $`, `IDR Rp`, `THB ฿`, `MYR RM`, `VND ₫`, `CNY ￥`...

## Endpoint hữu ích khác

| Endpoint | Công dụng |
|---|---|
| `GET /filterGroup/queryFilterConfiguration?type=video` | từ điển toàn bộ filter hợp lệ của trang |
| `GET /filterGroup/queryFilterTemplate?type=video` | preset filter dựng sẵn (High ROAS, Low-Follower...) |
| `GET /v1/tiktok/categories` | cây ngành hàng → lấy `cateIds` |
| `POST /video/detail/getVideoUrl` | link video gốc |
| `POST /product/detail/history` | lịch sử số liệu sản phẩm |
| `GET /api/credit/log/list` | credit đã tiêu |
| `POST /user/features` | quyền theo gói |

Giới hạn lịch sử: hằng số trong bundle là `365` và `180` ngày.

## Auth

Dùng cookie phiên đăng nhập. Cách lấy chính xác header tối thiểu:
DevTools → Network → chuột phải request → **Copy as cURL (bash)** → bỏ dần từng header
cho tới khi gãy.

## Rủi ro — đọc trước khi tự động hoá

1. **Tính credit.** Bundle liệt kê rõ các route bị trừ credit: `/video/queryList`,
   `/product/queryList`, `/shop/queryList`, `/creator/queryList`,
   `/shop/detail/product/queryList`, `/livestream/detail/product/queryList`,
   `/creator/detail/*/queryList`, `/homepage/hot/live/queryList`.
   Gọi bằng script đốt quota y hệt bấm tay, chỉ nhanh hơn.
2. **Vi phạm ToS.** Kalodata chỉ mở "full API access" ở gói Enterprise. Dùng cookie tài khoản
   để gọi endpoint nội bộ có thể bị khoá tài khoản.
3. **Cookie hết hạn** theo phiên → cần cơ chế refresh nếu chạy nền.
4. **Số liệu là ước lượng.** GMV/doanh số của Kalodata do AI ước lượng từ scrape, không phải
   số thật từ TikTok Shop (xem `docs/nghien-cuu-nguon-du-lieu.md` mục 5).
