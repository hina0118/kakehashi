import { useState } from 'react'
import { api, doujinApi, type DoujinGame, type UpdatePlan } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { useRunJob } from '../../lib/jobs'

type Props = { game: DoujinGame; onClose: () => void; onApplied: (g: DoujinGame) => void }

const STATUS_LABELS = { new: '追加', changed: '変更' } as const

/** 展開済みの更新データ（フォルダ）を、PC側の作品フォルダに重ねる。 */
export function UpdateDialog({ game, onClose, onApplied }: Props) {
  const runJob = useRunJob()
  const [source, setSource] = useState('')
  const [plan, setPlan] = useState<UpdatePlan | null>(null)
  const [version, setVersion] = useState('')
  const [busy, setBusy] = useState<'pick' | 'plan' | 'apply' | null>(null)
  const [error, setError] = useState<unknown>(null)

  async function makePlan(src: string, root?: string) {
    setBusy('plan')
    setError(null)
    try {
      const p = await doujinApi.planUpdate(game.id, src, root)
      setPlan(p)
      if (root === undefined) setVersion(p.version || game.version)
    } catch (e) {
      setError(e)
      setPlan(null)
    } finally {
      setBusy(null)
    }
  }

  async function pick() {
    setBusy('pick')
    setError(null)
    try {
      const [path] = await api.pickLocal('folder', '更新データ（展開済みのフォルダ）を選択')
      if (path) {
        setSource(path)
        await makePlan(path)
      }
    } catch (e) {
      setError(e)
    } finally {
      setBusy((b) => (b === 'pick' ? null : b))
    }
  }

  async function apply() {
    if (!plan) return
    setBusy('apply')
    setError(null)
    try {
      const r = await runJob(() => doujinApi.applyUpdate(game.id, source, plan.root, version.trim()))
      const updated = await doujinApi.get(game.id)
      onApplied(updated)
      if (!r.exe_exists) {
        alert(`起動ファイル（${game.exe}）が作品フォルダにありません。新しいバージョンで名前が変わっていないか確認してください。`)
      }
      onClose()
    } catch (e) {
      setError(e)
      setBusy(null)
    }
  }

  const changes = plan ? plan.new + plan.changed : 0

  return (
    <Modal
      title="更新データを適用"
      onClose={onClose}
      wide
      footer={
        <button className="btn primary" disabled={!plan || changes === 0 || busy !== null} onClick={apply}>
          {busy === 'apply' ? '適用中…' : `${changes}ファイルを上書き・追加`}
        </button>
      }
    >
      <p className="hint">
        新しいバージョンやパッチを展開したフォルダを選ぶと、PC側の作品フォルダ（{game.local_path || '未設定'}）に重ねます。
        追加・変更されたファイルだけを書き込み、何も削除しません（セーブデータも残ります）。適用したあと「Deckへ反映」で送ってください。
      </p>
      <div className="form-actions">
        <button className="btn" onClick={pick} disabled={busy !== null}>
          {busy === 'pick' ? '選択中…' : '更新データのフォルダを選ぶ'}
        </button>
        {source && <code className="muted">{source}</code>}
      </div>
      {busy === 'plan' && <p className="muted">中身を確認しています…</p>}
      {error != null && <ErrorBox error={error} />}

      {plan && (
        <>
          <div className="form-row">
            <label className="field grow">
              <span className="field-label">作品フォルダに当たる位置（更新データの中）</span>
              <select value={plan.root} onChange={(e) => makePlan(source, e.target.value)} disabled={busy !== null}>
                {plan.root_candidates.map((r) => <option key={r} value={r}>{r || '（選んだフォルダの直下）'}</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field-label">バージョン</span>
              <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder={game.version || '例: 1.15'} />
            </label>
          </div>
          {plan.exe_found ? (
            <p className="notice">起動ファイル（{game.exe}）の位置で合わせました。</p>
          ) : (
            <p className="steam-state ng">
              更新データの中に起動ファイル（{game.exe || '未設定'}）が見つからなかったため、作品フォルダのファイルと最もよく一致する位置を選びました。差分パッチでなければ、位置が正しいか確かめてください。
            </p>
          )}
          <p className="muted">
            追加 {plan.new}件・変更 {plan.changed}件・同じ {plan.same}件
            {plan.files.length < changes && `（先頭の${plan.files.length}件を表示）`}
          </p>
          {changes > 0 ? (
            <div className="coverage-table-wrap">
              <table className="coverage-table">
                <thead><tr><th>ファイル</th><th>種類</th><th>サイズ</th></tr></thead>
                <tbody>
                  {plan.files.map((f) => (
                    <tr key={f.path}>
                      <td className="coverage-title" title={f.path}>{f.path}</td>
                      <td className={f.status === 'new' ? 'ok' : ''}>{STATUS_LABELS[f.status]}</td>
                      <td>{formatSize(f.size)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">作品フォルダはすでにこの更新データと同じ内容です。</p>
          )}
        </>
      )}
    </Modal>
  )
}

function formatSize(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  if (n >= 1024) return `${Math.round(n / 1024)} KB`
  return `${n} B`
}
