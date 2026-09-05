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
 * AUTH GATE — chưa đăng nhập thì đá về /login/.
 *
 * Kiểm cả `rs_token` (cấu hình Supabase, có JWT) và `rs_username` (chế độ chỉ-localStorage
 * khi backend chưa cấu hình Supabase, login page tự set fallback). Thiếu cả hai → chưa đăng
 * nhập → redirect. Đặt Ở ĐẦU FILE để không code nào chạy trước khi có user.
 * ===========================================================================
 */
if (!localStorage.getItem('rs_token') && !localStorage.getItem('rs_email')) {
  window.top.location.replace('/login');
  return;
}

// Tên user + đăng xuất + link Admin nay nằm ở SIDEBAR (khung Next bọc ngoài iframe), không ở
// header trang này nữa — nhờ vậy chúng hiện ở MỌI tab, không riêng tab Sản phẩm. Xem
// components/layout/Sidebar.tsx.

// Helper gọi backend có kèm JWT (nếu có). Dùng chung cho mọi fetch tới /api/* sau này.
window.rsAuthFetch = async function (url, options = {}) {
  const token = localStorage.getItem('rs_token');
  const headers = Object.assign({}, options.headers || {});
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const r = await fetch(url, Object.assign({}, options, { headers }));
  // 401 = token hết hạn hoặc sai → về login.
  if (r.status === 401) {
    ['rs_token', 'rs_email', 'rs_display', 'rs_role', 'rs_user_id', 'rs_username'].forEach((k) => localStorage.removeItem(k));
    window.top.location.replace('/login');
    throw new Error('Phiên đã hết hạn');
  }
  return r;
};

// Fire-and-forget analytics tracker. Backend tự xử user_id từ JWT; không có JWT vẫn track ẩn danh.
window.rsTrack = function (eventType, meta) {
  try {
    const body = JSON.stringify({ event_type: eventType, meta: meta || {} });
    const token = localStorage.getItem('rs_token');
    fetch('/api/analytics/track', {
      method: 'POST',
      headers: Object.assign(
        { 'Content-Type': 'application/json' },
        token ? { 'Authorization': 'Bearer ' + token } : {},
      ),
      body,
      keepalive: true,  // cho phép request hoàn tất khi user điều hướng đi
    }).catch(() => {});
  } catch (e) {}
};

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

/**
 * RELAY: không có extension trên MÁY NÀY, nhưng có một máy-thợ (trình duyệt khác đã cài
 * extension + đăng nhập sàn, ở IP dân cư) đang online. Khi đó mọi lệnh `RS_*` được đẩy qua
 * `/api/relay/submit` tới máy-thợ thay vì `postMessage` cục bộ. Bật ở `DOMContentLoaded` bên
 * dưới, chỉ khi PING cục bộ trượt MÀ `/api/relay/status` báo có thợ.
 *
 * `relaySend` trả về ĐÚNG hình dạng như `rsSend`: chính object mà `background.js` trả cho lệnh
 * đó (vd Shopee: { ok, texts, videoItems, blocked, error }), nên phần parse phía dưới không
 * phân biệt được nó tới từ extension cục bộ hay từ máy-thợ.
 */
let RELAY_MODE = false;

async function relaySend(msg) {
  try {
    // rsAuthFetch kèm JWT: khi backend bật auth, /submit đòi đăng nhập (máy-thợ chạy trên IP dân
    // cư đã đăng nhập sàn, không mở cho ẩn danh). 401 → về login, đúng như mọi lệnh khác.
    const r = await window.rsAuthFetch('/api/relay/submit', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(msg),
    });
    const j = await r.json();
    return j && j.ok ? j.result : null;
  } catch (e) {
    console.warn('[research] relay lỗi:', e);
    return null;
  }
}

/** Gửi một lệnh tới extension — cục bộ (postMessage) hoặc qua máy-thợ (relay). */
function dispatch(msg) {
  return RELAY_MODE ? relaySend(msg) : rsSend(msg);
}

const chrome = {
  runtime: {
    sendMessage(msg, callback) {
      dispatch(msg).then((result) => { if (callback) callback(result); });
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
      dispatch({ type: 'RS_COOKIE', url, name }).then((r) => callback((r && r.cookie) || null));
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

// Quyết định đi đường nào: extension cục bộ, hay relay tới máy-thợ. PHẢI await xong TRƯỚC khi
// gọi `refreshLogin()` lần đầu — nếu không, login check ban đầu chạy lúc RELAY_MODE còn false,
// đi đường local (không extension) và trả ✕ cho mọi sàn. Gọi ở cuối file: `detectMode().then(refreshLogin)`.
async function detectMode() {
  // 1) Có extension NGAY TRÊN MÁY NÀY → dùng thẳng, không cần relay.
  if (await rsExtensionReady()) return;

  // 2) Không có extension cục bộ → thử máy-thợ qua relay. Có thợ thì chạy bình thường (im lặng),
  //    chỉ đổi đường đi ở `dispatch`. User không cần biết crawl chạy ở máy khác.
  try {
    const r = await fetch('/api/relay/status', { cache: 'no-store' });
    const s = await r.json();
    if (s && s.workerOnline) {
      RELAY_MODE = true;
      const bar2 = document.getElementById('status');
      const text2 = document.getElementById('statusText');
      if (bar2 && text2) {
        bar2.classList.remove('err');
        text2.textContent = '🔗 Máy này không có extension — đang dùng máy-thợ chung (relay). Bấm Research như bình thường.';
      }
      return;
    }
  } catch (e) {
    /* backend không phản hồi — rơi xuống thông báo bên dưới */
  }

  // 3) Không extension, không thợ → nói rõ CẢ HAI đường.
  const bar = document.getElementById('status');
  const text = document.getElementById('statusText');
  if (!bar || !text) return;
  bar.classList.add('err');
  text.textContent =
    'Các sàn cần phiên đăng nhập (Shopee, TikTok Shop, Amazon, Taobao, 1688, Temu) sẽ không chạy: ' +
    'máy này chưa cài extension, và cũng chưa có máy-thợ nào online. Cách 1: cài extension ở ' +
    'chrome://extensions → Developer mode → Load unpacked → thư mục extension/. Cách 2: mở trang ' +
    '/worker trên một máy đã cài extension + đăng nhập sàn để nó làm máy-thợ chung.';
}

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

// Modal Giá vốn: tỉ giá ¥(CNY)→TIỀN CỦA SÀN + ngưỡng % (giá nhập/giá bán). Giá vốn 1688 là ¥ nên
// phải quy về ĐÚNG tiền của sàn đối thủ mới chia ra % — mỗi tiền một tỉ giá riêng. Mặc định ~2026;
// user chỉnh ở modal, lưu localStorage THEO TỪNG TIỀN (rs_cost_rate_<CUR>). Ngưỡng % dùng chung.
const COST_RATE_DEFAULTS = { VND: 3900, PHP: 7.9, THB: 4.9, MYR: 0.62, IDR: 2200, SGD: 0.19, TWD: 4.4, USD: 0.14, GBP: 0.11, EUR: 0.13, BRL: 0.79, MXN: 2.6, JPY: 21 };
const COST_THRESH_DEFAULT = 30;
function costRate(cur) {
  cur = cur || 'VND';
  try { const v = parseFloat(localStorage.getItem('rs_cost_rate_' + cur)); if (v > 0) return v; } catch (e) {}
  return COST_RATE_DEFAULTS[cur] || COST_RATE_DEFAULTS.VND;
}
function costThresh() { try { const v = parseFloat(localStorage.getItem('rs_cost_thresh')); return v > 0 ? v : COST_THRESH_DEFAULT; } catch (e) { return COST_THRESH_DEFAULT; } }

// Cấu hình sàn: active = đã có adapter; regions = mảng nước (có region), [] = nội địa/toàn cầu
// (không chọn region), 'any' = lọc mọi nước (Facebook). Region động theo sàn đang chọn.
//
// THỨ TỰ NƯỚC LÀ CÓ CHỦ Ý: Việt Nam trước, rồi Philippines, rồi phần còn lại. Đây là hai thị
// trường đang làm thật, và thứ tự này không chỉ để đỡ phải tìm — nước ĐẦU TIÊN chính là nước
// được chọn sẵn khi bấm vào một sàn lần đầu (xem chỗ chọn sàn ở `renderPlatforms`). Đảo thứ
// tự là đảo luôn mặc định, nên đừng sắp lại theo bảng chữ cái cho "gọn".
const PLATFORMS = {
  shopee: { label: 'Shopee', active: true, regions: ['VN', 'PH', 'TH', 'ID', 'MY', 'SG', 'TW', 'BR', 'MX', 'CO', 'CL'] },
  tiktok: { label: 'TikTok Shop', active: true, regions: ['VN', 'PH', 'TH', 'ID', 'MY', 'SG', 'US', 'GB'] },
  // Facebook nằm CHUNG hàng chọn sàn như mọi nguồn khác. Trước đây nó bị tách ra một tab
  // riêng ("Content (FB Ads)") vì dữ liệu khác hẳn — quảng cáo đang chạy, không có giá,
  // không có lượt bán. Nhưng `fetchBackend` vốn đã chuẩn hoá nó về đúng hình dạng sản phẩm
  // và backend đã tự chấm điểm theo đời quảng cáo, nên nó chạy được ngay trong bảng chung.
  // Facebook ẩn khỏi chọn sàn tìm sản phẩm (theo yêu cầu) — luồng video FB (VID_SOURCES) vẫn giữ.
  // facebook: { label: 'Facebook', active: true, backend: true, regions: ['VN', 'US', 'GB', 'DE', 'FR', 'BR'] },
  amazon: { label: 'Amazon', active: true, regions: ['US', 'GB', 'DE', 'JP', 'FR', 'IT', 'ES', 'CA'] },
  etsy: { label: 'Etsy', active: true, backend: true, regions: [] },
  taobao: { label: 'Taobao', active: true, experimental: true, regions: [] },
  ali1688: { label: '1688 (giá sỉ)', active: true, regions: [] },
  temu: { label: 'Temu', active: true, experimental: true, regions: ['US', 'GB', 'DE', 'FR', 'JP'] }, // gõ-search-trong-tab để bắn API rồi chộp
};

const loginStatus = {}; // "pf:CODE" -> true | false | undefined
// Mặc định KHÔNG chọn sàn nào — người dùng tự bấm sàn muốn chạy (chọn 1 → chạy 1, chọn nhiều →
// chạy nhiều). Trước đây Shopee được chọn sẵn; bỏ để khởi đầu là một bảng trắng, không giả định.
const selectedPlatforms = new Set();
// Sàn cần đăng nhập (Cách A) → check tức thì qua một cookie đặc trưng của phiên. Sàn công khai
// (Amazon) không có ở đây. Thêm sàn login = thêm 1 dòng {domain, cookie, ok}.
const LOGIN = {
  shopee: { domain: DOMAIN, cookie: 'SPC_U', ok: (v) => v && v !== '-' },
  tiktok: { domain: TT_DOMAIN, cookie: 'oec_seller_id_unified_seller_env', ok: (v) => !!v },
};
// Region chọn theo TỪNG sàn — key "pf:CODE". Mỗi sàn có bộ region riêng (Shopee 11 nước, Amazon
// 8 nước…) nên KHÔNG dùng chung một tập region; nhờ vậy Shopee-VN và Amazon-US độc lập với nhau.
// Rỗng lúc đầu — chưa có sàn nào được chọn nên chưa có nước. Khi user chọn một sàn có region,
// `updateRegionSection` tự thêm nước đầu tiên của sàn đó (giữ tối thiểu 1 nước/sàn để chạy được).
const selectedRegions = new Set();
function curOf(p) { return p.currency || CURRENCY[p.region] || 'VND'; }

// Các sàn (tab Sản phẩm) đang chọn mà CÓ region — để gom nhóm region theo sàn.
function regionPlatforms() {
  return [...selectedPlatforms].filter((p) => {
    const cfg = PLATFORMS[p];
    return cfg && Array.isArray(cfg.regions) && cfg.regions.length;
  });
}

function renderPlatforms() {
  const box = document.getElementById('platforms');
  if (!box) return;
  box.innerHTML = '';
  for (const [id, cfg] of Object.entries(PLATFORMS)) {
    const rg = cfg.regions === 'any' ? 'mọi nước' : (cfg.regions.length ? `${cfg.regions.length} nước` : 'nội địa/không region');
    const chip = document.createElement('button');
    chip.className = 'rgchip' + (cfg.active ? '' : ' dim');
    chip.dataset.pf = id;
    chip.dataset.on = selectedPlatforms.has(id) ? '1' : '0';
    chip.innerHTML = `<span class="tick" aria-hidden>✓</span>${esc(cfg.label)}`;
    chip.title = `${cfg.label} · ${rg}${cfg.active ? '' : ' — chưa hỗ trợ'}`;
    box.appendChild(chip);
  }
}

// Region đổi theo sàn: mỗi sàn có region là một NHÓM riêng. Giữ tối thiểu 1 region/sàn.
function updateRegionSection() {
  const pfs = regionPlatforms();
  const section = document.getElementById('regionSection');
  if (!pfs.length) { if (section) section.style.display = 'none'; return; } // Taobao/1688/Etsy → ẩn region
  if (section) section.style.display = ''; // trả về display của CSS (.step là block)
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

// Vẽ nước theo NHÓM sàn, dùng đúng dáng chip của bước 1 — chọn nước và chọn sàn là cùng một
// thao tác, nên không bắt người dùng học hai kiểu điều khiển.
//
// Từng thử ô thả xuống "+ Thêm nước" để đỡ rối khi Shopee có 11 nước. Bỏ, vì nó giấu mất thứ
// đang có: nhìn vào không biết ngay còn chọn được nước nào, phải mở ra mới thấy. Chip hiện hết
// thì tốn hai hàng, nhưng đọc một lượt là xong.
function renderRegions() {
  const box = document.getElementById('regions');
  if (!box) return;
  box.innerHTML = '';
  const pfs = regionPlatforms();
  for (const pf of pfs) {
    const cfg = PLATFORMS[pf];
    const group = document.createElement('div');
    group.className = 'rgroup';

    // Nhãn sàn chỉ cần khi có TỪ HAI sàn — một sàn thì nó lặp lại đúng thứ vừa đọc ở bước 1.
    if (pfs.length > 1) {
      const label = document.createElement('span');
      label.className = 'rglabel';
      label.textContent = cfg.label;
      group.appendChild(label);
    }

    for (const code of cfg.regions) {
      const isLoginRegion = !!(LOGIN[pf] && LOGIN[pf].domain[code]); // Shopee/TikTok cần đăng nhập; Amazon công khai
      const st = loginStatus[`${pf}:${code}`];
      const on = selectedRegions.has(`${pf}:${code}`);
      const badge = !isLoginRegion
        ? '<span class="sub">🌐</span>'
        : st === true ? '<span class="ok">✓</span>' : st === false ? '<span class="no">✕</span>' : '<span class="sub">…</span>';
      const chip = document.createElement('button');
      chip.className = 'rgchip';
      chip.dataset.pf = pf;
      chip.dataset.code = code;
      chip.dataset.on = on ? '1' : '0';
      chip.innerHTML = `<span class="tick" aria-hidden>✓</span>${FLAG[code] || ''} ${esc(COUNTRY[code] || code)} ${badge}`;
      chip.title = !isLoginRegion
        ? `${cfg.label} · ${COUNTRY[code] || code} (${code}) — công khai, không cần đăng nhập`
        : st === false
          ? `${cfg.label} · ${COUNTRY[code] || code} (${code}): chưa đăng nhập — bấm để mở trang đăng nhập`
          : `${cfg.label} · ${COUNTRY[code] || code} (${code})`;
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
// 1234 → "1,2K" · 12345 → "12,3K" · 1234567 → "1,2M". Số nhỏ giữ nguyên (dễ đọc).
function fmtCompact(n) {
  if (typeof n !== 'number' || !isFinite(n) || n < 0) return '';
  if (n < 1000) return String(n);
  if (n < 1_000_000) return (n / 1000).toFixed(n < 10_000 ? 1 : 0).replace('.', ',') + 'K';
  return (n / 1_000_000).toFixed(n < 10_000_000 ? 1 : 0).replace('.', ',') + 'M';
}
// Unix giây → "hôm nay" / "hôm qua" / "N ngày trước" / "N tháng trước" / "N năm trước".
function fmtRelDate(unixSec) {
  if (typeof unixSec !== 'number' || unixSec < 1_000_000_000) return '';
  const days = Math.max(0, Math.floor((Date.now() / 1000 - unixSec) / 86400));
  if (days === 0) return 'hôm nay';
  if (days === 1) return 'hôm qua';
  if (days < 30) return days + ' ngày trước';
  if (days < 365) return Math.floor(days / 30) + ' tháng trước';
  return Math.floor(days / 365) + ' năm trước';
}
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

// Giá vốn 1688 lấy từ MODAL (tìm theo ảnh) — cột "Giá vốn 1688" ở bảng chính đọc cái này.
// Key = URL ảnh gốc của dòng (rawImg), khớp với data-img nút 💰 và ảnh dùng để tra 1688.
// Value = giá sỉ rẻ nhất (¥/CNY). Bảng quy ra ₫ + % theo tỉ giá/ngưỡng hiện tại (costRate/costThresh).
const cost1688 = {}; // imgUrl -> giá ¥ rẻ nhất

// Ô cột "Giá vốn 1688": hiện ₫ (¥×tỉ giá) + % (₫/giá bán). Dưới ngưỡng → class 'cheap' (xanh).
// Chưa tra (chưa bấm 💰 dòng đó) → '—'. Trả { html, cheap } để tô cả ô.
function cost1688Cell(p) {
  const cny = cost1688[rawImg(p.image)];
  // Chưa tra (undefined) hoặc đã tra nhưng không ra ('none') → '—'. Chỉ số ¥ mới tính ₫/%.
  if (typeof cny !== 'number') return { html: '<span class="sub" title="Bấm 💰 Giá vốn ở cột Thao tác, hoặc nút Giá vốn hàng loạt">—</span>', cheap: false };
  const cur = curOf(p);                 // tiền của SÀN dòng này (VND/PHP/THB…)
  const rate = costRate(cur), thresh = costThresh();
  const conv = Math.round(cny * rate);  // giá vốn ¥ quy về tiền của sàn
  const canRatio = p.price != null && p.price > 0; // giá bán đối thủ cùng tiền → chia ra %
  const ratio = canRatio ? (conv / p.price) * 100 : null;
  const cheap = ratio != null && ratio < thresh;
  const ratioHtml = ratio != null ? `<div class="costratio${cheap ? ' cheap' : ''}">${ratio.toFixed(1)}% giá bán</div>` : '';
  return { html: `<span class="price" title="¥${cny} × ${fmtInt(rate)} = giá vốn quy ${cur}">${fmtPrice(conv, cur)}</span>${ratioHtml}`, cheap };
}
function cost1688Td(p) { const c = cost1688Cell(p); return `<td class="num costcell${c.cheap ? ' cheap' : ''}">${c.html}</td>`; }

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

// Dịch một keyword sang ngôn ngữ của từng region qua backend (Gemini). FAIL-SAFE: lỗi/mạng →
// trả {} để research() dùng nguyên keyword gốc (không bao giờ chặn lượt tìm vì dịch hỏng).
async function translateForRegions(keyword, regions) {
  try {
    const url = `${BACKEND}/api/keywords/translate?keyword=${encodeURIComponent(keyword)}&regions=${encodeURIComponent(regions.join(','))}`;
    const r = await fetch(url);
    if (!r.ok) return {};
    const d = await r.json().catch(() => ({}));
    return d.terms || {};
  } catch (e) { return {}; }
}

async function research() {
  const keywords = $('kw').value.split(',').map((s) => s.trim()).filter(Boolean);
  const count = Number($('count').value);
  const activePf = [...selectedPlatforms].filter((p) => PLATFORMS[p]?.active);
  if (!activePf.length) { setStatus('Chọn ít nhất 1 sàn đang hỗ trợ.', 'err'); return; }
  if (!keywords.length) { setStatus('Nhập ít nhất 1 từ khoá.', 'err'); return; }
  // Mỗi sàn chỉ chạy region nó phục vụ; Shopee thì region đó phải đã đăng nhập.
  // Gom (sàn × region) HỢP LỆ trước — để biết cần dịch keyword sang những region (ngôn ngữ) nào.
  const combos = [];
  const skipLI = [];
  for (const pf of activePf) {
    const cfg = PLATFORMS[pf];
    const hasReg = Array.isArray(cfg.regions) && cfg.regions.length;
    // Sàn không region (Etsy) → chạy 1 lần với '_'; sàn có region → lấy đúng region đã chọn CHO SÀN ĐÓ.
    const pfRegions = hasReg ? cfg.regions.filter((c) => selectedRegions.has(`${pf}:${c}`)) : ['_'];
    for (const region of pfRegions) {
      if (LOGIN[pf] && loginStatus[`${pf}:${region}`] === false) { skipLI.push(`${pf}:${region}`); continue; }
      combos.push({ pf, region });
    }
  }
  if (!combos.length) { setStatus('Không có (sàn × region) hợp lệ. Sàn có region thì phải chọn region của nó.', 'err'); return; }

  // TỰ DỊCH keyword theo ngôn ngữ của từng region (giữ tên hãng/model). SEARCH bằng bản dịch,
  // nhưng NHÃN (nhóm/lọc) giữ keyword GỐC. Region '_' (sàn không nước, vd 1688/Etsy) không dịch.
  $('go').disabled = true;
  const wantTranslate = $('autoTranslate') && $('autoTranslate').checked;
  const regionSet = [...new Set(combos.map((c) => c.region).filter((r) => r && r !== '_'))];
  const trans = {}; // kw gốc -> { region: từ khoá đã dịch }
  let translatedAny = false;
  if (wantTranslate && regionSet.length) {
    setStatus('Đang dịch từ khoá theo ngôn ngữ sàn…');
    for (const kw of keywords) {
      trans[kw] = await translateForRegions(kw, regionSet);
      if (Object.values(trans[kw]).some((t) => t && t !== kw)) translatedAny = true;
    }
  }

  const jobs = [];
  for (const { pf, region } of combos) {
    for (const kw of keywords) {
      const searchKw = (region !== '_' && trans[kw] && trans[kw][region]) ? trans[kw][region] : kw;
      jobs.push({ pf, region, kw: searchKw, kwLabel: kw });
    }
  }

  setStatus(`Đang chạy ${jobs.length} truy vấn (sàn × region × từ khoá)${translatedAny ? ' · đã dịch theo sàn' : ''}…`);

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
    for (const p of r.products) { p.keyword = j.kwLabel || j.kw; if (!p.score) p.score = score(p); }
    all.push(...r.products);
  }
  $('go').disabled = false;
  renderRegions();

  if (!all.length) {
    // Câu cuối cùng phải nói về ĐÚNG những sàn vừa chạy. Bản trước ghi cứng "Shopee: kiểm tra
    // đăng nhập; Amazon: có thể bị chặn" cho mọi trường hợp — chạy mỗi Facebook cũng hiện y
    // như vậy, tức là chỉ người dùng đi sửa hai thứ không liên quan gì tới lượt tìm của họ.
    const daChay = [...new Set(jobs.map((j) => j.pf))];
    const ten = daChay.map((pf) => (PLATFORMS[pf] && PLATFORMS[pf].label) || pf).join(', ');
    const goiY = [];
    if (daChay.some((pf) => LOGIN[pf])) goiY.push('sàn cần đăng nhập thì kiểm lại phiên');
    if (daChay.includes('amazon')) goiY.push('Amazon có thể đang bị chặn tạm/captcha');
    const msg = backendDown
      ? 'Không gọi được backend — Etsy/Facebook cần nó. Kiểm cửa sổ backend còn chạy không, rồi tải lại trang.'
      : notices.length
        ? notices.join(' · ') // hiện lý do thật từ backend (vd Etsy chưa có key)
        : `Không có kết quả từ ${ten}${goiY.length ? ' — ' + goiY.join('; ') : ''}.`;
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
    cost1688Td(p) +
    `<td><button class="sim cost" data-img="${esc(rawImg(p.image))}" data-name="${esc(p.name)}" data-price="${p.price != null ? p.price : ''}" data-cur="${esc(curOf(p))}">💰 Giá vốn</button> ` +
    `<button class="sim vid" data-img="${esc(rawImg(p.image))}" data-name="${esc(p.name)}" data-region="${esc(p.region || '')}">🎬 Video</button></td>` +
    `</tr>`
  ).join('');
  $('table').style.display = list.length ? 'table' : 'none';
  $('costAll').style.display = list.length ? '' : 'none'; // nút giá vốn hàng loạt chỉ hiện khi có list
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

// ---- Click trong bảng: "Giá vốn" (tìm bằng ảnh trên 1688) hoặc "Video" (modal video khớp ảnh) ----
$('rows').addEventListener('click', (e) => {
  const cost = e.target.closest('button.cost');
  if (cost) {
    const sell = cost.dataset.price !== '' && cost.dataset.price != null ? Number(cost.dataset.price) : null;
    openCostModal({ img: cost.dataset.img, name: cost.dataset.name, sell, cur: cost.dataset.cur || 'VND' });
    return;
  }
  const vid = e.target.closest('button.vid');
  if (vid) {
    openVideoModal({ img: vid.dataset.img, name: vid.dataset.name, region: vid.dataset.region });
    return;
  }
});

// ===== MODAL GIÁ VỐN — tìm bằng ẢNH sản phẩm trên 1688, lấy chào hàng RẺ NHẤT (giá sỉ ¥ = giá vốn) =====
// Dùng lại endpoint /api/imagesearch (mục Tìm bằng ảnh), chỉ hỏi nguồn '1688'. Ảnh của dòng là URL
// → tải bytes qua proxy /api/media (tránh CORS) → gửi multipart. `sourcing` trả về = bảng 1688.
let costToken = 0; // chống race: mỗi lần mở gắn token, chỉ render kết quả của token mới nhất.
// Ngữ cảnh modal hiện tại — giữ để đổi tỉ giá/ngưỡng thì tính lại % ngay, KHÔNG fetch lại 1688.
let costOffers = [];      // các chào hàng 1688 đã lấy (mỗi cái là một nguồn nhập)
let costSell = null;      // giá bán đối thủ (VND) của dòng đang xét — mẫu số của %
let costCur = 'VND';      // tiền tệ của giá bán; chỉ tính % khi = VND (tỉ giá là ¥→₫)
function setCostStatus(msg, kind) { $('costStatusText').textContent = msg || ''; $('costStatus').className = 'status' + (kind ? ' ' + kind : ''); }
function closeCostModal() {
  $('costModal').classList.remove('on');
  $('costGrid').innerHTML = '';
  $('costHeadline').innerHTML = '';
  $('costTitle').textContent = '';
  $('costControls').hidden = true;
  costOffers = [];
  setCostStatus('');
}

// Lõi tra giá vốn 1688 theo ẢNH — DÙNG CHUNG cho modal (mở chi tiết một dòng) và batch (cả bảng).
// KHÔNG đụng DOM, không token. Trả { offers, min, error, identity, cached }: offers đã lọc phụ
// kiện + sắp giá tăng dần (rẻ nhất đầu), min = offers[0]. nameHint giúp Gemini lọc đúng loại SP.
async function fetch1688Offers(imgUrl, nameHint) {
  let blob;
  try {
    const ir = await fetch(proxyMedia(imgUrl));
    if (!ir.ok) throw new Error('HTTP ' + ir.status);
    blob = await ir.blob();
  } catch (e) { return { offers: [], min: null, error: 'Không tải được ảnh: ' + e.message }; }

  let data;
  try {
    const form = new FormData();
    const type = /^image\/(jpeg|png|webp)$/.test(blob.type) ? blob.type : 'image/jpeg';
    const typed = blob.type === type ? blob : new Blob([blob], { type });
    form.append('file', typed, 'product.' + type.split('/')[1]);
    form.append('geo', 'VN');
    form.append('sources', '1688');
    const r = await fetch(`${BACKEND}/api/imagesearch`, { method: 'POST', body: form });
    data = await r.json().catch(() => ({}));
    if (!r.ok) return { offers: [], min: null, error: (data && data.error) || `backend HTTP ${r.status}` };
  } catch (e) { return { offers: [], min: null, error: 'Lỗi gọi tìm-bằng-ảnh: ' + e.message }; }

  let offers = (data.sourcing || [])
    .filter((o) => o.priceValue != null && !o.isAccessory)
    .sort((a, b) => a.priceValue - b.priceValue);

  // Lọc theo Gemini: tìm bằng ảnh trả về hàng NHÌN GIỐNG, rẻ nhất có thể là món KHÁC loại. Hỏi
  // model tiêu đề nào ĐÚNG loại rồi chỉ lấy rẻ nhất trong số đó. Thiếu khoá/model lỗi → giữ nguyên.
  if (offers.length > 1) {
    try {
      const productHint = (data.identity && data.identity.product) || nameHint || '';
      const rr = await fetch(`${BACKEND}/api/cost/rank`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ product: productHint, titles: offers.map((o) => o.title || '') }),
      });
      const rj = await rr.json().catch(() => ({}));
      if (Array.isArray(rj.relevant) && rj.relevant.length) {
        const keep = new Set(rj.relevant);
        const filtered = offers.filter((_, idx) => keep.has(idx)); // giữ thứ tự giá tăng dần
        if (filtered.length) offers = filtered;
      }
    } catch (e) { /* Gemini lỗi/không cấu hình → giữ nguyên, lấy rẻ nhất */ }
  }
  return {
    offers, min: offers[0] || null,
    error: offers.length ? null : (data.message || '1688 không tìm thấy hàng khớp ảnh này.'),
    identity: data.identity, cached: data.cached,
  };
}

async function openCostModal(p) {
  const my = ++costToken;
  costSell = (p.sell != null && isFinite(p.sell) && p.sell > 0) ? p.sell : null;
  costCur = p.cur || 'VND';
  costOffers = [];
  $('costTitle').textContent = p.name || '(không tên)';
  $('costHeadline').innerHTML = '';
  $('costGrid').innerHTML = '';
  $('costControls').hidden = true;
  $('costModal').classList.add('on');
  setCostStatus('Đang tìm giá vốn trên 1688 theo ảnh… (lần đầu hơi chậm)');

  const res = await fetch1688Offers(p.img, p.name);
  if (my !== costToken) return; // user đã mở dòng khác trong lúc chờ → bỏ kết quả cũ
  if (!res.offers.length) { setCostStatus(res.error || '1688 không tìm thấy hàng khớp ảnh này.', 'err'); return; }
  const offers = res.offers;
  if (res.identity && res.identity.product) $('costTitle').textContent = res.identity.product;

  const min = offers[0];
  costOffers = offers;
  // Ghi giá vốn 1688 rẻ nhất về store theo ảnh dòng → cột "Giá vốn 1688" ở bảng chính hiện ngay.
  if (p.img != null && min.priceValue != null) { cost1688[p.img] = min.priceValue; render(); }
  $('costHeadline').innerHTML = `Giá vốn nhỏ nhất <b>${esc(min.price || ('¥' + min.priceValue))}</b>`;
  const rate = costRate(costCur); // tỉ giá ¥→tiền của sàn dòng này
  const sellNote = costSell != null
    ? ` · giá bán đối thủ ${fmtPrice(costSell, costCur)} · % = giá nhập ÷ giá bán`
    : ' · dòng này thiếu giá bán nên không tính %';
  setCostStatus(`${offers.length} chào hàng 1688${res.cached ? ' (cache)' : ''}. Tỉ giá ¥→${costCur} = ${fmtInt(rate)}${sellNote}`, 'ok');

  // Nhãn ô tỉ giá theo tiền của sàn (¥→PHP, ¥→₫…) + nạp giá trị hiện tại, hiện controls, dựng card.
  $('costRateCur').textContent = '¥→' + (costCur === 'VND' ? '₫' : costCur);
  $('costRate').value = rate;
  $('costThresh').value = costThresh();
  $('costControls').hidden = false;
  renderCostCards();
}

// Dựng lại các card 1688 theo TỈ GIÁ + NGƯỠNG hiện tại (KHÔNG fetch lại). Mỗi card = một nguồn
// nhập: hiện giá quy ₫ và % = (giá 1688 × tỉ giá) ÷ giá bán đối thủ. Dưới ngưỡng → class 'cheap' (xanh).
function renderCostCards() {
  // Ưu tiên số đang gõ trong ô (nguồn sự thật khi modal mở), rớt về localStorage/mặc định.
  const rInput = parseFloat($('costRate').value);
  const tInput = parseFloat($('costThresh').value);
  const rate = rInput > 0 ? rInput : costRate(costCur);
  const thresh = tInput > 0 ? tInput : costThresh();
  const canRatio = costSell != null && costSell > 0; // giá bán đối thủ cùng tiền costCur → chia ra %
  $('costGrid').innerHTML = costOffers.map((o, i) => {
    const conv = o.priceValue != null ? Math.round(o.priceValue * rate) : null;
    const ratio = (canRatio && conv != null) ? (conv / costSell) * 100 : null;
    const cheap = ratio != null && ratio < thresh;
    const vndHtml = conv != null ? `<div class="cvnd">≈ ${fmtPrice(conv, costCur)}</div>` : '';
    const ratioHtml = ratio != null ? `<div class="cratio">${ratio.toFixed(1)}% giá bán</div>` : '';
    return (
      `<a class="ccard${cheap ? ' cheap' : ''}" href="${esc(o.link)}" target="_blank" rel="noreferrer">` +
      `<div class="media">${o.thumbnail ? `<img src="${esc(proxyMedia(o.thumbnail))}" loading="lazy" alt="" />` : ''}` +
      `${i === 0 ? '<span class="mbadge">Rẻ nhất</span>' : ''}</div>` +
      `<div class="cbody">` +
      `<div class="cost-price">${esc(o.price || ('¥' + o.priceValue))}</div>` +
      vndHtml + ratioHtml +
      `<div class="ccopy">${esc(o.title || '')}</div>` +
      `<div class="cmeta">${[o.supplier, o.location, o.sold != null ? 'đã bán ' + fmtInt(o.sold) : o.note]
        .filter(Boolean).map(esc).join(' · ')}</div>` +
      `</div></a>`
    );
  }).join('');
}

// Nút "Giá vốn hàng loạt": tra 1688 theo ẢNH cho MỌI dòng đang hiện (bỏ dòng đã có / đã thử),
// điền dần cột "Giá vốn 1688". Song song tối đa 3 để nhanh mà không dội backend. Bấm 💰 từng dòng
// vẫn mở modal chi tiết như cũ.
let costBatchRunning = false;
async function runCost1688Batch() {
  if (costBatchRunning) return;
  const kwPick = $('kwfilter').value || '__all';
  const list = rows.filter((p) => kwPick === '__all' || p.keyword === kwPick);
  // Chỉ tra dòng CHƯA có kết quả (undefined/null). 'none' = đã thử không ra → không tra lại loạt.
  const targets = list.filter((p) => rawImg(p.image) && cost1688[rawImg(p.image)] == null);
  if (!targets.length) { setStatus('Mọi sản phẩm đang hiện đã tra giá vốn 1688 rồi.', 'ok'); return; }

  costBatchRunning = true;
  const btn = $('costAll');
  const total = targets.length; let done = 0, ok = 0, idx = 0;
  const CONC = 2;         // nhẹ tay: bắn 1688 dồn dập dễ dính risk-control (FAIL_SYS_ILLEGAL_ACCESS)
  let blocked = false;    // 1688 chặn IP → dừng loạt, giữ dòng chưa tra để thử lại sau
  // Nhãn nút thành spinner + tiến độ NGAY khi bấm (lần fetch đầu vài giây, đừng để user tưởng lỗi).
  function setBtnRunning() { if (btn) { btn.disabled = true; btn.innerHTML = `<span class="rs-spin"></span>Đang tính… ${done}/${total}`; } }
  setBtnRunning();
  setStatus(`Đang tra giá vốn 1688 cho ${total} sản phẩm… (lần đầu mỗi món hơi chậm)`);
  async function worker() {
    while (idx < targets.length && !blocked) {
      const p = targets[idx++];
      const key = rawImg(p.image);
      try {
        const res = await fetch1688Offers(key, p.name);
        if (res.min && res.min.priceValue != null) { cost1688[key] = res.min.priceValue; ok++; }
        else if (res.error && /ILLEGAL|非法|FAIL_SYS/i.test(res.error)) { blocked = true; break; } // dừng ngay khi bị chặn
        else cost1688[key] = 'none'; // đã thử, không ra → khỏi tra lại ở lần loạt sau
      } catch (e) { cost1688[key] = 'none'; }
      done++;
      setBtnRunning();
      setStatus(`Đang tính giá vốn 1688: ${done}/${total}… (${ok} ra kết quả)`);
      render(); // điền cột dần
      await new Promise((r) => setTimeout(r, 500)); // giãn nhịp cho 1688 đỡ gắn cờ
    }
  }
  try {
    await Promise.all(Array.from({ length: Math.min(CONC, targets.length) }, worker));
    if (blocked) setStatus(`1688 tạm chặn (risk-control 非法请求) sau ${done}/${total}. Đợi vài phút rồi bấm lại, hoặc tra lẻ từng dòng. Đã lấy ${ok} món.`, 'err');
    else setStatus(`Xong giá vốn 1688: ${ok}/${total} sản phẩm ra kết quả. Bấm 💰 một dòng để xem nguồn 1688 chi tiết.`, 'ok');
  } finally {
    costBatchRunning = false;
    if (btn) { btn.disabled = false; btn.textContent = '💰 Giá vốn hàng loạt'; }
    render();
  }
}
$('costAll').addEventListener('click', runCost1688Batch);

$('costClose').addEventListener('click', closeCostModal);
$('costModal').addEventListener('click', (e) => { if (e.target === $('costModal')) closeCostModal(); }); // bấm nền tối để đóng
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('costModal').classList.contains('on')) closeCostModal(); });

// Chỉnh tỉ giá / ngưỡng → lưu localStorage (giữ cho lần sau) rồi tính lại % + tô màu ngay, không fetch lại.
function onCostCtrlChange() {
  const r = parseFloat($('costRate').value);
  const t = parseFloat($('costThresh').value);
  try {
    if (r > 0) localStorage.setItem('rs_cost_rate_' + costCur, String(r)); // tỉ giá riêng theo tiền sàn
    if (t > 0) localStorage.setItem('rs_cost_thresh', String(t));
  } catch (e) { /* storage bị chặn — vẫn tính lại theo giá trị đang gõ */ }
  renderCostCards();
  render(); // cột "Giá vốn 1688" ở bảng chính cũng đổi theo tỉ giá/ngưỡng mới
}
$('costRate').addEventListener('input', onCostCtrlChange);
$('costThresh').addEventListener('input', onCostCtrlChange);

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
$('regions').addEventListener('click', (e) => {
  const chip = e.target.closest('.rgchip');
  if (!chip) return;
  const pf = chip.dataset.pf, code = chip.dataset.code;
  // Chưa đăng nhập (Shopee/TikTok) → mở tab đăng nhập đúng sàn+nước đó, không đổi lựa chọn.
  const spec = LOGIN[pf];
  if (spec && spec.domain[code] && loginStatus[`${pf}:${code}`] === false) { chrome.tabs.create({ url: `https://${spec.domain[code]}/` }); return; }
  const key = `${pf}:${code}`;
  if (multiRegion) {
    if (selectedRegions.has(key)) {
      // Không để một sàn trống hết nước — muốn bỏ hẳn sàn thì bỏ chọn nó ở bước 1.
      if (PLATFORMS[pf].regions.some((c) => c !== code && selectedRegions.has(`${pf}:${c}`))) selectedRegions.delete(key);
    } else selectedRegions.add(key);
  } else {
    // Chọn-một: thay thế nước đang chọn CỦA CHÍNH SÀN ĐÓ, không đụng tới sàn khác.
    for (const c of PLATFORMS[pf].regions) selectedRegions.delete(`${pf}:${c}`);
    selectedRegions.add(key);
  }
  renderRegions();
});
// Hai chế độ, cho cả SÀN lẫn NƯỚC. Mặc định chọn-một: bấm cái nào thì THAY THẾ hẳn cái đang
// chọn, như một nhóm nút radio. Chuyển sang "Nhiều" thì quay lại kiểu cộng dồn — cần khi muốn
// xếp Shopee cạnh TikTok Shop, hay so Việt Nam với Thái Lan trong cùng một bảng.
// Sàn: không còn công tắc "Một/Nhiều" — luôn chọn tự do (xem handler #platforms). Nước vẫn có
// hai chế độ vì region gom theo sàn và đổi-một-nước bằng một bấm là thao tác thường dùng.
let multiRegion = false;

/** Gắn một nút hai nấc vào một biến chế độ. Trả về hàm để đọc lại trạng thái khi cần vẽ lại. */
function bindMode(id, onChange) {
  const box = $(id);
  box.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-multi]');
    if (!btn || btn.dataset.on === 'true') return;
    for (const b of box.querySelectorAll('button[data-multi]')) b.dataset.on = String(b === btn);
    onChange(btn.dataset.multi === '1');
  });
}

bindMode('rgMode', (multi) => {
  multiRegion = multi;
  if (!multi) {
    // Mỗi sàn giữ đúng MỘT nước — nước đầu tiên đang chọn của chính sàn đó.
    for (const pf of regionPlatforms()) {
      const dangChon = PLATFORMS[pf].regions.filter((c) => selectedRegions.has(`${pf}:${c}`));
      for (const c of dangChon.slice(1)) selectedRegions.delete(`${pf}:${c}`);
    }
  }
  renderRegions();
});

$('platforms').addEventListener('click', (e) => {
  const chip = e.target.closest('.rgchip');
  if (!chip) return;
  const id = chip.dataset.pf, cfg = PLATFORMS[id];
  if (!cfg || !cfg.active) return; // sàn chưa hỗ trợ → không chọn được
  // Chọn tự do: bấm để bật/tắt. Được phép bỏ hết (bảng trắng) — Research sẽ nhắc "chọn ít nhất
  // 1 sàn". Số sàn đang bật quyết định chạy 1 hay nhiều, không cần công tắc chế độ.
  if (selectedPlatforms.has(id)) selectedPlatforms.delete(id);
  else selectedPlatforms.add(id);
  renderPlatforms();
  updateRegionSection();
  refreshLogin();
});

// Khởi tạo: vẽ chip sàn + region theo sàn + check đăng nhập.
// ?kw đến từ HAI nơi: popup của extension, và nút "Tìm sản phẩm" ở tab Keyword — nút đó gọi
// `/ads?keyword=...` rồi `app/(dashboard)/ads/page.tsx` chuyền tiếp vào src của iframe này.
// Chỉ ĐIỀN sẵn, không tự bấm Research: mỗi lượt là một loạt crawl thật lên các sàn.
renderPlatforms();
updateRegionSection();
const _kw = new URLSearchParams(location.search).get('kw');
if (_kw) $('kw').value = _kw;
// Xác định extension/relay TRƯỚC, rồi mới kiểm tra đăng nhập (để chạy đúng đường). KHÔNG tự research.
detectMode().then(refreshLogin);

// ===== TAB CONTENT (Facebook Ads) + TAB TÌM BẰNG ẢNH =====
// ===== MODAL VIDEO — "video quảng cáo khớp ẢNH sản phẩm" cho một dòng ở tab Sản phẩm =====
// Gọi backend /api/ads/match-image: seed keyword (tên SP) lấy ứng viên Facebook/TikTok, rồi backend
// so pHash poster video với ẢNH sản phẩm, chỉ trả video TRÙNG ảnh. Cần backend chạy.
let vidToken = 0; // chống race: mỗi lần mở gắn một token, chỉ render kết quả của token mới nhất.
let vidState = null; // { p, usedKw, fbAds, marketAds } — giữ FB/Sàn để đổi NƯỚC chỉ tải lại TikTok.

function proxyMedia(url) { return url ? `${BACKEND}/api/media?url=${encodeURIComponent(url)}` : ''; }
function setVidStatus(msg, kind) { $('vidStatusText').textContent = msg; $('vidStatus').className = 'status' + (kind ? ' ' + kind : ''); }
// Đóng cửa sổ là dọn SẠCH: lưới, hàng lọc, danh sách trong bộ nhớ, và cả lớp phủ phát nếu
// đang mở. Bỏ sót cái nào thì lần mở sau sẽ thấy thoáng qua kết quả của sản phẩm trước.
function closeVideoModal() {
  closeTkPlayer();
  $('vidModal').classList.remove('on');
  $('vidGrid').innerHTML = '';
  $('vidFilter').innerHTML = '';
  vidAll = [];
  vidShown = [];
  vidPick = 'all';
  vidState = null;
}

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
    setVidStatus('Không gọi được backend — cần nó để lấy video quảng cáo. Kiểm cửa sổ backend rồi thử lại.', 'err');
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

  // VẼ NGAY PHẦN ĐÃ CÓ, đừng chờ TikTok.
  //
  // Facebook về sau vài giây; TikTok thì phải mở tab, gõ chữ, cuộn — hàng chục giây, và còn
  // một lượt lấy thống kê nữa phía sau. Chờ đủ cả hai rồi mới vẽ nghĩa là người dùng nhìn màn
  // hình trống suốt quãng ấy, trong khi thứ họ hỏi ("có ai đang chạy quảng cáo món này không")
  // thì Facebook đã trả lời xong rồi.
  renderVideos(fbAds.concat(marketAds));
  setVidStatus(`Facebook ${fbAds.length} · Sàn ${marketAds.length} — đang lấy TikTok…`);

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
  // likeCount + createdAt: chỉ có khi parseTiktokTexts chộp được API (không DOM), nên có thể null.
  const tkAds = tkItems.map((it) => ({
    platform: 'tiktok', id: it.id, advertiser: it.author || 'TikTok', title: it.name, body: it.name,
    permalink: it.videoUrl, langMatch: it.langMatch || 'neutral', regionTag: region,
    likeCount: it.likeCount || null,
    commentCount: it.commentCount || null,
    playCount: it.playCount || null,
    startedAt: it.createdAt || null,
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
  // Vẽ xong rồi mới đi lấy tim/bình luận/lượt xem — xem ghi chú ở `fillTiktokStats`. Không
  // `await`: lưới đã dùng được ngay, số điền vào sau.
  void fillTiktokStats(all, my);
}

/**
 * Bổ sung tim / bình luận / chia sẻ / LƯỢT XEM cho các thẻ TikTok.
 *
 * ĐI QUA BACKEND, KHÔNG QUA EXTENSION. Backend đọc trang nhúng của chính TikTok bằng Chrome
 * thật — không cần đăng nhập, không cần extension, và cache sáu giờ theo từng video nên lượt
 * sau gần như tức thì (đo: 3 video mất 7,8 giây lần đầu, 1,8 giây lần sau).
 *
 * Bản trước giao việc này cho extension. Nó chạy được về lý thuyết nhưng KHÔNG kiểm được bằng
 * máy — Chrome 151 bỏ `--load-extension` — nên mỗi lần hỏng chỉ còn cách đoán. Đường qua
 * backend thì đo được từ đầu đến cuối, và đó là lý do đổi.
 *
 * Chạy SAU khi đã vẽ lưới và vẽ lại khi có số: người dùng thấy video ngay, số điền vào sau.
 */
async function fillTiktokStats(ads, token) {
  // `== null` chứ không `!a.likeCount`: video có ĐÚNG 0 tim là một phép đo hợp lệ, dùng
  // `!` thì nó rơi vào nhánh "chưa có" và bị đi hỏi lại ở mọi lượt vẽ.
  const ids = ads.filter((a) => a.platform === 'tiktok' && a.id && a.likeCount == null).map((a) => a.id);
  if (!ids.length) return;
  let data;
  try {
    const r = await fetch(`${BACKEND}/api/ads/tiktok-stats?ids=${encodeURIComponent(ids.join(','))}`);
    data = await r.json();
    if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  } catch (e) {
    // Không có số thì thôi, nhưng NÓI RA. Một hàng thống kê trống mà không lời giải đọc thành
    // "video này không ai xem" — sai, và sai theo hướng làm người dùng bỏ qua video tốt.
    if (token === vidToken) setVidStatus($('vidStatusText').textContent + ' · chưa lấy được lượt tim (backend không trả lời)', 'err');
    return;
  }
  if (token !== vidToken) return; // lượt tìm khác đã chen vào — bỏ kết quả cũ

  let co = 0;
  for (const ad of ads) {
    const st = data.stats && data.stats[ad.id];
    if (!st) continue;
    co++;
    ad.likeCount = st.likeCount ?? ad.likeCount;
    ad.commentCount = st.commentCount ?? ad.commentCount;
    ad.shareCount = st.shareCount ?? ad.shareCount;
    ad.playCount = st.playCount ?? ad.playCount;
    ad.startedAt = ad.startedAt || st.createdAt || null;
  }
  if (co) renderVideos(ads);
  if (co < ids.length) {
    // Nói rõ thiếu bao nhiêu. Video riêng tư hoặc đã xoá thì đọc không ra, và đó là chuyện
    // bình thường — nhưng im lặng thì người dùng tưởng công cụ hỏng.
    setVidStatus(`${$('vidStatusText').textContent} · thống kê ${co}/${ids.length} video`, co ? 'ok' : 'err');
  }
}

/**
 * Nguồn của một thẻ, dùng cho hàng lọc. Gom "sàn" thành MỘT nhóm: Shopee, Taobao, 1688, Temu
 * đều là video sản phẩm lấy từ trang bán hàng, người dùng đọc chúng như một loại.
 */
function vidSource(ad) {
  const pf = String(ad.platform || '').toLowerCase();
  if (pf === 'facebook' || pf === 'tiktok' || pf === 'douyin') return pf;
  return 'market';
}

const VID_SOURCES = [
  { id: 'all', label: 'Tất cả' },
  { id: 'facebook', label: 'Facebook' },
  { id: 'tiktok', label: 'TikTok' },
  { id: 'douyin', label: 'Douyin' },
  { id: 'market', label: 'Sàn' },
];

let vidAll = [];       // toàn bộ thẻ đang có, chưa lọc
let vidShown = [];     // phần đang hiện — cũng là danh sách để bấm ‹ › trong lớp phủ
let vidPick = 'all';

/** Vẽ hàng lọc. Chip bằng 0 VẪN HIỆN — xem ghi chú CSS `.vfilter`. */
function drawVidFilter() {
  const box = $('vidFilter');
  if (!box) return;
  const dem = {};
  for (const ad of vidAll) dem[vidSource(ad)] = (dem[vidSource(ad)] || 0) + 1;
  box.innerHTML = VID_SOURCES
    .map((s) => {
      const n = s.id === 'all' ? vidAll.length : (dem[s.id] || 0);
      return `<button data-src="${s.id}" data-on="${vidPick === s.id ? 1 : 0}">${s.label}<b>${n}</b></button>`;
    })
    .join('');
}

function drawVidGrid() {
  const grid = $('vidGrid');
  grid.innerHTML = '';
  vidShown = vidPick === 'all' ? vidAll.slice() : vidAll.filter((a) => vidSource(a) === vidPick);
  if (!vidShown.length) {
    // Một CÂU, không phải một ô trống. Ô trống đọc thành "hỏng"; câu này nói rõ là nguồn ấy
    // không có gì, và đó là một thông tin.
    grid.innerHTML = `<p class="sub">Không có video nào từ nguồn này.</p>`;
    return;
  }
  for (let i = 0; i < vidShown.length; i++) grid.appendChild(vidCard(vidShown[i], i));
}

/**
 * Một con số thống kê CỦA CHÍNH VIDEO ẤY. Không cộng gộp gì cả — mỗi thẻ đọc đúng trường của
 * mình.
 *
 * SỐ 0 VẪN HIỆN, chỉ trường VẮNG MẶT mới ẩn. Hai chuyện khác hẳn nhau và giao diện phải phân
 * biệt được: "0 bình luận" là một phép đo — video ấy thật sự không ai bình luận, và đó là
 * thông tin đáng giá khi chọn video để bắt chước. Còn trường vắng mặt nghĩa là đọc không ra
 * (video riêng tư, đã xoá, hoặc hết hạn giờ), và bịa ra số 0 cho nó là nói dối.
 *
 * Rút gọn về K/M cho mọi cỡ: bốn ô số đứng cạnh nhau trong một thẻ hẹp, viết đủ "41.400.000"
 * thì vỡ hàng. Số đầy đủ nằm trong phần chú khi rê chuột.
 */
function stat(icon, ten, v) {
  if (typeof v !== 'number' || v < 0) return '';
  return `<span title="${ten}: ${v.toLocaleString('vi-VN')}">${icon}<span class="n">${fmtCompact(v)}</span></span>`;
}

function vidCard(ad, idx) {
  const creatives = ad.creatives || [];
  const video = creatives.find((c) => c.kind === 'video' && c.url);
  const poster = (video && video.posterUrl) ||
    (creatives.find((c) => c.posterUrl) || {}).posterUrl ||
    (creatives.find((c) => c.url) || {}).url || '';

  // HÀNG THỐNG KÊ riêng, tách khỏi hàng nhãn. Đây là thứ người dùng quét mắt qua để chọn
  // video đáng xem, nên nó không được lẫn vào giữa tên sàn và ngày tháng.
  const stats =
    stat('❤️', 'Lượt tim', ad.likeCount) +
    stat('💬', 'Bình luận', ad.commentCount) +
    stat('↗', 'Chia sẻ', ad.shareCount) +
    stat('▶', 'Lượt xem', ad.playCount);
  // Facebook không có tương tác nào (Ads Library không công bố — đo 2026-08-18), chỉ có số
  // người theo dõi Trang. Nói rõ đó là follower chứ không phải like của bài.
  const fbFollow = !stats && ad.pageLikeCount
    ? `<span title="Người theo dõi Trang Facebook — KHÔNG phải tương tác của quảng cáo này">👥<span class="n">${fmtCompact(ad.pageLikeCount)}</span><span class="k">theo dõi</span></span>`
    : '';

  const days = ad.daysActive != null ? `<span title="Số ngày quảng cáo đã chạy">${ad.daysActive} ngày chạy</span>` : '';
  const posted = ad.startedAt ? `<span title="Ngày đăng / bắt đầu chạy">📅 ${fmtRelDate(ad.startedAt)}</span>` : '';
  const match = typeof ad.matchScore === 'number' ? `<span class="mbadge">🎯 ${ad.matchScore}% khớp ảnh</span>` : '';
  const langBadge = (ad.langMatch === 'other' && ad.regionTag)
    ? `<span class="mbadge langoff" title="Mô tả không phải tiếng ${COUNTRY[ad.regionTag] || ad.regionTag} — TikTok trả theo account/IP của bạn">⚠ khác ngôn ngữ</span>`
    : '';

  const isTk = ad.platform === 'tiktok' && ad.id;
  let media;
  if (isTk) {
    media =
      (poster ? `<img src="${esc(poster)}" loading="lazy" alt="" referrerpolicy="no-referrer">` : `<div class="tk-ph">TikTok</div>`) +
      `<button class="play-overlay" data-idx="${idx}" aria-label="Phát video TikTok"><span>▶</span></button>`;
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
    ((stats || fbFollow) ? `<div class="cstats">${stats}${fbFollow}</div>` : '') +
    `<div class="cmeta"><span class="pill">${esc(PF_LABEL[ad.platform] || ad.platform)}</span>${posted}${days}</div>` +
    (ad.permalink ? `<a class="clink" href="${esc(ad.permalink)}" target="_blank" rel="noreferrer">${isTk ? 'Mở trên TikTok ↗' : 'Xem quảng cáo ↗'}</a>` : '') +
    `</div>`;
  return el;
}

function renderVideos(ads) {
  vidAll = ads || [];
  // Nguồn đang lọc có thể vừa biến mất (đổi nước, đổi sản phẩm) — về "Tất cả" thay vì để
  // người dùng nhìn một lưới trống mà không hiểu vì sao.
  if (vidPick !== 'all' && !vidAll.some((a) => vidSource(a) === vidPick)) vidPick = 'all';
  drawVidFilter();
  drawVidGrid();
}

/*
 * CỬA CHO MÁY CHẠY THỬ. Lộ đúng một hàm vẽ và danh sách đang hiện, không lộ gì để sửa dữ liệu.
 *
 * Có nó vì phần cửa sổ video chỉ chạy được khi extension đã bơm kết quả TikTok vào, mà Chrome
 * 151 thì không cho nạp extension trong máy tự động — không có cửa này thì toàn bộ hàng lọc,
 * hàng thống kê và lớp phủ phát KHÔNG kiểm được bằng máy, chỉ còn cách nhìn bằng mắt.
 */
window.__rsVid = {
  render: renderVideos,
  // Tự truyền mã lượt hiện tại: `fillTiktokStats` bỏ qua kết quả của lượt cũ, nên gọi
  // trần từ ngoài sẽ luôn rơi vào nhánh ấy.
  fill: (ads) => fillTiktokStats(ads, vidToken),
  get shown() { return vidShown; },
};

$('vidFilter').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-src]');
  if (!b) return;
  vidPick = b.getAttribute('data-src');
  drawVidFilter();
  drawVidGrid();
});

// ===== LỚP PHỦ PHÁT VIDEO =====
//
// Bấm ▶ mở player ở một lớp phủ riêng, KHÔNG nhét iframe vào ô ảnh của thẻ. Ô ấy là hình vuông
// cỡ ba trăm pixel, còn player TikTok là khung dọc có chiều cao tối thiểu — nhét vào đó thì nó
// cắt cụt hoặc rơi về màn hình "Watch more exciting videos on TikTok".
//
// Đã đo: `embed/v2`, `embed` và `player/v1` đều trả 200, không có `X-Frame-Options` cũng không
// có `frame-ancestors`. Nhúng chưa bao giờ bị chặn; chỉ là cái khung quá nhỏ.
//
// Lớp phủ mang theo THÔNG TIN VIDEO bên cạnh và hai nút ‹ › để đi tiếp — trước đây muốn biết
// đang xem của ai, bao nhiêu tim, thì phải đóng ra tìm lại đúng cái thẻ vừa bấm.
let tkAt = -1; // vị trí trong `vidShown` của video đang phát

function tkInfoHTML(ad) {
  const stats =
    stat('❤️', 'Lượt tim', ad.likeCount) +
    stat('💬', 'Bình luận', ad.commentCount) +
    stat('↗', 'Chia sẻ', ad.shareCount) +
    stat('▶', 'Lượt xem', ad.playCount);
  return (
    `<h3>${esc(ad.advertiser || '—')}</h3>` +
    (stats ? `<div class="cstats">${stats}</div>` : '') +
    `<div class="desc">${esc(ad.title || ad.body || '')}</div>` +
    (ad.startedAt ? `<div class="sub">📅 ${fmtRelDate(ad.startedAt)}</div>` : '') +
    (ad.permalink ? `<a href="${esc(ad.permalink)}" target="_blank" rel="noreferrer">Mở trên TikTok ↗</a>` : '')
  );
}

function openTkPlayer(idx) {
  const ad = vidShown[idx];
  if (!ad || !ad.id) return;
  tkAt = idx;
  const khung = $('tkFrame');
  khung.innerHTML = '';
  const f = document.createElement('iframe');
  f.src = `https://www.tiktok.com/embed/v2/${encodeURIComponent(ad.id)}`;
  f.allow = 'autoplay; encrypted-media; fullscreen';
  f.setAttribute('scrolling', 'no');
  khung.appendChild(f);
  $('tkInfo').innerHTML = tkInfoHTML(ad);

  // Chỉ đi tới video TikTok khác — thẻ Facebook/Sàn không có player để nhảy sang.
  const co = (d) => {
    for (let i = idx + d; i >= 0 && i < vidShown.length; i += d) {
      if (vidShown[i] && vidShown[i].platform === 'tiktok' && vidShown[i].id) return i;
    }
    return -1;
  };
  $('tkPrev').disabled = co(-1) < 0;
  $('tkNext').disabled = co(1) < 0;
  $('tkPlay').classList.add('on');
}

function tkStep(d) {
  for (let i = tkAt + d; i >= 0 && i < vidShown.length; i += d) {
    if (vidShown[i] && vidShown[i].platform === 'tiktok' && vidShown[i].id) { openTkPlayer(i); return; }
  }
}

function closeTkPlayer() {
  $('tkPlay').classList.remove('on');
  // XOÁ HẲN iframe chứ không chỉ ẩn: để nguyên thì video chạy tiếp và tiếng vẫn phát sau lưng
  // một lớp phủ đã đóng — người dùng không có cách nào tắt ngoài việc tải lại trang.
  $('tkFrame').innerHTML = '';
  $('tkInfo').innerHTML = '';
  tkAt = -1;
}

$('vidGrid').addEventListener('click', (e) => {
  const btn = e.target.closest('.play-overlay[data-idx]');
  if (!btn) return;
  openTkPlayer(Number(btn.getAttribute('data-idx')));
});
$('tkPlayClose').addEventListener('click', closeTkPlayer);
$('tkPrev').addEventListener('click', () => tkStep(-1));
$('tkNext').addEventListener('click', () => tkStep(1));
// Bấm ra nền tối cũng đóng — nhưng chỉ khi bấm đúng cái nền, không phải bấm trong player.
$('tkPlay').addEventListener('click', (e) => { if (e.target === $('tkPlay')) closeTkPlayer(); });
document.addEventListener('keydown', (e) => {
  if (!$('tkPlay').classList.contains('on')) return;
  if (e.key === 'Escape') closeTkPlayer();
  else if (e.key === 'ArrowLeft') tkStep(-1);
  else if (e.key === 'ArrowRight') tkStep(1);
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
  // likeCount + createdAt: chỉ có khi parseDouyinTexts chộp được API, có thể null.
  const dyAds = dyItems.map((it) => ({
    platform: 'douyin', id: it.id, advertiser: it.author || 'Douyin', title: it.name, body: it.name,
    permalink: it.videoUrl, langMatch: 'match', regionTag: 'CN',
    likeCount: it.likeCount || null,
    commentCount: it.commentCount || null,
    startedAt: it.createdAt || null,
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
