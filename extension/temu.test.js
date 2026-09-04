// Kiểm phần gợi ý từ khoá Temu: bộ chống treo và bộ đọc gợi ý.
//
// Chạy:  node extension/temu.test.js
//
// Nạp `background.js` vào sandbox với chrome API giả — không cần Chrome, không cần Temu.
//
// Ca đáng giá nhất ở đây là "lời gọi treo vô hạn". Đo 2026-09-04: một job gợi ý Temu chạy quá
// 90 giây dù đã đặt ngân sách 70 giây, vì `chrome.scripting.executeScript` KHÔNG có hạn giờ và
// mọi chỗ kiểm ngân sách đều nằm SAU nó — lời gọi treo thì không bao giờ tới được chỗ kiểm.
// Sửa xong thì phải có test giữ, nếu không lần refactor sau nó lặng lẽ quay lại.

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, 'background.js'), 'utf8');

const chrome = {
  runtime: { onMessage: { addListener() {} } },
  cookies: { get() {} },
  scripting: {
    getRegisteredContentScripts: async () => [],
    registerContentScripts: async () => {},
    executeScript: async () => [{ result: null }],
  },
  storage: { session: { get: async () => ({}), set: async () => {} } },
  alarms: { get: async () => null, create() {}, onAlarm: { addListener() {} } },
  windows: { update: async () => {} },
  tabs: {
    onUpdated: { addListener() {}, removeListener() {} },
    onRemoved: { addListener() {} },
    create: async () => ({ id: 1, url: 'about:blank' }),
    get: async () => ({ id: 1, url: 'about:blank' }),
    update: async () => ({ id: 1 }),
    remove: async () => {},
    query: async () => [],
  },
};

const g = vm.createContext({ chrome, console, setTimeout, clearTimeout, Date, URL, Promise });
vm.runInContext(src, g, { filename: 'background.js' });

let failures = 0;
function check(label, ok, detail) {
  if (ok) console.log(`  OK   ${label}`);
  else { failures++; console.log(`  HỎNG ${label}${detail ? ' — ' + detail : ''}`); }
}

(async () => {
  console.log('Temu: chống treo + đọc gợi ý');

  // --- withTimeout: cái chặn duy nhất giữa ta và một job treo vĩnh viễn ---
  const t0 = Date.now();
  const hung = await g.withTimeout(new Promise(() => {}), 60, 'BỎ-DỞ');
  check('lời gọi treo vô hạn → vẫn trả về', hung === 'BỎ-DỞ');
  check('và trả về ĐÚNG HẠN, không chờ thêm', Date.now() - t0 < 1000, `mất ${Date.now() - t0}ms`);

  check('lời gọi ném lỗi → trả fallback, không ném ra ngoài',
    (await g.withTimeout(Promise.reject(new Error('vỡ')), 500, 'FB')) === 'FB');
  check('lời gọi xong sớm → giữ nguyên kết quả thật',
    (await g.withTimeout(Promise.resolve('THẬT'), 500, 'FB')) === 'THẬT');

  // --- evalInTab: cùng cái bẫy, ở tầng hay dùng nhất ---
  chrome.scripting.executeScript = () => new Promise(() => {}); // treo vĩnh viễn
  const t1 = Date.now();
  const r = await g.evalInTab(1, () => 1, [], 80);
  check('evalInTab khi trang treo → trả null chứ không treo theo', r === null);
  check('evalInTab tôn trọng hạn giờ', Date.now() - t1 < 1000, `mất ${Date.now() - t1}ms`);
  chrome.scripting.executeScript = async () => [{ result: null }];

  // --- parseTemuSuggest: đọc gợi ý mà không chốt cứng cấu trúc ---
  const nested = JSON.stringify({
    result: { items: [{ query: 'váy nữ' }, { keyword: 'váy dài' }, { text: 'váy' }] },
  });
  check('đọc được gợi ý ở khoá lồng nhiều tầng',
    JSON.stringify(g.parseTemuSuggest(nested)) === JSON.stringify(['váy nữ', 'váy dài', 'váy']));

  check('bỏ chuỗi quá dài (tiêu đề sản phẩm, không phải cụm tìm kiếm)',
    g.parseTemuSuggest(JSON.stringify({ query: 'x'.repeat(80) })).length === 0);
  check('bỏ URL',
    g.parseTemuSuggest(JSON.stringify({ query: 'https://temu.com/abc' })).length === 0);
  check('bỏ trùng, không phân biệt hoa thường',
    g.parseTemuSuggest(JSON.stringify([{ query: 'Váy' }, { query: 'váy' }])).length === 1);
  check('JSON hỏng → mảng rỗng, không ném lỗi',
    Array.isArray(g.parseTemuSuggest('{không phải json')) && g.parseTemuSuggest('{x').length === 0);
  check('bỏ qua khoá không liên quan',
    g.parseTemuSuggest(JSON.stringify({ price: '199', goodsId: '123' })).length === 0);

  console.log();
  if (failures) { console.log(`${failures} kiểm tra HỎNG`); process.exit(1); }
  console.log('TẤT CẢ KIỂM TRA ĐỀU QUA');
})().catch((e) => { console.error('THẤT BẠI:', e.message); process.exit(1); });
