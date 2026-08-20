import { useEffect, useRef, useState } from 'react'
import { mediaUrl } from '../api'
import { formatBytes, formatDuration } from '../format'
import { previewSource, type MediaFile } from '../media'
import { acquirePreviewSlot } from '../previewQueue'
import { FilmGlyph, PhotoGlyph, PlayIcon } from '../icons'

const LAZY_MARGIN = '320px'
const PREVIEW_SEEK_FRAGMENT = '#t=0.5'

interface MediaCardProps {
  file: MediaFile
  size: number | null
  selected: boolean
  onToggle: () => void
  onPreview: () => void
}

export function MediaCard({ file, size, selected, onToggle, onPreview }: MediaCardProps) {
  const thumbRef = useRef<HTMLDivElement>(null)
  const releaseRef = useRef<(() => void) | null>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [duration, setDuration] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const target = thumbRef.current
    if (!target) return
    let cancelled = false
    const observer = new IntersectionObserver(
      async entries => {
        if (!entries.some(e => e.isIntersecting)) return
        observer.disconnect()
        const release = await acquirePreviewSlot()
        if (cancelled) {
          release()
          return
        }
        releaseRef.current = release
        setSrc(mediaUrl(previewSource(file)))
      },
      { rootMargin: LAZY_MARGIN },
    )
    observer.observe(target)
    return () => {
      cancelled = true
      observer.disconnect()
      releaseRef.current?.()
    }
  }, [file])

  const releaseSlot = () => {
    releaseRef.current?.()
    releaseRef.current = null
  }

  const isVideo = file.kind !== 'photo'
  const meta = [file.time, size != null ? formatBytes(size) : '']
    .filter(Boolean)
    .join(' · ')

  return (
    <div className={selected ? 'card selected' : 'card'} onClick={onToggle}>
      <div className="thumb" ref={thumbRef}>
        {src && !failed ? (
          isVideo ? (
            <video
              muted
              playsInline
              preload="metadata"
              src={src + PREVIEW_SEEK_FRAGMENT}
              onLoadedData={e => {
                setDuration(e.currentTarget.duration)
                releaseSlot()
              }}
              onError={() => {
                setFailed(true)
                releaseSlot()
              }}
            />
          ) : (
            <img src={src} alt="" onLoad={releaseSlot} onError={() => {
              setFailed(true)
              releaseSlot()
            }} />
          )
        ) : (
          <span className="glyph">{isVideo ? <FilmGlyph /> : <PhotoGlyph />}</span>
        )}
        {duration != null && <span className="duration">{formatDuration(duration)}</span>}
        <span className="tick" aria-hidden />
        <button
          className="peek"
          aria-label="Preview"
          onClick={e => {
            e.stopPropagation()
            onPreview()
          }}
        >
          <PlayIcon />
        </button>
      </div>
      <div className="card-label">
        <div className="card-name">{file.name}</div>
        <div className="card-meta">{meta || ' '}</div>
      </div>
    </div>
  )
}
