export interface CurrentFile {
  name: string
  bytes: number
  total: number | null
}

export interface DownloadState {
  active: boolean
  files_done: number
  files_total: number
  bytes_done: number
  bytes_total: number | null
  speed: number
  eta: number | null
  current: CurrentFile | null
  dest: string | null
  done: { name: string; bytes: number; path: string }[]
  errors: { name: string; error: string }[]
}

export interface Status {
  connected: boolean
  host: string
  error: string | null
  downloads: DownloadState
  defaultDest: string
}

export interface FileListing {
  uris: string[]
  total: number
  sizes: Record<string, number>
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const options = body ? { method: 'POST', body: JSON.stringify(body) } : undefined
  const response = await fetch(path, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || response.statusText)
  return data as T
}

export const api = {
  status: () => request<Status>('/api/status'),
  connect: (host: string) => request('/api/connect', { host }),
  disconnect: () => request('/api/disconnect', {}),
  files: () => request<FileListing>('/api/files'),
  sizes: () => request<{ sizes: Record<string, number>; scanning: boolean }>('/api/sizes'),
  download: (uris: string[], dest: string) => request('/api/download', { uris, dest }),
  openFolder: (path: string) => request('/api/open-folder', { path }),
  logs: (since: number) => request<{ cursor: number; lines: string[] }>(`/api/logs?since=${since}`),
}

export const mediaUrl = (uri: string) => `/api/media?uri=${encodeURIComponent(uri)}`
