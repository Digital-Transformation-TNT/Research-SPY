/*
 * Service worker — điều phối fetch, nhưng KHÔNG tự gọi mạng.
 *
 * Bài học đo được: fetch thẳng từ service worker là CROSS-ORIGIN (chrome-extension:// →
 * shopee.vn) nên Shopee trả 403 dù đã đăng nhập — request không đến từ trang shopee.vn.
 * Cách đúng: chạy fetch NGAY TRONG tab shopee.vn qua executeScript(world:'MAIN'). Khi ấy
 * request là same-origin, mang theo cookie + ngữ cảnh trang y như chính Shopee tự gọi.
 *
 * Nếu chưa có tab của sàn, tự mở một tab nền (cookie theo domain nên vẫn đăng nhập sẵn).
 */

const VERSION = '0.3.0';

const SHOPEE_DOMAINS = ['shopee.vn', 'shopee.co.th', 'shopee.ph', 'shopee.com.my', 'shopee.co.id', 'shopee.sg', 'shopee.tw', 'shopee.com.br', 'shopee.com.mx', 'shopee.com.co', 'shopee.cl'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function hostOf(url) {
  try { return new URL(url).host; } catch { return null; }
}

// Đăng ký hook document_start (MAIN world) cho trang find_similar — để nó bọc fetch TRƯỚC khi
// trang gọi recommend_post. Đăng ký một lần; gọi lại an toàn.
async function ensureHook() {
  try {
    const existing = await chrome.scripting.getRegisteredContentScripts({ ids: ['rs-similar-hook'] });
    if (existing.length) return;
    await chrome.scripting.registerContentScripts([{
      id: 'rs-similar-hook',
      matches: SHOPEE_DOMAINS.map((d) => `https://${d}/find_similar_products*`),
      js: ['similar-hook.js'],
      runAt: 'document_start',
      world: 'MAIN',
    }]);
  } catch (e) { /* đã đăng ký hoặc lỗi nhẹ — bỏ qua */ }
}
ensureHook();

// Đăng ký hook CHUNG (page-hook.js) cho Taobao/Tmall/Temu — chộp response search mà chính trang tự gọi
// (ta không tự ký được mtop x5sec / anti-content của họ). Cài document_start world MAIN. Gọi lại an toàn.
async function ensurePageHook() {
  try {
    const existing = await chrome.scripting.getRegisteredContentScripts({ ids: ['rs-page-hook'] });
    if (existing.length) return;
    await chrome.scripting.registerContentScripts([{
      id: 'rs-page-hook',
      matches: ['https://*.taobao.com/*', 'https://*.tmall.com/*', 'https://*.temu.com/*'],
      js: ['page-hook.js'],
      runAt: 'document_start',
      world: 'MAIN',
    }]);
  } catch (e) { /* đã đăng ký hoặc lỗi nhẹ — bỏ qua */ }
}
ensurePageHook();

// Chạy TRONG trang find_similar: trả response recommend_post mà hook chộp được, và một fallback
// đọc giá thấp nhất từ DOM (phòng khi hook lỡ nhịp). Giá DOM là VND thật; giá trong JSON ×100000.
function scrapeSimilar() {
  const captured = window.__rsCaptured || null;
  let domMin = null;
  try {
    // textContent (không cần layout — tab nền không paint nên innerText có thể rỗng).
    const text = document.body ? document.body.textContent : '';
    const re = /₫\s?([\d.]+)/g;
    let m; const vals = [];
    while ((m = re.exec(text))) { const n = Number(m[1].replace(/\./g, '')); if (n >= 1000) vals.push(n); }
    if (vals.length) domMin = Math.min(...vals);
  } catch (e) {}
  return { captured, domMin };
}

// Mở tab nền tới trang find_similar, để JS Shopee tự gọi (đã ký) recommend_post, chộp response
// qua hook. Trả {text, domMin}: ưu tiên text (JSON đầy đủ), fallback domMin (giá VND từ DOM).
async function findSimilar(url) {
  await ensureHook();
  const tab = await chrome.tabs.create({ url, active: false });
  try {
    await waitForComplete(tab.id, 12000);
    const deadline = Date.now() + 15000;
    let domMin = null;
    while (Date.now() < deadline) {
      await sleep(700);
      try {
        const out = await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: 'MAIN', func: scrapeSimilar });
        const r = out && out[0] && out[0].result;
        if (r) {
          if (r.captured) return { text: r.captured, domMin: null };
          if (typeof r.domMin === 'number') domMin = r.domMin;
        }
      } catch (e) { /* trang chưa sẵn sàng */ }
    }
    return { text: '', domMin };
  } finally {
    try { await chrome.tabs.remove(tab.id); } catch (e) {}
  }
}

async function findTab(host) {
  const tabs = await chrome.tabs.query({ url: `https://${host}/*` });
  return tabs.find((t) => t.id != null) || null;
}

function waitForComplete(tabId, timeoutMs = 12000) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, timeoutMs);
    function listener(id, info) {
      if (id === tabId && info.status === 'complete') {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function ensureTab(host) {
  const existing = await findTab(host);
  if (existing) return existing;
  const tab = await chrome.tabs.create({ url: `https://${host}/`, active: false });
  await waitForComplete(tab.id);
  return tab;
}

// Chạy trong context TRANG (MAIN world) — đây là chỗ fetch trở thành same-origin.
async function fetchInTab(tabId, requests) {
  const injected = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    args: [requests],
    func: async (reqs) => {
      const out = [];
      for (let i = 0; i < reqs.length; i++) {
        const r = reqs[i];
        if (i > 0) await new Promise((res) => setTimeout(res, 400 + Math.floor(Math.random() * 500)));
        try {
          const resp = await fetch(r.url, {
            method: r.method || 'GET',
            headers: r.headers || {},
            body: r.body || undefined,
            credentials: 'include',
          });
          out.push({ tag: r.tag ?? null, status: resp.status, text: await resp.text() });
        } catch (e) {
          out.push({ tag: r.tag ?? null, status: 0, text: String(e) });
        }
      }
      return out;
    },
  });
  return (injected && injected[0] && injected[0].result) || [];
}

async function handleFetch(requests) {
  // Nhóm theo host để chạy trong đúng tab của từng sàn.
  const byHost = new Map();
  for (const r of requests || []) {
    const host = hostOf(r.url);
    if (!host) continue;
    if (!byHost.has(host)) byHost.set(host, []);
    byHost.get(host).push(r);
  }

  const all = [];
  for (const [host, reqs] of byHost) {
    let tab;
    try {
      tab = await ensureTab(host);
    } catch (e) {
      for (const r of reqs) all.push({ tag: r.tag ?? null, status: 0, text: `NO_TAB:${host}` });
      continue;
    }
    if (!tab || tab.id == null) {
      for (const r of reqs) all.push({ tag: r.tag ?? null, status: 0, text: `NO_TAB:${host}` });
      continue;
    }
    try {
      all.push(...(await fetchInTab(tab.id, reqs)));
    } catch (e) {
      for (const r of reqs) all.push({ tag: r.tag ?? null, status: 0, text: `INJECT_FAIL:${String(e)}` });
    }
  }
  return all;
}

// NHANH: mở MỘT tab find_similar (seed) để nạp bộ ký của Shopee, rồi từ chính tab đó gọi
// recommend_post cho NHIỀU sản phẩm. Nếu trang tự ký fetch → lấy giá vốn cả loạt trong 1 tab.
// Trả map itemid -> {status, text}.
async function costBatch(seedUrl, products) {
  await ensureHook();
  const tab = await chrome.tabs.create({ url: seedUrl, active: false });
  try {
    await waitForComplete(tab.id, 12000);
    // Chờ trang gọi xong recommend_post đầu tiên (bằng chứng bộ ký đã sẵn), tối đa ~10s.
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      await sleep(700);
      try {
        const out = await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: 'MAIN', func: () => !!window.__rsCaptured });
        if (out && out[0] && out[0].result) break;
      } catch (e) {}
    }
    // Bắn recommend_post cho tất cả sản phẩm từ ngay trong tab (dùng fetch của trang → được ký).
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: 'MAIN', args: [products],
      func: async (items) => {
        const map = {};
        for (const p of items) {
          try {
            const body = JSON.stringify({
              offset: 0, limit: 30, section: 'find_similar_product_pd_sec', bundle: 'find_similar_product_pd',
              itemid: Number(p.itemid), shopid: Number(p.shopid), catid: Number(p.catid), item_card: 2,
            });
            const r = await fetch('/api/v4/recommend/recommend_post', {
              method: 'POST', headers: { 'content-type': 'application/json' }, body, credentials: 'include',
            });
            map[p.itemid] = { status: r.status, text: r.status === 200 ? await r.text() : '' };
          } catch (e) { map[p.itemid] = { status: 0, text: String(e) }; }
          await new Promise((z) => setTimeout(z, 200));
        }
        return map;
      },
    });
    return (out && out[0] && out[0].result) || {};
  } finally {
    try { await chrome.tabs.remove(tab.id); } catch (e) {}
  }
}

// Amazon: SW fetch trần bị captcha. Cách chắc: điều hướng MỘT tab nền riêng tới trang search
// (Amazon render SSR → tab load như user thật), rồi đọc sản phẩm từ DOM.
let amazonTabId = null;
async function amazonTab() {
  if (amazonTabId != null) {
    try { const t = await chrome.tabs.get(amazonTabId); if (t) return t; } catch (e) { amazonTabId = null; }
  }
  const t = await chrome.tabs.create({ url: 'about:blank', active: false });
  amazonTabId = t.id;
  return t;
}
async function amazonSearch(domain, url) {
  try {
    const tab = await amazonTab();
    await chrome.tabs.update(tab.id, { url });
    await waitForComplete(tab.id, 15000);
    await sleep(1000); // để kết quả render
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const body = document.body ? document.body.textContent.slice(0, 4000) : '';
        const captcha = /Enter the characters|not a robot|Type the characters|Sorry, we just need/i.test(body);
        const items = [];
        const seen = new Set();
        // Đọc số tiền theo mọi locale: "$1,234.56" · "1.299,00 €" · "￥1,299". Xác định dấu thập
        // phân là dấu (. hoặc ,) đứng trước 1–2 chữ số cuối; phần còn lại là dấu phân cách nghìn.
        const money = (s) => {
          const m = s && s.match(/[\d.,]+/);
          if (!m) return null;
          let t = m[0];
          const dec = t.match(/[.,](\d{1,2})$/);
          t = dec ? t.slice(0, -dec[0].length).replace(/[.,]/g, '') + '.' + dec[1] : t.replace(/[.,]/g, '');
          const n = parseFloat(t);
          return isFinite(n) && n > 0 ? n : null;
        };
        // Giá hiện tại: ưu tiên .a-offscreen (đủ định dạng), fallback .a-price-whole+fraction, rồi
        // bất kỳ .a-offscreen nào có số — để dòng không buy-box vẫn ra giá thay vì "—".
        const priceOf = (el) => {
          const off = el.querySelector('.a-price:not(.a-text-price) .a-offscreen') || el.querySelector('.a-price .a-offscreen');
          let n = off && money(off.textContent);
          if (n) return n;
          const whole = el.querySelector('.a-price-whole');
          if (whole) {
            const frac = el.querySelector('.a-price-fraction');
            n = money(whole.textContent + (frac ? '.' + frac.textContent : ''));
            if (n) return n;
          }
          for (const o of el.querySelectorAll('.a-offscreen')) { n = money(o.textContent); if (n) return n; }
          return null;
        };
        const els = document.querySelectorAll('div[data-asin][data-component-type="s-search-result"], div.s-result-item[data-asin]');
        for (const el of els) {
          const asin = el.getAttribute('data-asin');
          if (!asin || seen.has(asin)) continue;
          const t = el.querySelector('h2 span') || el.querySelector('h2 a') || el.querySelector('h2');
          const name = t ? t.textContent.trim() : '';
          if (!name) continue;
          seen.add(asin);
          const price = priceOf(el);
          const se = el.querySelector('.a-price.a-text-price .a-offscreen');
          const strike = se ? money(se.textContent) : null;
          const im = el.querySelector('img.s-image');
          const image = im ? im.getAttribute('src') : '';
          const re = el.querySelector('.a-icon-alt');
          const rating = re ? (parseFloat((re.textContent.match(/([\d.]+)/) || [])[1]) || null) : null;
          // Số review ĐẦY ĐỦ nằm ở container ratings-count → aria-label của <a> (vd "44,268 ratings").
          // Strip mọi ký tự không phải số → chạy cho mọi region (US "44,268", IT "1.257 recensioni"…).
          let ratingCount = null;
          const rcComp = el.querySelector('[data-csa-c-content-id="alf-customer-ratings-count-component"]');
          if (rcComp) {
            const a = rcComp.querySelector('a[aria-label]');
            let n = parseInt(((a && a.getAttribute('aria-label')) || '').replace(/[^0-9]/g, ''));
            if (!n) n = parseInt((rcComp.textContent || '').replace(/[^0-9]/g, ''));
            if (n) ratingCount = n;
          }
          if (ratingCount == null) {
            const a2 = el.querySelector('a.s-underline-text[aria-label]');
            if (a2) { const n = parseInt((a2.getAttribute('aria-label') || '').replace(/[^0-9]/g, '')); if (n) ratingCount = n; }
          }
          if (ratingCount == null) {
            const und = el.querySelector('a.s-underline-text, .s-underline-text');
            if (und) { const n = parseInt((und.textContent || '').replace(/[^0-9]/g, '')); if (n) ratingCount = n; }
          }
          // Cầu thật của Amazon: "X+ bought in past month" (1K+ → 1000).
          let monthly = null;
          const bm = (el.textContent || '').match(/([\d.,]+)\s*([KkMm])?\+?\s*bought in past month/i);
          if (bm) { let n = parseFloat(bm[1].replace(/,/g, '')); const u = (bm[2] || '').toLowerCase(); if (u === 'k') n *= 1000; else if (u === 'm') n *= 1e6; monthly = Math.round(n) || null; }
          const isAd = el.getAttribute('data-component-type') === 'sp-sponsored-result' || !!el.querySelector('.puis-sponsored-label-text');
          items.push({ asin, name, price, strike, image, rating, ratingCount, monthly, isAd });
        }
        return { captcha, items };
      },
    });
    const r = (out && out[0] && out[0].result) || { captcha: false, items: [] };
    return { items: r.items, blocked: r.captcha && !r.items.length };
  } catch (e) {
    return { items: [], blocked: false, error: String(e) };
  }
}

// 1688 (giá sỉ Trung) — gọi API nội bộ mtop JSON (h5api.m.1688.com) NGAY TRONG tab world:MAIN.
// Trang React s.1688.com/www.1688.com đá về login.taobao.com khi phiên "lạnh"; nhưng endpoint mtop
// trả JSON sản phẩm KỂ CẢ ẩn danh (không cần đăng nhập). Chữ ký = md5(token&t&appKey&data), với
// token = cookie _m_h5_tk (đọc được same-site ở origin h5api.m.1688.com). Không region.
let ali1688TabId = null;
async function ali1688Tab() {
  if (ali1688TabId != null) {
    try { const t = await chrome.tabs.get(ali1688TabId); if (t) return t; } catch (e) { ali1688TabId = null; }
  }
  const t = await chrome.tabs.create({ url: 'about:blank', active: false });
  ali1688TabId = t.id;
  return t;
}
async function search1688(keyword, count) {
  try {
    const tab = await ali1688Tab();
    // h5api.m.1688.com KHÔNG redirect login (khác www/s.1688.com) và là nơi cookie _m_h5_tk same-origin.
    await chrome.tabs.update(tab.id, { url: 'https://h5api.m.1688.com/h5/mtop.relationrecommend.wirelessrecommend.recommend/2.0/' });
    await waitForComplete(tab.id, 12000);
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      args: [keyword, count || 20],
      func: async (keyword, count) => {
        // md5 thuần JS (mtop ký sign = md5(token&t&appKey&data)).
        function md5(s){function L(k,d){return(k<<d)|(k>>>(32-d))}function K(G,k){var I,d,F,H,x;F=(G&2147483648);H=(k&2147483648);I=(G&1073741824);d=(k&1073741824);x=(G&1073741823)+(k&1073741823);if(I&d){return(x^2147483648^F^H)}if(I|d){if(x&1073741824){return(x^3221225472^F^H)}else{return(x^1073741824^F^H)}}else{return(x^F^H)}}function r(d,F,k){return(d&F)|((~d)&k)}function q(d,F,k){return(d&k)|(F&(~k))}function p(d,F,k){return(d^F^k)}function n(d,F,k){return(F^(d|(~k)))}function u(G,F,aa,Z,k,H,I){G=K(G,K(K(r(F,aa,Z),k),I));return K(L(G,H),F)}function f(G,F,aa,Z,k,H,I){G=K(G,K(K(q(F,aa,Z),k),I));return K(L(G,H),F)}function D(G,F,aa,Z,k,H,I){G=K(G,K(K(p(F,aa,Z),k),I));return K(L(G,H),F)}function t(G,F,aa,Z,k,H,I){G=K(G,K(K(n(F,aa,Z),k),I));return K(L(G,H),F)}function e(G){var Z;var F=G.length;var x=F+8;var k=(x-(x%64))/64;var I=(k+1)*16;var aa=Array(I-1);var d=0;var H=0;while(H<F){Z=(H-(H%4))/4;d=(H%4)*8;aa[Z]=(aa[Z]|(G.charCodeAt(H)<<d));H++}Z=(H-(H%4))/4;d=(H%4)*8;aa[Z]=aa[Z]|(128<<d);aa[I-2]=F<<3;aa[I-1]=F>>>29;return aa}function B(x){var k="",F="",G,d;for(d=0;d<=3;d++){G=(x>>>(d*8))&255;F="0"+G.toString(16);k=k+F.substr(F.length-2,2)}return k}function J(k){k=k.replace(/\r\n/g,"\n");var d="";for(var F=0;F<k.length;F++){var x=k.charCodeAt(F);if(x<128){d+=String.fromCharCode(x)}else{if((x>127)&&(x<2048)){d+=String.fromCharCode((x>>6)|192);d+=String.fromCharCode((x&63)|128)}else{d+=String.fromCharCode((x>>12)|224);d+=String.fromCharCode(((x>>6)&63)|128);d+=String.fromCharCode((x&63)|128)}}}return d}var C=[];var P,h,E,v,g,Y,X,W,V;var S=7,Q=12,N=17,M=22;var A=5,z=9,y=14,w=20;var o=4,m=11,l=16,j=23;var U=6,T=10,R=15,O=21;s=J(s);C=e(s);Y=1732584193;X=4023233417;W=2562383102;V=271733878;for(P=0;P<C.length;P+=16){h=Y;E=X;v=W;g=V;Y=u(Y,X,W,V,C[P+0],S,3614090360);V=u(V,Y,X,W,C[P+1],Q,3905402710);W=u(W,V,Y,X,C[P+2],N,606105819);X=u(X,W,V,Y,C[P+3],M,3250441966);Y=u(Y,X,W,V,C[P+4],S,4118548399);V=u(V,Y,X,W,C[P+5],Q,1200080426);W=u(W,V,Y,X,C[P+6],N,2821735955);X=u(X,W,V,Y,C[P+7],M,4249261313);Y=u(Y,X,W,V,C[P+8],S,1770035416);V=u(V,Y,X,W,C[P+9],Q,2336552879);W=u(W,V,Y,X,C[P+10],N,4294925233);X=u(X,W,V,Y,C[P+11],M,2304563134);Y=u(Y,X,W,V,C[P+12],S,1804603682);V=u(V,Y,X,W,C[P+13],Q,4254626195);W=u(W,V,Y,X,C[P+14],N,2792965006);X=u(X,W,V,Y,C[P+15],M,1236535329);Y=f(Y,X,W,V,C[P+1],A,4129170786);V=f(V,Y,X,W,C[P+6],z,3225465664);W=f(W,V,Y,X,C[P+11],y,643717713);X=f(X,W,V,Y,C[P+0],w,3921069994);Y=f(Y,X,W,V,C[P+5],A,3593408605);V=f(V,Y,X,W,C[P+10],z,38016083);W=f(W,V,Y,X,C[P+15],y,3634488961);X=f(X,W,V,Y,C[P+4],w,3889429448);Y=f(Y,X,W,V,C[P+9],A,568446438);V=f(V,Y,X,W,C[P+14],z,3275163606);W=f(W,V,Y,X,C[P+3],y,4107603335);X=f(X,W,V,Y,C[P+8],w,1163531501);Y=f(Y,X,W,V,C[P+13],A,2850285829);V=f(V,Y,X,W,C[P+2],z,4243563512);W=f(W,V,Y,X,C[P+7],y,1735328473);X=f(X,W,V,Y,C[P+12],w,2368359562);Y=D(Y,X,W,V,C[P+5],o,4294588738);V=D(V,Y,X,W,C[P+8],m,2272392833);W=D(W,V,Y,X,C[P+11],l,1839030562);X=D(X,W,V,Y,C[P+14],j,4259657740);Y=D(Y,X,W,V,C[P+1],o,2763975236);V=D(V,Y,X,W,C[P+4],m,1272893353);W=D(W,V,Y,X,C[P+7],l,4139469664);X=D(X,W,V,Y,C[P+10],j,3200236656);Y=D(Y,X,W,V,C[P+13],o,681279174);V=D(V,Y,X,W,C[P+0],m,3936430074);W=D(W,V,Y,X,C[P+3],l,3572445317);X=D(X,W,V,Y,C[P+6],j,76029189);Y=D(Y,X,W,V,C[P+9],o,3654602809);V=D(V,Y,X,W,C[P+12],m,3873151461);W=D(W,V,Y,X,C[P+15],l,530742520);X=D(X,W,V,Y,C[P+2],j,3299628645);Y=t(Y,X,W,V,C[P+0],U,4096336452);V=t(V,Y,X,W,C[P+7],T,1126891415);W=t(W,V,Y,X,C[P+14],R,2878612391);X=t(X,W,V,Y,C[P+5],O,4237533241);Y=t(Y,X,W,V,C[P+12],U,1700485571);V=t(V,Y,X,W,C[P+3],T,2399980690);W=t(W,V,Y,X,C[P+10],R,4293915773);X=t(X,W,V,Y,C[P+1],O,2240044497);Y=t(Y,X,W,V,C[P+8],U,1873313359);V=t(V,Y,X,W,C[P+15],T,4264355552);W=t(W,V,Y,X,C[P+6],R,2734768916);X=t(X,W,V,Y,C[P+13],O,1309151649);Y=t(Y,X,W,V,C[P+4],U,4149444226);V=t(V,Y,X,W,C[P+11],T,3174756917);W=t(W,V,Y,X,C[P+2],R,718787259);X=t(X,W,V,Y,C[P+9],O,3951481745);Y=K(Y,h);X=K(X,E);W=K(W,v);V=K(V,g)}return(B(Y)+B(X)+B(W)+B(V)).toLowerCase()}
        const appKey = '12574478';
        const api = 'mtop.relationrecommend.WirelessRecommend.recommend';
        const base = 'https://h5api.m.1688.com/h5/mtop.relationrecommend.wirelessrecommend.recommend/2.0/';
        const pageSize = Math.min(60, Math.max(10, count || 20));
        // sortType 'va_rmdarkgmv30rt' = xếp theo GMV 30 ngày ↓ — vừa nổi hàng bán chạy, vừa LỘ số bán
        // (sort 'booked' trả bookedCount toàn "0"; sort này mới có bookedCount thật + afterPrice "已售…件").
        const params = JSON.stringify({ keywords: keyword, beginPage: 1, pageSize, method: 'getOfferList', verticalProductFlag: 'pcmarket', searchScene: 'pcOfferSearch', charset: 'GBK', sortType: 'va_rmdarkgmv30rt' });
        const data = JSON.stringify({ appId: '32517', params });
        const tok = () => { const m = document.cookie.match(/_m_h5_tk=([^;_]+)/); return m ? m[1] : ''; };
        const mkurl = () => { const ts = Date.now().toString(); const sign = md5(tok() + '&' + ts + '&' + appKey + '&' + data); return base + '?jsv=2.5.1&appKey=' + appKey + '&t=' + ts + '&sign=' + sign + '&api=' + api + '&v=2.0&type=originaljson&dataType=json&data=' + encodeURIComponent(data); };
        // Thử tối đa 3 lần: lần đầu có thể FAIL_SYS_TOKEN (token rỗng/hết hạn) nhưng server SET LẠI cookie
        // _m_h5_tk → lần sau ký đúng. Đây là nhịp chuẩn của mtop, chống lỗi token chập chờn giữa các lần search.
        let j = null, lastRet = 'no-response', lastParsed = null;
        for (let attempt = 0; attempt < 3; attempt++) {
          let txt = '';
          try { txt = await (await fetch(mkurl(), { credentials: 'include' })).text(); }
          catch (e) { return { items: [], blocked: false, error: 'fetch: ' + e }; }
          try { lastParsed = JSON.parse(txt); } catch (e) { lastParsed = null; }
          lastRet = (lastParsed && lastParsed.ret && lastParsed.ret[0]) || 'no-json';
          if (/SUCCESS/i.test(lastRet)) { j = lastParsed; break; }
          await new Promise((res) => setTimeout(res, 400)); // cookie vừa được set/refresh → thử lại
        }
        if (!j) {
          const spam = /ILLEGAL|RGV587|SPAM|FLOW|punish|限流/i.test(lastRet);
          const validate = /VALIDATE/i.test(lastRet); // FAIL_SYS_USER_VALIDATE = bắt kéo slider (Baxia)
          return { items: [], blocked: spam || validate, error: lastRet, verifyUrl: (lastParsed && lastParsed.data && lastParsed.data.url) || '' };
        }
        // Dò link video trong item (chạy IN-PAGE nên không dùng được rsFindVideoUrl của background).
        function _vid(o, dp) { dp = dp || 0; if (o == null || dp > 5) return ''; if (typeof o === 'string') { return /^(https?:)?\/\//.test(o) && /\.mp4(\?|$)|\.m3u8|cloud\.video|\/video\//i.test(o) ? (o.indexOf('//') === 0 ? 'https:' + o : o) : ''; } if (Array.isArray(o)) { for (var i = 0; i < o.length; i++) { var v = _vid(o[i], dp + 1); if (v) return v; } return ''; } if (typeof o === 'object') { for (var k in o) { var vv = _vid(o[k], dp + 1); if (vv) return vv; } } return ''; }
        const raw = ((((j.data || {}).data || {}).OFFER || {}).items) || [];
        const items = [];
        for (const it of raw) {
          const d = it && it.data;
          if (!d || !d.offerId) continue;
          const price = parseFloat(String((d.priceInfo && d.priceInfo.price) || '').replace(/[^0-9.]/g, '')) || null;
          // Số bán: bookedCount = thành giao ~30 ngày (BÁN/THÁNG); afterPrice.text "已售10万+件" = tổng đã bán (TỔNG BÁN).
          const monthly = parseInt(String(d.bookedCount || '').replace(/[^0-9]/g, ''), 10) || null; // bán ~30 ngày (chính xác)
          // afterPrice.text: "已售X+件" = đã bán của CHÍNH shop này (tích luỹ, làm tròn xuống 100+/300+/…).
          // "全网X+件" = toàn sàn cho mẫu đó — KHÔNG phải shop này → BỎ, tránh thổi phồng tổng bán.
          let sold = null;
          const apt = String((d.afterPrice && d.afterPrice.text) || '');
          if (/已售/.test(apt)) {
            const sm = apt.match(/([\d.]+)\s*(万)?/);
            if (sm) { sold = parseFloat(sm[1]) || null; if (sold && sm[2] === '万') sold = Math.round(sold * 10000); } // "1.9万+" = 19000
          }
          // Chống "ảo": tổng (làm tròn xuống) không thể NHỎ HƠN bán ~30 ngày → lệch thì bỏ tổng, giữ số tháng chính xác.
          if (sold != null && monthly != null && sold < monthly) sold = null;
          // 1688 không có rating theo sản phẩm → dùng điểm dịch vụ shop tổng hợp (0-5), như rating shop Etsy.
          const ts = (d.shopAddition && d.shopAddition.tradeService) || {};
          const rating = parseFloat(ts.compositeNewScore || ts.goodsScore || '') || null;
          // 回头率 (tỉ lệ khách quay lại) — tín hiệu cầu phụ. "37%" -> 37.
          const rrText = (d.afterTags && /return_rate/i.test(d.afterTags.matKey || '') && d.afterTags.text) || '';
          const repurchase = parseFloat(String(rrText).replace(/[^0-9.]/g, '')) || null;
          items.push({
            id: String(d.offerId),
            name: (d.title || '').replace(/<[^>]+>/g, '').trim(), // bỏ thẻ <font> tô đậm từ khoá
            price,
            image: d.offerPicUrl || '',
            videoUrl: _vid(it), // video sản phẩm nếu có trong response search

            monthly,                                          // thành giao ~30 ngày
            sold,                                             // tổng đã bán (từ "已售…件")
            shop: (d.shop && d.shop.text) || d.loginId || '', // tên công ty đầy đủ nếu có
            rating,                                           // điểm shop 0-5
            repurchase,                                       // % khách quay lại
            similar: d.sameDesignUrl || '',                   // link tìm sản phẩm CÙNG MẪU
          });
        }
        return { items, blocked: false };
      },
    });
    const r = (out && out[0] && out[0].result) || { items: [], blocked: false };
    // 1688 bắt xác minh (kéo slider) — mở trang xác minh cho user giải 1 lần → set cookie x5sec → lần sau qua.
    if (r.error && /VALIDATE/i.test(r.error)) {
      let vurl = r.verifyUrl || 'https://s.1688.com/';
      if (vurl.indexOf('//') === 0) vurl = 'https:' + vurl;
      try { await chrome.tabs.create({ url: vurl, active: true }); } catch (e) {}
      return { items: [], blocked: true, error: 'cần xác minh — đã mở tab 1688, kéo slider xong rồi bấm Research lại' };
    }
    return r;
  } catch (e) {
    return { items: [], blocked: false, error: String(e) };
  }
}

// ============================================================================
// TAOBAO + TEMU (Cách A "ký sinh"): điều hướng tab đã login tới URL search → trang TỰ gọi API đã ký
// (mtop x5sec / anti-content) → page-hook.js chộp response → parse phòng thủ. KHÔNG tự ký request.
// EXPERIMENTAL: cần tab đã đăng nhập; Baxia/Temu có thể chặn → báo notice để user xử lý.
// ============================================================================

let taobaoTabId = null;
async function taobaoTab() {
  if (taobaoTabId != null) { try { const t = await chrome.tabs.get(taobaoTabId); if (t) return t; } catch (e) { taobaoTabId = null; } }
  const t = await chrome.tabs.create({ url: 'about:blank', active: false });
  taobaoTabId = t.id;
  return t;
}
let temuTabId = null;
async function temuTab() {
  if (temuTabId != null) { try { const t = await chrome.tabs.get(temuTabId); if (t) return t; } catch (e) { temuTabId = null; } }
  const t = await chrome.tabs.create({ url: 'about:blank', active: false });
  temuTabId = t.id;
  return t;
}

// Điều hướng tab tới URL search rồi ĐỢI hook chộp response (trang tự gọi, tự ký). Chạy NGẦM khi trót
// lọt; khi vướng đăng nhập/xác minh (slider) hoặc quá giờ → ĐƯA TAB RA TRƯỚC để user tự xử 1 lần.
// Trả {texts[], blocked, reason}. Không tự giải captcha (không thể & không được phép).
async function navAndCapture(getTab, url, needleRe, loginRe, contentRe, timeoutMs = 22000) {
  const tab = await getTab();
  await chrome.tabs.update(tab.id, { url });
  await focusTab(tab.id); // SPA nặng (Temu/Taobao) chỉ render + bắn XHR khi tab HIỆN TRƯỚC; tab nền bị Chrome tiết chế
  await waitForComplete(tab.id, 16000);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await sleep(700);
    let r = null;
    try {
      const out = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, world: 'MAIN',
        func: () => ({ cap: (window.__rsCap || []).map((c) => ({ url: c.url, text: c.text })), href: location.href, body: (document.body ? document.body.innerText.slice(0, 500) : '') }),
      });
      r = out && out[0] && out[0].result;
    } catch (e) { /* trang chưa sẵn sàng */ }
    if (r) {
      // Chỉ nhận response CÓ SẢN PHẨM (khớp contentRe) — bỏ qua các call phụ như search_suggest bắn trước.
      const hits = (r.cap || []).filter((c) => needleRe.test(c.url) && (!contentRe || contentRe.test(c.text)));
      if (hits.length) return { texts: hits.map((h) => h.text), blocked: false };
      // Đăng nhập hoặc slider (nc/滑块/验证) → không tự qua được, đưa tab ra trước cho user.
      if (loginRe.test(r.href) || /login|登录|sign in/i.test(r.href)) { await focusTab(tab.id); return { texts: [], blocked: true, reason: 'login' }; }
      if (/滑块|请拖动|向右滑|verify|captcha|拖动|nc_wrapper|安全验证/i.test(r.body || '')) { await focusTab(tab.id); return { texts: [], blocked: true, reason: 'verify' }; }
    }
  }
  await focusTab(tab.id); // hết giờ mà chưa bắt được — nhiều khả năng có slider/đăng nhập, đưa tab ra
  return { texts: [], blocked: true, reason: 'timeout' };
}
async function focusTab(tabId) {
  try {
    const t = await chrome.tabs.get(tabId);
    await chrome.tabs.update(tabId, { active: true });
    if (t && t.windowId != null) await chrome.windows.update(t.windowId, { focused: true });
  } catch (e) {}
}

// Dò MẢNG sản phẩm trong JSON bất kỳ: mảng có ≥3 phần tử "trông giống sản phẩm" (theo `looksItem`).
function rsDeepFindArray(root, looksItem) {
  let best = null;
  (function walk(o, depth) {
    if (o == null || depth > 8) return;
    if (Array.isArray(o)) {
      const n = o.length;
      if (n) {
        const hits = o.slice(0, 30).filter((x) => looksItem(x)).length;
        if (hits >= Math.min(3, n) && (!best || n > best.length)) best = o;
      }
      for (let i = 0; i < Math.min(o.length, 30); i++) walk(o[i], depth + 1);
    } else if (typeof o === 'object') {
      for (const k in o) walk(o[k], depth + 1);
    }
  })(root, 0);
  return best || [];
}

// Dò link VIDEO trong item sản phẩm bất kỳ (không cần biết field chính xác từng sàn): duyệt cây,
// bắt string trông như URL video (.mp4/.m3u8, cloud.video, /video/…). Trả '' nếu item không có
// video trong response search — nghĩa là video (nếu có) chỉ nằm ở trang chi tiết, không phải bug.
function rsFindVideoUrl(o, depth) {
  depth = depth || 0;
  if (o == null || depth > 6) return '';
  if (typeof o === 'string') {
    if (/^(https?:)?\/\//.test(o) && /\.mp4(\?|$)|\.m3u8|cloud\.video|\/video\/|video_url|\/vod\//i.test(o)) {
      return o.indexOf('//') === 0 ? 'https:' + o : o;
    }
    return '';
  }
  if (Array.isArray(o)) { for (var i = 0; i < o.length; i++) { var v = rsFindVideoUrl(o[i], depth + 1); if (v) return v; } return ''; }
  if (typeof o === 'object') {
    for (var k in o) { if (/video/i.test(k)) { var vk = rsFindVideoUrl(o[k], depth + 1); if (vk) return vk; } }
    for (var k2 in o) { var v2 = rsFindVideoUrl(o[k2], depth + 1); if (v2) return v2; }
  }
  return '';
}

// Taobao FAST: gọi mtop h5search TRỰC TIẾP trong tab origin h5api.m.taobao.com (không chờ render SPA).
// Kế thừa cookie session + x5sec của user → có thể qua Baxia khi đã đăng nhập (IP nhà). Nhanh như 1688.
async function searchTaobao(keyword, count) {
  try {
    const tab = await taobaoTab();
    await chrome.tabs.update(tab.id, { url: 'https://h5api.m.taobao.com/h5/mtop.taobao.wsearch.h5search/1.0/' });
    await waitForComplete(tab.id, 12000);
    const out = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      args: [keyword, count || 20],
      func: async (keyword, count) => {
        function md5(s){function L(k,d){return(k<<d)|(k>>>(32-d))}function K(G,k){var I,d,F,H,x;F=(G&2147483648);H=(k&2147483648);I=(G&1073741824);d=(k&1073741824);x=(G&1073741823)+(k&1073741823);if(I&d){return(x^2147483648^F^H)}if(I|d){if(x&1073741824){return(x^3221225472^F^H)}else{return(x^1073741824^F^H)}}else{return(x^F^H)}}function r(d,F,k){return(d&F)|((~d)&k)}function q(d,F,k){return(d&k)|(F&(~k))}function p(d,F,k){return(d^F^k)}function n(d,F,k){return(F^(d|(~k)))}function u(G,F,aa,Z,k,H,I){G=K(G,K(K(r(F,aa,Z),k),I));return K(L(G,H),F)}function f(G,F,aa,Z,k,H,I){G=K(G,K(K(q(F,aa,Z),k),I));return K(L(G,H),F)}function D(G,F,aa,Z,k,H,I){G=K(G,K(K(p(F,aa,Z),k),I));return K(L(G,H),F)}function t(G,F,aa,Z,k,H,I){G=K(G,K(K(n(F,aa,Z),k),I));return K(L(G,H),F)}function e(G){var Z;var F=G.length;var x=F+8;var k=(x-(x%64))/64;var I=(k+1)*16;var aa=Array(I-1);var d=0;var H=0;while(H<F){Z=(H-(H%4))/4;d=(H%4)*8;aa[Z]=(aa[Z]|(G.charCodeAt(H)<<d));H++}Z=(H-(H%4))/4;d=(H%4)*8;aa[Z]=aa[Z]|(128<<d);aa[I-2]=F<<3;aa[I-1]=F>>>29;return aa}function B(x){var k="",F="",G,d;for(d=0;d<=3;d++){G=(x>>>(d*8))&255;F="0"+G.toString(16);k=k+F.substr(F.length-2,2)}return k}function J(k){k=k.replace(/\r\n/g,"\n");var d="";for(var F=0;F<k.length;F++){var x=k.charCodeAt(F);if(x<128){d+=String.fromCharCode(x)}else{if((x>127)&&(x<2048)){d+=String.fromCharCode((x>>6)|192);d+=String.fromCharCode((x&63)|128)}else{d+=String.fromCharCode((x>>12)|224);d+=String.fromCharCode(((x>>6)&63)|128);d+=String.fromCharCode((x&63)|128)}}}return d}var C=[];var P,h,E,v,g,Y,X,W,V;var S=7,Q=12,N=17,M=22;var A=5,z=9,y=14,w=20;var o=4,m=11,l=16,j=23;var U=6,T=10,R=15,O=21;s=J(s);C=e(s);Y=1732584193;X=4023233417;W=2562383102;V=271733878;for(P=0;P<C.length;P+=16){h=Y;E=X;v=W;g=V;Y=u(Y,X,W,V,C[P+0],S,3614090360);V=u(V,Y,X,W,C[P+1],Q,3905402710);W=u(W,V,Y,X,C[P+2],N,606105819);X=u(X,W,V,Y,C[P+3],M,3250441966);Y=u(Y,X,W,V,C[P+4],S,4118548399);V=u(V,Y,X,W,C[P+5],Q,1200080426);W=u(W,V,Y,X,C[P+6],N,2821735955);X=u(X,W,V,Y,C[P+7],M,4249261313);Y=u(Y,X,W,V,C[P+8],S,1770035416);V=u(V,Y,X,W,C[P+9],Q,2336552879);W=u(W,V,Y,X,C[P+10],N,4294925233);X=u(X,W,V,Y,C[P+11],M,2304563134);Y=u(Y,X,W,V,C[P+12],S,1804603682);V=u(V,Y,X,W,C[P+13],Q,4254626195);W=u(W,V,Y,X,C[P+14],N,2792965006);X=u(X,W,V,Y,C[P+15],M,1236535329);Y=f(Y,X,W,V,C[P+1],A,4129170786);V=f(V,Y,X,W,C[P+6],z,3225465664);W=f(W,V,Y,X,C[P+11],y,643717713);X=f(X,W,V,Y,C[P+0],w,3921069994);Y=f(Y,X,W,V,C[P+5],A,3593408605);V=f(V,Y,X,W,C[P+10],z,38016083);W=f(W,V,Y,X,C[P+15],y,3634488961);X=f(X,W,V,Y,C[P+4],w,3889429448);Y=f(Y,X,W,V,C[P+9],A,568446438);V=f(V,Y,X,W,C[P+14],z,3275163606);W=f(W,V,Y,X,C[P+3],y,4107603335);X=f(X,W,V,Y,C[P+8],w,1163531501);Y=f(Y,X,W,V,C[P+13],A,2850285829);V=f(V,Y,X,W,C[P+2],z,4243563512);W=f(W,V,Y,X,C[P+7],y,1735328473);X=f(X,W,V,Y,C[P+12],w,2368359562);Y=D(Y,X,W,V,C[P+5],o,4294588738);V=D(V,Y,X,W,C[P+8],m,2272392833);W=D(W,V,Y,X,C[P+11],l,1839030562);X=D(X,W,V,Y,C[P+14],j,4259657740);Y=D(Y,X,W,V,C[P+1],o,2763975236);V=D(V,Y,X,W,C[P+4],m,1272893353);W=D(W,V,Y,X,C[P+7],l,4139469664);X=D(X,W,V,Y,C[P+10],j,3200236656);Y=D(Y,X,W,V,C[P+13],o,681279174);V=D(V,Y,X,W,C[P+0],m,3936430074);W=D(W,V,Y,X,C[P+3],l,3572445317);X=D(X,W,V,Y,C[P+6],j,76029189);Y=D(Y,X,W,V,C[P+9],o,3654602809);V=D(V,Y,X,W,C[P+12],m,3873151461);W=D(W,V,Y,X,C[P+15],l,530742520);X=D(X,W,V,Y,C[P+2],j,3299628645);Y=t(Y,X,W,V,C[P+0],U,4096336452);V=t(V,Y,X,W,C[P+7],T,1126891415);W=t(W,V,Y,X,C[P+14],R,2878612391);X=t(X,W,V,Y,C[P+5],O,4237533241);Y=t(Y,X,W,V,C[P+12],U,1700485571);V=t(V,Y,X,W,C[P+3],T,2399980690);W=t(W,V,Y,X,C[P+10],R,4293915773);X=t(X,W,V,Y,C[P+1],O,2240044497);Y=t(Y,X,W,V,C[P+8],U,1873313359);V=t(V,Y,X,W,C[P+15],T,4264355552);W=t(W,V,Y,X,C[P+6],R,2734768916);X=t(X,W,V,Y,C[P+13],O,1309151649);Y=t(Y,X,W,V,C[P+4],U,4149444226);V=t(V,Y,X,W,C[P+11],T,3174756917);W=t(W,V,Y,X,C[P+2],R,718787259);X=t(X,W,V,Y,C[P+9],O,3951481745);Y=K(Y,h);X=K(X,E);W=K(W,v);V=K(V,g)}return(B(Y)+B(X)+B(W)+B(V)).toLowerCase()}
        const appKey = '12574478', api = 'mtop.taobao.wsearch.h5search', ver = '1.0';
        const base = 'https://h5api.m.taobao.com/h5/' + api + '/' + ver + '/';
        const n = Math.min(40, Math.max(10, count || 20));
        const data = JSON.stringify({ q: keyword, search_action: 'initiative', tab: 'all', page: 1, n: n, sort: '_sale' });
        const tok = () => { const m = document.cookie.match(/_m_h5_tk=([^;_]+)/); return m ? m[1] : ''; };
        const mkurl = () => { const ts = Date.now().toString(); const sign = md5(tok() + '&' + ts + '&' + appKey + '&' + data); return base + '?jsv=2.6.1&appKey=' + appKey + '&t=' + ts + '&sign=' + sign + '&api=' + api + '&v=' + ver + '&type=originaljson&dataType=json&data=' + encodeURIComponent(data); };
        let lastText = '', lastRet = 'no-response', verifyUrl = '';
        for (let a = 0; a < 3; a++) {
          try { lastText = await (await fetch(mkurl(), { credentials: 'include' })).text(); }
          catch (e) { return { text: '', ret: 'fetch:' + e }; }
          let pj = null; try { pj = JSON.parse(lastText); } catch (e) {}
          lastRet = (pj && pj.ret && pj.ret[0]) || 'no-json';
          if (/SUCCESS/i.test(lastRet)) return { text: lastText, ret: lastRet };
          if (pj && pj.data && pj.data.url) verifyUrl = pj.data.url;
          await new Promise((r) => setTimeout(r, 400));
        }
        return { text: lastText, ret: lastRet, verifyUrl: verifyUrl };
      },
    });
    const r = (out && out[0] && out[0].result) || { text: '', ret: 'no-response' };
    if (!/SUCCESS/i.test(r.ret || '')) {
      // Baxia (RGV587_SM) / cần xác minh / chưa đăng nhập → mở trang Taobao cho user kéo slider/login 1 lần.
      if (/VALIDATE|RGV587|SM|哎哟|令牌|FORBIDDEN|ILLEGAL/i.test(r.ret || '')) {
        let vurl = r.verifyUrl || ('https://s.taobao.com/search?q=' + encodeURIComponent(keyword));
        if (vurl.indexOf('//') === 0) vurl = 'https:' + vurl;
        try { await chrome.tabs.create({ url: vurl, active: true }); } catch (e) {}
        return { items: [], blocked: true, error: 'cần đăng nhập/xác minh — đã mở tab Taobao, xong rồi bấm Research lại' };
      }
      return { items: [], blocked: false, error: r.ret };
    }
    const items = parseTaobaoTexts([r.text], count);
    // Chưa map được field → trả raw để dev chỉnh (Taobao h5search cấu trúc chưa xác nhận).
    return { items, blocked: false, raw: items.length ? undefined : (r.text || '').slice(0, 1400) };
  } catch (e) { return { items: [], blocked: false, error: String(e) }; }
}

function parseTaobaoTexts(texts, count) {
  const out = [];
  const looks = (o) => o && typeof o === 'object' && (o.title || o.raw_title || o.subject) && (o.price || o.view_price || o.priceInfo || o.sortPrice);
  for (const text of texts) {
    let j; try { j = JSON.parse(text); } catch (e) { continue; }
    const arr = rsDeepFindArray(j, looks);
    for (const it of arr) {
      const id = String(it.item_id || it.nid || it.itemId || it.id || '');
      if (!id) continue;
      const name = String(it.title || it.raw_title || it.subject || '').replace(/<[^>]+>/g, '').trim();
      const priceRaw = it.price || it.view_price || (it.priceInfo && (it.priceInfo.price || it.priceInfo.priceStr)) || it.sortPrice || '';
      const price = parseFloat(String(priceRaw).replace(/[^0-9.]/g, '')) || null;
      const soldRaw = String(it.realSales || it.view_sales || it.sold || it.payNum || (it.priceInfo && it.priceInfo.saleNum) || '');
      let monthly = parseFloat(soldRaw.replace(/[^0-9.]/g, '')) || null;
      if (monthly && /万/.test(soldRaw)) monthly = Math.round(monthly * 10000);
      let img = it.pic_url || it.picUrl || it.pic || it.image || (it.picInfo && it.picInfo.pic) || '';
      if (img && img.indexOf('//') === 0) img = 'https:' + img;
      const shop = it.nick || it.shopName || (it.shopInfo && it.shopInfo.title) || it.userNick || '';
      out.push({ id, name, price, image: img, monthly, shop, videoUrl: rsFindVideoUrl(it) });
      if (out.length >= count) break;
    }
    if (out.length) break;
  }
  return out;
}

// Temu: mở tab search (foreground) → TỰ CÀI HOOK rồi GÕ từ khoá + Enter vào ô search để trang tự bắn
// /api/poppy/v1/search (đã ký anti-content) → chộp response. Điều hướng URL trần chỉ SSR, không bắn XHR.
async function searchTemu(keyword, count) {
  try {
    const tab = await temuTab();
    await chrome.tabs.update(tab.id, { url: 'https://www.temu.com/search_result.html?search_key=' + encodeURIComponent(keyword) });
    await focusTab(tab.id); // SPA nặng — phải foreground mới chạy
    await waitForComplete(tab.id, 16000);
    await sleep(1500); // để React mount xong ô search

    // Cài hook bắt /poppy/v1/search (có goods) + KÍCH HOẠT tìm kiếm: set value ô input rồi Enter (React-friendly).
    await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: 'MAIN', args: [keyword],
      func: (kw) => {
        if (!window.__rsTemuCap) {
          window.__rsTemuCap = [];
          const hit = (t) => /goods_list|goods_id|goodsList|goodsId/.test(t);
          const of = window.fetch;
          window.fetch = function () {
            const u = typeof arguments[0] === 'string' ? arguments[0] : (arguments[0] && arguments[0].url) || '';
            const p = of.apply(this, arguments);
            if (/poppy\/v1.*search/.test(u)) p.then((r) => { try { r.clone().text().then((t) => { if (hit(t)) window.__rsTemuCap.push(t); }); } catch (e) {} }).catch(() => {});
            return p;
          };
          const X = window.XMLHttpRequest, oo = X.prototype.open, os = X.prototype.send;
          X.prototype.open = function (m, u) { this.__u = u; return oo.apply(this, arguments); };
          X.prototype.send = function () { const self = this; this.addEventListener('load', function () { try { if (/poppy\/v1.*search/.test(self.__u) && hit(self.responseText)) window.__rsTemuCap.push(self.responseText); } catch (e) {} }); return os.apply(this, arguments); };
        }
        // Gõ vào ô search + Enter để trang tự gọi API sản phẩm (dùng native setter cho React).
        try {
          const inp = document.querySelector('input[type="search"]') || document.querySelector('input[role="searchbox"]') || [...document.querySelectorAll('input')].find((e) => /search|tìm/i.test((e.placeholder || '') + (e.getAttribute('aria-label') || '')));
          if (inp) {
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(inp, kw); inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.focus();
            for (const type of ['keydown', 'keypress', 'keyup']) inp.dispatchEvent(new KeyboardEvent(type, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
            const form = inp.closest('form'); if (form) { try { form.requestSubmit ? form.requestSubmit() : form.submit(); } catch (e) {} }
          }
        } catch (e) {}
        return true;
      },
    });

    // Đợi hook chộp được response sản phẩm (do mount hoặc do lần gõ Enter ở trên).
    const deadline = Date.now() + 18000;
    let texts = [];
    while (Date.now() < deadline) {
      await sleep(800);
      let r = null;
      try {
        const out = await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: 'MAIN', func: () => ({ a: window.__rsTemuCap || [], b: (window.__rsCap || []).filter((c) => /poppy\/v1.*search/.test(c.url) && /goods_list|goods_id/.test(c.text)).map((c) => c.text), href: location.href }) });
        r = out && out[0] && out[0].result;
      } catch (e) {}
      if (r) {
        if (/login\.html/.test(r.href)) { await focusTab(tab.id); return { items: [], blocked: true, error: 'chưa đăng nhập — đã mở tab Temu, đăng nhập xong rồi bấm Research lại' }; }
        const got = (r.a || []).concat(r.b || []);
        if (got.length) { texts = got; break; }
      }
    }
    if (!texts.length) { await focusTab(tab.id); return { items: [], blocked: true, error: 'chưa bắt được lưới SP — đã mở tab, gõ search 1 lần trong tab Temu rồi bấm Research lại' }; }
    const items = parseTemuTexts(texts, count);
    return { items, blocked: false, raw: items.length ? undefined : (texts[0] || '').slice(0, 1400) };
  } catch (e) { return { items: [], blocked: false, error: String(e) }; }
}

// Parse giá từ chuỗi hiển thị theo locale của tiền tệ. Tiền KHÔNG có phần lẻ (VND/JPY…) → mọi dấu ./,
// đều là ngăn nghìn → bỏ hết. Tiền CÓ lẻ (USD/EUR…) → dấu ./, CUỐI CÙNG là thập phân, còn lại ngăn nghìn.
function rsParsePrice(str, cur) {
  let s = String(str || '').replace(/[^0-9.,]/g, '');
  if (!s) return null;
  if (/VND|JPY|KRW|IDR|CLP|HUF|TWD|COP/i.test(cur || '')) return parseInt(s.replace(/[.,]/g, ''), 10) || null;
  const lastSep = Math.max(s.lastIndexOf('.'), s.lastIndexOf(','));
  if (lastSep === -1) return parseInt(s, 10) || null;
  const intPart = s.slice(0, lastSep).replace(/[.,]/g, '');
  const decPart = s.slice(lastSep + 1).replace(/[.,]/g, '');
  return parseFloat(intPart + '.' + decPart) || null;
}

function parseTemuTexts(texts, count) {
  const out = [];
  const looks = (o) => o && typeof o === 'object' && o.title && (o.price_info || o.priceInfo);
  for (const text of texts) {
    let j; try { j = JSON.parse(text); } catch (e) { continue; }
    // Đường dẫn thật: result.data.goods_list[]; fallback deep-find nếu Temu đổi cấu trúc.
    let arr = (((j.result || {}).data || {}).goods_list) || ((j.data || {}).goods_list) || null;
    if (!Array.isArray(arr) || !arr.length) arr = rsDeepFindArray(j, looks);
    for (const it of arr) {
      const id = String(it.goods_id || it.goodsId || it.productId || it.id || '');
      if (!id) continue;
      const name = String(it.title || '').trim();
      const pi = it.price_info || it.priceInfo || {};
      // Giá theo TIỀN TỆ: "₫302.510" (VN . = ngăn nghìn) vs "$12.99" (US . = thập phân) → parse khác nhau.
      let price = rsParsePrice(pi.price_str || pi.priceStr, pi.currency);
      if (price == null && typeof pi.price === 'number') price = pi.price;
      let img = it.thumb_url || (it.image && (it.image.url || it.image)) || it.thumbUrl || '';
      if (img && img.indexOf('//') === 0) img = 'https:' + img;
      // sales_num "11K+" = tổng đã bán (Temu không tách theo tháng).
      const soldRaw = String(it.sales_num || it.salesNum || it.sales_tip || '');
      let sold = parseFloat(soldRaw.replace(/[^0-9.]/g, '')) || null;
      if (sold && /K/i.test(soldRaw)) sold = Math.round(sold * 1000);
      else if (sold && /M/i.test(soldRaw)) sold = Math.round(sold * 1000000);
      const cm = it.comment || {};
      const rr = cm.goods_score || cm.goodsScore;
      const rating = rr ? parseFloat(rr) || null : null;
      // Video sản phẩm có sẵn trong response Temu (field `video.video_url`) — rỗng nếu SP không có video.
      let videoUrl = (it.video && (it.video.video_url || it.video.url)) || '';
      if (videoUrl && videoUrl.indexOf('//') === 0) videoUrl = 'https:' + videoUrl;
      out.push({ id, name, price, image: img, sold, rating, currency: pi.currency || '', videoUrl });
      if (out.length >= count) break;
    }
    if (out.length) break;
  }
  return out;
}

// ===== TikTok organic: keyword → list VIDEO (Cách A, auto-scroll + chộp API) =====
// TikTok search bắn API đã ký (X-Bogus/msToken) do JS trang tự sinh — không reimplement được.
// Nên: điều hướng tới /search/video, để page-hook (document_start) chộp response, rồi TỰ CUỘN
// nhanh nhiều lần ép trang bắn tiếp các trang sau (infinite scroll) → gom HẾT, không bắt user cuộn.
// Đây là cách khắc phục "phải kéo mới ra video": tool cuộn thay, và gom mọi trang một lượt.
let tiktokTabId = null;
async function tiktokTab() {
  if (tiktokTabId != null) { try { const t = await chrome.tabs.get(tiktokTabId); if (t) return t; } catch (e) { tiktokTabId = null; } }
  const t = await chrome.tabs.create({ url: 'about:blank', active: false });
  tiktokTabId = t.id;
  return t;
}

// ===== TikTok Creative Center: filter country THẬT (không bám IP user) =====
// Creative Center là công cụ duy nhất của TikTok cho phép query "top ads theo country" — endpoint
// `/api/*?biz_id=cc` gộp query dạng batch. V1 KHÔNG reimplement sign — mở tab thật, để trang tự sinh
// request, hook fetch để capture batch response + scrape DOM cards. Trả cả `raw` (2KB đầu response
// batch) để lần chạy đầu thấy được shape thật và refine parser vòng sau.
let tkccTabId = null;
async function tkccTab() {
  if (tkccTabId != null) { try { const t = await chrome.tabs.get(tkccTabId); if (t) return t; } catch (e) { tkccTabId = null; } }
  const t = await chrome.tabs.create({ url: 'about:blank', active: false });
  tkccTabId = t.id;
  return t;
}

// Endpoint URL Creative Center: query string đã gồm region + period; industry (nếu có) truyền tay
// vào state URL — Creative Center đọc từ URL hash / query khi mount.
function tkccUrl(region, period) {
  const r = String(region || 'VN').toUpperCase();
  const p = String(period || 30);
  return `https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en?region=${encodeURIComponent(r)}&period=${p}&sort_by=for_you`;
}

async function searchTiktokCreative(region, keyword, count) {
  try {
    const tab = await tkccTab();
    const target = Math.min(60, Math.max(12, count || 24));

    // 1. Cài fetch hook TRƯỚC khi navigate (document_start không có cho ads.tiktok.com, nên cài
    //    sau khi navigate lần đầu, rồi reload để capture request batch đầu tiên).
    await chrome.tabs.update(tab.id, { url: tkccUrl(region, 30) });
    await waitForComplete(tab.id, 20000);
    await focusTab(tab.id);
    await sleep(1500);

    await chrome.scripting.executeScript({
      target: { tabId: tab.id }, world: 'MAIN',
      func: () => {
        if (window.__rsCcCap) return;
        window.__rsCcCap = [];
        const of = window.fetch;
        window.fetch = function () {
          const u = typeof arguments[0] === 'string' ? arguments[0] : (arguments[0] && arguments[0].url) || '';
          const p = of.apply(this, arguments);
          if (/biz_id=cc/.test(u)) {
            p.then((r) => { try { r.clone().text().then((t) => window.__rsCcCap.push({ url: u, text: t })); } catch (e) {} }).catch(() => {});
          }
          return p;
        };
      },
    });

    // 2. Reload để hook chộp được batch request LOAD LIST (không phải bootstrap).
    await chrome.tabs.reload(tab.id);
    await waitForComplete(tab.id, 20000);
    await sleep(3500);

    // 3. Gom item: scroll để load-more + poll DOM/hook. Trả raw sample nếu chưa parse được.
    const byId = {};
    const rawSamples = [];
    const deadline = Date.now() + 45000;
    let prev = 0, stagnant = 0;
    let lastBody = '';
    while (Date.now() < deadline) {
      let r = null;
      try {
        const out = await chrome.scripting.executeScript({
          target: { tabId: tab.id }, world: 'MAIN',
          func: () => {
            try {
              const h = document.documentElement.scrollHeight;
              window.scrollTo(0, h * 0.7);
              window.scrollTo(0, h);
            } catch (e) {}
            // Scrape DOM cards — chưa biết selector chuẩn nên thử nhiều pattern.
            const items = [];
            const seen = new Set();
            // Pattern A: link chi tiết topads có id số
            document.querySelectorAll('a[href*="/topads/detail/"], a[href*="/detail/pc/"]').forEach((a) => {
              const m = (a.href || '').match(/(?:detail\/pc\/|detail\/)(\d+)/);
              if (!m || seen.has(m[1])) return;
              seen.add(m[1]);
              const card = a.closest('[class*="card"], [class*="Card"], [class*="item"], [class*="Item"], div');
              const img = a.querySelector('img') || (card && card.querySelector('img'));
              const vid = a.querySelector('video') || (card && card.querySelector('video'));
              let brand = '', body = '', metrics = '';
              if (card) {
                const spans = [...card.querySelectorAll('span,p,div')].map((e) => (e.textContent || '').trim()).filter(Boolean).slice(0, 8);
                brand = spans[0] || '';
                body = spans.find((s) => s.length > 15) || '';
                metrics = spans.filter((s) => /\d/.test(s)).slice(0, 3).join(' · ');
              }
              items.push({
                id: m[1], brand, body, metrics,
                image: img ? (img.src || img.getAttribute('data-src') || '') : '',
                videoUrl: vid ? (vid.src || vid.getAttribute('src') || '') : '',
                permalink: a.href,
              });
            });
            const caps = (window.__rsCcCap || []).slice(-3).map((c) => ({ url: c.url, text: (c.text || '').slice(0, 2000) }));
            return { items, caps, href: location.href, body: (document.body ? document.body.innerText : '').slice(0, 500) };
          },
        });
        r = out && out[0] && out[0].result;
      } catch (e) {}
      if (r) {
        lastBody = r.body || '';
        for (const it of (r.items || [])) if (it.id && !byId[it.id]) byId[it.id] = { ...it, platform: 'TikTok Creative Center' };
        for (const c of (r.caps || [])) {
          if (rawSamples.length < 3 && !rawSamples.some((s) => s.url === c.url)) rawSamples.push(c);
        }
        const n = Object.keys(byId).length;
        if (n >= target) break;
        if (/log ?in|please sign in|đăng nhập/i.test(lastBody) && n === 0) {
          return { items: [], blocked: true, error: 'Creative Center đòi đăng nhập — mở tab, đăng nhập xong bấm lại.', raw: rawSamples };
        }
        stagnant = n === prev ? stagnant + 1 : 0; prev = n;
        if (stagnant >= 6) break;
      }
      await sleep(1300);
    }
    const items = Object.values(byId).slice(0, target);
    // Filter theo keyword (client-side) nếu có — CC keyword search yếu, ta lọc lại từ industry list.
    const kw = String(keyword || '').trim().toLowerCase();
    const filtered = kw
      ? items.filter((it) => (`${it.brand} ${it.body}`).toLowerCase().includes(kw))
      : items;
    return {
      items: filtered.length ? filtered : items,
      blocked: !items.length,
      error: items.length ? null : 'Chưa parse được item — xem `raw` để refine selector.',
      raw: rawSamples,
      total: items.length,
      filtered: filtered.length,
    };
  } catch (e) {
    return { items: [], blocked: false, error: String(e) };
  }
}

// Một item TikTok (aweme/item) → có id + (author|desc|video).
function _tkLooksItem(x) {
  return x && typeof x === 'object' && (x.id || x.aweme_id) && (x.author || x.desc || x.video);
}

function parseTiktokTexts(texts, count) {
  const out = [];
  const seen = new Set();
  for (const t of texts) {
    let j = null; try { j = JSON.parse(t); } catch (e) { continue; }
    // Các hình dạng response TikTok: item_list[], data[].item, hoặc lồng sâu → deep-find dự phòng.
    let arr = [];
    if (Array.isArray(j.item_list)) arr = j.item_list;
    else if (Array.isArray(j.data)) arr = j.data.map((d) => (d && (d.item || d.aweme_info)) || d).filter(Boolean);
    if (!arr.length) arr = rsDeepFindArray(j, _tkLooksItem);
    for (const raw of arr) {
      const it = (raw && (raw.item || raw.aweme_info)) || raw;
      if (!_tkLooksItem(it)) continue;
      const id = String(it.id || it.aweme_id || '');
      if (!id || seen.has(id)) continue;
      const author = it.author || {};
      const uid = author.uniqueId || author.unique_id || author.uid || '';
      const video = it.video || {};
      const cover = video.cover || video.originCover || video.origin_cover || video.dynamicCover || '';
      seen.add(id);
      out.push({
        id,
        name: String(it.desc || '').slice(0, 120),
        author: author.nickname || author.uniqueId || '',
        // Link video THẬT (permalink) — dựng từ id + user do TikTok trả về, không bịa.
        videoUrl: uid ? `https://www.tiktok.com/@${uid}/video/${id}` : `https://www.tiktok.com/video/${id}`,
        image: typeof cover === 'string' ? cover : (Array.isArray(cover && cover.url_list) ? cover.url_list[0] : ''),
        platform: 'TikTok',
      });
      if (out.length >= count) return out;
    }
  }
  return out;
}

// URL cho một cụm. hashtag mode + có anchor (brand+model đã dịch) → search text = `<anchor> <term>`
// để TikTok chỉ trả video ĐÚNG SP CÓ tag/từ khoá đó (không loãng ra cả ngành hàng như trang /tag/ trần).
// Không có anchor → hạ về /tag/<name> (rộng nhưng vẫn on-topic của tag).
function tkTermUrl(term, mode, anchor) {
  const t = String(term || '').trim();
  if (mode === 'hashtag') {
    if (anchor) return 'https://www.tiktok.com/search/video?q=' + encodeURIComponent(anchor + ' ' + t);
    if (/^#/.test(t)) {
      const clean = t.replace(/^#+/, '').replace(/[\s#]+/g, '').trim();
      if (clean) return 'https://www.tiktok.com/tag/' + encodeURIComponent(clean);
    }
  }
  return 'https://www.tiktok.com/search/video?q=' + encodeURIComponent(t);
}

// Cuộn + bóc video cho MỘT cụm tìm (keyword hoặc hashtag), gộp vào `byId` (dedup theo id video —
// "link trùng thì bỏ qua"). Trả {blocked?: 'login'|'verify'}. Điều hướng CÙNG một tab qua từng cụm.
// Gõ vào ô search của TikTok + Enter, không navigate URL. Trả true nếu tìm được ô, false nếu không
// (caller hạ về navigate). Dùng native setter cho React. Xoá __rsCap trước để lượt sau không nuốt cũ.
async function tkTypeInSearchBox(tabId, term) {
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId }, world: 'MAIN', args: [term],
      func: (q) => {
        // Reset bộ đệm response để không nhặt lại cụm cũ.
        try { window.__rsCap = []; } catch (e) {}
        const inp = document.querySelector('input[type="search"]')
          || document.querySelector('[data-e2e="search-user-input"]')
          || document.querySelector('input[placeholder*="Search" i], input[placeholder*="Tìm" i], input[placeholder*="搜索" i]');
        if (!inp) return false;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, q);
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        // React đôi khi cần thêm 'change'; thêm cho chắc.
        inp.dispatchEvent(new Event('change', { bubbles: true }));
        // Enter → SPA route sang /search/video?q=... (KHÔNG reload).
        const opts = { bubbles: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 };
        inp.dispatchEvent(new KeyboardEvent('keydown', opts));
        inp.dispatchEvent(new KeyboardEvent('keypress', opts));
        inp.dispatchEvent(new KeyboardEvent('keyup', opts));
        // Fallback cuối: nếu có form, submit thẳng.
        try { const f = inp.closest('form'); if (f && typeof f.requestSubmit === 'function') f.requestSubmit(); } catch (e) {}
        return true;
      },
    });
    return !!(out && out[0] && out[0].result);
  } catch (e) { return false; }
}

async function searchTiktokTerm(tab, term, byId, target, budgetMs, mode, anchor, isFirst) {
  if (isFirst) {
    // LẦN ĐẦU: navigate URL đầy đủ (nạp signing JS của TikTok cho các cụm sau xài chung).
    await chrome.tabs.update(tab.id, { url: tkTermUrl(term, mode, anchor) });
    await waitForComplete(tab.id, 16000);
    await sleep(2200); // để trang render danh sách video đầu tiên
  } else {
    // CÁC CỤM SAU: KHÔNG navigate — GÕ vào ô search + Enter, như user tự search. TikTok SPA
    // đổi route ngầm (không reload trang, tab không "nhảy"). Chính là "kiểu search giống sản phẩm".
    const q = String(term).replace(/^#/, '#'); // giữ nguyên; hashtag TikTok search-box hiểu #
    const typed = await tkTypeInSearchBox(tab.id, mode === 'hashtag' && anchor ? `${anchor} ${q}` : q);
    if (!typed) {
      // Không tìm thấy ô search (layout đổi) → hạ về navigate cho cụm này (fallback an toàn).
      await chrome.tabs.update(tab.id, { url: tkTermUrl(term, mode, anchor) });
      await waitForComplete(tab.id, 16000);
    }
    await sleep(1800);
  }

  const deadline = Date.now() + budgetMs;
  let prevN = Object.keys(byId).length, stagnant = 0, iter = 0;
  while (Date.now() < deadline) {
    iter++; // không focus tab định kỳ nữa — focus 1 lần ở đầu là đủ, tránh cảm giác "cứ nhảy lên"
    let r = null;
    try {
      const out = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, world: 'MAIN',
        func: () => {
          // Kích infinite-scroll: cuộn xuống đáy nhiều nấc (kích IntersectionObserver "load thêm").
          const SCOPE = '[data-e2e="search_video-item"]';
          try {
            const h = document.documentElement.scrollHeight;
            window.scrollTo(0, h * 0.7);
            window.scrollTo(0, h);
            window.dispatchEvent(new Event('scroll'));
          } catch (e) {}
          // BÓC từ DOM: mỗi video là thẻ <a href=".../@user/video/id">. CHỈ lấy trong KHỐI KẾT QUẢ
          // SEARCH — bỏ video "Có thể bạn thích"/gợi ý ở cuối trang. Không có marker → lấy hết (fallback).
          const hasScope = !!document.querySelector(SCOPE);
          const links = [];
          document.querySelectorAll('a[href*="/video/"]').forEach((a) => {
            if (hasScope && !a.closest(SCOPE)) return; // ngoài lưới kết quả search → bỏ (rác gợi ý)
            const m = (a.href || '').match(/tiktok\.com\/@([\w.\-]+)\/video\/(\d+)/);
            if (!m) return;
            const img = a.querySelector('img') || (a.closest('div[class]') && a.closest('div[class]').querySelector('img'));
            let name = img ? (img.alt || '') : '';
            if (/^\d+$/.test(name.trim())) name = ''; // alt chỉ là số (id) → không phải mô tả, bỏ
            links.push({ id: m[2], author: m[1], url: 'https://www.tiktok.com/@' + m[1] + '/video/' + m[2], image: img ? (img.src || img.getAttribute('data-src') || '') : '', name: name });
          });
          const cap = (window.__rsCap || []).filter((c) => /api\/search\/(general|item|video)/.test(c.url)).map((c) => c.text);
          return { links, cap, href: location.href, body: document.body ? document.body.innerText.slice(0, 400) : '' };
        },
      });
      r = out && out[0] && out[0].result;
    } catch (e) { /* trang chưa sẵn sàng */ }
    if (r) {
      const lastHref = r.href, lastBody = r.body || '';
      for (const it of (r.links || [])) {
        if (it.id && !byId[it.id]) byId[it.id] = { id: it.id, name: it.name || '', author: it.author || '', videoUrl: it.url, image: it.image || '', platform: 'TikTok' };
      }
      // API (nếu page-hook chộp được) có desc/author đẹp hơn — gộp đè lên bản DOM.
      for (const it of parseTiktokTexts(r.cap || [], 999)) byId[it.id] = Object.assign({}, byId[it.id] || {}, it);
      const n = Object.keys(byId).length;
      if (n >= target) return {}; // đủ target trên TỔNG các cụm → dừng cả loạt
      if (n === 0 && /\/login|passport|\/signup/i.test(lastHref) && /log ?in|đăng nhập|sign up/i.test(lastBody)) return { blocked: 'login' };
      if (/verify|captcha|robot|security check|滑块|verification/i.test(lastBody)) return { blocked: 'verify' };
      stagnant = n === prevN ? stagnant + 1 : 0; prevN = n;
      if (stagnant >= 6) break; // cụm này cạn → sang cụm sau (đừng phí thời gian)
    }
    await sleep(900); // chờ TikTok tải trang video tiếp sau khi cuộn (load-more chậm hơn scroll)
  }
  return {};
}

// Đoán ngôn ngữ mô tả video → 'match' | 'neutral' | 'other' so với NƯỚC đích. Dùng để SẮP XẾP
// (không bỏ), vì TikTok cá nhân hoá theo account/IP: bạn login VN, dù dịch keyword sang tiếng Phi
// nó vẫn đẩy video VN. Bám dấu Việt / chữ Thái / chữ Hán để nhận diện; text Latin không dấu → 'neutral'
// (không phân biệt được PH vs ID vs EN). Không có mô tả → 'neutral' (không có tín hiệu, đừng dìm).
function tkLangTag(text, region) {
  const s = String(text || '').trim();
  if (!s) return 'neutral';
  const r = String(region || '').toUpperCase();
  const isThai = /[฀-๿]/.test(s);
  const isHan = /[一-鿿]/.test(s);
  const isVN = /[ăâđêôơư]|[àáảãạầấẩẫậằắẳẵặèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]/i.test(s);
  // Match khi script đặc trưng khớp NƯỚC đích.
  if (isThai) return r === 'TH' ? 'match' : 'other';
  if (isHan) return (r === 'TW' || r === 'CN' || r === 'SG') ? 'match' : 'other';
  if (isVN) return r === 'VN' ? 'match' : 'other';
  return 'neutral'; // Latin không dấu (EN/PH/ID/MY…) — không đủ tín hiệu, coi như trung tính
}

// TikTok organic: NHIỀU cụm tìm (keyword + hashtag do backend sinh theo ngôn ngữ region) → gom video,
// bỏ link trùng. `keywords` (mảng) ưu tiên; không có thì dùng `keyword` đơn. `region` để STAMP
// nhãn ngôn ngữ vào từng item (results.js sắp xếp: match → neutral → other). Tất cả chạy trên 1 tab.
async function searchTiktok(keyword, count, keywords, region, mode, anchor) {
  try {
    const tab = await tiktokTab();
    const target = Math.min(150, Math.max(12, count || 24));
    let terms = (Array.isArray(keywords) && keywords.length ? keywords : [keyword]).map((s) => String(s || '').trim()).filter(Boolean).slice(0, 6);
    if (!terms.length) return { items: [], blocked: false, error: 'TikTok: thiếu từ khoá.' };
    // hashtag mode: ưu tiên hashtag; có anchor thì kể cả keyword thường cũng ok (đằng nào cũng nối anchor).
    if (mode === 'hashtag') {
      const tags = terms.filter((t) => /^#/.test(t));
      if (tags.length) terms = tags;
      else if (!anchor) mode = 'mixed'; // không hashtag, không anchor → hạ về search text thô
    }
    // Mode label khớp thực tế: có anchor = "anchored" (neo brand+model), else /tag/ = "hashtag".
    const effectiveMode = mode === 'hashtag' ? (anchor ? 'anchored' : 'hashtag') : 'mixed';

    const byId = {}; // id -> item, dedup xuyên suốt mọi cụm ("link trùng thì bỏ qua")
    const totalDeadline = Date.now() + 120000; // ngân sách tổng cho cả loạt cụm
    let blocked = null;
    // Focus tab CHỈ 1 lần ở đầu (nạp signing JS, render kết quả đầu). Các cụm sau chạy nền + gõ ô
    // search → tab không "nhảy" như cũ. Nếu Chrome tiết chế nặng, kết quả có thể hụt vài cụm cuối —
    // đánh đổi chấp nhận được để bớt gây khó chịu.
    await focusTab(tab.id);
    for (let i = 0; i < terms.length; i++) {
      if (Object.keys(byId).length >= target || Date.now() >= totalDeadline) break;
      // Chia đều thời gian còn lại cho các cụm CHƯA chạy; kẹp 12–28s/cụm.
      const remainingTerms = terms.length - i;
      const budget = Math.max(12000, Math.min(28000, Math.floor((totalDeadline - Date.now()) / Math.max(1, remainingTerms))));
      const res = await searchTiktokTerm(tab, terms[i], byId, target, budget, mode, anchor, i === 0);
      if (res.blocked) { blocked = res.blocked; break; }
    }

    // Nhãn ngôn ngữ + SẮP XẾP: match trước, neutral giữa, other cuối. TikTok cá nhân hoá theo
    // account nên video khác ngôn ngữ (vd tiếng Việt khi chọn PH) vẫn giữ lại — chỉ đẩy xuống cuối.
    const rank = { match: 0, neutral: 1, other: 2 };
    const stamped = Object.values(byId).map((it) => ({ ...it, langMatch: tkLangTag(it.name, region) }));
    stamped.sort((a, b) => rank[a.langMatch] - rank[b.langMatch]);
    const items = stamped.slice(0, target);
    const counts = items.reduce((a, it) => (a[it.langMatch]++, a), { match: 0, neutral: 0, other: 0 });
    if (blocked === 'login') { await focusTab(tab.id); return { items, counts, mode: effectiveMode, blocked: !items.length, error: 'TikTok đòi đăng nhập — đăng nhập trong tab rồi bấm lại.' }; }
    if (blocked === 'verify') { await focusTab(tab.id); return { items, counts, mode: effectiveMode, blocked: !items.length, error: 'TikTok bắt xác minh — xử trong tab rồi bấm lại.' }; }
    if (!items.length) { await focusTab(tab.id); return { items: [], counts, mode: effectiveMode, blocked: true, error: 'Chưa lấy được video TikTok (chưa đăng nhập / bị chặn tự động / vùng không có kết quả). Mở tab TikTok, cuộn 1 chút rồi bấm lại.' }; }
    return { items, counts, mode: effectiveMode, blocked: false };
  } catch (e) { return { items: [], blocked: false, error: String(e) }; }
}

// ===== DOUYIN organic: keyword → list VIDEO (nội địa TQ, tiếng Trung; ít vướng cá nhân hoá VN) =====
// Douyin siết bot mạnh: hay hiện slider verify sau vài truy vấn. User chưa login vẫn xem được video
// public, nhưng có thể bị 网络异常/xác minh. Chiến lược: 1 tab riêng, navigate 1 lần, sau đó GÕ vào ô
// search + Enter cho các cụm sau (SPA đổi route ngầm). Kết quả: DOM scrape <a href="/video/<id>">.
let douyinTabId = null;
async function douyinTab() {
  if (douyinTabId != null) { try { const t = await chrome.tabs.get(douyinTabId); if (t) return t; } catch (e) { douyinTabId = null; } }
  const t = await chrome.tabs.create({ url: 'about:blank', active: false });
  douyinTabId = t.id;
  return t;
}

// Gõ vào ô search Douyin, KHÔNG navigate (giống TikTok). Trả true/false.
async function dyTypeInSearchBox(tabId, term) {
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId }, world: 'MAIN', args: [term],
      func: (q) => {
        try { window.__rsCap = []; } catch (e) {}
        // Douyin: ô search thường có placeholder tiếng Trung, hoặc data-e2e riêng của họ.
        const inp = document.querySelector('input[type="search"]')
          || document.querySelector('input[placeholder*="搜索"]')
          || document.querySelector('input[data-e2e*="search"]')
          || Array.from(document.querySelectorAll('input')).find((e) => /搜索|search/i.test((e.placeholder || '') + (e.getAttribute('aria-label') || '')));
        if (!inp) return false;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, q);
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        inp.dispatchEvent(new Event('change', { bubbles: true }));
        const opts = { bubbles: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 };
        inp.dispatchEvent(new KeyboardEvent('keydown', opts));
        inp.dispatchEvent(new KeyboardEvent('keypress', opts));
        inp.dispatchEvent(new KeyboardEvent('keyup', opts));
        try { const f = inp.closest('form'); if (f && typeof f.requestSubmit === 'function') f.requestSubmit(); } catch (e) {}
        return true;
      },
    });
    return !!(out && out[0] && out[0].result);
  } catch (e) { return false; }
}

async function searchDouyinTerm(tab, term, byId, target, budgetMs, isFirst) {
  if (isFirst) {
    // /search/<encoded>?type=video → tab video, đỡ lẫn user/hashtag ở trang search tổng hợp.
    await chrome.tabs.update(tab.id, { url: 'https://www.douyin.com/search/' + encodeURIComponent(term) + '?type=video' });
    await waitForComplete(tab.id, 16000);
    await sleep(2500); // Douyin render chậm hơn TikTok (JS nặng, animation intro)
  } else {
    const typed = await dyTypeInSearchBox(tab.id, term);
    if (!typed) {
      await chrome.tabs.update(tab.id, { url: 'https://www.douyin.com/search/' + encodeURIComponent(term) + '?type=video' });
      await waitForComplete(tab.id, 16000);
    }
    await sleep(2200);
  }
  const deadline = Date.now() + budgetMs;
  let prevN = Object.keys(byId).length, stagnant = 0;
  while (Date.now() < deadline) {
    let r = null;
    try {
      const out = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, world: 'MAIN',
        func: () => {
          try {
            const h = document.documentElement.scrollHeight;
            window.scrollTo(0, h * 0.7);
            window.scrollTo(0, h);
            window.dispatchEvent(new Event('scroll'));
          } catch (e) {}
          // Douyin video URL pattern: /video/<numeric_id>. Card thường có <img> cover + tiêu đề.
          const links = [];
          document.querySelectorAll('a[href*="/video/"]').forEach((a) => {
            const m = (a.getAttribute('href') || '').match(/\/video\/(\d+)/);
            if (!m) return;
            const img = a.querySelector('img') || (a.closest('li,div[class]') && (a.closest('li,div[class]').querySelector('img')));
            let name = '';
            // Douyin: tiêu đề nằm ở <p class="..."> hoặc [data-e2e="search-card-desc"] sát card.
            const wrap = a.closest('li') || a.closest('div[class]');
            if (wrap) {
              const t = wrap.querySelector('[data-e2e*="desc"], p[class]');
              if (t) name = (t.textContent || '').trim().slice(0, 200);
            }
            if (!name && img && img.alt && !/^\d+$/.test(img.alt.trim())) name = img.alt;
            const href = a.href.startsWith('http') ? a.href : ('https://www.douyin.com' + a.getAttribute('href'));
            links.push({ id: m[1], url: href.split('?')[0], image: img ? (img.src || img.getAttribute('data-src') || '') : '', name });
          });
          return { links, href: location.href, body: document.body ? document.body.innerText.slice(0, 400) : '' };
        },
      });
      r = out && out[0] && out[0].result;
    } catch (e) { /* trang chưa sẵn sàng */ }
    if (r) {
      const lastHref = r.href, lastBody = r.body || '';
      for (const it of (r.links || [])) {
        if (it.id && !byId[it.id]) byId[it.id] = { id: it.id, name: it.name || '', author: '', videoUrl: it.url, image: it.image || '', platform: 'Douyin' };
      }
      const n = Object.keys(byId).length;
      if (n >= target) return {};
      if (/passport|\/login/i.test(lastHref) || /扫码登录|需要登录|请登录/.test(lastBody)) return { blocked: 'login' };
      if (/滑块|请拖动|向右滑|verify|captcha|安全验证|网络异常/i.test(lastBody)) return { blocked: 'verify' };
      stagnant = n === prevN ? stagnant + 1 : 0; prevN = n;
      if (stagnant >= 6) break;
    }
    await sleep(1100);
  }
  return {};
}

async function searchDouyin(keyword, count, keywords, anchor) {
  try {
    const tab = await douyinTab();
    const target = Math.min(100, Math.max(12, count || 24));
    let terms = (Array.isArray(keywords) && keywords.length ? keywords : [keyword]).map((s) => String(s || '').trim()).filter(Boolean);
    if (!terms.length) return { items: [], blocked: false, error: 'Douyin: thiếu từ khoá.' };
    // Douyin search hiểu text thô (kể cả có #). Với anchor + hashtag: nối lại thành text 1 dòng.
    terms = terms.slice(0, 4).map((t) => (anchor && /^#/.test(t)) ? `${anchor} ${t}` : t);

    const byId = {};
    const totalDeadline = Date.now() + 120000;
    let blocked = null;
    await focusTab(tab.id); // Douyin cần foreground để render (giống TikTok)
    for (let i = 0; i < terms.length; i++) {
      if (Object.keys(byId).length >= target || Date.now() >= totalDeadline) break;
      const remaining = terms.length - i;
      const budget = Math.max(14000, Math.min(30000, Math.floor((totalDeadline - Date.now()) / Math.max(1, remaining))));
      const res = await searchDouyinTerm(tab, terms[i], byId, target, budget, i === 0);
      if (res.blocked) { blocked = res.blocked; break; }
    }
    // Douyin toàn tiếng Trung → langMatch coi như 'match' hết (không cần detect).
    const items = Object.values(byId).slice(0, target).map((it) => ({ ...it, langMatch: 'match' }));
    const counts = { match: items.length, neutral: 0, other: 0 };
    if (blocked === 'login') { await focusTab(tab.id); return { items, counts, blocked: !items.length, error: 'Douyin đòi đăng nhập — mở tab douyin.com đăng nhập (quét QR) rồi bấm lại.' }; }
    if (blocked === 'verify') { await focusTab(tab.id); return { items, counts, blocked: !items.length, error: 'Douyin bắt xác minh (滑块) — kéo slider trong tab rồi bấm lại.' }; }
    if (!items.length) { await focusTab(tab.id); return { items: [], counts, blocked: true, error: 'Chưa lấy được video Douyin (chặn tự động / cần verify). Mở tab douyin.com, cuộn 1 chút rồi bấm lại.' }; }
    return { items, counts, blocked: false };
  } catch (e) { return { items: [], blocked: false, error: String(e) }; }
}

// Shopee: fetch thô /api/v4/search/search_items bị 403 (anti-bot, thiếu header ký JS). Cách chạy:
// ĐIỀU HƯỚNG tab shopee (đã đăng nhập) tới trang /search — để CHÍNH TRANG gọi search_items (tự ký),
// page-hook chộp response. Cuộn để lấy thêm trang. Giống Taobao/Temu, chỉ khác domain.
let shopeeSearchTabId = null;
async function shopeeSearchTab() {
  // Tab RIÊNG cho search (không chiếm tab shopee bạn đang mở). Cookie same-domain → vẫn có session login.
  if (shopeeSearchTabId != null) { try { const t = await chrome.tabs.get(shopeeSearchTabId); if (t) return t; } catch (e) { shopeeSearchTabId = null; } }
  const t = await chrome.tabs.create({ url: 'about:blank', active: false });
  shopeeSearchTabId = t.id;
  return t;
}
async function searchShopee(keyword, domain) {
  domain = domain || 'shopee.vn';
  try {
    // Dùng lại tab shopee CÓ SẴN (không đẻ tab thừa), navigate ngầm (active:false → không cướp focus).
    // search_items bắn NGAY khi load → thoát ngay khi chộp được (nhanh ~2-3s), không chờ/không cuộn.
    const tab = await ensureTab(domain);
    await chrome.tabs.update(tab.id, { url: `https://${domain}/search?keyword=${encodeURIComponent(keyword)}`, active: false });

    const deadline = Date.now() + 15000;
    let texts = [], videoItems = {}, textsIter = -1, iter = 0;
    while (Date.now() < deadline) {
      await sleep(500);
      iter++;
      let r = null;
      try {
        const out = await chrome.scripting.executeScript({
          target: { tabId: tab.id }, world: 'MAIN',
          func: () => {
            const cap = (window.__rsCap || []).filter((c) => /\/api\/v4\/search\/search_items/.test(c.url)).map((c) => c.text);
            // search_items KHÔNG có URL video, chỉ DOM có badge `data-testid="badge-video"`. Bóc LINK
            // sản phẩm có badge đó (shopid.itemid trong href) — sau này backend trỏ vào link lấy video.
            const vids = [];
            document.querySelectorAll('[data-testid="badge-video"]').forEach((b) => {
              const a = b.closest('a[href*="-i."]') || (b.closest('li') && b.closest('li').querySelector('a[href*="-i."]'));
              if (!a) return;
              const m = (a.getAttribute('href') || '').match(/-i\.(\d+)\.(\d+)/);
              if (m) vids.push({ shopid: m[1], itemid: m[2], url: a.href.split('?')[0] });
            });
            return { cap, vids, href: location.href, body: document.body ? document.body.innerText.slice(0, 300) : '' };
          },
        });
        r = out && out[0] && out[0].result;
      } catch (e) { /* trang chưa sẵn sàng */ }
      if (r) {
        if (/\/(buyer\/)?login|\/verify/i.test(r.href) || /verify|captcha|robot|xác minh/i.test(r.body || '')) { return { texts: [], blocked: true, error: 'Shopee đòi đăng nhập/xác minh — mở shopee.vn đăng nhập rồi bấm lại.' }; }
        if (r.cap && r.cap.length) { texts = r.cap; if (textsIter < 0) textsIter = iter; }
        for (const v of (r.vids || [])) videoItems[v.itemid] = v;
        // Có JSON + đã bắt badge (hoặc chờ thêm ~2s cho DOM render badge) → thoát.
        if (texts.length > 0 && (Object.keys(videoItems).length > 0 || iter - textsIter >= 4)) break;
      }
    }
    return { texts, videoItems: Object.values(videoItems), blocked: !texts.length, error: texts.length ? undefined : 'Shopee: chưa chộp được search_items — thử lại (trang có thể chưa render kết quả kịp).' };
  } catch (e) { return { texts: [], videoItems: [], blocked: false, error: String(e) }; }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg !== 'object') return;

  if (msg.type === 'RS_PING') {
    sendResponse({ ok: true, version: VERSION });
    return;
  }

  // Đọc MỘT cookie theo tên, cho trang Research dò xem đã đăng nhập sàn nào.
  //
  // Chỉ service worker mới có `chrome.cookies` (trang web thì không, kể cả trang cùng miền —
  // cookie đăng nhập của các sàn đều là HttpOnly). Trang gọi qua cầu `content.js`.
  //
  // Trả về cookie NGUYÊN VẸN chứ không phải true/false: `research.js` tự quyết định thế nào là
  // "đã đăng nhập" theo từng sàn (Shopee coi `SPC_U === '-'` là chưa), và TikTok Shop còn cần
  // chính giá trị đó làm seller id để dựng request.
  if (msg.type === 'RS_COOKIE') {
    try {
      chrome.cookies.get({ url: msg.url, name: msg.name }, (c) => {
        sendResponse({ ok: true, cookie: c ? { name: c.name, value: c.value, domain: c.domain } : null });
      });
    } catch (e) {
      sendResponse({ ok: false, cookie: null, error: String(e) });
    }
    return true; // giữ kênh mở cho phản hồi bất đồng bộ
  }

  if (msg.type === 'RS_FETCH') {
    handleFetch(msg.requests).then((responses) => sendResponse({ ok: true, responses }));
    return true; // giữ kênh mở cho phản hồi bất đồng bộ
  }

  if (msg.type === 'RS_FIND_SIMILAR') {
    findSimilar(msg.url).then((r) => sendResponse({
      ok: !!(r && (r.text || typeof r.domMin === 'number')),
      text: (r && r.text) || '',
      domMin: r ? r.domMin : null,
    }));
    return true;
  }

  if (msg.type === 'RS_COST_BATCH') {
    costBatch(msg.seedUrl, msg.products || []).then((results) => sendResponse({ ok: true, results }));
    return true;
  }

  if (msg.type === 'RS_1688') {
    search1688(msg.keyword, msg.count).then((r) => sendResponse({ ok: true, ...r }));
    return true;
  }

  if (msg.type === 'RS_TAOBAO') {
    searchTaobao(msg.keyword, msg.count).then((r) => sendResponse({ ok: true, ...r })).catch((e) => sendResponse({ ok: true, items: [], blocked: false, error: String(e) }));
    return true;
  }

  if (msg.type === 'RS_TEMU') {
    searchTemu(msg.keyword, msg.count).then((r) => sendResponse({ ok: true, ...r })).catch((e) => sendResponse({ ok: true, items: [], blocked: false, error: String(e) }));
    return true;
  }

  if (msg.type === 'RS_AMAZON') {
    amazonSearch(msg.domain, msg.url).then((r) => sendResponse({ ok: true, ...r }));
    return true;
  }

  if (msg.type === 'RS_TIKTOK') {
    searchTiktok(msg.keyword, msg.count, msg.keywords, msg.region, msg.mode, msg.anchor).then((r) => sendResponse({ ok: true, ...r })).catch((e) => sendResponse({ ok: true, items: [], blocked: false, error: String(e) }));
    return true;
  }

  if (msg.type === 'RS_TIKTOK_CC') {
    searchTiktokCreative(msg.region, msg.keyword, msg.count).then((r) => sendResponse({ ok: true, ...r })).catch((e) => sendResponse({ ok: true, items: [], blocked: false, error: String(e) }));
    return true;
  }

  if (msg.type === 'RS_DOUYIN') {
    searchDouyin(msg.keyword, msg.count, msg.keywords, msg.anchor).then((r) => sendResponse({ ok: true, ...r })).catch((e) => sendResponse({ ok: true, items: [], blocked: false, error: String(e) }));
    return true;
  }

  if (msg.type === 'RS_SHOPEE') {
    searchShopee(msg.keyword, msg.domain).then((r) => sendResponse({ ok: true, ...r })).catch((e) => sendResponse({ ok: true, texts: [], blocked: false, error: String(e) }));
    return true;
  }
});
