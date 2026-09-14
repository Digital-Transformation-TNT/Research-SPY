'use client'

/**
 * Phân trang dùng chung cho Toplist và Khám phá.
 *
 * Trần hiển thị là 200 sản phẩm chia 3 trang (chốt 14/09/2026). Cả 200 thẻ đổ một lượt thì
 * trang dài hàng chục màn hình và cuộn nặng; chia trang giữ mỗi màn một nhóm đọc được, mà
 * vẫn không phải bấm sang ngành khác mới xem tiếp.
 *
 * KHÔNG tự dựng khi chỉ có một trang — một dãy nút chỉ có mỗi số "1" là thứ trang trí gây
 * hiểu nhầm là còn trang sau.
 */
export default function Pager({
  trang,
  soTrang,
  onTrang,
}: {
  trang: number
  soTrang: number
  onTrang: (t: number) => void
}) {
  if (soTrang <= 1) return null
  const di = (t: number) => {
    onTrang(t)
    // Sang trang mới mà màn hình vẫn ở cuối danh sách cũ thì người xem thấy một trang trống
    // giữa chừng và tưởng hết dữ liệu.
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  return (
    <nav className="ts-pager" aria-label="Phân trang">
      <button className="chip" disabled={trang <= 1} onClick={() => di(trang - 1)}>
        ‹ Trước
      </button>
      {Array.from({ length: soTrang }, (_, i) => i + 1).map((t) => (
        <button
          key={t}
          className="chip"
          data-on={t === trang}
          aria-current={t === trang ? 'page' : undefined}
          onClick={() => di(t)}
        >
          {t}
        </button>
      ))}
      <button className="chip" disabled={trang >= soTrang} onClick={() => di(trang + 1)}>
        Sau ›
      </button>
    </nav>
  )
}
