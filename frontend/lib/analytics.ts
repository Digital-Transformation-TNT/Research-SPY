/*
 * Đo hành vi người dùng — bản có bookkeeping cho phần Next của webtool.
 *
 * `window.rsTrack` trong `public/research/research.js` cũng bắn tới cùng endpoint, nhưng nó là
 * JS thường trong iframe và không biết gì về session/task. File này là bản TypeScript có:
 *   - session_id chung một phiên (lưu localStorage nên iframe research đọc được cùng phiên),
 *   - task_id theo từng tool (mở tool = một task mới), gom event lẻ về đúng task,
 *   - tools_used tích luỹ để đính vào session_end.
 *
 * FIRE-AND-FORGET: mọi lời gọi đều nuốt lỗi. Mất 1–2 event tệ hơn treo một thao tác chính, và
 * analytics KHÔNG bao giờ được phép làm hỏng tính năng. Khớp bộ tên event ở
 * `backend/app/api/admin.py` (_RUN_EVENTS / _LINK_EVENTS).
 *
 * Đường `/api/analytics/track` cố ý ở GỐC tên miền (không `withBase`) — xem `lib/basePath.ts`.
 */

//: Cùng khoá mà research.js đọc, để iframe research nối vào đúng phiên đang mở.
const SESSION_KEY = 'rs_session_id'

let sessionId = ''
let sessionStart = 0
let sessionEnded = false
const toolsUsed = new Set<string>()
//: task_id đang mở theo từng tool. Mở lại tool = task mới.
const currentTask: Record<string, string> = {}

/** Mã ngẫu nhiên ngắn có tiền tố (S_… cho phiên, T_… cho task). */
function rid(prefix: string): string {
  const raw = (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}${Math.random()}`)
    .replace(/[^a-z0-9]/gi, '')
    .slice(0, 12)
  return `${prefix}_${raw}`
}

function deviceKind(): string {
  if (typeof navigator === 'undefined') return 'unknown'
  return /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent) ? 'mobile' : 'desktop'
}

function referrer(): string {
  try {
    if (!document.referrer) return 'direct'
    return new URL(document.referrer).hostname || 'direct'
  } catch {
    return 'direct'
  }
}

/** Bảo đảm có một phiên; tạo mới (kèm mốc thời gian) nếu chưa có. Trả session_id. */
export function ensureSession(): string {
  if (typeof window === 'undefined') return ''
  if (sessionId) return sessionId
  sessionId = rid('S')
  sessionStart = Date.now()
  sessionEnded = false
  try {
    localStorage.setItem(SESSION_KEY, sessionId)
  } catch {
    // localStorage bị chặn: vẫn track được, chỉ là iframe research không nối chung phiên.
  }
  return sessionId
}

/**
 * Bắn một event bất kỳ. Luôn kèm session_id. Không await, không raise.
 *
 * CHƯA CÓ TOKEN thì không gửi: trang đã chặn login nên mọi người dùng thật đều có vé, và một
 * event không kèm vé chỉ tạo ra một dòng NULL mà backend cũng bỏ. Chặn ngay ở đây để khỏi tốn
 * một request vô ích.
 */
export function track(eventType: string, meta: Record<string, unknown> = {}): void {
  if (typeof window === 'undefined') return
  let token: string | null = null
  try {
    token = localStorage.getItem('rs_token')
  } catch {
    // localStorage bị chặn: coi như không có vé → không gửi.
  }
  if (!token) return
  const sid = ensureSession()
  try {
    fetch('/api/analytics/track', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + token,
      },
      body: JSON.stringify({ event_type: eventType, meta: { session_id: sid, ...meta } }),
      keepalive: true, // cho request hoàn tất khi người dùng điều hướng đi
    }).catch(() => {})
  } catch {
    // JSON.stringify hay fetch ném lỗi đồng bộ: bỏ qua.
  }
}

/** Mở một tool = một task mới. Trả task_id, và nhớ nó làm task hiện tại của tool. */
export function openFeature(feature: string): string {
  const taskId = rid('T')
  currentTask[feature] = taskId
  toolsUsed.add(feature)
  track('feature_open', { task_id: taskId, feature })
  return taskId
}

/** task_id hiện tại của tool; tự mở task nếu chưa có (event lẻ tới trước feature_open). */
function taskOf(feature: string): string {
  return currentTask[feature] || openFeature(feature)
}

/** Bắn event thuộc một tool — tự đính task_id + feature hiện tại của tool đó. */
export function trackTask(
  feature: string,
  eventType: string,
  meta: Record<string, unknown> = {},
): void {
  toolsUsed.add(feature)
  track(eventType, { task_id: taskOf(feature), feature, ...meta })
}

/** Bắt đầu phiên: chỉ nên gọi một lần lúc app dựng. Không lặp lại nếu đã có phiên đang mở. */
export function sessionStartEvent(): void {
  if (typeof window === 'undefined') return
  const fresh = !sessionId
  ensureSession()
  if (fresh) track('session_start', { device: deviceKind(), ref: referrer() })
}

/** Đổi trang trong SPA — một dòng page_view. */
export function pageView(page: string): void {
  track('page_view', { page })
}

/** Kết phiên: đo thời lượng + tool đã dùng. Bắn nhiều nhất MỘT lần cho mỗi phiên. */
export function sessionEndEvent(lastPage: string): void {
  if (!sessionId || sessionEnded) return
  sessionEnded = true
  const durationSec = Math.max(0, Math.round((Date.now() - sessionStart) / 1000))
  track('session_end', {
    durationSec,
    last_page: lastPage,
    tools_used: [...toolsUsed],
  })
}
