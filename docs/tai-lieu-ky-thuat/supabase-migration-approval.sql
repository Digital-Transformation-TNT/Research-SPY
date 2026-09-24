-- ===========================================================================
-- MIGRATION: luồng DUYỆT user (approval flow) — chạy 1 lần trong Supabase SQL Editor
-- ===========================================================================
-- User mới nhập username → tạo bản ghi status='pending' (chờ duyệt), KHÔNG vào được app.
-- Admin duyệt (approved) / từ chối (rejected) ở trang Quản trị. Chỉ approved mới đăng nhập được.

-- 1. Thêm cột status. IF NOT EXISTS để chạy lại nhiều lần không lỗi.
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'
  CHECK (status IN ('pending', 'approved', 'rejected'));

-- 2. MỌI user đang có (admin titus + ai đã tạo trước migration) phải được duyệt sẵn — nếu không
--    họ sẽ bị chặn login vì cột mới mặc định 'pending'.
UPDATE users SET status = 'approved' WHERE status = 'pending';

-- 3. (Kiểm tra) — xem lại danh sách sau migration:
-- SELECT username, role, status, is_active FROM users ORDER BY created_at;
