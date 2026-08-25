/**
 * Bộ đo cho hai luật lọc phụ kiện ở `lib/imagesearch/vnfilter.ts`.
 *
 *     node scripts/vnfilter.test.js
 *
 * Nó biên dịch chính file trong repo rồi chạy, chứ không chép lại logic sang đây — một bản
 * sao thứ hai sẽ vẫn xanh trong lúc bản thật đã hỏng.
 *
 * HAI PHÍA CỦA BỘ ĐO KHÔNG NGANG NHAU VỀ ĐỘ TIN, và phải nói thẳng chuyện đó:
 *
 *   BẮT NHẦM  đo trên `fixtures/vn-titles.json` — 137 tiêu đề THẬT, lấy từ cache của các
 *             lượt tìm đã chạy (chuột Logitech, sáp thơm Carefor, quạt Tiross). Đây là bằng
 *             chứng chắc chắn: không dòng nào trong đó là phụ kiện, nên mọi lượt gắn cờ đều
 *             là gắn nhầm. Chính bộ này đã bắt được bản đầu dùng `includes('op ')` khớp bên
 *             trong chữ "top".
 *
 *   BẮT ĐỦ    đo trên một bộ tiêu đề TỰ VIẾT (lót chuột, keycap, cánh quạt). Nó chỉ nói luật
 *             chữ không chết, không nói gì về recall ngoài đời.
 *
 *   CHỌN GIÁ  đo trên `fixtures/shopee-vn.json` — 179 dòng Shopee THẬT, đúng thứ tự Liên Quan,
 *             lấy từ chính lượt tìm của người dùng ngày 2026-08-25 (bật `ADS_DUMP=1` rồi đọc
 *             `.cache/ads-mau.json`). Đây mới là bộ đo có giá trị cho phần chọn giá.
 */

const { execFileSync } = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

const GOC = path.resolve(__dirname, '..')
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'vnfilter-'))

// Gọi thẳng tsc bằng chính Node, KHÔNG qua `npx`. Node 24 từ chối spawn một file `.cmd` khi
// không bật shell (EINVAL), mà bật shell thì lại phải lo chuyện trích dẫn đường dẫn có dấu
// cách. Chạy file JS của tsc là tránh được cả hai, và giống nhau trên mọi hệ điều hành.
execFileSync(
  process.execPath,
  [path.join(GOC, 'node_modules/typescript/bin/tsc'),
   path.join(GOC, 'lib/imagesearch/vnfilter.ts'),
   '--outDir', OUT, '--module', 'commonjs', '--target', 'es2020', '--skipLibCheck'],
  { cwd: GOC, stdio: 'inherit' },
)
const { laPhuKienVn, chonGiaThapNhat, maTrongTieuDe, CUA_SO_LIEN_QUAN } = require(path.join(OUT, 'vnfilter.js'))

let hong = 0
const bao = (ok, nhan, them = '') => {
  if (!ok) hong++
  console.log(`${ok ? '  ok  ' : '  HONG'} ${nhan}${them ? ' — ' + them : ''}`)
}

// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== 1. BẮT NHẦM trên tiêu đề THẬT (bằng chứng chắc) ===')
const that = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/vn-titles.json'), 'utf8'))
const nham = that.filter(laPhuKienVn)
nham.forEach((t) => console.log('       !! ' + t.slice(0, 88)))
bao(nham.length === 0, `0/${that.length} bắt nhầm`, nham.length ? `còn ${nham.length}` : '')

// Cái bẫy cụ thể: 16 dòng chứa chữ "dây" mà đều là chuột KHÔNG DÂY thật.
const coDay = that.filter((t) => /\bdây\b/i.test(t))
bao(coDay.length > 0 && coDay.every((t) => !laPhuKienVn(t)),
    `${coDay.length} dòng chứa "dây" đều không bị gắn cờ`)

// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== 2. BẮT ĐỦ trên bộ TỰ VIẾT (chỉ là gợi ý, không phải bằng chứng) ===')
const phuKien = [
  'Miếng lót chuột G102 cỡ lớn chống trượt',
  'Bàn di chuột Logitech G102 G304 chống trượt',
  'Ốp silicon dành cho chuột Logitech G304',
  'Keycap thay thế cho bàn phím Logitech K380',
  'Cánh quạt thay thế dùng cho quạt cầm tay F200',
  'Dây sạc Type-C cho quạt mini TS3429',
  'Miếng dán skin chuột G304 chống mồ hôi',
  'Feet chuột Logitech G304 Teflon trượt êm',
  'Combo phụ kiện chuột G102 gồm lót và feet',
  'Lưới lọc thay thế cho quạt Tiross TS3429',
]
const sot = phuKien.filter((t) => !laPhuKienVn(t))
sot.forEach((t) => console.log('       SÓT ' + t.slice(0, 88)))
bao(sot.length === 0, `bắt ${phuKien.length - sot.length}/${phuKien.length}`)


// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== 3. CHỌN GIÁ trên 179 dòng Shopee THẬT ===')
const shopee = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/shopee-vn.json'), 'utf8'))

// `truoc` là con số công cụ ĐANG in ra trước bản vá này; `tu`-`den` là vùng giá thật đọc từ
// ảnh chụp Shopee của người dùng. KHÔNG nhắm trúng một con số — người dùng đã nói rõ đây là
// công cụ ước lượng, không phải thứ phải chuẩn 100%. Nhắm vào đúng vùng là đủ.
const canh = [
  { ma: 'G304', truoc: 58_147, tu: 85_000, den: 300_000 },
  { ma: 'G102', truoc: 84_000, tu: 100_000, den: 300_000 },
  { ma: 'G305', truoc: 789_000, tu: 700_000, den: 900_000 },
]

for (const c of canh) {
  const r = chonGiaThapNhat(shopee[c.ma], c.ma)
  const trong = r.price !== null && r.price >= c.tu && r.price <= c.den
  console.log(
    `  ${c.ma}: ${c.truoc.toLocaleString('vi-VN')} → ${r.price?.toLocaleString('vi-VN')} ₫ ` +
    `(bỏ ${r.skipped}, dùng ${r.used})`,
  )
  bao(trong, `${c.ma} nằm trong ${c.tu.toLocaleString('vi-VN')}–${c.den.toLocaleString('vi-VN')} ₫`)

  // Cột giá bấm thẳng vào SẢN PHẨM, nên dòng thắng phải mang link — và phải là link sản
  // phẩm thật, không phải một trang tìm kiếm.
  const link = r.winner && r.winner.link
  bao(!!link && /shopee\.vn\/product\//.test(link),
      `${c.ma} có link thẳng tới sản phẩm`, String(link).slice(0, 52))
  bao(r.winner && r.winner.priceValue === r.price, `${c.ma}: link khớp đúng dòng mang giá đó`)
}

// Ba thứ kéo giá xuống sai — mỗi thứ phải bị ĐÚNG một luật bắt, không phải tình cờ đúng.
const g304 = chonGiaThapNhat(shopee.G304, 'G304')
const gopMa = g304.rows.find((r) => (r.title || '').includes('M220/M350/G304'))
bao(gopMa && gopMa.vnSkip === 'ma-khac',
    'dòng gộp M220/M350/G304 (58.147 ₫, hạng 6) bị bắt vì "mã khác"',
    gopMa ? String(gopMa.vnSkip) : 'không thấy dòng')

const g102 = chonGiaThapNhat(shopee.G102, 'G102')
const nhai = g102.rows.find((r) => r.priceValue === 19_000)
bao(nhai && nhai.vnSkip === 'gia-lac',
    'hàng nhái 19.000 ₫ (hạng 3, tiêu đề không có gì đáng ngờ) bị bắt vì "giá lạc"',
    nhai ? String(nhai.vnSkip) : 'không thấy dòng')

// Dòng ngoài cửa sổ liên quan KHÔNG được gắn cờ: chúng không sai, chỉ là không đủ liên quan
// để tin. Gắn cờ chúng sẽ thổi con số "đã bỏ" lên tới bốn chục và làm tooltip vô nghĩa.
const ngoai = g304.rows.slice(CUA_SO_LIEN_QUAN).filter((r) => r.vnSkip)
bao(ngoai.length === 0, 'dòng ngoài cửa sổ liên quan không bị gắn cờ', `còn ${ngoai.length}`)

// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== 4. RÚT MÃ khớp bản Python ở backend (codes.py) ===')
const caMa = [
  ['Chuột không dây Logiteck M220/M350/G304 bluetooth', ['M220', 'M350', 'G304']],
  ['Chuột Gaming Không Dây Logitech G304 Lightspeed', ['G304']],
  ['Chuột gaming Logitech G102/G304/G402 có dây', ['G102', 'G304', 'G402']],
]
for (const [t, mong] of caMa) {
  const duoc = maTrongTieuDe(t)
  bao(mong.every((m) => duoc.includes(m)), `rút được ${mong.join(', ')}`, `ra: ${duoc.join(', ')}`)
}

// -----------------------------------------------------------------------------
console.log('')
console.log('=== 5. KHÔNG LUẬT NÀO ĐƯỢC LỌC ĐẾN RỖNG ===')
// Đã xảy ra thật, người dùng chụp màn hình: G305 hay được bán kèm G304 trong cùng một
// tiêu đề, nên luật "mã khác" gạch sạch cả bảng, `price` thành null, và giao diện in ra
// "không có ở sàn Việt" cho một món đang bày bán đầy trên Shopee.
// Thà giữ một con số kém chắc còn hơn tuyên bố một điều sai.
const deuNhacMaKhac = [
  { title: 'Chuột Logitech G304/G305 không dây chính hãng', priceValue: 700000, codeHit: true, link: 'https://shopee.vn/product/1/1' },
  { title: 'Chuột G305 và G304 Lightspeed bản quốc tế', priceValue: 800000, codeHit: true, link: 'https://shopee.vn/product/2/2' },
]
const r5 = chonGiaThapNhat(deuNhacMaKhac, 'G305')
bao(r5.price === 700000, 'vẫn ra giá thay vì null', `ra ${r5.price}`)
bao(r5.noiLong.includes('ma-khac'), 'nói ra là đã phải tắt luật "mã khác"', JSON.stringify(r5.noiLong))
bao(!!r5.winner && !!r5.winner.link, 'vẫn giữ được link sản phẩm')

// Thật sự KHÔNG có dòng nào mang mã -> null MỚI đúng, và đó mới là câu "không có ở sàn Việt".
const khongCo = chonGiaThapNhat(
  [{ title: 'Chuột Logitech G102 chính hãng', priceValue: 289000, codeHit: false }],
  'G305',
)
bao(khongCo.price === null && khongCo.noiLong.length === 0,
    'không dòng nào mang mã thì null mới đúng')

// Nới lỏng không được lây sang lượt bình thường.
for (const maX of ['G304', 'G102', 'G305']) {
  const rX = chonGiaThapNhat(shopee[maX], maX)
  bao(rX.noiLong.length === 0, `${maX}: dữ liệu thật vẫn chạy đủ cả ba luật`, JSON.stringify(rX.noiLong))
}

console.log(hong === 0 ? '\n>>> TAT CA DAT\n' : `\n>>> ${hong} PHEP DO HONG\n`)
process.exit(hong === 0 ? 0 : 1)
