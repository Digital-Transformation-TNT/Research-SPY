'use client'

import { useState } from 'react'
import type { Answer, OpportunityItem, OpportunityStatus } from '@/lib/opportunity/types'

/**
 * MỘT lượt trả lời của trợ lý.
 *
 * Mỗi món là MỘT DÒNG và chỉ một dòng: tên món, nghĩa của nó, nhãn nói sàn có bán thật không,
 * và nhu cầu nó giải quyết. Không có phần mở ra.
 *
 * Từng có: bấm vào dòng thì bung ra chuỗi hệ quả, câu bằng chứng và danh sách cụm gợi ý của
 * sàn. Bỏ đi vì cả ba đều trả lời một câu hỏi mà `reply` phía trên đã trả lời rồi — vì sao
 * nhóm món này hợp với tình huống — chỉ là lặp lại mười lăm lần bằng chữ nhỏ. Bỏ chúng còn
 * cắt được hai trường khỏi mỗi lượt gọi Gemini; xem `demand_map.py`.
 *
 * Chỗ nối sang mục Keyword không mất theo: giờ chính CẢ DÒNG là cái nút đó.
 */

/**
 * `not_found` cố ý không có mục — nó KHÔNG dựng ra nhãn nào. Vắng nhãn đã là câu trả lời, xem
 * `Row`.
 */
const STATUS: Record<Exclude<OpportunityStatus, 'not_found'>, { label: string; hint: string }> = {
  real: {
    label: 'sàn có bán',
    hint: 'Ô tìm kiếm của sàn hoàn thiện cụm này thành nhiều biến thể của đúng món đó',
  },
  niche: {
    label: 'ngách hẹp',
    hint: 'Sàn có nhận nhưng gợi ý ít hoặc lệch — ngách hẹp, chưa chắc là xấu',
  },
  wrong: { label: 'đặt tên sai', hint: 'Gợi ý của sàn nói về một món khác hẳn' },
}

/**
 * Bao nhiêu món hiện ngay, phần còn lại nằm sau một dòng "xem thêm".
 *
 * Năm là con số đọc hết được trong một lần nhìn. Mười lăm thì không, và một danh sách không
 * ai đọc hết thì mười món cuối chỉ làm loãng năm món đầu.
 */
const PREVIEW = 5

function Row({ item, onPick }: { item: OpportunityItem; onPick: (term: string) => void }) {
  const status = item.status === 'not_found' ? null : STATUS[item.status]
  // Không có bằng chứng từ sàn thì không có cụm nào để mang sang mục Keyword, nên dòng đó chỉ
  // để đọc. Dựng nó thành thẻ `div` chứ không phải `button` đã tắt: một cái nút bấm không ăn
  // là thứ người ta thử đi thử lại.
  const usable = Boolean(item.searchTerm)
  const Tag = usable ? 'button' : 'div'

  return (
    <li className="ans-item" data-status={item.status}>
      <Tag
        className="ans-row"
        data-usable={usable}
        onClick={usable ? () => onPick(item.searchTerm) : undefined}
        title={usable ? `Mở mục Keyword với từ gốc “${item.searchTerm}”` : undefined}
      >
        <span className="ans-head">
          <span className="ans-name">{item.term}</span>
          {/* `not_found` KHÔNG có nhãn. Vắng nhãn đã là câu trả lời — ba nhãn kia đều nói sàn
              phản ứng thế nào, nên chỗ trống nghĩa là sàn không phản ứng gì. */}
          {status && (
            <span className="ans-status" title={status.hint}>
              {status.label}
            </span>
          )}
          {/* Dòng nghĩa. Quét thị trường Thái hay Philippines thì cả bảng về bằng chữ bản địa;
              không có dòng này thì không đọc nổi dòng nào. Thị trường Việt trả `gloss` rỗng
              nên nó tự biến mất. */}
          {item.gloss && <em className="ans-gloss">{item.gloss}</em>}
        </span>
        <span className="ans-pain">{item.pain}</span>
        <span className="ans-arrow" aria-hidden>
          →
        </span>
      </Tag>
    </li>
  )
}

export default function AnswerBlock({
  answer,
  onPick,
  onAsk,
}: {
  answer: Answer
  onPick: (term: string) => void
  onAsk: (question: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? answer.items : answer.items.slice(0, PREVIEW)
  const hidden = answer.items.length - shown.length

  return (
    <div className="ans">
      {answer.reply && <p className="ans-reply">{answer.reply}</p>}

      {/* Câu hiểu-bối-cảnh nằm DƯỚI lời đáp và nhỏ hơn nó: nó chỉ cần thiết đúng lúc mô hình
          hiểu sai, mà phần lớn lượt thì không. */}
      {answer.situation && <p className="ans-situation">{answer.situation}</p>}

      {answer.message && <div className="notice warn">{answer.message}</div>}

      {answer.items.length > 0 && (
        <div className="ans-card">
          <ul className="ans-list">
            {shown.map((item) => (
              <Row key={item.term} item={item} onPick={onPick} />
            ))}
          </ul>
          {hidden > 0 && (
            <button className="ans-more" onClick={() => setExpanded(true)}>
              Xem thêm {hidden} gợi ý
            </button>
          )}
        </div>
      )}

      {answer.followUps.length > 0 && (
        <div className="ans-next">
          {answer.followUps.map((question) => (
            <button key={question} onClick={() => onAsk(question)}>
              {question}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
