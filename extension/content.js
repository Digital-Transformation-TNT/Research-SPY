/*
 * Cầu nối giữa TRANG WEB của bạn và service worker.
 *
 * Trang web không gọi trực tiếp API extension được, nên nó `window.postMessage` xuống đây;
 * content script chuyển tiếp qua `chrome.runtime` tới background, rồi post kết quả ngược lên
 * trang. Chỉ nhận message có nhãn 'research-spy' để không ai khác chen vào.
 */

(function () {
  const FROM_PAGE = 'research-spy';
  const FROM_EXT = 'research-spy-ext';

  window.addEventListener('message', (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== FROM_PAGE) return;

    if (data.type === 'PING') {
      chrome.runtime.sendMessage({ type: 'RS_PING' }, (resp) => {
        window.postMessage(
          { source: FROM_EXT, type: 'PONG', id: data.id, ok: !!(resp && resp.ok), version: resp && resp.version },
          '*'
        );
      });
      return;
    }

    if (data.type === 'FETCH') {
      chrome.runtime.sendMessage({ type: 'RS_FETCH', requests: data.requests }, (resp) => {
        window.postMessage(
          { source: FROM_EXT, type: 'FETCH_RESULT', id: data.id, responses: (resp && resp.responses) || [] },
          '*'
        );
      });
      return;
    }
  });

  // Báo cho trang biết extension đã có mặt (trang có thể chờ event này thay vì tự PING).
  window.postMessage({ source: FROM_EXT, type: 'READY' }, '*');
})();
