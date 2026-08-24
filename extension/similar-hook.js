/*
 * Hook cài vào trang find_similar_products (MAIN world, document_start).
 *
 * Ta KHÔNG gọi recommend_post trực tiếp được (403 vì thiếu chữ ký). Nên để chính trang Shopee
 * gọi (nó tự ký), còn đây chỉ bọc `fetch`/XHR để chộp lại response của recommend_post rồi cất
 * vào `window.__rsCaptured` cho background đọc. Cài ở document_start để bọc TRƯỚC khi trang gọi.
 */

(function () {
  if (window.__rsHooked) return;
  window.__rsHooked = true;
  window.__rsCaptured = null;

  const isSimilar = (u) => typeof u === 'string' && u.indexOf('recommend_post') !== -1;

  // fetch
  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (...args) {
      const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
      const p = origFetch.apply(this, args);
      if (isSimilar(url)) {
        p.then((r) => { try { r.clone().text().then((t) => { window.__rsCaptured = t; }); } catch (e) {} }).catch(() => {});
      }
      return p;
    };
  }

  // XHR (dự phòng nếu Shopee dùng XHR thay fetch)
  const OrigXHR = window.XMLHttpRequest;
  if (OrigXHR) {
    const origOpen = OrigXHR.prototype.open;
    OrigXHR.prototype.open = function (method, url) {
      this.__rsUrl = url;
      return origOpen.apply(this, arguments);
    };
    OrigXHR.prototype.addEventListener &&
      (function () {
        const origSend = OrigXHR.prototype.send;
        OrigXHR.prototype.send = function () {
          this.addEventListener('load', function () {
            try { if (isSimilar(this.__rsUrl)) window.__rsCaptured = this.responseText; } catch (e) {}
          });
          return origSend.apply(this, arguments);
        };
      })();
  }
})();
