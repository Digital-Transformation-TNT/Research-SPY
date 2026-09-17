// Kiểm phần TÌM SẢN PHẨM Taobao sau khi chuyển sang lối KÝ SINH (trang tự gọi mtop, ta chộp response).
//
// Chạy:  node extension/taobao-search.test.js
//
// Nạp `background.js` vào sandbox với chrome API giả — không cần Chrome, không cần Taobao.
//
// BA CA ĐÁNG GIÁ, và cả ba đều là thứ bản cũ làm sai:
//   1. Chưa đăng nhập → phải nói ĐÚNG là "đòi đăng nhập". Đo 16/09/2026 trên phiên chưa đăng nhập,
//      s.taobao.com dựng đủ vỏ trang nhưng đứng ở "加载中..." với 0 sản phẩm — nếu hàm trả bảng rỗng
//      không kèm lý do thì người dùng đi sửa sai chỗ (bản cũ báo "Baxia", thật ra chỉ cần đăng nhập).
//   2. Baxia (RGV587) → phải nói ĐÚNG là Baxia, vì cách sửa khác hẳn ca 1 (giải slider, không phải
//      đăng nhập).
//   3. Trang render sản phẩm mà KHÔNG phát thêm lượt mtop nào → vẫn phải ra hàng, nhờ đường đọc DOM.
//      Trả bảng rỗng trong khi màn hình đầy sản phẩm là kiểu sai khó tin nhất.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, 'background.js'), 'utf8');

//: Response mtop giả, đúng hình dạng trang đời mới dùng: `itemId` + `priceShow` + `realSales`.
function mtopGia(n) {
  return JSON.stringify({
    api: 'mtop.taobao.wsearch.h5search', ret: ['SUCCESS::调用成功'],
    data: { itemsArray: Array.from({ length: n }, (_, k) => ({
      itemId: `i${k}`, title: `连衣裙 ${k}`, priceShow: `${19 + k}.90`,
      realSales: k === 0 ? '2.3万' : `${100 + k}`,
      pic: `//img.alicdn.com/${k}.jpg`, nick: `Shop ${k}`,
    })) },
  });
}

//: Một "trang" giả. `che` quyết định trang đang ở trạng thái nào.
function trangGia(che, soSP = 20) {
  return {
    che,
    docTrang() {
      if (this.che === 'mtop') return { cap: [mtopGia(soSP)], s: 200, loi: '', href: 'https://s.taobao.com/search', login: false, dom: [] };
      if (this.che === 'login') return { cap: [], s: 0, loi: '', href: 'https://s.taobao.com/search', login: true, dom: [] };
      if (this.che === 'baxia') return { cap: [], s: 200, loi: 'RGV587_ERROR::SM::哎哟喂,被挤爆啦', href: 'https://s.taobao.com/search', login: false, dom: [] };
      if (this.che === 'dom') return { cap: [], s: 0, loi: '', href: 'https://s.taobao.com/search', login: false,
        dom: Array.from({ length: soSP }, (_, k) => ({
          id: `d${k}`, title: `连衣裙 DOM ${k}`, img: `//img.alicdn.com/d${k}.jpg`,
          giaChu: `${30 + k}.00`, banChu: k === 0 ? '1.5万' : `${200 + k}`,
        })) };
      return { cap: [], s: 0, loi: '', href: 'https://s.taobao.com/search', login: false, dom: [] };
    },
  };
}

function taoSandbox(trang) {
  const chrome = {
    runtime: { onMessage: { addListener() {} } },
    cookies: { get() {} },
    scripting: {
      getRegisteredContentScripts: async () => [],
      registerContentScripts: async () => {},
      executeScript: async (opt) => {
        const f = String(opt.func);
        if (/prototype\.open/.test(f)) return [{ result: true }];        // cài hook + gõ Enter
        if (/item\.taobao\.com/.test(f)) return [{ result: trang.docTrang() }]; // vòng chờ
        return [{ result: null }];
      },
    },
    storage: { session: { get: async () => ({}), set: async () => {} } },
    alarms: { get: async () => null, create() {}, onAlarm: { addListener() {} } },
    windows: { update: async () => {} },
    tabs: {
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

(async () => {
  console.log('Taobao: đọc response mtop mà trang tự gọi');
  {
    const g = taoSandbox(trangGia('mtop'));
    const r = await g.searchTaobao('连衣裙', 20);
    check('ra đủ 20 SP', r.items.length === 20, `ra ${r.items.length}`);
    check('không bị đánh dấu chặn', r.blocked === false);
    check('đọc được tên', r.items[0].name === '连衣裙 0', r.items[0].name);
    check('đọc được giá từ `priceShow`', r.items[0].price === 19.9, String(r.items[0].price));
    check('quy đổi 万 → 23000', r.items[0].monthly === 23000, String(r.items[0].monthly));
    check('ảnh được thêm https:', r.items[0].image.startsWith('https://'), r.items[0].image);
  }

  console.log('Taobao: chưa đăng nhập thì nói đúng là đăng nhập');
  {
    const g = taoSandbox(trangGia('login'));
    const r = await g.searchTaobao('连衣裙', 20);
    check('không trả SP', r.items.length === 0);
    check('đánh dấu blocked', r.blocked === true);
    check('lý do nói "đăng nhập"', /đăng nhập/.test(r.error || ''), r.error);
    check('KHÔNG đổ oan cho Baxia', !/Baxia|RGV587/.test(r.error || ''), r.error);
  }

  console.log('Taobao: Baxia thì nói đúng là Baxia');
  {
    const g = taoSandbox(trangGia('baxia'));
    const r = await g.searchTaobao('连衣裙', 20);
    check('đánh dấu blocked', r.blocked === true);
    check('lý do nhắc RGV587', /RGV587|Baxia/.test(r.error || ''), r.error);
    check('bảo giải slider chứ không bảo đăng nhập', /slider/.test(r.error || ''), r.error);
  }

  console.log('Taobao: trang đã render SP nhưng không phát lượt mtop nào');
  {
    const g = taoSandbox(trangGia('dom'));
    const r = await g.searchTaobao('连衣裙', 20);
    check('vẫn ra hàng nhờ đọc DOM', r.items.length === 20, `ra ${r.items.length}`);
    check('không báo chặn oan', r.blocked === false);
    check('đọc được giá từ chữ trên màn hình', r.items[0].price === 30, String(r.items[0].price));
    check('quy đổi 万 ở nhánh DOM → 15000', r.items[0].monthly === 15000, String(r.items[0].monthly));
  }

  console.log('Taobao: không có gì cả → vẫn phải nói một lý do');
  {
    const g = taoSandbox(trangGia('trong'));
    const r = await g.searchTaobao('连衣裙', 20);
    check('đánh dấu blocked', r.blocked === true);
    check('có câu lý do, không im lặng', !!(r.error || '').length, r.error);
  }

  console.log(failures ? `\n${failures} kiểm tra HỎNG` : '\nTất cả đều đạt');
  process.exit(failures ? 1 : 0);
})();
