/**
 * Hàng đợi tuần tự theo key, có khoảng cách tối thiểu giữa hai lần chạy.
 *
 * TikTok bắt đầu trả 40100 "too many requests" sau khoảng năm lần gọi liên tiếp, và một
 * nguồn bị chặn tốn kém hơn nhiều so với một nguồn chạy chậm — nên mọi request ra ngoài
 * đều đi qua đây thay vì trông chờ nơi gọi tự giữ nhịp.
 */

type Task<T> = () => Promise<T>

type Queue = {
  chain: Promise<unknown>
  lastRunAt: number
}

const queues = new Map<string, Queue>()

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Chạy `task` khi hàng đợi của `key` rảnh và đã qua ít nhất `minIntervalMs` kể từ task
 * trước trên cùng key. Hai task cùng key không bao giờ chạy song song.
 */
export function schedule<T>(key: string, minIntervalMs: number, task: Task<T>): Promise<T> {
  const queue = queues.get(key) ?? { chain: Promise.resolve(), lastRunAt: 0 }
  queues.set(key, queue)

  const run = queue.chain.then(async () => {
    const waitFor = queue.lastRunAt + minIntervalMs - Date.now()
    if (waitFor > 0) await sleep(waitFor)
    try {
      return await task()
    } finally {
      queue.lastRunAt = Date.now()
    }
  })

  // Giữ chuỗi sống ngay cả khi một task lỗi, để một lần hỏng không làm nghẽn cả hàng đợi.
  queue.chain = run.then(
    () => undefined,
    () => undefined,
  )
  return run as Promise<T>
}

/** Số mili-giây còn phải chờ trước khi task tiếp theo trên `key` được chạy. */
export function queueDelay(key: string, minIntervalMs: number): number {
  const queue = queues.get(key)
  if (!queue) return 0
  return Math.max(0, queue.lastRunAt + minIntervalMs - Date.now())
}
