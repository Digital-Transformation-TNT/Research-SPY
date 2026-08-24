/*
 * Hook CHUNG (MAIN world, document_start) cho các sàn phải "KÝ SINH" request của chính trang.
 *
 * Taobao (h5search) và Temu (/api/poppy/v1/search) không cho ta tự dựng request: Taobao cần chữ ký
 * mtop + cookie chống bot `x5sec` (Baxia), Temu cần token `anti-content` — cả hai do JS của trang tự
 * sinh runtime, xoay liên tục, không reimplement bền được. Nên để CHÍNH TRANG gọi (khi ta điều hướng
 * tới URL search), còn đây chỉ bọc `fetch`/XHR để chộp response rồi cất vào `window.__rsCap` cho
 * background đọc. Cài ở document_start để bọc TRƯỚC khi trang gọi.
 */
(function () {
  if (window.__rsCapHooked) return;
  window.__rsCapHooked = true;
  window.__rsCap = []; // [{ url, text, ts }] — các response search đã chộp (mới nhất ở cuối)

  var NEEDLES = [
    'mtop.taobao.wsearch.h5search', // Taobao search (mtop)
    'mtop.relationrecommend',       // Taobao/1688 recommend (dự phòng)
    '/api/poppy/v1/search',         // Temu search
    '/api/poppy/v1/api/search',     // Temu (biến thể path)
    '/api/search/general',          // TikTok search (tab tổng hợp)
    '/api/search/item',             // TikTok search video
    '/api/search/video',            // TikTok search video (biến thể)
    '/api/v4/search/search_items',  // Shopee search (trang tự gọi + ký anti-bot, ta chộp response)
  ];
  function match(u) {
    if (typeof u !== 'string') return false;
    for (var i = 0; i < NEEDLES.length; i++) if (u.indexOf(NEEDLES[i]) !== -1) return true;
    return false;
  }
  function push(url, text) {
    try {
      if (!text) return;
      window.__rsCap.push({ url: url, text: text, ts: Date.now() });
      // Giữ nhiều hơn: TikTok/infinite-scroll bắn 1 response/trang, auto-scroll gom chục trang.
      if (window.__rsCap.length > 40) window.__rsCap.shift();
    } catch (e) {}
  }

  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function () {
      var url = typeof arguments[0] === 'string' ? arguments[0] : (arguments[0] && arguments[0].url) || '';
      var p = origFetch.apply(this, arguments);
      if (match(url)) {
        p.then(function (r) { try { r.clone().text().then(function (t) { push(url, t); }); } catch (e) {} }).catch(function () {});
      }
      return p;
    };
  }

  var OrigXHR = window.XMLHttpRequest;
  if (OrigXHR) {
    var origOpen = OrigXHR.prototype.open, origSend = OrigXHR.prototype.send;
    OrigXHR.prototype.open = function (method, url) { this.__rsU = url; return origOpen.apply(this, arguments); };
    OrigXHR.prototype.send = function () {
      var self = this;
      this.addEventListener('load', function () { try { if (match(self.__rsU)) push(self.__rsU, self.responseText); } catch (e) {} });
      return origSend.apply(this, arguments);
    };
  }
})();
