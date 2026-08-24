/**
 * Ba ô chọn của Google Trends: tìm ở đâu, trong bao lâu, trên kho dữ liệu nào.
 *
 * Giá trị ở đây phải khớp từng ký tự với thứ backend chấp nhận — xem `TRENDS_PRESET_RANGES`
 * và `TRENDS_PROPERTIES` ở `backend/lib/keywords/search.py`. Backend cố ý CHỐT danh sách và
 * lặng lẽ rơi về mặc định khi gặp giá trị lạ, vì Google cũng làm đúng như vậy: một `date`
 * hay `gprop` sai không báo lỗi, nó trả về một bảng hợp lệ của một câu hỏi khác.
 */

export type TrendsOption = { value: string; label: string }

/** Giá trị `country` cho "Toàn thế giới" — khớp `WORLDWIDE` ở backend. */
export const WORLDWIDE = 'WORLD'

export const DEFAULT_COUNTRY = 'VN'
export const DEFAULT_TIME_RANGE = 'today 12-m'
export const DEFAULT_PROPERTY = ''

export const TIME_RANGES: TrendsOption[] = [
  { value: 'now 1-H', label: 'Giờ qua' },
  { value: 'now 4-H', label: '4 giờ qua' },
  { value: 'now 1-d', label: '24 giờ qua' },
  { value: 'now 7-d', label: 'Tuần qua' },
  { value: 'today 1-m', label: 'Tháng qua' },
  { value: 'today 3-m', label: '3 tháng qua' },
  { value: 'today 12-m', label: 'Năm qua' },
  { value: 'today 5-y', label: '5 năm qua' },
  { value: 'all', label: '2004 – Hiện nay' },
]

/**
 * Các năm trọn vẹn, mới nhất trước — đúng phần dưới của menu thời gian trên Google Trends.
 *
 * Năm hiện tại KHÔNG có mặt: nó chưa trọn, nên `2026-01-01 2026-12-31` sẽ hỏi Trends một
 * khoảng có phần nằm ở tương lai và đường vẽ ra kết thúc bằng một đoạn phẳng bằng không —
 * trông hệt như nhu cầu sụp đổ. Ai cần phần đã trôi qua của năm nay thì đã có "Năm qua".
 */
export function fullYearRanges(now: Date, count = 12): TrendsOption[] {
  const latest = now.getFullYear() - 1
  return Array.from({ length: count }, (_, i) => latest - i)
    .filter((year) => year >= 2004)
    .map((year) => ({ value: `${year}-01-01 ${year}-12-31`, label: String(year) }))
}

/** `gprop` của Trends. Rỗng là Tìm kiếm trên web — đó là giá trị thật, không phải "chưa chọn". */
export const PROPERTIES: TrendsOption[] = [
  { value: '', label: 'Tìm kiếm trên web' },
  { value: 'images', label: 'Tìm kiếm hình ảnh' },
  { value: 'news', label: 'Tìm kiếm tin tức' },
  { value: 'froogle', label: 'Google Mua sắm' },
  { value: 'youtube', label: 'Tìm kiếm trên YouTube' },
]

/**
 * Các thị trường lên đầu danh sách quốc gia.
 *
 * Không phải "quan trọng hơn" mà là "hay dùng hơn ở đây": đây là công cụ cho người bán hàng
 * Việt Nam, nên nhóm Đông Nam Á cộng Mỹ đứng trước hai trăm nước còn lại.
 *
 * KHÔNG phải danh sách thị trường của Shopee, dù trông giống. Shopee còn phục vụ Đài Loan và
 * Brazil (`DOMAIN` ở `backend/lib/keywords/providers/shopee.py`) mà hai nước đó không được
 * ghim, còn Mỹ thì được ghim mà Shopee lại không có mặt. Việc lọc theo nguồn là của
 * `countryOptions(allowed)`; ghim chỉ là thứ tự hiển thị.
 */
export const PINNED_COUNTRIES = ['VN', 'TH', 'PH', 'ID', 'MY', 'SG', 'US']

/**
 * Mã ISO 3166-1 alpha-2 của các vùng Google Trends nhận.
 *
 * Chỉ lưu MÃ, không lưu tên. Tên tiếng Việt lấy từ `Intl.DisplayNames` của chính trình duyệt,
 * nên không có bảng dịch hai trăm dòng nào phải bảo trì trong repo này, và tên hiện ra luôn
 * khớp với tên hệ điều hành người dùng đang dùng ở mọi chỗ khác.
 */
export const COUNTRY_CODES = [
  'AD','AE','AF','AG','AI','AL','AM','AO','AQ','AR','AS','AT','AU','AW','AX','AZ',
  'BA','BB','BD','BE','BF','BG','BH','BI','BJ','BL','BM','BN','BO','BQ','BR','BS','BT','BV','BW','BY','BZ',
  'CA','CC','CD','CF','CG','CH','CI','CK','CL','CM','CN','CO','CR','CU','CV','CW','CX','CY','CZ',
  'DE','DJ','DK','DM','DO','DZ',
  'EC','EE','EG','EH','ER','ES','ET',
  'FI','FJ','FK','FM','FO','FR',
  'GA','GB','GD','GE','GF','GG','GH','GI','GL','GM','GN','GP','GQ','GR','GS','GT','GU','GW','GY',
  'HK','HM','HN','HR','HT','HU',
  'ID','IE','IL','IM','IN','IO','IQ','IR','IS','IT',
  'JE','JM','JO','JP',
  'KE','KG','KH','KI','KM','KN','KP','KR','KW','KY','KZ',
  'LA','LB','LC','LI','LK','LR','LS','LT','LU','LV','LY',
  'MA','MC','MD','ME','MF','MG','MH','MK','ML','MM','MN','MO','MP','MQ','MR','MS','MT','MU','MV','MW','MX','MY','MZ',
  'NA','NC','NE','NF','NG','NI','NL','NO','NP','NR','NU','NZ',
  'OM',
  'PA','PE','PF','PG','PH','PK','PL','PM','PN','PR','PS','PT','PW','PY',
  'QA',
  'RE','RO','RS','RU','RW',
  'SA','SB','SC','SD','SE','SG','SH','SI','SJ','SK','SL','SM','SN','SO','SR','SS','ST','SV','SX','SY','SZ',
  'TC','TD','TF','TG','TH','TJ','TK','TL','TM','TN','TO','TR','TT','TV','TW','TZ',
  'UA','UG','UM','US','UY','UZ',
  'VA','VC','VE','VG','VI','VN','VU',
  'WF','WS',
  'YE','YT',
  'ZA','ZM','ZW',
]

/**
 * Danh sách quốc gia đã có tên tiếng Việt, "Toàn thế giới" đứng đầu rồi tới nhóm hay dùng.
 *
 * `Intl.DisplayNames` cần dữ liệu ICU đầy đủ. Trình duyệt nào cũng có; Node khi dựng trang
 * thì tuỳ bản build — nên chỗ nào không dịch được sẽ rơi về chính mã ISO thay vì làm hỏng
 * cả danh sách.
 *
 * `allowed` giới hạn danh sách vào các thị trường mà nguồn ĐANG CHỌN thật sự phục vụ;
 * `null`/bỏ trống nghĩa là mọi thị trường. Danh sách truyền vào đến từ `markets` do backend
 * công bố, nên ở đây không có mã nước nào bị viết cứng theo nguồn.
 *
 * Lọc chứ không phải làm mờ: một ô chọn bày ra hai trăm nước rồi âm thầm đổi nguồn khi người
 * dùng chạm vào nước thứ bảy là bắt họ học một luật ẩn. Thà đừng bày ra thứ không chọn được.
 */
export function countryOptions(allowed?: string[] | null): TrendsOption[] {
  let display: Intl.DisplayNames | null = null
  try {
    display = new Intl.DisplayNames(['vi'], { type: 'region' })
  } catch {
    display = null
  }
  const nameOf = (code: string) => {
    try {
      return display?.of(code) ?? code
    } catch {
      return code
    }
  }

  // `WORLDWIDE` đi qua đúng phép kiểm này chứ không được miễn trừ: "Toàn thế giới" là một
  // lựa chọn thật mà Shopee không phục vụ được, nên nó phải biến mất cùng với các nước khác.
  const permitted = allowed ? new Set(allowed) : null
  const serves = (code: string) => !permitted || permitted.has(code)

  const pinned = PINNED_COUNTRIES.filter(serves).map((code) => ({ value: code, label: nameOf(code) }))
  const rest = COUNTRY_CODES.filter((code) => !PINNED_COUNTRIES.includes(code) && serves(code))
    .map((code) => ({ value: code, label: nameOf(code) }))
    .sort((a, b) => a.label.localeCompare(b.label, 'vi'))

  const worldwide = serves(WORLDWIDE) ? [{ value: WORLDWIDE, label: 'Toàn thế giới' }] : []
  return [...worldwide, ...pinned, ...rest]
}
