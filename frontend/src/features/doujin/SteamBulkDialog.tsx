import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { doujinApi, steamApi, type DoujinGame, type SteamGameResult } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { useRunJob } from '../../lib/jobs'

type Props = { games: DoujinGame[]; onClose: () => void; onDone: (updated: DoujinGame[]) => void; onOpenSettings: () => void }

export function SteamBulkDialog({ games, onClose, onDone, onOpenSettings }: Props) {
  const runJob = useRunJob()
  const status = useQuery({ queryKey: ['steam-status'], queryFn: steamApi.status, gcTime: 0 })
  const eligible = games.filter((g) => g.deck_dir && g.exe)
  const [checked, setChecked] = useState<Set<number>>(() => new Set(eligible.map((g) => g.id)))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [results, setResults] = useState<SteamGameResult[] | null>(null)
  const [overwriteArt, setOverwriteArt] = useState(false)

  const s = status.data
  const blocked = !s || s.running || !s.user

  async function apply() {
    setBusy(true)
    setError(null)
    try {
      const r = await runJob(() => steamApi.apply([...checked], overwriteArt))
      setResults(r)
      onDone(await Promise.all(r.filter((x) => !x.error).map((x) => doujinApi.get(x.id))))
      status.refetch()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  const toggle = (id: number) => setChecked((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  return (
    <Modal
      title="Steamにまとめて反映"
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn" onClick={() => status.refetch()} disabled={status.isFetching}>
            {status.isFetching ? '確認中…' : 'Steamの状態を再確認'}
          </button>
          <button className="btn primary" disabled={busy || blocked || checked.size === 0} onClick={apply}>
            {busy ? '書き込み中…' : `${checked.size}件を反映`}
          </button>
        </>
      }
    >
      {status.isLoading && <p className="muted">DeckのSteamの状態を確認しています…</p>}
      {status.error && (
        <ErrorBox error={status.error}><button className="btn" onClick={onOpenSettings}>接続設定を開く</button></ErrorBox>
      )}
      {s && (
        <div className={`steam-state${s.running || !s.user ? ' ng' : ' ok'}`}>
          {s.running
            ? 'DeckでSteamが起動しています。デスクトップモードに切り替えてSteamを終了し、「Steamの状態を再確認」を押してください。'
            : s.user
              ? `Steamは停止しています。登録先: ${s.user.persona_name || s.user.account_name || s.user.account_id}`
              : s.problem}
          {!s.user && <button className="link" onClick={onOpenSettings}>設定を開く</button>}
        </div>
      )}
      <p className="hint">
        Deckに転送済みで起動ファイルが設定された作品が対象です。Steamに同じ起動ファイルの登録が既にあれば、それを引き継いで更新します（二重登録しません）。
      </p>
      <label className="check">
        <input type="checkbox" checked={overwriteArt} onChange={(e) => setOverwriteArt(e.target.checked)} />
        Deckにある既存の画像も台帳の画像で置き換える
      </label>
      {error != null && <ErrorBox error={error} />}
      <div className="coverage-table-wrap">
        <table className="coverage-table candidate-table">
          <thead>
            <tr><th /><th>タイトル</th><th>状態</th><th>結果</th></tr>
          </thead>
          <tbody>
            {eligible.map((g) => {
              const r = results?.find((x) => x.id === g.id)
              return (
                <tr key={g.id} onClick={() => toggle(g.id)}>
                  <td><input type="checkbox" checked={checked.has(g.id)} onChange={() => toggle(g.id)} onClick={(e) => e.stopPropagation()} /></td>
                  <td className="coverage-title">{g.title}</td>
                  <td>{g.steam_registered_at ? '登録済み' : '未登録'}</td>
                  <td className={r?.error ? 'ng' : ''}>{r ? (r.error ?? r.action) : ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {eligible.length === 0 && <p className="muted">対象の作品がありません。</p>}
    </Modal>
  )
}
