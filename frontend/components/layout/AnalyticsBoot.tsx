'use client'

import { useEffect } from 'react'
import { usePathname } from 'next/navigation'

import { sessionStartEvent, sessionEndEvent, pageView } from '@/lib/analytics'

/**
 * Nhịp đo cấp PHIÊN — gắn một lần ở khung dashboard, không hiện gì (`return null`).
 *
 *   - session_start: khi khung dựng (một phiên = một lần mở app shell).
 *   - page_view: mỗi lần đổi route trong SPA (theo `usePathname`).
 *   - session_end: khi rời trang (`pagehide`) — kèm thời lượng + tool đã dùng.
 *
 * Không đo cấp tool ở đây; việc đó nằm trong từng tool (keyword_search, product_click…).
 * Mọi lời gọi đều fire-and-forget, hỏng cũng không kéo theo giao diện.
 */
export default function AnalyticsBoot() {
  const pathname = usePathname()

  useEffect(() => {
    sessionStartEvent()
    // `pagehide` bắn khi đóng tab / điều hướng đi — đáng tin hơn `beforeunload` trên mobile.
    // `sessionEndEvent` tự chặn bắn trùng, nên gọi ở đây một lần là đủ.
    const onHide = () => sessionEndEvent(window.location.pathname)
    window.addEventListener('pagehide', onHide)
    return () => window.removeEventListener('pagehide', onHide)
  }, [])

  useEffect(() => {
    if (pathname) pageView(pathname)
  }, [pathname])

  return null
}
