'use client'

import OpportunityWorkspace from '@/components/opportunity/OpportunityWorkspace'

/**
 * One-shot AI — mục riêng trong nhóm "Tín hiệu thị trường" (tách khỏi Trend Signal Hub 13/09/2026).
 *
 * KHÔNG CÓ Ô CHỌN SÀN (bỏ 14/09/2026). Backend tự đọc cả Shopee VN, Shopee PH và 1688, tự lọc
 * đúng phần dữ liệu liên quan tới câu hỏi rồi mới hỏi Gemini — xem `backend/hub/signal/ask.py`.
 * Bắt người dùng chọn sàn trước khi hỏi là bắt họ trả lời một câu mà chính họ đang đi hỏi.
 *
 * Cuộc trò chuyện vẫn cất ở khoá `hub-oneshot-v1` như lúc còn là tab của Hub, nên ai đang hỏi
 * dở vẫn thấy lại cuộc trò chuyện của mình.
 */
export default function OneShotAI() {
  return (
    <>
      <div className="page-head opp-head">
        <div>
          <h1>One-shot AI</h1>
        </div>
      </div>

      <div className="ts-ai">
        <OpportunityWorkspace hub />
      </div>
    </>
  )
}
