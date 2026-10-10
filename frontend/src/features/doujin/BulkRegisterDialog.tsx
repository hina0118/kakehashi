import { useState } from 'react'
import { api, describeDuplicate, doujinApi, type DoujinGame, type FolderCandidate } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'

type Props = { onClose: () => void; onRegistered: (created: DoujinGame[]) => void }

export function BulkRegisterDialog({ onClose, onRegistered }: Props) {
  const [parent, setParent] = useState('')
  const [cands, setCands] = useState<FolderCandidate[] | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function pick() {
    setError(null)
    try {
      const [path] = await api.pickLocal('folder', '作品フォルダが入っている親フォルダを選択')
      if (!path) return
      setParent(path)
      setBusy(true)
      const list = await doujinApi.scanFolder(path)
      setCands(list)
      // 台帳の作品と重複していそうなフォルダは、最初はチェックを外しておく
      setChecked(new Set(list.filter((c) => c.registered_id === null && c.duplicates.length === 0).map((c) => c.path)))
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  async function register() {
    setBusy(true)
    setError(null)
    try {
      const created = await doujinApi.registerMany([...checked])
      onRegistered(created)
      onClose()
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  const toggle = (p: string) => setChecked((prev) => {
    const next = new Set(prev)
    if (next.has(p)) next.delete(p)
    else next.add(p)
    return next
  })

  return (
    <Modal
      title="まとめて登録"
      onClose={onClose}
      wide
      footer={
        <button className="btn primary" disabled={busy || checked.size === 0} onClick={register}>
          {busy && cands ? '登録中…' : `${checked.size}件を登録`}
        </button>
      }
    >
      <div className="form-actions">
        <button className="btn" onClick={pick} disabled={busy}>親フォルダを選択</button>
        <span className="muted">{parent || '作品フォルダが並んでいるフォルダを選ぶと、中の作品を一覧にします。'}</span>
      </div>
      {error != null && <ErrorBox error={error} />}
      {cands?.some((c) => c.duplicates.length > 0) && (
        <p className="steam-state ng">
          台帳の作品と同じかもしれないフォルダはチェックを外しています。同じ作品なら、登録せずに台帳の作品で「更新データを適用」を使ってください。
        </p>
      )}
      {cands && (
        <CandidateTable
          rows={cands.map((c) => ({
            key: c.path, name: c.name, guess: c.guess, done: c.registered_id !== null,
            sub: c.duplicates.map(describeDuplicate).join(' / ') || undefined, warn: c.duplicates.length > 0,
          }))}
          checked={checked}
          onToggle={toggle}
          doneLabel="登録済み"
        />
      )}
    </Modal>
  )
}

export function CandidateTable({ rows, checked, onToggle, doneLabel }: {
  rows: { key: string; name: string; guess: { title: string; circle: string; work_id: string }; done: boolean; sub?: string; warn?: boolean }[]
  checked: Set<string>
  onToggle: (key: string) => void
  doneLabel: string
}) {
  if (rows.length === 0) return <p className="muted">フォルダが見つかりませんでした。</p>
  return (
    <div className="coverage-table-wrap">
      <table className="coverage-table candidate-table">
        <thead>
          <tr><th /><th>フォルダ</th><th>タイトル（推定）</th><th>サークル</th><th>作品ID</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className={r.done ? 'done' : ''} onClick={() => !r.done && onToggle(r.key)}>
              <td>
                {r.done ? <span className="badge">{doneLabel}</span> : (
                  <input type="checkbox" checked={checked.has(r.key)} onChange={() => onToggle(r.key)} onClick={(e) => e.stopPropagation()} />
                )}
              </td>
              <td className="coverage-title" title={r.key}>{r.name}{r.sub && <div className={r.warn ? 'dup-note' : 'muted'}>{r.sub}</div>}</td>
              <td className="coverage-title">{r.guess.title}</td>
              <td className="coverage-title">{r.guess.circle}</td>
              <td>{r.guess.work_id}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
