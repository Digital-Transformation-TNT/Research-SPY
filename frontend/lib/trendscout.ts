/**
 * Từ vựng của TREND·SCOUT (Top sản phẩm trong Trend Signal Hub), phía giao diện.
 * Nguồn sự thật: `backend/hub/signal/scout.py`. Công thức và các mức: `Trend Signal Hub/Cach-tinh-tung-trang-thai.docx`.
 */

/**
 * Ba sàn thật. File demo ghi "TikTok" — đó là viết nhầm cho 1688.
 * `country` là thị trường One-shot AI đem đi đối chiếu ô tìm kiếm của sàn.
 */
export const SAN = [
  { key: 'shopee_vn', label: 'Shopee VN', country: 'VN' },
  { key: 'shopee_ph', label: 'Shopee PH', country: 'PH' },
  { key: '1688', label: '1688', country: 'CN' },
] as const

export type SanKey = (typeof SAN)[number]['key']

export type LensKey = 'ban_chay' | 'hot' | 'steady' | 'spike' | 'gap' | 'new'

/**
 * Sáu lăng kính, đúng thứ tự và tên của tài liệu 14/09/2026 — Tân binh ĐỂ CUỐI.
 *
 * "Tăng tốc" trước đây là HAI lăng kính (`hot_gmv` doanh số và `hot_sold` lượt bán) cho ra hai
 * bảng gần trùng nhau; nay là MỘT, phải đạt cả hai điều kiện lũy kế + tốc độ.
 *
 * `knobs` là các số đỏ của tài liệu mà lăng kính đó dùng — ô Tùy chỉnh chỉ bày đúng những số
 * này, không bày cả 19 số cùng lúc.
 */
export const LENSES: Array<{
  key: LensKey
  icon: string
  label: string
  note: string
  knobs: Array<{ key: string; label: string; unit: string }>
}> = [
  {
    key: 'ban_chay',
    icon: '📈',
    label: 'Bán chạy',
    note: 'Lấy nguyên thứ hạng theo lượt bán 30 ngày của sàn. Chỉ cần một lần quét.',
    knobs: [],
  },
  {
    key: 'hot',
    icon: '🔥',
    label: 'Đang tăng tốc',
    note: 'Tốc độ bán mỗi ngày của 5 ngày gần nhất cao hơn hẳn 5 ngày trước đó. Phải đạt CẢ HAI: tăng từ 40% trở lên VÀ đã bán lũy kế tối thiểu 1.000 sản phẩm. Xếp theo mức tăng.',
    knobs: [
      { key: 'tang_toc_pct', label: 'Tăng từ', unit: '%' },
      { key: 'tang_toc_luy_ke', label: 'Đã bán lũy kế từ', unit: 'sp' },
      { key: 'tang_toc_cua_so', label: 'Cửa sổ so sánh', unit: 'ngày' },
    ],
  },
  // ĐÃ ẨN lăng kính 'Bán khoẻ ổn định' (steady) khỏi giao diện theo yêu cầu 22/09/2026 — cho
  // CẢ Shopee VN, Shopee PH và 1688 (mảng LENSES dùng chung, không lọc theo sàn). Backend
  // (scout.py) vẫn còn nhánh 'steady' nguyên vẹn; whyText/knob 'on_dinh_*' cũng giữ. Bỏ comment
  // khối dưới để hiện lại chip này.
  // {
  //   key: 'steady',
  //   icon: '💰',
  //   label: 'Bán khoẻ ổn định',
  //   note: 'Ngày tệ nhất vẫn bán được kha khá — hầu như không có ngày chết, và hiện vẫn chưa hạ nhiệt (TB 3 ngày gần nhất ≥ 80% TB 5 ngày). Cầu đã được chứng minh, nhập về không sợ ôm hàng. Xếp theo doanh thu sàn 5 ngày.',
  //   knobs: [
  //     { key: 'on_dinh_moc', label: 'Sàn tối thiểu', unit: 'sp/ngày' },
  //     { key: 'on_dinh_giu_nhiet', label: 'TB 3 ngày ≥', unit: '% TB 5 ngày' },
  //     { key: 'on_dinh_cua_so', label: 'Cửa sổ', unit: 'ngày' },
  //   ],
  // },
  {
    key: 'spike',
    icon: '⚡',
    label: 'Đột biến',
    note: 'Tốc độ bán trong 1 ngày gần nhất vọt lên từ 500% trở lên so với nền 5 ngày trước đó, và đã bán ít nhất 1.000 lượt để loại tăng ảo. Xếp theo mức vọt.',
    knobs: [
      { key: 'dot_bien_pct', label: 'Vọt từ', unit: '%' },
      { key: 'dot_bien_luy_ke', label: 'Đã bán lũy kế từ', unit: 'sp' },
      { key: 'dot_bien_nen', label: 'Nền trước', unit: 'ngày' },
    ],
  },
  {
    key: 'gap',
    icon: '🎯',
    label: 'Khe hở',
    note: 'Cầu đã chứng minh (bán nhiều và đều) nhưng listing dẫn đầu ngách lại yếu vì rating quá thấp — cửa đang mở để nhảy vào làm hàng tốt hơn. Xếp theo doanh thu 5 ngày.',
    knobs: [
      { key: 'khe_ho_luy_ke', label: 'Đã bán lũy kế trên', unit: 'sp' },
      { key: 'khe_ho_deu', label: 'Sàn ≥', unit: '% mức thường' },
      { key: 'khe_ho_rating', label: 'Rating dưới', unit: '★' },
    ],
  },
  {
    key: 'new',
    icon: '🆕',
    label: 'Tân binh bán chạy',
    note: 'Mới xuất hiện trong ngành không quá 7 ngày mà đã bán được từ 350 lượt trở lên. Xếp theo bán được bao nhiêu một ngày kể từ khi xuất hiện. Hàng cũ vừa mới leo vào top ngành bị loại bằng phép thử lũy kế ≈ lượt bán 30 ngày.',
    knobs: [
      { key: 'tan_binh_ngay', label: 'Xuất hiện không quá', unit: 'ngày' },
      { key: 'tan_binh_da_ban', label: 'Đã bán từ', unit: 'sp' },
      { key: 'tan_binh_ty_le', label: 'Lũy kế tối đa', unit: '× bán 30 ngày' },
    ],
  },
]

export type CategoryTree = {
  san: SanKey
  nganh: Array<{ main_id: string; main_name: string; subs: Array<{ sub_id: string; sub_name: string }> }>
}

export type ToplistItem = {
  product_id: string
  title: string | null
  url: string | null
  image_url: string | null
  price: number | null
  currency: string | null
  rating: number | null
  reviews: number | null
  sold_cumulative: number | null
  ban_30: number
  doanh_so_30: number
  ngay: string
  main_id: string | null
  main_name: string | null
  sub_id: string | null
  sub_name: string | null
}

export type Toplist = {
  san: SanKey
  loai: 'ban_chay' | 'doanh_so'
  ngay_moi_nhat?: string
  /** Số listing hàng ảo (quà tặng, ô bù tiền…) đã bị loại trước khi xếp hạng. */
  da_loc?: number
  items: ToplistItem[]
  ghi_chu?: string
}

export type ScoutItem = {
  product_id: string
  title: string | null
  url: string | null
  image_url: string | null
  price: number | null
  currency: string | null
  rating: number | null
  reviews: number | null
  sold_cumulative: number | null
  sold_monthly: number | null
  doanh_so_30_san: number
  lan_quet: number
  so_ngay: number
  diem: number
  tang_toc_cua_so?: number
  tang_ban_pct?: number | null
  tang_doanh_so_pct?: number | null
  dot_bien_pct?: number | null
  dot_bien_nhanh?: number
  dot_bien_nen?: number
  san_ngay?: number | null
  muc_thuong?: number | null
  /** Số ngày THẬT trong cửa sổ ổn định — có thể nhỏ hơn 5 khi lịch sử còn ngắn. */
  on_dinh_cua_so?: number
  on_dinh_gan_day?: number
  tb_gan?: number | null
  tb_cua_so?: number | null
  /** Doanh thu sàn = sàn/ngày × số ngày cửa sổ × giá. Xếp hạng Bán khoẻ ổn định. */
  doanh_thu_san?: number
  /** Doanh thu cả cửa sổ = tổng bán trong cửa sổ × giá. Xếp hạng Khe hở. */
  doanh_so_cua_so?: number
  ngay_xuat_hien?: number
  main_name?: string
  sub_name?: string
}

export type Explore = {
  san: SanKey
  main_id: string | null
  sub_id: string | null
  nguon: 'nganh_lon' | 'nganh_con' | 'gop_nganh_con' | 'tu_khoa_1688' | 'tat_ca_nganh_con'
  ngay_quet: string[]
  so_lan_quet: number
  so_ngay: number
  nguong: Record<string, number>
  lens: LensKey
  dem: Record<LensKey, number>
  tong_san_pham: number
  items: ScoutItem[]
  ghi_chu?: string
}

// ── định dạng ────────────────────────────────────────────────────────────────────────────

const FULL = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 })
const DECIMAL = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 })
const ONE = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 })

/**
 * Số gọn kiểu người Việt đọc: 12.300 → "12,3k", 1.700.000 → "1,7 tr", 93.000.000.000 → "93 tỷ".
 *
 * Tự viết thay vì `Intl` `notation: 'compact'`: bản vi-VN của nó cho ra "93 T" và "1,7 Tr" —
 * chữ "T" đọc được thành cả "tỷ" lẫn "triệu", đúng chỗ không được phép mơ hồ là cột doanh số.
 */
function compact(n: number): string {
  const a = Math.abs(n)
  if (a >= 1e9) return `${ONE.format(n / 1e9)} tỷ`
  if (a >= 1e6) return `${ONE.format(n / 1e6)} tr`
  return `${ONE.format(n / 1e3)}k`
}

/** Dưới 10.000 thì để nguyên số — gọn hoá chỉ làm mất độ chính xác. */
export function short(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return Math.abs(n) < 10_000 ? FULL.format(n) : compact(n)
}

/**
 * Tiền theo đơn vị gốc của sàn — KHÔNG quy đổi. Mỗi lần chỉ xem một sàn nên VND, PHP, CNY
 * không bao giờ đứng cạnh nhau trong cùng một bảng.
 */
export function money(n: number | null | undefined, currency: string | null | undefined, gon = false): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const cur = (currency || '').toUpperCase()
  const body = gon && Math.abs(n) >= 10_000 ? compact(n) : cur === 'VND' ? FULL.format(n) : DECIMAL.format(n)
  if (cur === 'VND') return `${body} ₫`
  if (cur === 'PHP') return `₱${body}`
  if (cur === 'CNY') return `¥${body}`
  return cur ? `${body} ${cur}` : body
}

/**
 * Phần trăm theo kiểu QUỐC TẾ — "," ngăn nghìn, "." thập phân, luôn 2 chữ số: "+19,300.00%".
 *
 * Cố ý khác mọi số khác trên trang (vốn theo vi-VN). Chủ dự án chốt 18/09/2026: "+19.300%" kiểu
 * Việt bị đọc nhầm thành 19,3% trong khi thật là mười chín NGHÌN phần trăm — ở đúng cột quyết
 * định có nhập hàng hay không.
 */
const PCT = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function pct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n >= 0 ? '+' : ''}${PCT.format(n)}%`
}

/** "2026-09-11" → "11/09". */
export function dayLabel(day: string | null | undefined): string {
  if (!day) return '—'
  const [, m, d] = day.split('-')
  return `${d}/${m}`
}

/** Câu "vì sao lọt lăng kính này", dựng từ đúng các con số backend đã dùng để xét. */
export function whyText(item: ScoutItem, lens: LensKey): string {
  const cur = item.currency
  switch (lens) {
    case 'ban_chay':
      return `Sàn ghi bán ${short(item.sold_monthly)} trong 30 ngày, doanh số ~${money(item.doanh_so_30_san, cur, true)}.`
    case 'hot':
      // Lũy kế nhắc lại ngay trong câu: đây là lăng kính có HAI điều kiện, đọc mỗi % tăng thì
      // tưởng một dòng tăng 900% từ nền 3 sản phẩm cũng lọt được.
      return `Bán/ngày ${item.tang_toc_cua_so} ngày gần nhất ${pct(item.tang_ban_pct)} so với ${item.tang_toc_cua_so} ngày trước, trên nền đã bán ${short(item.sold_cumulative)}.`
    case 'steady':
      return `Ngày thấp vẫn bán ${short(item.san_ngay)}/ngày. Doanh thu sàn ${item.on_dinh_cua_so} ngày ~${money(item.doanh_thu_san, cur, true)}.`
    case 'spike':
      return `${item.dot_bien_nhanh} ngày cuối bán vọt ${pct(item.dot_bien_pct)} so với nền ${item.dot_bien_nen} ngày trước.`
    case 'gap':
      return `Cầu đều (ngày thấp ${short(item.san_ngay)}/ngày) nhưng rating chỉ ${item.rating}★. Doanh thu ${item.on_dinh_cua_so} ngày ~${money(item.doanh_so_cua_so, cur, true)}.`
    case 'new':
      return `Xuất hiện ${item.ngay_xuat_hien} ngày, đã bán ${short(item.sold_cumulative)} → ${short(item.diem)}/ngày.`
  }
}
