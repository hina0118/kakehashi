import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, steamApi, updateSettings, type DoujinGame, type SteamShortcut } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'

type Props = { onClose: () => void; onImported: (games: DoujinGame[]) => void; onOpenSettings: () => void }

export function SteamImportDialog({ onClose, onImported, onOpenSettings }: Props) {
  const qc = useQueryClient()
  const titles = new Map((qc.getQueryData<DoujinGame[]>(['doujin']) ?? []).map((g) => [g.id, g.title]))
  const scan = useQuery({ queryKey: ['steam-shortcuts'], queryFn: steamApi.shortcuts, gcTime: 0 })
  const [checked, setChecked] = useState<Set<number> | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const items = scan.data?.shortcuts ?? []
  const selectable = items.filter((s) => s.linked_id === null)
  const selected = checked ?? new Set(selectable.map((s) => s.appid))
  const outside = items.filter((s) => !s.in_base).length
  const needsSettings = scan.error instanceof ApiError && ['deck_not_configured', 'deck_unreachable'].includes(scan.error.code ?? '')

  async function addBases(paths: string[]) {
    setBusy(true)
    setError(null)
    try {
      const saved = await updateSettings((s) => ({
        steam_deck: { ...s.steam_deck, doujin_base: [...new Set([...s.steam_deck.doujin_base, ...paths])] },
      }))
      qc.setQueryData(['settings'], saved)
      setChecked(null)
      await scan.refetch()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  async function importSelected() {
    setBusy(true)
    setError(null)
    try {
      onImported(await steamApi.importShortcuts([...selected]))
      onClose()
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  const toggle = (appid: number) => {
    const next = new Set(selected)
    if (next.has(appid)) next.delete(appid)
    else next.add(appid)
    setChecked(next)
  }

  function statusOf(s: SteamShortcut) {
    if (s.linked_id !== null) return <span className="badge">台帳にあり</span>
    if (s.match_id !== null) return <span className="muted">「{titles.get(s.match_id) ?? s.match_id}」に紐づけ</span>
    return <span className="muted">新規登録</span>
  }

  return (
    <Modal
      title="Steamから取り込み"
      onClose={onClose}
      wide
      footer={
        <button className="btn primary" disabled={busy || selected.size === 0} onClick={importSelected}>
          {busy ? '処理中…' : `${selected.size}件を取り込む`}
        </button>
      }
    >
      <p className="hint">
        DeckのSteamに非Steamゲームとして登録済みの作品（Windows用のもの）を台帳に取り込みます。appID・Proton・起動オプションはそのまま引き継ぐので、
        あとから「Steamの登録を更新」しても二重登録にはならず、プレイ時間なども残ります。Steamが起動中でも取り込めます（読み取りのみ）。
      </p>
      {scan.isLoading && <p className="muted">Deckの登録内容を読み込んでいます…</p>}
      {(scan.error ?? error) != null && (
        <ErrorBox error={scan.error ?? error}>
          {needsSettings && <button className="btn" onClick={onOpenSettings}>接続設定を開く</button>}
        </ErrorBox>
      )}
      {scan.data && scan.data.suggested_bases.length > 0 && (
        <div className="steam-state ng">
          <span>
            次のフォルダに作品が置かれていますが、同人ゲームの格納先に登録されていません。格納先に登録すると、作品フォルダ（深い位置にある起動ファイルを含む）を正しく判定できます。
          </span>
          <ul className="plain-list">
            {scan.data.suggested_bases.map((b) => <li key={b}><code>{b}</code></li>)}
          </ul>
          <button className="btn small" disabled={busy} onClick={() => addBases(scan.data!.suggested_bases)}>
            格納先に登録する
          </button>
        </div>
      )}
      {scan.data && (
        <p className="muted">
          {items.length}件（台帳にあり {items.length - selectable.length}件{outside ? `・格納先の外 ${outside}件` : ''}）
        </p>
      )}
      {items.length > 0 && (
        <div className="coverage-table-wrap">
          <table className="coverage-table candidate-table">
            <thead>
              <tr><th /><th>Steamでの名前</th><th>作品フォルダ / 起動ファイル</th><th>Proton</th><th>画像</th><th>取り込み</th></tr>
            </thead>
            <tbody>
              {items.map((s) => {
                const done = s.linked_id !== null
                return (
                  <tr key={s.appid} className={done ? 'done' : ''} onClick={() => !done && toggle(s.appid)}>
                    <td>{!done && <input type="checkbox" checked={selected.has(s.appid)} onChange={() => toggle(s.appid)} onClick={(e) => e.stopPropagation()} />}</td>
                    <td className="coverage-title" title={s.name}>{s.name}</td>
                    <td className="coverage-title" title={s.exe_path}>
                      {s.deck_dir.split('/').pop()}<div className="muted">{s.exe}{s.in_base ? '' : '（格納先の外）'}</div>
                    </td>
                    <td>{s.compat_tool || '—'}</td>
                    <td>{s.has_art ? 'あり' : '—'}</td>
                    <td>{statusOf(s)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
