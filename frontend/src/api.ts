export const EDITABLE_FIELDS = ['name', 'desc', 'releasedate', 'developer', 'publisher', 'genre'] as const
export type EditableField = (typeof EDITABLE_FIELDS)[number]
export type GameFields = Record<EditableField, string>

export type EsdeGame = GameFields & {
  path: string
  registered: boolean
  extra: Record<string, string>
}

export type GameUpdate = { path: string; fields: Partial<GameFields> }
export type UpdateResult = { applied: number; deleted: number; requested: number }

export type Settings = {
  systems: string[]
  backup_max: number
  windows: { media_base: string }
  steam_deck: { rom_base: string; gamelist_base: string; media_base: string; doujin_base: string[] }
  sync: { host: string; port: number; username: string; password_set: boolean }
}

export type SettingsInput = Omit<Settings, 'sync'> & {
  sync: { host: string; port: number; username: string; password?: string }
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string

  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export const MEDIA_FOLDERS = [
  '3dboxes', 'backcovers', 'covers', 'fanart', 'manuals', 'marquees',
  'miximages', 'physicalmedia', 'screenshots', 'titlescreens', 'videos',
] as const
export type MediaFolder = (typeof MEDIA_FOLDERS)[number]

export type MediaFile = {
  folder: MediaFolder
  filename: string
  size: number
  mtime: number
  kind: 'image' | 'video' | 'pdf' | 'other'
}
export type GameMedia = { path: string; stem: string; files: Record<MediaFolder, MediaFile | null> }
export type Coverage = Record<string, Partial<Record<MediaFolder, string>>>
export type PreviewInfo = { id: string; width: number; height: number }
export type Capabilities = { ai_logo: boolean; ytdlp: boolean }
export type SyncResult = { transferred: number; skipped: number; deleted: number; errors: string[] }

export type JobView<R = unknown> = {
  id: string
  kind: string
  title: string
  status: 'running' | 'done' | 'error'
  done: number
  total: number
  messages: string[]
  error: string | null
  result: R | null
  started_at: string
  finished_at: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? 'GET'
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      // 更新系APIはこのヘッダが無いと拒否される（CSRF対策）
      ...(method !== 'GET' ? { 'X-Kakehashi': '1' } : {}),
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`
    throw new ApiError(res.status, detail, body.code)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body: unknown = {}) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) })

const sys = (system: string) => `/api/esde/${encodeURIComponent(system)}`

/** ジョブの完了を待つ。失敗したジョブは ApiError として投げる。 */
export async function waitForJob<R>(job: JobView<R>, onUpdate?: (j: JobView<R>) => void): Promise<R> {
  let current = job
  while (current.status === 'running') {
    await new Promise((r) => setTimeout(r, 500))
    current = await request<JobView<R>>(`/api/jobs/${current.id}`)
    onUpdate?.(current)
  }
  if (current.status === 'error') throw new ApiError(500, current.error ?? 'ジョブが失敗しました')
  return current.result as R
}

export function mediaFileUrl(system: string, f: MediaFile, width?: number): string {
  const q = new URLSearchParams({ v: String(f.mtime) })
  if (width) q.set('w', String(width))
  return `${sys(system)}/media/file/${f.folder}/${encodeURIComponent(f.filename)}?${q}`
}

export const previewUrl = (p: PreviewInfo) => `/api/media/previews/${p.id}.png`

export const api = {
  systems: () => request<string[]>('/api/esde/systems'),
  games: (system: string, opts: { refresh?: boolean; includeUnregistered?: boolean } = {}) => {
    const q = new URLSearchParams({
      refresh: String(opts.refresh ?? false),
      include_unregistered: String(opts.includeUnregistered ?? false),
    })
    return request<EsdeGame[]>(`/api/esde/${encodeURIComponent(system)}/games?${q}`)
  },
  updateGames: (system: string, updates: GameUpdate[], deleted: string[] = []) =>
    post<UpdateResult>(`${sys(system)}/games/update`, { updates, deleted }),
  settings: () => request<Settings>('/api/settings'),
  saveSettings: (s: SettingsInput) =>
    request<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(s) }),
  capabilities: () => request<Capabilities>('/api/media/capabilities'),
  gameMedia: (system: string, path: string) =>
    request<GameMedia>(`${sys(system)}/media?${new URLSearchParams({ path })}`),
  coverage: (system: string) => request<Coverage>(`${sys(system)}/media/coverage`),
  pendingDeletions: (system: string) => request<string[]>(`${sys(system)}/media/pending-deletions`),
  importFile: (system: string, folder: MediaFolder, path: string, source: string) =>
    post<MediaFile>(`${sys(system)}/media/${folder}/import-file`, { path, source }),
  importUrl: (system: string, folder: MediaFolder, path: string, url: string) =>
    post<JobView<MediaFile>>(`${sys(system)}/media/${folder}/import-url`, { path, url }),
  deleteMedia: (system: string, folder: MediaFolder, path: string) =>
    post<{ deleted: number }>(`${sys(system)}/media/${folder}/delete`, { path }),
  preview3dbox: (
    system: string,
    body: { path: string; spine_ratio: number; angle_pct: number; shadow: boolean; spine_text: string },
  ) => post<PreviewInfo>(`${sys(system)}/media/preview/3dbox`, body),
  previewMiximage: (system: string, path: string) =>
    post<PreviewInfo>(`${sys(system)}/media/preview/miximage`, { path }),
  previewCrop: (system: string, path: string, box: [number, number, number, number], folder = 'covers') =>
    post<PreviewInfo>(`${sys(system)}/media/preview/crop`, { path, box, folder }),
  previewAiLogo: (system: string, path: string) =>
    post<JobView<PreviewInfo>>(`${sys(system)}/media/preview/ai-logo`, { path }),
  savePreview: (system: string, folder: MediaFolder, path: string, previewId: string) =>
    post<MediaFile>(`${sys(system)}/media/${folder}/save-preview`, { path, preview_id: previewId }),
  syncMedia: (system: string, direction: 'pull' | 'push', overwrite = false) =>
    post<JobView<SyncResult>>(`${sys(system)}/media/sync`, { direction, overwrite }),
  uploadRoms: (system: string, files: string[]) =>
    post<JobView<{ transferred: number; skipped: number; errors: string[] }>>(`${sys(system)}/roms/upload`, { files }),
  jobs: () => request<JobView[]>('/api/jobs'),
  pickLocal: (mode: 'files' | 'file' | 'folder', title: string, filetypes?: 'image' | 'video' | 'pdf' | 'media') =>
    post<string[]>('/api/local/pick', { mode, title, filetypes }),
  testConnection: () => post<{ ok: boolean; message: string }>('/api/settings/test-connection'),
}
