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
 *   BẮT ĐỦ    đo trên một bộ tiêu đề TỰ VIẾT theo đúng những gì người dùng mô tả (lót chuột,
 *             keycap, cánh quạt). KHÔNG phải dữ liệu thật — bảng Shopee gây ra lỗi này nằm
 *             trong bộ nhớ chứ không xuống đĩa, nên chưa lấy mẫu thật được. Nghĩa là con số
 *             "bắt đủ" ở đây KHÔNG chứng minh luật chạy tốt ngoài đời. Khi nào có mẫu Shopee
 *             thật thì thay bộ này đi.
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
const { laPhuKienVn, chonGiaThapNhat, TY_GIA_VND } = require(path.join(OUT, 'vnfilter.js'))

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
console.log('\n=== 3. ĐÚNG CẢNH TRONG ẢNH NGƯỜI DÙNG GỬI ===')
// Giá sỉ 1688 đọc thẳng từ ảnh: G304 ¥29, G102 ¥23,76, "305 không dây" ¥49.
const yen = TY_GIA_VND['¥']
const canh = [
  {
    ma: 'G102',
    san: 23.76 * yen,
    truoc: 19_000,          // con số công cụ ĐANG in ra — sai
    rows: [
      { title: 'Miếng lót chuột G102 chống trượt cỡ lớn', priceValue: 19_000, codeHit: true },
      { title: 'Chuột Logitech G102 Lightsync RGB chính hãng', priceValue: 289_000, codeHit: true },
      { title: 'Chuột gaming G102 2nd Gen 8000DPI', priceValue: 315_000, codeHit: true },
      { title: 'Bàn phím cơ AKKO 3068', priceValue: 890_000, codeHit: false },
    ],
    mong: 289_000,
  },
  {
    ma: 'G304',
    san: 29 * yen,
    truoc: 40_000,
    rows: [
      { title: 'Miếng dán skin chuột G304 chống mồ hôi', priceValue: 40_000, codeHit: true },
      { title: 'Chuột Gaming không dây Logitech G304 Lightspeed', priceValue: 835_000, codeHit: true },
      { title: 'Chuột Logitech G304 | Giá tốt cho game thủ', priceValue: 872_000, codeHit: true },
    ],
    mong: 835_000,
  },
  {
    ma: 'G305',
    san: 49 * yen,
    truoc: 595_000,         // con số này vốn ĐÚNG — luật không được đụng vào
    rows: [
      { title: 'Chuột Gaming không dây Logitech G305 Lightspeed chính hãng', priceValue: 595_000, codeHit: true },
      { title: 'Chuột Logitech G305 bản quốc tế', priceValue: 749_000, codeHit: true },
    ],
    mong: 595_000,
  },
]

for (const c of canh) {
  const r = chonGiaThapNhat(c.rows, c.san)
  const doi = r.price !== c.truoc
  console.log(
    `  ${c.ma}: sàn ${Math.round(c.san).toLocaleString('vi-VN')} ₫ · ` +
    `trước ${c.truoc.toLocaleString('vi-VN')} → sau ${r.price?.toLocaleString('vi-VN')} ₫ ` +
    `(bỏ ${r.skipped}) ${doi ? '[đã sửa]' : '[giữ nguyên]'}`,
  )
  bao(r.price === c.mong, `${c.ma} ra đúng ${c.mong.toLocaleString('vi-VN')} ₫`)
}

// ─────────────────────────────────────────────────────────────────────────────
console.log('\n=== 4. KHÔNG CÓ SÀN GIÁ thì luật giá phải TẮT, không bịa ===')
const khongSan = chonGiaThapNhat(
  [
    { title: 'Chuột Logitech G102 chính hãng', priceValue: 289_000, codeHit: true },
    { title: 'Miếng lót chuột G102', priceValue: 19_000, codeHit: true },
  ],
  null,
)
// Luật chữ vẫn bắt được miếng lót; luật giá không chạy nên không bỏ thêm gì.
bao(khongSan.price === 289_000 && khongSan.skipped === 1,
    'chỉ luật chữ làm việc', `giá=${khongSan.price} bỏ=${khongSan.skipped}`)

// Dòng KHÔNG mang mã thì không được đụng tới — việc lọc mã là của `rowMatches`.
const ngoaiMa = chonGiaThapNhat(
  [{ title: 'Miếng lót chuột loại rẻ', priceValue: 5_000, codeHit: false }],
  100_000,
)
bao(ngoaiMa.price === null && ngoaiMa.skipped === 0, 'dòng không mang mã: không tính, không gắn cờ')

console.log(hong === 0 ? '\n>>> TAT CA DAT\n' : `\n>>> ${hong} PHEP DO HONG\n`)
process.exit(hong === 0 ? 0 : 1)
