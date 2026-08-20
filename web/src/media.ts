export type MediaKind = 'video' | 'photo' | 'lrv'

export interface MediaFile {
  uri: string
  name: string
  key: string
  kind: MediaKind
  date: string
  time: string
  lrvUri?: string
}

const TIMESTAMP_PATTERN = /(\d{4})(\d{2})(\d{2})[_-]?(\d{2})(\d{2})(\d{2})/
const VIDEO_EXTENSIONS = ['mp4', 'mov', 'insv']
const NAME_PREFIX = /^(VID|LRV|IMG|PRO)_/i

function parseFileName(uri: string): MediaFile {
  const name = uri.split('/').pop() ?? uri
  const stamp = name.match(TIMESTAMP_PATTERN)
  const extension = (name.match(/\.(\w+)$/)?.[1] ?? '').toLowerCase()
  const isLrv = extension === 'lrv' || /^LRV_/i.test(name)
  const isVideo = VIDEO_EXTENSIONS.includes(extension)
  return {
    uri,
    name,
    key: name.replace(NAME_PREFIX, '').replace(/\.\w+$/, ''),
    kind: isLrv ? 'lrv' : isVideo ? 'video' : 'photo',
    date: stamp ? `${stamp[1]}-${stamp[2]}-${stamp[3]}` : 'unknown',
    time: stamp ? `${stamp[4]}:${stamp[5]}` : '',
  }
}

export function buildLibrary(uris: string[]): MediaFile[] {
  const files = uris.map(parseFileName)
  const lrvByKey = new Map(files.filter(f => f.kind === 'lrv').map(f => [f.key, f.uri]))
  for (const file of files) {
    if (file.kind === 'video') file.lrvUri = lrvByKey.get(file.key)
  }
  return files
}

export const previewSource = (file: MediaFile) => file.lrvUri ?? file.uri
