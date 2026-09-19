/*
 * KALODATA cho trang Research — nạp vào service worker bằng `importScripts('kalodata.js')`.
 *
 * VÌ SAO NẰM Ở ĐÂY chứ không dùng thẳng extension `extension-kalodata/`: trang Research gửi lệnh
 * qua cầu `content.js` của CHÍNH extension này, và khi máy người dùng không có extension thì lệnh
 * đi relay tới máy-thợ — máy-thợ cũng chỉ chạy extension này. Gọi sang một extension khác thì
 * đường relay đứt hẳn. `extension-kalodata/` vẫn giữ nguyên làm công cụ cào độc lập.
 *
 * Lõi dưới đây CHÉP từ `extension-kalodata/background.js` (kdSend / kdCrawl / kdNormalize) —
 * sửa một bên nhớ sửa bên kia. Đặc tả API ở `docs/kalodata-api.md`. Ba điều dễ sai nhất, đã đo:
 *
 *   keyword    sản phẩm đi bằng `query`, video đi bằng `title`. Nhầm khoá = 200 kèm danh sách
 *              RỖNG, không báo lỗi.
 *   tiền       là CHUỖI đã rút gọn ("₫3,56tr"). Số thô là `sum(revenue_trend)` = `revenue_raw`.
 *   video      phải gửi `video.filter.video_type = "WithProduct"`, thiếu là mọi cột tiền bằng 0.
 *
 * ⚠️ MỖI TRANG `searchList` TRỪ MỘT LƯỢT CREDIT của gói. Nơi gọi (`research.js`) giới hạn số
 * trang và cache kết quả; ở đây chỉ chặn trần cứng.
 */

const KD_HOST = 'www.kalodata.com';
const KD_BASE = 'https://www.kalodata.com';
const KD_IMG = 'https://img.kalocdn.com';
const KD_REGIONS = ['US', 'GB', 'ID', 'VN', 'TH', 'MY', 'PH', 'SG', 'MX', 'DE', 'FR', 'IT', 'ES', 'JP', 'BR'];
const KD_PAGE_GAP_MS = 900;
// Trang Research không có lý do gì cần hơn thế trong một lượt; trần này chặn lỗi truyền nhầm.
const KD_MAX_PAGES = 5;
// Gói thuê bao chặn `pageSize` > 10 bằng paywall "Exceeded pagination limit" (đo 2026-09-08).
const KD_PAGE_SIZE = 10;

let kdBorrowedTabId = null;

function kdWaitComplete(tabId, timeoutMs) {
  return new Promise((resolve) => {
    const done = () => {
      chrome.tabs.onUpdated.removeListener(onUpdate);
      clearTimeout(timer);
      resolve();
    };
    const onUpdate = (id, info) => { if (id === tabId && info.status === 'complete') done(); };
    const timer = setTimeout(done, timeoutMs || 15000);
    chrome.tabs.onUpdated.addListener(onUpdate);
    chrome.tabs.get(tabId, (t) => {
      if (chrome.runtime.lastError) { done(); return; }
      if (t && t.status === 'complete') done();
    });
  });
}

/** Tab dự phòng: mượn tab kalodata.com đang mở, không có mới mở tab nền. KHÔNG tự đóng. */
async function kdTab() {
  if (kdBorrowedTabId != null) {
    try {
      const t = await chrome.tabs.get(kdBorrowedTabId);
      if (t && (t.url || '').includes(KD_HOST)) return t;
    } catch (e) { /* tab đã bị đóng */ }
    kdBorrowedTabId = null;
  }
  const open = await chrome.tabs.query({ url: `https://${KD_HOST}/*` });
  if (open.length) return open[0];
  const tab = await chrome.tabs.create({ url: `https://${KD_HOST}/product`, active: false });
  kdBorrowedTabId = tab.id;
  await kdWaitComplete(tab.id);
  return tab;
}

async function kdFetchInTab(tabId, url, init) {
  const injected = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    args: [url, init],
    func: async (u, opt) => {
      try {
        const r = await fetch(u, { method: opt.method || 'GET', headers: opt.headers || {}, body: opt.body || undefined, credentials: 'include' });
        return { status: r.status, text: await r.text() };
      } catch (e) {
        return { status: 0, text: String(e) };
      }
    },
  });
  return (injected && injected[0] && injected[0].result) || null;
}

/** `message` của Kalodata có lúc là object/JSON lồng nhau (paywall) — bóc ra câu người đọc được. */
function kdText(v) {
  if (v == null) return '';
  if (typeof v === 'string') {
    const t = v.trim();
    if (t.startsWith('{') || t.startsWith('[')) {
      try { return kdText(JSON.parse(t)); } catch (e) { return t; }
    }
    return t;
  }
  if (typeof v === 'object') return kdText(v.message) || kdText(v.desc) || kdText(v.msg) || JSON.stringify(v).slice(0, 180);
  return String(v);
}

function kdIsPaywall(raw) {
  return /UPGRADE|pagination limit|Exceeded/i.test(raw || '');
}

/** Khoảng ngày kết ở HÔM QUA: hôm nay chưa chốt số, lấy vào là doanh thu tụt giả. */
function kdRange(days) {
  const end = new Date(Date.now() - 86400000);
  const start = new Date(end.getTime() - (Math.max(1, days || 30) - 1) * 86400000);
  const iso = (d) => d.toISOString().slice(0, 10);
  return { startDate: iso(start), endDate: iso(end) };
}

/**
 * Fetch thẳng từ service worker trước; cookie SameSite=Lax không đi theo thì Kalodata trả 200
 * kèm HTML đăng nhập → lùi về chạy trong tab kalodata.com (same-origin). Phân biệt "chưa đăng
 * nhập" bằng HÌNH DẠNG phản hồi, không bằng mã trạng thái.
 */
async function kdSend(path, method, body) {
  const payload = body == null ? undefined : JSON.stringify(body);
  const headers = body == null ? {} : { 'Content-Type': 'application/json' };

  const readJson = (status, text) => {
    if (!text) return { fail: 'rỗng (HTTP ' + status + ')' };
    if (text.slice(0, 200).trim().startsWith('<')) return { fail: 'auth' };
    try {
      const j = JSON.parse(text);
      if (j && j.success === false) {
        return { fail: kdText(j.message) || kdText(j.data) || ('code ' + j.code), paywall: kdIsPaywall(text) };
      }
      return { data: j ? j.data : null };
    } catch (e) {
      return { fail: 'không phải JSON (HTTP ' + status + ')' };
    }
  };

  try {
    const r = await fetch(KD_BASE + path, { method, headers, body: payload, credentials: 'include' });
    const got = readJson(r.status, await r.text());
    if (!got.fail) return { data: got.data, via: 'sw' };
    if (got.fail !== 'auth' && r.status !== 401 && r.status !== 403) {
      return { error: got.fail, paywall: got.paywall, via: 'sw' };
    }
  } catch (e) {
    // Lỗi ở đây gần như luôn là cookie/CORS — đường tab không dính.
  }

  let tab;
  try {
    tab = await kdTab();
  } catch (e) {
    return { error: 'không mở được tab ' + KD_HOST + ': ' + String(e), via: 'tab' };
  }
  if (!tab || tab.id == null) return { error: 'không mở được tab ' + KD_HOST, via: 'tab' };

  const resp = await kdFetchInTab(tab.id, KD_BASE + path, { method, headers, body: payload });
  if (!resp) return { error: 'tab Kalodata không trả lời', via: 'tab' };
  const got = readJson(resp.status, resp.text);
  if (got.fail === 'auth') return { error: 'chưa đăng nhập Kalodata — đăng nhập www.kalodata.com rồi thử lại', auth: true, via: 'tab' };
  if (got.fail) return { error: got.fail, paywall: got.paywall, via: 'tab' };
  return { data: got.data, via: 'tab' };
}

function kdNormalize(kind, row) {
  const trend = Array.isArray(row.revenue_trend) ? row.revenue_trend : [];
  const id = row.id == null ? '' : String(row.id);
  return Object.assign({}, row, {
    id,
    revenue_raw: trend.reduce((a, v) => a + (typeof v === 'number' ? v : 0), 0),
    image: id ? KD_IMG + '/tiktok.' + kind + '/' + id + '/cover.png' : null,
  });
}

/**
 * Lặp trang cho tới khi đủ `pages` hoặc hết dữ liệu. `total` nằm trong MỖI bản ghi nên biết
 * được ngay sau trang đầu, khỏi gọi `/count`. Chạm paywall giữa chừng thì GIỮ những trang đã có.
 */
async function kdCrawl(kind, opts) {
  opts = opts || {};
  const country = String(opts.country || 'VN').toUpperCase();
  if (KD_REGIONS.indexOf(country) < 0) {
    return { items: [], error: 'Kalodata không hỗ trợ nước ' + country };
  }
  const pages = Math.min(Math.max(1, Number(opts.pages) || 1), KD_MAX_PAGES);
  const range = kdRange(opts.days);
  const keywordKey = kind === 'product' ? 'query' : 'title';

  const seen = new Set();
  const items = [];
  const notes = [];
  let total = null;
  let via = null;

  for (let page = 1; page <= pages; page++) {
    if (page > 1) await new Promise((r) => setTimeout(r, KD_PAGE_GAP_MS));
    const body = {
      country,
      startDate: range.startDate,
      endDate: range.endDate,
      cateIds: [],
      showCateIds: [],
      pageNo: page,
      pageSize: KD_PAGE_SIZE,
    };
    body[keywordKey] = opts.keyword || '';
    // Sort: product KHÔNG gửi khoá sort (request thật không có); video luôn `sale DESC`.
    if (kind === 'video') {
      body['video.filter.video_type'] = opts.videoType || 'WithProduct';
      body['video.filter.ad.daily_roas'] = '';
      body.sort = [{ field: 'sale', type: 'DESC' }];
    }

    const got = await kdSend('/' + kind + '/searchList', 'POST', body);
    via = got.via;
    if (got.error) {
      if (got.paywall && items.length) {
        notes.push('hết hạn mức phân trang của gói ở trang ' + page);
        break;
      }
      return {
        items, total, notes, via,
        error: got.paywall ? got.error + ' (giới hạn gói Kalodata)' : got.error,
        paywall: !!got.paywall, auth: !!got.auth,
      };
    }

    const rows = (Array.isArray(got.data) ? got.data : []).map((r) => kdNormalize(kind, r));
    if (rows.length && total == null && typeof rows[0].total === 'number') total = rows[0].total;
    for (const r of rows) {
      if (r.id && seen.has(r.id)) continue;
      if (r.id) seen.add(r.id);
      items.push(r);
    }
    if (rows.length < KD_PAGE_SIZE) break;
    if (total != null && items.length >= total) break;
  }
  return { items, total, notes, via, pagesDone: pages };
}

/**
 * Phiên còn sống không — `/user/features` KHÔNG thuộc nhóm route bị trừ credit.
 *
 * `loggedIn` BA TRẠNG THÁI như `checkLogin` của trang: true / false (bị đá về trang đăng nhập) /
 * null (lỗi mạng, không kết luận được). Gộp null vào false là dán ✕ oan lên TikTok Shop, và
 * `research()` bỏ qua sàn có ✕.
 */
async function kdStatus() {
  const got = await kdSend('/user/features', 'POST', { country: 'VN', list: ['FILTER.CUSTOM_TIMES'] });
  if (!got.error) return { loggedIn: true, via: got.via };
  return { loggedIn: got.auth ? false : null, via: got.via, error: got.error };
}

/**
 * Link PHÁT của một video, lấy TỪ CHÍNH KALODATA — đây là link Kalodata dùng để phát ngay trên
 * trang họ, xem được, khác với link `tiktok.com/@x/video/{id}` (bị TikTok đá về trang chung).
 *
 * `getVideoUrl` là GET (`?videoId=`), gửi POST là 404 câm. KHÔNG suy được từ id như ảnh cover
 * (đã thử `.mp4` cùng thư mục cover → 404). KHÔNG thuộc nhóm route bị trừ credit (chỉ các route
 * dạng queryList mới trừ) — xem `docs/kalodata-api.md`. `code 1053` = video đã gỡ/riêng tư.
 */
async function kdVideoUrl(videoId) {
  const id = String(videoId || '').trim();
  if (!id) return { url: null, error: 'thiếu videoId' };
  const got = await kdSend('/video/detail/getVideoUrl?videoId=' + encodeURIComponent(id), 'GET', null);
  if (got.error) return { url: null, error: got.error, auth: got.auth };
  const url = got.data && got.data.url;
  return url ? { url } : { url: null, error: 'Kalodata không trả link cho video này' };
}
