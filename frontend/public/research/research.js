/*
 * Trang research đầy đủ — mở dạng full tab.
 *
 * Lấy nhiều TỪ KHOÁ cùng lúc (mỗi từ khoá nhiều trang, sort bán chạy) qua service worker,
 * chuẩn hoá theo format 2026, XẾP HẠNG theo công thức backend (cầu 60% + chất lượng 40%),
 * rồi hiện một bảng gộp có cột Từ khoá + Sàn để so sánh. Chấm điểm phản chiếu
 * `backend/lib/ads/scoring.py::_score_product` — sửa một bên nhớ sửa bên kia.
 *
 * Đa sàn: Shopee + TikTok Shop (Cách A, fetch trong tab đăng nhập), Amazon (công khai, scrape DOM),
 * Etsy/Facebook (qua backend). Thêm sàn = viết một adapter fetch/parse riêng trong fetchFor + thêm
 * domain vào host_permissions; cột "Sàn" đã sẵn cho việc đó.
 */

/*
 * ĐÓNG GÓI TOÀN BỘ FILE TRONG MỘT HÀM. Bắt buộc, không phải cho gọn:
 *
 * Trình duyệt Chrome tự tạo sẵn `window.chrome` cho mọi trang. Ở phạm vi script, `const chrome`
 * đụng đúng cái tên đó và ném `Identifier 'chrome' has already been declared` — lỗi xảy ra lúc
 * KHỞI TẠO script, nên KHÔNG một dòng nào trong file chạy. Triệu chứng rất dễ chẩn đoán nhầm:
 * trang vẫn hiện đủ tab, đủ cột, đủ chữ (tất cả là HTML tĩnh), chỉ có điều bấm gì cũng không
 * phản ứng. Đã đo 2026-08-24, và đó là lý do có hai dòng này.
 *
 * Trong phạm vi hàm thì `const chrome` chỉ che đi biến toàn cục, hợp lệ. Không thụt lề lại phần
 * bên dưới, cố ý: giữ file khác bản gốc đúng những chỗ buộc phải khác.
 */
(function () {
/*
 * ===========================================================================
 * LỚP GIẢ LẬP API EXTENSION  —  phần DUY NHẤT khác bản chạy trong extension
 * ===========================================================================
 *
 * Trang này vốn là một trang của extension (`chrome-extension://…/results.html`) nên gọi được
 * thẳng `chrome.runtime` và `chrome.tabs`. Giờ nó là một trang web bình thường trong webtool,
 * và trang web thì KHÔNG có hai API đó.
 *
 * Thay vì sửa 16 chỗ gọi rải khắp 1.300 dòng bên dưới, ở đây dựng lại đúng hai API ấy bằng
 * cầu `postMessage` mà `extension/content.js` đang lắng nghe. Toàn bộ phần còn lại của file
 * giữ nguyên từng ký tự so với `extension/results.js` — đó là chủ đích: giao diện và hành vi
 * không được phép lệch đi chỉ vì đổi chỗ ở.
 *
 * `const chrome` ở phạm vi script che đi `window.chrome` mà trình duyệt tự tạo (một object
 * gần như rỗng với trang thường). Cố ý: mọi lượt gọi bên dưới đi vào cầu này.
 *
 * KHÔNG CÓ EXTENSION thì mỗi lượt gọi trả về `null` sau 30 giây. Không phải giá trị tuỳ tiện:
 * mọi chỗ gọi bên dưới đều đã kiểm `!res || !res.ok` hoặc `(r && r.items) || []` sẵn, nên
 * `null` đi qua đúng những nhánh báo lỗi mà tác giả đã viết, thay vì ném TypeError.
 */
const RS_PAGE = 'research-spy';
const RS_EXT = 'research-spy-ext';

/*
 * PHẢI lớn hơn ngân sách của MỌI lệnh trong `background.js`, không phải một con số cho đẹp.
 *
 * `chrome.runtime.sendMessage` thật không có timeout — nó chờ service worker bao lâu cũng được.
 * Con số ở đây chỉ là lưới an toàn phòng khi extension chết giữa chừng, nên nó phải nằm TRÊN
 * lệnh chậm nhất, không phải dưới. Ngân sách đo được (2026-08-24):
 *
 *     searchTiktok          120.000 ms   ← chậm nhất
 *     searchDouyin          120.000 ms
 *     searchTiktokCreative   45.000 ms
 *     mọi lệnh sàn còn lại  ≤ 18.000 ms
 *
 * Cộng thêm thời gian mở tab và chờ trang tải trước khi vào vòng lặp → chọn 240 giây.
 *
 * ĐÃ SAI MỘT LẦN Ở ĐÂY: đặt 30 giây thì Shopee/1688/Taobao/Amazon vẫn chạy (đều dưới 18 giây)
 * nên trông như mọi thứ bình thường, còn đúng ba nguồn VIDEO thì luôn rỗng. Rỗng IM LẶNG, vì
 * hết giờ trả `null` mà nhánh báo lỗi của trang là `if (tk && tk.blocked && tk.error)` — `null`
 * trượt qua hết. Người dùng chỉ thấy "Không có video", không phân biệt được với thật sự không có.
 */
const RS_TIMEOUT_MS = 240000;
let _rsSeq = 0;

function rsSend(msg) {
  return new Promise((resolve) => {
    const id = `rs-page-${Date.now()}-${_rsSeq++}`;
    const timer = setTimeout(() => {
      window.removeEventListener('message', onMessage);
      // Ít nhất phải để lại dấu vết. Trang xử `null` như "không có kết quả", nên nếu không có
      // dòng này thì một lượt hết giờ trông y hệt một lượt trả về rỗng.
      console.warn(`[research] ${msg && msg.type} không có trả lời sau ${RS_TIMEOUT_MS / 1000}s — extension còn sống không?`);
      resolve(null);
    }, RS_TIMEOUT_MS);

    function onMessage(event) {
      if (event.source !== window) return;
      const d = event.data;
      if (!d || d.source !== RS_EXT || d.id !== id) return;
      clearTimeout(timer);
      window.removeEventListener('message', onMessage);
      resolve(d.result);
    }

    window.addEventListener('message', onMessage);
    window.postMessage({ source: RS_PAGE, type: 'CALL', id, msg }, '*');
  });
}

const chrome = {
  runtime: {
    sendMessage(msg, callback) {
      rsSend(msg).then((result) => { if (callback) callback(result); });
    },
  },
  tabs: {
    // Mở bằng một thẻ <a> tạm chứ KHÔNG bằng `window.open`, và đây là chỗ đã sai một lần
    // (2026-08-24) nên ghi lại cho rõ:
    //
    //     window.open(url, '_blank', 'noopener')  → trả về null NHƯNG TAB VẪN MỞ
    //     window.open(url, '_blank')              → trả về Window
    //
    // `noopener` theo đúng chuẩn là trả `null`, vì bên mở cố ý không được giữ tham chiếu tới
    // cửa sổ mới. Bản trước kiểm `if (!win)` rồi kêu "trình duyệt đã chặn cửa sổ bật lên" —
    // báo động giả MỖI LẦN BẤM, trong khi tab vẫn mở ra ngay sau lưng thông báo đó.
    //
    // Thẻ <a target="_blank" rel="noopener"> giữ nguyên phần an toàn (trang mới không với
    // được `window.opener`), mở ra TAB chứ không phải cửa sổ popup, và không có giá trị trả
    // về nào để hiểu nhầm. Mọi chỗ gọi đều nằm trong click handler nên không đụng bộ chặn.
    create({ url }) {
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    },
  },
  cookies: {
    // Trang web KHÔNG đọc được cookie đăng nhập của các sàn, kể cả khi cùng miền: chúng đều là
    // HttpOnly. Phải nhờ service worker, nơi duy nhất có quyền `cookies`.
    //
    // Thiếu hàm này thì lượt gọi ném TypeError, bị `catch` của trang nuốt và thành `false` —
    // và vì `research()` bỏ qua sàn nào có `loginStatus === false`, Shopee với TikTok Shop sẽ
    // im lặng không bao giờ chạy. Đã sập đúng vào đó một lần, 2026-08-24.
    get({ url, name }, callback) {
      rsSend({ type: 'RS_COOKIE', url, name }).then((r) => callback((r && r.cookie) || null));
    },
  },
};

/** Extension đã cài và trả lời chưa. Trang tự hỏi lúc nạp để báo sớm thay vì để người dùng chờ. */
async function rsExtensionReady() {
  const resp = await Promise.race([
    rsSend({ type: 'RS_PING' }),
    new Promise((r) => setTimeout(() => r(null), 2000)),
  ]);
  return !!(resp && resp.ok);
}

window.addEventListener('DOMContentLoaded', async () => {
  if (await rsExtensionReady()) return;
  const bar = document.getElementById('status');
  const text = document.getElementById('statusText');
  if (!bar || !text) return;
  bar.classList.add('err');
  text.textContent =
    'Chưa thấy extension Research-SPY Fetcher. Các sàn cần phiên đăng nhập của bạn (Shopee, ' +
    'TikTok Shop, Amazon, Taobao, 1688, Temu) sẽ không chạy. Cài ở chrome://extensions → ' +
    'Developer mode → Load unpacked → chọn thư mục extension/, rồi tải lại trang.';
});

const DOMAIN = { VN: 'shopee.vn', TH: 'shopee.co.th', PH: 'shopee.ph', MY: 'shopee.com.my', ID: 'shopee.co.id', SG: 'shopee.sg', TW: 'shopee.tw', BR: 'shopee.com.br', MX: 'shopee.com.mx', CO: 'shopee.com.co', CL: 'shopee.cl' };
const IMG_REGION = { VN: 'vn', TH: 'th', PH: 'ph', MY: 'my', ID: 'id', SG: 'sg', TW: 'tw', BR: 'br', MX: 'mx', CO: 'co', CL: 'cl' };
const CURRENCY = { VN: 'VND', TH: 'THB', PH: 'PHP', MY: 'MYR', ID: 'IDR', SG: 'SGD', TW: 'TWD', BR: 'BRL', MX: 'MXN', CO: 'COP', CL: 'CLP' };
const COUNTRY = { VN: 'Việt Nam', TH: 'Thái Lan', ID: 'Indonesia', MY: 'Malaysia', PH: 'Philippines', SG: 'Singapore', TW: 'Đài Loan', BR: 'Brazil', MX: 'Mexico', CO: 'Colombia', CL: 'Chile', US: 'Mỹ', GB: 'Anh', DE: 'Đức', JP: 'Nhật', FR: 'Pháp', IT: 'Ý', ES: 'TBN', CA: 'Canada' };
const FLAG = { VN: '🇻🇳', TH: '🇹🇭', ID: '🇮🇩', MY: '🇲🇾', PH: '🇵🇭', SG: '🇸🇬', TW: '🇹🇼', BR: '🇧🇷', MX: '🇲🇽', CO: '🇨🇴', CL: '🇨🇱', US: '🇺🇸', GB: '🇬🇧', DE: '🇩🇪', JP: '🇯🇵', FR: '🇫🇷', IT: '🇮🇹', ES: '🇪🇸', CA: '🇨🇦' };
// Amazon: sàn CÔNG KHAI (không login) — mỗi nước 1 domain, fetch thẳng + parse HTML.
const AMZ_DOMAIN = { US: 'amazon.com', GB: 'amazon.co.uk', DE: 'amazon.de', JP: 'amazon.co.jp', FR: 'amazon.fr', IT: 'amazon.it', ES: 'amazon.es', CA: 'amazon.ca' };
const AMZ_CUR = { US: 'USD', GB: 'GBP', DE: 'EUR', FR: 'EUR', IT: 'EUR', ES: 'EUR', JP: 'JPY', CA: 'CAD' };
// TikTok Shop: Cách A qua SELLER CENTER. SDK của trang tự ký fetch (X-Tts-Oec-Bsid) → chỉ cần
// build request + fetch trong tab seller (như Shopee). Mỗi region = 1 domain seller; user chỉ
// chạy được region mình có account đăng nhập.
const TT_DOMAIN = { PH: 'seller-ph.tiktok.com', VN: 'seller-vn.tiktok.com', TH: 'seller-th.tiktok.com', ID: 'seller-id.tiktok.com', MY: 'seller-my.tiktok.com', SG: 'seller-sg.tiktok.com', US: 'seller-us.tiktok.com', GB: 'seller-uk.tiktok.com' };
const TT_CUR = { PH: 'PHP', VN: 'VND', TH: 'THB', ID: 'IDR', MY: 'MYR', SG: 'SGD', US: 'USD', GB: 'GBP' };
const TT_TZ = { PH: 'Asia/Manila', VN: 'Asia/Ho_Chi_Minh', TH: 'Asia/Bangkok', ID: 'Asia/Jakarta', MY: 'Asia/Kuala_Lumpur', SG: 'Asia/Singapore', US: 'America/Los_Angeles', GB: 'Europe/London' };
// Tỉ giá xấp xỉ về USD — để quy GMV các sàn/nước về cùng thang khi chấm "chất" (không phụ thuộc
// đơn vị tiền). Chỉ dùng cho chuẩn hoá điểm, không phải giá trị tài chính chính xác.
const FX_USD = { PHP: 0.017, VND: 0.00004, THB: 0.028, IDR: 0.000062, MYR: 0.22, SGD: 0.74, USD: 1, GBP: 1.27 };
// Sàn chạy ở BACKEND (secret/scrape phía server): Etsy, Facebook.
//
// RỖNG là cố ý: trang này giờ nằm trong webtool, nên `/api/...` đi cùng origin và được
// `frontend/next.config.mjs` chuyển tiếp sang FastAPI. Nhờ vậy đổi tên miền lúc deploy
// không phải sửa file này — khác hẳn bản cũ trỏ cứng vào localhost:8000.
const BACKEND = '';
const PF_LABEL = { etsy: 'Etsy', facebook: 'Facebook', tiktok: 'TikTok', douyin: 'Douyin 抖音' };
const PRICE_SCALE = 100000;

// Cấu hình sàn: active = đã có adapter; regions = mảng nước (có region), [] = nội địa/toàn cầu
// (không chọn region), 'any' = lọc mọi nước (Facebook). Region động theo sàn đang chọn.
const PLATFORMS = {
  shopee: { label: 'Shopee', active: true, regions: ['VN', 'TH', 'ID', 'MY', 'PH', 'SG', 'TW', 'BR', 'MX', 'CO', 'CL'] },
  tiktok: { label: 'TikTok Shop', active: true, regions: ['PH', 'VN', 'TH', 'ID', 'MY', 'SG', 'US', 'GB'] },
  facebook: { label: 'Facebook Ads', active: true, backend: true, content: true, regions: ['US', 'GB', 'DE', 'FR', 'BR', 'VN'] },
  amazon: { label: 'Amazon', active: true, regions: ['US', 'GB', 'DE', 'JP', 'FR', 'IT', 'ES', 'CA'] },
  etsy: { label: 'Etsy', active: true, backend: true, regions: [] },
  taobao: { label: 'Taobao', active: true, experimental: true, regions: [] },
  ali1688: { label: '1688 (giá sỉ)', active: true, regions: [] },
  temu: { label: 'Temu', active: true, experimental: true, regions: ['US', 'GB', 'DE', 'FR', 'JP'] }, // gõ-search-trong-tab để bắn API rồi chộp
};

const loginStatus = {}; // "pf:CODE" -> true | false | undefined
const selectedPlatforms = new Set(['shopee']);
// Sàn cần đăng nhập (Cách A) → check tức thì qua một cookie đặc trưng của phiên. Sàn công khai
// (Amazon) không có ở đây. Thêm sàn login = thêm 1 dòng {domain, cookie, ok}.
const LOGIN = {
  shopee: { domain: DOMAIN, cookie: 'SPC_U', ok: (v) => v && v !== '-' },
  tiktok: { domain: TT_DOMAIN, cookie: 'oec_seller_id_unified_seller_env', ok: (v) => !!v },
};
// Region chọn theo TỪNG sàn — key "pf:CODE". Mỗi sàn có bộ region riêng (Shopee 11 nước, Amazon
// 8 nước…) nên KHÔNG dùng chung một tập region; nhờ vậy Shopee-VN và Amazon-US độc lập với nhau.
const selectedRegions = new Set(['shopee:VN']);
function curOf(p) { return p.currency || CURRENCY[p.region] || 'VND'; }

// Các sàn (tab Sản phẩm) đang chọn mà CÓ region — để gom nhóm region theo sàn.
function regionPlatforms() {
  return [...selectedPlatforms].filter((p) => {
    const cfg = PLATFORMS[p];
    return cfg && !cfg.content && Array.isArray(cfg.regions) && cfg.regions.length;
  });
}

function renderPlatforms() {
  const box = document.getElementById('platforms');
  if (!box) return;
  box.innerHTML = '';
  for (const [id, cfg] of Object.entries(PLATFORMS)) {
    if (cfg.content) continue; // sàn content (FB) nằm ở tab Content, không hiện ở tab Sản phẩm
    const rg = cfg.regions === 'any' ? 'mọi nước' : (cfg.regions.length ? `${cfg.regions.length} region` : 'nội địa/không region');
    const chip = document.createElement('button');
    chip.className = 'rgchip' + (cfg.active ? '' : ' dim');
    chip.dataset.pf = id;
    chip.dataset.on = selectedPlatforms.has(id) ? '1' : '0';
    chip.textContent = cfg.label;
    chip.title = `${cfg.label} · ${rg}${cfg.active ? ' — bấm chọn/bỏ' : ' — chưa hỗ trợ'}`;
    box.appendChild(chip);
  }
}

// Region đổi theo sàn: mỗi sàn có region là một NHÓM riêng. Giữ tối thiểu 1 region/sàn.
function updateRegionSection() {
  const pfs = regionPlatforms();
  const section = document.getElementById('regionSection');
  if (!pfs.length) { if (section) section.style.display = 'none'; return; } // Taobao/1688/Etsy → ẩn region
  if (section) section.style.display = 'flex';
  // Bỏ region của sàn không còn được chọn.
  for (const key of [...selectedRegions]) if (!pfs.includes(key.split(':')[0])) selectedRegions.delete(key);
  // Mỗi sàn có region phải giữ tối thiểu 1 (mặc định nước đầu) để nó còn chạy được.
  for (const pf of pfs) {
    if (!PLATFORMS[pf].regions.some((c) => selectedRegions.has(`${pf}:${c}`))) selectedRegions.add(`${pf}:${PLATFORMS[pf].regions[0]}`);
  }
  renderRegions();
}

// Check đăng nhập TỨC THÌ qua cookie đặc trưng của sàn (Shopee: SPC_U; TikTok: seller id).
function checkLogin(pf, code) {
  const spec = LOGIN[pf];
  const domain = spec && spec.domain[code];
  if (!domain) return Promise.resolve(undefined);
  return new Promise((resolve) => {
    try {
      chrome.cookies.get({ url: `https://${domain}/`, name: spec.cookie }, (c) => resolve(!!(c && c.value && spec.ok(c.value))));
    } catch (e) { resolve(false); }
  });
}
async function refreshLogin() {
  renderRegions();
  for (const pf of regionPlatforms()) {
    if (!LOGIN[pf]) continue; // sàn công khai (Amazon) không cần check
    for (const code of PLATFORMS[pf].regions) {
      if (!LOGIN[pf].domain[code]) continue;
      loginStatus[`${pf}:${code}`] = await checkLogin(pf, code);
      renderRegions();
    }
  }
}

// Vẽ region theo NHÓM sàn: một Ô THẢ XUỐNG để THÊM nước, và chip cho từng nước ĐÃ CHỌN.
//
// Trước đây hiện MỌI nước cùng lúc (Shopee một mình đã 11 chip) — nhìn rối, và không phải ai
// cũng cần so 11 nước một lúc. Giờ mặc định chỉ thấy nước đang chọn; muốn thêm thì mở danh
// sách. Logic bấm-chip-để-bỏ/mở-đăng-nhập giữ NGUYÊN — chỉ đổi nguồn hiện ra của các chip.
function renderRegions() {
  const box = document.getElementById('regions');
  if (!box) return;
  box.innerHTML = '';
  for (const pf of regionPlatforms()) {
    const cfg = PLATFORMS[pf];
    const group = document.createElement('div');
    group.className = 'rgroup';
    const label = document.createElement('span');
    label.className = 'rglabel';
    label.textContent = cfg.label;
    group.appendChild(label);

    const nhanNuoc = (code) => {
      const isLoginRegion = !!(LOGIN[pf] && LOGIN[pf].domain[code]);
      const st = loginStatus[`${pf}:${code}`];
      const badge = !isLoginRegion
        ? '🌐'
        : st === true ? '✓' : st === false ? '✕' : '…';
      return { isLoginRegion, st, badge };
    };

    // Ô "+ Thêm nước": chỉ liệt kê nước CHƯA chọn của sàn này. Chọn xong danh sách nước cũng
    // rút bớt lại — không có gì để thêm nữa thì cả ô này biến mất.
    const chuaChon = cfg.regions.filter((c) => !selectedRegions.has(`${pf}:${c}`));
    if (chuaChon.length) {
      const add = document.createElement('select');
      add.className = 'region-add';
      add.dataset.pf = pf;
      add.innerHTML =
        `<option value="">+ Thêm nước…</option>` +
        chuaChon
          .map((c) => {
            const { badge } = nhanNuoc(c);
            return `<option value="${c}">${FLAG[c] || ''} ${COUNTRY[c] || c} (${c}) ${badge}</option>`;
          })
          .join('');
      group.appendChild(add);
    }

    for (const code of cfg.regions) {
      if (!selectedRegions.has(`${pf}:${code}`)) continue; // chỉ vẽ chip cho nước ĐÃ CHỌN
      const { isLoginRegion, st, badge } = nhanNuoc(code);
      const chip = document.createElement('button');
      chip.className = 'rgchip';
      chip.dataset.pf = pf;
      chip.dataset.code = code;
      chip.dataset.on = '1';
      chip.innerHTML = `${FLAG[code] || ''} ${COUNTRY[code] || code} <span class="sub">${code}</span> <span class="${isLoginRegion ? (st ? 'ok' : 'no') : 'sub'}">${badge}</span>`;
      chip.title = !isLoginRegion
        ? `${cfg.label} · ${COUNTRY[code] || code} — công khai, không cần đăng nhập. Bấm để bỏ.`
        : st === false ? `${cfg.label} · ${COUNTRY[code] || code}: chưa đăng nhập — bấm để mở đăng nhập` : `${cfg.label} · ${COUNTRY[code] || code} — bấm để bỏ`;
      group.appendChild(chip);
    }
    box.appendChild(group);
  }
}
const PAGE_SIZE = 60;

const $ = (id) => document.getElementById(id);
let rows = [];
let sortKey = 'score';

function esc(s) { return String(s == null ? '' : s).replace(/</g, '&lt;').replace(/"/g, '&quot;'); }
function setStatus(msg, kind) { $('statusText').textContent = msg; $('status').className = 'status' + (kind ? ' ' + kind : ''); }
function fmtInt(n) { return typeof n === 'number' ? n.toLocaleString('vi-VN') : '—'; }
function fmtPrice(v, cur) { return v == null ? '—' : v.toLocaleString('vi-VN') + ' ' + cur; }
function imageUrl(region, hash) { return hash ? `https://down-${IMG_REGION[region] || 'vn'}.img.susercontent.com/file/${hash}` : ''; }
// Gỡ lớp proxy `/api/media?url=` để lấy lại URL CDN GỐC — backend /match-image cần url thật của
// ảnh sản phẩm (nó tự bọc Referer khi tải). Ảnh Shopee/Amazon vốn đã là url gốc nên trả nguyên.
function rawImg(url) {
  const pfx = `${BACKEND}/api/media?url=`;
  return url && url.startsWith(pfx) ? decodeURIComponent(url.slice(pfx.length)) : (url || '');
}
function clamp(v) { return Math.max(0, Math.min(100, Math.round(v))); }
function compactNum(n) { return n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'k' : String(Math.round(n)); }
// Dòng phụ dưới điểm: sàn có rating → "cầu · chất"; TikTok (không rating, có GMV) → "cầu · GMV"
// (gọi đúng tên doanh thu, không giả vờ là quality).
function scoreSub(p) {
  if (p.rating != null) {
    const base = `cầu ${p.score.demand} · chất ${p.score.quality}`; // Shopee/Amazon/1688
    return p.repurchase != null ? `${base} · quay lại ${p.repurchase}%` : base; // 1688 thêm 回头率
  }
  if (p.gmv != null) return `cầu ${p.score.demand} · GMV ${compactNum(p.gmv)}`;    // TikTok
  return `cầu ${p.score.demand}`;
}

// Giá vốn = giá thấp nhất trong danh sách sản phẩm tương tự. Tính lười theo từng dòng.
const costCache = {}; // itemid -> số (đã /PRICE_SCALE) hoặc 'none'

// Gom mọi trường `price` (giá bán, đơn vị ×100000) trong JSON find_similar rồi lấy min.
function collectPrices(node, out) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) { for (const x of node) collectPrices(x, out); return; }
  for (const k in node) {
    const v = node[k];
    if (k === 'price' && typeof v === 'number' && v > 100000) out.push(v);
    else if (v && typeof v === 'object') collectPrices(v, out);
  }
}

function costValueHtml(cost, price, cur) {
  let note = '';
  if (price && cost < price) note = `<div class="sub" style="color:var(--good)">biên ${Math.round((1 - cost / price) * 100)}%</div>`;
  else if (price && cost >= price) note = '<div class="sub" style="color:var(--disc)">≥ giá bán</div>';
  return `<span class="price" title="Giá vốn = rẻ nhất từ Sản phẩm tương tự">${fmtPrice(cost, cur)}</span>${note}`;
}

function costCellHtml(p) {
  const c = costCache[p.itemid];
  if (typeof c === 'number') return costValueHtml(c, p.price, curOf(p)); // giá vốn từ find_similar
  if (c === 'none') return '<span class="sub">—</span>';
  return '<span class="sub">…</span>'; // đang/chờ batch tính
}

function productById(itemid) { return rows.find((p) => p.itemid === itemid); }

function searchUrl(domain, keyword, offset) {
  const q = new URLSearchParams({ by: 'sales', keyword, limit: String(PAGE_SIZE), newest: String(offset), order: 'desc', page_type: 'search', scenario: 'PAGE_GLOBAL_SEARCH', version: '2' });
  return `https://${domain}/api/v4/search/search_items?${q.toString()}`;
}

// Dò link VIDEO trong item sản phẩm (không cần biết field chính xác): duyệt cây, bắt URL video
// (.mp4/.m3u8/cloud.video/…). Trả '' nếu response search không có video (chỉ ở trang chi tiết).
function findVideoUrl(o, depth) {
  depth = depth || 0;
  if (o == null || depth > 6) return '';
  if (typeof o === 'string') {
    return /^(https?:)?\/\//.test(o) && /\.mp4(\?|$)|\.m3u8|cloud\.video|\/video\/|video_url|\/vod\//i.test(o) ? (o.indexOf('//') === 0 ? 'https:' + o : o) : '';
  }
  if (Array.isArray(o)) { for (var i = 0; i < o.length; i++) { var v = findVideoUrl(o[i], depth + 1); if (v) return v; } return ''; }
  if (typeof o === 'object') {
    for (var k in o) { if (/video/i.test(k)) { var vk = findVideoUrl(o[k], depth + 1); if (vk) return vk; } }
    for (var k2 in o) { var v2 = findVideoUrl(o[k2], depth + 1); if (v2) return v2; }
  }
  return '';
}

// Shopee: SP có video (nút ▶ trên thumbnail) → dữ liệu video nằm trong `video_info_list` (ở
// item_card_displayed_asset / item_basic / item_data). URL mp4 thường ở default_format.url.
// Tìm nhánh video_info_list bất kỳ trong item, ưu tiên URL trông như video, rồi mới URL đầu tiên.
function shopeeVideoUrl(it) {
  let best = '', first = '';
  (function walk(o, d) {
    if (o == null || d > 7) return;
    if (Array.isArray(o)) { o.forEach((x) => walk(x, d + 1)); return; }
    if (typeof o !== 'object') return;
    for (const k in o) {
      if (/video[_-]?info[_-]?list|videoInfoList/i.test(k) && o[k]) {
        (function grab(v, dd) {
          if (v == null || dd > 5) return;
          if (typeof v === 'string' && /^(https?:)?\/\//.test(v)) {
            const u = v.indexOf('//') === 0 ? 'https:' + v : v;
            if (/\.mp4|\/vod\/|\.m3u8|video/i.test(u)) { if (!best) best = u; }
            else if (!first) first = u;
            return;
          }
          if (Array.isArray(v)) v.forEach((x) => grab(x, dd + 1));
          else if (typeof v === 'object') for (const kk in v) grab(v[kk], dd + 1);
        })(o[k], 0);
      }
      walk(o[k], d + 1);
    }
  })(it, 0);
  return best || first || findVideoUrl(it);
}

function parseItem(it, region, domain) {
  const asset = it.item_card_displayed_asset || {};
  const idata = it.item_data || {};
  const basic = it.item_basic || {};
  const itemid = it.itemid || idata.itemid, shopid = it.shopid || idata.shopid;
  if (itemid == null || shopid == null) return null;

  const dp = idata.item_card_display_price || asset.display_price || {};
  const rawPrice = dp.price ?? basic.price;
  const price = typeof rawPrice === 'number' && rawPrice > 0 ? rawPrice / PRICE_SCALE : null;
  const rawStrike = dp.strikethrough_price;
  const strike = typeof rawStrike === 'number' && rawStrike > 0 ? rawStrike / PRICE_SCALE : null;
  let discount = typeof dp.discount === 'number' ? dp.discount : null;
  if (discount == null && strike && price && strike > price) discount = Math.round((1 - price / strike) * 100);

  const sc = idata.item_card_display_sold_count || {};
  const monthly = typeof sc.monthly_sold_count === 'number' ? sc.monthly_sold_count : null;
  const sold = sc.historical_sold_count ?? basic.historical_sold ?? basic.sold ?? null;

  const rb = idata.item_rating || {};
  const rating = typeof rb.rating_star === 'number' && rb.rating_star > 0 ? rb.rating_star : null;
  const ratingCount = Array.isArray(rb.rating_count) && typeof rb.rating_count[0] === 'number' ? rb.rating_count[0] : null;

  const catid = idata.catid || (Array.isArray((idata.global_cat || {}).catid) ? idata.global_cat.catid[0] : null);

  return {
    platform: 'Shopee', region, currency: CURRENCY[region],
    itemid: String(itemid), shopid: String(shopid), catid,
    name: asset.name || basic.name || '',
    image: imageUrl(region, asset.image || (Array.isArray(asset.images) ? asset.images[0] : '') || basic.image),
    price, strike, discount, monthly, sold, rating, ratingCount,
    videoUrl: shopeeVideoUrl(it), // video sản phẩm Shopee (video_info_list) nếu SP có ▶
    shop: (idata.shop_data || {}).shop_name || asset.shop_location || '',
    isAd: !!it.adsid,
    link: `https://${domain}/product/${shopid}/${itemid}`,
    similarUrl: catid ? `https://${domain}/find_similar_products?catid=${catid}&itemid=${itemid}&shopid=${shopid}` : `https://${domain}/product/${shopid}/${itemid}`,
  };
}

// Chấm điểm sản phẩm — soi gương backend _score_product.
function score(p) {
  let demand, quality;
  if (p.monthly != null) demand = clamp(Math.log10(Math.max(1, p.monthly)) / 4 * 100);
  else if (p.sold != null) demand = clamp(Math.log10(Math.max(1, p.sold)) / 5.5 * 100);
  else if (p.ratingCount != null) demand = clamp(Math.log10(Math.max(1, p.ratingCount)) / 5 * 100); // Amazon: số review làm proxy cầu (không có sold)
  else if (p.repurchase != null) demand = clamp(p.repurchase); // 1688: 回头率 (% khách quay lại) làm proxy cầu
  else demand = 0;
  if (p.rating != null) {
    const base = clamp((p.rating - 3.0) / 2.0 * 100);
    // Shopee/Amazon/Etsy: chiết khấu theo số review. 1688 (điểm shop tổng hợp, không có ratingCount) → tin luôn.
    const trust = p.ratingCount != null ? Math.min(1, Math.log10((p.ratingCount || 0) + 1) / 2) : 1;
    quality = clamp(base * trust);
  } else if (p.gmv != null) {
    // TikTok không có rating → "chất" thay bằng GMV/tháng (doanh thu thật), quy về USD để so được
    // giữa các nước, rồi log10 (doanh thu trải nhiều bậc). Mốc: $100→25, $1k→50, $10k→75, $100k→100.
    const usd = p.gmv * (FX_USD[curOf(p)] || 0.02);
    quality = clamp((Math.log10(Math.max(1, usd)) - 1) / 4 * 100);
  } else quality = 0;
  return { total: clamp(demand * 0.6 + quality * 0.4), demand, quality };
}

function sendFetch(requests) {
  return new Promise((resolve) => chrome.runtime.sendMessage({ type: 'RS_FETCH', requests }, (r) => resolve((r && r.responses) || [])));
}

// Lấy sản phẩm Shopee cho MỘT từ khoá. Trả {products, blocked}.
// CÁCH NHANH (mặc định): fetch same-origin search_items NGAY TRONG tab shopee đã đăng nhập
// (RS_FETCH → fetchInTab). Tab chỉ ở trang chính `https://{domain}/`, KHÔNG điều hướng tới /search —
// nên 1 tab/region, trả JSON thẳng ~1-2s. Nếu Shopee 403 (siết anti-bot) mới hạ xuống cách điều
// hướng /search (searchShopeeNav) làm dự phòng.
async function fetchKeyword(keyword, region, count) {
  const domain = DOMAIN[region];
  const seen = new Set();
  const products = [];
  let rawItemCount = 0, hardBlock = false, blockMsg = '';
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE));
  for (let page = 0; page < pages; page++) {
    const url = searchUrl(domain, keyword, page * PAGE_SIZE);
    const res = await sendFetch([{ url, method: 'GET', headers: { 'x-api-source': 'pc' }, tag: 'shopee' }]);
    const r = res && res[0];
    if (!r) break;
    // Không mở được tab đăng nhập → không phải 403, báo rõ để user mở shopee.vn.
    if (/^NO_TAB|^INJECT_FAIL/.test(String(r.text || ''))) {
      return { products: [], blocked: true, notice: 'Shopee: chưa mở được tab shopee — mở shopee.vn (đăng nhập) rồi bấm lại.' };
    }
    if (r.status === 403 || r.status === 401) { hardBlock = true; break; } // siết anti-bot → thử cách điều hướng
    let data; try { data = JSON.parse(r.text); } catch { continue; }
    if (data.error && data.error !== 0) { hardBlock = true; break; } // JSON báo lỗi (login/verify) → dự phòng
    const items = data.items || (data.data || {}).items || [];
    rawItemCount += items.length;
    for (const it of items) {
      const p = parseItem(it, region, domain);
      if (!p || seen.has(p.itemid)) continue;
      seen.add(p.itemid);
      p.keyword = keyword;
      p.score = score(p);
      products.push(p);
      if (products.length >= count) break;
    }
    if (products.length >= count || items.length === 0) break;
  }
  if (products.length) return { products, blocked: false };

  // Fetch thẳng bị chặn/rỗng → DỰ PHÒNG: điều hướng tab tới /search cho trang tự gọi (chậm hơn).
  if (hardBlock || !rawItemCount) {
    const nav = await fetchKeywordNav(keyword, region, count);
    if (nav.products.length || nav.blocked) return nav;
  }
  const notice = rawItemCount > 0
    ? `Shopee: có ${rawItemCount} item thô nhưng parse ra 0 — Shopee đổi tên field, báo dev.`
    : 'Shopee: chưa lấy được sản phẩm — kiểm tra đăng nhập shopee.vn rồi thử lại.';
  return { products: [], blocked: false, notice };
}

// DỰ PHÒNG: cách điều hướng tab tới /search?keyword (background searchShopee) — dùng khi fetch thẳng
// bị 403. Chậm hơn (chờ render + cuộn) nên chỉ chạy khi cách nhanh thất bại.
async function fetchKeywordNav(keyword, region, count) {
  const domain = DOMAIN[region];
  const res = await new Promise((r) => chrome.runtime.sendMessage({ type: 'RS_SHOPEE', keyword, domain }, (x) => r(x)));
  if (!res || !res.ok) return { products: [], blocked: false, notice: 'Shopee: extension không phản hồi' };
  if (res.blocked) return { products: [], blocked: true, notice: `Shopee: ${res.error || 'bị chặn / chưa đăng nhập'}` };
  const videoMap = {};
  for (const v of (res.videoItems || [])) videoMap[String(v.itemid)] = v.url;
  const seen = new Set();
  const products = [];
  let rawItemCount = 0;
  for (const text of (res.texts || [])) {
    let data; try { data = JSON.parse(text); } catch { continue; }
    const items = data.items || (data.data || {}).items || [];
    rawItemCount += items.length;
    for (const it of items) {
      const p = parseItem(it, region, domain);
      if (!p || seen.has(p.itemid)) continue;
      if (videoMap[p.itemid]) p.videoUrl = videoMap[p.itemid];
      seen.add(p.itemid);
      p.keyword = keyword;
      p.score = score(p);
      products.push(p);
      if (products.length >= count) break;
    }
    if (products.length >= count) break;
  }
  let notice;
  if (!products.length) {
    notice = rawItemCount > 0
      ? `Shopee: có ${rawItemCount} item thô nhưng parse ra 0 — Shopee đổi tên field, báo dev.`
      : (res.error || 'Shopee: chưa lấy được sản phẩm — thử lại (để tab shopee tự cuộn, đừng rời).');
  }
  return { products, blocked: false, notice };
}

// --- Amazon (công khai, không login) — background điều hướng tab tới trang search, đọc DOM ---
async function fetchAmazon(keyword, region, count) {
  const domain = AMZ_DOMAIN[region];
  if (!domain) return { products: [], blocked: false };
  const cur = AMZ_CUR[region] || 'USD';
  const url = `https://www.${domain}/s?k=${encodeURIComponent(keyword)}`;
  const res = await new Promise((r) => chrome.runtime.sendMessage({ type: 'RS_AMAZON', domain, url }, (x) => r(x)));
  if (!res || !res.ok || res.blocked) return { products: [], blocked: true };
  const products = (res.items || []).slice(0, count).map((it) => ({
    platform: 'Amazon', region, currency: cur,
    itemid: it.asin, shopid: '', catid: null,
    name: it.name, image: it.image,
    price: it.price, strike: it.strike,
    discount: it.strike && it.price && it.strike > it.price ? Math.round((1 - it.price / it.strike) * 100) : null,
    monthly: it.monthly, sold: null, rating: it.rating, ratingCount: it.ratingCount, // cầu: "bought/tháng" nếu có, không thì số review
    shop: '', isAd: it.isAd,
    link: `https://www.${domain}/dp/${it.asin}`,
    similarUrl: `https://www.${domain}/dp/${it.asin}`,
  }));
  return { products, blocked: false };
}

// --- Sàn BACKEND (Etsy: API key; Facebook: scrape) — extension gọi /api/ads/search của backend ---
async function fetchBackend(platform, keyword, region, count) {
  const country = region === '_' ? 'US' : region;
  const params = new URLSearchParams({ keyword, platforms: platform, countries: country, limit: String(count) });
  let data;
  try {
    const r = await fetch(`${BACKEND}/api/ads/search?${params.toString()}`);
    data = await r.json();
    if (!r.ok) return { products: [], blocked: false, notice: (data && data.error) || `backend HTTP ${r.status}` };
  } catch (e) {
    return { products: [], blocked: false, backendDown: true };
  }
  const products = (data.ads || []).slice(0, count).map((ad) => {
    const cr = (ad.creatives || []).find((c) => c.url || c.posterUrl) || {};
    const imgRaw = cr.posterUrl || cr.url || '';
    return {
      platform: PF_LABEL[platform] || platform, region: region === '_' ? '' : region, currency: ad.currency,
      itemid: ad.id, shopid: '', catid: null,
      name: ad.title || ad.body || '',
      image: imgRaw ? `${BACKEND}/api/media?url=${encodeURIComponent(imgRaw)}` : '',
      price: ad.price ?? null, strike: null, discount: null,
      monthly: ad.monthlySold ?? null, sold: ad.soldCount ?? null,
      rating: ad.rating ?? null, ratingCount: ad.ratingCount ?? null,
      daysActive: ad.daysActive ?? null, // cho tab Content (FB: đời quảng cáo)
      shop: ad.advertiser || '', isAd: false,
      link: ad.permalink || '#', similarUrl: ad.permalink || '#',
      // Dùng điểm do BACKEND chấm (FB chấm theo đời quảng cáo; Etsy theo favorites) — đừng re-score.
      score: ad.score ? { total: ad.score.total, demand: ad.score.demandScore ?? ad.score.cvrProxy ?? 0, quality: ad.score.qualityScore ?? ad.score.contentScore ?? 0 } : undefined,
    };
  });
  const notice = (data.statuses || []).map((s) => s.message).filter(Boolean)[0] || null;
  return { products, blocked: false, notice };
}

// --- TikTok Shop (Cách A qua Seller Center) — build POST rồi fetch trong tab seller; SDK tự ký ---
const TT_ENDPOINT = '/api/v1/product/oc/seller_product_opportunity/seller/lead/list';

// seller_id nằm trong cookie (mỗi user một id) — cần để dựng URL.
function tiktokSellerId(domain) {
  return new Promise((resolve) => {
    try { chrome.cookies.get({ url: `https://${domain}/`, name: 'oec_seller_id_unified_seller_env' }, (c) => resolve((c && c.value) || null)); }
    catch (e) { resolve(null); }
  });
}
// Số dạng chuỗi TikTok ("1,099.00" / "2,140" / "₱131,065") → number.
function ttNum(v) { const n = Number(String(v == null ? '' : v).replace(/[^\d.]/g, '')); return isFinite(n) && n > 0 ? n : null; }

function parseTiktokItem(it, region) {
  const pics = it.pic_url || it.high_resolution_pic_url || [];
  return {
    platform: 'TikTok Shop', region, currency: TT_CUR[region] || 'USD',
    itemid: String(it.lead_id || ''), shopid: '', catid: null,
    name: it.lead_name || '',
    image: Array.isArray(pics) ? (pics[0] || '') : '',
    price: ttNum(it.recommend_price_low), strike: null, discount: null,
    monthly: ttNum(it.l30d_sales_volume), sold: null, // cầu = bán 30 ngày (TikTok không cho tổng luỹ kế)
    rating: null, ratingCount: null,                   // product opportunity không có rating
    gmv: ttNum(it.gmv_l30d || it.gmv),                 // doanh thu 30 ngày → dùng làm "chất" thay rating
    shop: it.level3_cate_name || it.level2_cate_name || '', // không có shop → hiện ngành hàng cho có ngữ cảnh
    isAd: false,
    link: it.real_external_product_id ? `https://www.tiktok.com/view/product/${it.real_external_product_id}` : '#',
    similarUrl: `https://${TT_DOMAIN[region]}/product/opportunity/search?search_text=${encodeURIComponent(it.lead_name || '')}`,
  };
}

async function fetchTiktok(keyword, region, count) {
  const domain = TT_DOMAIN[region];
  if (!domain) return { products: [], blocked: false };
  const sellerId = await tiktokSellerId(domain);
  if (!sellerId) return { products: [], blocked: true, notice: `TikTok ${region}: chưa đăng nhập Seller Center` };
  const q = new URLSearchParams({
    locale: 'en', language: 'en', oec_seller_id: sellerId, seller_id: sellerId, aid: '4068', app_name: 'i18n_ecom_shop',
    device_platform: 'web', cookie_enabled: 'true', screen_width: '1536', screen_height: '864',
    browser_language: 'en-US', browser_platform: 'Win32', browser_name: 'Mozilla', browser_online: 'true', timezone_name: TT_TZ[region] || 'Asia/Manila',
  });
  const body = JSON.stringify({
    opportunity_type: 3, tab_code_filter: ['high_potential_products'], use_like: false, sort_field: 1,
    incentive_tag_query: null, page_number: 1, page_size: Math.min(100, count), search_text: keyword, traffic_source: 'seller_organic',
  });
  const res = await sendFetch([{ url: `https://${domain}${TT_ENDPOINT}?${q.toString()}`, method: 'POST', headers: { 'content-type': 'application/json', 'x-tt-oec-region': region }, body, tag: 'tt' }]);
  const r = res[0];
  if (!r || r.status !== 200) return { products: [], blocked: !!(r && (r.status === 403 || r.status === 0)), notice: r ? `TikTok HTTP ${r.status}` : null };
  let data; try { data = JSON.parse(r.text); } catch { return { products: [], blocked: false, notice: 'TikTok: phản hồi không phải JSON' }; }
  if (data.code !== 0) return { products: [], blocked: false, notice: `TikTok: ${data.message || 'lỗi ' + data.code}` };
  const products = (data.data || []).slice(0, count).map((it) => parseTiktokItem(it, region)).filter((p) => p.itemid);
  return { products, blocked: false };
}

// --- 1688 (giá sỉ Trung, công khai) — background gọi API mtop JSON trong tab h5api. Không region ---
async function fetch1688(keyword, count) {
  const res = await new Promise((r) => chrome.runtime.sendMessage({ type: 'RS_1688', keyword, count }, (x) => r(x)));
  if (!res || !res.ok) return { products: [], blocked: false, notice: '1688: extension không phản hồi' };
  if (res.blocked) return { products: [], blocked: true, notice: `1688: bị chặn tạm (${res.error || 'rate-limit'}) — thử lại sau` };
  const products = (res.items || []).slice(0, count).map((it) => ({
    platform: '1688', region: '', currency: 'CNY',
    itemid: String(it.id), shopid: '', catid: null,
    name: it.name, image: it.image,
    price: it.price, strike: null, discount: null, // giá sỉ (giá vốn); 1688 không công khai giảm giá
    monthly: it.monthly, sold: it.sold, rating: it.rating, ratingCount: null, repurchase: it.repurchase, // sort GMV 30d lộ số bán; rating=điểm shop
    videoUrl: it.videoUrl || '', // video sản phẩm nếu response search có
    shop: it.shop, isAd: false,
    link: `https://detail.1688.com/offer/${it.id}.html`,
    similarUrl: it.similar || `https://detail.1688.com/offer/${it.id}.html`, // link tìm sản phẩm cùng mẫu (sameDesignUrl)
  }));
  // Hiện LÝ DO thật khi rỗng (thay vì để lọt vào thông báo chung chung) — vd token/limit/không có SP.
  if (!products.length) return { products: [], blocked: false, notice: `1688: ${res.error || 'không có sản phẩm cho từ khoá này'}` };
  return { products, blocked: false };
}

// --- Taobao (Cách A "ký sinh": trang tự gọi h5search đã ký + x5sec, extension chộp response). Không region ---
async function fetchTaobao(keyword, count) {
  const res = await new Promise((r) => chrome.runtime.sendMessage({ type: 'RS_TAOBAO', keyword, count }, (x) => r(x)));
  if (!res || !res.ok) return { products: [], blocked: false, notice: 'Taobao: extension không phản hồi' };
  if (res.blocked) return { products: [], blocked: true, notice: `Taobao: ${res.error || 'bị chặn'}` };
  if (res.raw) { console.log('[RS] Taobao raw (chưa map được field):', res.raw); return { products: [], blocked: false, notice: 'Taobao: bắt được response nhưng chưa khớp field — xem Console (F12) gửi dev' }; }
  const products = (res.items || []).slice(0, count).map((it) => ({
    platform: 'taobao', region: '', currency: 'CNY',
    itemid: String(it.id), shopid: '', catid: null,
    name: it.name, image: it.image,
    price: it.price, strike: null, discount: null,
    monthly: it.monthly, sold: null, rating: null, ratingCount: null,
    videoUrl: it.videoUrl || '', // video sản phẩm nếu response search có
    shop: it.shop, isAd: false,
    link: `https://item.taobao.com/item.htm?id=${it.id}`,
    similarUrl: `https://s.taobao.com/search?q=${encodeURIComponent(it.name || keyword)}`,
  }));
  return { products, blocked: false };
}

// --- Temu (Cách A "ký sinh": trang tự gọi /api/poppy/v1/search kèm anti-content, extension chộp response) ---
const TEMU_CUR = { US: 'USD', GB: 'GBP', DE: 'EUR', FR: 'EUR', JP: 'JPY' };
async function fetchTemu(keyword, region, count) {
  const res = await new Promise((r) => chrome.runtime.sendMessage({ type: 'RS_TEMU', keyword, count }, (x) => r(x)));
  if (!res || !res.ok) return { products: [], blocked: false, notice: 'Temu: extension không phản hồi' };
  if (res.blocked) return { products: [], blocked: true, notice: `Temu: ${res.error || 'bị chặn'}` };
  if (res.raw) { console.log('[RS] Temu raw (chưa map được field):', res.raw); return { products: [], blocked: false, notice: 'Temu: bắt được response nhưng chưa khớp field — xem Console (F12) gửi dev' }; }
  const products = (res.items || []).slice(0, count).map((it) => ({
    platform: 'temu', region: region || '', currency: it.currency || TEMU_CUR[region] || 'USD',
    itemid: String(it.id), shopid: '', catid: null,
    name: it.name, image: it.image,
    price: it.price, strike: null, discount: null,
    monthly: null, sold: it.sold, rating: it.rating, ratingCount: null, // Temu: "11K+ sold" = tổng bán; không có số tháng
    videoUrl: it.videoUrl || '', // video sản phẩm (có sẵn trong response)
    shop: '', isAd: false,
    link: `https://www.temu.com/goods.html?goods_id=${it.id}`,
    similarUrl: `https://www.temu.com/search_result.html?search_key=${encodeURIComponent(it.name || keyword)}`,
  }));
  return { products, blocked: false };
}

function fetchFor(platform, keyword, region, count) {
  if (platform === 'amazon') return fetchAmazon(keyword, region, count);
  if (platform === 'tiktok') return fetchTiktok(keyword, region, count);
  if (platform === 'ali1688') return fetch1688(keyword, count);
  if (platform === 'taobao') return fetchTaobao(keyword, count);
  if (platform === 'temu') return fetchTemu(keyword, region, count);
  if (PLATFORMS[platform] && PLATFORMS[platform].backend) return fetchBackend(platform, keyword, region, count);
  return fetchKeyword(keyword, region, count); // shopee
}

async function research() {
  const keywords = $('kw').value.split(',').map((s) => s.trim()).filter(Boolean);
  const count = Number($('count').value);
  const activePf = [...selectedPlatforms].filter((p) => PLATFORMS[p]?.active);
  if (!activePf.length) { setStatus('Chọn ít nhất 1 sàn đang hỗ trợ.', 'err'); return; }
  if (!keywords.length) { setStatus('Nhập ít nhất 1 từ khoá.', 'err'); return; }
  // Mỗi sàn chỉ chạy region nó phục vụ; Shopee thì region đó phải đã đăng nhập.
  const jobs = [];
  const skipLI = [];
  for (const pf of activePf) {
    const cfg = PLATFORMS[pf];
    const hasReg = Array.isArray(cfg.regions) && cfg.regions.length;
    // Sàn không region (Etsy) → chạy 1 lần với '_'; sàn có region → lấy đúng region đã chọn CHO SÀN ĐÓ.
    const pfRegions = hasReg ? cfg.regions.filter((c) => selectedRegions.has(`${pf}:${c}`)) : ['_'];
    for (const region of pfRegions) {
      if (LOGIN[pf] && loginStatus[`${pf}:${region}`] === false) { skipLI.push(`${pf}:${region}`); continue; }
      for (const kw of keywords) jobs.push({ pf, region, kw });
    }
  }
  if (!jobs.length) { setStatus('Không có (sàn × region) hợp lệ. Sàn có region thì phải chọn region của nó.', 'err'); return; }

  $('go').disabled = true;
  setStatus(`Đang chạy ${jobs.length} truy vấn (sàn × region × từ khoá)…`);

  const all = [];
  let backendDown = false;
  const notices = [];

  // Chạy các SÀN song song, nhưng job trong cùng một sàn thì tuần tự — giữ nhịp giãn chống ban
  // của Shopee (Cách A) và tab nền dùng-lại của Amazon, mà vẫn để Shopee/Amazon/backend chạy chồng.
  const byPf = new Map();
  for (const j of jobs) { if (!byPf.has(j.pf)) byPf.set(j.pf, []); byPf.get(j.pf).push(j); }
  const groups = await Promise.all([...byPf.values()].map(async (group) => {
    const out = [];
    for (const j of group) out.push({ j, r: await fetchFor(j.pf, j.kw, j.region, count) });
    return out;
  }));

  for (const { j, r } of groups.flat()) {
    if (r.backendDown) backendDown = true;
    if (r.notice) notices.push(r.notice);
    if (r.blocked && LOGIN[j.pf]) loginStatus[`${j.pf}:${j.region}`] = false;
    for (const p of r.products) { p.keyword = j.kw; if (!p.score) p.score = score(p); }
    all.push(...r.products);
  }
  $('go').disabled = false;
  renderRegions();

  if (!all.length) {
    const msg = backendDown
      ? 'Backend chưa chạy — Etsy/Facebook cần backend ở localhost:8000 (chạy: uvicorn app.main:app).'
      : notices.length
        ? notices.join(' · ') // hiện lý do thật từ backend (vd Etsy chưa có key)
        : 'Không có kết quả — Shopee: kiểm tra đăng nhập; Amazon: có thể bị chặn tạm/captcha.';
    setStatus(msg, 'err');
    $('table').style.display = 'none';
    return;
  }

  rows = all;
  const kwset = [...new Set(all.map((p) => p.keyword))];
  $('kwfilter').innerHTML = '<option value="__all">Tất cả</option>' + kwset.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join('');
  $('filterWrap').style.display = kwset.length > 1 ? 'inline' : 'none';

  const pfset = [...new Set(all.map((p) => p.platform))];
  const ads = all.filter((p) => p.isAd).length;
  const skipNote = skipLI.length ? ` · bỏ ${skipLI.join('/')}` : '';
  const noticeNote = notices.length ? ' · ' + [...new Set(notices)].join(' · ') : '';
  setStatus(`${all.length} SP · ${pfset.join('+')} · ${kwset.length} từ khoá · ${ads} qc${skipNote} · xếp theo điểm.${noticeNote}`, 'ok');
  render();
  // Giá vốn tạm ẩn (trang find_similar 403 khi replay). Bật lại khi có cách ký.
}

function scoreClass(v) { return v >= 65 ? 'hi' : v >= 40 ? 'mid' : 'lo'; }

function render() {
  const kwPick = $('kwfilter').value || '__all';

  let list = rows.filter((p) => kwPick === '__all' || p.keyword === kwPick);
  list.sort((a, b) => {
    switch (sortKey) {
      case 'name': return a.name.localeCompare(b.name);
      case 'platform': return a.platform.localeCompare(b.platform);
      case 'price': return (b.price || 0) - (a.price || 0);
      case 'discount': return (b.discount || 0) - (a.discount || 0);
      case 'rating': return (b.rating || 0) - (a.rating || 0);
      case 'monthly': return (b.monthly || 0) - (a.monthly || 0);
      case 'sold': return (b.sold || 0) - (a.sold || 0);
      default: return b.score.total - a.score.total;
    }
  });

  // Dựng toàn bộ HTML một lần rồi gán một phát — tránh reflow mỗi dòng khi bảng dài (120+ SP).
  // Handler hover/click gắn theo uỷ quyền trên #rows nên không bị ảnh hưởng khi thay innerHTML.
  $('rows').innerHTML = list.map((p, i) =>
    `<tr>` +
    `<td class="num rank">${i + 1}</td>` +
    `<td class="num"><span class="score ${scoreClass(p.score.total)}">${p.score.total}</span>` +
    `<div class="bar"><i style="width:${p.score.total}%"></i></div>` +
    `<div class="sub">${scoreSub(p)}</div></td>` +
    `<td><div class="prod">` +
    `<img class="thumb" src="${p.image}" data-full="${p.image}" loading="lazy" alt="" />` +
    `<div><a class="name" href="${p.link}" target="_blank" rel="noreferrer">${esc(p.name)}${p.isAd ? '<span class="adtag">Ad</span>' : ''}</a>` +
    `${p.videoUrl ? ` <a class="hasvid" href="${esc(p.videoUrl)}" target="_blank" rel="noreferrer" title="Sản phẩm có video — bấm để xem">▶</a>` : ''}` +
    `<div class="shop">${esc(p.shop)}</div></div></div></td>` +
    `<td><span class="pill">${esc(p.platform)} ${FLAG[p.region] || ''}${p.region ? ' ' + esc(p.region) : ''}</span></td>` +
    `<td class="num">${fmtInt(p.monthly)}</td>` +
    `<td class="num">${fmtInt(p.sold)}</td>` +
    `<td class="num">${p.rating != null ? p.rating.toFixed(1) + '★' : '—'}${p.ratingCount != null ? `<div class="sub">${fmtInt(p.ratingCount)}</div>` : ''}</td>` +
    `<td class="num"><span class="price">${fmtPrice(p.price, curOf(p))}</span>${p.strike ? `<div class="sub strike">${fmtInt(p.strike)}</div>` : ''}</td>` +
    `<td class="num">${p.discount ? `<span class="disc">-${p.discount}%</span>` : '—'}</td>` +
    `<td><button class="sim" data-url="${esc(p.similarUrl)}">↗ Tương tự</button> ` +
    `<button class="sim vid" data-img="${esc(rawImg(p.image))}" data-name="${esc(p.name)}" data-region="${esc(p.region || '')}">🎬 Video</button></td>` +
    `</tr>`
  ).join('');
  $('table').style.display = list.length ? 'table' : 'none';
}

// ---- Hover ảnh: phóng to bám theo con trỏ ----
const zoom = $('zoom');
const zoomImg = zoom.querySelector('img');
function positionZoom(x, y) {
  const w = 332, h = 332, pad = 18;
  let left = x + pad, top = y + pad;
  if (left + w > window.innerWidth) left = x - w - pad;
  if (top + h > window.innerHeight) top = Math.max(pad, window.innerHeight - h - pad);
  zoom.style.left = left + 'px';
  zoom.style.top = top + 'px';
}
$('rows').addEventListener('mouseover', (e) => {
  const img = e.target.closest('img.thumb');
  if (!img || !img.dataset.full) return;
  zoomImg.src = img.dataset.full;
  zoom.style.display = 'block';
  positionZoom(e.clientX, e.clientY);
});
$('rows').addEventListener('mousemove', (e) => { if (zoom.style.display === 'block') positionZoom(e.clientX, e.clientY); });
$('rows').addEventListener('mouseout', (e) => { if (e.target.closest('img.thumb')) zoom.style.display = 'none'; });

// ---- Click trong bảng: "Video" (mở modal video quảng cáo khớp ảnh) hoặc "Tương tự" ----
$('rows').addEventListener('click', (e) => {
  const vid = e.target.closest('button.vid');
  if (vid) {
    openVideoModal({ img: vid.dataset.img, name: vid.dataset.name, region: vid.dataset.region });
    return;
  }
  const sim = e.target.closest('button.sim');
  if (sim && sim.dataset.url) chrome.tabs.create({ url: sim.dataset.url });
});

// Giá vốn NHANH: một tab find_similar duy nhất → gọi recommend_post cho top N cùng lúc trong tab
// đó (nếu trang tự ký fetch). Nhanh hơn nhiều lần mở tab từng sản phẩm.
let costRunning = false;
async function runCostBatch(n) {
  if (costRunning) return;
  const targets = [...rows]
    .sort((a, b) => b.score.total - a.score.total)
    .filter((p) => p.platform === 'Shopee' && p.catid && costCache[p.itemid] === undefined) // giá vốn find_similar chỉ có ở Shopee
    .slice(0, n);
  if (!targets.length) return;

  costRunning = true;
  $('calcTop').disabled = true;
  targets.forEach((p) => { costCache[p.itemid] = 'pending'; });
  render();
  setStatus(`Đang tính giá vốn cho ${targets.length} sản phẩm (1 tab find_similar)…`);

  try {
    const seedUrl = targets[0].similarUrl;
    const payload = targets.map((p) => ({ itemid: p.itemid, shopid: p.shopid, catid: p.catid }));
    const res = await new Promise((r) => chrome.runtime.sendMessage({ type: 'RS_COST_BATCH', seedUrl, products: payload }, (x) => r(x)));
    const results = (res && res.results) || {};

    let ok = 0, forbidden = 0;
    for (const p of targets) {
      const r = results[p.itemid];
      let cost = null;
      if (r && r.status === 200 && r.text) {
        try { const arr = []; collectPrices(JSON.parse(r.text), arr); if (arr.length) cost = Math.min(...arr) / PRICE_SCALE; } catch (e) {}
      }
      if (r && r.status === 403) forbidden++;
      if (cost != null) ok++;
      costCache[p.itemid] = cost == null ? 'none' : cost;
    }
    render();
    if (ok === 0 && forbidden > 0) {
      setStatus('Giá vốn: tất cả bị 403 — trang find_similar KHÔNG tự ký fetch của mình. Báo dev để đổi cách.', 'err');
    } else {
      setStatus(`Giá vốn: ${ok}/${targets.length} ok${forbidden ? `, ${forbidden} bị 403` : ''}.`, 'ok');
    }
  } finally {
    costRunning = false;
    $('calcTop').disabled = false;
  }
}

// ---- Sort khi bấm tiêu đề cột ----
document.querySelectorAll('th[data-k]').forEach((th) => {
  th.addEventListener('click', () => {
    sortKey = th.dataset.k;
    document.querySelectorAll('th').forEach((h) => h.classList.remove('sorted'));
    th.classList.add('sorted');
    render();
  });
});

$('go').addEventListener('click', research);
$('kw').addEventListener('keydown', (e) => { if (e.key === 'Enter') research(); });
$('kwfilter').addEventListener('change', render);
$('refreshLogin').addEventListener('click', refreshLogin);
$('regions').addEventListener('change', (e) => {
  const add = e.target.closest('select.region-add');
  if (!add || !add.value) return;
  selectedRegions.add(`${add.dataset.pf}:${add.value}`);
  renderRegions();
});
$('regions').addEventListener('click', (e) => {
  const chip = e.target.closest('.rgchip');
  if (!chip) return;
  const pf = chip.dataset.pf, code = chip.dataset.code;
  // Chưa đăng nhập (Shopee/TikTok) → mở tab đăng nhập đúng sàn+region đó.
  const spec = LOGIN[pf];
  if (spec && spec.domain[code] && loginStatus[`${pf}:${code}`] === false) { chrome.tabs.create({ url: `https://${spec.domain[code]}/` }); return; }
  const key = `${pf}:${code}`;
  if (selectedRegions.has(key)) {
    // Không để một sàn trống hết region — muốn bỏ hẳn sàn thì bỏ chọn chip sàn ở mục ①.
    if (PLATFORMS[pf].regions.some((c) => c !== code && selectedRegions.has(`${pf}:${c}`))) selectedRegions.delete(key);
  } else selectedRegions.add(key);
  renderRegions();
});
// Mặc định CHỌN-MỘT: bấm sàn nào thì THAY THẾ hẳn sàn đang chọn, giống một nhóm nút radio.
// Bật công tắc "So sánh nhiều sàn" thì quay lại kiểu CỘNG DỒN (toggle add/remove) như trước —
// cần khi người dùng thật sự muốn xếp Shopee cạnh TikTok Shop để so giá.
let multiPlatform = false;

$('platforms').addEventListener('click', (e) => {
  const chip = e.target.closest('.rgchip');
  if (!chip) return;
  const id = chip.dataset.pf, cfg = PLATFORMS[id];
  if (!cfg || !cfg.active) return; // sàn chưa hỗ trợ → không chọn được
  if (multiPlatform) {
    if (selectedPlatforms.has(id)) { if (selectedPlatforms.size > 1) selectedPlatforms.delete(id); }
    else selectedPlatforms.add(id);
  } else if (!(selectedPlatforms.size === 1 && selectedPlatforms.has(id))) {
    selectedPlatforms.clear();
    selectedPlatforms.add(id);
  }
  renderPlatforms();
  updateRegionSection();
  refreshLogin();
});

$('multiPf').addEventListener('change', (e) => {
  multiPlatform = e.target.checked;
  if (!multiPlatform && selectedPlatforms.size > 1) {
    // Tắt so sánh → giữ lại đúng MỘT sàn (sàn đầu tiên trong tập đang chọn).
    const keep = [...selectedPlatforms][0];
    selectedPlatforms.clear();
    selectedPlatforms.add(keep);
  }
  renderPlatforms();
  updateRegionSection();
  refreshLogin();
});

// Khởi tạo: vẽ chip sàn + region theo sàn + check đăng nhập; ?kw từ popup thì chạy sau khi check.
renderPlatforms();
updateRegionSection();
const _kw = new URLSearchParams(location.search).get('kw');
if (_kw) $('kw').value = _kw;
refreshLogin(); // KHÔNG tự research — chờ user bấm

// ===== TAB CONTENT (Facebook Ads) + TAB TÌM BẰNG ẢNH =====
function showTab(which) {
  $('tabProduct').style.display = which === 'product' ? '' : 'none';
  $('tabContent').style.display = which === 'content' ? '' : 'none';
  $('tabImage').style.display = which === 'image' ? '' : 'none';
  $('tabProductBtn').classList.toggle('on', which === 'product');
  $('tabContentBtn').classList.toggle('on', which === 'content');
  $('tabImageBtn').classList.toggle('on', which === 'image');
  if (which === 'image') updateISel();
}
function setCStatus(msg, kind) { $('cstatusText').textContent = msg; $('cstatus').className = 'status' + (kind ? ' ' + kind : ''); }

function renderContent(list) {
  const grid = $('contentGrid');
  grid.innerHTML = '';
  for (const p of list) {
    const days = p.daysActive != null ? `<span>${p.daysActive} ngày chạy</span>` : '';
    const sc = p.score ? `<span class="cscore">${p.score.total}đ</span>` : '';
    const el = document.createElement('div');
    el.className = 'ccard';
    el.innerHTML =
      `<div class="media">${p.image ? `<img src="${p.image}" loading="lazy" alt="">` : ''}</div>` +
      `<div class="cbody">` +
      `<div class="cadv">${esc(p.shop || '—')}</div>` +
      `<div class="ccopy">${esc(p.name || '')}</div>` +
      `<div class="cmeta">${sc}${days}</div>` +
      `<a class="clink" href="${esc(p.link)}" target="_blank" rel="noreferrer">Xem quảng cáo ↗</a>` +
      `</div>`;
    grid.appendChild(el);
  }
}

async function contentResearch() {
  const kw = $('ckw').value.trim();
  const region = $('cregion').value;
  const count = Number($('ccount').value);
  if (!kw) { setCStatus('Nhập keyword.', 'err'); return; }
  $('cgo').disabled = true;
  setCStatus(`Đang tìm content quảng cáo cho "${kw}" (${region})… (FB lần đầu chậm)`);
  const r = await fetchBackend('facebook', kw, region, count);
  $('cgo').disabled = false;
  if (r.backendDown) { setCStatus('Backend chưa chạy — Content cần backend ở localhost:8000.', 'err'); $('contentGrid').innerHTML = ''; return; }
  if (!r.products.length) { setCStatus(r.notice || 'Không có quảng cáo nào khớp từ khoá.', 'err'); $('contentGrid').innerHTML = ''; return; }
  const list = r.products.slice().sort((a, b) => ((b.score && b.score.total) || 0) - ((a.score && a.score.total) || 0));
  setCStatus(`${list.length} quảng cáo · Facebook ${region}${r.notice ? ' · ' + r.notice : ''}`, 'ok');
  renderContent(list);
}

$('tabProductBtn').addEventListener('click', () => showTab('product'));
$('tabContentBtn').addEventListener('click', () => showTab('content'));
$('tabImageBtn').addEventListener('click', () => showTab('image'));
$('cgo').addEventListener('click', contentResearch);
$('ckw').addEventListener('keydown', (e) => { if (e.key === 'Enter') contentResearch(); });

// ===== TAB TÌM BẰNG ẢNH — tìm cùng sản phẩm trên các sàn, xếp theo giá rẻ nhất =====
let imgData = null; // dataURL ảnh đã chọn (để gửi lên adapter khi wire)
let irows = [];
function setIStatus(msg, kind) { $('istatusText').textContent = msg; $('istatus').className = 'status' + (kind ? ' ' + kind : ''); }
function updateISel() {
  const pfs = [...selectedPlatforms].filter((p) => PLATFORMS[p]?.active).map((p) => PLATFORMS[p].label);
  const regs = [...new Set([...selectedRegions].map((k) => k.split(':')[1]))];
  $('iselSummary').textContent = `Sàn: ${pfs.join(', ') || '—'} · Region: ${regs.join(', ') || '—'}`;
}
function setImg(blob) {
  const rd = new FileReader();
  rd.onload = () => {
    imgData = rd.result;
    $('imgPreview').src = imgData; $('imgPreview').style.display = '';
    $('imgClear').style.display = ''; $('imgDrop').textContent = 'Đã chọn ảnh — bấm để đổi ảnh khác';
  };
  rd.readAsDataURL(blob);
}

// Dispatcher image-search theo sàn. CHƯA WIRE: mỗi sàn cần bắt API upload+search-by-image riêng
// (Shopee: Cách A in-tab; 1688/Taobao: login/TMAPI) hoặc dùng Google Lens/SerpApi (backend, mọi web).
async function imageSearchFor(pf, region, img) {
  const label = `${PLATFORMS[pf]?.label || pf}${region && region !== '_' ? ' ' + region : ''}`;
  return { products: [], notice: `${label}: image search chưa wire` };
}

async function imageResearch() {
  if (!imgData) { setIStatus('Chọn hoặc dán 1 ảnh sản phẩm trước.', 'err'); return; }
  const activePf = [...selectedPlatforms].filter((p) => PLATFORMS[p]?.active);
  if (!activePf.length) { setIStatus('Chọn ít nhất 1 sàn ở tab Sản phẩm.', 'err'); return; }
  const jobs = [];
  for (const pf of activePf) {
    const cfg = PLATFORMS[pf];
    const hasReg = Array.isArray(cfg.regions) && cfg.regions.length;
    const pfRegions = hasReg ? cfg.regions.filter((c) => selectedRegions.has(`${pf}:${c}`)) : ['_'];
    for (const region of pfRegions) jobs.push({ pf, region });
  }
  if (!jobs.length) { setIStatus('Không có (sàn × region) hợp lệ.', 'err'); return; }

  $('imgGo').disabled = true;
  setIStatus(`Đang tìm nguồn theo ảnh (${jobs.length} sàn × region)…`);
  const all = [];
  const notices = [];
  for (const j of jobs) {
    const r = await imageSearchFor(j.pf, j.region, imgData);
    if (r.notice) notices.push(r.notice);
    for (const p of (r.products || [])) { if (!p.score) p.score = score(p); all.push(p); }
  }
  $('imgGo').disabled = false;

  irows = all.sort((a, b) => (a.price == null ? Infinity : a.price) - (b.price == null ? Infinity : b.price)); // rẻ nhất lên đầu
  renderImage();
  const note = notices.length ? ' · ' + [...new Set(notices)].join(' · ') : '';
  setIStatus(all.length ? `${all.length} nguồn · xếp theo giá rẻ nhất${note}` : (notices.join(' · ') || 'Chưa có nguồn nào.'), all.length ? 'ok' : 'err');
}

function renderImage() {
  $('irows').innerHTML = irows.map((p, i) =>
    `<tr>` +
    `<td class="num rank">${i + 1}</td>` +
    `<td><div class="prod"><img class="thumb" src="${p.image}" data-full="${p.image}" loading="lazy" alt="" />` +
    `<div><a class="name" href="${p.link}" target="_blank" rel="noreferrer">${esc(p.name)}</a>` +
    `<div class="shop">${esc(p.shop)}</div></div></div></td>` +
    `<td><span class="pill">${esc(p.platform)} ${FLAG[p.region] || ''}${p.region ? ' ' + esc(p.region) : ''}</span></td>` +
    `<td class="num"><span class="price">${fmtPrice(p.price, curOf(p))}</span></td>` +
    `<td><button class="sim" data-url="${esc(p.link)}">↗ Mở</button></td>` +
    `</tr>`
  ).join('');
  $('itable').style.display = irows.length ? 'table' : 'none';
}

$('imgDrop').addEventListener('click', () => $('imgFile').click());
$('imgFile').addEventListener('change', (e) => { const f = e.target.files[0]; if (f) setImg(f); });
$('imgDrop').addEventListener('dragover', (e) => { e.preventDefault(); $('imgDrop').classList.add('drag'); });
$('imgDrop').addEventListener('dragleave', () => $('imgDrop').classList.remove('drag'));
$('imgDrop').addEventListener('drop', (e) => {
  e.preventDefault(); $('imgDrop').classList.remove('drag');
  const f = e.dataTransfer.files[0]; if (f && f.type.startsWith('image/')) setImg(f);
});
window.addEventListener('paste', (e) => {
  if ($('tabImage').style.display === 'none') return; // chỉ nhận dán khi đang ở tab ảnh
  for (const it of (e.clipboardData ? e.clipboardData.items : [])) {
    if (it.type.startsWith('image/')) { setImg(it.getAsFile()); break; }
  }
});
$('imgClear').addEventListener('click', () => {
  imgData = null; $('imgPreview').style.display = 'none'; $('imgClear').style.display = 'none';
  $('imgDrop').textContent = 'Kéo-thả ảnh vào đây · hoặc dán (Ctrl+V) · hoặc bấm chọn file';
});
$('irows').addEventListener('click', (e) => {
  const b = e.target.closest('button.sim'); if (b && b.dataset.url) chrome.tabs.create({ url: b.dataset.url });
});
$('imgGo').addEventListener('click', imageResearch);
$('iGoProduct').addEventListener('click', () => showTab('product'));

// ===== MODAL VIDEO — "video quảng cáo khớp ẢNH sản phẩm" cho một dòng ở tab Sản phẩm =====
// Gọi backend /api/ads/match-image: seed keyword (tên SP) lấy ứng viên Facebook/TikTok, rồi backend
// so pHash poster video với ẢNH sản phẩm, chỉ trả video TRÙNG ảnh. Cần backend chạy (localhost:8000).
let vidToken = 0; // chống race: mỗi lần mở gắn một token, chỉ render kết quả của token mới nhất.
let vidState = null; // { p, usedKw, fbAds, marketAds } — giữ FB/Sàn để đổi NƯỚC chỉ tải lại TikTok.

function proxyMedia(url) { return url ? `${BACKEND}/api/media?url=${encodeURIComponent(url)}` : ''; }
function setVidStatus(msg, kind) { $('vidStatusText').textContent = msg; $('vidStatus').className = 'status' + (kind ? ' ' + kind : ''); }
function closeVideoModal() { $('vidModal').classList.remove('on'); $('vidGrid').innerHTML = ''; vidState = null; }

async function openVideoModal(p) {
  const my = ++vidToken;
  $('vidTitle').textContent = p.name || '(không tên)';
  $('vidGrid').innerHTML = '';
  $('vidModal').classList.add('on');

  setVidStatus('Đang lọc từ khoá (Gemini) và lấy video quảng cáo… (lần đầu hơi chậm)');

  // Facebook Ad Library nhận country; dùng region của SP nếu là mã 2 chữ, không thì VN.
  const region = /^[A-Z]{2}$/.test((p.region || '').toUpperCase()) ? p.region.toUpperCase() : 'VN';
  fillVidRegions(region); // ô chọn NƯỚC cho TikTok — mặc định = nước của SP

  // Gửi TIÊU ĐỀ sản phẩm (p.name): backend gọi Gemini rút thành từ khoá ĐÚNG LOẠI + mã model
  // (vd "tai nghe gaming chụp tai B39") rồi mới search FB. SP không có tên → rơi về ô tìm kiếm.
  // CHỈ Facebook: TikTok Creative Center không search được theo từ khoá nếu thiếu TIKTOK_COOKIE
  // → trả top-ads ngẫu nhiên (rác, không liên quan SP). Bật lại 'facebook,tiktok' sau khi khai cookie.
  const params = new URLSearchParams({
    platforms: 'facebook', countries: region, limit: '24', videoOnly: 'true',
  });
  if (p.name) params.set('title', p.name);
  else params.set('keyword', ($('kw') && $('kw').value || '').trim());

  let data;
  try {
    const r = await fetch(`${BACKEND}/api/ads/search?${params.toString()}`);
    data = await r.json();
    if (my !== vidToken) return; // đã mở modal khác → bỏ kết quả cũ
    if (!r.ok) { setVidStatus((data && data.error) || `backend HTTP ${r.status}`, 'err'); return; }
  } catch (e) {
    if (my !== vidToken) return;
    setVidStatus('Backend chưa chạy (localhost:8000) — cần backend để lấy video quảng cáo.', 'err');
    return;
  }

  const fbAds = data.ads || [];
  const usedKw = data.keyword || '(từ khoá)';

  // Video SẢN PHẨM từ SÀN TMĐT: lấy thẳng từ list đã search (rows) — SP nào có videoUrl (Shopee/
  // Taobao/1688/Temu). Không phụ thuộc NƯỚC TikTok nên tính một lần, giữ nguyên khi đổi nước.
  const marketAds = (Array.isArray(rows) ? rows : [])
    .filter((x) => x && x.videoUrl)
    .map((x) => {
      // Temu… videoUrl là FILE mp4 → nhúng phát; Shopee videoUrl là TRANG SP → chỉ link (video
      // Shopee chỉ xem ở trang chi tiết, backend sau này trỏ vào link đó lấy video).
      const isFile = /\.mp4|\.m3u8|\/video\//i.test(x.videoUrl);
      return {
        platform: String(x.platform || 'sàn').toLowerCase(),
        advertiser: x.shop || x.platform || '', title: x.name, body: x.name,
        permalink: x.link || x.videoUrl,
        creatives: [isFile ? { kind: 'video', url: x.videoUrl, posterUrl: x.image || '' } : { kind: 'image', posterUrl: x.image || '' }],
      };
    });

  // Lưu FB + Sàn + region GỐC (của SP) để đổi NƯỚC TikTok chỉ tải lại phần TikTok. `homeRegion`
  // dùng để quyết định mode: chọn khác nước SP → auto hashtag-only (đỡ cá nhân hoá theo account/IP).
  vidState = { p, usedKw, fbAds, marketAds, homeRegion: region };
  await loadModalTiktok(region);
}

// Danh sách NƯỚC cho ô chọn TikTok — dịch keyword/hashtag theo ngôn ngữ nước này (backend _REGION_LANG).
const TIKTOK_REGIONS = ['VN', 'TH', 'ID', 'MY', 'PH', 'SG', 'TW', 'US', 'GB', 'BR', 'MX', 'CO', 'CL'];
function fillVidRegions(selected) {
  const sel = $('vidRegion');
  if (!sel) return;
  const regs = TIKTOK_REGIONS.includes(selected) ? TIKTOK_REGIONS : [selected, ...TIKTOK_REGIONS];
  sel.innerHTML = regs.map((r) => `<option value="${r}"${r === selected ? ' selected' : ''}>${FLAG[r] || ''} ${COUNTRY[r] || r}</option>`).join('');
  sel.value = selected;
}

// Tải phần TikTok theo NƯỚC đã chọn: backend Gemini dịch keyword + hashtag sang ngôn ngữ nước đó,
// extension lặp search + dedup link, rồi render CHUNG với FB + Sàn (đã có trong vidState). Đổi ô
// nước = gọi lại hàm này (FB/Sàn giữ nguyên, chỉ TikTok đổi).
async function loadModalTiktok(region) {
  const st = vidState;
  if (!st) return;
  const my = ++vidToken; // đổi nước = huỷ lần tải TikTok trước (chống race)
  const p = st.p, usedKw = st.usedKw;

  // MỘT cụm, MỘT lượt tìm.
  //
  // Bản trước gom 3-4 từ khoá cộng 5-7 hashtag rồi chạy tới sáu lượt tìm nối nhau, mỗi lượt là
  // một lần mở tab, gõ chữ, cuộn — người dùng ngồi chờ mấy phút cho một sản phẩm. Mà các cụm
  // thêm ("tai nghe redmi chính hãng", "đánh giá redmi buds 6 play") chỉ là biến tấu quanh cùng
  // một thứ, nên chúng kéo về gần đúng nhóm video mà cụm đầu đã kéo về.
  //
  // Backend giờ trả đúng một cụm đã dịch sang tiếng của nước đang chọn (`/api/ads/video-keywords`).
  // Hỏng thì rơi về `usedKw` — cụm brand+model mà Gemini rút từ tiêu đề ở bước trước.
  let tkTerm = usedKw;
  try {
    const vkParams = new URLSearchParams({ title: p.name || usedKw, region });
    const vr = await fetch(`${BACKEND}/api/ads/video-keywords?${vkParams.toString()}`);
    if (my !== vidToken) return;
    if (vr.ok) {
      const vk = await vr.json();
      const first = (Array.isArray(vk.keywords) ? vk.keywords : []).map((x) => String(x || '').trim()).filter(Boolean)[0];
      if (first) tkTerm = first;
    }
  } catch (e) { /* backend lỗi → dùng usedKw */ }

  const flag = FLAG[region] || '', country = COUNTRY[region] || region;
  setVidStatus(`FB ${st.fbAds.length} · Sàn ${st.marketAds.length} · đang tìm TikTok ${flag} ${country} · “${tkTerm}”… (tool tự cuộn)`);
  let tkItems = [], tkNote = '', tkCounts = null, tkMode = null;
  try {
    const tk = await new Promise((res) => chrome.runtime.sendMessage({ type: 'RS_TIKTOK', keyword: tkTerm, keywords: [tkTerm], region, mode: 'mixed', count: 100 }, (x) => res(x)));
    if (my !== vidToken) return;
    tkItems = (tk && tk.items) || [];
    tkCounts = (tk && tk.counts) || null;
    tkMode = (tk && tk.mode) || 'mixed';
    if (tk && tk.blocked && tk.error) tkNote = ' · TikTok: ' + tk.error;
  } catch (e) { tkNote = ' · TikTok: extension chưa sẵn sàng'; }

  // Chuẩn hoá item TikTok về dạng "ad" để render chung; permalink = LINK VIDEO THẬT.
  // langMatch chuyển sang creative để renderVideos gắn badge (không đổi thứ tự — đã sort ở background).
  const tkAds = tkItems.map((it) => ({
    platform: 'tiktok', id: it.id, advertiser: it.author || 'TikTok', title: it.name, body: it.name,
    permalink: it.videoUrl, langMatch: it.langMatch || 'neutral', regionTag: region,
    creatives: [{ kind: 'video', posterUrl: it.image || '' }],
  }));

// TikTok Ads (Creative Center) ĐÃ GỠ khỏi đây, 2026-08-24.
  //
  // Không phải vì hỏng — sau khi sửa thì nó chộp được 18 quảng cáo thật, đủ video và ảnh bìa.
  // Gỡ vì nó không trả lời được câu hỏi của cửa sổ này. Request tìm-theo-từ-khoá của Creative
  // Center có chữ ký (`user-sign`) phủ cả query string, nên từ đây chỉ đọc được ~20 Top Ads của
  // cả nước rồi lọc phía mình. Đo: "kem chống nắng" 0/18, "tai nghe" 0/18, "áo" 7/18 — và 7 kia
  // chỉ vì "áo" là chuỗi con quá phổ biến. Tức là gần như luôn rỗng, mà vẫn tốn một lượt mở tab
  // cộng tải lại trang.
  //
  // `RS_TIKTOK_CC` vẫn còn ở `extension/background.js` cùng toàn bộ ghi chú đo đạc, phòng khi
  // sau này Creative Center mở đường tìm không cần ký.
  const ccAds = [];

  st.tkAds = tkAds; // lưu để nút 🎥 Douyin có thể gộp thêm mà không xoá TikTok đang có
  st.ccAds = ccAds;
  // CC lên đầu (country filter thật) → organic TikTok → Douyin → sàn.
  const all = st.fbAds.concat(ccAds).concat(tkAds).concat(st.dyAds || []).concat(st.marketAds);
  if (!all.length) {
    setVidStatus(`Không có video cho "${usedKw}" ${flag} ${country}.${tkNote} Thử nước khác hoặc SP khác.`, 'err');
    return;
  }
  // Nhắc rõ vì sao có video khác ngôn ngữ: TikTok cá nhân hoá theo account/IP, không theo URL.
  const langBreak = tkCounts
    ? ` (khớp ${flag} ${tkCounts.match} · trung tính ${tkCounts.neutral} · khác ngôn ngữ ${tkCounts.other})`
    : '';
  const ccBreak = ccAds.length ? ` · CC ${flag}${ccAds.length}` : '';
  setVidStatus(`${all.length} video · "${usedKw}" · TikTok ${flag}${country} ${tkItems.length} · ${tkMode || modeLabel}${langBreak}${ccBreak} · FB ${st.fbAds.length} · Sàn ${st.marketAds.length}${tkNote}`, 'ok');
  renderVideos(all);
}

function renderVideos(ads) {
  const grid = $('vidGrid');
  grid.innerHTML = '';
  for (const ad of ads) {
    const creatives = ad.creatives || [];
    const video = creatives.find((c) => c.kind === 'video' && c.url);
    // Poster: ưu tiên poster của video phát được → poster của bất kỳ creative nào (TikTok chỉ có
    // poster + permalink, không có url phát trực tiếp) → ảnh tĩnh.
    const poster = (video && video.posterUrl) ||
      (creatives.find((c) => c.posterUrl) || {}).posterUrl ||
      (creatives.find((c) => c.url) || {}).url || '';
    const days = ad.daysActive != null ? `<span>${ad.daysActive} ngày chạy</span>` : '';
    const match = typeof ad.matchScore === 'number' ? `<span class="mbadge">🎯 ${ad.matchScore}% khớp ảnh</span>` : '';
    // Badge KHI video có mô tả khác ngôn ngữ nước đang chọn (TikTok cá nhân hoá theo account/IP).
    // Không dìm/bỏ, chỉ nhắc user: "cái này lệch nước, coi cẩn thận".
    const langBadge = (ad.langMatch === 'other' && ad.regionTag)
      ? `<span class="mbadge langoff" title="Mô tả không phải tiếng ${COUNTRY[ad.regionTag] || ad.regionTag} — TikTok trả theo account/IP của bạn">⚠ khác ngôn ngữ</span>`
      : '';

    // TikTok: KHÔNG có url phát trực tiếp → hiện poster + nút ▶; bấm ▶ sẽ nhúng player embed
    // (tiktok.com/embed/v2/<id>) phát NGAY TẠI CHỖ. Poster load thẳng (no-referrer), không qua proxy.
    const isTk = ad.platform === 'tiktok' && ad.id;
    let media;
    if (isTk) {
      media =
        (poster ? `<img src="${esc(poster)}" loading="lazy" alt="" referrerpolicy="no-referrer">` : `<div class="tk-ph">TikTok</div>`) +
        `<button class="play-overlay" data-tkid="${esc(ad.id)}" aria-label="Phát video TikTok"><span>▶</span></button>`;
    } else if (video) {
      media = `<video controls preload="none" ${poster ? `poster="${esc(proxyMedia(poster))}"` : ''} src="${esc(proxyMedia(video.url))}"></video>`;
    } else {
      media = poster ? `<img src="${esc(proxyMedia(poster))}" loading="lazy" alt="">` : '';
    }

    const el = document.createElement('div');
    el.className = 'ccard';
    el.innerHTML =
      `<div class="media">${match}${langBadge}${media}</div>` +
      `<div class="cbody">` +
      `<div class="cadv">${esc(ad.advertiser || '—')}</div>` +
      `<div class="ccopy">${esc(ad.title || ad.body || '')}</div>` +
      `<div class="cmeta"><span class="pill">${esc(PF_LABEL[ad.platform] || ad.platform)}</span>${days}</div>` +
      (ad.permalink ? `<a class="clink" href="${esc(ad.permalink)}" target="_blank" rel="noreferrer">${isTk ? 'Mở trên TikTok ↗' : 'Xem quảng cáo ↗'}</a>` : '') +
      `</div>`;
    grid.appendChild(el);
  }
}

// Bấm ▶ trên card TikTok → thay poster bằng player embed của TikTok (phát ngay tại chỗ).
// Video nào TikTok cho nhúng thì phát được; video app-only/riêng tư thì player báo, đành mở app.
$('vidGrid').addEventListener('click', (e) => {
  const btn = e.target.closest('.play-overlay[data-tkid]');
  if (!btn) return;
  const id = btn.getAttribute('data-tkid');
  const box = btn.closest('.media');
  if (box && id) {
    box.innerHTML = `<iframe src="https://www.tiktok.com/embed/v2/${encodeURIComponent(id)}" style="width:100%;height:100%;border:0;background:#000" allow="autoplay; encrypted-media; fullscreen" scrolling="no"></iframe>`;
  }
});

$('vidClose').addEventListener('click', closeVideoModal);
// Đổi NƯỚC TikTok → dịch keyword + hashtag sang ngôn ngữ nước đó rồi tìm lại (FB/Sàn giữ nguyên).
$('vidRegion').addEventListener('change', (e) => { if (vidState) loadModalTiktok(e.target.value); });
$('vidDouyin').addEventListener('click', () => { if (vidState) loadModalDouyin(); });

// Bấm 🎥 Douyin: backend Gemini dịch tiêu đề SP sang từ khoá/hashtag TIẾNG TRUNG (region=CN), gửi
// cho background search Douyin. Chạy tách khỏi TikTok — user chủ động bấm (Douyin hay verify, đừng
// tự chạy mỗi lần mở modal). Kết quả gộp thêm vào grid, không xoá TikTok/FB đã có.
async function loadModalDouyin() {
  const st = vidState;
  if (!st) return;
  const p = st.p, usedKw = st.usedKw;
  const my = ++vidToken;

  // MỘT cụm, dịch sang tiếng Trung (CN) — cùng lý do như TikTok: mỗi cụm là một lượt mở tab,
  // gõ, cuộn, và Douyin còn hay chen màn xác minh 滑块 giữa chừng.
  let dyTerm = usedKw;
  try {
    const vkParams = new URLSearchParams({ title: p.name || usedKw, region: 'CN' });
    const vr = await fetch(`${BACKEND}/api/ads/video-keywords?${vkParams.toString()}`);
    if (my !== vidToken) return;
    if (vr.ok) {
      const vk = await vr.json();
      const first = (Array.isArray(vk.keywords) ? vk.keywords : []).map((x) => String(x || '').trim()).filter(Boolean)[0];
      if (first) dyTerm = first;
    }
  } catch (e) { /* backend lỗi → dùng usedKw (tiếng Việt, Douyin vẫn thử) */ }

  setVidStatus(`Đang lấy Douyin (抖音) cho “${dyTerm}”… (nếu ra 滑块 verify, kéo trong tab)`);
  let dyItems = [], dyNote = '';
  try {
    const dy = await new Promise((res) => chrome.runtime.sendMessage({ type: 'RS_DOUYIN', keyword: dyTerm, keywords: [dyTerm], anchor: dyTerm, count: 60 }, (x) => res(x)));
    if (my !== vidToken) return;
    dyItems = (dy && dy.items) || [];
    if (dy && dy.blocked && dy.error) dyNote = ' · Douyin: ' + dy.error;
  } catch (e) { dyNote = ' · Douyin: extension chưa sẵn sàng'; }

  // Chuẩn hoá Douyin item về "ad" — Douyin video KHÔNG có player embed public như TikTok, nên chỉ
  // hiện poster + link mở trên Douyin. platform='douyin' để card không dính nhánh play-overlay TikTok.
  const dyAds = dyItems.map((it) => ({
    platform: 'douyin', id: it.id, advertiser: 'Douyin', title: it.name, body: it.name,
    permalink: it.videoUrl, langMatch: 'match', regionTag: 'CN',
    creatives: [{ kind: 'image', posterUrl: it.image || '' }],
  }));

  // Gộp thêm vào grid, dedup theo (platform,id) để tránh render trùng nếu user bấm 2 lần.
  const existing = new Set();
  const merge = (arr) => arr.filter((a) => {
    const k = `${a.platform}:${a.id || a.permalink}`;
    if (existing.has(k)) return false; existing.add(k); return true;
  });
  // Lấy lại list hiện đang render bằng cách rebuild từ state (không có "current ads" store — dựng lại).
  // Đơn giản: gọi lại loadModalTiktok chưa xong sẽ đá kết quả cũ; giải pháp: render trực tiếp bằng gộp
  // vào vidState.dyAds và trigger re-render qua nút.
  st.dyAds = merge((st.dyAds || []).concat(dyAds));
  const all = st.fbAds.concat(st.tkAds || []).concat(st.dyAds).concat(st.marketAds);
  setVidStatus(`${all.length} video · Douyin ${dyItems.length}${dyNote}`, dyItems.length ? 'ok' : 'err');
  renderVideos(all);
}
$('vidModal').addEventListener('click', (e) => { if (e.target === $('vidModal')) closeVideoModal(); });
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('vidModal').classList.contains('on')) closeVideoModal(); });

})();
