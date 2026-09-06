import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Trend Signal Hub — Research SPY',
}

/**
 * Trang Trend Signal Hub — ba mục: ① Tín hiệu Google Trends · ② Top 10 chính & nổi bật ·
 * ③ One-shot AI (đã gộp chatbot của mục "Cơ hội" cũ).
 *
 * Vẫn nhúng bằng iframe đúng như trang Sản phẩm (`app/ads/page.tsx`) và vì đúng lý do đó:
 * file HTML tự chứa cả CSS lẫn JS, khai `body`, `table`, `.card`… trùng tên với `styles/`
 * của webtool. Viết lại thành React thì phải đổi tên hàng trăm lớp CSS mà không được gì.
 *
 * Dữ liệu đi qua `/api/hub/signal/*` (xem `backend/hub/routes.py` và `backend/hub/signal/`).
 *
 * ĐÃ SỬA MỘT ĐIỀU TỪNG PHẢI CẢNH BÁO Ở ĐÂY: bản cũ khi backend không trả lời thì KHÔNG báo
 * lỗi — nó rơi về bộ dữ liệu mẫu nhúng cứng và hiện đầy số trông như thật. Trang mới không
 * có dữ liệu mẫu; mục nào không đọc được thì nói ra là nó không đọc được.
 */
export default function TrendSignalPage() {
  return <iframe src="/hub/trend-signal-hub.html" className="research-frame" title="Trend Signal Hub" />
}
