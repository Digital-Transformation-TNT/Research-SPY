'use client'

import { useState } from 'react'
import type { Ad } from '@/lib/ads/types'

/** Đẩy media qua proxy của ta: CDN các nền tảng đều xét Referer và link đều có chữ ký. */
function proxied(url: string) {
  return `/api/media?url=${encodeURIComponent(url)}`
}

function scoreClass(value: number) {
  return value >= 70 ? 'high' : value >= 45 ? 'mid' : 'low'
}

const CONFIDENCE_LABEL = {
  high: 'độ tin cậy cao',
  medium: 'độ tin cậy trung bình',
  low: 'độ tin cậy thấp',
} as const

function Media({ ad }: { ad: Ad }) {
  // Video chỉ tải khi bấm. Tự động tải cả lưới video sẽ dội vào CDN và đốt link ký số của
  // những creative không ai buồn xem.
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const video = ad.creatives.find((c) => c.kind === 'video' && c.url)
  const image = ad.creatives.find((c) => c.kind === 'image' && c.url)
  const poster = video?.posterUrl ?? image?.url

  if (!video && !image) {
    return <div className="media-empty">Không có media — quảng cáo này chỉ có text</div>
  }

  if (video && playing) {
    return (
      <>
        <video
          src={proxied(video.url!)}
          poster={poster ? proxied(poster) : undefined}
          controls
          autoPlay
          playsInline
          onError={() => setError('Không phát được — link CDN có thể đã hết hạn, hãy search lại')}
        />
        {error && <div className="media-error">{error}</div>}
      </>
    )
  }

  return (
    <>
      {poster ? (
        <img src={proxied(poster)} alt="" loading="lazy" />
      ) : (
        <div className="media-empty">Không có ảnh xem trước</div>
      )}
      {video && (
        <button className="play-overlay" onClick={() => setPlaying(true)} aria-label="Phát video">
          <span>▶</span>
        </button>
      )}
    </>
  )
}

export default function AdCard({ ad, platformLabel }: { ad: Ad; platformLabel: string }) {
  const [expanded, setExpanded] = useState(false)
  const [showReasons, setShowReasons] = useState(false)
  const score = ad.score
  const videoCount = ad.creatives.filter((c) => c.kind === 'video').length
  const firstVideoUrl = ad.creatives.find((c) => c.kind === 'video')?.url

  return (
    <article className="card">
      <div className="card-media">
        <Media ad={ad} />
        <div className="card-tags">
          <span className={`tag platform-${ad.platform}`}>{platformLabel}</span>
          {ad.countries.map((c) => (
            <span className="tag" key={c}>
              {c}
            </span>
          ))}
          {videoCount > 0 && <span className="tag">{videoCount} video</span>}
        </div>
      </div>

      <div className="card-body">
        <div className="advertiser" title={ad.advertiser}>
          {ad.advertiser}
        </div>

        <div className="metrics">
          {typeof ad.daysActive === 'number' && (
            <span className="metric" title="Số ngày quảng cáo đã chạy — tín hiệu mạnh nhất cho thấy sản phẩm có lãi">
              <b>{ad.daysActive}</b> ngày chạy
            </span>
          )}
          {typeof ad.ctrPercent === 'number' && (
            <span className="metric" title="Tỷ lệ click do nền tảng công bố">
              CTR <b>{ad.ctrPercent}%</b>
            </span>
          )}
          {typeof ad.likeCount === 'number' && (
            <span className="metric">
              <b>{ad.likeCount.toLocaleString('vi-VN')}</b> likes
            </span>
          )}
          {typeof ad.variantCount === 'number' && ad.variantCount > 1 && (
            <span className="metric" title="Số biến thể creative — nhiều biến thể nghĩa là advertiser đang scale">
              <b>{ad.variantCount}</b> biến thể
            </span>
          )}
          {typeof ad.pageLikeCount === 'number' && (
            <span className="metric">
              Page <b>{ad.pageLikeCount.toLocaleString('vi-VN')}</b>
            </span>
          )}
          {ad.isActive === false && <span className="metric">Đã dừng</span>}
        </div>

        {score && (
          <>
            <div className="score">
              <span className={`score-num ${scoreClass(score.total)}`}>{score.total}</span>
              <div className="score-bar">
                <i style={{ width: `${score.total}%` }} />
              </div>
              <button className="linkish" onClick={() => setShowReasons((v) => !v)}>
                {showReasons ? 'ẩn' : 'vì sao?'}
              </button>
            </div>
            <div className="confidence">
              CVR ước lượng {score.cvrProxy}/100 · content {score.contentScore}/100 ·{' '}
              {CONFIDENCE_LABEL[score.confidence]}
            </div>
            {showReasons && (
              <ul className="reasons">
                {score.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </>
        )}

        {ad.body && (
          <div
            className={`copy ${expanded ? 'open' : ''}`}
            onClick={() => setExpanded((v) => !v)}
            title="Bấm để mở rộng"
          >
            {ad.body}
          </div>
        )}

        <div className="link-row">
          {ad.permalink && (
            <a href={ad.permalink} target="_blank" rel="noreferrer">
              Xem trên {platformLabel} ↗
            </a>
          )}
          {ad.landingUrl && (
            <a href={ad.landingUrl} target="_blank" rel="noreferrer">
              Landing page ↗
            </a>
          )}
          {firstVideoUrl && (
            <a href={proxied(firstVideoUrl)} target="_blank" rel="noreferrer">
              Tải video ↗
            </a>
          )}
        </div>
      </div>
    </article>
  )
}
