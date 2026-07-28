/**
 * Màn hình hiện khi backend Python chưa chạy.
 *
 * Cần nói thẳng ra vì cách hỏng này trông giống hệt "công cụ hỏng": trang vẫn lên, sidebar
 * vẫn đúng, chỉ có phần nội dung trống. Một dòng chỉ đúng lệnh cần chạy tiết kiệm được cả
 * buổi mò của người mới nhận máy.
 */
export default function BackendDown({ message }: { message: string }) {
  return (
    <div className="notice bad" style={{ marginTop: 24 }}>
      <strong>Chưa kết nối được tầng dữ liệu.</strong>
      <p style={{ margin: '8px 0' }}>{message}</p>
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
        cd backend{'\n'}
        python -m uvicorn app.main:app --port 8000
      </pre>
    </div>
  )
}
