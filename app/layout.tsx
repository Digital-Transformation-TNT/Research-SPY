import type { Metadata } from 'next'
import Sidebar from '@/components/layout/Sidebar'
import './globals.css'

export const metadata: Metadata = {
  title: 'Research SPY — Công cụ research sản phẩm',
  description:
    'Tìm content quảng cáo đang chạy trên các nền tảng, và nghiên cứu từ khoá từ Google/Shopee/TikTok cho phòng test sản phẩm',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <div className="shell">
          <Sidebar />
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  )
}
