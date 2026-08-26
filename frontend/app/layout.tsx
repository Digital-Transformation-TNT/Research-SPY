import type { Metadata } from 'next'
import { Space_Grotesk, Be_Vietnam_Pro, JetBrains_Mono } from 'next/font/google'
import './globals.css'

/**
 * Bộ chữ của Research SPY — nạp qua next/font (Google Fonts được TỰ HOST khi build, không có
 * request runtime ra ngoài, không FOUT). Mỗi vai một họ, phơi ra bằng CSS variable để dùng ở
 * mọi nơi mà không phải nhớ tên họ chữ:
 *
 *   --font-display  Space Grotesk  — tiêu đề, con số lớn (grotesque kỹ thuật, nét riêng)
 *   --font-body     Be Vietnam Pro  — chữ giao diện, thiết kế riêng cho tiếng Việt (chuẩn dấu)
 *   --font-mono     JetBrains Mono  — số liệu trong bảng/thẻ (chữ số đều cột)
 */
const display = Space_Grotesk({ subsets: ['latin', 'latin-ext', 'vietnamese'], weight: ['500', '600', '700'], variable: '--font-display', display: 'swap' })
const body = Be_Vietnam_Pro({ subsets: ['latin', 'latin-ext', 'vietnamese'], weight: ['400', '500', '600', '700'], variable: '--font-body', display: 'swap' })
const mono = JetBrains_Mono({ subsets: ['latin', 'latin-ext'], weight: ['400', '500', '600'], variable: '--font-mono', display: 'swap' })

export const metadata: Metadata = {
  title: 'Research SPY — Công cụ research sản phẩm',
  description:
    'Tìm content quảng cáo đang chạy trên các nền tảng, và nghiên cứu từ khoá từ Google/Shopee/TikTok cho phòng test sản phẩm',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  )
}
