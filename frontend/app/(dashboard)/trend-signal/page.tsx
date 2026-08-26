import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Trend Signal Hub — Research SPY',
}

/**
 * Trang Trend Signal Hub.
 *
 * Mang nguyên từ dự án Product Opportunity Hub. Nhúng bằng iframe đúng như trang Research
 * (`app/ads/page.tsx`) và vì đúng những lý do đó: file gốc là một trang HTML gần 12.000 dòng
 * tự chứa cả CSS lẫn JS, khai `body`, `table`, `.card`… trùng tên với `styles/` của webtool.
 * Viết lại thành React thì vừa chắc chắn lệch giao diện, vừa phải đổi tên hàng trăm lớp CSS.
 *
 * Dữ liệu đi qua `/api/hub/*` (xem `backend/hub/routes.py`). Trang tự chèn `/hub` vào giữa
 * đường dẫn, xem khối `hubUrl()` trong file HTML.
 *
 * CẦN BIẾT: khi backend không trả lời, trang này KHÔNG báo lỗi — nó rơi về bộ dữ liệu mẫu
 * nhúng cứng và hiện đầy số liệu trông như thật. Nên nếu số liệu trông lạ, việc đầu tiên
 * phải làm là mở `/api/hub/health` xem backend có sống không, đừng đoán qua giao diện.
 */
export default function TrendSignalPage() {
  return <iframe src="/hub/trend-signal-hub.html" className="research-frame" title="Trend Signal Hub" />
}
