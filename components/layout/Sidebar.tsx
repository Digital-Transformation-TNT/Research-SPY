'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

/** SVG nội tuyến để trang tự chứa — không phụ thuộc thư viện icon, không gọi ra ngoài. */
const icons = {
  ads: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="14" rx="2" />
      <path d="m10 9 5 3-5 3z" />
    </svg>
  ),
  keyword: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  ),
  guide: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5z" />
      <path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5z" />
    </svg>
  ),
}

type NavItem = { href: string; label: string; hint: string; icon: keyof typeof icons }

const GROUPS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: 'Research',
    items: [
      {
        href: '/ads',
        label: 'Quảng cáo',
        hint: 'Content quảng cáo đang chạy từ các nền tảng',
        icon: 'ads',
      },
      {
        href: '/keywords',
        label: 'Từ khoá',
        hint: 'Mở rộng từ khoá từ Google + Shopee + TikTok',
        icon: 'keyword',
      },
    ],
  },
  {
    label: 'Trợ giúp',
    items: [
      {
        href: '/guide',
        label: 'Hướng dẫn',
        hint: 'Quy trình dùng và cách đọc số liệu',
        icon: 'guide',
      },
    ],
  },
]

export default function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="sidebar">
      <Link href="/ads" className="sidebar-brand">
        <span className="mark">RS</span>
        <span className="brand-text">
          <b>Research SPY</b>
          <small>Công cụ research sản phẩm</small>
        </span>
      </Link>

      <nav className="sidebar-nav">
        {GROUPS.map((group) => (
          <div className="nav-group" key={group.label}>
            <span className="nav-label">{group.label}</span>
            {group.items.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
              return (
                <Link key={item.href} href={item.href} className="nav-item" data-active={active} title={item.hint}>
                  <span className="nav-icon">{icons[item.icon]}</span>
                  <span className="nav-text">
                    {item.label}
                    <small>{item.hint}</small>
                  </span>
                </Link>
              )
            })}
          </div>
        ))}
      </nav>

      <div className="sidebar-foot">
        Dữ liệu lấy trực tiếp từ nền tảng công khai, không lưu video vào máy chủ.
      </div>
    </aside>
  )
}
