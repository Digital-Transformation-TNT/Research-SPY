// Kiểm tra vòng đời tab của background.js: giữ tab, hạ nhiệt, dọn tab rảnh, gộp tab xác minh.
//
// Chạy:  node extension/tabs.test.js
//
// Nạp ``background.js`` vào sandbox với một bản chrome API giả — không cần Chrome, không cần
// đăng nhập sàn nào. Chỉ phủ phần quản lý tab; phần bóc dữ liệu của từng sàn vẫn phải thử tay
// qua popup, vì nó phụ thuộc HTML thật của sàn.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const src = fs.readFileSync(require('path').join(__dirname, 'background.js'), 'utf8');

let nextId = 100;
const tabs = new Map();          // id -> {id, url, active}
const sessionStore = {};
const created = [];              // log mọi lần tabs.create
const removed = [];
let alarm = null;
const onRemovedCbs = [];

const chrome = {
  runtime: { onMessage: { addListener() {} } },
  cookies: { get() {} },
  scripting: {
    getRegisteredContentScripts: async () => [],
    registerContentScripts: async () => {},
    executeScript: async () => [{ result: null }],
  },
  storage: {
    session: {
      get: async (k) => ({ [k]: sessionStore[k] }),
      set: async (o) => Object.assign(sessionStore, o),
    },
  },
  alarms: {
    get: async () => alarm,
    create: (name, opts) => { alarm = { name, ...opts }; },
    onAlarm: { addListener() {} },
  },
  windows: { update: async () => {} },
  tabs: {
    onUpdated: { addListener() {}, removeListener() {} },
    onRemoved: { addListener: (cb) => onRemovedCbs.push(cb) },
    create: async ({ url, active }) => {
      const t = { id: nextId++, url, active: !!active };
      tabs.set(t.id, t);
      created.push({ id: t.id, url });
      return t;
    },
    get: async (id) => {
      const t = tabs.get(id);
      if (!t) throw new Error('No tab with id: ' + id);
      return t;
    },
    update: async (id, props) => {
      const t = tabs.get(id);
      if (!t) throw new Error('No tab with id: ' + id);
      Object.assign(t, props);
      return t;
    },
    remove: async (id) => {
      if (!tabs.has(id)) throw new Error('No tab with id: ' + id);
      tabs.delete(id);
      removed.push(id);
    },
    query: async ({ url }) => {
      const host = url.replace('https://', '').replace('/*', '');
      return [...tabs.values()].filter((t) => (t.url || '').startsWith(`https://${host}/`));
    },
  },
};

const ctx = vm.createContext({ chrome, console, setTimeout, clearTimeout, Date, URL });
vm.runInContext(src, ctx, { filename: 'background.js' });
const g = ctx;

// Lùi `usedAt` của mọi slot về quá khứ, để giả lập "đã rảnh lâu".
function ageAllSlots(ms) {
  const store = sessionStore['rs-kept-tabs'];
  for (const k of Object.keys(store)) store[k].usedAt -= ms;
}

(async () => {
  // 1. Tab thường trú: gọi hai lần chỉ mở MỘT tab.
  const a1 = await g.keptTab('amazon');
  const a2 = await g.keptTab('amazon');
  assert.strictEqual(a1.id, a2.id, 'keptTab phải trả lại đúng tab cũ');
  assert.strictEqual(created.length, 1, 'không được mở tab thứ hai');
  console.log('✓ keptTab dùng lại tab, không đẻ thêm');

  // 2. Hạ nhiệt: trang nặng → about:blank, tab vẫn còn.
  await chrome.tabs.update(a1.id, { url: 'https://www.amazon.com/s?k=abc' });
  await g.coolTab('amazon');
  assert.strictEqual(tabs.get(a1.id).url, 'about:blank', 'phải hạ về trang trống');
  assert.ok(tabs.has(a1.id), 'tab không được đóng khi hạ nhiệt');
  console.log('✓ coolTab bỏ trang nặng nhưng giữ tab');

  // 3. Đang bận thì KHÔNG được dọn, dù đã quá hạn rảnh.
  let release;
  const job = new Promise((r) => { release = r; });
  const wrapped = g.withCooldown('amazon', job);
  ageAllSlots(60 * 60_000);
  await g.reapTabs();
  assert.ok(tabs.has(a1.id), 'tab đang chạy job không được đóng');
  console.log('✓ reapTabs tha tab đang bận');

  // 4. Job xong → hết bận, và lần dọn sau đóng thật.
  release();
  await wrapped;
  ageAllSlots(60 * 60_000);
  await g.reapTabs();
  assert.ok(!tabs.has(a1.id), 'tab rảnh lâu phải bị đóng');
  assert.deepStrictEqual(removed, [a1.id]);
  console.log('✓ reapTabs đóng tab rảnh lâu');

  // 5. Đóng rồi thì lần gọi sau tự mở lại.
  const a3 = await g.keptTab('amazon');
  assert.notStrictEqual(a3.id, a1.id);
  console.log('✓ tab tự mở lại sau khi bị dọn');

  // 6. Tab đang hiện trước được tha (người vận hành đang giải slider).
  await chrome.tabs.update(a3.id, { active: true });
  ageAllSlots(60 * 60_000);
  await g.reapTabs();
  assert.ok(tabs.has(a3.id), 'tab đang hiện trước không được đóng');
  await chrome.tabs.update(a3.id, { active: false });
  console.log('✓ reapTabs tha tab đang hiện trước');

  // 7. Tab xác minh: mười lần bị chặn vẫn chỉ MỘT tab.
  const before = created.length;
  for (let i = 0; i < 10; i++) await g.openVerifyTab('verify:1688', 'https://s.1688.com/?n=' + i);
  assert.strictEqual(created.length - before, 1, 'chỉ được mở một tab xác minh');
  console.log('✓ openVerifyTab gộp về một tab (10 lần chặn → 1 tab)');

  // 8. ensureTab: tab đã hạ nhiệt phải được đưa về đúng origin, không mở tab mới.
  const s1 = await g.ensureTab('shopee.vn');
  assert.strictEqual(s1.url, 'https://shopee.vn/');
  await g.coolTab('site:shopee.vn');
  assert.strictEqual(tabs.get(s1.id).url, 'about:blank');
  const n = created.length;
  const s2 = await g.ensureTab('shopee.vn');
  assert.strictEqual(s2.id, s1.id, 'phải dùng lại tab cũ, không mở tab mới');
  assert.strictEqual(tabs.get(s1.id).url, 'https://shopee.vn/', 'phải đưa về đúng origin');
  assert.strictEqual(created.length, n, 'không được mở thêm tab');
  console.log('✓ ensureTab đưa tab đã hạ nhiệt về lại origin, không đẻ tab');

  // 9. Người dùng tự đóng tab → slot phải quên ngay.
  const id = s1.id;
  await chrome.tabs.remove(id);
  for (const cb of onRemovedCbs) await cb(id);
  assert.ok(!sessionStore['rs-kept-tabs']['site:shopee.vn'], 'slot phải bị xoá');
  console.log('✓ onRemoved xoá slot khi người dùng tự đóng tab');

  console.log('\nTẤT CẢ 9 KIỂM TRA ĐỀU QUA');
})().catch((e) => { console.error('THẤT BẠI:', e.message); process.exit(1); });
