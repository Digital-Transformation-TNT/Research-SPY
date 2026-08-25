/**
 * LỌC PHỤ KIỆN ĐỘI LỐT HÀNG THẬT khi tra giá bán ở Việt Nam.
 *
 * File này CỐ Ý KHÔNG IMPORT GÌ CẢ. Nó tách khỏi `vnprice.ts` — nơi phải kéo theo extension,
 * `browserGet` và cả tầng mạng — để hai luật bên dưới chạy được trong một tiến trình Node
 * trần, không cần trình duyệt, không cần stub. Nhờ vậy chúng KIỂM ĐƯỢC, và chúng cần được
 * kiểm: cả hai đều là luật đoán, và một luật đoán không có bộ đo là một luật không ai biết
 * nó đang đúng hay sai.
 *
 * Bộ đo nằm ở `scripts/test/vnfilter.test.js`.
 */

/** Chỉ cần đúng ba trường này để chấm một dòng — không kéo cả `ImageMatch` vào đây. */
export type DongCoGia = {
  title?: string
  priceValue?: number
  codeHit?: boolean
}

/* ═══════════════════════════════════════════════════════════════════════════════════════
 * PHỤ KIỆN ĐỘI LỐT HÀNG THẬT — hai luật độc lập
 *
 * Người bán Shopee cố tình để phụ kiện rẻ dưới cùng từ khoá với hàng thật, vì món rẻ nhất
 * là món được bấm vào. Tra "chuột G102" thì miếng lót chuột 19.000 ₫ nằm ngay trong bảng,
 * mang đúng mã G102, nên `rowMatches` cho qua và `Math.min` chộp đúng nó. Kết quả là công cụ
 * in ra "Giá ở VN: 19.000 ₫" cho một con chuột giá thật hơn 150.000 ₫ — một con số sai mà
 * trông hoàn toàn hợp lý, tức là kiểu sai tệ nhất mục này có thể mắc.
 *
 * Hai luật dưới đây bắt hai loại khác nhau và cố ý KHÔNG phụ thuộc nhau:
 *
 *   giá   phụ kiện rẻ bất thường — bắt được cả khi tiêu đề không có chữ nào đáng ngờ
 *   chữ   phụ kiện đắt ngang hàng thật (keycap, cánh quạt) — luật giá không thấy chúng
 *
 * Dòng bị bắt KHÔNG bị xoá. Nó ở lại bảng, mang nhãn, và chỉ bị gạch khỏi phép tính giá —
 * đúng nguyên tắc của cả mục này: xếp hạng chứ không âm thầm giấu. Giấu đi thì lúc luật đoán
 * sai sẽ không còn cách nào biết.
 * ═══════════════════════════════════════════════════════════════════════════════════════ */

/** Vì sao một dòng bị gạch khỏi phép tính giá. `null` = dòng này được tính. */
export type VnSkip = 'phu-kien' | 're-hon-gia-si' | null

/**
 * Danh từ chính của phụ kiện. So ở PHẦN ĐẦU tiêu đề, vì tiếng Việt đặt danh từ chính lên
 * trước: "Miếng lót chuột G102" mở đầu bằng món thật sự đang bán, còn "Chuột Logitech G102"
 * cũng vậy. Đọc phần đầu là đọc đúng chỗ nói món này là cái gì.
 */
const DAU_HIEU_PHU_KIEN = [
  'mieng lot', 'lot chuot', 'ban di chuot', 'pad chuot', 'mousepad', 'lot tay', 'ke tay',
  'op lung', 'op silicon', 'op deo', 'op nhua', 'vo bao', 'vo op', 'bao da', 'bao dung',
  'tui dung', 'tui chong soc', 'keycap', 'key cap', 'nut bam', 'mat phim', 'ban phim so',
  'chan de', 'gia do', 'de dung', 'ke man', 'gia treo',
  'day sac', 'day cap', 'day nguon', 'day deo', 'cap sac', 'cu sac', 'adapter', 'adaptor',
  'canh quat', 'luoi loc', 'mang loc', 'loi loc', 'tam loc', 'dau xit',
  'mieng dan', 'tem dan', 'decal', 'sticker', 'skin dan', 'cuong luc',
  'feet chuot', 'chan chuot', 'grip tape',
  'phu kien', 'linh kien', 'do thay the',
]

/**
 * PHẢI so theo RANH GIỚI TỪ, không được dùng `includes`.
 *
 * Đo trên 137 tiêu đề Việt thật lấy từ cache: bản đầu dùng `includes('op ')` và nó khớp bên
 * trong chữ "top", gắn cờ nhầm "Top 5 chuột gaming không dây tốt nhất". Sau khi đổi sang
 * ranh giới từ: 0/137 bắt nhầm.
 *
 * Tiếng Việt tách từ bằng khoảng trắng nên cách này chạy được — khác hẳn tiếng Trung, nơi
 * ranh giới từ không bao giờ nảy giữa `境` và `G` (xem `backend/lib/imagesearch/codes.py`).
 *
 * KHÔNG dùng `\s+` trong chuỗi này: `dauTitle` đã gộp mọi khoảng trắng về một dấu cách, nên
 * dấu cách thường là đủ — và nó tránh hẳn cái bẫy escape nhiều lớp đã làm hỏng bản nháp,
 * biến `mieng\s+lot` thành `miengs+lot` rồi luật im lặng không bắt gì.
 */
const RE_PHU_KIEN = new RegExp(
  `(?:^|[^a-z0-9])(?:${DAU_HIEU_PHU_KIEN.join('|')})(?![a-z0-9])`,
  'i',
)

/** Bỏ dấu, thường hoá, và gỡ mấy chữ trang trí người bán hay nhét lên đầu tiêu đề. */
function dauTitle(title: string): string {
  let text = (title || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/đ/gi, 'd')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
  const rac = /^(?:[^\p{L}\p{N}]+|combo|set|hot|new|sale|freeship|chinh hang|gia re)\s*/giu
  let truoc: string
  do {
    truoc = text
    text = text.replace(rac, '')
  } while (text !== truoc)
  return text
}

/** Tiêu đề này nói món đang bán là một phụ kiện, chứ không phải chính sản phẩm. */
export function laPhuKienVn(title: string): boolean {
  return RE_PHU_KIEN.test(dauTitle(title).slice(0, 34))
}

/**
 * Tỷ giá quy giá sỉ Trung Quốc về đồng, đọc theo ký hiệu mà `priceUnit` bóc ra.
 *
 * Ghi cứng, đo ngày 2026-08-25. Nó SẼ cũ dần, và điều đó không sao: khoảng cách luật này đi
 * bắt là 4-5 lần (G102 19.000 ₫ so với giá sỉ ~88.000 ₫), nên tỷ giá lệch 10-20% cũng không
 * đổi được kết luận nào. Đừng dùng mấy con số này cho việc tính biên lợi nhuận.
 */
export const TY_GIA_VND: Record<string, number> = {
  '¥': 3_700,
  'cny': 3_700,
  'rmb': 3_700,
  'us$': 25_400,
  '$': 25_400,
  'usd': 25_400,
  '₫': 1,
  'đ': 1,
  'vnd': 1,
}

/** Giá VN phải đạt ít nhất ngần này lần giá sỉ thì mới coi là cùng một món. */
const NGUONG_SAN = 0.9

/**
 * Chọn giá thấp nhất, sau khi gạch những dòng không phải món đang tìm.
 *
 * `sanVnd` là giá sỉ Trung Quốc của chính mã này, đã quy ra đồng. `null` khi không tra được
 * — lúc ấy luật giá tự tắt và chỉ còn luật chữ làm việc, chứ không bịa ra một cái sàn.
 */
export function chonGiaThapNhat<T extends DongCoGia>(
  rows: T[],
  sanVnd: number | null,
): { price: number | null; rows: (T & { vnSkip: VnSkip })[]; used: number; skipped: number } {
  const danhDau = rows.map((row) => {
    if (!row.codeHit) return { ...row, vnSkip: null as VnSkip }
    if (laPhuKienVn(row.title || '')) return { ...row, vnSkip: 'phu-kien' as VnSkip }
    if (
      sanVnd !== null &&
      typeof row.priceValue === 'number' &&
      row.priceValue < sanVnd * NGUONG_SAN
    ) {
      // Bán lẻ ở Việt Nam thấp hơn cả giá sỉ tại xưởng Trung Quốc là chuyện không xảy ra với
      // cùng một món. Gần như luôn là một món khác, rẻ hơn, bày chung từ khoá.
      return { ...row, vnSkip: 're-hon-gia-si' as VnSkip }
    }
    return { ...row, vnSkip: null as VnSkip }
  })

  const dungDuoc = danhDau.filter((row) => row.codeHit && !row.vnSkip)
  const price = dungDuoc.reduce<number | null>((best, row) => {
    const value = row.priceValue
    if (typeof value !== 'number') return best
    return best === null || value < best ? value : best
  }, null)

  return {
    price,
    rows: danhDau,
    used: dungDuoc.length,
    skipped: danhDau.filter((row) => row.vnSkip).length,
  }
}

