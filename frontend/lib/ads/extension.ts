/**
 * Cầu nối tới extension Research-SPY Fetcher (Cách A).
 *
 * Trang web không gọi API extension trực tiếp được, nên nó `window.postMessage` cho content
 * script của extension, chờ message trả về khớp `id`. Nếu extension chưa cài, các hàm này
 * trả về "không có" một cách êm — giao diện tự rơi về thông báo, không treo.
 *
 * Nguồn sự thật hình dạng dữ liệu: `frontend/lib/ads/types.ts` (mirror của backend).
 */

import type { ClientJob, ClientResponse, ClientSubmission } from './types'

const FROM_PAGE = 'research-spy'
const FROM_EXT = 'research-spy-ext'
let counter = 0

/** Gửi một message xuống extension và chờ đúng phản hồi (theo `id`), có timeout. */
function call<T>(type: string, payload: Record<string, unknown>, timeoutMs: number): Promise<T | null> {
  if (typeof window === 'undefined') return Promise.resolve(null)
  const id = `rs-${Date.now()}-${counter++}`

  return new Promise<T | null>((resolve) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener('message', onMessage)
      resolve(null)
    }, timeoutMs)

    function onMessage(event: MessageEvent) {
      if (event.source !== window) return
      const d = event.data
      if (!d || d.source !== FROM_EXT || d.id !== id) return
      window.clearTimeout(timer)
      window.removeEventListener('message', onMessage)
      resolve(d as T)
    }

    window.addEventListener('message', onMessage)
    window.postMessage({ source: FROM_PAGE, type, id, ...payload }, '*')
  })
}

/** Extension đã cài và trả lời? Dùng để quyết định có bật nguồn client_fetch hay không. */
export async function extensionAvailable(): Promise<boolean> {
  const resp = await call<{ ok: boolean }>('PING', {}, 1500)
  return !!(resp && resp.ok)
}

/**
 * Chạy các job (do backend trả trong `pending`) qua extension, gom thành submissions để POST
 * về /api/ads/ingest. Mỗi job fetch bằng session user cho đúng domain của nó.
 */
export async function runClientJobs(jobs: ClientJob[]): Promise<ClientSubmission[]> {
  const submissions: ClientSubmission[] = []
  for (const job of jobs) {
    const resp = await call<{ responses: ClientResponse[] }>(
      'FETCH',
      { requests: job.requests },
      30_000,
    )
    submissions.push({
      platform: job.platform,
      country: job.country,
      responses: (resp && resp.responses) || [],
    })
  }
  return submissions
}
