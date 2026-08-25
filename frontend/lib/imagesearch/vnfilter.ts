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
  /** Link tới ĐÚNG sản phẩm đó trên sàn. Cột giá bấm thẳng vào đây. */
  link?: string
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
export type VnSkip = 'phu-kien' | 'ma-khac' | 'gia-lac' | null

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


/* ═══════════════════════════════════════════════════════════════════════════════════════
 * BA THỨ KÉO GIÁ XUỐNG SAI, đo trên 177 dòng Shopee THẬT (`.cache/ads-mau.json`, 2026-08-25)
 *
 *   phụ kiện       "Miếng lót chuột G102" — luật chữ ở trên bắt.
 *   gộp nhiều mã   "(Thanh lý 1K) Chuột không dây Logiteck M220/M350/G304 hàng OEM" — 58.147 ₫,
 *                  đứng HẠNG 6. Người bán gộp nhiều model vào một listing rồi hiện giá bản rẻ
 *                  nhất, tức là giá của M220 chứ không phải G304.
 *   hàng nhái      "[G102] Chuột gaming logitech G102 Led RGB 8000DPI" — 19.000 ₫, hạng 3.
 *                  Tiêu đề KHÔNG có gì đáng ngờ. Đúng tiêu đề ấy còn hiện lại ở hạng 44 với
 *                  giá 84.000 ₫ — cùng một listing, nhiều biến thể, hiện bản rẻ nhất.
 *
 * ĐÃ THỬ VÀ BỎ: lấy giá sỉ 1688 làm sàn. Nghe hợp lý — bán lẻ không thể dưới giá sỉ — nhưng
 * bảng 1688 trộn hàng nhái ¥15 với hàng Logitech thật ¥175, nên sàn tụt theo con rẻ nhất và
 * gần như không chặn gì. Sâu hơn: giá VỐN không đo được giá BÁN LẺ, G304 vốn ¥29 mà bán ở VN
 * 800k. Cách đó đã ship một lần và trượt; nó cũng kéo theo một bảng tỷ giá ghi cứng sẽ mục.
 *
 * BA LUẬT THAY THẾ, đều không cần tỷ giá:
 *   cửa sổ liên quan   chỉ đọc N dòng đầu. Shopee xếp theo Liên Quan, và mấy chục dòng cuối
 *                      là hàng vơ vét — hạng 50-51 của G304 có món 26.000 ₫ và 40.000 ₫.
 *   mã khác            tiêu đề nhắc model KHÁC thì giá hiện ra gần như luôn là của model kia.
 *   giá lạc            bỏ giá thấp hơn hẳn phần còn lại của cụm. Đây là thứ duy nhất bắt được
 *                      hàng nhái, vì chữ nghĩa của nó không khác gì hàng thật.
 *
 * KHÔNG NHẮM CHUẨN 100%. Đây là công cụ ước lượng để người bán khỏi phải tự tra tay từng mã;
 * lệch vài chục nghìn không sao, lệch mười lần mới là hỏng.
 * ═══════════════════════════════════════════════════════════════════════════════════════ */

/**
 * Chỉ đọc ngần này dòng đầu tiên.
 *
 * Shopee trả về theo LIÊN QUAN (xem `SORT` ở `vnprice.ts`), nên thứ tự này là thông tin thật
 * chứ không phải ngẫu nhiên: dòng đầu bảng là món người mua thật sự đang tìm. Đo trên dữ liệu
 * thật, hai món rẻ nhất mang mã G304 nằm ở hạng 50 và 51 — chúng chỉ lọt vào vì Shopee phải
 * trả đủ 60 dòng, không phải vì chúng liên quan.
 */
export const CUA_SO_LIEN_QUAN = 20

/** Giá thấp hơn ngần này lần trung vị của cụm thì coi là lạc, không phải cùng một món. */
const NGUONG_LAC = 0.25

/**
 * Rút các mã model có trong một tiêu đề. Bản TypeScript của `codes_in` ở
 * `backend/lib/imagesearch/codes.py` — cùng luật, để hai đầu đọc ra cùng một thứ.
 *
 * Mã là cụm CHỮ + SỐ dính nhau: G304, M220, TS3429, PH1627. Bắt buộc phải có ít nhất một chữ
 * số, nếu không thì mọi từ tiếng Anh trong tiêu đề đều thành mã.
 */
export function maTrongTieuDe(title: string): string[] {
  const re = /(?<![A-Za-z0-9])(?=[A-Za-z0-9-]{3,14}(?![A-Za-z0-9]))(?=[A-Za-z0-9-]*\d)[A-Za-z][A-Za-z0-9-]{2,13}(?![A-Za-z0-9])/g
  return [...(title || '').matchAll(re)].map((m) => m[0].toUpperCase())
}

/**
 * Chọn giá thấp nhất trong các dòng THẬT SỰ là món đang tìm.
 *
 * `rows` phải giữ nguyên THỨ TỰ LIÊN QUAN mà Shopee trả về — `markAndRank` đưa nhóm khớp mã
 * lên trước nhưng `Array.sort` của JS ổn định nên bên trong nhóm ấy thứ tự vẫn nguyên.
 * `ma` là mã đang tra; rỗng thì luật "mã khác" tự tắt (lúc tra bằng cụm chữ thường).
 */
export function chonGiaThapNhat<T extends DongCoGia>(
  rows: T[],
  ma: string,
): {
  price: number | null
  /** Chính dòng đã cho ra `price`. Cột giá cần nó để bấm thẳng vào sản phẩm, không phải mở
   *  lại một trang tìm kiếm rồi bắt người ta tự dò lại đúng món vừa đọc được. */
  winner: (T & { vnSkip: VnSkip }) | null
  rows: (T & { vnSkip: VnSkip })[]
  used: number
  skipped: number
  /**
   * Những luật đã bị TẮT ở lượt này vì áp vào là hết sạch ứng viên.
   *
   * Phải nói ra, không được nuốt: một con số tính trong lúc luật bị tắt kém tin hơn hẳn con
   * số bình thường, và người đọc có quyền biết điều đó.
   */
  noiLong: Exclude<VnSkip, null>[]
} {
  const mucTieu = (ma || '').toUpperCase()

  // Bước 1 — cửa sổ liên quan. Dòng ngoài cửa sổ KHÔNG bị gắn cờ: chúng không sai, chỉ là
  // không đủ liên quan để tin. Gắn cờ chúng sẽ thổi con số "đã bỏ" lên tới bốn chục.
  let trongCuaSo = 0
  type Dong = T & { vnSkip: VnSkip; _xet: boolean }
  let hienTai: Dong[] = rows.map((row) => {
    if (!row.codeHit) return { ...row, vnSkip: null as VnSkip, _xet: false }
    trongCuaSo += 1
    return { ...row, vnSkip: null as VnSkip, _xet: trongCuaSo <= CUA_SO_LIEN_QUAN }
  })

  const conLai = (ds: Dong[]) => ds.filter((r) => r._xet && !r.vnSkip)
  const noiLong: Exclude<VnSkip, null>[] = []

  /**
   * Áp một luật, NHƯNG CHỈ KHI nó còn chừa lại ít nhất một dòng.
   *
   * Đây là chốt chặn quan trọng nhất của cả hàm. Không có nó, một luật quá tay sẽ gạch sạch
   * ứng viên, `price` thành null, và giao diện in ra "không có ở sàn Việt" — một câu SAI về
   * một món đang bày bán đầy trên Shopee. Đã xảy ra thật với G305: người bán hay ghi
   * "G304/G305" chung một tiêu đề, nên luật "mã khác" gạch hết cả bảng.
   *
   * Thà giữ một con số kém chắc còn hơn tuyên bố một điều sai. Luật bị tắt được ghi lại để
   * nói ra, chứ không im lặng.
   */
  const apDung = (ten: Exclude<VnSkip, null>, dinh: (r: Dong) => boolean) => {
    // Chưa từng có ứng viên nào thì không có luật nào để nới. Không chặn ở đây thì một lượt
    // tra mà Shopee không trả dòng nào mang mã sẽ báo "đã phải tắt cả ba luật" — nghe như
    // công cụ vừa xoay xở chật vật, trong khi thật ra nó chẳng làm gì cả.
    if (conLai(hienTai).length === 0) return
    const thu = hienTai.map((r) =>
      r._xet && !r.vnSkip && dinh(r) ? { ...r, vnSkip: ten as VnSkip } : r,
    )
    if (conLai(thu).length === 0) {
      noiLong.push(ten)
      return
    }
    hienTai = thu
  }

  apDung('phu-kien', (r) => laPhuKienVn(r.title || ''))

  if (mucTieu) {
    apDung('ma-khac', (r) =>
      maTrongTieuDe(r.title || '').some((m) => m !== mucTieu),
    )
  }

  // Giá lạc — so với trung vị của chính những dòng còn sống SAU hai luật trên.
  const gia = conLai(hienTai)
    .map((r) => r.priceValue)
    .filter((v): v is number => typeof v === 'number')
    .sort((a, b) => a - b)
  if (gia.length) {
    const trungVi =
      gia.length % 2 ? gia[(gia.length - 1) / 2] : (gia[gia.length / 2 - 1] + gia[gia.length / 2]) / 2
    apDung('gia-lac', (r) => typeof r.priceValue === 'number' && r.priceValue < trungVi * NGUONG_LAC)
  }

  const dungDuoc = conLai(hienTai).filter((r) => typeof r.priceValue === 'number')
  const re = dungDuoc.reduce<Dong | null>(
    (best, row) =>
      best === null || (row.priceValue as number) < (best.priceValue as number) ? row : best,
    null,
  )

  // `_xet` là chuyện nội bộ của hàm này, không để nó rò ra ngoài.
  const bo = (r: Dong): T & { vnSkip: VnSkip } => {
    const { _xet, ...rest } = r
    return rest as T & { vnSkip: VnSkip }
  }
  const sach = hienTai.map(bo)
  return {
    price: re ? (re.priceValue as number) : null,
    winner: re ? bo(re) : null,
    rows: sach,
    used: dungDuoc.length,
    skipped: sach.filter((r) => r.vnSkip).length,
    noiLong,
  }
}
