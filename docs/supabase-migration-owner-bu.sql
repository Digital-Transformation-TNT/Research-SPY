-- ===========================================================================
-- MIGRATION 2026-09-10 — vai trò `owner`, BU chốt danh sách, và bảng xin đổi vai trò
--
-- Chạy trong SQL Editor của Supabase. Chạy lại nhiều lần được (idempotent).
--
-- BA VIỆC, và việc thứ ba PHỤ THUỘC việc thứ hai:
--   1. thêm vai trò 'owner' vào CHECK của users.role
--   2. dọn `bu` về đúng bốn mã BU1/BU2/BU3/HO  ← phải xong TRƯỚC khi thêm CHECK ở bước 3
--   3. khoá `bu` bằng CHECK, để cột này không quay lại thành ô chữ tự do
--
-- Vì sao phải dọn trước: bốn tài khoản đầu tiên đã ghi BU bằng ba cách khác nhau
-- ("Holding" ×2, "Hoding" ×1 — gõ thiếu chữ, "HO" ×1). Thêm CHECK trước khi dọn thì
-- Postgres từ chối tạo ràng buộc và migration chết giữa chừng.
-- ===========================================================================

-- ─── 1. Vai trò owner ──────────────────────────────────────────────────────
-- `owner` là vai trò DUY NHẤT nâng/hạ được admin. Admin không đổi vai trò của ai, kể cả của
-- người dùng thường — họ phải gửi yêu cầu cho owner (bảng `role_requests` bên dưới).
-- Xem `backend/app/api/admin.py::_require_owner`.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
  CHECK (role IN ('owner', 'admin', 'user'));

-- ─── 2. Dọn BU về danh sách chốt ───────────────────────────────────────────
-- "Holding"/"Hoding" là cùng một đơn vị và đã được chốt gộp về 'HO' (quyết định 2026-09-10).
-- Chuẩn hoá luôn cả hoa/thường và khoảng trắng: 'bu 1', 'Bu1' → 'BU1'.
UPDATE users
   SET bu = 'HO'
 WHERE bu IS NOT NULL
   AND upper(regexp_replace(bu, '[\s_-]', '', 'g')) IN ('HOLDING', 'HODING', 'HO');

UPDATE users
   SET bu = upper(regexp_replace(bu, '[\s_-]', '', 'g'))
 WHERE bu IS NOT NULL
   AND upper(regexp_replace(bu, '[\s_-]', '', 'g')) IN ('BU1', 'BU2', 'BU3');

-- Bất cứ giá trị nào KHÔNG nhận ra thì để trống, đừng đoán. Một BU đoán sai sẽ lặng lẽ áp sai
-- ngưỡng xanh cho người ấy, còn một ô trống thì admin nhìn trang Quản trị là thấy ngay.
UPDATE users
   SET bu = NULL
 WHERE bu IS NOT NULL
   AND bu NOT IN ('BU1', 'BU2', 'BU3', 'HO');

-- ─── 3. Khoá danh sách BU ──────────────────────────────────────────────────
-- NULL vẫn cho phép: tài khoản admin tạo tay có thể chưa điền BU. Chỉ cấm giá trị RÁC.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_bu_check;
ALTER TABLE users ADD CONSTRAINT users_bu_check
  CHECK (bu IS NULL OR bu IN ('BU1', 'BU2', 'BU3', 'HO'));

-- ─── 4. Chỉ định owner ─────────────────────────────────────────────────────
-- anhnv@tntecom.com (quyết định 2026-09-10). Phải có ÍT NHẤT MỘT owner, nếu không sẽ không ai
-- nâng/hạ được admin nữa và cách sửa duy nhất là chạy tay SQL.
UPDATE users SET role = 'owner' WHERE lower(email) = 'anhnv@tntecom.com';

-- ─── 5. Yêu cầu đổi vai trò ────────────────────────────────────────────────
-- Admin không tự nâng/hạ được nữa, nên phải có đường ĐỀ NGHỊ — nếu không thì cách duy nhất để
-- nâng một người là nhắn riêng cho owner, và không còn dấu vết ai xin gì, ai duyệt, lúc nào.
--
-- Cố ý KHÔNG dùng lại `users.status`: cột ấy trả lời "tài khoản này được vào tool chưa", còn
-- bảng này trả lời "có nên đổi vai trò người này không". Nhét chung thì một người bị từ chối
-- nâng quyền sẽ trông y hệt một người bị từ chối truy cập.
CREATE TABLE IF NOT EXISTS role_requests (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Người ĐƯỢC đề nghị đổi vai trò.
  target_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  -- Admin đứng ra đề nghị.
  requester_id  UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  -- Vai trò muốn đổi thành. 'owner' KHÔNG nằm ở đây: nhường quyền sở hữu là việc phải làm
  -- bằng tay có chủ đích, không phải thứ duyệt lướt trong một hàng danh sách.
  to_role       TEXT NOT NULL CHECK (to_role IN ('admin', 'user')),
  reason        TEXT,
  status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'approved', 'rejected')),
  -- Owner đã xử. NULL khi còn treo.
  decided_by    UUID REFERENCES users (id) ON DELETE SET NULL,
  decided_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trang Quản trị luôn hỏi "còn yêu cầu nào treo không", nên đánh chỉ mục đúng câu hỏi ấy.
CREATE INDEX IF NOT EXISTS role_requests_pending_idx
  ON role_requests (status, created_at DESC);

-- Mỗi người chỉ treo được MỘT yêu cầu tại một thời điểm. Thiếu ràng buộc này thì bấm hai lần
-- là owner thấy hai dòng giống hệt nhau và duyệt cái nào cũng đúng — rồi cái còn lại treo mãi.
CREATE UNIQUE INDEX IF NOT EXISTS role_requests_one_open_idx
  ON role_requests (target_id) WHERE status = 'pending';
