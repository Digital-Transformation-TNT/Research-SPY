'use client'

import type { BridgeResult, BridgeVerdict, SeedCandidate } from '@/lib/keywords/types'

export type BridgeState = { loading: boolean; result?: BridgeResult; message?: string }

/**
 * Nhãn ngắn cho từng phán quyết, và cụm giải thích khi rê chuột.
 *
 * `unknown` cố ý KHÔNG có nhãn: nó nghĩa là chưa đối chiếu được, và vẽ một huy hiệu xám ghi
 * "chưa rõ" lên mọi dòng của một thị trường không có sàn nào chỉ là thêm nhiễu vào chỗ vốn
 * không có thông tin.
 */
const VERDICT: Record<Exclude<BridgeVerdict, 'unknown'>, { label: string; hint: string }> = {
  same: { label: 'đúng ngành hàng', hint: 'Sàn ở thị trường đó dùng cụm này cho đúng mặt hàng bạn hỏi' },
  subtype: { label: 'một loại con', hint: 'Một kiểu dáng hoặc dòng sản phẩm riêng trong ngành hàng — vẫn chọn được nếu bạn định bán đúng loại đó' },
  broader: { label: 'rộng hơn', hint: 'Danh mục bao trùm ngành hàng này nhưng không riêng nó — kết quả sẽ lẫn nhiều hàng khác' },
  brand: { label: 'tên hãng', hint: 'Đây là tên một thương hiệu, không phải tên ngành hàng' },
  different: { label: 'hàng khác', hint: 'Sàn dùng cụm này cho một mặt hàng khác hẳn' },
  misspelling: { label: 'viết sai', hint: 'Nhiều khả năng là cách viết sai của một cụm khác' },
}

/**
 * Một dòng đề cử.
 *
 * BẢN ĐẦU KHÔNG CÓ CỘT BẰNG CHỨNG NÀO, và đó từng là quyết định đúng: khi ấy thứ duy nhất đo
 * được là số gợi ý Amazon, mà con số đó chạm trần ở mọi cụm hợp lệ nên nó không phân biệt được
 * gì. Đo 2026-08-12 còn cho thấy nó gần như không bao giờ khác 0 — kể cả với cụm bịa.
 *
 * Thứ thay nó không phải một con số mà là một câu ĐỌC ĐƯỢC, dựng từ chính gợi ý của sàn ở thị
 * trường đó. Với thị trường Trung Quốc thì đây là khác biệt giữa dùng được và không: đo trên
 * sáu ngành hàng, ba đề cử là MẶT HÀNG KHÁC HẲN (`彩妆蛋` là mút tán nền chứ không phải son,
 * `耳塞` là nút bịt tai chứ không phải tai nghe) mà người dùng không đọc được chữ Hán thì không
 * có cách nào nhận ra.
 */
function CandidateRow({ item, onPick }: { item: SeedCandidate; onPick: (term: string) => void }) {
  const verdict = item.verdict === 'unknown' ? null : VERDICT[item.verdict]
  // Bằng chứng thô đi vào tooltip chứ không lên mặt bảng: nó bằng tiếng bản địa, nên với người
  // đọc nó là một khối chữ lạ. `reason` mới là thứ đọc được — bằng chứng ở đây để KIỂM LẠI.
  const evidence = item.evidence.length ? `\n\nSàn gợi ý: ${item.evidence.join(' · ')}` : ''

  return (
    <button
      className="bridge-row"
      data-verdict={item.verdict}
      onClick={() => onPick(item.term)}
      title={`Dùng “${item.term}” làm từ gốc${verdict ? `\n\n${verdict.hint}` : ''}${evidence}`}
    >
      <span className="bridge-term">{item.term}</span>
      {verdict && <span className="bridge-verdict">{verdict.label}</span>}
      <span className="bridge-note">{item.reason || item.note}</span>
    </button>
  )
}

export default function SeedBridge({
  state,
  countryLabel,
  onPick,
  onClose,
}: {
  state: BridgeState
  countryLabel: string
  onPick: (term: string) => void
  onClose: () => void
}) {
  const candidates = state.result?.candidates ?? []
  const message = state.message ?? state.result?.message

  return (
    <div className="bridge">
      <div className="bridge-head">
        <strong>Người {countryLabel} gọi ngành hàng này là gì</strong>
        <button className="bridge-close" onClick={onClose} title="Đóng">
          ×
        </button>
      </div>

      {state.loading && (
        <p className="muted small">
          <span className="spinner" /> Loading…
        </p>
      )}

      {!state.loading && candidates.length > 0 && (
        <div className="bridge-list">
          {candidates.map((item) => (
            <CandidateRow key={item.term} item={item} onPick={onPick} />
          ))}
        </div>
      )}

      {message && <p className="muted small">{message}</p>}
    </div>
  )
}
