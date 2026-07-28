import { redirect } from 'next/navigation'

/**
 * Trang gốc chỉ chuyển hướng.
 *
 * Hai mục lớn — Quảng cáo và Từ khoá — nằm ở hai đường dẫn ngang hàng nhau (`/ads` và
 * `/keywords`) thay vì một cái chiếm trang gốc. Nhờ vậy code của hai mục nằm ở hai thư mục
 * đối xứng, và nhìn vào một commit là biết ngay nó động vào mục nào.
 */
export default function RootPage() {
  redirect('/ads')
}
