import type { Metadata } from 'next'

import TrendScout from '@/components/trendscout/TrendScout'

export const metadata: Metadata = {
  title: 'Trend Signal Hub — Research SPY',
}

/**
 * Trend Signal Hub — Toplist · Khám phá & Tùy chỉnh · One-shot AI.
 *
 * ĐỔI 13/09/2026: bỏ bản nhúng iframe `public/hub/trend-signal-hub.html` (Google Trends + Top 10)
 * và dựng lại bằng React như Keyword/Image Search. Lý do nhúng iframe trước đây là file HTML tự
 * mang CSS trùng tên với `styles/`; nay trang dùng thẳng khung của webtool nên lý do đó hết.
 * Google Trends bỏ khỏi giao diện; dữ liệu Trends vẫn đóng băng trong kho.
 *
 * Dữ liệu: `/api/hub/scout/*` (`backend/hub/signal/scout.py`) và `/api/hub/signal/ask`.
 * Không hỏi backend lúc dựng trang, nên trang vẫn mở được khi backend chưa chạy.
 */
export default function TrendSignalPage() {
  return <TrendScout />
}
