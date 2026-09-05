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
    '/api/graphql',                 // Facebook Ad Library (trang tự ký AdLibrarySearchPaginationQuery)
    '/trends/api/widgetdata/',      // Google Trends TRANG CŨ (trang tự xin widget bằng token của nó)
    '/TrendsUi/data/batchexecute',  // Google Trends TRANG MỚI — nơi DUY NHẤT có cột "Thay đổi"
  ];
  function match(u) {
    if (typeof u !== 'string') return false;
    for (var i = 0; i < NEEDLES.length; i++) if (u.indexOf(NEEDLES[i]) !== -1) return true;
    return false;
  }
  function push(url, text) {
    try {
      if (!text) return;
      // FB bắn RẤT nhiều /api/graphql (filter options, đếm…); chỉ giữ response CÓ quảng cáo
      // (ad_archive_id) để không đẩy trôi response tìm-kiếm khỏi bộ đệm 40 phần tử.
      if (url.indexOf('/api/graphql') !== -1 && text.indexOf('ad_archive_id') === -1) return;
      // Trends bắn 4 widget mỗi lần tải trang (biểu đồ, bản đồ, chủ đề, truy vấn); chỉ giữ
      // widget TRUY VẤN liên quan — ba cái kia nặng và sẽ đẩy nó khỏi bộ đệm 40 phần tử.
      if (url.indexOf('/trends/api/widgetdata/') !== -1 && url.indexOf('relatedsearches') === -1) return;
      // Trang mới bắn một RPC nặng 4,5 MB (danh mục/gợi ý, không phải bảng ta cần). Giữ nó là
      // đẩy trôi mọi thứ khác khỏi bộ đệm 40 phần tử và bắt relay chở 4,5 MB qua mạng mỗi lượt.
      // Bảng truy vấn liên quan đo được chỉ vài chục KB.
      if (url.indexOf('/TrendsUi/data/batchexecute') !== -1 && text.length > 1500000) return;
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
