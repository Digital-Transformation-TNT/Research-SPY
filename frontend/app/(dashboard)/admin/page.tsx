'use client'

import { Fragment, useCallback, useEffect, useState } from 'react'
import { withBase } from '@/lib/basePath'
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
  role: 'owner' | 'admin' | 'user'
  status?: 'pending' | 'approved' | 'rejected'
  is_active?: boolean
  created_at?: string
  last_login_at?: string
}
type Stats = { current: any; previous: any; trends: any }

type UserStat = {
  user_id: string
  name: string
  email?: string
  bu?: string
  role?: string
  runs: number
  errs: number
  ok: number
  success_rate: number | null
  links: number
  tasks: number
  sessions: number
  avg_session_min: number | null
  last_active?: string | null
}
type ToolStat = {
  feature: string
  runs: number
  errs: number
  ok: number
  success_rate: number | null
  links: number
  tasks: number
}
type ByUser = {
  users: UserStat[]
  tools: ToolStat[]
  anon: { runs: number; errs: number; links: number; sessions: number } | null
}

type ActEvent = { ts?: string; event_type: string; feature?: string | null; label: string; error?: boolean }
type ActSession = {
  session_id: string
  device?: string | null
  duration_sec?: number | null
  tools_used?: string[]
  started?: string | null
  ended?: string | null
  links: number
  runs: number
  errs?: number
  events: ActEvent[]
}
type Activity = { loading: boolean; error?: string; sessions?: ActSession[]; truncated?: boolean }

/** Nhãn tool cho người đọc — khớp `feature` mà frontend bắn lên. */
const TOOL_LABEL: Record<string, string> = {
  keywords: 'Keyword',
  ads: 'Sản phẩm (Ads)',
  image: 'Image Search',
  'trend-signal': 'Trend Signal',
  oneshot: 'One-shot AI',
  opportunity: 'Cơ hội',
  khác: 'Khác',
}
const toolLabel = (f: string) => TOOL_LABEL[f] ?? f

/** Màu cho tỉ lệ thành công: xanh ≥60, vàng ≥30, đỏ dưới đó. `null` = chưa có task. */
function rateClass(rate: number | null, s: Record<string, string>) {
  if (rate == null) return ''
  if (rate >= 60) return s.rateGood
  if (rate >= 30) return s.rateMid
  return s.rateBad
}

function clearAuthAndLogin() {
  AUTH_KEYS.forEach((k) => localStorage.removeItem(k))
  window.location.replace(withBase('/login'))
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

/** Ngày giờ ngắn cho dòng thời gian: "17/09 09:02". */
function fmtWhen(iso?: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** Độ trễ một lượt chạy: giây (mặc định), đổi sang phút khi ≥60s. */
function fmtDur(sec: any) {
  if (typeof sec !== 'number' || !isFinite(sec)) return '—'
  if (sec < 60) return `${sec.toFixed(1).replace('.', ',')} giây`
  return `${(sec / 60).toFixed(1).replace('.', ',')} phút`
}

function fmtCompact(n: any) {
  if (typeof n !== 'number' || !isFinite(n)) return '—'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return (n / 1000).toFixed(1).replace('.', ',') + 'K'
  return (n / 1_000_000).toFixed(1).replace('.', ',') + 'M'
}

/** BU chốt danh sách — phải KHỚP `backend/lib/core/bu.py::BU_CHOICES` và trang đăng nhập. */
const BU_OPTIONS = ['BU1', 'BU2', 'BU3', 'HO']

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

/** Dòng thời gian hoạt động của một người — hiện khi bấm mở một dòng ở bảng theo nhân sự. */
function UserActivity({ act, s }: { act?: Activity; s: Record<string, string> }) {
  if (!act || act.loading) return <div className={s.actLoading}>Đang tải lịch sử…</div>
  if (act.error) return <div className={`${s.status} ${s.statusErr}`}>Lỗi: {act.error}</div>
  const sessions = act.sessions || []
  if (sessions.length === 0) return <div className={s.actLoading}>Chưa có hoạt động nào trong kỳ này.</div>
  return (
    <div className={s.act}>
      {sessions.map((se) => (
        <div className={s.actSession} key={se.session_id}>
          <div className={s.actHead}>
            <b>{fmtWhen(se.started)}</b>
            <span className={s.sub}>
              {se.device || '—'}
              {se.duration_sec ? ` · ${Math.round(se.duration_sec / 60)}′` : ''}
              {` · ${se.runs} chạy`}
              {se.errs ? ` · ${se.errs} lỗi` : ''}
              {` · ${se.links} link`}
              {se.tools_used && se.tools_used.length
                ? ` · ${se.tools_used.map(toolLabel).join(', ')}`
                : ''}
            </span>
          </div>
          <ol className={s.actList}>
            {se.events.map((e, i) => (
              <li key={i} className={s.actItem} data-kind={e.event_type} data-error={e.error ? '1' : undefined}>
                <span className={s.actTime}>{fmtWhen(e.ts).split(' ')[1] || ''}</span>
                <span className={s.actDot} />
                <span className={s.actLabel}>{e.label}</span>
              </li>
            ))}
          </ol>
        </div>
      ))}
      {act.truncated && (
        <p className={s.sub}>Chỉ hiện các event gần nhất (đã chạm trần) — thu hẹp kỳ để xem đủ.</p>
      )}
    </div>
  )
}

export default function AdminPage() {
  const [ready, setReady] = useState(false)
  const [tab, setTab] = useState<'users' | 'stats'>('users')
  //: Chỉ owner đổi được vai trò. Admin thấy nút "Xin đổi vai trò" để gửi yêu cầu.
  const [isOwner, setIsOwner] = useState(false)
  const [roleReqs, setRoleReqs] = useState<any[]>([])

  const [users, setUsers] = useState<User[]>([])
  const [addStatus, setAddStatus] = useState<{ text: string; kind: 'err' | 'ok' } | null>(null)
  const [form, setForm] = useState({ email: '', name: '', pos: '', bu: '', role: 'user' })

  const [period, setPeriod] = useState<'week' | 'month'>('week')
  const [stats, setStats] = useState<Stats | null>(null)
  const [statsErr, setStatsErr] = useState('')
  const [statsLoading, setStatsLoading] = useState(false)

  const [byUser, setByUser] = useState<ByUser | null>(null)
  const [byUserErr, setByUserErr] = useState('')
  //: User đang mở lịch sử (bấm một dòng để xem "dùng tới đâu"), và kho lịch sử theo user_id.
  const [openUser, setOpenUser] = useState<string | null>(null)
  const [activity, setActivity] = useState<Record<string, Activity>>({})

  // ---- Gate: chờ mounted rồi mới quyết định, tránh nháy nội dung admin cho non-admin ----
  useEffect(() => {
    const token = localStorage.getItem('rs_token')
    const role = localStorage.getItem('rs_role') || 'user'
    const uname = localStorage.getItem('rs_display') || localStorage.getItem('rs_email') || ''
    if (!token && !uname) return void window.location.replace(withBase('/login'))
    // `owner` PHẢI qua được cổng này. Kiểm `!== 'admin'` sẽ đá đúng người có nhiều quyền nhất
    // ra khỏi trang Quản trị, và họ là người duy nhất sửa được vai trò cho người khác.
    if (role !== 'admin' && role !== 'owner') return void window.location.replace(withBase('/ads'))
    setIsOwner(role === 'owner')
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

  //: Bảng theo nhân sự + theo tool. Tách khỏi `loadStats` để một cái hỏng không kéo cái kia.
  const loadByUser = useCallback(async (p: 'week' | 'month') => {
    setByUserErr('')
    try {
      const r = await api(`/api/admin/stats-by-user?period=${p}`)
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
      setByUser(data)
    } catch (e: any) {
      setByUserErr(e.message)
      setByUser(null)
    }
  }, [])

  //: Bấm một dòng user → tải (một lần) dòng thời gian hoạt động của họ.
  const toggleUser = useCallback(
    async (userId: string) => {
      if (openUser === userId) {
        setOpenUser(null)
        return
      }
      setOpenUser(userId)
      // Đã có trong kho (và không phải lần lỗi cần thử lại) thì khỏi gọi lại.
      if (activity[userId] && !activity[userId].error) return
      setActivity((prev) => ({ ...prev, [userId]: { loading: true } }))
      try {
        const r = await api(`/api/admin/user-activity?user_id=${encodeURIComponent(userId)}&period=${period}`)
        const data = await r.json()
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
        setActivity((prev) => ({
          ...prev,
          [userId]: { loading: false, sessions: data.sessions || [], truncated: data.truncated },
        }))
      } catch (e: any) {
        setActivity((prev) => ({ ...prev, [userId]: { loading: false, error: e.message } }))
      }
    },
    [openUser, activity, period],
  )

  // ---- Yêu cầu đổi vai trò (admin xin, owner duyệt) ----
  const loadRoleReqs = useCallback(async () => {
    try {
      const r = await api('/api/admin/role-requests')
      const data = await r.json()
      if (r.ok) setRoleReqs(data.requests || [])
    } catch {
      /* danh sách phụ — hỏng thì thôi, đừng chặn cả trang */
    }
  }, [])

  useEffect(() => {
    if (ready) {
      loadUsers()
      loadRoleReqs()
    }
  }, [ready, loadUsers, loadRoleReqs])
  useEffect(() => {
    if (ready && tab === 'stats') {
      loadStats(period)
      loadByUser(period)
      // Đổi kỳ → lịch sử đã tải là của kỳ cũ, dọn đi để lần mở sau tải lại đúng kỳ.
      setActivity({})
      setOpenUser(null)
    }
  }, [ready, tab, period, loadStats, loadByUser])

  async function askRoleChange(u: User, toRole: string) {
    const lyDo = prompt(
      `Xin owner đổi vai trò của "${nameOf(u)}" thành ${toRole}.

Lý do (owner sẽ đọc):`,
      '',
    )
    if (lyDo === null) return
    try {
      const r = await api('/api/admin/role-requests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ targetId: u.id, toRole, reason: lyDo }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
      setAddStatus({ text: `Đã gửi yêu cầu cho owner duyệt.`, kind: 'ok' })
      loadRoleReqs()
    } catch (err: any) {
      setAddStatus({ text: err.message, kind: 'err' })
    }
  }

  async function decideRoleReq(id: string, status: 'approved' | 'rejected') {
    if (!confirm(status === 'approved' ? 'Duyệt và đổi vai trò ngay?' : 'Từ chối yêu cầu này?')) return
    try {
      const r = await api(`/api/admin/role-requests/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
      loadRoleReqs()
      loadUsers()
    } catch (err: any) {
      setAddStatus({ text: err.message, kind: 'err' })
    }
  }

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
      // ADMIN KHÔNG ĐỔI THẲNG ĐƯỢC — cùng một nút, nhưng với admin nó MỞ MỘT YÊU CẦU cho owner
      // duyệt. Server chặn rồi (`_require_owner`); nhánh này để admin nhận được một đường đi
      // tiếp thay vì một thông báo 403 cụt.
      if (!isOwner) return void askRoleChange(u, newRole)
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
              {/* Ô CHỌN, khớp `backend/lib/core/bu.py::BU_CHOICES`. Admin gõ tay chính là chỗ
                  đã đẻ ra "Hoding"; và từ nay BU quyết định ngưỡng xanh nên gõ sai là áp sai
                  chính sách cho người được tạo. */}
              <select value={form.bu} onChange={(e) => setForm({ ...form, bu: e.target.value })}>
                <option value="">— BU —</option>
                {BU_OPTIONS.map((bu) => <option key={bu} value={bu}>{bu}</option>)}
              </select>
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="user">User</option>
                {/* Tạo thẳng một admin CŨNG LÀ nâng admin, nên chỉ owner thấy lựa chọn này —
                    server chặn nốt (`admin.py::create_user`). */}
                {isOwner && <option value="admin">Admin</option>}
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
            {roleReqs.length > 0 && (
              <div className={s.card} style={{ marginBottom: 16 }}>
                <h2>
                  {isOwner ? 'Yêu cầu đổi vai trò chờ duyệt' : 'Yêu cầu đổi vai trò bạn đã gửi'}
                  {' '}({roleReqs.filter((q) => q.status === 'pending').length})
                </h2>
                <table className={s.table}>
                  <thead>
                    <tr><th>Đổi cho ai</th><th>Thành</th><th>Người xin</th><th>Lý do</th><th>Trạng thái</th><th>Thao tác</th></tr>
                  </thead>
                  <tbody>
                    {roleReqs.map((q) => (
                      <tr key={q.id}>
                        <td><b>{q.target?.full_name || q.target?.email || q.target_id}</b></td>
                        <td><span className={s.badge}>{q.to_role}</span></td>
                        <td>{q.requester?.full_name || q.requester?.email || '—'}</td>
                        <td>{q.reason || '—'}</td>
                        <td><StatusBadge status={q.status} /></td>
                        <td>
                          {/* Chỉ owner mới có nút xử. Admin xem để biết yêu cầu của mình
                              đã tới đâu — thiếu cột này thì họ bấm xin lần nữa. */}
                          {isOwner && q.status === 'pending' ? (
                            <>
                              <button className={`${s.mini} ${s.approve}`} onClick={() => decideRoleReq(q.id, 'approved')}>✓ Duyệt</button>
                              <button className={`${s.mini} ${s.danger}`} onClick={() => decideRoleReq(q.id, 'rejected')}>✕ Từ chối</button>
                            </>
                          ) : (
                            <span className={s.sub}>{q.status === 'pending' ? 'chờ owner' : '—'}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

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
                    <td><span className={`${s.badge} ${u.role === 'admin' || u.role === 'owner' ? s.badgeAdmin : s.badgeUser}`}>{u.role}</span></td>
                    <td><StatusBadge status={u.status} /></td>
                    <td>{fmtDate(u.last_login_at)}</td>
                    <td>
                      {u.status === 'rejected' && (
                        <button className={`${s.mini} ${s.approve}`} onClick={() => rowAction(u, 'approve')}>✓ Duyệt lại</button>
                      )}
                      {/* Tài khoản owner không sửa/xoá được từ đây — server cũng chặn
                          (`admin.py::update_user`). Hiện nút rồi để nó báo 403 là bắt người
                          dùng thử mới biết. */}
                      {u.role === 'owner' ? (
                        <span className={s.sub}>owner — không sửa từ đây</span>
                      ) : (
                        <>
                          <button
                            className={s.mini}
                            onClick={() => rowAction(u, 'role')}
                            title={isOwner ? '' : 'Chỉ owner đổi được vai trò — nút này gửi yêu cầu cho owner'}
                          >
                            {isOwner
                              ? (u.role === 'admin' ? '↓ Hạ user' : '↑ Nâng admin')
                              : (u.role === 'admin' ? '✎ Xin hạ user' : '✎ Xin nâng admin')}
                          </button>
                          <button className={s.mini} onClick={() => rowAction(u, 'toggle')}>{u.is_active ? 'Khoá' : 'Mở'}</button>
                          <button className={`${s.mini} ${s.danger}`} onClick={() => rowAction(u, 'delete')}>Xoá</button>
                        </>
                      )}
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
                  <div className={s.kpiValue}>{fmtDur(stats.current.avg_time_sec)}</div>
                  <Delta curr={stats.current.avg_time_sec} prev={stats.previous.avg_time_sec} trend={stats.trends?.avg_time_sec} invert />
                </div>
                <div className={s.kpiCard}>
                  <div className={s.kpiLabel}>Số lượt chạy</div>
                  <div className={s.kpiValue}>{fmtCompact(stats.current.search_count)}</div>
                  <div className={s.kpiDelta}>kỳ trước: {fmtCompact(stats.previous.search_count)}</div>
                </div>
              </>
            ) : null}
          </div>

          {/* ── THEO NHÂN SỰ — ai dùng tốt, ai mở cho có ─────────────────────────────── */}
          <div className={s.panel}>
            <h2>Theo nhân sự</h2>
            {byUserErr ? (
              <div className={`${s.status} ${s.statusErr}`}>Lỗi: {byUserErr}</div>
            ) : !byUser ? (
              <p className={s.sub}>Đang tải…</p>
            ) : byUser.users.length === 0 ? (
              <p className={s.sub}>Chưa có event nào quy được về người trong kỳ này.</p>
            ) : (
              <table className={s.table}>
                <thead>
                  <tr>
                    <th></th>
                    <th>Người dùng</th>
                    <th>BU</th>
                    <th title="Số lần chạy tool: search từ khoá/quảng cáo, tra ảnh, hỏi AI, xem Trend">Chạy</th>
                    <th title="Số lần chạy bị lỗi (lag/giật, không truy cập được). Sàn trả 0 dữ liệu KHÔNG tính lỗi">Lỗi</th>
                    <th title="% lượt chạy ra kết quả (không lỗi)">%success</th>
                    <th title="Link ra ngoài: product_click + video_open + image_result_click — đo độ sâu research">Link ngoài</th>
                    <th title="Thời gian trung bình mỗi phiên">TB phiên</th>
                    <th>Hoạt động gần nhất</th>
                  </tr>
                </thead>
                <tbody>
                  {byUser.users.map((u) => {
                    const open = openUser === u.user_id
                    const act = activity[u.user_id]
                    return (
                      <Fragment key={u.user_id}>
                        <tr
                          className={s.userRow}
                          onClick={() => toggleUser(u.user_id)}
                          title="Bấm để xem lịch sử hoạt động"
                        >
                          <td className={s.caret}>{open ? '▾' : '▸'}</td>
                          <td>
                            <b>{u.name}</b>
                            {u.email && u.email !== u.name ? <div className={s.sub}>{u.email}</div> : null}
                          </td>
                          <td>{u.bu || '—'}</td>
                          <td>{fmtCompact(u.runs)}</td>
                          <td>{u.errs ? <span className={s.rateBad}>{fmtCompact(u.errs)}</span> : 0}</td>
                          <td>
                            {u.success_rate == null ? (
                              '—'
                            ) : (
                              <span className={rateClass(u.success_rate, s)}>{u.success_rate}%</span>
                            )}
                          </td>
                          <td>{fmtCompact(u.links)}</td>
                          <td>{u.avg_session_min != null ? `${u.avg_session_min}′` : '—'}</td>
                          <td>{fmtDate(u.last_active || undefined)}</td>
                        </tr>
                        {open && (
                          <tr className={s.actRow}>
                            <td colSpan={9}>
                              <UserActivity act={act} s={s} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            )}
            {byUser?.anon && (byUser.anon.runs > 0 || byUser.anon.links > 0) && (
              <p className={`${s.sub} ${s.anonNote}`}>
                ⚠️ Ẩn danh (chưa quy được về người): {fmtCompact(byUser.anon.runs)} lượt chạy ·{' '}
                {fmtCompact(byUser.anon.links)} link. Event không có vé nay đã bị chặn ghi — còn thấy
                dòng này là sót hiếm (vé hết hạn ngay lúc bấm) hoặc dữ liệu cũ.
              </p>
            )}
          </div>

          {/* ── THEO TOOL — tool nào ra kết quả ───────────────────────────────────────── */}
          {byUser && byUser.tools.length > 0 && (
            <div className={s.panel}>
              <h2>Theo tool</h2>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th title="Số lượt chạy tool">Chạy</th>
                    <th title="Số lượt lỗi (không truy cập được / lag)">Lỗi</th>
                    <th title="% lượt chạy ra kết quả (không lỗi)">%success</th>
                    <th title="Link ra ngoài — độ sâu research">Link ngoài</th>
                  </tr>
                </thead>
                <tbody>
                  {byUser.tools.map((t) => (
                    <tr key={t.feature}>
                      <td><b>{toolLabel(t.feature)}</b></td>
                      <td>{fmtCompact(t.runs)}</td>
                      <td>{t.errs ? <span className={s.rateBad}>{fmtCompact(t.errs)}</span> : 0}</td>
                      <td>
                        {t.success_rate == null ? (
                          '—'
                        ) : (
                          <span className={rateClass(t.success_rate, s)}>{t.success_rate}%</span>
                        )}
                      </td>
                      <td>{fmtCompact(t.links)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className={s.panel}>
            <h2>Ghi chú</h2>
            <ul className={s.notes}>
              <li><b>WAU</b>: số user riêng biệt hoạt động trong kỳ.</li>
              <li><b>Task Success Rate</b>: % lượt chạy tool ra kết quả (không lỗi) — cùng cách tính với bảng “Theo nhân sự”.</li>
              <li><b>Thời gian TB / task</b>: độ trễ mỗi lượt chạy — từ lúc bấm tìm/chạy đến khi ra kết quả (<code>durationMs</code>), tính bằng giây.</li>
              <li><b>Số lượt chạy</b>: tổng số lần chạy tool (search từ khoá/quảng cáo, tra ảnh, hỏi AI, xem Trend, tra giá vốn, lấy video).</li>
              <li><b>Trend</b>: so với kỳ trước ±5%. Thời gian nhanh hơn là ↑ tốt (đảo dấu).</li>
              <li><b>Theo nhân sự / theo tool</b>: <b>%success = % lượt chạy RA KẾT QUẢ</b> (kể cả sàn không có dữ liệu). Chỉ tính <b>Lỗi</b> khi có sự cố thật: lag/giật, không truy cập được, backend chết. <b>Link ngoài</b> chỉ đo độ sâu (bấm sang sàn), không quyết định thành công.</li>
            </ul>
          </div>
        </>
      )}
    </div>
  )
}
