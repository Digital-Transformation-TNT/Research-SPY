-- ===========================================================================
-- MIGRATION: đăng nhập bằng EMAIL công ty + hồ sơ (Tên · Vị trí · BU)
-- Chạy 1 lần trong Supabase SQL Editor. Idempotent (chạy lại không lỗi).
-- ===========================================================================
-- Luồng mới: user nhập email @tntecom.com → nếu chưa có phải khai Tên/Vị trí/BU → gửi request
-- → admin duyệt → vào dùng. Tên hiển thị = "Tên · Vị trí · BU".

-- 1. Thêm cột hồ sơ.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email     TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS position  TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bu        TEXT;

-- 2. Email là định danh đăng nhập → duy nhất (chỉ ràng buộc khi có giá trị, cho phép NULL cũ).
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL;

-- 3. Admin hiện có (seed cũ 'titus') → gán EMAIL + hồ sơ để đăng nhập theo luồng mới.
--    LƯU Ý: `position` = CHỨC DANH công việc (Trưởng nhóm, Chuyên viên...), KHÔNG phải role hệ
--    thống (admin/user). role nằm ở cột `role` riêng. Đổi các giá trị dưới cho đúng người.
UPDATE users
SET email = 'tuyengm@tntecom.com',
    full_name = COALESCE(full_name, 'Tên admin'),
    position = COALESCE(position, 'Trưởng nhóm Research'),
    bu = COALESCE(bu, 'Ecom'),
    status = 'approved'
WHERE role = 'admin' AND email IS NULL;

-- 4. (Kiểm tra)
-- SELECT email, full_name, position, bu, role, status FROM users ORDER BY created_at;
