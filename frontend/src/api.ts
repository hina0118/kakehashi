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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`
    throw new ApiError(res.status, detail, body.code)
  }
  return res.json() as Promise<T>
}

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
    request<UpdateResult>(`/api/esde/${encodeURIComponent(system)}/games/update`, {
      method: 'POST',
      body: JSON.stringify({ updates, deleted }),
    }),
  settings: () => request<Settings>('/api/settings'),
  saveSettings: (s: SettingsInput) =>
    request<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(s) }),
  testConnection: () =>
    request<{ ok: boolean; message: string }>('/api/settings/test-connection', { method: 'POST' }),
}
