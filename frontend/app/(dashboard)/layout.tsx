import Sidebar from '@/components/layout/Sidebar'

/**
 * Khung có sidebar — bọc mọi trang công cụ (`/ads`, `/keywords`, `/image`, …).
 *
 * Tách riêng khỏi root layout để nhóm `(auth)` (đăng nhập, chờ duyệt) KHÔNG bị bọc sidebar.
 * Route group `(dashboard)` trong suốt với URL: `/ads` vẫn là `/ads`.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="shell">
      <Sidebar />
      <main className="main">{children}</main>
    </div>
  )
}
