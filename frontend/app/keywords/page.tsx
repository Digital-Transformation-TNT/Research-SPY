import type { Metadata } from 'next'
import KeywordResearch from '@/components/keywords/KeywordResearch'
import BackendDown from '@/components/layout/BackendDown'
import { fetchKeywordSourceDescriptors, fetchMarketMap } from '@/lib/keywords/providers'
import { BackendDownError } from '@/lib/api'

export const metadata: Metadata = {
  title: 'Keyword — Research SPY',
}

/**
 * Trang research từ khoá.
 *
 * Server component: hỏi backend sổ đăng ký nguồn gợi ý rồi truyền xuống giao diện, giống hệt
 * cách trang Quảng cáo làm. Thêm một nguồn mới là nó tự hiện lên đây.
 */
export const dynamic = 'force-dynamic'

export default async function KeywordsPage() {
  try {
    // Hai lượt hỏi độc lập nhau nên chạy song song — trang không có lý do gì đợi lượt thứ hai
    // sau khi lượt thứ nhất xong.
    //
    // Bảng thị trường được phép VẮNG: một backend cũ chưa có endpoint đó thì trang vẫn phải
    // dựng đủ, chỉ mất phần nhắc lệch ngôn ngữ. Đổi một tính năng phụ thành cả trang trắng là
    // cái giá không đáng, và đã có tiền lệ ngay trong file này (xem `declaresPrimary`).
    const [sources, marketMap] = await Promise.all([
      fetchKeywordSourceDescriptors(),
      fetchMarketMap().catch(() => ({})),
    ])

    /**
     * "Nguồn nào là chấm chính" được chốt ĐÚNG MỘT LẦN ở đây, kể cả khi backend không nói.
     *
     * Cờ `primary` là thứ quyết định cả hình dạng màn hình bên dưới — có nó thì hiện đủ ba ô
     * chọn của Trends và cột lượng tìm, không có thì rơi về chế độ chỉ-sàn. Nên một backend
     * cũ chưa công bố trường này sẽ làm CẢ chế độ Google biến mất: không nguồn nào `primary`
     * nghĩa là tick Google một mình cũng bị đọc thành "không có nguồn chấm chính". Đã gặp
     * thật — một tiến trình uvicorn chạy từ phiên trước không tự cập nhật theo code.
     *
     * Hỏng theo kiểu đó rất khó lần ra, vì trang vẫn dựng bình thường và chỉ lặng lẽ thiếu
     * mất hai ô chọn. Rơi về nguồn ĐẦU TIÊN trong sổ đăng ký thì tệ nhất cũng chỉ là chọn
     * nhầm nguồn chính, và sổ đăng ký vốn đặt nguồn chính lên đầu.
     */
    const declaresPrimary = sources.some((s) => s.primary)

    return (
      <KeywordResearch
        markets={marketMap}
        sources={sources.map(({ id, label, markets, primary, geoTargeted }, index) => ({
          id,
          label,
          markets: markets ?? null,
          primary: declaresPrimary ? Boolean(primary) : index === 0,
          // Mặc định `true`: một nguồn cũ chưa công bố cờ này thì coi như có lọc theo vùng —
          // sai theo hướng im lặng, thay vì dán nhãn "không đổi theo nước" lên một nguồn có đổi.
          geoTargeted: geoTargeted ?? true,
        }))}
      />
    )
  } catch (error) {
    if (error instanceof BackendDownError) return <BackendDown message={error.message} />
    throw error
  }
}
