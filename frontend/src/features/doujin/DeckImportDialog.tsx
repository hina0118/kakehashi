import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, doujinApi, type DoujinGame } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { CandidateTable } from './BulkRegisterDialog'

type Props = { onClose: () => void; onImported: (created: DoujinGame[]) => void; onOpenSettings: () => void }

export function DeckImportDialog({ onClose, onImported, onOpenSettings }: Props) {
  const qc = useQueryClient()
  const titles = new Map((qc.getQueryData<DoujinGame[]>(['doujin']) ?? []).map((g) => [g.id, g.title]))
  const scan = useQuery({ queryKey: ['doujin-deck-scan'], queryFn: doujinApi.scanDeck, gcTime: 0 })
  const [checked, setChecked] = useState<Set<string> | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const folders = scan.data ?? []
  const selected = checked ?? new Set(folders.filter((f) => f.linked_id === null).map((f) => f.path))
  const needsSettings = scan.error instanceof ApiError && ['deck_not_configured', 'deck_unreachable'].includes(scan.error.code ?? '')

  async function importSelected() {
    setBusy(true)
    setError(null)
    try {
      onImported(await doujinApi.importFromDeck([...selected]))
      onClose()
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  const toggle = (p: string) => {
    const next = new Set(selected)
    if (next.has(p)) next.delete(p)
    else next.add(p)
    setChecked(next)
  }

  return (
    <Modal
      title="Deckから取り込み"
      onClose={onClose}
      wide
      footer={
        <button className="btn primary" disabled={busy || selected.size === 0} onClick={importSelected}>
          {busy ? '取り込み中…' : `${selected.size}件を取り込む`}
        </button>
      }
    >
      <p className="hint">
        Deckの同人ゲーム格納先にあるフォルダを台帳に取り込みます。作品IDかフォルダ名が一致する作品が台帳にあればそこへ紐づけ、無ければ新しく登録します（PC側のフォルダは空欄のまま。あとで設定できます）。
      </p>
      {scan.isLoading && <p className="muted">Deckのフォルダを確認しています…</p>}
      {scan.isSuccess && folders.length === 0 && (
        <p className="muted">格納先にフォルダがありません。<button className="link" onClick={onOpenSettings}>格納先の設定を確認</button></p>
      )}
      {(scan.error ?? error) != null && (
        <ErrorBox error={scan.error ?? error}>
          {needsSettings && <button className="btn" onClick={onOpenSettings}>接続設定を開く</button>}
        </ErrorBox>
      )}
      {folders.length > 0 && (
        <CandidateTable
          rows={folders.map((f) => ({
            key: f.path,
            name: f.name,
            sub: f.match_id !== null ? `→ 台帳の「${titles.get(f.match_id) ?? f.match_id}」と紐づけます` : f.base,
            guess: f.guess,
            done: f.linked_id !== null,
          }))}
          checked={selected}
          onToggle={toggle}
          doneLabel="台帳にあり"
        />
      )}
    </Modal>
  )
}
