import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, type EsdeGame, type GameFields } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { romStem } from '../../lib/esde'
import { useRunJob } from '../../lib/jobs'
import { CoverageDialog } from '../media/CoverageDialog'
import { MediaPanel } from '../media/MediaPanel'
import { GameEditor } from './GameEditor'
import { GameList } from './GameList'

type Edits = Record<string, Partial<GameFields>>

const LAST_SYSTEM_KEY = 'kakehashi.esde.system'

function loadLastSystem(): string {
  try {
    return localStorage.getItem(LAST_SYSTEM_KEY) ?? ''
  } catch {
    return ''
  }
}

export function EsdePage({ onOpenSettings }: { onOpenSettings: () => void }) {
  const qc = useQueryClient()
  const systems = useQuery({ queryKey: ['systems'], queryFn: api.systems })
  const [system, setSystem] = useState(loadLastSystem)
  const [showUnregistered, setShowUnregistered] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  // 機種ごとの未プッシュの編集内容
  const [editsBySystem, setEditsBySystem] = useState<Record<string, Edits>>({})
  const [notice, setNotice] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<'meta' | 'media'>('meta')
  const [showCoverage, setShowCoverage] = useState(false)
  const runJob = useRunJob()

  const systemList = systems.data ?? []
  const current = systemList.includes(system) ? system : (systemList[0] ?? '')
  const edits = useMemo(() => editsBySystem[current] ?? {}, [editsBySystem, current])
  const pendingCount = Object.keys(edits).length
  const totalPending = Object.values(editsBySystem).reduce((n, e) => n + Object.keys(e).length, 0)

  const games = useQuery({
    queryKey: ['games', current],
    queryFn: () => api.games(current),
    enabled: !!current,
  })
  const unregistered = useQuery({
    queryKey: ['unregistered', current],
    queryFn: async () => (await api.games(current, { includeUnregistered: true })).filter((g) => !g.registered),
    enabled: !!current && showUnregistered,
  })

  const allGames: EsdeGame[] = useMemo(
    () => [...(games.data ?? []), ...(showUnregistered ? (unregistered.data ?? []) : [])],
    [games.data, unregistered.data, showUnregistered],
  )
  const selectedGame = allGames.find((g) => g.path === selected) ?? null

  useEffect(() => {
    if (totalPending === 0) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [totalPending])

  async function refreshMediaViews(sys: string) {
    await qc.invalidateQueries({ queryKey: ['media', sys] })
    await qc.invalidateQueries({ queryKey: ['coverage', sys] })
  }

  // メディアの同期はジョブトレイに進捗を出し、完了を待たずに操作を続けられるようにする
  function startMediaSync(sys: string, direction: 'pull' | 'push') {
    runJob(() => api.syncMedia(sys, direction))
      .then(() => refreshMediaViews(sys))
      .catch(() => { /* 失敗はジョブトレイに表示される */ })
  }

  // 機種を初めて開いたときに、Deckにだけあるメディアを取得しておく（旧アプリと同じ動き）
  const autoPulled = useRef(new Set<string>())
  useEffect(() => {
    if (!current || !games.isSuccess || autoPulled.current.has(current)) return
    autoPulled.current.add(current)
    startMediaSync(current, 'pull')
  })

  const pull = useMutation({
    mutationFn: () => api.games(current, { refresh: true }),
    onSuccess: (data) => {
      qc.setQueryData(['games', current], data)
      qc.invalidateQueries({ queryKey: ['unregistered', current] })
      setNotice('Deckから最新のgamelist.xmlを取得しました。')
      startMediaSync(current, 'pull')
    },
  })

  const push = useMutation({
    mutationFn: async () => {
      if (pendingCount === 0) return null
      return api.updateGames(current, Object.entries(edits).map(([path, fields]) => ({ path, fields })))
    },
    onSuccess: async (result) => {
      if (result) {
        setEditsBySystem((prev) => ({ ...prev, [current]: {} }))
        // サーバ側のキャッシュは書き込み後の内容に更新済みなので、SSHなしで取り直せる
        await qc.invalidateQueries({ queryKey: ['games', current] })
        await qc.invalidateQueries({ queryKey: ['unregistered', current] })
        setNotice(`${result.applied}件をDeckのgamelist.xmlへ反映しました。メディアを送信しています…`)
      } else {
        setNotice('メディアを送信しています…')
      }
      startMediaSync(current, 'push')
    },
  })

  const addRoms = useMutation({
    mutationFn: async () => {
      const files = await api.pickLocal('files', `${current} のROMファイルを選択`)
      if (files.length === 0) return null
      return runJob(() => api.uploadRoms(current, files))
    },
    onSuccess: async (result) => {
      if (!result) return
      setShowUnregistered(true)
      await qc.invalidateQueries({ queryKey: ['unregistered', current] })
      setNotice(`ROMを${result.transferred}件送信しました（送信済み ${result.skipped}件）。一覧の「未登録」から登録できます。`)
    },
  })

  function changeSystem(next: string) {
    setSystem(next)
    setSelected(null)
    setNotice(null)
    try {
      localStorage.setItem(LAST_SYSTEM_KEY, next)
    } catch {
      /* 保存できなくても動作に影響しない */
    }
  }

  function handlePull() {
    if (pendingCount > 0 && !confirm('未プッシュの編集があります。取得し直しても編集内容は残りますが、Deck側の値と比較し直されます。続けますか？')) return
    pull.mutate()
  }

  function updateField(path: string, field: keyof GameFields, value: string) {
    const original = allGames.find((g) => g.path === path)
    setEditsBySystem((prev) => {
      const sysEdits = { ...(prev[current] ?? {}) }
      const gameEdits = { ...(sysEdits[path] ?? {}) }
      if (original && original[field] === value) delete gameEdits[field]
      else gameEdits[field] = value
      if (Object.keys(gameEdits).length === 0) delete sysEdits[path]
      else sysEdits[path] = gameEdits
      return { ...prev, [current]: sysEdits }
    })
  }

  function discardEdits(path: string) {
    setEditsBySystem((prev) => {
      const sysEdits = { ...(prev[current] ?? {}) }
      delete sysEdits[path]
      return { ...prev, [current]: sysEdits }
    })
  }

  const loadError = systems.error ?? games.error ?? (showUnregistered ? unregistered.error : null)
  const actionError = pull.error ?? push.error ?? addRoms.error
  const needsSettings = [loadError, actionError].some(
    (e) => e instanceof ApiError && (e.code === 'deck_not_configured' || e.code === 'deck_unreachable'),
  )

  if (systems.isSuccess && systemList.length === 0) {
    return (
      <div className="empty-page">
        <p>機種が設定されていません。</p>
        <button className="btn primary" onClick={onOpenSettings}>設定を開く</button>
      </div>
    )
  }

  return (
    <div className="esde">
      <div className="toolbar">
        <label className="field-inline">
          機種
          <select value={current} onChange={(e) => changeSystem(e.target.value)}>
            {systemList.map((s) => {
              const n = Object.keys(editsBySystem[s] ?? {}).length
              return (
                <option key={s} value={s}>
                  {s}{n > 0 ? `（未プッシュ ${n}）` : ''}
                </option>
              )
            })}
          </select>
        </label>
        <button className="btn" onClick={handlePull} disabled={!current || pull.isPending} title="gamelist.xmlを取り直し、PCに無いメディアを取得します">
          {pull.isPending ? '取得中…' : 'Deckから取得'}
        </button>
        <button className="btn" onClick={() => addRoms.mutate()} disabled={!current || addRoms.isPending}>
          {addRoms.isPending ? 'ROM送信中…' : 'ROMを追加'}
        </button>
        <button className="btn" onClick={() => setShowCoverage(true)} disabled={!current}>
          メディアチェック
        </button>
        <div className="toolbar-spacer" />
        {notice && <span className="notice">{notice}</span>}
        <button
          className="btn primary"
          onClick={() => push.mutate()}
          disabled={!current || push.isPending}
          title="gamelist.xmlの編集と、PCで変更したメディアをDeckへ反映します"
        >
          {push.isPending ? 'プッシュ中…' : `Deckへプッシュ${pendingCount > 0 ? `（編集 ${pendingCount}件）` : ''}`}
        </button>
      </div>

      {(loadError || actionError) && (
        <ErrorBox error={loadError ?? actionError}>
          {needsSettings && <button className="btn" onClick={onOpenSettings}>接続設定を開く</button>}
        </ErrorBox>
      )}

      <div className="esde-body">
        <GameList
          games={allGames}
          loading={games.isLoading || (showUnregistered && unregistered.isLoading)}
          edits={edits}
          selected={selected}
          onSelect={setSelected}
          showUnregistered={showUnregistered}
          onToggleUnregistered={setShowUnregistered}
        />
        {selectedGame ? (
          <section className="detail">
            <div className="detail-tabs" role="tablist">
              <button role="tab" aria-selected={detailTab === 'meta'} className={detailTab === 'meta' ? 'active' : ''} onClick={() => setDetailTab('meta')}>
                メタデータ
              </button>
              <button role="tab" aria-selected={detailTab === 'media'} className={detailTab === 'media' ? 'active' : ''} onClick={() => setDetailTab('media')}>
                メディア
              </button>
              <span className="detail-title">
                {(edits[selectedGame.path]?.name ?? selectedGame.name) || romStem(selectedGame.path)}
              </span>
            </div>
            {detailTab === 'meta' ? (
              <GameEditor
                key={`${current}:${selectedGame.path}`}
                system={current}
                game={selectedGame}
                edits={edits[selectedGame.path] ?? {}}
                onChange={(field, value) => updateField(selectedGame.path, field, value)}
                onDiscard={() => discardEdits(selectedGame.path)}
              />
            ) : (
              <MediaPanel
                key={`${current}:${selectedGame.path}`}
                system={current}
                game={selectedGame}
                title={edits[selectedGame.path]?.name ?? selectedGame.name}
              />
            )}
          </section>
        ) : (
          <div className="editor editor-empty">ゲームを選択してください</div>
        )}
      </div>

      {showCoverage && (
        <CoverageDialog
          system={current}
          games={games.data ?? []}
          onSelect={(path) => { setSelected(path); setDetailTab('media') }}
          onClose={() => setShowCoverage(false)}
        />
      )}
    </div>
  )
}
