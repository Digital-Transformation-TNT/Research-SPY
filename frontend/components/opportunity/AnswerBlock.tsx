'use client'

import { useState } from 'react'
import ProductThumb from '@/components/trendscout/ProductThumb'
import { money, short } from '@/lib/trendscout'
import {
  Y_DINH_NHAN,
  type Answer,
  type HubProduct,
  type OpportunityItem,
  type OpportunityStatus,
} from '@/lib/opportunity/types'

const NHAN_LANG_KINH: Record<string, string> = {
  hot: 'Đang tăng tốc',
  spike: 'Đột biến',
  steady: 'Bán khoẻ ổn định',
  gap: 'Khe hở',
  new: 'Tân binh',
  ban_chay: 'Bán chạy',
}

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

/**
 * Số thật của kho cho MỘT món AI gợi ý — thứ một chatbot thuần không nói được.
 *
 * "kho chưa đo" KHÁC "sàn không có", và phải nói đúng chữ đó. Kho chỉ cào TOP mỗi ngành nên
 * hàng ngách vắng mặt là chuyện bình thường; viết thành "không có" là bịa ra một kết luận thị
 * trường từ một lỗ hổng dữ liệu.
 *
 * Khi phải nới cụm để tìm ra hàng ("áo mưa bít cánh dơi" → "áo mưa bít"), con số là của cụm
 * rộng hơn nên phải ghi rõ — nếu không thì "7 listing" đọc thành 7 cái áo mưa bít cánh dơi.
 */
function KhoStat({ signal }: { signal: OpportunityItem['signal'] }) {
  if (!signal) return <span className="ans-kho" data-empty>kho chưa đo</span>
  const gia =
    signal.gia_min != null && signal.gia_max != null
      ? signal.gia_min === signal.gia_max
        ? money(signal.gia_min, signal.currency)
        : `${money(signal.gia_min, signal.currency)} – ${money(signal.gia_max, signal.currency)}`
      : null
  return (
    <span className="ans-kho" title={signal.nguyen_cum ? undefined : `Số của cụm rộng hơn: “${signal.cum}”`}>
      <b>{short(signal.n)}</b> listing · top bán <b>{short(signal.ban_30)}</b>/tháng
      {gia ? <> · {gia}</> : null}
      {!signal.nguyen_cum && <em> (cụm “{signal.cum}”)</em>}
    </span>
  )
}

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
        <KhoStat signal={item.signal} />
        <span className="ans-arrow" aria-hidden>
          →
        </span>
      </Tag>
    </li>
  )
}

/**
 * Sản phẩm thật của kho — PHẦN CHÍNH của câu trả lời, không phải phụ lục.
 *
 * TỪNG NẰM SAU MỘT NÚT GẤP tên là "Dữ liệu kho AI đã đọc", đóng sẵn. Sai ở chỗ: người hỏi "top
 * sản phẩm bán chạy" muốn thấy SẢN PHẨM — ảnh, tên bấm được, giá, lượt bán — chứ không phải một
 * đoạn văn kể tên vài món rồi tự đi tìm. Gấp lại thì thứ duy nhất hiện ra là đoạn văn, và nó đọc
 * như câu trả lời của một trợ lý chưa tra cứu gì. Chủ dự án chốt 14/09/2026: bày thẳng ra.
 *
 * GOM THEO SÀN. Ba sàn không cùng thang đo (1688 là sàn sỉ, lượt bán lớn hơn Shopee hàng chục
 * lần) nên không có bảng xếp hạng chung — mỗi sàn một nhóm, xếp hạng trong nhóm của nó. Cùng
 * nguyên tắc backend áp cho khối chữ gửi Gemini, xem `scout.top_ban_chay_tung_san`.
 *
 * SỐ LẤY TỪ KHO, KHÔNG LẤY TỪ CÂU CHỮ CỦA AI. Mô hình chép lại một con số là mô hình có thể chép
 * sai, và một con số sai trông y hệt một con số đúng.
 */
function HubProducts({ products, ngay }: { products: HubProduct[]; ngay?: string | null }) {
  // Giữ nguyên thứ tự backend gửi: bán chạy trước, doanh số sau, và trong mỗi sàn là thứ hạng
  // thật. `Map` giữ thứ tự chèn nên sàn nào có hàng trước thì đứng trước.
  const nhom = new Map<string, HubProduct[]>()
  for (const p of products) {
    const khoa = p.nhan_san ?? 'Chưa rõ sàn'
    const cu = nhom.get(khoa)
    if (cu) cu.push(p)
    else nhom.set(khoa, [p])
  }

  return (
    <div className="hubp">
      <p className="hubp-cap">
        Sản phẩm thật trong kho{ngay ? ` · quét ngày ${ngay.split('-').reverse().slice(0, 2).join('/')}` : ''} ·
        bấm tên để mở trang sản phẩm trên sàn
      </p>
      {[...nhom].map(([nhan, rows]) => (
        <section className="hubp-group" key={nhan}>
          <h4 className="hubp-san">
            {nhan} <span>{rows.length} sản phẩm</span>
          </h4>
          <div className="img-list hubp-list">
            {rows.map((p, i) => (
              <div className="hubp-row" key={`${p.san}:${p.product_id}`}>
                <span className="hubp-rank">{i + 1}</span>
                <ProductThumb src={p.image_url} />
                <div className="img-info">
                  {p.url ? (
                    <a className="ts-title" href={p.url} target="_blank" rel="noopener noreferrer">
                      {p.title ?? p.product_id}
                    </a>
                  ) : (
                    <b>{p.title ?? p.product_id}</b>
                  )}
                  <small>
                    {[p.main_name, p.sub_name].filter(Boolean).join(' › ') || 'Chưa gắn ngành'}
                    {p.rating ? ` · ${p.rating.toFixed(1)}★` : ''}
                  </small>
                </div>
                <div className="hubp-num">
                  <b>{money(p.price, p.currency)}</b>
                  <small>bán 30 ngày {short(p.ban_30 ?? p.sold_monthly)}</small>
                  <small>doanh số {money(p.doanh_so_30, p.currency, true)}</small>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

/**
 * HỆ THỐNG ĐÃ HIỂU CÂU HỎI NHƯ THẾ NÀO — một dòng, ngay dưới câu trả lời.
 *
 * Một hệ RAG mà người dùng không thấy được nó hiểu câu hỏi ra sao thì mỗi lần trả lời lệch, họ
 * chỉ kết luận được là "AI dở" và không có gì để sửa. Dòng này bày ra đúng những gì tầng
 * `truy_van.py` đã quyết: ý định nào, sàn nào, ngành nào, lọc giá nào — nên khi lệch, chỉ ra
 * được ngay mắt xích sai. Bấm vào xem đủ lý do.
 */
function DaHieu({ g }: { g: NonNullable<Answer['grounding']> }) {
  const [mo, setMo] = useState(false)
  if (!g.yDinh) return null
  const chip: string[] = [Y_DINH_NHAN[g.yDinh] ?? g.yDinh]
  if (g.phamVi) chip.push(g.phamVi)
  if (g.langKinh) chip.push(NHAN_LANG_KINH[g.langKinh] ?? g.langKinh)
  else if (g.yDinh === 'toplist') chip.push(g.bang === 'doanh_so' ? 'theo doanh số' : 'theo lượt bán')
  if (g.nganh?.length) chip.push(`ngành ${g.nganh.join(', ')}`)
  if (g.tuKhoa?.length) chip.push(`“${g.tuKhoa.join('”, “')}”`)
  if (g.giaMin != null || g.giaMax != null) {
    const n = (v: number) => v.toLocaleString('vi-VN')
    chip.push(
      g.giaMin != null && g.giaMax != null
        ? `giá ${n(g.giaMin)}–${n(g.giaMax)}`
        : g.giaMax != null
          ? `giá ≤ ${n(g.giaMax)}`
          : `giá ≥ ${n(g.giaMin!)}`,
    )
  }
  if (g.sanLoai?.length) chip.push(`trừ ${g.sanLoai.join(', ')}`)

  return (
    <div className="dahieu">
      <button className="dahieu-line" onClick={() => setMo((v) => !v)} title="Vì sao hiểu như vậy">
        <span aria-hidden>{mo ? '▾' : '▸'}</span> Đã hiểu: {chip.join(' · ')}
      </button>
      {mo && (
        <ul className="dahieu-ly-do">
          {(g.lyDo?.length ? g.lyDo : ['Không có ghi chú nào.']).map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
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
      {answer.grounding && <DaHieu g={answer.grounding} />}

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

      {answer.hubProducts && answer.hubProducts.length > 0 && (
        <HubProducts products={answer.hubProducts} ngay={answer.grounding?.ngay} />
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
