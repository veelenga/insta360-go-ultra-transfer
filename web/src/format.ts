const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

export function formatBytes(value: number | null | undefined): string {
  if (value == null) return ''
  let n = value
  let unit = 0
  while (n >= 1000 && unit < BYTE_UNITS.length - 1) {
    n /= 1000
    unit++
  }
  const digits = n >= 10 || unit === 0 ? 0 : 1
  return `${n.toFixed(digits)} ${BYTE_UNITS[unit]}`
}

export function formatEta(seconds: number | null): string {
  if (seconds == null || !isFinite(seconds)) return ''
  if (seconds < 60) return `${Math.max(5, Math.round(seconds / 5) * 5)} sec left`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min left`
  return `${(seconds / 3600).toFixed(1)} h left`
}

export function formatDuration(seconds: number): string {
  if (!isFinite(seconds)) return ''
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}:${String(rest).padStart(2, '0')}`
}

const DATE_FORMAT = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

export function formatDate(isoDate: string): string {
  const parsed = new Date(isoDate + 'T00:00:00')
  return isNaN(parsed.getTime()) ? 'Unknown date' : DATE_FORMAT.format(parsed)
}
