'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import Dropdown from '@/components/keywords/Dropdown'
import AnswerBlock from './AnswerBlock'
import { DEFAULT_COUNTRY, countryOptions } from '@/lib/keywords/trendsOptions'
import { browserPostJson } from '@/lib/api'
import type { Answer, AskTurn, Turn } from '@/lib/opportunity/types'

/**
 * Màn hình MỤC CƠ HỘI — một cuộc trò chuyện về việc nên bán gì.
 *
 * Trước đây là hai tab: một ô "bối cảnh" và một bảng thương hiệu đang tăng. Bảng thương hiệu
 * đã gỡ (nó đứng trên Google Trends, thứ bị chặn quá thường xuyên để làm một tính năng), và
 * ô "bối cảnh" thành ô nhập tự do: người bán không nghĩ bằng cụm hai chữ, họ nghĩ bằng câu —
 * "shop mình bán đồ mẹ và bé, sắp tựu trường nên nhập gì". Bắt họ nén câu đó lại thành "tựu
 * trường" là vứt đi đúng những chi tiết làm câu trả lời khác đi.
 *
 * Lịch sử trò chuyện được gửi lên theo mỗi lượt, nên câu hỏi tiếp theo không phải nhắc lại
 * bối cảnh. Nó SỐNG QUA LẦN TẢI LẠI, xem `STORAGE_KEY`.
 */

/**
 * Nơi cất cuộc trò chuyện đang mở. Cùng cách làm với `imagesearch-sources` ở mục Tìm bằng ảnh.
 *
 * Phải có, vì một lượt hỏi ở đây tốn tới mười giây và vài lượt gọi ra ngoài. Mất nó chỉ vì lỡ
 * bấm F5 — hay vì bấm "Đào sâu" sang mục Keyword rồi bấm Back — là mất cả một buổi tra cứu,
 * và người dùng không có cách nào lấy lại ngoài việc hỏi lại từ đầu.
 *
 * Hậu tố `v1` là hình dạng của `Turn`. Đổi hình dạng thì nâng số, đừng cố đọc bản ghi cũ.
 *
 * Chỉ giữ ĐÚNG MỘT cuộc trò chuyện. "Hội thoại mới" xoá nó đi và bắt đầu lại — không có danh
 * sách hội thoại cũ, vì mỗi lượt ở đây trả lời một tình huống bán hàng cụ thể chứ không phải
 * một chủ đề người ta quay lại nhiều lần.
 */
const STORAGE_KEY = 'opportunity-chat-v1'

/** Trần số lượt được ghi xuống, để một buổi hỏi dài không ăn hết hạn mức localStorage. */
const STORED_TURNS = 20

/**
 * Đọc bản ghi từ localStorage về đúng hình dạng `Turn`.
 *
 * Không tin gì ở đó cả. Bản ghi có thể do một phiên bản code cũ ghi ra, hoặc do người dùng sửa
 * tay, và một `answer.followUps` vắng mặt sẽ ném `Cannot read properties of undefined` ngay
 * giữa lúc dựng trang — nghĩa là một màn hình trắng, chứ không phải một lượt hiển thị lỗi.
 */
function reviveTurns(value: unknown): Turn[] {
  if (!Array.isArray(value)) return []

  const out: Turn[] = []
  for (const entry of value) {
    if (!entry || typeof entry !== 'object') continue
    const turn = entry as { role?: unknown; text?: unknown; answer?: unknown }

    if (turn.role === 'user' && typeof turn.text === 'string' && turn.text) {
      out.push({ role: 'user', text: turn.text })
      continue
    }
    if (turn.role === 'assistant' && turn.answer && typeof turn.answer === 'object') {
      const answer = turn.answer as Partial<Answer>
      out.push({
        role: 'assistant',
        answer: {
          ...(answer as Answer),
          reply: typeof answer.reply === 'string' ? answer.reply : '',
          situation: typeof answer.situation === 'string' ? answer.situation : '',
          items: Array.isArray(answer.items) ? answer.items : [],
          followUps: Array.isArray(answer.followUps) ? answer.followUps : [],
        },
      })
    }
  }
  return out
}

export default function OpportunityWorkspace() {
  const router = useRouter()
  const [country, setCountry] = useState(DEFAULT_COUNTRY)
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const countries = useMemo(() => countryOptions(null), [])
  const tail = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)
  // Giữ lịch sử trong một ref song song với state: `send` đọc nó ngay tại chỗ, nên hai câu
  // gửi sát nhau không bị câu sau đọc phải lịch sử cũ của câu trước.
  const history = useRef<Turn[]>([])
  // Chặn lượt ghi đầu tiên. Không có cờ này thì effect lưu chạy ngay lúc dựng trang với
  // `turns` còn rỗng và xoá sạch đúng cuộc trò chuyện vừa định khôi phục.
  const restored = useRef(false)

  // Khôi phục cuộc trò chuyện. Nằm trong effect chứ không nằm ở giá trị khởi tạo của
  // `useState`: trang này dựng cả ở phía server, nơi không có `window`, và đọc localStorage
  // lúc dựng sẽ làm HTML của server khác HTML của trình duyệt — React vứt cả cây đi dựng lại.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const saved = JSON.parse(raw) as { country?: unknown; turns?: unknown }
        const revived = reviveTurns(saved.turns)
        if (revived.length) {
          history.current = revived
          setTurns(revived)
        }
        if (typeof saved.country === 'string' && saved.country) setCountry(saved.country)
      }
    } catch {
      // Bản ghi hỏng, hoặc trình duyệt chặn localStorage (chế độ ẩn danh, cấu hình công ty).
      // Cả hai đều chỉ có nghĩa là bắt đầu bằng một cuộc trò chuyện trống.
    }
    restored.current = true
  }, [])

  useEffect(() => {
    if (!restored.current) return
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ country, turns: turns.slice(-STORED_TURNS) }),
      )
    } catch {
      // Hết chỗ hoặc bị chặn: mất phần lưu, không mất phiên đang chạy.
    }
  }, [turns, country])

  useEffect(() => {
    tail.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns, loading])

  // Ô nhập cao đúng bằng nội dung. Một textarea cố định phải chọn giữa hai cái dở: đủ cao cho
  // câu dài thì khi trống nó là một mảng trắng chiếm nửa panel, còn để một dòng thì câu dài
  // trôi mất khỏi tầm nhìn đúng lúc người ta đang đọc lại câu mình vừa viết.
  useEffect(() => {
    const field = box.current
    if (!field) return
    field.style.height = 'auto'
    field.style.height = `${field.scrollHeight}px`
    // Chỉ cho cuộn khi thật sự có phần bị che. Để `overflow-y: auto` thường trực thì Edge vẽ
    // sẵn cặp nút cuộn lên/xuống ở góc ô nhập kể cả lúc chỉ có một dòng — hai cái nút không
    // làm gì cả và không có cách nào đoán ra chúng để làm gì.
    field.style.overflowY = field.scrollHeight > field.clientHeight ? 'auto' : 'hidden'
  }, [draft])

  const send = useCallback(
    async (raw: string) => {
      const question = raw.trim()
      if (!question || loading) return

      const asked: Turn[] = [...history.current, { role: 'user', text: question }]
      history.current = asked
      setTurns(asked)
      setDraft('')
      setError(null)
      setLoading(true)

      const messages: AskTurn[] = asked.map((turn) =>
        turn.role === 'user'
          ? { role: 'user', text: turn.text, items: [] }
          : {
              role: 'assistant',
              text: turn.answer.reply,
              items: turn.answer.items.map((item) => item.term),
            },
      )

      try {
        const answer = await browserPostJson<Answer>('/api/opportunity/ask', {
          messages,
          geo: country,
        })
        const next: Turn[] = [...asked, { role: 'assistant', answer }]
        history.current = next
        setTurns(next)
      } catch (failure) {
        // Câu vừa hỏi ở lại trên màn hình. Nuốt nó đi cùng lỗi sẽ buộc người dùng gõ lại
        // nguyên câu, và đó là thứ họ vừa mất công viết nhất.
        setError((failure as Error).message)
      } finally {
        setLoading(false)
      }
    },
    [country, loading],
  )

  /**
   * Xoá cuộc trò chuyện, HAI BƯỚC.
   *
   * Một bước là đủ hồi cuộc trò chuyện chỉ sống trong bộ nhớ trang — bấm nhầm thì tải lại là
   * xong. Từ lúc nó sống qua lần tải lại thì không: một cú bấm nhầm xoá vĩnh viễn cả buổi hỏi,
   * mà mỗi lượt hỏi tốn mười giây. Bước xác nhận tự rút lui sau vài giây nên nó không biến
   * thành một cái nút hỏng nằm đó.
   */
  const reset = useCallback(() => {
    if (!confirming) {
      setConfirming(true)
      return
    }
    setConfirming(false)
    history.current = []
    setTurns([])
    setError(null)
    try {
      window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // Không xoá được thì effect lưu ở trên vẫn ghi đè bằng danh sách rỗng ngay sau đây.
    }
  }, [confirming])

  useEffect(() => {
    if (!confirming) return
    const timer = window.setTimeout(() => setConfirming(false), 4000)
    return () => window.clearTimeout(timer)
  }, [confirming])

  /** Chỗ nối duy nhất sang mục Từ khoá, và nó chỉ đi một chiều. */
  const openInKeywords = useCallback(
    (term: string) => {
      router.push(`/keywords?seed=${encodeURIComponent(term)}&geo=${encodeURIComponent(country)}`)
    },
    [router, country],
  )

  const empty = turns.length === 0

  return (
    <>
      <div className="page-head opp-head">
        <div>
          <h1>Cơ hội</h1>
        </div>
      </div>

      <div className="chat" data-empty={empty}>
        {empty ? (
          // Chỉ một câu hỏi và ô nhập. Đoạn hướng dẫn cùng bốn câu ví dụ đã gỡ theo yêu cầu:
          // người dùng của công cụ này được hướng dẫn trực tiếp, nên chữ ở đây chỉ làm màn
          // hình mở đầu nặng hơn mà không dạy được gì họ chưa biết.
          <h2 className="chat-open">Bạn đang tính bán gì?</h2>
        ) : (
          <div className="chat-thread">
            {turns.map((turn, index) =>
              turn.role === 'user' ? (
                <p className="chat-ask" key={`u${index}`}>
                  {turn.text}
                </p>
              ) : (
                <AnswerBlock
                  key={`a${index}`}
                  answer={turn.answer}
                  onPick={openInKeywords}
                  onAsk={send}
                />
              ),
            )}

            {loading && (
              <p className="chat-wait">
                <span className="spinner" /> Đang nghĩ theo chuỗi hệ quả, rồi hỏi sàn xem có bán
                thật không…
              </p>
            )}
            {error && <div className="notice bad">{error}</div>}
            <div ref={tail} />
          </div>
        )}

        <div className="chat-compose">
          <textarea
            ref={box}
            value={draft}
            rows={1}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send(draft)
              }
            }}
            placeholder={empty ? 'Hỏi bất cứ điều gì về việc nên bán gì…' : 'Hỏi tiếp…'}
          />
          <div className="chat-tools">
            <Dropdown
              value={country}
              options={countries}
              onChange={setCountry}
              searchable
              searchPlaceholder="Tìm nước…"
            />
            {/* Nút xoá nằm TRONG ô nhập chứ không ở tiêu đề trang. Ở tiêu đề thì nó cuộn mất
                ngay khi cuộc trò chuyện dài hơn một màn hình — đúng lúc người ta cần nó nhất.
                Ô nhập thì `position: sticky` nên luôn ở trong tầm mắt. */}
            {!empty && (
              <button className="btn ghost chat-reset" data-confirm={confirming} onClick={reset}>
                {confirming ? 'Xoá hội thoại này?' : 'Hội thoại mới'}
              </button>
            )}
            <button className="btn" onClick={() => send(draft)} disabled={loading || !draft.trim()}>
              {loading ? 'Đang nghĩ…' : 'Gửi'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
