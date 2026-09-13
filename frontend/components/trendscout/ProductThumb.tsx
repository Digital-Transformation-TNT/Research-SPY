'use client'

import { useState } from 'react'

/**
 * Ảnh sản phẩm, lấy thẳng từ CDN của sàn — kho chỉ lưu link, không lưu ảnh.
 *
 * `referrerPolicy="no-referrer"` là BẮT BUỘC chứ không phải trang trí: CDN alicdn của 1688 trả
 * 403 cho mọi request mang Referer của tên miền khác, nên thiếu nó thì cả tab 1688 toàn ô vỡ.
 * Ảnh hỏng thì về ô trống cùng cỡ, để hàng không nhảy bố cục.
 */
export default function ProductThumb({ src, className = 'img-thumb' }: { src: string | null; className?: string }) {
  const [broken, setBroken] = useState(false)
  if (!src || broken) return <span className={`${className} ts-thumb-empty`} aria-hidden />
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={className}
      src={src}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setBroken(true)}
    />
  )
}
