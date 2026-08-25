'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { extensionAvailable } from '@/lib/ads/extension'
import { browserPost } from '@/lib/api'
import {
  chonGiaThapNhat,
  shopeePrices,
  TY_GIA_VND,
  type VnCodePrice,
  type VnTerm,
} from '@/lib/imagesearch/vnprice'
import type {
  ImageMatch,
  ImageSearchResult,
  PlatformCount,
  ProductCode,
} from '@/lib/imagesearch/types'

/**
 * Màn hình MỤC TÌM BẰNG ẢNH.
 *
 * BA CÁCH ĐƯA ẢNH VÀO, và cả ba đều cần thiết: bấm chọn tệp, kéo-thả, và DÁN. Cách dán quan
 * trọng hơn vẻ ngoài của nó — người bán hàng thường đang xem ảnh sản phẩm ở một tab khác rồi
 * chuột phải "Sao chép hình ảnh", nên bắt được `paste` là bỏ hẳn một vòng lưu-tệp-rồi-chọn-tệp.
 *
 * Lượt tìm CHƯA có trong cache mất khoảng hai lăm giây vì phải mở trình duyệt thật. Vì vậy ô
 * chờ nói rõ con số đó thay vì chỉ quay vòng — một cái vòng quay im lặng trong hai lăm giây
 * đọc thành "treo rồi".
 */

const ACCEPT = 'image/jpeg,image/png,image/webp'
const MAX_MB = 8

/**
 * Các nguồn chọn được.
 *
 * `hint` KHÔNG còn hiện dưới tên sàn — nó chỉ sống trong tooltip. Ba dòng chú thích nằm thường
 * trực làm hàng nút nặng gấp đôi cho một thông tin người ta chỉ cần đúng lần đầu; nhưng bỏ
 * hẳn thì mất luôn cảnh báo "Lens có hạn mức", nên nó lùi vào chỗ rê chuột mới thấy.
 *
 * Chỉ 1688 bật sẵn: nó là nguồn duy nhất không mở trình duyệt và không có hạn mức. Bật sẵn
 * một nguồn có hạn mức là cách chắc chắn để tiêu hết hạn mức vào những lượt không ai cần.
 * Danh sách và mặc định phải khớp `SOURCES` / `DEFAULT_SOURCES` ở `lib/imagesearch/search.py`.
 */
const SOURCES = [
  { id: '1688', label: '1688', hint: 'Giá sỉ tại xưởng, tính bằng ¥ · khoảng 3 giây' },
  { id: 'alibaba', label: 'Alibaba.com', hint: 'Bán buôn xuất khẩu, giá ₫ kèm số lượng đặt tối thiểu · khoảng 4 giây' },
  { id: 'aliexpress', label: 'AliExpress', hint: 'Bán lẻ quốc tế ship về VN, giá ₫ · khoảng 5 giây · có lúc bị tạm chặn' },
  { id: 'taobao', label: 'Taobao', hint: 'Bán lẻ Trung Quốc · khoảng 30 giây · cần đăng nhập' },
  { id: 'lens', label: 'Google Lens', hint: 'Nơi bán ở VN · khoảng 20 giây · hạn mức ~15 lượt/ngày' },
]

const DEFAULT_SOURCES = ['1688']

/** Nhớ lựa chọn giữa các lần dùng — người vận hành hiếm khi đổi nguồn giữa chừng. */
const STORAGE_KEY = 'imagesearch-sources'

/** Nơi mang cụm tiếng Trung sang. Đây là thứ Lens không cho, nên nó đáng có nút riêng. */
/**
 * Nơi tra NGƯỢC một mã model về thị trường Việt Nam.
 *
 * Đây là câu trả lời cho "tìm ra hàng Trung rồi, vậy ở Việt Nam ai đang bán và giá bao
 * nhiêu". Mã model là đường tra chính xác hơn tên món rất nhiều: "máy sấy tóc" ra hàng nghìn
 * thứ, "BHD321" ra đúng một món.
 *
 * Link Shopee kèm sẵn `sortBy=price&order=asc` — mở ra là GIÁ THẤP NHẤT nằm ngay dòng đầu,
 * không phải cuộn đi tìm.
 *
 * Là LINK MỞ TAB chứ không phải bảng giá tại chỗ, và đó là giới hạn có thật chứ không phải
 * làm tắt: Shopee trả 403 cho mọi lượt gọi từ server (đo 2026-07-28), gắn cookie đăng nhập
 * vào thì rơi tiếp vào `captcha?scene=crawler_item` — Shopee tự dán nhãn "crawler". Lấy giá
 * tự động cần extension chạy trong trình duyệt đã đăng nhập của người dùng, đúng cách mục
 * Quảng cáo đang làm.
 */
const VN_MARKETS = [
  {
    id: 'shopee',
    label: 'Shopee',
    url: (term: string) =>
      `https://shopee.vn/search?keyword=${encodeURIComponent(term)}&sortBy=price&order=asc`,
  },
  {
    id: 'tiktok',
    label: 'TikTok Shop',
    url: (term: string) => `https://www.tiktok.com/search/shop?q=${encodeURIComponent(term)}`,
  },
]

const CN_MARKETS = [
  { id: 'taobao', label: 'Taobao', url: (t: string) => `https://s.taobao.com/search?q=${encodeURIComponent(t)}` },
  { id: '1688', label: '1688', url: (t: string) => `https://s.1688.com/selloffer/offer_search.htm?keywords=${encodeURIComponent(t)}` },
]

/**
 * CÁCH SẮP XẾP một bảng kết quả.
 *
 * SẮP Ở ĐÂY, KHÔNG GỌI LẠI SERVER — cùng lập luận đã viết cho dãy chip lọc sàn ở
 * `MarketSection`: một lượt tìm đã kéo về cả bảng và đã tiêu suất hạn mức rồi, nên đổi cách
 * sắp chỉ là đọc lại mảng đang có. Không chờ, không tốn thêm suất nào.
 *
 * So giá được LÀ VÌ mỗi bảng chỉ có MỘT loại tiền: 1688 với Taobao toàn ¥, Alibaba.com với
 * AliExpress toàn ₫. Cố ý không có nút nào sắp chung hai bảng — ¥29 và 989.000₫ không có
 * thứ tự, và một nút hứa hẹn điều đó là một nút nói dối.
 */
const SORTS = [
  { id: 'default', label: 'Mặc định', key: null },
  { id: 'price-asc', label: 'Giá thấp', key: 'priceValue', dir: 1 },
  { id: 'price-desc', label: 'Giá cao', key: 'priceValue', dir: -1 },
  { id: 'sold-desc', label: 'Bán chạy', key: 'sold', dir: -1 },
] as const

type SortId = (typeof SORTS)[number]['id']

function sortRows(items: ImageMatch[], id: SortId): ImageMatch[] {
  const spec = SORTS.find((s) => s.id === id)
  if (!spec || !spec.key) return items

  const { key, dir } = spec as { key: 'priceValue' | 'sold'; dir: number }
  // CHÉP RỒI MỚI SẮP. `Array.sort` sắp tại chỗ, mà `items` chính là mảng trong kết quả — sắp
  // thẳng lên nó là mất luôn thứ tự gốc, và "Mặc định" không còn đường quay về.
  return [...items].sort((a, b) => {
    const x = a[key]
    const y = b[key]
    // THIẾU SỐ THÌ XUỐNG CUỐI Ở MỌI CHIỀU, không coi như 0. Một dòng không công bố giá không
    // phải là dòng rẻ nhất — đó là dòng chưa biết. Đẩy nó lên đầu bảng "Giá thấp" là bịa ra
    // một câu trả lời. Và xuống cuối chứ không biến mất: giấu đi thì người dùng đếm thiếu.
    if (typeof x !== 'number') return typeof y !== 'number' ? 0 : 1
    if (typeof y !== 'number') return -1
    return (x - y) * dir
  })
}

/**
 * ĐƠN VỊ TIỀN của một dòng, đọc từ chính chuỗi giá: bỏ hết chữ số, dấu phân cách và dấu nối
 * khoảng, còn lại là ký hiệu ("¥", "₫", "us$"). `ImageMatch` không có trường `currency` — ba
 * trong năm nguồn chỉ trả về chuỗi đã định dạng sẵn — nên ký hiệu là thứ duy nhất có thật.
 */
function priceUnit(price: string | undefined): string {
  return (price ?? '').replace(/[\d.,\s\-–~/]/g, '').trim().toLowerCase()
}

/**
 * CHỈ HIỆN NHỮNG NÚT BẢNG NÀY LÀM ĐƯỢC.
 *
 * Google Lens không trả lượt bán, nên bảng "Nơi đang bán" không có gì để sắp theo "Bán chạy";
 * Taobao chỉ cho lượt bán dưới dạng chữ ("300+人付款") nên `sold` cũng vắng. Một cái nút bấm
 * vào mà bảng không nhúc nhích đọc thành "hỏng", nên nút nào không có dữ liệu thì không hiện.
 *
 * NÚT GIÁ CÒN TẮT KHI BẢNG TRỘN HAI LOẠI TIỀN. Bốn bảng nguồn Trung Quốc mỗi bảng một loại
 * tiền nên không bao giờ vướng; riêng "Nơi đang bán" là do Google Lens gom về từ mọi tên
 * miền, nên "989.000 đ" đứng cạnh "US $12.50" là chuyện có thể xảy ra. Sắp chung hai thứ đó
 * cho ra một danh sách TRÔNG có thứ tự mà thật ra vô nghĩa — sai kiểu tệ nhất, vì nó không
 * trông giống lỗi. Lọc về một sàn thì đơn vị đồng nhất trở lại và nút giá hiện lại.
 */
function usableSorts(items: ImageMatch[]) {
  const units = new Set(
    items.filter((item) => typeof item.priceValue === 'number').map((item) => priceUnit(item.price)),
  )
  const hasPrice = units.size === 1
  const hasSold = items.some((item) => typeof item.sold === 'number')
  return SORTS.filter((sort) =>
    sort.key === 'priceValue' ? hasPrice : sort.key === 'sold' ? hasSold : true,
  )
}

function SortBar({
  items,
  value,
  onChange,
}: {
  items: ImageMatch[]
  value: SortId
  onChange: (id: SortId) => void
}) {
  const options = usableSorts(items)
  // Còn mỗi "Mặc định" thì đây không còn là một lựa chọn nữa — ẩn hẳn thay vì bày một nút chết.
  if (options.length < 2) return null
  return (
    <div className="img-mode img-sort">
      {options.map((option) => (
        <button key={option.id} data-on={value === option.id} onClick={() => onChange(option.id)}>
          {option.label}
        </button>
      ))}
    </div>
  )
}

/**
 * GIÁ BÁN Ở VIỆT NAM, TRA THEO TỪNG MÃ.
 *
 * Bản trước hiện BỘI SỐ so với một mốc giá duy nhất, và nó sai theo hai tầng. Tầng ngoài:
 * một bảng 1688 lấy về bằng ảnh chứa nhiều model khác nhau (G304 lẫn G102), mà hai model ấy
 * có hai mức giá khác hẳn ở Việt Nam — một mốc chung là gán giá model này cho model kia.
 * Tầng trong, tệ hơn: chính cái mốc ấy cũng có thể neo nhầm vào một món rẻ tiền lọt lưới,
 * và khi đó CẢ CỘT sai cùng lúc — đúng cảnh "×0,5" hiện trên mọi dòng G304.
 *
 * Nên giờ mỗi mã hỏi Shopee một lượt riêng, và mỗi dòng chỉ hiện giá CỦA MÃ NÓ MANG. Không
 * còn phép nhân chia nào, không còn tỷ giá: một con số Shopee đang niêm yết, kèm đường dẫn
 * để bấm vào kiểm.
 *
 * Mã không có mặt ở sàn Việt Nam thì cột để TRỐNG. Đó là trường hợp thường gặp nhất với hàng
 * 1688 — mã xưởng thì người bán Việt không ai dùng — và im lặng mới là câu trả lời đúng.
 */
type VnPriceMap = Record<string, VnCodePrice>

/**
 * GIÁ SỈ TRUNG QUỐC của một mã, quy ra đồng — cái sàn để nhận ra phụ kiện đội lốt hàng thật.
 *
 * Lấy dòng RẺ NHẤT mang mã ấy trong bốn bảng nguồn, bỏ qua những dòng chính bảng nguồn đã
 * chấm là phụ kiện (`isAccessory`, luật 适用/适配 ở `codes.py`). Rẻ nhất chứ không phải trung
 * bình, vì đây là cái sàn: nó chỉ cần thấp đến mức KHÔNG thể loại bỏ nhầm hàng thật.
 *
 * `null` khi không có dòng nào mang mã, hoặc bảng trộn nhiều loại tiền không đọc nổi ký hiệu.
 * Lúc ấy luật giá tự tắt — thà không có sàn còn hơn có một cái sàn bịa ra.
 */
function sanGiaSi(found: ImageSearchResult, code: string): number | null {
  const bang = [
    ...(found.sourcing ?? []),
    ...(found.globalSourcing ?? []),
    ...(found.chinaRetail ?? []),
    ...(found.globalRetail ?? []),
  ]
  let thap: number | null = null
  for (const row of bang) {
    if (row.isAccessory) continue
    if (!(row.titleCodes ?? []).includes(code)) continue
    if (typeof row.priceValue !== 'number') continue
    const ty = TY_GIA_VND[priceUnit(row.price)]
    if (!ty) continue
    const vnd = row.priceValue * ty
    if (thap === null || vnd < thap) thap = vnd
  }
  return thap
}

/** Giá Việt Nam của dòng này: tìm mã đầu tiên trong tiêu đề mà bảng tra có số. */
function vnPriceFor(row: ImageMatch, prices: VnPriceMap): VnCodePrice | null {
  for (const code of row.titleCodes ?? []) {
    const found = prices[code]
    if (found && found.price !== null) return found
  }
  return null
}

/**
 * Một bảng kết quả. Ba nguồn dùng chung đúng một cách bày vì chúng cùng hình dạng dữ liệu —
 * cái khác nhau chỉ là trường nào có mặt: 1688 có `sold`, Taobao có `note` ("300+人付款"),
 * Lens có `rating` và `inStock`. Nên hàng tự bày theo thứ nó cầm, không cần ba bản sao.
 */
function Rows({ items, vnPrices }: { items: ImageMatch[]; vnPrices?: VnPriceMap | null }) {
  return (
      <div className="img-list" data-margin={!!vnPrices}>
        {items.map((item) => (
          <a
            className="img-row"
            key={item.link}
            href={item.link}
            target="_blank"
            rel="noreferrer"
            data-market={item.marketplace}
          >
            {item.thumbnail ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img className="img-thumb" src={item.thumbnail} alt="" loading="lazy" />
            ) : (
              <span className="img-thumb" />
            )}
            <span className="img-info">
              <b>{item.title}</b>
              <small>
                {[item.supplier ?? item.source, item.location].filter(Boolean).join('  ·  ')}
              </small>
            </span>
            <span className="img-meta">
              {item.price && <span className="img-price">{item.price}</span>}
              {/* MOQ đứng ngay sau giá vì hai con số ấy chỉ có nghĩa khi đọc cùng nhau:
                  ₫509.000 với "đặt tối thiểu 10 cái" là một mặt hàng khác hẳn ₫509.000 với
                  "đặt tối thiểu 1 cái". */}
              {item.moq && <span className="img-moq">{item.moq}</span>}
              {typeof item.rating === 'number' && (
                <span className="img-rating">
                  {item.rating}★{item.reviews ? ` (${item.reviews})` : ''}
                </span>
              )}
              {typeof item.sold === 'number' && (
                <span className="img-rating">đã bán {item.sold.toLocaleString('vi-VN')}</span>
              )}
              {item.note && <span className="img-rating">{item.note}</span>}
              {item.inStock && <span className="img-stock">Còn hàng</span>}
            </span>
            {vnPrices && <VnCell row={item} prices={vnPrices} />}
          </a>
        ))}
      </div>
  )
}

/**
 * Câu hiện khi rê chuột lên một mã. Nó nói ra CHỖ ĐÃ THẤY mã, vì chính chỗ ấy quyết định mã
 * có tra ngược được hay không: đo ngày 2026-08-19, mã hãng (`G304`) tra `site:shopee.vn` ra
 * 8 trang sản phẩm, còn mã lấy từ tiêu đề 1688 (`T15S`, `N612`) ra số không — người bán Việt
 * Nam không dịch tiêu đề 1688, họ viết tiêu đề mới và tự đặt mã riêng.
 */
function codeHint(code: ProductCode): string {
  if (code.fromImage) return 'Đọc được ngay trên tấm ảnh — đáng tin nhất.'
  const where = code.sources.join(', ')
  if (code.sources.includes('Nơi đang bán')) {
    return `${code.count} dòng có nhắc mã này (${where}). Thị trường Việt Nam đang gọi món này bằng mã ấy, nên gõ vào Shopee sẽ ra hàng.`
  }
  return `${code.count} dòng có nhắc mã này (${where}). Chưa thấy ở bảng bán tại Việt Nam, nên có thể là mã xưởng — tra ngược thường không ra gì.`
}

/**
 * Ô cột phải: giá đang bán ở Việt Nam của đúng model dòng này.
 *
 * BA TRẠNG THÁI, và trạng thái thứ ba — TRỐNG — là trạng thái hay gặp nhất, nên nó phải là
 * mặc định chứ không phải ngoại lệ:
 *
 *   phụ kiện   nhãn nổi. Miếng dán "dùng cho chuột G304" mang mã G304 trong tiêu đề nhưng
 *              nó không phải con chuột; dán giá con chuột lên đó là câu trả lời sai.
 *   có giá     số Shopee đang niêm yết cho đúng mã ấy, bấm vào mở thẳng trang tìm.
 *   trống      mã của dòng này không có ở sàn Việt Nam, hoặc dòng không có mã nào. Với hàng
 *              1688 đây là chuyện thường: mã xưởng thì người bán Việt không ai dùng. Im lặng
 *              là câu trả lời đúng — bịa ra một con số mới là hỏng.
 */
function VnCell({ row, prices }: { row: ImageMatch; prices: VnPriceMap }) {
  if (row.isAccessory) {
    return (
      <span
        className="img-vn"
        data-kind="accessory"
        title="Tiêu đề ghi “dùng cho…” — đây là phụ kiện cho món khác, không phải chính món đang tra."
      >
        phụ kiện
      </span>
    )
  }

  const found = vnPriceFor(row, prices)
  if (!found || found.price === null) return <span className="img-vn" data-kind="none" />

  // SPAN CHỨ KHÔNG PHẢI THẺ <a>: cả dòng `.img-row` vốn đã là một thẻ `<a>` trỏ sang 1688,
  // và `<a>` lồng trong `<a>` là HTML sai — trình duyệt tự gỡ lồng, ra một cây DOM không ai
  // đoán được. Chặn nổi bọt rồi tự mở tab thì vẫn bấm được mà cấu trúc vẫn đúng.
  return (
    <span
      className="img-vn"
      data-kind="price"
      role="link"
      tabIndex={0}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        window.open(found.url, '_blank', 'noopener')
      }}
      title={vnTooltip(found)}
    >
      <b>{found.price.toLocaleString('vi-VN')} ₫</b>
      <small>
        Shopee · {found.code}
        {found.skipped > 0 ? ` · bỏ ${found.skipped}` : ''}
      </small>
    </span>
  )
}

/**
 * Câu giải thích đầy đủ cho một ô giá, kể cả phần đã bị bỏ.
 *
 * PHẢI NÓI RA SỐ DÒNG ĐÃ BỎ. Người dùng bấm vào ô này là mở thẳng Shopee sắp theo giá tăng
 * dần, và dòng đầu tiên họ thấy ở đó chính là dòng công cụ vừa gạch đi. Hai con số lệch nhau
 * mà không giải thích thì đọc thành lỗi — trong khi lệch mới là đúng.
 */
function vnTooltip(found: VnCodePrice): string {
  const dong = [
    `Shopee: rẻ nhất ${found.price?.toLocaleString('vi-VN')} ₫ trong ${found.hits} sản phẩm mang mã ${found.code}.`,
  ]
  if (found.skipped > 0) {
    dong.push('', `Đã bỏ ${found.skipped} dòng không phải món này:`)
    for (const row of found.skippedRows) {
      const gia = row.price !== null ? `${row.price.toLocaleString('vi-VN')} ₫` : '—'
      const vi = row.why === 'phu-kien' ? 'tiêu đề là phụ kiện' : 'rẻ hơn cả giá sỉ Trung Quốc'
      dong.push(`  · ${gia} — ${row.title.slice(0, 60)} (${vi})`)
    }
    if (found.floorVnd !== null) {
      dong.push('', `Sàn giá dùng để lọc: ${Math.round(found.floorVnd).toLocaleString('vi-VN')} ₫ (giá sỉ 1688 quy đổi).`)
    }
  }
  dong.push('', 'Bấm để mở danh sách trên Shopee.')
  return dong.join('\n')
}

/**
 * Câu chú giải cho cột phải, đặt ngay trên bảng.
 *
 * Nó tồn tại vì trạng thái hay gặp nhất của cột ấy là TRỐNG: bảng 1688 đầy mã xưởng, mà mã
 * xưởng thì sàn Việt Nam không ai dùng. Một cột trống không lời giải đọc thành "công cụ
 * hỏng"; nói thẳng "N612 · không có ở sàn Việt" thì nó thành một phát hiện — món này chưa ai
 * bán ở Việt Nam dưới mã đó.
 */
function VnLegend({ items, prices }: { items: ImageMatch[]; prices: VnPriceMap }) {
  const seen = new Set<string>()
  for (const item of items) for (const code of item.titleCodes ?? []) seen.add(code)

  const known = Object.values(prices).filter((entry) => seen.has(entry.code))
  if (!known.length) return null

  const co = known.filter((entry) => entry.price !== null)
  const khong = known.filter((entry) => entry.price === null)

  return (
    <span className="img-ref">
      Giá ở VN
      {co.map((entry) => (
        <b key={entry.code}>
          {entry.code} {entry.price!.toLocaleString('vi-VN')} ₫
        </b>
      ))}
      {!!khong.length && (
        <small title="Hỏi Shopee rồi, không sản phẩm nào mang mã này — nhiều khả năng là mã xưởng, người bán Việt Nam tự đặt mã riêng.">
          {khong.map((entry) => entry.code).join(', ')} · không có ở sàn Việt
        </small>
      )}
    </span>
  )
}

function Section({
  title,
  items,
  vnPrices,
}: {
  title: string
  items: ImageMatch[]
  vnPrices?: VnPriceMap | null
}) {
  const [sort, setSort] = useState<SortId>('default')
  if (!items.length) return null
  return (
    <div className="panel">
      <h3 className="img-head">
        {title} <span className="img-count">{items.length}</span>
        {/* Nói CỘT PHẢI LÀ GÌ, và nói ra cả những mã KHÔNG có ở Việt Nam. Cột trống chiếm
            phần lớn bảng khi hàng là mã xưởng, và một cột trống không lời giải thích đọc
            thành "công cụ hỏng" chứ không thành "sàn Việt Nam không có món này". */}
        {vnPrices && <VnLegend items={items} prices={vnPrices} />}
        <SortBar items={items} value={sort} onChange={setSort} />
      </h3>
      <Rows items={sortRows(items, sort)} vnPrices={vnPrices} />
    </div>
  )
}

/**
 * Bảng "Nơi đang bán", kèm dãy chip lọc theo sàn.
 *
 * LỌC Ở ĐÂY, KHÔNG GỌI LẠI SERVER. Google Lens không nhận tham số sàn, nên một lượt tìm đã
 * mang về đủ mọi tên miền và suất hạn mức đã bị tiêu ngay lúc gửi ảnh đi. Vì vậy bấm đổi chip
 * là lọc trên mảng đã có: không chờ, không tốn thêm suất nào. Đó cũng là lý do "Shopee" KHÔNG
 * nằm trong hàng chọn nguồn phía trên — bật nó ở đấy sẽ ngụ ý là chọn nguồn tốn thêm tiền,
 * trong khi nó không hề tốn.
 *
 * CHIP BẰNG KHÔNG VẪN HIỆN VÀ VẪN BẤM ĐƯỢC. "TikTok 0" là một câu trả lời có thật; giấu chip
 * đi thì người dùng đọc thành "công cụ này không tra TikTok". Bấm vào nó ra một câu nói rõ
 * ràng chứ không phải một bảng trống câm — bảng trống là thứ người ta đọc thành "hỏng rồi".
 */
function MarketSection({
  title,
  items,
  platforms,
}: {
  title: string
  items: ImageMatch[]
  platforms: PlatformCount[]
}) {
  const [active, setActive] = useState('all')
  const [sort, setSort] = useState<SortId>('default')
  if (!items.length) return null

  const shown = active === 'all' ? items : items.filter((item) => item.platform === active)
  const activeLabel = platforms.find((p) => p.id === active)?.label ?? ''

  return (
    <div className="panel">
      <h3 className="img-head">
        {title} <span className="img-count">{items.length}</span>
        {/* Đọc theo `shown`, tức là SAU khi lọc sàn — nên dãy nút tự đổi theo sàn đang chọn.
            Ở "Tất cả", nếu Lens gom về nhiều loại tiền thì `usableSorts` giấu hai nút giá đi;
            bấm vào một sàn là đơn vị đồng nhất trở lại và chúng hiện ra. */}
        <SortBar items={shown} value={sort} onChange={setSort} />
      </h3>

      <div className="chips img-platforms">
        <button type="button" className="chip" data-on={active === 'all'} onClick={() => setActive('all')}>
          Tất cả <b>{items.length}</b>
        </button>
        {platforms.map((platform) => (
          <button
            type="button"
            key={platform.id}
            className="chip"
            data-on={active === platform.id}
            onClick={() => setActive(platform.id)}
          >
            {platform.label} <b>{platform.count}</b>
          </button>
        ))}
      </div>

      {shown.length ? (
        <Rows items={sortRows(shown, sort)} />
      ) : (
        <p className="img-none">Ảnh này không tìm thấy kết quả nào trên {activeLabel}.</p>
      )}
    </div>
  )
}

export default function ImageSearchWorkspace() {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)

  // ẢNH ĐƯỢC GIỮ LẠI, không tìm ngay khi nhận. Bản trước thả ảnh là chạy luôn, nên đổi sàn
  // xong phải thả lại ảnh — và mỗi lần thả nhầm lúc đang bật Lens là một suất hạn mức bay đi
  // mà không ai xin.
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [result, setResult] = useState<ImageSearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  const [chosen, setChosen] = useState<string[]>(DEFAULT_SOURCES)

  /**
   * MỘT SÀN là mặc định, NHIỀU SÀN phải tự bật.
   *
   * Không phải để giới hạn người dùng mà vì cái giá cộng dồn: mỗi sàn thêm vào là thêm một cửa
   * sổ Chrome và, với Lens, thêm một suất hạn mức. Người cần so ba nơi cùng lúc thì bật một
   * lần rồi thôi; người chỉ tra nguồn hàng thì không bao giờ phải nghĩ tới nó.
   */
  const [multi, setMulti] = useState(false)

  /*
   * GIÁ VIỆT NAM THEO TỪNG MÃ sống ở đây chứ không ở trong bảng tra giá, vì bốn bảng nguồn
   * nằm TRÊN bảng ấy lại là nơi cần nó. Bấm "Tra giá" một lượt là cột phải của cả bốn bảng
   * có số, mỗi dòng hiện giá của đúng mã nó mang.
   *
   * Rỗng là trạng thái mặc định và cũng là trạng thái sau mỗi lượt tìm ảnh mới: giá cũ thuộc
   * về tấm ảnh cũ, để lại thì cột phải nói về một sản phẩm khác.
   */
  const [vnPrices, setVnPrices] = useState<Record<string, VnCodePrice>>({})

  /*
   * `''` khi chưa chạy · `'hoi'` đang hỏi · `'xong'` · `'thieu-ext'` khi không có extension.
   *
   * Cần một trạng thái riêng chứ không suy từ `vnPrices` rỗng, vì rỗng có hai nghĩa hoàn toàn
   * khác nhau: "chưa hỏi" và "hỏi rồi, không mã nào có ở sàn Việt". Con thứ hai là một phát
   * hiện; con thứ nhất chỉ là chưa xong.
   */
  const [vnStatus, setVnStatus] = useState('')

  /*
   * ĐỌC KHI ĐÃ GẮN VÀO TRANG, không đọc trong hàm khởi tạo state. Trang này được dựng sẵn ở
   * phía máy chủ, nơi không có `localStorage`, nên máy chủ luôn vẽ ra mặc định. Nếu client
   * khởi tạo bằng một giá trị KHÁC thì hai bên lệch nhau, và React không vá lại thuộc tính
   * `data-on` khi hydrate: state đúng là "lens" mà chip sáng vẫn là 1688. Đã đo đúng triệu
   * chứng đó — kho lưu ghi `["lens"]` nhưng màn hình sáng 1688.
   *
   * Cái giá là một nhịp nháy rất ngắn ở lần vẽ đầu. Đổi lại là hành vi đúng.
   */
  const loaded = useRef(false)

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null')
      // Lọc theo danh sách hiện tại: một lựa chọn đã lưu có thể mang tên sàn đã bị gỡ.
      const valid = Array.isArray(saved)
        ? saved.filter((id: string) => SOURCES.some((s) => s.id === id))
        : []
      if (valid.length) {
        setChosen(valid)
        // Lưu nhiều hơn một sàn thì chắc chắn lần trước đang ở chế độ nhiều sàn.
        setMulti(valid.length > 1)
      }
    } catch {
      // Kho hỏng hoặc bị chặn: dùng mặc định, không làm hỏng lượt dùng.
    }
    loaded.current = true
  }, [])

  // GHI Ở ĐÂY, KHÔNG ghi trong hàm cập nhật state. Bản đầu gọi `localStorage.setItem` ngay
  // trong `setChosen(current => …)`; hàm cập nhật phải THUẦN TUÝ vì React gọi nó nhiều lần cho
  // một lần bấm (chế độ dev cố ý gọi hai lần để bắt đúng lỗi này).
  //
  // `loaded` chặn lượt ghi đầu tiên: không có nó thì effect này chạy ngay lúc gắn với giá trị
  // mặc định và ĐÈ MẤT lựa chọn đã lưu, trước khi effect đọc ở trên kịp áp dụng.
  useEffect(() => {
    if (!loaded.current) return
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(chosen))
    } catch {
      // Chế độ riêng tư chặn localStorage. Mất phần ghi nhớ, không mất tính năng.
    }
  }, [chosen])

  const pickSource = useCallback(
    (id: string) => {
      setChosen((current) => {
        // Một sàn: chọn cái mới là BỎ SÁNG cái cũ, không phải cộng thêm.
        if (!multi) return [id]
        // Nhiều sàn: bật/tắt từng cái, nhưng KHÔNG cho tắt hết — một lượt tìm không sàn nào
        // chỉ trả về phần đọc ảnh, và người dùng sẽ đọc đó là "công cụ hỏng".
        const next = current.includes(id)
          ? current.filter((item) => item !== id)
          : [...current, id]
        return next.length ? next : current
      })
    },
    [multi],
  )

  const switchMode = useCallback((toMulti: boolean) => {
    setMulti(toMulti)
    // Về lại một sàn thì giữ cái đầu tiên. Bỏ hết rồi bắt chọn lại là phạt người dùng vì đã
    // thử một chế độ.
    if (!toMulti) setChosen((current) => current.slice(0, 1))
  }, [])

  /** Nhận ảnh và GIỮ LẠI. Không tự tìm — xem ghi chú ở `file`. */
  const pickFile = useCallback((incoming: File) => {
    if (incoming.size > MAX_MB * 1024 * 1024) {
      setError(`Ảnh nặng ${(incoming.size / 1024 / 1024).toFixed(1)}MB, quá mức ${MAX_MB}MB`)
      return
    }
    setFile(incoming)
    setPreview(URL.createObjectURL(incoming))
    setResult(null)
    setError(null)
    setVnPrices({})
    setVnStatus('')
  }, [])

  /*
   * HỎI GIÁ VIỆT NAM cho từng mã, ngay sau khi đọc ảnh xong.
   *
   * GỌI TỪ `run()` CHỨ KHÔNG PHẢI TỪ `useEffect`, và đó là điểm đã đo chứ không phải sở
   * thích: bản đầu đặt trong effect phụ thuộc `result`, chốt lại bằng một `useRef`. Đo ra
   * BỐN lượt gọi cho một lượt tìm — StrictMode của React dựng lại component, mà dựng lại thì
   * `useRef` mất giá trị nên cái chốt không chốt được gì. Việc này vốn là một hành động do
   * người dùng khởi ra, không phải một hiệu ứng của lần vẽ, nên chỗ đúng của nó là ở đây.
   *
   * CHỈ HỎI CÁC MÃ, bỏ cụm chữ trần: cột phải tra theo mã của từng dòng, nên một lượt hỏi
   * bằng cụm chữ không điền được ô nào mà vẫn tốn một lần mở tab.
   *
   * TUẦN TỰ, tối đa ba mã: mỗi mã là một lần mở tab Shopee trong trình duyệt của người dùng,
   * và ba tab bật cùng lúc là Shopee bắt đầu nghi bot (`captcha?scene=crawler_item`, đo
   * 2026-07-28).
   */
  const hoiGiaVn = useCallback(async (found: ImageSearchResult) => {
    const ten = found.identity?.product ?? ''
    const ma = (found.codes ?? []).slice(0, 3).map((entry) => entry.code)
    if (!ma.length) return

    setVnStatus('hoi')
    if (!(await extensionAvailable())) {
      setVnStatus('thieu-ext')
      return
    }

    const gia: Record<string, VnCodePrice> = {}
    for (const code of ma) {
      const term: VnTerm = { query: `${ten} ${code}`.trim(), code }
      try {
        const one = await shopeePrices(term)
        const hits = one.rows.filter((row) => row.codeHit)
        // Sàn giá: rẻ hơn cả giá sỉ tại xưởng Trung Quốc thì không phải cùng một món.
        const san = sanGiaSi(found, code)
        const { price: low, rows: daCham, skipped } = chonGiaThapNhat(one.rows, san)
        // GHI CẢ KHI KHÔNG CÓ GIÁ (`price: null`) — nhờ vậy chú giải phân biệt được "hỏi rồi,
        // sàn Việt không có" với "chưa hỏi tới". Hai câu ấy khác hẳn nhau.
        gia[code] = {
          code,
          price: low,
          hits: hits.length,
          skipped,
          // Chỉ giữ vài dòng đầu: đây là tooltip, không phải bảng. Đủ để kiểm luật đoán đúng
          // hay sai, mà không biến một ô nhỏ thành bức tường chữ.
          skippedRows: daCham
            .filter((row) => row.vnSkip)
            .slice(0, 4)
            .map((row) => ({ title: row.title || '', price: row.priceValue ?? null, why: row.vnSkip ?? null })),
          floorVnd: san,
          url: `https://shopee.vn/search?keyword=${encodeURIComponent(term.query)}&sortBy=price&order=asc`,
        }
      } catch {
        // Một mã hỏng không được kéo theo hai mã còn lại. Bỏ qua, đi tiếp.
      }
      setVnPrices({ ...gia })
    }
    setVnStatus('xong')
  }, [])

  const run = useCallback(async () => {
    if (!file) return
    setResult(null)
    setError(null)
    setVnPrices({})
    setVnStatus('')
    setLoading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('geo', 'VN')
      form.append('sources', chosen.join(','))
      const found = await browserPost<ImageSearchResult>('/api/imagesearch', form)
      setResult(found)
      // Bảng nguồn hiện ra ngay; cột giá điền dần vào sau, nên không ai phải chờ nó.
      void hoiGiaVn(found)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [file, chosen, hoiGiaVn])

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      setDragging(false)
      const dropped = event.dataTransfer.files?.[0]
      if (dropped) pickFile(dropped)
    },
    [pickFile],
  )

  const onPaste = useCallback(
    (event: React.ClipboardEvent) => {
      const pasted = Array.from(event.clipboardData.items)
        .find((item) => item.type.startsWith('image/'))
        ?.getAsFile()
      if (pasted) pickFile(pasted)
    },
    [pickFile],
  )

  const identity = result?.identity
  const matches = result?.matches ?? []
  const platforms = result?.platforms ?? []
  const sourcing = result?.sourcing ?? []
  const globalSourcing = result?.globalSourcing ?? []
  const chinaRetail = result?.chinaRetail ?? []
  const globalRetail = result?.globalRetail ?? []
  const zhTerms = identity?.terms?.zh ?? []
  const codes = result?.codes ?? []


  // Từ gốc mang sang tab Từ khoá: cụm vi ĐẦU TIÊN, và lùi về tên món khi không có cụm nào.
  // Cụm vi sát với thứ người ta gõ hơn tên món — "chuột máy tính logitech" thay vì "chuột
  // không dây" — nên nó cho bảng từ khoá tốt hơn.
  const seed = identity?.terms?.vi?.[0] || identity?.product || ''
  /*
   * Cụm để tra giá Việt Nam: TÊN MÓN GHÉP VỚI MÃ, không phải mã trần trụi.
   *
   * Bản đầu gửi thẳng "PH16271" và nhận về dây sạc, cáp Type-C, đồ chơi lắp ráp — Shopee coi
   * một mã nó không biết là một chuỗi vô nghĩa rồi trả về hàng bán chạy chung. Ghép tên món
   * vào ("máy sấy tóc PH1627") thì Shopee còn một chỗ bám để hiểu, và bảng trả về ít nhất
   * đúng loại hàng. Đây đúng là cách người dùng tự gõ khi tra tay.
   *
   * `code` đi kèm riêng để `rowMatches` kiểm — tên món giúp Shopee tìm đúng NGÀNH, còn mã
   * mới phân biệt được ĐÚNG MODEL trong ngành ấy. Thiếu vế thứ hai thì bảng máy sấy tóc nào
   * cũng "có kết quả".
   *
   * Cụm chữ không mã đứng cuối, cho những món vốn không có mã nào — với chúng thì cụm chữ là
   * đường duy nhất, và lúc ấy `rowMatches` rơi về `phraseHit` mà backend đã chấm.
   */
  const daTra = vnStatus === 'hoi' || vnStatus === 'xong' ? vnPrices : null

  const product = identity?.product ?? ''
  const vnTerms = [
    ...codes.slice(0, 3).map((entry) => ({
      query: `${product} ${entry.code}`.trim(),
      code: entry.code,
    })),
    { query: seed, code: '' },
  ].filter((entry) => entry.query)

  return (
    <div onPaste={onPaste}>
      <div className="page-head">
        <div>
          <h1>Image Search</h1>
        </div>
      </div>

      {/* BA BƯỚC ĐÁNH SỐ, theo đúng thứ tự phải làm: chọn sàn → đưa ảnh → bấm tìm. Bản trước
          để ô thả ảnh trôi giữa panel với hàng chip nằm dưới và không có nút nào, nên không
          nhìn ra đâu là bước đầu và lúc nào thì việc đã xong. */}
      <div className="panel img-form">
        <div className="img-step">
          <div className="img-step-head">
            <h3>
              <span className="img-step-no">1</span> Chọn sàn
            </h3>
            <div className="img-mode">
              <button data-on={!multi} onClick={() => switchMode(false)}>
                Một sàn
              </button>
              <button data-on={multi} onClick={() => switchMode(true)}>
                Nhiều sàn
              </button>
            </div>
          </div>

          <div className="img-sources">
            {SOURCES.map((source) => (
              <button
                key={source.id}
                className="img-source"
                data-on={chosen.includes(source.id)}
                onClick={() => pickSource(source.id)}
                title={source.hint}
              >
                {/* Dấu tick chỉ hiện ở sàn đang chọn. Ở chế độ nhiều sàn, viền sáng thôi là
                    chưa đủ rõ khi hai chip cạnh nhau cùng sáng. */}
                <span className="img-source-tick" aria-hidden>
                  ✓
                </span>
                {source.label}
              </button>
            ))}
          </div>
        </div>

        <div className="img-step">
          <div className="img-step-head">
            <h3>
              <span className="img-step-no">2</span> Đưa ảnh vào
            </h3>
            {preview && (
              <button
                className="img-clear"
                onClick={() => {
                  setFile(null)
                  setPreview(null)
                  setResult(null)
                }}
              >
                Chọn ảnh khác
              </button>
            )}
          </div>

          <div
            className="img-drop"
            data-dragging={dragging}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
          >
            {preview ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img className="img-preview" src={preview} alt="Ảnh đang tìm" />
            ) : (
              <>
                <b>Kéo ảnh vào đây, dán bằng Ctrl+V, hoặc bấm để chọn tệp</b>
                <small>JPEG · PNG · WEBP, tối đa {MAX_MB}MB</small>
              </>
            )}
          </div>
        </div>

        <div className="img-run">
          <button className="btn" onClick={run} disabled={!file || loading}>
            {loading ? 'Đang tìm…' : 'Tìm sản phẩm'}
          </button>
          <span className="muted small">
            {!file
              ? 'Chưa có ảnh nào'
              : `Sẽ hỏi ${chosen
                  .map((id) => SOURCES.find((s) => s.id === id)?.label ?? id)
                  .join(' · ')}`}
          </span>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            const picked = e.target.files?.[0]
            if (picked) pickFile(picked)
            e.target.value = ''
          }}
        />
      </div>

      {loading && (
        <p className="muted small">
          <span className="spinner" /> Đang đọc ảnh
          {/* Con số phải theo nguồn đang bật, không phải một con số cố định: chỉ 1688 thì lượt
              tìm xong trong khoảng năm giây, và hứa hai lăm giây ở đó làm người dùng tưởng
              treo theo hướng ngược lại — họ bỏ đi trước khi kết quả kịp hiện. */}
          {chosen.some((id) => id === 'lens' || id === 'taobao')
            ? ' và mở trình duyệt để hỏi các sàn — lượt đầu với một tấm ảnh mới mất khoảng 30 giây.'
            : ' và hỏi các sàn — khoảng 5 giây.'}{' '}
          Ảnh đã tìm rồi thì trả lời ngay.
        </p>
      )}

      {error && <div className="notice bad">{error}</div>}

      {/* MỘT DÒNG, không phải một khối. Bản trước bày cả đặc điểm ("màu đen · có nút cuộn") lẫn
          chín chip cụm tìm kiếm — mà đặc điểm thì mô tả lại đúng tấm ảnh người dùng vừa tự tay
          tải lên, còn chip zh thì dẫn sang Taobao/1688 bằng chữ, đúng nơi bảng kết quả bên dưới
          vừa tới bằng ảnh. Giữ lại đúng thứ không có đường thay thế: một cầu sang tab Từ khoá. */}
      {identity && (
        <div className="panel img-identity">
          <div className="img-what">
            <h2>{identity.product}</h2>
            {identity.brand && <span className="img-brand">{identity.brand}</span>}
            {!!seed && (
              <button
                className="img-go"
                onClick={() => router.push(`/keywords?seed=${encodeURIComponent(seed)}`)}
                title={`Mở mục Keyword với từ gốc “${seed}”`}
              >
                Tra Keyword →
              </button>
            )}
          </div>

          {/* MÃ SẢN PHẨM, ngay dưới tên món vì đây là thứ người ta chép đi dùng: nhắn cho
              xưởng để chắc hai bên đang nói cùng một món, và gõ vào ô tìm kiếm của sàn Việt
              Nam để so giá.

              SỐ ĐẾM HIỆN CÙNG MÃ chứ không giấu. Backend xếp hạng chứ không lọc (xem
              `codes.py`), nên mã ở cuối danh sách có thể chỉ là một chuỗi ngẫu nhiên lọt vào
              một tiêu đề — con số là thứ duy nhất cho người dùng biết nên tin cái nào. Giấu
              nó đi là bắt người ta tin đều cả năm dòng. */}
          {!!codes.length && (
            <div className="img-codes">
              <span className="img-lang">mã model</span>
              {codes.slice(0, 5).map((code) => (
                <span className="img-code" key={code.code} title={codeHint(code)}>
                  <b>{code.code}</b>
                  <small>{code.fromImage ? 'trên ảnh' : `${code.count} dòng`}</small>
                  {VN_MARKETS.map((market) => (
                    <a
                      key={market.id}
                      className="img-go"
                      href={market.url(code.code)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {market.label}
                    </a>
                  ))}
                </span>
              ))}

              {/* Trạng thái của cột giá, đặt ngay cạnh dãy mã vì cột ấy nói về đúng những mã
                  này. Ba câu cho ba tình huống — im lặng ở đây thì cột trống bên dưới không
                  có gì giải thích, và người đọc chỉ có thể kết luận là công cụ hỏng. */}
              {vnStatus === 'hoi' && (
                <span className="img-vn-status">
                  <span className="spinner" /> đang hỏi giá Shopee…
                </span>
              )}
              {vnStatus === 'thieu-ext' && (
                <span className="img-vn-status" data-warn="true">
                  chưa có extension nên không lấy được giá Việt Nam
                </span>
              )}
            </div>
          )}

          {/* Cụm tiếng Trung CHỈ hiện khi hai sàn Trung Quốc không trả về gì — tức là đúng lúc
              nó là đường thoát duy nhất: ảnh mờ, nhiều vật, hoặc nhận nhầm loại. Lúc bảng có
              hàng thì nó chỉ là một đường vòng tới chỗ người dùng đã tới rồi. */}
          {!sourcing.length && !globalSourcing.length && !chinaRetail.length &&
            !globalRetail.length && !!zhTerms.length && (
            <div className="img-terms">
              <span className="img-lang">tra tay</span>
              {zhTerms.map((term) => (
                <span className="img-term" key={term}>
                  {term}
                  {CN_MARKETS.map((market) => (
                    <a
                      key={market.id}
                      className="img-go"
                      href={market.url(term)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {market.label}
                    </a>
                  ))}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Câu này thường là "Lens đang bận" chứ không phải lỗi, nên nó đứng DƯỚI phần đọc ảnh —
          người dùng thấy thứ dùng được trước, rồi mới thấy phần còn thiếu. */}
      {result?.message && <div className="notice warn">{result.message}</div>}

      {/* THỨ TỰ CÁC BẢNG LÀ CHUỖI RA QUYẾT ĐỊNH, không phải thứ tự nguồn nào có trước:

            nhập tận xưởng ¥  →  nhập chính ngạch ₫  →  chợ gốc bán ¥  →  khách tự đặt ₫  →
            chợ đích đang bán ₫

          Đọc từ trên xuống là ra ngay phần biên, và hai bảng ₫ ở giữa mới là cặp đáng nhìn
          nhất: Alibaba.com nói mua buôn về bao nhiêu, AliExpress nói KHÁCH tự đặt về bao nhiêu.
          Khoảng giữa hai con số ấy là toàn bộ chỗ còn lại để bán — và khi nó âm thì mặt hàng
          không có cửa, một câu không nguồn nào khác nói ra được.

          Cố ý KHÔNG trộn vào một bảng — ¥29 của xưởng, ¥145 của shop Taobao và 989.000đ của
          Shopee đặt cạnh nhau sẽ trông như so sánh trực tiếp được. */}
      {/* `vnPrices` rỗng thì KHÔNG truyền xuống — cột phải chưa mọc ra. Truyền một bảng
          rỗng vào thì bảng có thêm một cột trống trơn từ trước khi ai bấm tra giá, và một
          cột trống không lời giải đọc thành lỗi vẽ. */}
      <Section title="Nguồn hàng 1688" items={sourcing} vnPrices={daTra} />
      <Section title="Bán buôn quốc tế · Alibaba.com" items={globalSourcing} vnPrices={daTra} />
      <Section title="Bán lẻ ở Trung Quốc" items={chinaRetail} vnPrices={daTra} />
      <Section title="Khách tự đặt về · AliExpress" items={globalRetail} vnPrices={daTra} />
      <MarketSection title="Nơi đang bán" items={matches} platforms={platforms} />
    </div>
  )
}
