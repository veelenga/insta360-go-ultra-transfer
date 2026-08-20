import { useMemo } from 'react'
import { formatDate } from '../format'
import type { MediaFile } from '../media'
import { MediaCard } from './MediaCard'

interface GalleryProps {
  files: MediaFile[]
  sizes: Record<string, number>
  selected: ReadonlySet<string>
  onToggle: (uri: string) => void
  onToggleDay: (uris: string[]) => void
  onPreview: (file: MediaFile) => void
}

export function Gallery(props: GalleryProps) {
  const days = useMemo(() => {
    const byDate = new Map<string, MediaFile[]>()
    for (const file of props.files) {
      const group = byDate.get(file.date)
      if (group) group.push(file)
      else byDate.set(file.date, [file])
    }
    return [...byDate.entries()].sort((a, b) => b[0].localeCompare(a[0]))
  }, [props.files])

  return (
    <div className="gallery">
      {days.map(([date, dayFiles]) => {
        const allSelected = dayFiles.every(f => props.selected.has(f.uri))
        return (
          <section key={date}>
            <div className="day-head">
              <h2>{formatDate(date)}</h2>
              <span className="day-count">{dayFiles.length}</span>
              <button
                className="link"
                onClick={() => props.onToggleDay(dayFiles.map(f => f.uri))}
              >
                {allSelected ? 'Deselect' : 'Select'}
              </button>
            </div>
            <div className="grid">
              {dayFiles.map(file => (
                <MediaCard
                  key={file.uri}
                  file={file}
                  size={props.sizes[file.uri] ?? null}
                  selected={props.selected.has(file.uri)}
                  onToggle={() => props.onToggle(file.uri)}
                  onPreview={() => props.onPreview(file)}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
