'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { TrendsOption } from '@/lib/keywords/trendsOptions'

/**
 * Ô chọn một-trong-nhiều, có ô tìm khi danh sách dài.
 *
 * Tự dựng thay vì dùng `<select>` vì danh sách quốc gia có hơn hai trăm mục: `<select>` gốc
 * chỉ nhảy theo ký tự đầu, nên tìm "Việt Nam" phải cuộn qua cả trăm dòng, và gõ "viet" thì
 * nó hiểu thành bốn lần nhảy tới bốn chữ cái khác nhau.
 *
 * Dùng chung cho cả ba ô để chúng trông và hành xử như nhau; ô ngắn thì tắt `searchable`.
 */
export default function Dropdown({
  value,
  options,
  onChange,
  searchable = false,
  searchPlaceholder = 'Tìm…',
  disabled = false,
}: {
  value: string
  options: TrendsOption[]
  onChange: (value: string) => void
  searchable?: boolean
  searchPlaceholder?: string
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const current = options.find((o) => o.value === value)

  const filtered = useMemo(() => {
    const q = fold(query)
    if (!q) return options
    return options.filter((o) => fold(o.label).includes(q) || o.value.toLowerCase().includes(q))
  }, [options, query])

  // Bấm ra ngoài thì đóng. Dùng `mousedown` chứ không phải `click`: `click` bắn sau khi phần
  // tử bên trong đã xử lý xong, nên chọn một mục sẽ vừa chọn vừa bị coi là bấm ra ngoài.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // Mở ra là quay về trạng thái sạch, con trỏ đặt sẵn ở mục đang chọn.
  useEffect(() => {
    if (!open) return
    setQuery('')
    setActive(Math.max(0, options.findIndex((o) => o.value === value)))
    searchRef.current?.focus()
  }, [open, options, value])

  // Gõ tìm thì danh sách ngắn lại, con trỏ cũ có thể trỏ ra ngoài mảng mới.
  useEffect(() => setActive(0), [query])

  useLayoutEffect(() => {
    if (!open) return
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [open, active, filtered])

  const commit = (next: string) => {
    onChange(next)
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') return setOpen(false)
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!filtered.length) return
      const step = e.key === 'ArrowDown' ? 1 : -1
      return setActive((i) => (i + step + filtered.length) % filtered.length)
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      const picked = filtered[active]
      if (picked) commit(picked.value)
    }
  }

  return (
    <div className="dropdown" ref={rootRef}>
      <button
        type="button"
        className="dd-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{current?.label ?? value}</span>
        <i aria-hidden>▾</i>
      </button>

      {open && (
        <div className="dd-panel" onKeyDown={onKeyDown}>
          {searchable && (
            <input
              ref={searchRef}
              className="dd-search"
              type="text"
              placeholder={searchPlaceholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          )}
          <div className="dd-list" role="listbox" ref={listRef}>
            {filtered.map((option, i) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                data-active={i === active}
                data-on={option.value === value}
                className="dd-option"
                onMouseEnter={() => setActive(i)}
                onClick={() => commit(option.value)}
              >
                {option.value === value && <span className="dd-tick">✓</span>}
                {option.label}
              </button>
            ))}
            {filtered.length === 0 && <div className="dd-empty">Không có kết quả</div>}
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Bỏ dấu và về chữ thường, để gõ "viet" ra được "Việt Nam".
 *
 * Người dùng gõ tên nước trên bàn phím không dấu là chuyện thường, và so chuỗi có dấu sẽ
 * không khớp gì cả — đúng cái làm ô tìm trở nên vô dụng với chính thị trường mặc định.
 */
function fold(text: string): string {
  return text
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '') // NFD tách dấu ra thành ký tự riêng; đây là bước xoá chúng
    .replace(/đ/gi, 'd') // chữ đ không phải chữ d kèm dấu, nên NFD không đụng tới nó
    .toLowerCase()
    .trim()
}
