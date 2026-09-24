-- ===========================================================================
-- SCHEMA GỐC cho Supabase — chạy MỘT LẦN trong SQL Editor trước khi dùng login
-- ===========================================================================
-- `.env.example` (mục TÀI KHOẢN NGƯỜI DÙNG) bảo chạy file này ở bước 3. Nó vốn thiếu trong
-- nhánh Titus: ở đó chỉ có `supabase-migration-approval.sql`, mà file ấy là `ALTER TABLE users`
-- — tức là nó GIẢ ĐỊNH bảng đã tồn tại và sẽ báo lỗi trên một project Supabase mới tinh.
--
-- File này dựng lại từ chính code đang chạy, không phải đoán:
--   users            app/api/auth.py, app/api/admin.py (_SELECT dòng 67)
--   analytics_event  lib/core/analytics.py::_insert, app/api/admin.py::stats
--
-- Project nào ĐÃ chạy migration approval rồi thì không cần file này nữa — mọi lệnh ở đây đều
-- IF NOT EXISTS nên chạy lại cũng không hỏng gì.

-- gen_random_uuid() nằm trong pgcrypto. Supabase bật sẵn, nhưng khai cho chắc.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─── users ─────────────────────────────────────────────────────────────────
-- Không có cột password: login là username-only, xem docstring đầu app/api/auth.py.
CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username      TEXT NOT NULL UNIQUE,
  role          TEXT NOT NULL DEFAULT 'user'
                  CHECK (role IN ('admin', 'user')),
  -- Luồng duyệt: user tự đăng nhập lần đầu → 'pending', admin duyệt → 'approved'.
  -- Chỉ 'approved' mới được cấp JWT.
  status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'approved', 'rejected')),
  -- Khoá tài khoản mà không xoá. Kiểm TRƯỚC status trong auth.py, nên is_active=false
  -- chặn được cả user đã duyệt.
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ
);

-- admin.py sắp xếp theo created_at giảm dần ở mỗi lần mở trang Quản trị.
CREATE INDEX IF NOT EXISTS users_created_at_idx ON users (created_at DESC);

-- ─── analytics_event ───────────────────────────────────────────────────────
-- Ghi fire-and-forget: lib/core/analytics.py nuốt mọi lỗi, hỏng bảng này KHÔNG kéo theo
-- tính năng chính. `meta` để JSONB vì mỗi loại event mang một hình dạng khác nhau.
CREATE TABLE IF NOT EXISTS analytics_event (
  id         BIGSERIAL PRIMARY KEY,
  -- Cho phép NULL: analytics.py vẫn ghi khi người dùng chưa đăng nhập (ẩn danh).
  -- ON DELETE SET NULL để xoá user ở trang Quản trị không làm mất luôn số liệu lịch sử.
  user_id    UUID REFERENCES users (id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  meta       JSONB NOT NULL DEFAULT '{}'::jsonb,
  ts         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- admin.py::stats quét theo khoảng thời gian (gte/lt trên ts) cho 5 KPI.
CREATE INDEX IF NOT EXISTS analytics_event_ts_idx      ON analytics_event (ts DESC);
CREATE INDEX IF NOT EXISTS analytics_event_user_ts_idx ON analytics_event (user_id, ts DESC);

-- ─── Admin đầu tiên ────────────────────────────────────────────────────────
-- BẮT BUỘC. Không có dòng này thì người đầu tiên đăng nhập sẽ thành 'pending' và
-- KHÔNG AI có quyền duyệt cho họ — app tự khoá chính nó.
-- Đổi 'titus' thành username của bạn rồi chạy.
INSERT INTO users (username, role, status, is_active)
VALUES ('titus', 'admin', 'approved', TRUE)
ON CONFLICT (username) DO UPDATE
  SET role = 'admin', status = 'approved', is_active = TRUE;

-- ─── Kiểm lại ──────────────────────────────────────────────────────────────
-- SELECT username, role, status, is_active, created_at FROM users ORDER BY created_at;
