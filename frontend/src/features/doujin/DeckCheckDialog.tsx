import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, doujinApi, steamApi, type DeckCheckItem, type DoujinGame } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { useRunJob } from '../../lib/jobs'

type Props = {
  onClose: () => void
  onDone: (updated: DoujinGame[], message: string) => void
  onOpenGame: (id: number) => void
  onOpenSettings: () => void
}

const STATUS_LABELS: Record<DeckCheckItem['status'], string> = {
  folder_missing: '作品フォルダが無い',
  exe_missing: '起動ファイルが無い',
  unreachable: '格納先ごと見つからない',
}

/** 台帳でDeckにあることになっている作品のうち、Deck上で削除されたものを見つけて片付ける。 */
export function DeckCheckDialog({ onClose, onDone, onOpenGame, onOpenSettings }: Props) {
  const runJob = useRunJob()
  const check = useQuery({ queryKey: ['doujin-deck-check'], queryFn: doujinApi.checkDeck, gcTime: 0 })
  const problems = check.data?.problems ?? []
  const deleted = problems.filter((p) => p.status === 'folder_missing')
  const [checked, setChecked] = useState<Set<number> | null>(null)
  const [removeSteam, setRemoveSteam] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const selected = checked ?? new Set(deleted.map((p) => p.id))
  const steamTargets = deleted.filter((p) => selected.has(p.id) && p.steam_registered).map((p) => p.id)
  const needsSettings = check.error instanceof ApiError && ['deck_not_configured', 'deck_unreachable'].includes(check.error.code ?? '')

  async function cleanUp() {
    setBusy(true)
    setError(null)
    try {
      let steamNote = ''
      if (removeSteam && steamTargets.length > 0) {
        const r = await runJob(() => steamApi.remove(steamTargets))
        const failed = r.filter((x) => x.error).length
        steamNote = `、Steamの登録を${r.length - failed}件外しました${failed ? `（${failed}件失敗）` : ''}`
      }
      const { unlinked } = await doujinApi.unlinkDeck([...selected])
      const updated = await Promise.all(unlinked.map((id) => doujinApi.get(id)))
      onDone(updated, `Deckから削除された${unlinked.length}件の、台帳のDeckのフォルダを外しました${steamNote}。`)
      onClose()
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  const toggle = (id: number) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setChecked(next)
  }

  return (
    <Modal
      title="Deckと照合"
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn" onClick={() => { setChecked(null); check.refetch() }} disabled={check.isFetching || busy}>
            {check.isFetching ? '確認中…' : '再確認'}
          </button>
          <button className="btn primary" disabled={busy || selected.size === 0} onClick={cleanUp}>
            {busy ? '片付け中…' : `${selected.size}件を片付ける`}
          </button>
        </>
      }
    >
      <p className="hint">
        台帳でDeckにあることになっている作品を、Deck上の実際のフォルダと照らし合わせます。
        「片付ける」と、選んだ作品の台帳からDeckのフォルダと同期の記録を外します。台帳の作品、画像、PCのファイルは残ります。
      </p>
      {check.isLoading && <p className="muted">Deckのフォルダを確認しています…</p>}
      {check.error != null && (
        <ErrorBox error={check.error}>
          {needsSettings && <button className="btn" onClick={onOpenSettings}>接続設定を開く</button>}
        </ErrorBox>
      )}
      {check.data && problems.length === 0 && (
        <p className="notice">{check.data.checked}件を確認しました。Deckから削除された作品はありません。</p>
      )}

      {problems.length > 0 && (
        <>
          <p className="muted">
            {check.data!.checked}件を確認しました。削除されたもの {deleted.length}件
            {problems.length > deleted.length && `・ほかに確認が必要なもの ${problems.length - deleted.length}件`}
          </p>
          <label className="check">
            <input type="checkbox" checked={removeSteam} onChange={(e) => setRemoveSteam(e.target.checked)} />
            Steamの登録も外す（{steamTargets.length}件。DeckでSteamを終了しておく必要があります。appIDは台帳に残るので、入れ直して登録し直せばプレイ記録は引き継がれます）
          </label>
          {error != null && <ErrorBox error={error} />}
          <div className="coverage-table-wrap">
            <table className="coverage-table candidate-table">
              <thead>
                <tr><th /><th>タイトル</th><th>状態</th><th>Steam</th></tr>
              </thead>
              <tbody>
                {problems.map((p) => {
                  const selectable = p.status === 'folder_missing'
                  return (
                    <tr key={p.id} onClick={() => selectable && toggle(p.id)}>
                      <td>
                        {selectable && (
                          <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} onClick={(e) => e.stopPropagation()} />
                        )}
                      </td>
                      <td className="coverage-title" title={p.deck_dir}>
                        {p.title || '（無題）'}
                        <div className="muted">{p.deck_dir}</div>
                      </td>
                      <td className={selectable ? 'ng' : ''}>
                        {STATUS_LABELS[p.status]}
                        {p.status === 'exe_missing' && (
                          <div className="muted">
                            {p.exe}（更新で名前が変わったかもしれません。
                            <button className="link" onClick={(e) => { e.stopPropagation(); onOpenGame(p.id); onClose() }}>作品を開く</button>）
                          </div>
                        )}
                        {p.status === 'unreachable' && <div className="muted">SDカードが抜けていないか確認してください</div>}
                      </td>
                      <td>{p.steam_registered ? '登録済み' : ''}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  )
}
