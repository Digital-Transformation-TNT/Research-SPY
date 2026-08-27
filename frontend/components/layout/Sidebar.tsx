'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'

/** SVG nội tuyến để trang tự chứa — không phụ thuộc thư viện icon, không gọi ra ngoài. */
const icons = {
  admin: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2 4 5v6c0 5 3.5 8.5 8 11 4.5-2.5 8-6 8-11V5z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  ),
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
  image: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8" />
      <path d="M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8" />
      <path d="M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16" />
      <path d="M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
  guide: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5z" />
      <path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5z" />
    </svg>
  ),
  signal: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4.9 19.1a10 10 0 0 1 0-14.2" />
      <path d="M7.8 16.2a6 6 0 0 1 0-8.4" />
      <path d="M16.2 7.8a6 6 0 0 1 0 8.4" />
      <path d="M19.1 4.9a10 10 0 0 1 0 14.2" />
      <circle cx="12" cy="12" r="2" />
    </svg>
  ),
  idea: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18h6" />
      <path d="M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.5 10.9c.4.3.5.7.5 1.1v1h6v-1c0-.4.1-.8.5-1.1A6 6 0 0 0 12 3z" />
    </svg>
  ),
}

type NavItem = { href: string; label: string; hint: string; icon: keyof typeof icons }

const GROUPS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: 'Research',
    items: [
      {
        href: '/keywords',
        label: 'Keyword',
        hint: 'Khám phá và mở rộng từ khoá đa nguồn',
        icon: 'keyword',
      },
      {
        href: '/image',
        label: 'Image Search',
        hint: 'Tìm tên sản phẩm và nơi đang bán từ ảnh',
        icon: 'image',
      },
      {
        href: '/ads',
        label: 'Sản phẩm',
        hint: 'Top sản phẩm đa sàn theo từ khoá — kèm Facebook Ads và video theo sản phẩm',
        icon: 'ads',
      },
      {
        href: '/opportunity',
        label: 'Cơ hội',
        hint: 'Khám phá món nên bán cùng trợ lý AI',
        icon: 'idea',
      },
    ],
  },
  // Mục độc lập, có database riêng (`backend/hub_data.db`) và không dùng chung gì với nhóm
  // Research ở trên, nên nó là một nhóm riêng chứ không nằm lẫn vào đó.
  {
    label: 'Tín hiệu thị trường',
    items: [
      {
        href: '/trend-signal',
        label: 'Trend Signal Hub',
        hint: 'Tín hiệu hôm nay từ Etsy, Amazon và Google Trends',
        icon: 'signal',
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

/** Nhóm chỉ hiện với admin — trang quản lý user + thống kê. `/admin` là route Next thật. */
const ADMIN_GROUP: { label: string; items: NavItem[] } = {
  label: 'Quản trị',
  items: [
    {
      href: '/admin',
      label: 'Quản trị',
      hint: 'Duyệt & quản lý người dùng, xem thống kê sử dụng',
      icon: 'admin',
    },
  ],
}

export default function Sidebar() {
  const pathname = usePathname()
  // Auth đọc từ localStorage — chỉ có ở client, nên chờ mounted rồi mới quyết định hiển thị gì
  // (tránh hydration mismatch: server không biết localStorage). Trước mounted: coi như chưa rõ.
  const [mounted, setMounted] = useState(false)
  const [display, setDisplay] = useState('')
  //: Có phiên đăng nhập hay không — TÁCH khỏi `display`, và đó là cả vấn đề. Xem chỗ render.
  const [signedIn, setSignedIn] = useState(false)
  const [role, setRole] = useState('user')

  useEffect(() => {
    setMounted(true)
    const token = localStorage.getItem('rs_token')
    const email = localStorage.getItem('rs_email') || ''
    const r = localStorage.getItem('rs_role') || 'user'
    // Auth gate cho TOÀN app: chưa đăng nhập (không token và không email) → về trang login.
    // Sidebar chỉ render trong layout bọc /ads,/keywords,... nên không đụng trang /login,/admin
    // (chúng là HTML tĩnh riêng) → không sợ vòng lặp redirect.
    if (!token && !email) {
      window.location.replace('/login')
      return
    }
    // Tên hiển thị = "Tên · Vị trí · BU" (ghép sẵn ở backend, lưu rs_display). Thiếu thì rơi về
    // email, rồi tới `rs_username` — key của trang đăng nhập CŨ, bản username (`git show e29977f`).
    // Phiên tạo trước khi chuyển sang đăng nhập bằng email CHỈ có token + rs_username, nên nếu
    // không đọc key này thì cả chân sidebar biến mất mà không có lấy một dòng báo. Đo 2026-08-27.
    setDisplay(localStorage.getItem('rs_display') || email || localStorage.getItem('rs_username') || '')
    setSignedIn(true)
    setRole(r)
  }, [])

  const logout = () => {
    ;['rs_token', 'rs_email', 'rs_role', 'rs_user_id', 'rs_display', 'rs_username', 'rs_loginAt'].forEach((k) =>
      localStorage.removeItem(k),
    )
    window.location.replace('/login')
  }

  // Admin thấy thêm nhóm Quản trị. Chỉ ghép sau khi mounted để không nháy nhóm này với user thường.
  const groups = mounted && role === 'admin' ? [...GROUPS, ADMIN_GROUP] : GROUPS

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
        {groups.map((group) => (
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

      {/* Chân sidebar: tên (Tên · Vị trí · BU) + đăng xuất.
          ĐIỀU KIỆN LÀ `signedIn`, KHÔNG PHẢI `display` — và đây chính là chỗ đã hỏng. Bám vào
          `display` nghĩa là một phiên thiếu tên sẽ nuốt luôn nút Đăng xuất, tức là giấu đúng
          cái lối thoát duy nhất khỏi trạng thái ấy. Thà hiện một cái tên chưa rõ còn hơn hiện
          một khoảng trống không giải thích được. */}
      {mounted && signedIn ? (
        <div className="sidebar-user">
          <span className="user-name" title={display || 'Phiên đăng nhập cũ — chưa có tên hiển thị'}>
            <b>{display || 'Chưa rõ tài khoản'}</b>
            <small>
              {display ? (role === 'admin' ? 'Quản trị viên' : 'Người dùng') : 'Đăng nhập lại để hiện tên'}
            </small>
          </span>
          <button type="button" className="user-logout" onClick={logout} title="Đăng xuất">
            Đăng xuất
          </button>
        </div>
      ) : null}
    </aside>
  )
}
