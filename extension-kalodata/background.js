/*
 * Kalodata Scraper — service worker.
 *
 * ĐỘC LẬP HOÀN TOÀN với Research-SPY Fetcher: không dùng chung file, không dùng chung quyền,
 * không dùng chung tab. Nó chỉ xin đúng hai host (`kalodata.com`, `img.kalocdn.com`), nên cài
 * kèm nhau cũng không ai đụng phiên đăng nhập của ai.
 *
 * HAI BỘ CÀO TÁCH BẠCH — `kdProducts()` và `kdVideos()` — dùng chung một lõi truyền tải.
 * Tách ra vì hai đầu KHÁC NHAU đúng ở chỗ dễ sai nhất:
 *
 *   keyword    sản phẩm đi bằng khoá `query`, video đi bằng `title`. Gửi nhầm khoá thì API
 *              vẫn trả 200 kèm `success:true` và một danh sách RỖNG — hỏng mà không báo hỏng.
 *   ảnh        hai namespace CDN khác nhau (`tiktok.product` / `tiktok.video`).
 *
 * TIỀN TRẢ VỀ LÀ CHUỖI ĐÃ RÚT GỌN ("₫3,56tr") — đừng bao giờ parse nó. Số thô nằm ở
 * `revenue_trend`: mảng số nguyên theo ngày, cộng lại bằng ĐÚNG `revenue` tới từng đồng
 * (đo 2026-09-08: 702567+332263+…+332409 = 3.559.356 ⇢ "₫3,56tr"). `revenue_raw` là chỗ đó.
 *
 * ẢNH KHÔNG NẰM TRONG RESPONSE. Trang render bằng CSS `background-image` nên không có thẻ
 * <img> nào để bóc — nhưng URL suy được thẳng từ id, và nó PUBLIC: curl không cookie vẫn
 * trả 200 image/png. Nghĩa là ảnh không tốn thêm lượt gọi nào, cũng không tốn credit.
 *
 * ⚠️ TRỪ CREDIT: `searchList` ăn quota gói thuê bao y như bấm tay trên web. Vì vậy vòng lặp
 * trang dừng SỚM ngay khi biết đã hết dữ liệu, và có nghỉ giữa các trang.
 */

const VERSION = '2.1.0';

const KD_HOST = 'www.kalodata.com';
const KD_BASE = 'https://www.kalodata.com';
const KD_IMG = 'https://img.kalocdn.com';

// Rút từ bundle `production/assets/index-*.js`. Gửi mã ngoài danh sách này thì API trả rỗng.
const KD_REGIONS = ['US', 'GB', 'ID', 'VN', 'TH', 'MY', 'PH', 'SG', 'MX', 'DE', 'FR', 'IT', 'ES', 'JP', 'BR'];

const KD_PAGE_GAP_MS = 900;   // nghỉ giữa hai trang — vừa lịch sự vừa đỡ bị chặn
const KD_MAX_PAGES = 50;      // trần cứng, chặn lỗi gõ `pages: 9999` đốt sạch credit

// CỠ TRANG AN TOÀN. Giao diện web thật gửi đúng 10, và gói thuê bao chặn cỡ lớn hơn bằng
// lỗi "Exceeded pagination limit" kèm `actionType.code = "UPGRADE"` — nó KHÔNG phải lỗi kỹ
// thuật mà là paywall, nên thử lại y nguyên là vô ích. Đo 2026-09-08: pageNo=1 pageSize=20
// đã dính, pageSize=10 thì qua.
const KD_SAFE_PAGE_SIZE = 10;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── tab dự phòng ───────────────────────────────────────────────────────────
 *
 * Chỉ dùng khi fetch thẳng không mang được cookie. Mượn tab kalodata.com người dùng đang mở
 * trước đã; không có mới tự mở một tab nền. Tab tự mở được nhớ lại để lần sau dùng lại thay
 * vì mở thêm — nhưng KHÔNG tự đóng: người dùng có thể đang xem dở trang đó.
 */

let borrowedTabId = null;

function waitForComplete(tabId, timeoutMs = 15000) {
  return new Promise((resolve) => {
    const done = () => {
      chrome.tabs.onUpdated.removeListener(onUpdate);
      clearTimeout(timer);
      resolve();
    };
    const onUpdate = (id, info) => { if (id === tabId && info.status === 'complete') done(); };
    const timer = setTimeout(done, timeoutMs);
    chrome.tabs.onUpdated.addListener(onUpdate);
    chrome.tabs.get(tabId, (t) => {
      if (chrome.runtime.lastError) { done(); return; }
      if (t && t.status === 'complete') done();
    });
  });
}

async function kdTab() {
  if (borrowedTabId != null) {
    try {
      const t = await chrome.tabs.get(borrowedTabId);
      if (t && (t.url || '').includes(KD_HOST)) return t;
    } catch (e) { /* tab đã bị đóng */ }
    borrowedTabId = null;
  }

  const open = await chrome.tabs.query({ url: `https://${KD_HOST}/*` });
  if (open.length) return open[0];

  const tab = await chrome.tabs.create({ url: `https://${KD_HOST}/product`, active: false });
  borrowedTabId = tab.id;
  await waitForComplete(tab.id);
  return tab;
}

/** Chạy trong context TRANG (MAIN world) — đây là chỗ fetch trở thành same-origin. */
async function fetchInTab(tabId, url, init) {
  const injected = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    args: [url, init],
    func: async (u, opt) => {
      try {
        const r = await fetch(u, {
          method: opt.method || 'GET',
          headers: opt.headers || {},
          body: opt.body || undefined,
          credentials: 'include',
        });
        return { status: r.status, text: await r.text() };
      } catch (e) {
        return { status: 0, text: String(e) };
      }
    },
  });
  return (injected && injected[0] && injected[0].result) || null;
}

/* ── lõi truyền tải ─────────────────────────────────────────────────────── */

/**
 * Bóc câu chữ người đọc được ra khỏi lỗi.
 *
 * `message` của Kalodata KHÔNG phải lúc nào cũng là chuỗi: khi chạm paywall nó là cả một
 * object (hoặc một chuỗi chứa JSON) dạng
 * `{message, cause: "PRODUCT.LIST", actionType: {code: "UPGRADE", desc}}`. Nhét thẳng thứ đó
 * vào giao diện thì người dùng nhận nguyên khối JSON — đúng cái vừa xảy ra.
 */
function kdText(v) {
  if (v == null) return '';
  if (typeof v === 'string') {
    const t = v.trim();
    if (t.startsWith('{') || t.startsWith('[')) {
      try { return kdText(JSON.parse(t)); } catch (e) { return t; }
    }
    return t;
  }
  if (typeof v === 'object') {
    return kdText(v.message) || kdText(v.desc) || kdText(v.msg) || JSON.stringify(v).slice(0, 180);
  }
  return String(v);
}

/** Paywall (cỡ trang / số trang vượt hạn mức gói) chứ không phải lỗi kỹ thuật. */
function kdIsPaywall(raw) {
  return /UPGRADE|pagination limit|Exceeded/i.test(raw || '');
}

/** Khoảng ngày kết ở HÔM QUA: dữ liệu hôm nay chưa chốt, lấy vào là thấy doanh thu tụt giả. */
function kdRange(days) {
  const end = new Date(Date.now() - 86400000);
  const start = new Date(end.getTime() - (Math.max(1, days || 30) - 1) * 86400000);
  const iso = (d) => d.toISOString().slice(0, 10);
  return { startDate: iso(start), endDate: iso(end) };
}

function kdImage(kind, id) {
  return id ? KD_IMG + '/tiktok.' + kind + '/' + id + '/cover.png' : null;
}

/**
 * Gọi API bằng chính phiên đăng nhập của người dùng.
 *
 * ĐI THẲNG TỪ SERVICE WORKER TRƯỚC vì nó không cần tab nào cả. Nhưng cookie phiên có thể là
 * SameSite=Lax, và khi ấy request khởi từ extension KHÔNG mang cookie đi — API trả về trang
 * đăng nhập (HTML) thay vì JSON. Đó là lý do có đường lùi qua tab: chạy trong context
 * kalodata.com thì fetch thành same-origin và cookie chắc chắn đi kèm.
 *
 * Phân biệt "chưa đăng nhập" với "lỗi mạng" bằng chính HÌNH DẠNG phản hồi chứ không bằng mã
 * trạng thái: Kalodata trả 200 kèm HTML khi phiên hỏng, nên xét status là xét trượt.
 */
async function kdSend(path, method, body) {
  const payload = body == null ? undefined : JSON.stringify(body);
  const headers = body == null ? {} : { 'Content-Type': 'application/json' };

  const readJson = (status, text) => {
    if (!text) return { fail: 'rỗng (HTTP ' + status + ')' };
    if (text.slice(0, 200).trim().startsWith('<')) return { fail: 'auth' };  // bị đá về trang đăng nhập
    try {
      const j = JSON.parse(text);
      if (j && j.success === false) {
        return {
          fail: kdText(j.message) || kdText(j.data) || ('code ' + j.code),
          paywall: kdIsPaywall(text),
        };
      }
      return { data: j ? j.data : null };
    } catch (e) {
      return { fail: 'không phải JSON (HTTP ' + status + ')' };
    }
  };

  try {
    const r = await fetch(KD_BASE + path, { method, headers, body: payload, credentials: 'include' });
    const got = readJson(r.status, await r.text());
    if (!got.fail) return { items: got.data || [], data: got.data, via: 'sw' };
    if (got.fail !== 'auth' && r.status !== 401 && r.status !== 403) {
      return { items: [], error: got.fail, paywall: got.paywall, via: 'sw' };
    }
  } catch (e) {
    // Nuốt và rơi xuống đường tab: lỗi ở đây gần như luôn là cookie/CORS, mà tab thì không dính.
  }

  let tab;
  try {
    tab = await kdTab();
  } catch (e) {
    return { items: [], error: 'không mở được tab ' + KD_HOST + ': ' + String(e), via: 'tab' };
  }
  if (!tab || tab.id == null) return { items: [], error: 'không mở được tab ' + KD_HOST, via: 'tab' };

  const resp = await fetchInTab(tab.id, KD_BASE + path, { method, headers, body: payload });
  if (!resp) return { items: [], error: 'tab không trả lời', via: 'tab' };
  const got = readJson(resp.status, resp.text);
  if (got.fail === 'auth') {
    return { items: [], error: 'chưa đăng nhập Kalodata — mở www.kalodata.com đăng nhập rồi chạy lại', via: 'tab' };
  }
  if (got.fail) return { items: [], error: got.fail, paywall: got.paywall, via: 'tab' };
  return { items: got.data || [], data: got.data, via: 'tab' };
}

const kdPost = (path, body) => kdSend(path, 'POST', body);

/** GET kèm query string. `getVideoUrl` là GET chứ không phải POST — gửi POST là 404 câm. */
const kdGet = (path, params) => {
  const q = new URLSearchParams(params || {}).toString();
  return kdSend(path + (q ? '?' + q : ''), 'GET', null);
};

/**
 * Link phát video, lấy từ chính Kalodata.
 *
 * KHÔNG suy được từ id như ảnh: đã thử `img.kalocdn.com/tiktok.video/{id}/{video,play,origin}.mp4`
 * — 404 cả ba, trong khi `cover.png` cùng thư mục thì 200. Phải hỏi API.
 *
 * Khung nhúng của TikTok cũng không thay thế được: `embed/v2` trả 503 "overload-protect",
 * `player/v1` thì tuỳ lúc. Đây mới là đường Kalodata dùng để phát ngay trên trang họ.
 *
 * `code 1053` = video không còn link (đã gỡ / riêng tư), không phải lỗi phiên.
 */
async function kdVideoUrl(videoId) {
  const got = await kdGet('/video/detail/getVideoUrl', { videoId });
  if (got.error) return { url: null, error: got.error };
  const url = got.data && got.data.url;
  return url ? { url } : { url: null, error: 'Kalodata không trả link cho video này' };
}

/** Bù hai chỗ API hụt: số tiền thô và URL ảnh. Giữ nguyên mọi field gốc. */
function kdNormalize(kind, row) {
  const trend = Array.isArray(row.revenue_trend) ? row.revenue_trend : [];
  const id = row.id == null ? '' : String(row.id);
  return Object.assign({}, row, {
    id,
    revenue_raw: trend.reduce((a, v) => a + (typeof v === 'number' ? v : 0), 0),
    image: kdImage(kind, id),
  });
}

/**
 * Lõi chung: lặp trang cho tới khi đủ hoặc hết.
 *
 * `total` nằm trong MỖI bản ghi chứ không phải ở vỏ response, nên biết được tổng ngay sau
 * trang đầu và dừng đúng lúc — khỏi gọi `/{kind}/count` cho tốn thêm một lượt.
 */
async function kdCrawl(kind, opts) {
  const country = String(opts.country || 'VN').toUpperCase();
  if (KD_REGIONS.indexOf(country) < 0) {
    return { items: [], error: 'region ' + country + ' không hợp lệ (chỉ: ' + KD_REGIONS.join(', ') + ')' };
  }
  const keywordKey = kind === 'product' ? 'query' : 'title';
  let size = Math.min(Math.max(1, opts.pageSize || KD_SAFE_PAGE_SIZE), 50);
  const pages = Math.min(Math.max(1, opts.pages || 1), KD_MAX_PAGES);
  // Cho phép gọi từng trang một. Bảng điều khiển dùng để vừa lật vừa vẽ, thay vì ngồi chờ
  // hết job mới thấy gì — và để dừng đúng chỗ khi chạm trần gói.
  const from = Math.max(1, opts.startPage || 1);
  const range = kdRange(opts.days);

  const seen = new Set();
  const items = [];
  const notes = [];
  let total = null;
  let done = 0;

  const ask = (page) => {
    const body = {
      country,
      startDate: range.startDate,
      endDate: range.endDate,
      cateIds: opts.cateIds || [],
      showCateIds: [],
      pageNo: page,
      pageSize: size,
    };
    body[keywordKey] = opts.keyword || '';

    // LỌC VIDEO CÓ GẮN SẢN PHẨM. Thiếu khoá này là hỏng câm kiểu khác: API trả về đủ dòng,
    // nhưng toàn video organic (#fyp, #earphones) nên MỌI cột tiền đều bằng 0 — trông y như
    // lỗi parse. Request thật của web luôn gửi `WithProduct`; `daily_roas` rỗng đi kèm nó.
    if (kind === 'video') {
      body['video.filter.video_type'] = opts.videoType || 'WithProduct';
      body['video.filter.ad.daily_roas'] = '';
    }

    // SORT: hai module KHÁC NHAU, cứ theo đúng request thật đã bắt được.
    //   product  không có khoá `sort` — nhét thừa một khoá lạ vào API nội bộ là cách nhanh
    //            nhất để nhận về danh sách rỗng.
    //   video    LUÔN có `sort: [{field:"sale",type:"DESC"}]`. Nên video thiếu sort thì gửi
    //            đúng mặc định đó thay vì bỏ trống.
    const sortField = opts.sort || (kind === 'video' ? 'sale' : null);
    if (sortField) body.sort = [{ field: sortField, type: opts.sortDir === 'ASC' ? 'ASC' : 'DESC' }];
    return kdPost('/' + kind + '/searchList', body);
  };

  for (let n = 0; n < pages; n++) {
    const page = from + n;
    if (n > 0) await sleep(KD_PAGE_GAP_MS);

    let got = await ask(page);

    // HẠ CỠ TRANG RỒI THỬ LẠI — đúng một lần, và chỉ khi paywall bắt vì cỡ trang. Gói thuê
    // bao chặn `pageSize` lớn, nhưng lấy 10 dòng vẫn hơn hẳn trả về tay không; từ trang sau
    // `size` giữ nguyên mức đã hạ nên không đâm đầu vào tường thêm lần nữa.
    if (got.error && got.paywall && size > KD_SAFE_PAGE_SIZE) {
      notes.push('gói chặn pageSize ' + size + ' → đã hạ về ' + KD_SAFE_PAGE_SIZE);
      size = KD_SAFE_PAGE_SIZE;
      await sleep(KD_PAGE_GAP_MS);
      got = await ask(page);
    }

    if (got.error) {
      // Chạm trần phân trang giữa chừng KHÔNG phải hỏng: những trang đã lấy được vẫn dùng
      // tốt. Trả về kèm ghi chú thay vì vứt hết đi.
      if (got.paywall && items.length) {
        notes.push('hết hạn mức phân trang của gói ở trang ' + page);
        break;
      }
      const why = got.paywall ? got.error + ' (giới hạn gói thuê bao, không phải lỗi kỹ thuật)' : got.error;
      return { items, total, error: why, paywall: got.paywall, via: got.via, pagesDone: done, notes, pageSize: size };
    }
    done++;

    const rows = (got.items || []).map((r) => kdNormalize(kind, r));
    if (rows.length && total == null && typeof rows[0].total === 'number') total = rows[0].total;

    for (const r of rows) {
      if (r.id && seen.has(r.id)) continue;
      if (r.id) seen.add(r.id);
      items.push(r);
    }

    // Hết dữ liệu: trang trả về ít hơn cỡ trang, hoặc đã gom đủ `total`. Chạy tiếp chỉ là
    // đốt credit để nhận về mảng rỗng.
    if (rows.length < size) break;
    if (total != null && items.length >= total) break;
  }

  return { items, total, pagesDone: done, notes, pageSize: size };
}

/** BỘ CÀO SẢN PHẨM. keyword → `query`, ảnh → tiktok.product. */
async function kdProducts(opts) {
  return kdCrawl('product', opts || {});
}

/** BỘ CÀO VIDEO. keyword → `title`, ảnh → tiktok.video. */
async function kdVideos(opts) {
  return kdCrawl('video', opts || {});
}

/** Quét nhiều region trong một lượt. Mỗi region là một lượt gọi riêng — credit nhân lên. */
async function kdSweep(kind, opts) {
  const list = ((opts && opts.countries) || ['VN']).map((c) => String(c).toUpperCase());
  const out = {};
  for (let i = 0; i < list.length; i++) {
    if (i > 0) await sleep(KD_PAGE_GAP_MS);
    out[list[i]] = await kdCrawl(kind, Object.assign({}, opts, { country: list[i] }));
  }
  return out;
}

/** Phiên còn sống không — gọi endpoint rẻ, KHÔNG nằm trong nhóm bị trừ credit. */
async function kdStatus() {
  const got = await kdPost('/user/features', { country: 'VN', list: ['FILTER.CUSTOM_TIMES'] });
  return { ok: !got.error, via: got.via, error: got.error || null };
}

/* ── lấy mp4 thật từ trang TikTok ───────────────────────────────────────────
 *
 * ĐƯỜNG CUỐI, sau khi ba đường nhúng đều đã đo là hỏng:
 *
 *   embed/v2 & player/v1 từ chrome-extension://   vỏ dựng xong, không tạo thẻ <video>
 *   thêm tham số ?referrer= như embed.js tự sinh   script chạy, bấm play vẫn không ra hình
 *   nhúng từ origin kalodata.com                   cũng không phát
 *
 * TikTok khoá phát theo origin, không lách được bằng tham số. Nhưng CHÍNH TRANG TIKTOK trong
 * trình duyệt của người dùng thì có đủ cookie phiên, và trang đó nhúng sẵn link mp4 trong
 * `__UNIVERSAL_DATA_FOR_REHYDRATION__`. Fetch từ server không lấy được (đo: trang trả về vỏn
 * vẹn 1.462 byte, không có `playAddr`) — phải đọc TỪ TRONG tab thật.
 *
 * KHÔNG tốn request Kalodata nào: toàn bộ việc này chỉ đụng tới tiktok.com.
 */

const TT_HOST = 'www.tiktok.com';
let ttTabId = null;

async function ttTab(url) {
  if (ttTabId != null) {
    try {
      const t = await chrome.tabs.get(ttTabId);
      if (t) {
        await chrome.tabs.update(ttTabId, { url, active: false });
        await waitForComplete(ttTabId, 25000);
        return t;
      }
    } catch (e) { /* tab đã bị đóng */ }
    ttTabId = null;
  }
  const tab = await chrome.tabs.create({ url, active: false });
  ttTabId = tab.id;
  await waitForComplete(tab.id, 25000);
  return tab;
}

/** Chạy trong trang TikTok. Phải tự chứa — `executeScript` không mang closure theo. */
function ttScrapePlayAddr() {
  // Ưu tiên khối JSON trang tự nhúng: nó có sẵn nhiều mức bitrate và không phụ thuộc việc
  // người dùng đã bấm play hay chưa.
  const pick = (o, depth) => {
    if (!o || depth > 8 || typeof o !== 'object') return null;
    if (typeof o.playAddr === 'string' && o.playAddr) return o.playAddr;
    for (const k of Object.keys(o)) {
      const hit = pick(o[k], depth + 1);
      if (hit) return hit;
    }
    return null;
  };

  const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
  if (el) {
    try {
      const found = pick(JSON.parse(el.textContent), 0);
      if (found) return { url: found, from: 'rehydration' };
    } catch (e) { /* JSON đổi hình dạng — rơi xuống cách dưới */ }
  }

  // Dự phòng: thẻ <video> mà trang đã dựng. `currentSrc` đôi khi là blob: — vô dụng ở ngoài
  // tab này, nên chỉ nhận http(s).
  const v = document.querySelector('video');
  const src = v && (v.currentSrc || v.src || '');
  if (src && src.startsWith('http')) return { url: src, from: 'video-tag' };

  return { url: null, from: 'không thấy', title: document.title.slice(0, 80) };
}

/** Tải mp4 NGAY TRONG tab TikTok rồi trả về data URL: ở đó Referer và cookie mới đúng. */
async function ttFetchAsDataUrl(tabId, url) {
  const [out] = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    args: [url],
    func: async (u) => {
      try {
        const r = await fetch(u, { credentials: 'include' });
        if (!r.ok) return { error: 'HTTP ' + r.status };
        const b = await r.blob();
        // 40 MB là trần tự đặt: video TikTok thường 1–5 MB, vượt xa mức đó nghĩa là đã lấy
        // nhầm thứ khác, và nhồi vào kênh message thì treo cả extension.
        if (b.size > 40 * 1024 * 1024) return { error: 'file quá lớn (' + Math.round(b.size / 1048576) + ' MB)' };
        return await new Promise((res) => {
          const fr = new FileReader();
          fr.onload = () => res({ dataUrl: fr.result, size: b.size });
          fr.onerror = () => res({ error: 'không đọc được blob' });
          fr.readAsDataURL(b);
        });
      } catch (e) {
        return { error: String(e) };
      }
    },
  });
  return (out && out.result) || { error: 'tab không trả lời' };
}

/**
 * videoId → data URL phát được ngay trong bảng.
 *
 * Trả về data URL chứ không phải link CDN: link đó gần như luôn đòi Referer tiktok.com, mà
 * trang extension thì không gửi được header đó. Tải sẵn thành bytes là hết chuyện.
 */
async function ttCanonical(videoId) {
  // PHẢI CÓ TÊN TÀI KHOẢN THẬT. Link `@x/video/{id}` trả HTTP 200 nên nhìn qua tưởng dùng
  // được, nhưng đó chỉ là cái vỏ: mở trong tab thật thì TikTok đá về trang chung — đo được
  // 2026-09-08 qua tiêu đề trang trả về đúng "TikTok - Make Your Day", và khối
  // `__UNIVERSAL_DATA_FOR_REHYDRATION__` khi ấy không hề có video nào.
  //
  // oEmbed công khai, không cần đăng nhập, không tốn credit Kalodata — và nó cho đúng
  // `author_url`.
  try {
    const api = 'https://www.tiktok.com/oembed?url='
      + encodeURIComponent('https://www.tiktok.com/@x/video/' + videoId);
    const r = await fetch(api);
    if (r.ok) {
      const j = await r.json();
      if (j && j.author_url) return j.author_url + '/video/' + videoId;
    }
  } catch (e) { /* hỏng thì dùng link bịa, vẫn hơn là không thử */ }
  return 'https://www.tiktok.com/@x/video/' + videoId;
}

async function ttVideo(videoId) {
  const url = await ttCanonical(videoId);

  let tab;
  try {
    tab = await ttTab(url);
  } catch (e) {
    return { error: 'không mở được tab TikTok: ' + String(e) };
  }
  if (!tab || tab.id == null) return { error: 'không mở được tab TikTok' };

  // CHỜ BẰNG CÁCH THĂM DÒ, không chờ theo đồng hồ. Trang dựng nội dung sau khi tải xong, và
  // một mốc cứng 2,5s thì lúc mạng chậm là đọc hụt — mà đọc hụt trông y hệt bị chặn.
  let found = {};
  for (let i = 0; i < 10; i++) {
    if (i > 0) await sleep(1500);
    const [got] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      func: ttScrapePlayAddr,
    });
    found = (got && got.result) || {};
    if (found.url) break;
  }
  if (!found.url) {
    return { error: 'không tìm thấy link video trong trang TikTok'
      + (found.title ? ' (trang: ' + found.title + ')' : '') + ' · đã mở: ' + url };
  }

  const blob = await ttFetchAsDataUrl(tab.id, found.url);
  if (blob.error) return { error: 'tải video hỏng: ' + blob.error, from: found.from };
  return { dataUrl: blob.dataUrl, size: blob.size, from: found.from };
}

/* ── phát video trong tab Kalodata ──────────────────────────────────────────
 *
 * VÌ SAO PHẢI MƯỢN TAB KALODATA CHỨ KHÔNG PHÁT NGAY TRONG BẢNG.
 *
 * TikTok chặn theo ORIGIN CỦA TRANG CHA. Đo 2026-09-08 trên cùng một video, cùng một URL
 * `player/v1`:
 *
 *   nhúng từ https://www.kalodata.com   → phát bình thường, có khung hình, 00:00/00:54
 *   mở thẳng ở tab tiktok.com           → dựng vỏ (avatar, mô tả) rồi KHÔNG tạo thẻ <video>
 *   nhúng từ chrome-extension://        → y hệt: vỏ có, luồng video không
 *
 * Không phải CSP hay X-Frame-Options — TikTok không đặt `frame-ancestors`, cũng không đặt
 * `X-Frame-Options`. Nó tự từ chối nạp luồng khi trang cha không phải một website thật.
 * Extension không giả được origin, nên đường duy nhất là dựng lớp phủ NGAY TRONG tab
 * kalodata.com rồi đưa tab đó ra trước.
 */

/** Chạy trong trang kalodata.com. Phải tự chứa: `executeScript` không mang closure theo. */
function kdOverlay(videoId) {
  const old = document.getElementById('rs-kd-overlay');
  if (old) old.remove();

  const wrap = document.createElement('div');
  wrap.id = 'rs-kd-overlay';
  wrap.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.74);'
    + 'display:flex;align-items:center;justify-content:center';

  const box = document.createElement('div');
  box.style.cssText = 'background:#111;padding:10px;border-radius:12px';

  const bar = document.createElement('div');
  bar.style.cssText = 'display:flex;justify-content:flex-end;margin-bottom:8px';

  const btn = document.createElement('button');
  btn.textContent = 'Đóng ✕';
  btn.style.cssText = 'font:600 13px system-ui;padding:6px 12px;border-radius:8px;border:0;'
    + 'background:#fff;color:#111;cursor:pointer';

  const frame = document.createElement('iframe');
  // ĐÚNG URL MÀ `embed.js` CỦA TIKTOK TỰ SINH RA. Đo 2026-09-08: chạy script nhúng chính chủ
  // trên kalodata.com thì nó dựng iframe với dạng
  //   embed/v2/{id}?lang=en-US&referrer=<url trang cha, đã encode>
  // Bám theo đúng dạng đó thay vì tự chế `player/v1`, để TikTok thấy y hệt một lượt nhúng thật.
  frame.src = 'https://www.tiktok.com/embed/v2/' + videoId
    + '?lang=vi-VN&referrer=' + encodeURIComponent('https://www.kalodata.com/');
  frame.width = 325;
  frame.height = 580;
  frame.allow = 'autoplay; encrypted-media; picture-in-picture';
  frame.setAttribute('allowfullscreen', '');
  frame.style.cssText = 'border:0;border-radius:8px;display:block;background:#000';

  const close = () => {
    wrap.remove();
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (e) => { if (e.key === 'Escape') close(); };

  btn.addEventListener('click', close);
  // Chỉ đóng khi bấm đúng lớp nền, không đóng khi bấm vào khung phát.
  wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });
  document.addEventListener('keydown', onKey);

  bar.appendChild(btn);
  box.appendChild(bar);
  box.appendChild(frame);
  wrap.appendChild(box);
  document.body.appendChild(wrap);
  return true;
}

async function kdPlayInTab(videoId) {
  let tab;
  try {
    tab = await kdTab();
  } catch (e) {
    return { ok: false, error: 'không mở được tab ' + KD_HOST + ': ' + String(e) };
  }
  if (!tab || tab.id == null) return { ok: false, error: 'không mở được tab ' + KD_HOST };

  await chrome.scripting.executeScript({ target: { tabId: tab.id }, args: [String(videoId)], func: kdOverlay });
  // Đưa tab ra trước: lớp phủ dựng ở tab nền thì người dùng chẳng thấy gì, tưởng hỏng tiếp.
  await chrome.tabs.update(tab.id, { active: true });
  try {
    await chrome.windows.update(tab.windowId, { focused: true });
  } catch (e) { /* tab có thể ở cửa sổ đã đóng — không đáng để hỏng cả việc */ }
  return { ok: true, tabId: tab.id };
}

/* ── vào ra ─────────────────────────────────────────────────────────────── */

// Không có popup: bấm icon là mở thẳng bảng cào. Popup rộng 360px và tự đóng mỗi lần mất
// focus — chạy một job nhiều trang trong đó là mất kết quả giữa chừng.
chrome.action.onClicked.addListener(() => {
  chrome.tabs.create({ url: chrome.runtime.getURL('panel.html') });
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg !== 'object') return;

  if (msg.type === 'KD_PING') {
    sendResponse({ ok: true, version: VERSION, regions: KD_REGIONS });
    return;
  }

  if (msg.type === 'KD_PRODUCT') {
    kdProducts(msg.opts || {})
      .then((r) => sendResponse(Object.assign({ ok: true, kind: 'product' }, r)))
      .catch((e) => sendResponse({ ok: true, kind: 'product', items: [], error: String(e) }));
    return true; // giữ kênh mở cho phản hồi bất đồng bộ
  }

  if (msg.type === 'KD_VIDEO') {
    kdVideos(msg.opts || {})
      .then((r) => sendResponse(Object.assign({ ok: true, kind: 'video' }, r)))
      .catch((e) => sendResponse({ ok: true, kind: 'video', items: [], error: String(e) }));
    return true;
  }

  if (msg.type === 'KD_SWEEP') {
    kdSweep(msg.kind === 'video' ? 'video' : 'product', msg.opts || {})
      .then((byRegion) => sendResponse({ ok: true, byRegion }))
      .catch((e) => sendResponse({ ok: true, byRegion: {}, error: String(e) }));
    return true;
  }

  if (msg.type === 'KD_VIDEO_URL') {
    kdVideoUrl(msg.videoId)
      .then((r) => sendResponse(Object.assign({ ok: true }, r)))
      .catch((e) => sendResponse({ ok: false, url: null, error: String(e) }));
    return true;
  }

  if (msg.type === 'KD_PLAY_IN_TAB') {
    kdPlayInTab(msg.videoId)
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (msg.type === 'TT_VIDEO') {
    ttVideo(msg.videoId)
      .then((r) => sendResponse(Object.assign({ ok: !r.error }, r)))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (msg.type === 'KD_STATUS') {
    kdStatus()
      .then((r) => sendResponse(Object.assign({ ok: true }, r)))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
});
