'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Dropdown from './Dropdown'
import KeywordTable, { type SourceInfo } from './KeywordTable'
import {
  DEFAULT_COUNTRY,
  DEFAULT_PROPERTY,
  DEFAULT_TIME_RANGE,
  PROPERTIES,
  TIME_RANGES,
  countryOptions,
  fullYearRanges,
} from '@/lib/keywords/trendsOptions'
import SeedBridge, { type BridgeState } from './SeedBridge'
import type { MarketMap } from '@/lib/keywords/providers'
import { browserGet } from '@/lib/api'
import type { BridgeResult, KeywordGloss, KeywordResult, KeywordSource } from '@/lib/keywords/types'

/**
 * Màn hình research từ khoá.
 *
 * Danh sách nguồn được truyền vào từ server (xem `app/keywords/page.tsx`), nên thêm một
 * nguồn gợi ý mới sẽ tự hiện ở đây mà không phải sửa file này.
 *
 * Ba ô chọn quốc gia / thời gian / loại tìm kiếm là ba ô của chính trang Google Trends, và
 * chúng áp cho CẢ hai việc: tìm ra từ khoá, và đo đường lượng tìm. Đó là điều bắt buộc phải
 * đúng như vậy — bảng truy vấn liên quan của "24 giờ qua" là một tập từ khoá khác hẳn của
 * "Năm qua", nên đo một cửa sổ rồi liệt kê từ khoá của cửa sổ kia là trộn hai câu hỏi.
 *
 * Màn hình vẫn cố ý KHÔNG có nút chỉnh độ sâu, số dòng, cách sắp xếp hay bộ lọc câu hỏi.
 * Backend cố định 30 dòng và tự xếp theo top gộp của các nền tảng; thêm nút cho những thứ đó
 * chỉ tạo ra các tổ hợp mà không ai kiểm và phần lớn cho ra bảng tệ hơn mặc định.
 *
 * ── HAI HÌNH DẠNG, MỘT MÀN HÌNH ─────────────────────────────────────────────────────────
 *
 * Có nguồn chấm chính trong danh sách tick → nguyên vẹn như mô tả trên: đủ ba ô chọn, đủ cột
 * lượng tìm. Đây là hình dạng chính và không đổi khi bật thêm Shopee/TikTok để đối chiếu.
 *
 * KHÔNG có nguồn chấm chính (chỉ Shopee và/hoặc TikTok) → một màn hình khác hẳn, vì lúc đó
 * công cụ trả lời một câu hỏi khác. Đo lại 2026-07-30 bằng đúng endpoint mà backend gọi:
 * Shopee `search_items` trả HTTP 403 `is_login:false`, TikTok `search/general/full` trả 200
 * với body rỗng 0 byte. Không sàn nào cấp được lượt bán hay lượt xem, nên thứ duy nhất còn
 * lại là "sàn có gợi ý cụm này không, và ở vị trí nào". Ba thay đổi theo đó:
 *
 *   1. Bỏ hẳn cột lượng tìm. Lấp nó bằng Trends thì đường của GOOGLE nằm cạnh chip "Shopee"
 *      và đọc thành lượng tìm trên Shopee; để trống thì mọi dòng đọc thành "không ai tìm".
 *   2. Ẩn "Thời gian" và "Loại tìm kiếm" — hai khái niệm riêng của Trends. Backend nhận
 *      chúng qua `SearchContext` rồi bỏ qua ở cả hai sàn, nên để lại là hứa suông.
 *   3. GIỮ "Quốc gia", kể cả khi chỉ có TikTok. Endpoint TikTok trả gợi ý theo IP người gọi
 *      (`geoTargeted: false`), nhưng ô này vẫn đổi ngôn ngữ của các tiền tố mở rộng ở
 *      `expand_with_provider` — ẩn đi là khoá cứng ngôn ngữ một cách âm thầm. Nên nó ở lại,
 *      kèm câu nói đúng nó làm gì.
 */

/** Ba ô chọn gói lại, để một lượt đo luôn dùng đúng cửa sổ của lượt tìm sinh ra nó. */
type TrendsQuery = { country: string; timeRange: string; property: string }

export default function KeywordResearch({
  sources: allSources,
  markets = {},
}: {
  sources: SourceInfo[]
  /** Bảng ngôn ngữ theo thị trường. Rỗng khi backend chưa có endpoint — phần nhắc tự tắt. */
  markets?: MarketMap
}) {
  const [seed, setSeed] = useState('')
  /**
   * Từ gốc tiếng Việt đã bị thay bằng cụm bản địa, giữ lại để hoàn tác và để NHÌN THẤY.
   *
   * Thay ô nhập mà không để lại dấu vết là kiểu lặng lẽ đổi câu hỏi của người dùng rồi trả
   * lời câu khác — cả tầng `bridge.py` được viết để tránh đúng chuyện đó. Một dòng vết cho
   * họ ba thứ cùng lúc: thấy đã thay gì bằng gì, bấm một cái là quay lại, và học được từ
   * vựng thị trường để lần sau gõ thẳng.
   */
  const [bridgedFrom, setBridgedFrom] = useState<string | null>(null)
  /**
   * Nguồn đang xem. Dãy chip hành xử như RADIO, không phải checkbox.
   *
   * Vẫn là một mảng chứ không phải một chuỗi, vì "Tổng hợp" là một lựa chọn thật và nó chở
   * nhiều nguồn — và vì mọi thứ phía dưới (query string, `activeSources`, `hasPrimary`, cột
   * bảng) đều đã nói bằng danh sách nguồn. Đổi thành một chuỗi rồi bung ra lại ở bốn nơi thì
   * chỉ để đúng một chỗ trông gọn hơn.
   *
   * Mặc định là nguồn chấm chính (Google) một mình. "Tổng hợp" chậm hơn hẳn mà gần như không
   * đổi bảng: rổ ứng viên do Google quyết định, hai sàn chỉ tinh chỉnh thứ tự và mỗi sàn tốn
   * 25 lượt gọi cách nhau 700ms (xem `expand_with_provider`).
   *
   * Nguồn nào là "chính" do backend công bố, không phải giao diện đoán — nên ở đây không có
   * chuỗi "trends" nào viết cứng. Không cần phòng trường hợp "không nguồn nào được đánh dấu":
   * `app/keywords/page.tsx` đã chốt việc đó trước khi truyền xuống.
   */
  const [selected, setSelected] = useState<KeywordSource[]>(() =>
    allSources.filter((s) => s.primary).map((s) => s.id),
  )
  const [country, setCountry] = useState(DEFAULT_COUNTRY)
  const [timeRange, setTimeRange] = useState(DEFAULT_TIME_RANGE)
  const [property, setProperty] = useState(DEFAULT_PROPERTY)
  const [result, setResult] = useState<KeywordResult | null>(null)
  /**
   * Cửa sổ mà `result` đang hiển thị ĐÃ ĐƯỢC ĐO BẰNG — không phải cửa sổ đang chọn ở dropdown.
   *
   * Hai thứ này lệch nhau ngay khi người dùng đổi ô Thời gian mà chưa bấm tìm lại. Đọc từ state
   * sống thì tiêu đề cột và câu ghi chú sẽ nói "Năm qua" trong khi bảng bên dưới vẫn là số liệu
   * ba tháng — một cách nói sai rất khó phát hiện, vì mọi thứ trông vẫn hợp lý.
   */
  const [resultWindow, setResultWindow] = useState<TrendsQuery | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /**
   * Nghĩa tiếng Việt của từng dòng, khi thị trường không nói tiếng Việt.
   *
   * `entries` rỗng là trạng thái BÌNH THƯỜNG, không phải lỗi: thị trường VN không cần dịch,
   * và khoá Gemini có thể chưa được cấu hình. Cả hai trường hợp backend đều trả 200 kèm
   * `message`, và bảng phải hiện đầy đủ như chưa từng có tính năng này.
   */
  const [gloss, setGloss] = useState<{ loading: boolean; entries: Record<string, KeywordGloss>; message?: string }>({
    loading: false,
    entries: {},
  })
  /**
   * Bảng đề cử cách gọi bản địa cho từ gốc. `undefined` = chưa mở lần nào.
   *
   * Chỉ chạy khi người dùng chủ động bấm, không bao giờ theo mỗi lượt tìm: nó tốn một lần mở
   * trình duyệt cho Google Trends (~7 giây) cộng một lượt gọi Gemini, và phần lớn lượt tìm
   * không cần tới nó — người dùng thường đã biết cụm mình muốn sau lần bắc cầu đầu tiên.
   */
  const [bridge, setBridge] = useState<BridgeState | undefined>(undefined)
  //: Đếm số lượt đo đã bắt đầu, để lượt cũ tự bỏ cuộc khi có lượt mới.
  const measureRun = useRef(0)
  //: Cùng vai trò với `measureRun`, cho lượt dịch.
  const glossRun = useRef(0)
  //: Cùng vai trò, cho lượt bắc cầu.
  const bridgeRun = useRef(0)

  /**
   * Nhận từ gốc từ URL: `/keywords?seed=…&geo=…` — cửa vào từ mục Cơ hội.
   *
   * Trong `useEffect` chứ không trong hàm khởi tạo `useState`: trang dựng ở server nên đọc lúc
   * khởi tạo sẽ lệch hydrate. Cố ý KHÔNG tự chạy lượt tìm.
   */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const fromUrl = (params.get('seed') ?? '').trim()
    if (fromUrl) setSeed(fromUrl)
    const geo = (params.get('geo') ?? '').trim().toUpperCase()
    if (geo) setCountry(geo)
  }, [])

  const labelOf = useMemo(
    () => Object.fromEntries(allSources.map((s) => [s.id, s.label])) as Record<string, string>,
    [allSources],
  )

  /**
   * Từ gốc không thuộc thị trường đang chọn — phát hiện NGAY, không gọi mạng.
   *
   * Đây là điểm mấu chốt của cả phần này: thời điểm cần phản ứng là lúc người dùng đổi ô
   * Quốc gia, KHÔNG phải lúc họ bấm Tìm. Ngay giây đó ta đã biết chắc lượt tìm sẽ ra bảng
   * rỗng, nên bắt họ bấm rồi chờ nửa phút để nhận về một dòng lỗi là lãng phí tránh được.
   *
   * `> 127` là đúng phép kiểm mà backend dùng (`seed_looks_out_of_market`), và nó chỉ chạy ở
   * thị trường có `diacriticFree` — tức thị trường mà truy vấn viết bằng chữ Latin thuần
   * ASCII, nơi một ký tự ngoài ASCII không thể là từ khoá bản địa dù thuộc ngôn ngữ nào.
   * Backend vẫn kiểm lại một lần nữa; ở đây chỉ là để phản hồi tức thì.
   *
   * Cờ `diacriticFree` do backend tính và gửi sang — KHÔNG suy từ mã ngôn ngữ ở đây. Chính
   * chỗ này từng hỏng: thị trường Thái Lan bị gán nhầm ngôn ngữ "en", nên một từ gốc tiếng
   * Thái — đúng chữ bản địa của nó — bị báo là không thuộc thị trường.
   */
  const seedOutOfMarket = useMemo(() => {
    const term = seed.trim()
    const market = markets[country]
    if (term.length < 2 || !market) return false
    const chars = [...term].map((c) => c.codePointAt(0)!)
    // Luật 1: thị trường viết ASCII thuần mà từ gốc có ký tự ngoài ASCII.
    if (market.diacriticFree && chars.some((c) => c > 127)) return true
    // Luật 2: thị trường không viết chữ Latin có dấu mà từ gốc lại có dấu kiểu Latin. Đúng
    // hai dải này, đúng như `_LATIN_DIACRITIC_RANGES` ở backend.
    if (market.latinDiacritics) return false
    return chars.some((c) => (c >= 0x00c0 && c <= 0x024f) || (c >= 0x1e00 && c <= 0x1eff))
  }, [seed, country, markets])

  const timeOptions = useMemo(() => [...TIME_RANGES, ...fullYearRanges(new Date())], [])

  const activeSources = useMemo(
    () => allSources.filter((s) => selected.includes(s.id)),
    [allSources, selected],
  )

  /**
   * Các thị trường mà tập nguồn đang chọn phục vụ được. `null` = mọi thị trường.
   *
   * HỢP chứ không phải GIAO, và điều đó chỉ đúng vì "Tổng hợp" không đòi mọi nguồn cùng chạy:
   * chọn một nước mà chỉ Google phục vụ thì Google chạy một mình, đó là hành vi mong muốn.
   * Lấy giao sẽ bóp cả chế độ Tổng hợp xuống còn sáu nước của Shopee — tức là để nguồn hẹp
   * nhất quyết định thay cho nguồn rộng nhất.
   *
   * Một nguồn phủ mọi nơi (`markets: null`) làm cả hợp thành "mọi nơi", nên không cần liệt kê.
   */
  const allowedMarkets = useMemo(() => {
    if (activeSources.length === 0) return null
    if (activeSources.some((s) => !s.markets)) return null
    return [...new Set(activeSources.flatMap((s) => s.markets as string[]))]
  }, [activeSources])

  const countries = useMemo(() => countryOptions(allowedMarkets), [allowedMarkets])
  const countryLabel = useMemo(
    () => countries.find((o) => o.value === country)?.label ?? country,
    [countries, country],
  )

  /**
   * Tên nước theo mã, KHÔNG lọc theo nguồn.
   *
   * Cần bản đầy đủ vì có chỗ phải gọi tên một nước nằm NGOÀI danh sách đang chọn được: chip
   * của nguồn không phục vụ thị trường hiện tại nhắc "bấm để chuyển sang Hoa Kỳ", mà lúc đó
   * `countries` đang bị bó vào các thị trường của nguồn khác nên không có Hoa Kỳ trong đó.
   * Tra ở `countries` sẽ rơi về mã ISO và câu nhắc thành "chuyển sang US".
   */
  const countryNames = useMemo(() => {
    const map: Record<string, string> = {}
    for (const option of countryOptions()) map[option.value] = option.label
    return map
  }, [])

  /**
   * Cờ chuyển giữa hai hình dạng màn hình — xem khối chú thích đầu file.
   *
   * Đọc từ state SỐNG chứ không từ lượt tìm đã chạy, đúng như cột "Bảng xếp hạng" vốn vẫn
   * làm: bỏ tick một nguồn thì chip của nó biến khỏi mọi dòng ngay lập tức. Cột lượng tìm
   * theo đúng quy ước đó nên hai cột không bao giờ nói hai chuyện khác nhau về cùng một
   * danh sách nguồn.
   */
  const hasPrimary = activeSources.some((s) => s.primary)

  /**
   * Ô Quốc gia không còn lọc được kết quả, chỉ còn đổi ngôn ngữ tiền tố mở rộng.
   *
   * Xảy ra khi mọi nguồn đang bật đều có `geoTargeted: false` — hiện chỉ TikTok. Ô vẫn ở lại
   * vì nó CÓ tác dụng, chỉ là không phải tác dụng mà cái nhãn "Quốc gia" gợi ra, nên chỗ này
   * nói thẳng ra điều đó thay vì để người dùng đổi sang Thái Lan rồi tự hỏi vì sao kết quả y
   * hệt.
   */
  const geoIsAdvisory = activeSources.length > 0 && !activeSources.some((s) => s.geoTargeted)

  /** Nhãn của cửa sổ mà BẢNG ĐANG HIỂN THỊ được đo bằng; rơi về ô đang chọn khi chưa có bảng. */
  const shownRange = resultWindow?.timeRange ?? timeRange
  const timeLabel = timeOptions.find((o) => o.value === shownRange)?.label ?? shownRange

  /**
   * Nguồn nào phục vụ được thị trường đang chọn.
   *
   * `markets` do backend công bố (`KEYWORD_SOURCE_DESCRIPTORS`), nên chip tự tắt khi chọn một
   * nước Shopee không có mặt — thay vì để người dùng bấm tìm rồi nhận về một dòng lỗi đỏ nói
   * đúng điều mà giao diện đã biết trước từ đầu.
   */
  const servesMarket = useCallback(
    (source: SourceInfo) => !source.markets || source.markets.includes(country),
    [country],
  )

  /** Các nguồn phục vụ được thị trường đang chọn — cũng chính là tập mà "Tổng hợp" chọn. */
  const availableSources = useMemo(
    () => allSources.filter(servesMarket),
    [allSources, servesMarket],
  )

  /**
   * "Tổng hợp" đang được chọn, suy từ chính `selected` chứ không giữ thêm một biến chế độ.
   *
   * Hai nguồn sự thật cho cùng một chuyện thì sớm muộn cũng lệch nhau — ví dụ khi `changeCountry`
   * bỏ một nguồn khỏi `selected` mà biến chế độ không biết. Suy ra thì không bao giờ lệch.
   */
  const isCombined = selected.length > 1

  const changeCountry = (next: string) => {
    setCountry(next)
    const serves = (source: SourceInfo) => !source.markets || source.markets.includes(next)
    setSelected((prev) => {
      const kept = prev.filter((id) => {
        const source = allSources.find((s) => s.id === id)
        return source ? serves(source) : false
      })
      // Lưới an toàn, KHÔNG còn là đường chạy thường. Từ khi ô Quốc gia được lọc theo
      // `allowedMarkets`, một nguồn đơn không thể gặp thị trường nó không phục vụ — danh sách
      // đã không bày ra nước đó. Nhánh này chỉ còn đỡ những đường vào khác: state khôi phục
      // từ URL, hoặc backend bỏ một thị trường khỏi `markets` sau khi trang đã dựng.
      //
      // Giữ lại vì cái giá của việc thiếu nó là ZERO nguồn được chọn — dãy chip không sáng ô
      // nào và nút tìm chỉ trả về "Chọn ít nhất 1 nguồn", một ngõ cụt không tự thoát được.
      if (kept.length > 0) return kept
      return allSources.filter((s) => s.primary && serves(s)).map((s) => s.id)
    })
  }

  /**
   * Chọn đúng một nguồn — chip là radio, nên bấm Shopee sẽ tự bỏ Google.
   *
   * Nguồn làm chủ, quốc gia theo sau. Đây là chiều NGƯỢC với `changeCountry`, và cần cả hai
   * vì người dùng chạm vào hai ô đó theo thứ tự bất kỳ. Trước đây chỉ có một chiều: đang ở
   * Mỹ mà bấm Shopee thì Shopee bị gạt và nguồn lặng lẽ nhảy về Google — người dùng bấm một
   * nguồn rồi nhận về nguồn khác, không lời giải thích.
   *
   * Ưu tiên giữ `DEFAULT_COUNTRY` khi nguồn mới phục vụ được nó, để bấm qua lại giữa các
   * nguồn không đẩy ô quốc gia trôi lung tung; hết cách mới lấy thị trường đầu tiên.
   */
  const pick = (id: KeywordSource) => {
    setSelected([id])
    const source = allSources.find((s) => s.id === id)
    if (!source?.markets || source.markets.includes(country)) return
    setCountry(source.markets.includes(DEFAULT_COUNTRY) ? DEFAULT_COUNTRY : source.markets[0])
  }

  /** "Tổng hợp": mọi nguồn phục vụ được thị trường này, không phải cứng cả ba. */
  const pickCombined = () => setSelected(availableSources.map((s) => s.id))

  /**
   * Xin nghĩa tiếng Việt cho các dòng đang hiển thị.
   *
   * Gửi `keyword` (dạng đã chuẩn hoá) chứ không phải `display`: đó là chuỗi mà backend dùng
   * làm khoá cache và để ghép kết quả về đúng dòng, và nó đã bị lược hết dấu câu nên không
   * làm vỡ danh sách ngăn bởi dấu phẩy.
   *
   * KHÔNG tự đoán thị trường nào cần dịch. Bản đồ ngôn ngữ nằm ở `backend/lib/keywords/
   * market.py` và chỉ nên có một bản; chép một danh sách "nước nói tiếng Việt" sang đây là
   * tạo ra bản thứ hai để rồi lệch nhau. Giao diện cứ hỏi, backend trả về rỗng kèm lý do.
   */
  const translate = useCallback(async (keywords: string[], seedTerm: string, market: string) => {
    const run = ++glossRun.current
    setGloss({ loading: true, entries: {} })
    try {
      const params = new URLSearchParams({
        seed: seedTerm,
        keywords: keywords.join(','),
        geo: market,
      })
      const payload = await browserGet<{ entries?: Record<string, KeywordGloss>; message?: string }>(
        `/api/keywords/gloss?${params}`,
      )
      if (glossRun.current !== run) return
      setGloss({ loading: false, entries: payload.entries ?? {}, message: payload.message })
    } catch (e) {
      if (glossRun.current !== run) return
      setGloss({ loading: false, entries: {}, message: (e as Error).message })
    }
  }, [])

  /**
   * Xin đề cử cách gọi ngành hàng ở thị trường đang chọn, kèm số đo của Trends.
   *
   * KHÔNG tự thay ô từ gốc bằng cụm thắng, kể cả khi chỉ có đúng một ứng viên đo được. Công
   * cụ biết cụm nào nhiều người gõ; người dùng biết mình định bán cái gì. Tự thay là lặng lẽ
   * đổi câu hỏi của họ thành một câu khác rồi trả lời câu đó.
   */
  const openBridge = useCallback(async () => {
    const term = seed.trim()
    if (!term) return
    const run = ++bridgeRun.current
    setBridge({ loading: true })
    try {
      const params = new URLSearchParams({ seed: term, geo: country, date: timeRange, gprop: property })
      const payload = await browserGet<BridgeResult>(`/api/keywords/bridge?${params}`)
      if (bridgeRun.current !== run) return
      setBridge({ loading: false, result: payload })
    } catch (e) {
      if (bridgeRun.current !== run) return
      setBridge({ loading: false, message: (e as Error).message })
    }
  }, [seed, country, timeRange, property])

  const search = useCallback(
    async (fresh = false) => {
      if (!seed.trim()) return
      if (selected.length === 0) {
        setError('Chọn ít nhất 1 nguồn')
        return
      }
      setLoading(true)
      setError(null)
      setGloss({ loading: false, entries: {} })
      // Dọn bảng cũ NGAY, đừng để nó nằm lại trong lúc chờ.
      //
      // Một lượt tìm mất hàng chục giây, và trong suốt thời gian đó ô từ gốc đã hiện cụm mới
      // còn bảng bên dưới vẫn là kết quả của cụm cũ — hai thứ mâu thuẫn nhau trên cùng màn
      // hình, mà cái sai lại là cái to hơn và trông chắc chắn hơn. Đã gặp thật: ô nhập ghi
      // "handbag" ở thị trường Philippines trong khi bảng vẫn liệt kê "móc khóa" tiếng Việt.
      setResult(null)
      setResultWindow(null)
      try {
        // Không gửi `depth`, `includeInformational` hay `limit`: backend đã cố định 30 dòng
        // và tự chọn độ sâu. Ba tham số đó từng có nút riêng trên giao diện, nhưng chúng
        // không còn ý nghĩa từ khi nguồn Google chuyển sang Trends.
        const window: TrendsQuery = { country, timeRange, property }
        const params = new URLSearchParams({
          seed: seed.trim(),
          sources: selected.join(','),
          country,
          date: timeRange,
          gprop: property,
        })
        if (fresh) params.set('fresh', 'true')
        const found = await browserGet<KeywordResult>(`/api/keywords?${params}`)
        setResult(found)
        setResultWindow(window)
        // Cũng không `await`: dịch là phần thêm vào, bảng không được chờ nó. Truyền thị
        // trường của CHÍNH lượt tìm này vì cùng lý do với biểu đồ — người dùng đổi ô Quốc gia
        // trong lúc dịch thì hai lượt sẽ nói về hai thị trường khác nhau.
        if (found.keywords.length > 0) {
          void translate(found.keywords.map((k) => k.keyword), seed.trim(), country)
        }
      } catch (e) {
        setError((e as Error).message)
        setResult(null)
        setResultWindow(null)
      } finally {
        setLoading(false)
      }
    },
    [seed, selected, country, timeRange, property, hasPrimary, translate],
  )

  const failed = result?.statuses.filter((s) => !s.ok) ?? []

  // Bảng giữ đúng thứ tự API trả về — API đã xếp theo top gộp của các nền tảng.
  const rows = result?.keywords ?? []

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Keyword</h1>
        </div>
      </div>

      <section className="panel">
        <div className="search-row">
          <input
            type="text"
            placeholder="Nhập từ khoá gốc của ngành hàng… (vd: quần jeans, áo khoác, máy massage)"
            value={seed}
            onChange={(e) => {
              setSeed(e.target.value)
              // Người dùng tự gõ đè lên cụm đã bắc cầu thì dòng vết không còn đúng nữa.
              setBridgedFrom(null)
            }}
            onKeyDown={(e) => e.key === 'Enter' && void search()}
          />
          {/* Từ gốc không thuộc thị trường ⇒ hai nút ĐỔI VAI. Bắc cầu thành nút chính, tìm
              từ khoá tụt xuống mờ.

              Đổi vai chứ không khoá: người dùng không phải đọc dòng nhắc nào cũng thấy ngay
              nút-trông-như-nút-cần-bấm chính là nút đúng. Còn giữ "Tìm từ khoá" bấm được vì
              có câu hỏi hợp lệ mà nó trả lời — "người Việt ở nước đó có tìm cụm này không". */}
          <button
            className={`btn ${seedOutOfMarket ? 'ghost' : ''}`}
            onClick={() => void search()}
            disabled={loading || !seed.trim()}
          >
            {loading ? (
              <>
                <span className="spinner" /> Đang tìm…
              </>
            ) : (
              'Tìm từ khoá'
            )}
          </button>
          <button className="btn ghost" onClick={() => void search(true)} disabled={loading || !seed.trim()}>
            Làm mới
          </button>
          {/* Chỉ hiện ở thị trường ngoài Việt Nam. Ở VN nó không có việc gì để làm — người
              dùng gõ tiếng Việt vào một thị trường nói tiếng Việt — và backend cũng trả về
              đúng câu đó, nên để nút ở lại chỉ là mời người ta bấm vào một chỗ rỗng.

              Danh sách nước nói tiếng Việt KHÔNG được chép sang đây; điều kiện là "khác VN",
              còn bản đồ ngôn ngữ thật nằm ở `backend/lib/keywords/market.py`. */}
          {country !== 'VN' && (
            <button
              className={`btn ${seedOutOfMarket ? '' : 'ghost'}`}
              onClick={() => void openBridge()}
              disabled={!seed.trim() || bridge?.loading}
              title="Từ gốc tiếng Việt: tìm xem người bản địa gọi ngành hàng này là gì, rồi đo từng cách trên Google Trends và Amazon"
            >
              Tìm cách gọi bản địa
            </button>
          )}
        </div>

        {/* Dấu vết của lần thay từ gốc. Xem `bridgedFrom`. */}
        {bridgedFrom && !seedOutOfMarket && (
          <p className="seed-hint">
            {bridgedFrom} → <b>{seed}</b>{' '}
            <button
              className="linklike"
              onClick={() => {
                setSeed(bridgedFrom)
                setBridgedFrom(null)
              }}
            >
              đổi lại
            </button>
          </p>
        )}

        {bridge && (
          <SeedBridge
            state={bridge}
            countryLabel={countryLabel}
            onPick={(term) => {
              // Chỉ ghi dấu vết khi cụm cũ THẬT SỰ lệch thị trường. Người dùng đang gõ
              // "jacket" rồi đổi sang "hoodie" là đổi ý, không phải bắc cầu — dán nhãn
              // "jacket → hoodie" vào đó là kể một câu chuyện không xảy ra.
              setBridgedFrom(seedOutOfMarket ? seed.trim() : null)
              setSeed(term)
              setBridge(undefined)
            }}
            onClose={() => setBridge(undefined)}
          />
        )}

        <div className="filters">
          <div className="field">
            <label>Nguồn</label>
            <div className="chips">
              {allSources.map((source) => {
                const available = servesMarket(source)
                // Thị trường mà bấm vào sẽ chuyển tới. Cùng luật với `pick`, và tính ở đây để
                // câu nhắc nói ĐÚNG tên nước sắp nhảy sang chứ không nói chung chung.
                const jumpTo = available
                  ? null
                  : source.markets?.includes(DEFAULT_COUNTRY)
                    ? DEFAULT_COUNTRY
                    : source.markets?.[0]
                const jumpLabel = jumpTo ? (countryNames[jumpTo] ?? jumpTo) : null
                return (
                  <button
                    key={source.id}
                    className="chip"
                    // Ở chế độ Tổng hợp KHÔNG ô nguồn nào sáng, chỉ ô Tổng hợp sáng. Sáng hết
                    // thì dãy chip không còn nói được nó là radio hay checkbox.
                    data-on={!isCombined && selected.includes(source.id)}
                    // CỐ Ý không `disabled` và cố ý KHÔNG có dấu hiệu hình ảnh nào. Mọi chip
                    // trông giống nhau vì mọi chip đều bấm được: nguồn ngoài thị trường đang
                    // chọn thì `pick` tự chuyển ô Quốc gia sang nước nó phục vụ.
                    //
                    // Đã thử ba kiểu đánh dấu và bỏ cả ba — xem chú thích ở `styles/controls.css`.
                    // Điều duy nhất cần nói được nói bằng câu nhắc bên dưới.
                    title={
                      available
                        ? undefined
                        : `${source.label} không phục vụ ${countryLabel} — bấm để chuyển sang ${jumpLabel}`
                    }
                    onClick={() => pick(source.id)}
                  >
                    {source.label}
                  </button>
                )
              })}
              {/* Không phải một nguồn mà là một lựa chọn sẵn, nên nó không đến từ `allSources`
                  và được tách khỏi các ô nguồn bằng một đường kẻ. Tắt khi thị trường chỉ có
                  một nguồn phục vụ — lúc đó "tổng hợp" và chính nguồn đó là một.

                  Câu nhắc chỉ còn ở trạng thái TẮT, nơi nó trả lời một câu hỏi người dùng
                  thật sự có ("sao bấm không được"). Bản cũ liệt kê các nguồn sẽ gộp kèm cảnh
                  báo số lượt gọi, nhưng dãy chip ngay bên cạnh đã nói ra các nguồn rồi, còn
                  con số lượt gọi thì vừa là chi tiết nội bộ vừa lệch mỗi lần chỉnh độ sâu. */}
              <button
                className="chip preset"
                data-on={isCombined}
                disabled={availableSources.length < 2}
                title={
                  availableSources.length < 2 ? 'Thị trường này chỉ có một nguồn phục vụ' : undefined
                }
                onClick={pickCombined}
              >
                Tổng hợp
              </button>
            </div>
          </div>

          <div className="field">
            <label>
              Quốc gia
              {geoIsAdvisory && (
                <span
                  className="hint"
                  title="Endpoint gợi ý của TikTok không nhận tham số vùng — nó trả kết quả theo IP của máy chủ. Ô này vẫn có tác dụng: nó chọn ngôn ngữ của các cụm mở rộng dùng để moi ra long-tail."
                >
                  {' '}
                  — chỉ đổi ngôn ngữ
                </span>
              )}
            </label>
            <Dropdown
              value={country}
              options={countries}
              onChange={changeCountry}
              searchable
              searchPlaceholder="Tìm kiếm vị trí"
            />
          </div>

          {/* Hai ô này là khái niệm của riêng Google Trends. `SearchContext` vẫn chở chúng
              xuống mọi nguồn, nhưng Shopee và TikTok chỉ đọc `country` — nên khi tắt nguồn
              chấm chính, để chúng lại là bày ra hai nút không nối vào đâu cả. */}
          {hasPrimary && (
            <>
              <div className="field">
                <label>Thời gian</label>
                <Dropdown value={timeRange} options={timeOptions} onChange={setTimeRange} />
              </div>

              <div className="field">
                <label>Loại tìm kiếm</label>
                <Dropdown value={property} options={PROPERTIES} onChange={setProperty} />
              </div>
            </>
          )}
        </div>
      </section>

      <div className="notices">
        {/* Từng có ở đây một khối giải thích dài về việc Shopee/TikTok không cấp được lượng
            tìm. Đã gỡ theo yêu cầu: cột lượng tìm biến mất khi tắt nguồn chấm chính là điều
            tự nói lên rồi, và phần phương pháp luận thì được giải thích ngoài giao diện chứ
            không phải bằng một đoạn văn chiếm đầu trang mỗi lượt tìm. */}
        {/* Đứng TRƯỚC mọi dòng lỗi nguồn, và không mang màu lỗi.
            Khi từ gốc không thuộc thị trường đang chọn thì các dòng "Google lỗi: bảng rỗng"
            bên dưới đều là HỆ QUẢ của nó, không phải sự cố riêng — đọc chúng trước rồi mới
            đọc tới đây là đi sửa đúng thứ không hỏng. */}
        {result?.seedNotice && (
          <div className="notice info">
            {result.seedNotice}{' '}
            <button className="linklike" onClick={() => void openBridge()}>
              Tìm cách gọi bản địa
            </button>
          </div>
        )}
        {error && (
          <div className="notice bad">
            <strong>Lỗi:</strong> {error}
          </div>
        )}
        {failed.map((status, i) => (
          <div className="notice bad" key={i}>
            <strong>{labelOf[status.source] ?? status.source} lỗi:</strong> {status.message}
          </div>
        ))}
      </div>

      {/* Chỗ của bảng trong lúc chờ. Đặt TRƯỚC mọi nhánh khác vì `result` đã bị dọn về `null`
          khi bắt đầu tìm, nên nếu không có khối này thì vùng kết quả trống trơn và màn hình
          trông như đã xong mà không ra gì. */}
      {loading && (
        <div className="empty">
          <span className="spinner" /> Đang tìm từ khoá cho <b>{seed.trim()}</b>…
        </div>
      )}

      {result && result.keywords.length > 0 && (
        <KeywordTable
          rows={rows}
          timeLabel={timeLabel}
          sources={activeSources}
          sourceTotals={result.sourceTotals}
          showDemand={hasPrimary}
          gloss={gloss.entries}
          glossLoading={gloss.loading}
        />
      )}

      {/* Lời báo về phần dịch nằm DƯỚI bảng, không phải trên đầu trang.
          "Chưa cấu hình GEMINI_API_KEY" là một ghi chú, không phải sự cố — đặt nó cạnh chỗ
          lẽ ra có nghĩa tiếng Việt thì người đọc hiểu ngay nó nói về cái gì, còn đẩy lên đầu
          trang cùng khối `notices` là biến nó thành thứ trông như bảng bên dưới bị sai. */}
      {result && result.keywords.length > 0 && gloss.message && (
        <p className="muted small gloss-note">{gloss.message}</p>
      )}

      {result && result.keywords.length === 0 && !loading && (
        <div className="empty">
          Không tìm được từ khoá nào. Thử từ khoá gốc ngắn hơn — vd &ldquo;jeans&rdquo; thay vì &ldquo;quần jeans
          nam ống rộng&rdquo;.
        </div>
      )}

      {!result && !loading && !error && (
        <div className="empty">
          Nhập từ khoá gốc của ngành hàng để mở rộng ra các biến thể đang được tìm kiếm.
          <br />
          Ví dụ: <b>quần jeans</b> → quần jeans ống rộng, quần jeans suông nữ, quần jeans lửng, quần jeans rách
          gối…
        </div>
      )}
    </>
  )
}
