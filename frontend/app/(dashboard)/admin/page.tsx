'use client'

import { useCallback, useEffect, useState } from 'react'
import s from './admin.module.css'

/**
 * Trang quản trị — bản Next.js (thay cho public/admin/index.html + admin.js).
 *
 * GATE hai lớp: client-side ở đây cho UX mượt (không token → /login, không phải admin → /ads),
 * nhưng gate THẬT nằm ở backend — mọi /api/admin/* trả 403 nếu role != admin, kể cả gọi curl.
 * Nằm trong (dashboard) nên có sidebar chung; whoami/đăng-xuất do sidebar lo, trang chỉ còn
 * nội dung quản trị.
 *
 * API (đều kèm Authorization: Bearer <rs_token>):
 *   GET    /api/admin/users            → { users, pending_count }
 *   POST   /api/admin/users            → tạo tay (duyệt sẵn)
 *   PATCH  /api/admin/users/:id        → { role } | { is_active } | { status }
 *   DELETE /api/admin/users/:id
 *   GET    /api/admin/stats?period=week|month → { current, previous, trends }
 */

const AUTH_KEYS = ['rs_token', 'rs_email', 'rs_display', 'rs_role', 'rs_user_id', 'rs_username']

type User = {
  id: string
  email?: string
  full_name?: string
  position?: string
  bu?: string
  role: 'admin' | 'user'
  status?: 'pending' | 'approved' | 'rejected'
  is_active?: boolean
  created_at?: string
  last_login_at?: string
}
type Stats = { current: any; previous: any; trends: any }

function clearAuthAndLogin() {
  AUTH_KEYS.forEach((k) => localStorage.removeItem(k))
  window.location.replace('/login')
}

/** fetch có JWT; 401 → dọn phiên và về /login. */
async function api(url: string, options: RequestInit = {}) {
  const token = localStorage.getItem('rs_token')
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) }
  if (token) headers['Authorization'] = 'Bearer ' + token
  const r = await fetch(url, { ...options, headers })
  if (r.status === 401) {
    clearAuthAndLogin()
    throw new Error('Phiên hết hạn')
  }
  return r
}

function fmtDate(iso?: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (days === 0) return 'hôm nay'
  if (days === 1) return 'hôm qua'
  if (days < 30) return days + ' ngày trước'
  return d.toLocaleDateString('vi-VN')
}

function fmtCompact(n: any) {
  if (typeof n !== 'number' || !isFinite(n)) return '—'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return (n / 1000).toFixed(1).replace('.', ',') + 'K'
  return (n / 1_000_000).toFixed(1).replace('.', ',') + 'M'
}

const nameOf = (u: User) => u.full_name || u.email || '(không tên)'
const roleBu = (u: User) => [u.position, u.bu].filter(Boolean).join(' · ') || '—'

function StatusBadge({ status }: { status?: string }) {
  if (status === 'pending') return <span className={`${s.badge} ${s.badgePending}`}>⏳ Chờ duyệt</span>
  if (status === 'rejected') return <span className={`${s.badge} ${s.badgeOff}`}>✕ Từ chối</span>
  return <span className={`${s.badge} ${s.badgeOn}`}>✓ Đã duyệt</span>
}

function WhoCell({ u }: { u: User }) {
  const name = nameOf(u)
  const email = u.email || ''
  return (
    <>
      <b>{name}</b>
      {email && email !== name ? <div className={s.sub}>{email}</div> : null}
    </>
  )
}

/** Delta kỳ trước cho một KPI. invert = KPI mà giảm là tốt (đảo màu mũi tên, số vẫn thật). */
function Delta({ curr, prev, trend, invert }: { curr: any; prev: any; trend?: string; invert?: boolean }) {
  if (curr == null || prev == null) return null
  const arrow = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→'
  const cls = trend === 'flat' || !trend ? '' : invert ? (trend === 'down' ? s.up : s.down) : trend === 'up' ? s.up : s.down
  const delta = prev === 0 ? '' : ` (${(((curr - prev) / prev) * 100).toFixed(0)}%)`
  return <div className={`${s.kpiDelta} ${cls}`}>{arrow} kỳ trước: {fmtCompact(prev)}{delta}</div>
}

export default function AdminPage() {
  const [ready, setReady] = useState(false)
  const [tab, setTab] = useState<'users' | 'stats'>('users')

  const [users, setUsers] = useState<User[]>([])
  const [addStatus, setAddStatus] = useState<{ text: string; kind: 'err' | 'ok' } | null>(null)
  const [form, setForm] = useState({ email: '', name: '', pos: '', bu: '', role: 'user' })

  const [period, setPeriod] = useState<'week' | 'month'>('week')
  const [stats, setStats] = useState<Stats | null>(null)
  const [statsErr, setStatsErr] = useState('')
  const [statsLoading, setStatsLoading] = useState(false)

  // ---- Gate: chờ mounted rồi mới quyết định, tránh nháy nội dung admin cho non-admin ----
  useEffect(() => {
    const token = localStorage.getItem('rs_token')
    const role = localStorage.getItem('rs_role') || 'user'
    const uname = localStorage.getItem('rs_display') || localStorage.getItem('rs_email') || ''
    if (!token && !uname) return void window.location.replace('/login')
    if (role !== 'admin') return void window.location.replace('/ads')
    setReady(true)
  }, [])

  const loadUsers = useCallback(async () => {
    try {
      const r = await api('/api/admin/users')
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
      setUsers(data.users || [])
    } catch (e: any) {
      setAddStatus({ text: 'Không load được danh sách: ' + e.message, kind: 'err' })
    }
  }, [])

  const loadStats = useCallback(async (p: 'week' | 'month') => {
    setStatsLoading(true)
    setStatsErr('')
    try {
      const r = await api(`/api/admin/stats?period=${p}`)
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
      setStats(data)
    } catch (e: any) {
      setStatsErr(e.message)
      setStats(null)
    } finally {
      setStatsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (ready) loadUsers()
  }, [ready, loadUsers])
  useEffect(() => {
    if (ready && tab === 'stats') loadStats(period)
  }, [ready, tab, period, loadStats])

  // ---- Thao tác trên một dòng user ----
  async function rowAction(u: User, act: 'approve' | 'reject' | 'role' | 'toggle' | 'delete') {
    const uname = nameOf(u)
    let opts: RequestInit | undefined
    let url = `/api/admin/users/${u.id}`
    const json = (body: any): RequestInit => ({
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (act === 'role') {
      const newRole = u.role === 'admin' ? 'user' : 'admin'
      if (!confirm(`Đổi role của "${uname}" thành ${newRole}?`)) return
      opts = json({ role: newRole })
    } else if (act === 'toggle') {
      const newActive = !u.is_active
      if (!confirm(`${newActive ? 'Mở khoá' : 'Khoá'} user "${uname}"?`)) return
      opts = json({ is_active: newActive })
    } else if (act === 'delete') {
      if (!confirm(`XOÁ VĨNH VIỄN user "${uname}"? Analytics event của họ vẫn giữ (user_id → null).`)) return
      opts = { method: 'DELETE' }
    } else if (act === 'approve') {
      if (!confirm(`Duyệt cho "${uname}" vào dùng tool?`)) return
      opts = json({ status: 'approved' })
    } else if (act === 'reject') {
      if (!confirm(`Từ chối yêu cầu của "${uname}"?`)) return
      opts = json({ status: 'rejected' })
    }
    try {
      const r = await api(url, opts)
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
      loadUsers()
    } catch (err: any) {
      setAddStatus({ text: err.message, kind: 'err' })
    }
  }

  async function addUser() {
    const email = form.email.trim().toLowerCase()
    if (!email) return setAddStatus({ text: 'Nhập email.', kind: 'err' })
    try {
      const r = await api('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, fullName: form.name.trim(), position: form.pos.trim(), bu: form.bu.trim(), role: form.role }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
      setForm({ email: '', name: '', pos: '', bu: '', role: 'user' })
      setAddStatus({ text: `Đã thêm "${email}" (${form.role}).`, kind: 'ok' })
      loadUsers()
    } catch (e: any) {
      setAddStatus({ text: e.message, kind: 'err' })
    }
  }

  if (!ready) return null

  const pending = users.filter((u) => u.status === 'pending')
  const others = users.filter((u) => u.status !== 'pending')

  return (
    <div className={s.admin}>
      <div className="page-head">
        <div>
          <h1>Quản trị</h1>
          <p>Duyệt &amp; quản lý người dùng, xem thống kê sử dụng tool.</p>
        </div>
      </div>

      <div className={s.tabs}>
        <button className={`${s.tab} ${tab === 'users' ? s.tabOn : ''}`} onClick={() => setTab('users')}>
          👥 Người dùng
          {pending.length ? <span className={s.tabCount}>{pending.length}</span> : null}
        </button>
        <button className={`${s.tab} ${tab === 'stats' ? s.tabOn : ''}`} onClick={() => setTab('stats')}>
          📊 Thống kê
        </button>
      </div>

      {tab === 'users' && (
        <>
          <div className={s.panel}>
            <h2>Thêm user mới (duyệt sẵn)</h2>
            <div className={s.addUser}>
              <input type="email" placeholder="email @tntecom.com" maxLength={120} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <input placeholder="Tên" maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <input placeholder="Vị trí (vd: R&D)" maxLength={120} value={form.pos} onChange={(e) => setForm({ ...form, pos: e.target.value })} />
              <input placeholder="BU (vd: BU1)" maxLength={120} value={form.bu} onChange={(e) => setForm({ ...form, bu: e.target.value })} />
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
              <button className={s.primary} onClick={addUser}>Thêm →</button>
            </div>
            {addStatus && <div className={`${s.status} ${addStatus.kind === 'err' ? s.statusErr : s.statusOk}`}>{addStatus.text}</div>}
          </div>

          {pending.length > 0 && (
            <div className={`${s.panel} ${s.panelPending}`}>
              <h2>⏳ Yêu cầu chờ duyệt <span className={s.tabCount}>{pending.length}</span></h2>
              <table className={s.table}>
                <thead>
                  <tr><th>Người dùng</th><th>Vị trí · BU</th><th>Ngày gửi</th><th>Thao tác</th></tr>
                </thead>
                <tbody>
                  {pending.map((u) => (
                    <tr key={u.id} className={s.rowPending}>
                      <td><WhoCell u={u} /></td>
                      <td>{roleBu(u)}</td>
                      <td>{fmtDate(u.created_at)}</td>
                      <td>
                        <button className={`${s.mini} ${s.approve}`} onClick={() => rowAction(u, 'approve')}>✓ Duyệt</button>
                        <button className={`${s.mini} ${s.danger}`} onClick={() => rowAction(u, 'reject')}>✕ Từ chối</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className={s.panel}>
            <h2>Danh sách user</h2>
            <table className={s.table}>
              <thead>
                <tr><th>Người dùng</th><th>Vị trí · BU</th><th>Quyền</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th>Thao tác</th></tr>
              </thead>
              <tbody>
                {others.map((u) => (
                  <tr key={u.id}>
                    <td><WhoCell u={u} /></td>
                    <td>{roleBu(u)}</td>
                    <td><span className={`${s.badge} ${u.role === 'admin' ? s.badgeAdmin : s.badgeUser}`}>{u.role}</span></td>
                    <td><StatusBadge status={u.status} /></td>
                    <td>{fmtDate(u.last_login_at)}</td>
                    <td>
                      {u.status === 'rejected' && (
                        <button className={`${s.mini} ${s.approve}`} onClick={() => rowAction(u, 'approve')}>✓ Duyệt lại</button>
                      )}
                      <button className={s.mini} onClick={() => rowAction(u, 'role')}>{u.role === 'admin' ? '↓ Hạ user' : '↑ Nâng admin'}</button>
                      <button className={s.mini} onClick={() => rowAction(u, 'toggle')}>{u.is_active ? 'Khoá' : 'Mở'}</button>
                      <button className={`${s.mini} ${s.danger}`} onClick={() => rowAction(u, 'delete')}>Xoá</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === 'stats' && (
        <>
          <div className={s.periodPicker}>
            <button className={period === 'week' ? s.periodOn : ''} onClick={() => setPeriod('week')}>7 ngày</button>
            <button className={period === 'month' ? s.periodOn : ''} onClick={() => setPeriod('month')}>30 ngày</button>
          </div>

          <div className={s.kpiGrid}>
            {statsLoading || (!stats && !statsErr) ? (
              <div className={s.kpiCard}><div className={s.kpiLabel}>Đang tải…</div></div>
            ) : statsErr ? (
              <div className={s.kpiCard}><div className={s.kpiLabel} style={{ color: 'var(--bad)' }}>Lỗi: {statsErr}</div></div>
            ) : stats ? (
              <>
                <div className={s.kpiCard}>
                  <div className={s.kpiLabel}>Weekly Active Users</div>
                  <div className={s.kpiValue}>{fmtCompact(stats.current.wau)}</div>
                  <Delta curr={stats.current.wau} prev={stats.previous.wau} trend={stats.trends?.wau} />
                </div>
                <div className={s.kpiCard}>
                  <div className={s.kpiLabel}>Task Success Rate</div>
                  <div className={s.kpiValue}>{stats.current.task_success_rate ?? '—'}%</div>
                  <Delta curr={stats.current.task_success_rate} prev={stats.previous.task_success_rate} trend={stats.trends?.task_success_rate} />
                </div>
                <div className={s.kpiCard}>
                  <div className={s.kpiLabel}>Thời gian TB / task</div>
                  <div className={s.kpiValue}>{stats.current.avg_time_min != null ? stats.current.avg_time_min + ' phút' : '—'}</div>
                  <Delta curr={stats.current.avg_time_min} prev={stats.previous.avg_time_min} trend={stats.trends?.avg_time_min} invert />
                </div>
                <div className={s.kpiCard}>
                  <div className={s.kpiLabel}>Giờ tiết kiệm</div>
                  <div className={s.kpiValue}>{fmtCompact(stats.current.hours_saved)} h</div>
                  <Delta curr={stats.current.hours_saved} prev={stats.previous.hours_saved} trend={stats.trends?.hours_saved} />
                </div>
                <div className={s.kpiCard}>
                  <div className={s.kpiLabel}>Số lượt search</div>
                  <div className={s.kpiValue}>{fmtCompact(stats.current.search_count)}</div>
                  <div className={s.kpiDelta}>kỳ trước: {fmtCompact(stats.previous.search_count)}</div>
                </div>
              </>
            ) : null}
          </div>

          <div className={s.panel}>
            <h2>Ghi chú</h2>
            <ul className={s.notes}>
              <li><b>WAU</b>: số user riêng biệt hoạt động trong kỳ.</li>
              <li><b>Task Success Rate</b>: % user vừa search vừa có click (product/video) — đo xấp xỉ.</li>
              <li><b>Thời gian trung bình/task</b>: từ event <code>session_end</code>, đơn vị phút.</li>
              <li><b>Giờ tiết kiệm</b>: baseline 30 phút thủ công × số task hoàn tất − thời gian thực tế.</li>
              <li><b>Trend</b>: so với kỳ trước ±5%. Thời gian ít hơn là ↑ tốt (đảo dấu).</li>
            </ul>
          </div>
        </>
      )}
    </div>
  )
}
