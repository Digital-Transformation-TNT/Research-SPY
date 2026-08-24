/**
 * Danh sách nguồn quảng cáo, đọc từ backend.
 *
 * Trước đây file này là sổ đăng ký thật và trang `/ads` import thẳng. Sau khi tầng dữ liệu
 * chuyển sang Python, sổ đăng ký nằm ở `backend/lib/ads/platforms/__init__.py` và giao diện
 * hỏi nó qua HTTP. Tính chất quan trọng vẫn giữ nguyên: **giao diện không hard-code nguồn
 * nào** — thêm một nguồn ở backend là nó tự hiện ra ở đây.
 */
import { serverGet } from '../api'
import type { PlatformCapabilities, PlatformOption } from './platform'
import type { PlatformId } from './types'

/** Mô tả rút gọn của một nguồn, đủ để giao diện dựng ô điều khiển. */
export type PlatformDescriptor = {
  id: PlatformId
  label: string
  capabilities: PlatformCapabilities
  options: PlatformOption[]
  /**
   * Các thị trường nguồn này phục vụ. `null` nghĩa là mọi thị trường.
   *
   * Nhờ trường này giao diện không phải đoán: nước nào không nguồn nào đang bật phục vụ thì
   * bị khoá kèm lý do, thay vì cho chọn rồi trả về một lưới rỗng không lời giải thích.
   */
  countries?: string[] | null
}

export async function fetchPlatformDescriptors(): Promise<PlatformDescriptor[]> {
  const data = await serverGet<{ platforms: PlatformDescriptor[] }>('/api/ads/platforms')
  return data.platforms
}
