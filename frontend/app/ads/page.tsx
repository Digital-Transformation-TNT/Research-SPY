import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Research — Research SPY',
}

/**
 * Trang Research.
 *
 * Đây là trang research đa sàn vốn chạy trong extension (`results.html`), đã chuyển hẳn vào
 * webtool. Nó được nhúng NGUYÊN VẸN từ `public/research/index.html` chứ không viết lại thành
 * component React, và đó là một quyết định có chủ đích:
 *
 *  - GIAO DIỆN KHÔNG ĐƯỢC LỆCH. Yêu cầu là giữ y như bản đang chạy. Viết lại 1.300 dòng thao
 *    tác DOM thành React thì chắc chắn lệch ở đâu đó, và lệch kiểu khó thấy.
 *  - CSS KHÔNG ĐƯỢC ĐỤNG NHAU. Trang đó khai `body`, `table`, `input`, `.status`, `.chip`…
 *    Nhiều tên trùng với `styles/` của webtool. Trong iframe thì hai bộ CSS không thấy nhau,
 *    khỏi phải đổi tên hàng trăm lớp.
 *
 * ĐÁNH ĐỔI phải biết: iframe là một tài liệu riêng, nên `extension/manifest.json` phải khai
 * `all_frames: true`, nếu không content script chỉ chạy ở khung ngoài và cầu postMessage
 * không có ai nghe — trang sẽ báo "chưa cài extension" dù đã cài.
 */
export default function ResearchPage() {
  return <iframe src="/research/index.html" className="research-frame" title="Research đa sàn" />
}
