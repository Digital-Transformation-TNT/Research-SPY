/*
 * Popup tự test — soi gương logic của backend (build_request + parse_response ở shopee.py),
 * để chứng minh: cùng lệnh fetch đó, chạy trong trình duyệt đã đăng nhập thì RA DATA THẬT,
 * còn chạy từ server thì 403.
 */

const DOMAIN = {
  VN: 'shopee.vn', TH: 'shopee.co.th', PH: 'shopee.ph', MY: 'shopee.com.my', ID: 'shopee.co.id', SG: 'shopee.sg',
  TW: 'shopee.tw', BR: 'shopee.com.br', MX: 'shopee.com.mx', CO: 'shopee.com.co', CL: 'shopee.cl',
};
const IMG_REGION = { VN: 'vn', TH: 'th', PH: 'ph', MY: 'my', ID: 'id', SG: 'sg', TW: 'tw', BR: 'br', MX: 'mx', CO: 'co', CL: 'cl' };
const CURRENCY = { VN: 'VND', TH: 'THB', PH: 'PHP', MY: 'MYR', ID: 'IDR', SG: 'SGD', TW: 'TWD', BR: 'BRL', MX: 'MXN', CO: 'COP', CL: 'CLP' };
const PRICE_SCALE = 100000;

function searchUrl(domain, keyword) {
  const q = new URLSearchParams({
    // by=sales = sort "Bán chạy" (giống ?sortBy=sales trên web) → top-seller thật, ít quảng cáo.
    by: 'sales', keyword, limit: '20', newest: '0', order: 'desc',
    page_type: 'search', scenario: 'PAGE_GLOBAL_SEARCH', version: '2',
  });
  return `https://${domain}/api/v4/search/search_items?${q.toString()}`;
}

function imageUrl(region, hash) {
  if (!hash) return '';
  return `https://down-${IMG_REGION[region] || 'vn'}.img.susercontent.com/file/${hash}`;
}

function fmtPrice(v, cur) {
  if (v == null) return '';
  return new Intl.NumberFormat('vi-VN').format(Math.round(v)) + ' ' + cur;
}

const $ = (id) => document.getElementById(id);
const statusEl = $('status');
const listEl = $('list');

function setStatus(msg, kind) {
  statusEl.textContent = msg;
  statusEl.className = 'status' + (kind ? ' ' + kind : '');
}

async function fetchViaBackground(url, domain, keyword) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      {
        type: 'RS_FETCH',
        requests: [{
          url,
          method: 'GET',
          headers: {
            'x-api-source': 'pc',
            'x-requested-with': 'XMLHttpRequest',
            referer: `https://${domain}/search?keyword=${encodeURIComponent(keyword)}`,
          },
          tag: 'page-0',
        }],
      },
      (resp) => resolve((resp && resp.responses && resp.responses[0]) || null)
    );
  });
}

async function run() {
  const keyword = $('kw').value.trim();
  const region = $('region').value;
  if (!keyword) { setStatus('Nhập từ khoá đã.', 'err'); return; }

  const domain = DOMAIN[region];
  listEl.innerHTML = '';
  setStatus('Đang lấy dữ liệu…');
  $('go').disabled = true;

  try {
    const res = await fetchViaBackground(searchUrl(domain, keyword), domain, keyword);
    if (!res) { setStatus('Không nhận được phản hồi từ extension.', 'err'); return; }

    if (res.status === 0 && String(res.text).startsWith('NO_TAB')) {
      setStatus('Chưa mở được tab ' + domain + '. Mở một tab ' + domain + ' (đã đăng nhập) rồi thử lại.', 'err');
      return;
    }
    if (res.status === 0 && String(res.text).startsWith('INJECT_FAIL')) {
      setStatus('Không chèn được vào tab Shopee: ' + res.text, 'err');
      return;
    }
    if (res.status === 403) {
      setStatus('403 — Shopee vẫn chặn dù đã đăng nhập. Có thể cần chữ ký chống bot; báo lại để đổi cách lấy.', 'err');
      return;
    }
    if (res.status !== 200) {
      setStatus('Shopee trả HTTP ' + res.status + ' (' + String(res.text).slice(0, 60) + ').', 'err');
      return;
    }

    let data;
    try { data = JSON.parse(res.text); } catch { setStatus('Phản hồi không phải JSON.', 'err'); return; }
    const items = (data && (data.items || data.data?.items)) || [];
    if (!items.length) { setStatus('Không có kết quả cho từ khoá này.', 'err'); return; }

    document.getElementById('debug').style.display = 'none';
    document.getElementById('copy').style.display = 'none';

    lastItems = items; // để nút find-similar đọc itemid/shopid/catid của SP đầu
    document.getElementById('similar').style.display = 'block';

    setStatus(`OK — lấy được ${items.length} sản phẩm (HTTP 200) bằng phiên của bạn.`, 'ok');
    for (const it of items) {
      // Format 2026: item_basic bỏ; data ở item_card_displayed_asset (tên/ảnh) + item_data (giá/bán).
      const asset = it.item_card_displayed_asset || {};
      const idata = it.item_data || {};
      const basic = it.item_basic || {};

      const dp = idata.item_card_display_price || asset.display_price || {};
      const rawPrice = dp.price ?? basic.price;
      const price = typeof rawPrice === 'number' && rawPrice > 0 ? rawPrice / PRICE_SCALE : null;

      const sc = idata.item_card_display_sold_count || {};
      const sold = sc.historical_sold_count ?? sc.monthly_sold_count ?? basic.historical_sold ?? basic.sold ?? 0;

      const name = asset.name || basic.name || '';
      const imgHash = asset.image || (Array.isArray(asset.images) ? asset.images[0] : '') || basic.image;
      const shop = (idata.shop_data || {}).shop_name || asset.shop_location || '';
      const isAd = !!it.adsid;

      const el = document.createElement('div');
      el.className = 'item';
      el.innerHTML =
        `<img src="${imageUrl(region, imgHash)}" alt="" loading="lazy" />` +
        `<div><div class="name">${String(name).replace(/</g, '&lt;')}</div>` +
        `<div class="meta"><span class="price">${fmtPrice(price, CURRENCY[region])}</span>` +
        ` · đã bán ${Number(sold).toLocaleString('vi-VN')}${shop ? ' · ' + String(shop).replace(/</g, '&lt;') : ''}` +
        `${isAd ? ' · <span style="color:#b45309">Ad</span>' : ''}</div></div>`;
      listEl.appendChild(el);
    }
  } catch (e) {
    setStatus('Lỗi: ' + e, 'err');
  } finally {
    $('go').disabled = false;
  }
}

let lastSample = null;
let lastItems = null;

// Giá đơn vị ×100000 → text đọc được.
function scaledPrice(v) {
  return typeof v === 'number' && v > 0 ? v / PRICE_SCALE : null;
}

// Trích itemid/shopid/catid từ một item search (format 2026).
function idsOf(it) {
  const idata = it.item_data || {};
  return {
    itemid: it.itemid || idata.itemid,
    shopid: it.shopid || idata.shopid,
    catid: idata.catid || (Array.isArray((idata.global_cat || {}).catid) ? idata.global_cat.catid[0] : undefined),
  };
}

// Tìm giá thấp nhất trong danh sách sản phẩm tương tự (thử nhiều đường vì chưa chắc cấu trúc).
function cheapestFrom(list, region) {
  let min = null;
  for (const it of list || []) {
    const idata = it.item_data || {};
    const asset = it.item_card_displayed_asset || {};
    const dp = idata.item_card_display_price || asset.display_price || {};
    const p = scaledPrice(dp.price ?? (it.item_basic || {}).price);
    if (p != null && (min == null || p < min)) min = p;
  }
  return min;
}

async function testFindSimilar() {
  if (!lastItems || !lastItems.length) return;
  const region = $('region').value;
  const { itemid, shopid, catid } = idsOf(lastItems[0]);
  if (!itemid || !shopid) { setStatus('SP #1 thiếu itemid/shopid.', 'err'); return; }

  setStatus(`Đang tìm SP tương tự cho SP #1 (item ${itemid})…`);
  const body = JSON.stringify({
    offset: 0, limit: 50,
    section: 'find_similar_product_pd_sec', bundle: 'find_similar_product_pd',
    itemid, shopid, catid, item_card: 2,
  });
  const res = await new Promise((resolve) => chrome.runtime.sendMessage({
    type: 'RS_FETCH',
    requests: [{
      url: 'https://shopee.vn/api/v4/recommend/recommend_post',
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-source': 'rweb', 'x-requested-with': 'XMLHttpRequest' },
      body, tag: 'similar',
    }],
  }, (r) => resolve(r && r.responses && r.responses[0])));

  if (!res) { setStatus('Không có phản hồi từ extension.', 'err'); return; }
  if (res.status !== 200) {
    setStatus(`find-similar HTTP ${res.status} — có thể cần chữ ký/điều hướng trang. ${String(res.text).slice(0, 80)}`, 'err');
    return;
  }
  let data;
  try { data = JSON.parse(res.text); } catch { setStatus('Phản hồi không phải JSON.', 'err'); return; }

  // Thử tìm mảng sản phẩm ở vài vị trí hay gặp.
  const d = data.data || data;
  let list = d.items || d.units || (Array.isArray(d.sections) ? (d.sections[0] || {}).data?.item || [] : []) || [];
  if (!Array.isArray(list)) list = [];
  const cheapest = cheapestFrom(list, region);

  // Lộ cấu trúc để map chính xác.
  const dbg = document.getElementById('debug');
  dbg.style.display = 'block';
  dbg.textContent =
    'recommend_post OK. top keys: ' + JSON.stringify(Object.keys(data)) + '\n' +
    'data keys: ' + JSON.stringify(Object.keys(d)).slice(0, 400) + '\n' +
    'tìm thấy ' + list.length + ' SP tương tự' + (cheapest != null ? ', rẻ nhất ≈ ' + fmtPrice(cheapest, CURRENCY[region]) : '');
  lastSample = data;
  document.getElementById('copy').style.display = 'block';
  setStatus('find-similar HTTP 200 ✅ — xem debug; bấm Copy JSON gửi dev để map chuẩn.', 'ok');
}

$('go').addEventListener('click', run);
$('kw').addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
$('similar').addEventListener('click', testFindSimilar);
$('openResults').addEventListener('click', () => {
  const kw = encodeURIComponent($('kw').value.trim());
  chrome.tabs.create({ url: chrome.runtime.getURL('results.html') + (kw ? `?kw=${kw}` : '') });
});
$('copy').addEventListener('click', async () => {
  if (!lastSample) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(lastSample, null, 2));
    setStatus('Đã copy JSON mẫu vào clipboard — dán cho dev.', 'ok');
  } catch (e) {
    setStatus('Copy lỗi: ' + e, 'err');
  }
});
