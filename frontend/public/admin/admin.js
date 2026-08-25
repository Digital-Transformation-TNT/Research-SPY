/*
 * Trang admin — CRUD user + xem thống kê.
 *
 * GATE: bắt buộc role='admin'. User thường vào /admin/ sẽ bị đá về /research/. Không có JWT
 * → về /login/. Đây là gate CLIENT-SIDE để UX mượt; gate THẬT sự nằm ở backend admin.py
 * (mọi endpoint /api/admin/* trả 403 nếu role != admin, kể cả gọi thẳng bằng curl).
 */
(function () {
  const $ = (id) => document.getElementById(id);

  // ---- Gate ----
  const token = localStorage.getItem('rs_token');
  const role = localStorage.getItem('rs_role') || 'user';
  const uname = localStorage.getItem('rs_username') || '';
  if (!token && !uname) { window.location.replace('/login'); return; }
  if (role !== 'admin') { window.location.replace('/ads'); return; }
  $('whoami').textContent = uname ? `Xin chào ${uname}` : '';

  // ---- Fetch helper có JWT + auto redirect nếu 401 ----
  async function api(url, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const r = await fetch(url, Object.assign({}, options, { headers }));
    if (r.status === 401) {
      ['rs_token', 'rs_username', 'rs_role', 'rs_user_id'].forEach((k) => localStorage.removeItem(k));
      window.location.replace('/login');
      throw new Error('Phiên hết hạn');
    }
    return r;
  }

  // ---- Logout ----
  $('logoutBtn').addEventListener('click', () => {
    ['rs_token', 'rs_username', 'rs_role', 'rs_user_id'].forEach((k) => localStorage.removeItem(k));
    window.location.replace('/login');
  });

  // ---- Tab switching ----
  function showTab(which) {
    $('tabUsers').style.display = which === 'users' ? '' : 'none';
    $('tabStats').style.display = which === 'stats' ? '' : 'none';
    $('tabUsersBtn').classList.toggle('on', which === 'users');
    $('tabStatsBtn').classList.toggle('on', which === 'stats');
    if (which === 'stats') loadStats(currentPeriod);
  }
  $('tabUsersBtn').addEventListener('click', () => showTab('users'));
  $('tabStatsBtn').addEventListener('click', () => showTab('stats'));

  // ---- Users tab ----
  function setStatus(msg, kind) {
    const el = $('addStatus');
    el.textContent = msg || '';
    el.className = 'status' + (kind ? ' ' + kind : '');
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

  function fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (days === 0) return 'hôm nay';
    if (days === 1) return 'hôm qua';
    if (days < 30) return days + ' ngày trước';
    return d.toLocaleDateString('vi-VN');
  }

  // Badge trạng thái duyệt.
  function statusBadge(s) {
    if (s === 'pending') return '<span class="badge pending">⏳ Chờ duyệt</span>';
    if (s === 'rejected') return '<span class="badge off">✕ Từ chối</span>';
    return '<span class="badge on">✓ Đã duyệt</span>';
  }

  async function loadUsers() {
    try {
      const r = await api('/api/admin/users');
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      const rows = data.users || [];
      const pendingCount = data.pending_count || 0;

      // Badge đếm trên tab "Người dùng".
      $('tabUsersBtn').innerHTML = '👥 Người dùng' + (pendingCount ? ` <span class="tab-count">${pendingCount}</span>` : '');

      // TÁCH 2 nhóm: pending → bảng riêng phía trên; còn lại (đã duyệt / từ chối) → danh sách chính.
      const pending = rows.filter((u) => u.status === 'pending');
      const others = rows.filter((u) => u.status !== 'pending');

      // --- Bảng yêu cầu chờ duyệt (chỉ hiện khi có) ---
      $('pendingPanel').style.display = pending.length ? '' : 'none';
      $('pendingCount').textContent = pending.length || '';
      $('pendingRows').innerHTML = pending.map((u) => `
        <tr data-id="${esc(u.id)}">
          <td><b>${esc(u.username)}</b></td>
          <td>${fmtDate(u.created_at)}</td>
          <td>
            <button class="mini approve" data-act="approve">✓ Duyệt</button>
            <button class="mini danger" data-act="reject">✕ Từ chối</button>
          </td>
        </tr>`).join('');

      // --- Danh sách user chính (đã duyệt / từ chối) ---
      $('usersRows').innerHTML = others.map((u) => {
        // Từ chối → cho phép Duyệt lại; còn lại → quản lý bình thường.
        const reapprove = u.status === 'rejected'
          ? `<button class="mini approve" data-act="approve">✓ Duyệt lại</button>`
          : '';
        return `
        <tr data-id="${esc(u.id)}">
          <td><b>${esc(u.username)}</b></td>
          <td><span class="badge ${u.role}">${u.role}</span></td>
          <td>${statusBadge(u.status)}</td>
          <td>${fmtDate(u.last_login_at)}</td>
          <td>${fmtDate(u.created_at)}</td>
          <td>
            ${reapprove}
            <button class="mini" data-act="role" data-role="${u.role === 'admin' ? 'user' : 'admin'}">${u.role === 'admin' ? '↓ Hạ user' : '↑ Nâng admin'}</button>
            <button class="mini" data-act="toggle" data-active="${u.is_active ? 'false' : 'true'}">${u.is_active ? 'Khoá' : 'Mở'}</button>
            <button class="mini danger" data-act="delete">Xoá</button>
          </td>
        </tr>`;
      }).join('');
    } catch (e) {
      setStatus('Không load được danh sách: ' + e.message, 'err');
    }
  }

  // Delegate mọi action nút trong CẢ HAI bảng (chờ duyệt + danh sách chính) — 1 handler dùng chung.
  const onRowAction = async (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const row = btn.closest('tr[data-id]');
    const id = row.getAttribute('data-id');
    const act = btn.getAttribute('data-act');
    const uname = row.querySelector('td b').textContent;
    let opts;
    if (act === 'role') {
      const newRole = btn.getAttribute('data-role');
      if (!confirm(`Đổi role của "${uname}" thành ${newRole}?`)) return;
      opts = { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: newRole }) };
    } else if (act === 'toggle') {
      const newActive = btn.getAttribute('data-active') === 'true';
      if (!confirm(`${newActive ? 'Mở khoá' : 'Khoá'} user "${uname}"?`)) return;
      opts = { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: newActive }) };
    } else if (act === 'delete') {
      if (!confirm(`XOÁ VĨNH VIỄN user "${uname}"? Analytics event của họ vẫn giữ (user_id → null).`)) return;
      opts = { method: 'DELETE' };
    } else if (act === 'approve') {
      if (!confirm(`Duyệt cho "${uname}" vào dùng tool?`)) return;
      opts = { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'approved' }) };
    } else if (act === 'reject') {
      if (!confirm(`Từ chối yêu cầu của "${uname}"?`)) return;
      opts = { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'rejected' }) };
    }
    try {
      const r = await api(`/api/admin/users/${id}`, opts);
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      loadUsers();
    } catch (err) {
      setStatus(err.message, 'err');
    }
  };
  $('usersRows').addEventListener('click', onRowAction);
  $('pendingRows').addEventListener('click', onRowAction);

  // Thêm user
  $('addBtn').addEventListener('click', async () => {
    const username = ($('newUsername').value || '').trim().toLowerCase();
    const role = $('newRole').value;
    if (!username) { setStatus('Nhập username.', 'err'); return; }
    if (!/^[a-z0-9._-]+$/.test(username)) { setStatus('Username chỉ dùng chữ/số/. _ -', 'err'); return; }
    try {
      const r = await api('/api/admin/users', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, role }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      $('newUsername').value = '';
      setStatus(`Đã thêm "${username}" (${role}).`, 'ok');
      loadUsers();
    } catch (e) {
      setStatus(e.message, 'err');
    }
  });

  // ---- Stats tab ----
  let currentPeriod = 'week';
  document.querySelectorAll('.period-picker button').forEach((b) => {
    b.addEventListener('click', () => {
      currentPeriod = b.getAttribute('data-period');
      document.querySelectorAll('.period-picker button').forEach((x) => x.classList.toggle('on', x === b));
      loadStats(currentPeriod);
    });
  });

  function fmtCompact(n) {
    if (typeof n !== 'number' || !isFinite(n)) return '—';
    if (n < 1000) return String(n);
    if (n < 1_000_000) return (n / 1000).toFixed(1).replace('.', ',') + 'K';
    return (n / 1_000_000).toFixed(1).replace('.', ',') + 'M';
  }

  function fmtDelta(curr, prev, trend, invert) {
    if (curr == null || prev == null) return '';
    // invert = KPI mà giảm là tốt (vd thời gian/task) — đảo mũi tên xanh/đỏ nhưng số vẫn hiển thị thật.
    const arrow = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→';
    const cls = trend === 'flat' ? '' : (invert ? (trend === 'down' ? 'up' : 'down') : trend);
    const delta = prev === 0 ? '' : ` (${(((curr - prev) / prev) * 100).toFixed(0)}%)`;
    return `<div class="kpi-delta ${cls}">${arrow} kỳ trước: ${fmtCompact(prev)}${delta}</div>`;
  }

  async function loadStats(period) {
    $('kpiGrid').innerHTML = '<div class="kpi-card"><div class="kpi-label">Đang tải…</div></div>';
    try {
      const r = await api(`/api/admin/stats?period=${period}`);
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      const c = data.current, p = data.previous, t = data.trends || {};
      $('kpiGrid').innerHTML = `
        <div class="kpi-card">
          <div class="kpi-label">Weekly Active Users</div>
          <div class="kpi-value">${fmtCompact(c.wau)}</div>
          ${fmtDelta(c.wau, p.wau, t.wau)}
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Task Success Rate</div>
          <div class="kpi-value">${c.task_success_rate ?? '—'}%</div>
          ${fmtDelta(c.task_success_rate, p.task_success_rate, t.task_success_rate)}
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Thời gian TB / task</div>
          <div class="kpi-value">${c.avg_time_min != null ? c.avg_time_min + ' phút' : '—'}</div>
          ${fmtDelta(c.avg_time_min, p.avg_time_min, t.avg_time_min, true)}
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Giờ tiết kiệm</div>
          <div class="kpi-value">${fmtCompact(c.hours_saved)} h</div>
          ${fmtDelta(c.hours_saved, p.hours_saved, t.hours_saved)}
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Số lượt search</div>
          <div class="kpi-value">${fmtCompact(c.search_count)}</div>
          <div class="kpi-delta">kỳ trước: ${fmtCompact(p.search_count)}</div>
        </div>
      `;
    } catch (e) {
      $('kpiGrid').innerHTML = `<div class="kpi-card"><div class="kpi-label" style="color:var(--bad)">Lỗi: ${esc(e.message)}</div></div>`;
    }
  }

  // ---- Khởi động ----
  loadUsers();
})();
