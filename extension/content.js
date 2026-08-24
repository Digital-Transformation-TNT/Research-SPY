/*
 * Cầu nối giữa TRANG WEB của bạn và service worker.
 *
 * Trang web không gọi trực tiếp API extension được, nên nó `window.postMessage` xuống đây;
 * content script chuyển tiếp qua `chrome.runtime` tới background, rồi post kết quả ngược lên
 * trang. Chỉ nhận message có nhãn 'research-spy' để không ai khác chen vào.
 *
 * HAI GIAO THỨC, cố ý giữ cả hai:
 *
 *   PING / FETCH   giao thức hẹp, có từ đầu. `frontend/lib/ads/extension.ts` dùng nó cho
 *                  luồng `pending` → `/api/ads/ingest` của backend.
 *   CALL           giao thức chung, thêm khi trang Research chuyển từ extension vào webtool.
 *                  Nó chuyển tiếp NGUYÊN VẸN một message `RS_*` bất kỳ. Nhờ vậy thêm một
 *                  loại lệnh mới ở `background.js` không phải sửa file này lần nữa.
 *
 * CALL chỉ nhận `type` bắt đầu bằng `RS_`, và đó là ranh giới an ninh chứ không phải quy ước
 * đặt tên: thiếu nó, bất kỳ script nào trên trang cũng bảo được extension gọi mạng bằng phiên
 * đăng nhập của người dùng tới nơi nó muốn.
 */

(function () {
  const FROM_PAGE = 'research-spy';
  const FROM_EXT = 'research-spy-ext';

  /** Extension bị tải lại / gỡ giữa chừng thì kênh đứt và callback không bao giờ được gọi. */
  function forward(msg, reply) {
    try {
      chrome.runtime.sendMessage(msg, (resp) => {
        if (chrome.runtime.lastError) {
          reply(null, chrome.runtime.lastError.message);
          return;
        }
        reply(resp, null);
      });
    } catch (error) {
      reply(null, String(error));
    }
  }

  window.addEventListener('message', (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== FROM_PAGE) return;

    if (data.type === 'PING') {
      forward({ type: 'RS_PING' }, (resp) => {
        window.postMessage(
          { source: FROM_EXT, type: 'PONG', id: data.id, ok: !!(resp && resp.ok), version: resp && resp.version },
          '*'
        );
      });
      return;
    }

    if (data.type === 'FETCH') {
      forward({ type: 'RS_FETCH', requests: data.requests }, (resp) => {
        window.postMessage(
          { source: FROM_EXT, type: 'FETCH_RESULT', id: data.id, responses: (resp && resp.responses) || [] },
          '*'
        );
      });
      return;
    }

    if (data.type === 'CALL') {
      const msg = data.msg;
      if (!msg || typeof msg !== 'object' || typeof msg.type !== 'string' || !msg.type.startsWith('RS_')) {
        window.postMessage({ source: FROM_EXT, type: 'CALL_RESULT', id: data.id, result: null }, '*');
        return;
      }
      forward(msg, (resp, error) => {
        // Trả `null` khi hỏng, KHÔNG phải một object lỗi: mọi chỗ gọi ở trang Research đều đã
        // kiểm `!res || !res.ok` sẵn, nên `null` rơi đúng vào nhánh báo lỗi tác giả đã viết.
        window.postMessage(
          { source: FROM_EXT, type: 'CALL_RESULT', id: data.id, result: error ? null : resp ?? null },
          '*'
        );
      });
      return;
    }
  });

  // Báo cho trang biết extension đã có mặt (trang có thể chờ event này thay vì tự PING).
  window.postMessage({ source: FROM_EXT, type: 'READY' }, '*');
})();
