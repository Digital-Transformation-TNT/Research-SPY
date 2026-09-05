'use client'

import type { KeywordCandidate, KeywordGloss, KeywordSource } from '@/lib/keywords/types'

/** `markets` là `null` khi nguồn chạy ở mọi thị trường — xem `KeywordProvider.markets`. */
export type SourceInfo = {
  id: KeywordSource
  label: string
  markets: string[] | null
  /** Nguồn chấm chính; do backend công bố, xem `KeywordProvider.is_primary`. */
  primary: boolean
  /** Chọn thị trường có đổi được kết quả nguồn này không — xem `KeywordProvider.geo_targeted`. */
  geoTargeted: boolean
}

/**
 * Lượng tìm của một cụm — thanh 0–100. Phần trăm thay đổi nằm ở cột kế bên (`ChangeCell`),
 * đúng cách Google Trends bày hai cột.
 *
 * Đây là bản sao đúng hai con số mà bảng "Cụm từ tìm kiếm hàng đầu" của chính Google Trends
 * hiện ra, và cả hai đến từ cùng một hàng trong RPC đó (`RelatedQuery.value` và
 * `.change_percent`). Đo 2026-07-30 trên "bút bi": 100/+20%, 95/+7%, 90/−4% — khớp từng số
 * với giao diện Trends.
 *
 * ĐÃ TỪNG LÀ MỘT SPARKLINE MỖI DÒNG, và bị thay có lý do đo được:
 *   - Nửa số dòng không vẽ được gì. Trends từ chối đo các cụm long-tail lượng tìm thấp —
 *     đúng nhóm mà công cụ này sinh ra để tìm — nên bảng đầy chữ "không có dữ liệu".
 *   - Ba mươi dòng tốn tám lượt điều hướng /explore ≈ 70 giây, mỗi lượt một cơ hội để
 *     Playwright gãy, cho một cột mà các đường trông gần như giống hệt nhau.
 *   - Chính Google cũng không làm thế: họ vẽ MỘT biểu đồ cho từ gốc, còn bảng liên quan thì
 *     mỗi hàng chỉ có thanh và phần trăm. Cái biểu đồ từ gốc ấy cũng đã bị gỡ khỏi công cụ:
 *     nó tốn thêm một lần mở trình duyệt (~7–10 giây) và một lượt vào hạn mức Trends cho một
 *     hình không quyết định được gì.
 * Hai con số này thì đi kèm ngay trong lần gọi `/api/keywords` duy nhất, không thêm giây nào.
 *
 * Vẫn là thang TƯƠNG ĐỐI, và giao diện phải nói vậy. Lượng tìm tuyệt đối chỉ có ở Google Ads
 * Keyword Planner với tài khoản đang tiêu tiền, hoặc mua lại qua API trả phí — không nguồn
 * miễn phí nào cấp được.
 */
function DemandCell({ item }: { item: KeywordCandidate }) {
  const { demand } = item.score

  if (demand === undefined || demand === null) {
    // Cụm chỉ có mặt ở bảng "đang tăng" thì không có thứ hạng lượng tìm, nhưng "đang tăng"
    // tự nó là tín hiệu — mất nó đi thì dòng này trông y hệt dòng Trends chưa từng nhắc tới.
    const surge = item.hits.find((h) => h.rising && h.demand !== undefined)
    if (surge) {
      // Trends dùng 5000 làm mã cho nhãn "Đột biến" chứ không phải một phần trăm thật.
      const label = (surge.demand ?? 0) >= 5000 ? 'đột biến' : `+${Math.round(surge.demand ?? 0)}%`
      return (
        <span
          className="surge"
          title="Google Trends xếp cụm này vào bảng “Cụm từ tìm kiếm tăng”. Đó là phần trăm tăng trưởng, không phải khối lượng — nên không xếp chung thang với thanh của các dòng khác."
        >
          ↑ đang tăng {label}
        </span>
      )
    }
    return (
      <span
        className="muted small"
        title="Google Trends không xếp cụm này vào bảng truy vấn liên quan. KHÔNG có nghĩa là không ai tìm — bảng đó chỉ chứa khoảng một trăm cụm, nên phần lớn long-tail nằm ngoài tầm nó."
      >
        —
      </span>
    )
  }

  return (
    <div className="demand">
      <span
        className="demand-bar"
        role="img"
        aria-label={`Lượng tìm ${demand} trên 100`}
        title={`${demand}/100 so với cụm được tìm nhiều nhất trong nhóm truy vấn liên quan`}
      >
        <i style={{ width: `${demand}%` }} />
      </span>
    </div>
  )
}

/**
 * Cột "Thay đổi" — dựng lại đúng cột cùng tên của Google Trends: mũi tên, rồi phần trăm.
 *
 * CỘT RIÊNG, không nhét cạnh thanh như trước. Google tách hai cột vì chúng là hai đại lượng
 * khác nhau — một cái là mức, một cái là chiều — và tách ra thì các phần trăm nằm thẳng hàng
 * nên đọc lướt cả bảng được. Nhét chung một ô thì mỗi dòng phần trăm bắt đầu ở một chỗ.
 *
 * `null` NGHĨA LÀ CHƯA BIẾT, và ô để trống chứ không hiện `0%`. Bản trước mặc định 0.0 nên mọi
 * dòng hiện `→ 0%` — một phán quyết mà Google chưa hề đưa ra. Xem `RelatedQuery.change_percent`.
 * Ô trống xuất hiện khi bảng đến từ đường lui Playwright: response đường đó không chở cột này.
 */
function ChangeCell({ item }: { item: KeywordCandidate }) {
  const { demand, changePercent } = item.score

  if (demand === undefined || demand === null || changePercent == null) {
    return (
      <span
        className="muted small"
        title="Google Trends chưa công bố mức thay đổi cho cụm này ở lượt lấy vừa rồi."
      >
        —
      </span>
    )
  }

  const dir = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'flat'
  return (
    <span className={`delta ${dir}`} title={DELTA_HINT[dir]}>
      <i className="delta-arrow">{dir === 'up' ? '↑' : dir === 'down' ? '↓' : '→'}</i>
      <b>
        {changePercent > 0 ? '+' : ''}
        {changePercent}%
      </b>
    </span>
  )
}

/** Phần trăm này là của Google, không phải của ta — câu giải thích phải nói rõ điều đó. */
const DELTA_HINT: Record<string, string> = {
  up: 'Google Trends công bố cụm này tăng so với kỳ trước — đúng cột “Thay đổi” trên trang Trends',
  down: 'Google Trends công bố cụm này giảm so với kỳ trước. Phần lớn là mùa vụ — so với cùng kỳ năm ngoái trước khi kết luận',
  flat: 'Google Trends không ghi nhận thay đổi đáng kể so với kỳ trước',
}

/**
 * Câu giải thích cho chip thứ hạng, khác nhau theo loại bằng chứng mà nguồn đó có.
 *
 * `hasPrimary` đổi hẳn ý nghĩa của hai sàn chứ không chỉ đổi chữ. Khi nguồn chấm chính đang
 * bật, chúng đúng là "nguồn đối chiếu" — trọng số 0,2 so với 0,5, và rổ ứng viên do Trends
 * quyết định (`_primary_pool` ở `lib/keywords/rank.py`). Khi tắt nó đi thì rổ là toàn bộ ứng
 * viên và hai sàn là bằng chứng DUY NHẤT, nên gọi chúng là "đối chiếu" thành nói dối về chỗ
 * thứ hạng ấy từ đâu ra.
 */
function rankHint(source: SourceInfo, rank: number, total: number | undefined, hasPrimary: boolean): string {
  const scope = total ? `trong ${total} từ khoá ${source.label} trả về` : `ở ${source.label}`
  // `source.primary` chứ không phải `source.id === 'trends'`: nguồn nào là chính do backend
  // công bố, và ở đây không có lý do gì để viết cứng lại chuỗi đó lần nữa.
  if (source.primary)
    return `Xếp thứ ${rank} ${scope}, theo lượng tìm kiếm đo được — đây là nền tảng chấm chính`

  // Các sàn KHÔNG hiện thứ hạng, và đây là một quyết định về sự trung thực chứ không phải về
  // chỗ trống trên màn hình. Chúng là API gợi ý gõ: thứ chúng trả về là danh sách hoàn thiện
  // cho một tiền tố mà CHÍNH TA bịa ra, không phải một bảng xếp hạng nhu cầu. Hiện "Shopee #7
  // / 94" là gán cho Shopee một phán quyết mà nó chưa bao giờ đưa ra, kèm hai chữ số chính xác
  // giả — mẫu số 94 chỉ là số cụm mà mấy lượt mở rộng của ta tình cờ nhặt được.
  //
  // Ranh giới ở đây trùng đúng ranh giới `MEASURED_FLOOR` của `lib/keywords/rank.py`: đo được
  // nhu cầu thì được con số, còn lại chỉ được xác nhận có mặt.
  const role = hasPrimary
    ? 'dùng để đối chiếu chéo, không phải để xếp hạng'
    : 'chưa có nguồn nào đo được lượng tìm cho lượt này'
  return `${source.label} có gợi ý từ khoá này (${role})`
}

/**
 * Nền tảng nào gợi ý từ khoá này, và ở vị trí bao nhiêu.
 *
 * Con số ở đây là thứ hạng TRONG TOÀN BỘ danh sách nguồn đó trả về, khác hẳn cột `#` bên trái
 * là thứ tự trong ba mươi dòng đang xem. Hai thứ đó không phải một, và không cần bằng nhau —
 * "Shopee #21" ở dòng 21 nghĩa là Shopee cũng xếp nó thứ 21, còn "Google #26" ở dòng 14 nghĩa
 * là bảng này đã đẩy nó lên nhờ các nguồn khác. Tooltip nói ra mẫu số để so được.
 *
 * Cột này cố ý KHÔNG gọi là "độ phổ biến". Đo 2026-07-30: endpoint tìm sản phẩm của Shopee trả
 * 403 với người gọi ẩn danh, và search organic của TikTok trả body rỗng — nên cả lượt bán lẫn
 * lượt xem đều ngoài tầm. Thứ công cụ thật sự biết là từ khoá có được gợi ý không và ở vị trí
 * nào, và cột này nói đúng chừng ấy chứ không ngụ ý có dữ liệu doanh số.
 */
function PresenceCell({
  item,
  sources,
  sourceTotals,
}: {
  item: KeywordCandidate
  sources: SourceInfo[]
  sourceTotals: Partial<Record<KeywordSource, number>>
}) {
  // `sources` ở đây đã là các nguồn ĐANG BẬT, nên đây đúng là câu hỏi "lượt tìm này có nguồn
  // chấm chính không" — không cần truyền thêm một prop nói lại điều đã có trong danh sách.
  const hasPrimary = sources.some((s) => s.primary)
  return (
    <div className="presence">
      {sources.map((source) => {
        const rank = item.sourceRanks?.[source.id]
        const on = rank !== undefined
        // Số HIỆN RA là số đã đánh lại 1..N trong đúng những dòng đang xem, nên dãy chip không
        // có lỗ. Số THẬT của nguồn ở lại trong tooltip cùng mẫu số — xem `display_ranks` ở
        // `backend/lib/keywords/types.py`.
        //
        // Rơi về `rank` khi backend chưa có trường mới: một bản cũ vẫn hiện đúng như trước,
        // chỉ là dãy số lại có lỗ.
        const shown = item.displayRanks?.[source.id] ?? rank
        return (
          <span
            key={source.id}
            className={`src ${source.id}`}
            data-off={!on}
            title={
              on
                ? rankHint(source, rank!, sourceTotals[source.id], hasPrimary)
                : `${source.label} không gợi ý từ khoá này`
            }
          >
            {source.label}
            {/* Chỉ nguồn chấm chính mới hiện số. Xem lý do đầy đủ ở `rankHint`: các sàn là
                API gợi ý gõ, thứ hạng của chúng là sản phẩm phụ của những tiền tố ta tự gieo
                chứ không phải phán quyết của sàn. */}
            {on && source.primary && <b>#{shown}</b>}
          </span>
        )
      })}
    </div>
  )
}

function Row({
  item,
  rank,
  showRank,
  sources,
  sourceTotals,
  showDemand,
  gloss,
  glossLoading,
}: {
  item: KeywordCandidate
  rank: number
  /** Xem `showRank` ở `KeywordTable` — cột `#` biến mất khi không có nguồn chấm chính. */
  showRank: boolean
  sources: SourceInfo[]
  sourceTotals: Partial<Record<KeywordSource, number>>
  showDemand: boolean
  gloss?: KeywordGloss
  glossLoading: boolean
}) {
  return (
    <tr className={item.intent === 'informational' ? 'info-row' : undefined}>
      {showRank && <td className="rank">{rank}</td>}
      <td>
        <div className="kw">{item.display}</div>
        {/* Nghĩa nằm ngay dưới từ khoá chứ không thành một cột riêng: đọc một dòng ngoại ngữ
            rồi liếc sang cột thứ tư để biết nó nghĩa gì là bắt mắt nhảy qua cả bảng, ba mươi
            lần. Ở đây mắt chỉ đi xuống một dòng.

            Chuỗi rỗng KHÔNG hiện gì cả. Backend cho phép Gemini để trống khi nó không chắc,
            và một phỏng đoán về tiếng Tagalog trông y hệt một bản dịch chắc chắn — người đọc
            không có cách nào phân biệt, nên chỗ trống là câu trả lời trung thực hơn. */}
        {gloss?.meaning && <div className="kw-gloss">{gloss.meaning}</div>}
        {!gloss && glossLoading && <div className="kw-gloss loading">đang dịch…</div>}
        {/* Đã gỡ theo yêu cầu: nhãn mùa vụ, chip "câu hỏi" của `intent`, và chip nhãn của
            Gemini (mua / tìm hiểu / thương hiệu / lạc chủ đề).

            Cả hai trường vẫn về đủ trong dữ liệu và vẫn LÀM VIỆC ở chỗ khác — `intent` quyết
            định thứ tự sắp xếp và làm mờ cả dòng qua `.info-row`, còn `gloss.label` thì chưa
            có nơi dùng. Ở đây chỉ thôi vẽ chúng ra. */}
      </td>
      {showDemand && (
        <td>
          <DemandCell item={item} />
        </td>
      )}
      {showDemand && (
        <td className="change">
          <ChangeCell item={item} />
        </td>
      )}
      <td>
        <PresenceCell item={item} sources={sources} sourceTotals={sourceTotals} />
      </td>
      <td className="actions">
        {/* Sang tab Sản phẩm với từ khoá điền sẵn. `?keyword=` được `app/(dashboard)/ads/page.tsx`
            chuyển tiếp thành `?kw=` của trang research bên trong iframe — không có bước đó thì
            người dùng nhảy sang tab rồi phải gõ lại đúng cụm vừa bấm. KHÔNG tự chạy research:
            mỗi lượt là một loạt lượt crawl thật, phải do người dùng bấm. */}
        <a href={`/ads?keyword=${encodeURIComponent(item.display)}`} title="Mở tab Sản phẩm với từ khoá này điền sẵn">
          Tìm sản phẩm ↗
        </a>
      </td>
    </tr>
  )
}

/**
 * Bảng kết quả. Có hai hình dạng, quyết định bởi `showDemand`.
 *
 * Cột lượng tìm BIẾN MẤT chứ không hiện rỗng khi nguồn chấm chính bị tắt, và đó là điểm mấu
 * chốt: Google Trends là nguồn duy nhất đo được nhu cầu (đo lại 2026-07-30 — Shopee
 * `search_items` trả 403 `is_login:false`, TikTok `search/general/full` trả body rỗng). Giữ
 * cột lại rồi lấp bằng số của Google sẽ dựng nên một thanh lượng tìm CỦA GOOGLE nằm ngay cạnh
 * chip "Shopee", và người đọc hiểu thành lượng tìm trên Shopee. Để trống cả cột thì mọi dòng
 * đọc thành "không ai tìm". Bỏ hẳn là cách duy nhất không nói sai.
 */
export default function KeywordTable({
  rows,
  timeLabel,
  sources,
  sourceTotals = {},
  showDemand,
  gloss = {},
  glossLoading = false,
}: {
  rows: KeywordCandidate[]
  /** Nhãn cửa sổ đang xem ("Năm qua", "3 tháng qua"…), để tiêu đề cột không nói sai khoảng. */
  timeLabel: string
  sources: SourceInfo[]
  /** Mỗi nguồn trả về bao nhiêu từ khoá — mẫu số cho các chip thứ hạng. */
  sourceTotals?: Partial<Record<KeywordSource, number>>
  /** Bật khi nguồn chấm chính đang được chọn — chỉ khi đó cột lượng tìm mới có gì để nói. */
  showDemand: boolean
  /**
   * Nghĩa tiếng Việt theo `KeywordCandidate.keyword`. Rỗng ở thị trường Việt Nam và khi chưa
   * cấu hình khoá Gemini — cả hai đều là trạng thái bình thường, bảng không đổi hình dạng.
   */
  gloss?: Record<string, KeywordGloss>
  glossLoading?: boolean
}) {
  // Cùng phép suy như `PresenceCell`, và cùng lý do: nguồn nào là chính do backend công bố,
  // nên chỗ này đọc từ danh sách nguồn đang bật chứ không viết cứng chuỗi "trends".
  const hasPrimary = sources.some((s) => s.primary)

  return (
    // Bề rộng các cột được ghim theo vị trí trong `keywords.css`, nên bỏ một cột đi phải báo
    // cho CSS biết — nếu không thì cột xếp hạng lĩnh bề rộng của cột lượng tìm vừa biến mất.
    // `no-rank` là lời báo thứ hai, cho lần cột `#` biến mất.
    <table className={`kwtable${showDemand ? '' : ' no-trend'}${hasPrimary ? '' : ' no-rank'}`}>
      <thead>
        <tr>
          {/* Cột `#` chỉ có nghĩa khi có nguồn chấm chính. Không có Google Trends thì thứ tự
              các dòng không đến từ một phép đo nhu cầu nào — đánh số 1, 2, 3 lên nó là dựng ra
              một bảng xếp hạng mà không nguồn nào đứng sau. Cùng lý do với việc chip của các
              sàn không hiện `#`; xem `rankHint`. */}
          {hasPrimary && <th>#</th>}
          <th>Từ khoá</th>
          {showDemand && (
            <th title="Thang 0–100 so với cụm được tìm nhiều nhất trong nhóm truy vấn liên quan — KHÔNG phải số lượt tìm tuyệt đối, đúng như Google Trends công bố.">
              Lượng tìm — {timeLabel}
            </th>
          )}
          {showDemand && (
            <th
              className="change"
              title="Phần trăm thay đổi so với kỳ trước, đúng con số Google Trends hiện ở cột “Thay đổi”. Gạch ngang nghĩa là lượt lấy vừa rồi không kèm số này — KHÔNG phải 0%."
            >
              Thay đổi
            </th>
          )}
          {/* Tên cột đổi theo việc có nguồn chấm chính hay không, vì nội dung cột đổi thật:
              có Google Trends thì mỗi chip mang một thứ hạng đo được, còn lại thì chip chỉ nói
              "nguồn này có gợi ý từ khoá đó" — gọi chỗ ấy là "Bảng xếp hạng" là hứa một thứ
              hạng không tồn tại. */}
          {hasPrimary ? (
            <th title="Thứ hạng của từ khoá trong TOÀN BỘ danh sách mà nguồn đó trả về — không phải thứ tự ở cột # bên trái. Đưa chuột vào từng chip để xem mẫu số và cách nguồn đó xếp.">
              Bảng xếp hạng
            </th>
          ) : (
            <th title="Những nguồn có gợi ý từ khoá này. KHÔNG phải thứ hạng: đây là API gợi ý gõ, thứ tự chúng trả về chỉ phản ánh cách hoàn thiện tiền tố ta tự gieo, không phản ánh có bao nhiêu người tìm.">
              Nguồn tham khảo
            </th>
          )}
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((item, i) => (
          <Row
            key={item.keyword}
            item={item}
            rank={i + 1}
            showRank={hasPrimary}
            sources={sources}
            sourceTotals={sourceTotals}
            showDemand={showDemand}
            gloss={gloss[item.keyword]}
            glossLoading={glossLoading}
          />
        ))}
      </tbody>
    </table>
  )
}
