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
export default async function ResearchPage({
  searchParams,
}: {
  /** Promise từ Next 15 — `searchParams` không còn đọc đồng bộ được nữa. */
  searchParams: Promise<{ keyword?: string | string[] }>
}) {
  // Cầu nối từ tab Keyword: liên kết "Tìm sản phẩm" của mỗi dòng gọi `/ads?keyword=...`.
  //
  // Bước chuyển tiếp này là thứ đã THIẾU, và thiếu một cách lặng lẽ: `?keyword=` nằm ở URL
  // khung ngoài, còn ô tìm kiếm nằm trong iframe `/research/index.html` — một tài liệu khác,
  // không thấy query string của khung cha. Trang research vốn ĐÃ biết đọc `?kw=` (nó nhận từ
  // popup extension), nên chỉ cần chuyền tham số qua đúng ranh giới đó.
  //
  // Lấy phần tử đầu khi Next trả về mảng (`?keyword=a&keyword=b`) — ô tìm kiếm chỉ có một.
  const { keyword } = await searchParams
  const seed = (Array.isArray(keyword) ? keyword[0] : keyword)?.trim()
  const src = seed ? `/research/index.html?kw=${encodeURIComponent(seed)}` : '/research/index.html'

  return <iframe src={src} className="research-frame" title="Research đa sàn" />
}
