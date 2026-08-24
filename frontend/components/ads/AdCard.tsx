'use client'

import { useState } from 'react'
import type { Ad } from '@/lib/ads/types'

/** Đẩy media qua proxy của ta: CDN các nền tảng đều xét Referer và link đều có chữ ký. */
function proxied(url: string) {
  return `/api/media?url=${encodeURIComponent(url)}`
}

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

        {/*
          Chỉ hiện con số nào nền tảng THẬT SỰ công bố. Mỗi dòng tự quyết định có mặt hay
          không, nên khối này vẫn không phải rẽ nhánh theo nguồn.

          Vì vậy card Facebook chỉ còn số ngày chạy: Ads Library không công bố like / share /
          comment / view của quảng cáo thương mại. Đo bằng `scripts/probe/fb_ad_fields.py` —
          78 trường, `impressions_index` luôn -1, `reach_estimate` và `spend` luôn null, vì
          `is_aaa_eligible: false` (Meta chỉ mở dữ liệu đó cho quảng cáo chính trị và vấn đề
          xã hội). Đừng đi tìm lại; nếu cần con số ấy thì phải đổi hẳn cách thu thập.

          TikTok Creative Center thì có công bố CTR và lượt thích, nên card TikTok giữ chúng.
        */}
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
          {ad.isActive === false && <span className="metric">Đã dừng</span>}
          {/* Nhãn NHẸ, cố ý không phải màu cảnh báo: quảng cáo này vẫn có thể đáng xem — cụm từ
              có thể nằm trong ảnh, hoặc nền tảng khớp nó ở trang đích. Nó chỉ nói cho người
              dùng biết vì sao một thẻ trông lệch chủ đề lại có mặt, thay vì để họ nghĩ công cụ
              tìm sai. Xem `backend/lib/ads/relevance.py`. */}
          {ad.phraseHit === false && (
            <span className="metric off-phrase" title="Nền tảng khớp từ khoá ở nơi khác — tên trang, đường dẫn hoặc trang đích — chứ không trong nội dung hiển thị">
              không chứa từ khoá
            </span>
          )}
        </div>

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
