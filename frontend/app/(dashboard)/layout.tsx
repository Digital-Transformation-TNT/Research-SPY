import Sidebar from '@/components/layout/Sidebar'
import AnalyticsBoot from '@/components/layout/AnalyticsBoot'

/**
 * Khung có sidebar — bọc mọi trang công cụ (`/ads`, `/keywords`, `/image`, …).
 *
 * Tách riêng khỏi root layout để nhóm `(auth)` (đăng nhập, chờ duyệt) KHÔNG bị bọc sidebar.
 * Route group `(dashboard)` trong suốt với URL: `/ads` vẫn là `/ads`.
 *
 * `AnalyticsBoot` đứng ở đây (không phải trong từng trang) để nhịp đo cấp phiên chạy cho MỌI
 * tool, và session_start bắn đúng một lần cho cả lần mở app.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <AnalyticsBoot />
      <Sidebar />
      <main className="main">{children}</main>
    </div>
  )
}
