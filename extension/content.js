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

  /** Lỗi cầu nối, kèm cách sửa khi nhận ra được kiểu lỗi. `__workerError` để backend phân biệt
   *  "thợ nhận job nhưng không chạy được" với `null` (không có ai trả lời gì cả). */
  function callFailure(type, error) {
    let why = `Extension không chạy được ${type}: ${error}`;
    if (/context invalidated/i.test(error)) {
      // Sau mỗi lần bấm Reload ở chrome://extensions, content script trong các TAB ĐANG MỞ
      // vẫn trỏ vào bản extension vừa bị huỷ. Không có lỗi nào khác xuất hiện, và cả mẻ job
      // rơi sạch trong một giây — trông y như extension hỏng, trong khi việc phải làm chỉ là
      // F5. Đặt nhánh này TRƯỚC nhánh "establish connection" vì Chrome thỉnh thoảng gói cùng
      // một sự cố thành hai thông điệp khác nhau, và lời khuyên của nhánh kia (bấm Reload)
      // sẽ đẩy người dùng lặp lại đúng thao tác vừa gây ra lỗi.
      why += ' — vừa Reload extension nhưng TAB MÁY THỢ còn giữ bản cũ. Bấm F5 ở tab /worker là xong (không cần Reload lại).';
    } else if (/establish connection|Receiving end does not exist/i.test(error)) {
      why += ' — nhiều khả năng extension chưa nạp loại job này. Vào chrome://extensions bấm Reload rồi F5 tab Máy thợ.';
    } else if (/message port closed/i.test(error)) {
      why += ' — service worker bị Chrome kết liễu giữa job (MV3). Bấm lại; nếu lặp lại thì job này cần giữ nhịp bằng `withHeartbeat`.';
    }
    return { __workerError: true, ok: false, blocked: true, error: why, items: [] };
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
        // Hỏng thì trả object CÓ LÝ DO, không phải `null`.
        //
        // Bản trước trả `null` với lập luận "mọi chỗ gọi đều kiểm `!res || !res.ok` sẵn" — đúng
        // phần rơi vào nhánh lỗi, nhưng vứt mất `chrome.runtime.lastError`, thứ duy nhất nói
        // được vì sao. Và hai nguyên nhân hay gặp nhất lại cần hai cách sửa khác hẳn nhau:
        //
        //   "Could not establish connection…"  → extension chưa nạp loại job này, phải Reload
        //   "message port closed before…"      → MV3 giết service worker giữa job (job dài)
        //
        // Object dưới đây vẫn có `ok: false` nên mọi nhánh `!res || !res.ok` sẵn có chạy y như
        // cũ; `blocked` + `error` là đúng hình dạng mà `background.js` dùng cho nguồn bị chặn,
        // nên cửa sổ video hiện thẳng lý do thay vì "Không có video".
        window.postMessage(
          {
            source: FROM_EXT,
            type: 'CALL_RESULT',
            id: data.id,
            result: error ? callFailure(msg.type, error) : resp ?? null,
          },
          '*'
        );
      });
      return;
    }
  });

  // Báo cho trang biết extension đã có mặt (trang có thể chờ event này thay vì tự PING).
  window.postMessage({ source: FROM_EXT, type: 'READY' }, '*');
})();
