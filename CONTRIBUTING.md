# Hướng dẫn làm việc trên Research SPY

Đọc [README.md](README.md) trước để nắm cấu trúc thư mục. File này nói về *cách thêm code
mới* sao cho không phá vỡ ranh giới giữa hai mục lớn.

---

## Nguyên tắc chung

1. **Đặc thù của một nguồn phải nằm gọn trong file của nguồn đó.** Nếu bạn thấy mình phải
   viết `if (platform === 'facebook')` ở ngoài `lib/ads/platforms/facebook.ts`, tức là hợp
   đồng đang thiếu một trường — hãy thêm trường đó vào `lib/ads/platform.ts` thay vì rẽ nhánh.

2. **Mục Quảng cáo và mục Từ khoá không import lẫn nhau**, kể cả kiểu dữ liệu. Thứ dùng chung
   thì đặt ở `lib/core/`.

3. **Comment giải thích *vì sao*, không kể lại code đang làm gì.** Đặc biệt: mọi con số đo
   được (giới hạn của endpoint, tỷ lệ kết quả đúng chủ đề, thời gian sống của chữ ký…) phải
   được ghi lại ngay tại chỗ dùng nó. Người sau sẽ không có cách nào đoán ra tại sao
   `MAX_PAGE_SIZE = 20` nếu bạn không viết ra.

4. **Không được để kết quả rỗng im lặng.** Đây là kiểu hỏng nguy hiểm nhất của công cụ này:
   một lưới trống đọc thành "sản phẩm không có nhu cầu". Nguồn nào trả về ít hơn hoặc khác
   với điều người dùng yêu cầu thì phải kèm `notice`, và lỗi thì phải hiện ra `status.ok = false`.

---

## Thêm một nguồn quảng cáo mới

Ví dụ thêm Shopee Ads.

### Bước 1 — tạo `lib/ads/platforms/shopee.ts`

Dùng `facebook.ts` (nguồn cần trình duyệt để lấy chữ ký) hoặc `tiktok.ts` (nguồn có bộ lọc
động) làm mẫu. Khung tối thiểu:

```ts
import type { AdPlatform, PlatformSearchInput, PlatformSearchOutcome } from '../platform'
import type { Ad } from '../types'

const PLATFORM_ID = 'shopee'

export type ShopeeOptions = { sortBy: 'newest' | 'popular' }

function parseOptions(raw: Record<string, string>): ShopeeOptions {
  return { sortBy: raw.sortBy === 'popular' ? 'popular' : 'newest' }
}

async function search(input: PlatformSearchInput<ShopeeOptions>): Promise<PlatformSearchOutcome> {
  // … gọi nguồn, ánh xạ về kiểu Ad …
  return { ads }
}

export const shopee: AdPlatform<ShopeeOptions> = {
  id: PLATFORM_ID,
  label: 'Shopee Ads',
  capabilities: { keywordSearch: true, startDate: false, remoteFilters: false },
  options: [
    {
      key: 'sortBy',
      label: 'Sắp xếp',
      kind: 'choice',
      defaultValue: 'newest',
      choices: [
        { value: 'newest', label: 'Mới nhất' },
        { value: 'popular', label: 'Phổ biến' },
      ],
    },
  ],
  parseOptions,
  search,
  media: { hostSuffixes: ['shopeecdn.com'], referer: 'https://shopee.vn/' },
  healthProbe: { keyword: 'kem', country: 'VN' },
}
```

### Bước 2 — đăng ký ở `lib/ads/platforms/index.ts`

```ts
import { shopee } from './shopee'

export const AD_PLATFORMS = {
  facebook,
  tiktok,
  shopee,        // ← chỉ một dòng này
} satisfies Record<string, AdPlatform<any>>
```

### Xong. Những thứ tự động hoạt động:

* chip chọn nguồn trên giao diện
* các ô điều khiển riêng của nguồn (dựng từ `options`)
* chấm trạng thái ở `/api/ads/health`
* proxy media cho CDN của nguồn (từ `media.hostSuffixes`)
* cache key, gộp kết quả, xếp hạng luân phiên giữa các nguồn
* kiểu `PlatformId` trong TypeScript

**Không phải sửa:** route, component, CSS, `.env`, `lib/core/*`.

### Vài điểm cần chú ý

* **Nếu nguồn cần chữ ký từ JS phía client**, đừng viết lại thuật toán ký — nó sẽ hỏng mỗi
  lần nền tảng đổi. Khai báo một `SessionRecipe` (xem `lib/core/browser.ts`) để mở một trang
  thật, nhặt vật liệu từ request đã ký, rồi phát lại. Cả Facebook và TikTok đều làm vậy.
* **`capabilities` phải khai báo trung thực.** Giao diện dựa vào nó để không hứa với người
  dùng những thứ nguồn không có. Nguồn không công bố ngày bắt đầu chạy thì `startDate: false`
  — phần chấm điểm sẽ tự hạ độ tin cậy thay vì bịa ra một con số.
* **Giới hạn tần suất là của riêng nguồn**, đọc từ biến môi trường ngay trong file nguồn
  (xem `MIN_INTERVAL_MS` trong `tiktok.ts`). Đừng thêm vào `lib/core/config.ts`.
* Thêm biến môi trường mới thì **nhớ ghi vào `.env.example`** — đó là tài liệu duy nhất về chúng.

---

## Thêm một nguồn từ khoá mới

Nhẹ hơn nhiều: nguồn chỉ phải nhận một cụm từ và trả về danh sách gợi ý. Phần mở rộng
long-tail, giữ nhịp gọi và xử lý lỗi từng phần đã có sẵn ở `providers/expand.ts`.

`lib/keywords/providers/lazada.ts`:

```ts
import { getJson } from '@/lib/core/http'
import type { KeywordProvider } from '../provider'

export const lazada: KeywordProvider = {
  id: 'lazada',
  label: 'Lazada',
  hasNativeScore: false,
  markets: ['VN', 'TH', 'PH'],   // bỏ trống nếu phục vụ mọi thị trường
  fetchSuggestions: async (term, country) => {
    const json = (await getJson(`https://…?q=${encodeURIComponent(term)}`)) as { items?: string[] }
    return (json.items ?? []).map((keyword) => ({ keyword }))
  },
}
```

Rồi thêm một dòng vào `lib/keywords/providers/index.ts`. Chip nguồn trên giao diện, cột "Có
mặt trên", cache và xếp hạng đều tự nhận nguồn mới.

---

## Trước khi commit

```bash
npm run typecheck      # bắt buộc
npm run build          # bắt buộc nếu có động vào app/ hoặc components/
npm run smoke:ads      # nếu có động vào lib/ads
npm run smoke:keywords # nếu có động vào lib/keywords
npm run smoke:ui       # nếu có động vào components/
```

Smoke test cần một dev server đang chạy (`npm run dev`) và gọi thật ra các nền tảng, nên hơi
chậm và có thể trượt vì nguồn đang giới hạn tần suất — đọc thông báo lỗi trước khi kết luận
là code sai.

---

## Quy ước commit

Một commit nên nằm gọn trong một mục. Tiền tố cho biết nó động vào đâu:

```
ads: thêm nguồn Shopee Ads
ads(tiktok): sửa lỗi phân trang khi ngành hàng rỗng
keywords: thêm nguồn gợi ý Lazada
keywords(rank): hạ điểm từ khoá dạng câu hỏi
core: tăng thời gian chờ làm nóng trình duyệt
ui: gộp thanh trạng thái nguồn vào page header
docs: cập nhật hướng dẫn thêm nguồn
```

Nhánh: `feat/<mô-tả-ngắn>`, `fix/<mô-tả-ngắn>`. Không commit thẳng vào `main`.

---

## Style code

Dự án chưa cấu hình ESLint/Prettier riêng, đang theo mặc định của Next.js. Quy ước đang dùng
xuyên suốt, hãy giữ cho nhất quán:

* không dấu chấm phẩy cuối câu lệnh
* nháy đơn cho chuỗi
* chiều rộng dòng ~110 ký tự
* dấu phẩy cuối trong danh sách nhiều dòng
* comment và chuỗi hiển thị cho người dùng viết bằng **tiếng Việt**; tên biến, hàm, kiểu
  viết bằng **tiếng Anh**
