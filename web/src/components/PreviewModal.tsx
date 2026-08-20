import { useEffect } from 'react'
import { mediaUrl } from '../api'
import { formatBytes } from '../format'
import { previewSource, type MediaFile } from '../media'

interface PreviewModalProps {
  file: MediaFile
  size: number | null
  onClose: () => void
}

export function PreviewModal({ file, size, onClose }: PreviewModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal" onClick={onClose}>
      <figure onClick={e => e.stopPropagation()}>
        {file.kind === 'photo' ? (
          <img src={mediaUrl(file.uri)} alt={file.name} />
        ) : (
          <video controls autoPlay muted src={mediaUrl(previewSource(file))} />
        )}
        <figcaption>
          {file.name}
          {size != null && ` · ${formatBytes(size)}`}
          {file.lrvUri && ' · proxy preview'}
        </figcaption>
      </figure>
    </div>
  )
}
