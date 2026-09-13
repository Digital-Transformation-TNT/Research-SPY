'use client'

import { useEffect, useState } from 'react'
import OpportunityWorkspace from '@/components/opportunity/OpportunityWorkspace'
import { SAN, type SanKey } from '@/lib/trendscout'

/** Nhớ sàn đang chọn qua lần tải lại. Khoá riêng, KHÔNG dùng chung `trend-scout-v1` của Hub. */
const STORAGE_KEY = 'oneshot-san-v1'

/**
 * One-shot AI — mục riêng trong nhóm "Tín hiệu thị trường" (tách khỏi Trend Signal Hub 13/09/2026).
 *
 * Vẫn là khung trò chuyện của mục Cơ hội ở chế độ `hub`: backend chèn Top bán chạy + Top doanh
 * số của SÀN ĐANG CHỌN vào đầu hội thoại (`backend/hub/signal/ask.py`). Nên ô Sàn phải nằm ngay
 * trên khung chat — bỏ nó đi thì AI không biết đọc Top của sàn nào.
 *
 * Cuộc trò chuyện vẫn cất ở khoá `hub-oneshot-v1` như lúc còn là tab của Hub, nên ai đang hỏi
 * dở trước khi tách mục vẫn thấy lại cuộc trò chuyện của mình.
 */
export default function OneShotAI() {
  const [san, setSan] = useState<SanKey>('shopee_vn')

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY)
      if (SAN.some((s) => s.key === saved)) setSan(saved as SanKey)
    } catch {
      // Bị chặn localStorage: dùng mặc định.
    }
  }, [])

  const pick = (key: SanKey) => {
    setSan(key)
    try {
      window.localStorage.setItem(STORAGE_KEY, key)
    } catch {
      // Không lưu được thì chỉ mất phần nhớ.
    }
  }

  const info = SAN.find((s) => s.key === san)!

  return (
    <>
      <div className="page-head opp-head">
        <div>
          <h1>One-shot AI</h1>
        </div>
      </div>

      <section className="panel ts-oneshot-san">
        <div className="field">
          <label>Sàn AI đọc Top sản phẩm</label>
          <div className="chips">
            {SAN.map((s) => (
              <button key={s.key} className="chip" data-on={s.key === san} onClick={() => pick(s.key)}>
                {s.label}
              </button>
            ))}
          </div>
        </div>
        <p className="ts-meta">
          AI đọc Top bán chạy và Top doanh số của <b>{info.label}</b> trước khi đề xuất, rồi hỏi ô tìm kiếm của sàn xem
          món đó có bán thật không.
        </p>
      </section>

      <div className="ts-ai">
        <OpportunityWorkspace hub={{ san, country: info.country }} />
      </div>
    </>
  )
}
