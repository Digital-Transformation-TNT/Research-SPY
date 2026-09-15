// Kiểm phần TÌM SẢN PHẨM Temu: gộp nhiều trang + khử trùng, và cuộn lấy thêm trang cho đủ `count`.
//
// Chạy:  node extension/temu-search.test.js
//
// Nạp `background.js` vào sandbox với chrome API giả — không cần Chrome, không cần Temu. Trang Temu
// giả ở đây trả 40 SP một trang và chỉ nhả trang kế khi bị cuộn, đúng như trang thật đo 15/09/2026.
//
// Ca đáng giá nhất: chọn 60 SP mà chỉ ra 40. Bản cũ dừng ở response đầu tiên ở HAI chỗ (vòng chờ của
// `searchTemu` và `parseTemuTexts`), nên trang hai không bao giờ được tải lẫn được đọc. Sửa một chỗ mà
// quên chỗ kia thì vẫn ra 40 — test giữ cả hai.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, 'background.js'), 'utf8');

// ── Trang Temu giả: `soTrang` trang, mỗi trang `moiTrang` SP; cuộn một lần nhả thêm một trang. ──
function trangGia(soTrang, moiTrang = 40) {
  const trang = (i) => JSON.stringify({ result: { data: { goods_list: Array.from({ length: moiTrang }, (_, k) => ({
    goods_id: `g${i}-${k}`, title: `SP ${i}-${k}`,
    price_info: { price_str: '$1.99', currency: 'USD' }, sales_num: '1K+',
  })) } } });
  const s = { daNha: 1, soLanCuon: 0, caps: [] };
  // Mỗi response bị HAI hook cùng chộp — mô phỏng đúng cái làm bản cũ phải dừng sớm để khỏi đếm đôi.
  s.docCaps = () => Array.from({ length: s.daNha }, (_, i) => [trang(i), trang(i)]).flat();
  s.cuon = () => { s.soLanCuon++; if (s.daNha < soTrang) s.daNha++; };
  return s;
}

function taoSandbox(temu) {
  const chrome = {
    runtime: { onMessage: { addListener() {} } },
    cookies: { get() {} },
    scripting: {
      getRegisteredContentScripts: async () => [],
      registerContentScripts: async () => {},
      executeScript: async (opt) => {
        const f = String(opt.func);
        if (/prototype\.open/.test(f)) return [{ result: true }];                 // cài hook + gõ Enter
        if (/scrollTo/.test(f)) { temu.cuon(); return [{ result: true }]; }       // cuộn lấy trang kế
        if (/href:\s*location\.href/.test(f)) {                                    // vòng chờ response đầu
          return [{ result: { a: temu.docCaps(), b: [], href: 'https://www.temu.com/search_result.html', s: 200 } }];
        }
        if (/concat/.test(f)) return [{ result: temu.docCaps() }];                // temuDocLuoi
        return [{ result: null }];
      },
    },
    storage: { session: { get: async () => ({}), set: async () => {} } },
    alarms: { get: async () => null, create() {}, onAlarm: { addListener() {} } },
    windows: { update: async () => {} },
    tabs: {
      // Bắn `complete` ngay, không thì `waitForComplete` treo đủ 16 giây mỗi lần gọi.
      onUpdated: { addListener(fn) { setTimeout(() => fn(1, { status: 'complete' }), 0); }, removeListener() {} },
      onRemoved: { addListener() {} },
      create: async () => ({ id: 1, url: 'about:blank' }),
      get: async () => ({ id: 1, url: 'about:blank' }),
      update: async () => ({ id: 1 }),
      remove: async () => {},
      query: async () => [],
    },
  };
  const g = vm.createContext({ chrome, console, setTimeout, clearTimeout, Date, URL, Promise });
  g.importScripts = (...files) => { for (const f of files) vm.runInContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), g, { filename: f }); };
  vm.runInContext(src, g, { filename: 'background.js' });
  return g;
}

let failures = 0;
function check(label, ok, detail) {
  if (ok) console.log(`  OK   ${label}${detail ? ' — ' + detail : ''}`);
  else { failures++; console.log(`  HỎNG ${label}${detail ? ' — ' + detail : ''}`); }
}
const khongTrung = (items) => new Set(items.map((x) => x.id)).size === items.length;

(async () => {
  console.log('Temu: gộp trang + khử trùng');
  {
    const t = trangGia(3);
    t.daNha = 2;
    const g = taoSandbox(t);
    const items = g.parseTemuTexts(t.docCaps(), 60);
    check('2 trang (mỗi trang bị chộp đôi) → đủ 60 SP', items.length === 60, `ra ${items.length}`);
    check('không SP nào bị đếm hai lần', khongTrung(items));
    const mot = g.parseTemuTexts(trangGia(1).docCaps(), 60);
    check('1 trang chộp đôi → 40, không phải 80', mot.length === 40, `ra ${mot.length}`);
  }

  console.log('Temu: cuộn lấy thêm trang cho đủ count');
  {
    const t = trangGia(3);
    const g = taoSandbox(t);
    const r = await g.searchTemu('phone case', 60);
    check('chọn 60 SP, Temu còn hàng → ra đủ 60', r.items.length === 60, `ra ${r.items.length}, ${r.trang} trang`);
    check('có cuộn để lấy trang kế', t.soLanCuon >= 1, `cuộn ${t.soLanCuon} lần`);
    check('không trùng SP', khongTrung(r.items));
  }
  {
    const t = trangGia(3);
    const g = taoSandbox(t);
    const r = await g.searchTemu('phone case', 40);
    check('chọn 40 SP → trang đầu đã đủ, KHÔNG cuộn thừa', r.items.length === 40 && t.soLanCuon === 0,
      `ra ${r.items.length}, cuộn ${t.soLanCuon} lần`);
  }
  {
    const t = trangGia(1);                      // từ khoá chỉ có đúng 40 SP
    const g = taoSandbox(t);
    const t0 = Date.now();
    const r = await g.searchTemu('hiem', 60);
    const giay = (Date.now() - t0) / 1000;
    check('từ khoá chỉ có 40 SP → trả 40, không bịa thêm', r.items.length === 40, `ra ${r.items.length}`);
    check('và DỪNG khi hết trang, không ngồi đợi hết ngân sách 48s', giay < 12, `mất ${giay.toFixed(1)}s`);
  }

  if (failures) { console.log(`${failures} kiểm tra HỎNG`); process.exit(1); }
  console.log('Tất cả đạt.');
})().catch((e) => { console.error('THẤT BẠI:', e.stack || e.message); process.exit(1); });
