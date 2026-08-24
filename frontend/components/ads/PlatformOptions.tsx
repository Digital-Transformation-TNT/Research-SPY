'use client'

import { useEffect, useMemo, useState } from 'react'
import type { PlatformOption } from '@/lib/ads/platform'
import type { PlatformDescriptor } from '@/lib/ads/platforms'

/**
 * Vẽ các ô điều khiển riêng của một nguồn quảng cáo.
 *
 * Giao diện KHÔNG biết Facebook hay TikTok có tuỳ chọn gì — nó đọc mô tả `options` mà nguồn
 * tự khai báo trong `lib/ads/platforms/*` rồi dựng ô tương ứng. Thêm một nguồn mới có tuỳ
 * chọn riêng thì ô của nó tự xuất hiện, không phải sửa file này.
 *
 * Hai loại ô:
 *  - `choice`: danh sách cố định, biết trước (ví dụ khoảng thời gian 7/30/180)
 *  - `remote`: danh sách lấy động từ nguồn (ví dụ 258 ngành hàng của TikTok)
 */

type Values = Record<string, string>

function ChoiceField({
  option,
  value,
  onChange,
}: {
  option: PlatformOption
  value: string
  onChange: (next: string) => void
}) {
  return (
    <div className="field">
      <label title={option.hint}>{option.label}</label>
      <div className="chips">
        {(option.choices ?? []).map((choice) => (
          <button
            key={choice.value}
            className="chip"
            data-on={value === choice.value}
            title={choice.hint}
            onClick={() => onChange(choice.value)}
          >
            {choice.label}
          </button>
        ))}
      </div>
    </div>
  )
}

type RemoteOption = { value: string; label: string; group?: string }
type FiltersResponse = { groups?: Array<{ key: string; options: RemoteOption[] }>; error?: string }

/**
 * Một lần gọi `/api/ads/filters` cho mỗi nguồn, dùng chung cho mọi ô `remote` của nguồn đó.
 *
 * Backend trả TẤT CẢ nhóm bộ lọc trong cùng một response, còn `fetch_filters` phía nguồn thì
 * bị giới hạn tần suất. Để mỗi ô tự gọi thì hai ô của cùng một nguồn sẽ cùng trượt cache khi
 * mở trang, và lần gọi thứ hai phải xếp hàng chờ hết một suất rate-limit — chậm thêm gần
 * mười giây mà không thu về thêm dữ liệu nào.
 */
const inFlight = new Map<string, Promise<FiltersResponse>>()

function loadFilters(platformId: string): Promise<FiltersResponse> {
  const shared = inFlight.get(platformId)
  if (shared) return shared

  const pending = fetch(`/api/ads/filters?platform=${encodeURIComponent(platformId)}`)
    .then((r) => r.json() as Promise<FiltersResponse>)
    .then((data) => {
      // Một lần hỏng không được đóng băng vĩnh viễn: quên đi để lần sau còn thử lại.
      if (data.error) inFlight.delete(platformId)
      return data
    })
  pending.catch(() => inFlight.delete(platformId))

  inFlight.set(platformId, pending)
  return pending
}

function RemoteField({
  platformId,
  option,
  value,
  onChange,
}: {
  platformId: string
  option: PlatformOption
  value: string
  onChange: (next: string) => void
}) {
  const [options, setOptions] = useState<RemoteOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    loadFilters(platformId)
      .then((data) => {
        if (cancelled) return
        if (data.error) setError(data.error)
        const group = data.groups?.find((g) => g.key === option.remoteGroup)
        setOptions(group?.options ?? [])
      })
      .catch((e) => !cancelled && setError((e as Error).message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [platformId, option.remoteGroup])

  // Nguồn đã gom nhóm sẵn; ở đây chỉ dựng lại optgroup theo đúng thứ tự nhận được.
  const grouped = useMemo(() => {
    const map = new Map<string, RemoteOption[]>()
    for (const item of options) {
      const key = item.group ?? ''
      map.set(key, [...(map.get(key) ?? []), item])
    }
    return [...map.entries()]
  }, [options])

  return (
    <div className="field">
      <label title={option.hint}>{option.label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading || options.length === 0}
        style={{ maxWidth: 250 }}
      >
        <option value="">
          {loading ? 'đang tải…' : options.length === 0 ? 'không tải được' : `Tất cả ${option.label.toLowerCase()}`}
        </option>
        {grouped.map(([groupLabel, items]) =>
          groupLabel ? (
            <optgroup key={groupLabel} label={groupLabel}>
              {items.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </optgroup>
          ) : (
            items.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))
          ),
        )}
      </select>
      {error && <span className="small">Không tải được: {error}</span>}
    </div>
  )
}

export default function PlatformOptions({
  platform,
  values,
  onChange,
}: {
  platform: PlatformDescriptor
  values: Values
  onChange: (key: string, value: string) => void
}) {
  return (
    <>
      {platform.options.map((option) => {
        const value = values[option.key] ?? option.defaultValue ?? ''
        return option.kind === 'remote' ? (
          <RemoteField
            key={option.key}
            platformId={platform.id}
            option={option}
            value={value}
            onChange={(next) => onChange(option.key, next)}
          />
        ) : (
          <ChoiceField
            key={option.key}
            option={option}
            value={value}
            onChange={(next) => onChange(option.key, next)}
          />
        )
      })}
    </>
  )
}

/** Giá trị mặc định của mọi tuỳ chọn, dùng để khởi tạo state. */
export function defaultOptionValues(platforms: PlatformDescriptor[]): Record<string, Values> {
  const out: Record<string, Values> = {}
  for (const platform of platforms) {
    out[platform.id] = Object.fromEntries(
      platform.options.filter((o) => o.defaultValue).map((o) => [o.key, o.defaultValue!]),
    )
  }
  return out
}
