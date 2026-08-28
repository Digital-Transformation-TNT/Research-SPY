'use client'

import { useEffect, useRef, useState } from 'react'
import s from './login.module.css'

/**
 * Đăng nhập bằng email công ty — bản Next.js (thay cho public/login/index.html).
 *
 * Luồng GIỮ NGUYÊN như bản HTML tĩnh cũ để backend không phải đổi:
 *   1) nhập email  → /api/auth/login
 *        · có token           → lưu localStorage, vào /ads
 *        · needsRegistration  → sang bước 2 (hồ sơ)
 *        · pending            → sang bước 3 (chờ duyệt, poll)
 *        · 501                → chưa cấu hình Supabase, fallback dev: coi như đăng nhập
 *   2) gửi hồ sơ   → /api/auth/register → pending → bước 3
 *   3) chờ duyệt   → poll /api/auth/login mỗi 4s tới khi có token / bị từ chối
 *
 * Các key localStorage (rs_token, rs_email, rs_role, rs_user_id, rs_display) trùng khít với
 * Sidebar để phần còn lại của app đọc được y như trước.
 */

const ENTER_URL = '/ads'
const POLL_MS = 4000
const DOMAIN_HINT = '@tntecom.com'

type Mode = 'email' | 'reg' | 'wait'
type Status = { text: string; kind: 'err' | 'wait' | 'ok' } | null

type LoginResult = { status: number; ok: boolean; data: any }

async function callLogin(email: string): Promise<LoginResult> {
  const r = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  const data = await r.json().catch(() => ({}))
  return { status: r.status, ok: r.ok, data }
}

function saveAndEnter(data: any) {
  localStorage.setItem('rs_token', data.token)
  localStorage.setItem('rs_email', data.user?.email || '')
  localStorage.setItem('rs_role', data.user?.role || 'user')
  localStorage.setItem('rs_user_id', data.user?.id || '')
  localStorage.setItem('rs_display', data.user?.displayName || data.user?.email || '')
  window.location.replace(ENTER_URL)
}

/** Chữ ký thị giác: đĩa radar + vòng ngắm, có tia quét cam (CSS lo phần quay). */
function Radar() {
  return (
    <div className={s.radar} aria-hidden="true">
      <div className={s.sweep} />
      <svg className={s.radarSvg} viewBox="0 0 200 200" fill="none">
        <g stroke="rgba(255,255,255,.16)" strokeWidth="1">
          <circle cx="100" cy="100" r="94" />
          <circle cx="100" cy="100" r="64" />
          <circle cx="100" cy="100" r="34" />
          <line x1="100" y1="6" x2="100" y2="194" />
          <line x1="6" y1="100" x2="194" y2="100" />
        </g>
        <g stroke="rgba(255,255,255,.28)" strokeWidth="1.4">
          <line x1="100" y1="8" x2="100" y2="18" />
          <line x1="100" y1="182" x2="100" y2="192" />
          <line x1="8" y1="100" x2="18" y2="100" />
          <line x1="182" y1="100" x2="192" y2="100" />
        </g>
        <circle className={s.blip} cx="140" cy="72" r="4.5" />
        <circle className={`${s.blip} ${s.blip2}`} cx="74" cy="132" r="3.6" />
      </svg>
    </div>
  )
}

export default function LoginPage() {
  const [ready, setReady] = useState(false)
  const [orgLogoOk, setOrgLogoOk] = useState(true) // logo TNT Group — tự ẩn nếu thiếu file
  const [mode, setMode] = useState<Mode>('email')
  const [status, setStatus] = useState<Status>(null)
  const [busy, setBusy] = useState(false)

  const [email, setEmail] = useState('')
  const [regName, setRegName] = useState('')
  const [regPos, setRegPos] = useState('')
  const [regBu, setRegBu] = useState('')
  const [waitEmail, setWaitEmail] = useState('')

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  // Đã có token → vào thẳng, không nháy form. Chỉ quyết định sau khi ở client.
  useEffect(() => {
    if (localStorage.getItem('rs_token')) {
      window.location.replace(ENTER_URL)
      return
    }
    setReady(true)
    return stopPoll
  }, [])

  // Bước 3: chờ duyệt — poll tới khi có token hoặc bị từ chối.
  function startWaiting(addr: string) {
    setWaitEmail(addr)
    setStatus(null)
    setMode('wait')
    stopPoll()
    const poll = async () => {
      try {
        const { data } = await callLogin(addr)
        if (data.token) {
          stopPoll()
          setStatus({ text: 'Đã được duyệt! Đang vào…', kind: 'ok' })
          saveAndEnter(data)
          return
        }
        if (data.error && !data.pending) {
          stopPoll()
          setStatus({ text: data.error, kind: 'err' })
          setMode('email')
        }
      } catch {
        /* mạng chập chờn — thử lại lần sau */
      }
    }
    poll() // kiểm ngay (phòng khi admin đã duyệt trước lúc mở màn chờ)
    pollRef.current = setInterval(poll, POLL_MS)
  }

  async function submitEmail(e: React.FormEvent) {
    e.preventDefault()
    const addr = email.trim().toLowerCase()
    setStatus(null)
    setBusy(true)
    try {
      const { status: code, data } = await callLogin(addr)
      if (code === 501) {
        // chưa cấu hình Supabase → fallback dev
        localStorage.setItem('rs_email', addr)
        localStorage.setItem('rs_role', 'user')
        window.location.replace(ENTER_URL)
        return
      }
      if (data.token) return saveAndEnter(data)
      if (data.needsRegistration) {
        setMode('reg')
        return
      }
      if (data.pending) return startWaiting(addr)
      setStatus({ text: data.error || 'Không đăng nhập được.', kind: 'err' })
    } catch {
      setStatus({ text: 'Lỗi kết nối máy chủ.', kind: 'err' })
    } finally {
      setBusy(false)
    }
  }

  async function submitReg(e: React.FormEvent) {
    e.preventDefault()
    const addr = email.trim().toLowerCase()
    const fullName = regName.trim()
    const position = regPos.trim()
    const bu = regBu.trim()
    setStatus(null)
    if (!fullName || !position || !bu) {
      setStatus({ text: 'Phải nhập đủ Tên, Vị trí và BU.', kind: 'err' })
      return
    }
    setBusy(true)
    try {
      const r = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: addr, fullName, position, bu }),
      })
      const data = await r.json().catch(() => ({}))
      if (data.pending) return startWaiting(addr)
      setStatus({ text: data.error || 'Không gửi được yêu cầu.', kind: 'err' })
    } catch {
      setStatus({ text: 'Lỗi kết nối máy chủ.', kind: 'err' })
    } finally {
      setBusy(false)
    }
  }

  const backToEmail = () => {
    stopPoll()
    setStatus(null)
    setMode('email')
  }

  return (
    <div className={s.wrap}>
      {/* ------- bảng radar (chữ ký thị giác) ------- */}
      <section className={s.recon}>
        <div className={s.brandLock}>
          <div>
            <p className={s.eyebrow}>Reconnaissance console</p>
            <div className={s.wordmark}>
              Research<span>·</span>SPY
            </div>
          </div>
        </div>

        <div className={s.middle}>
          <h1 className={s.tagline}>
            Tìm <b>tín hiệu</b> sản phẩm trước khi thị trường thấy.
          </h1>
          <p className={s.sub}>
            Quét đa sàn theo từ khoá, ảnh và xu hướng — gom về một bảng để phòng test ra quyết định nhanh.
          </p>
          <Radar />
          <div className={s.targets}>
            {['Shopee', '1688', 'TikTok', 'Etsy', 'Amazon', 'Google Trends'].map((t) => (
              <span className={s.target} key={t}>
                <i /> {t}
              </span>
            ))}
          </div>
        </div>

        <div className={s.reconFoot}>TNT GROUP · INTERNAL</div>
      </section>

      {/* ------- form ------- */}
      <section className={s.formPane}>
        {ready ? (
          <div className={s.formInner}>
          <div className={s.card}>
            {mode === 'email' && (
              <form onSubmit={submitEmail}>
                <div className={s.cardHead}>
                  <h2>Đăng nhập</h2>
                  <p>Dùng email công ty để vào bảng research.</p>
                </div>
                <label className={s.label} htmlFor="email">
                  Email công ty
                </label>
                <input
                  id="email"
                  className={s.input}
                  type="email"
                  placeholder="vd: mailtnt@tntecom.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  autoComplete="email"
                />
                <button className={s.primary} type="submit" disabled={busy}>
                  {busy ? 'Đang kiểm tra…' : 'Tiếp tục →'}
                </button>
                <p className={s.hint}>
                  Chỉ nhận email <b>{DOMAIN_HINT}</b>.
                </p>
              </form>
            )}

            {mode === 'reg' && (
              <form onSubmit={submitReg}>
                <div className={s.cardHead}>
                  <h2>Tạo hồ sơ</h2>
                  <p>Email chưa có trong hệ thống — gửi yêu cầu để quản trị viên duyệt.</p>
                </div>
                <label className={s.label}>Email</label>
                <input className={s.input} type="email" value={email} disabled />
                <label className={s.label} htmlFor="regName">
                  Tên
                </label>
                <input
                  id="regName"
                  className={s.input}
                  type="text"
                  placeholder="Họ và tên"
                  maxLength={120}
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  autoFocus
                />
                <label className={s.label} htmlFor="regPos">
                  Vị trí
                </label>
                <input
                  id="regPos"
                  className={s.input}
                  type="text"
                  placeholder="vd: R&D"
                  maxLength={120}
                  value={regPos}
                  onChange={(e) => setRegPos(e.target.value)}
                />
                <label className={s.label} htmlFor="regBu">
                  BU (đơn vị làm việc)
                </label>
                <input
                  id="regBu"
                  className={s.input}
                  type="text"
                  placeholder="vd: BU1"
                  maxLength={120}
                  value={regBu}
                  onChange={(e) => setRegBu(e.target.value)}
                />
                <button className={s.primary} type="submit" disabled={busy}>
                  {busy ? 'Đang gửi…' : 'Gửi yêu cầu →'}
                </button>
                <button className={s.ghost} type="button" onClick={backToEmail}>
                  ← Đổi email khác
                </button>
              </form>
            )}

            {mode === 'wait' && (
              <div className={s.waitBox}>
                <div className={s.spinner} />
                <h3>Đang chờ quản trị viên duyệt</h3>
                <p>
                  Yêu cầu của <span className={s.waitEmail}>{waitEmail}</span> đã được gửi.
                </p>
                <p>Trang này tự vào ngay khi được duyệt — không cần làm gì thêm.</p>
                <button className={s.ghost} type="button" onClick={backToEmail}>
                  ← Dùng email khác
                </button>
              </div>
            )}

            {status && <div className={`${s.status} ${s[status.kind]}`}>{status.text}</div>}
          </div>
          {orgLogoOk ? (
            <div className={s.orgMark}>
              <span>Nội bộ</span>
              <img src="/brand/tnt-group.png" alt="TNT Group" onError={() => setOrgLogoOk(false)} />
            </div>
          ) : null}
          </div>
        ) : null}
      </section>
    </div>
  )
}
