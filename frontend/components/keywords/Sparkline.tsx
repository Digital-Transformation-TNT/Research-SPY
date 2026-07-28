import type { TrendSeries } from '@/lib/keywords/types'

/**
 * Đường quan tâm 12 tháng.
 *
 * Cố ý chuẩn hoá theo cực đại của chính nó. Trong một nhóm so sánh của Trends, giá trị thô
 * của một từ khoá nhỏ nằm sát đáy khi đặt cạnh từ gốc, nên vẽ chung thang sẽ làm mọi từ
 * long-tail thành một đường thẳng và giấu mất tính mùa vụ — thứ mà cả cái biểu đồ này sinh
 * ra để cho thấy. Độ lớn do con số "% so với từ gốc" bên cạnh gánh, còn hình dạng do đường.
 */
export default function Sparkline({
  series,
  width = 108,
  height = 30,
}: {
  series: TrendSeries
  width?: number
  height?: number
}) {
  const values = series.points.map((p) => p.value)
  if (values.length < 2) return null

  const max = Math.max(1, ...values)
  const step = width / (values.length - 1)
  const point = (v: number, i: number) =>
    `${(i * step).toFixed(1)} ${(height - (v / max) * (height - 3) - 1.5).toFixed(1)}`
  const line = values.map((v, i) => `${i === 0 ? 'M' : 'L'} ${point(v, i)}`).join(' ')
  const area = `${line} L ${width} ${height} L 0 ${height} Z`

  return (
    <svg
      width={width}
      height={height}
      className="spark"
      role="img"
      aria-label={`Xu hướng 12 tháng của ${series.keyword}`}
    >
      <path d={area} fill="currentColor" opacity="0.1" />
      <path d={line} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}
