import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { doujinApi, steamApi, type DoujinGame, type SettingsPlanItem, type SteamGameResult } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { useRunJob } from '../../lib/jobs'

type Props = {
  /** 対象の作品（一覧で絞り込んでいる作品） */
  games: DoujinGame[]
  onClose: () => void
  onDone: (updated: DoujinGame[], message: string) => void
}

/** Proton と起動オプションを、まとめて設定してSteamに反映する。 */
export function SteamSettingsDialog({ games, onClose, onDone }: Props) {
  const runJob = useRunJob()
  const tools = useQuery({ queryKey: ['steam-compat-tools'], queryFn: steamApi.compatTools })
  const [compatTool, setCompatTool] = useState('')
  const [addOptions, setAddOptions] = useState('')
  const [plan, setPlan] = useState<SettingsPlanItem[] | null>(null)
  const [busy, setBusy] = useState<'plan' | 'apply' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [results, setResults] = useState<SteamGameResult[] | null>(null)

  const ids = games.map((g) => g.id)
  const changed = plan?.filter((p) => p.changed) ?? []
  const nothingToDo = !compatTool && !addOptions.trim()

  async function makePlan() {
    setBusy('plan')
    setError(null)
    setResults(null)
    try {
      setPlan(await steamApi.planSettings(ids, compatTool, addOptions.trim()))
    } catch (e) {
      setError(e)
    } finally {
      setBusy(null)
    }
  }

  async function apply() {
    setBusy('apply')
    setError(null)
    try {
      const r = await runJob(() => steamApi.applySettings(ids, compatTool, addOptions.trim()))
      setResults(r)
      const updated = await Promise.all(changed.map((p) => doujinApi.get(p.id)))
      const failed = r.filter((x) => x.error).length
      onDone(updated, `${changed.length}件のProton・起動オプションを変更しました${failed ? `（Steamへの反映に${failed}件失敗）` : ''}。`)
      if (!failed) onClose()
      else setPlan(null)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(null)
    }
  }

  // 条件を変えたら、確認し直してもらう
  const edit = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPlan(null) }

  return (
    <Modal
      title="Proton・起動オプションをまとめて設定"
      onClose={onClose}
      wide
      footer={
        plan ? (
          <button className="btn primary" disabled={busy !== null || changed.length === 0} onClick={apply}>
            {busy === 'apply' ? '反映中…' : `${changed.length}件を変更してSteamに反映`}
          </button>
        ) : (
          <button className="btn primary" disabled={busy !== null || nothingToDo || ids.length === 0} onClick={makePlan}>
            {busy === 'plan' ? 'Deckの今の設定を確認中…' : '変更内容を確認'}
          </button>
        )
      }
    >
      <p className="hint">
        一覧で絞り込んでいる{ids.length}件が対象です。起動オプションは、Steamの今の値に足します（同じものがあれば足さず、同じ環境変数は値を置き換えます）。
        環境変数（<code>LANG=ja_JP.UTF-8</code> など）は <code>%command%</code> の前、それ以外は後ろに足します。反映するときはDeckでSteamを終了しておいてください。
      </p>
      <div className="form-row">
        <label className="field">
          <span className="field-label">Proton</span>
          <select value={compatTool} onChange={(e) => edit(setCompatTool)(e.target.value)}>
            <option value="">変更しない</option>
            {(tools.data ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="field grow">
          <span className="field-label">足す起動オプション</span>
          <input
            value={addOptions}
            onChange={(e) => edit(setAddOptions)(e.target.value)}
            placeholder="例: LANG=ja_JP.UTF-8 %command%"
          />
        </label>
      </div>
      {tools.error != null && <ErrorBox error={tools.error} />}
      {error != null && <ErrorBox error={error} />}

      {plan && (
        <>
          <p className="muted">変更あり {changed.length}件・変更なし {plan.length - changed.length}件</p>
          <div className="coverage-table-wrap">
            <table className="coverage-table">
              <thead>
                <tr><th>タイトル</th><th>Proton</th><th>起動オプション</th><th>結果</th></tr>
              </thead>
              <tbody>
                {plan.filter((p) => p.changed).map((p) => {
                  const r = results?.find((x) => x.id === p.id)
                  return (
                    <tr key={p.id}>
                      <td className="coverage-title">
                        {p.title}
                        {!p.registered && <div className="muted">Steam未登録（台帳だけ変更）</div>}
                      </td>
                      <td>{p.compat_before === p.compat_after ? p.compat_after : <>{p.compat_before || '（なし）'} → <b>{p.compat_after}</b></>}</td>
                      <td>
                        {p.options_before === p.options_after ? <code>{p.options_after || '（なし）'}</code> : (
                          <>
                            <div className="muted"><code>{p.options_before || '（なし）'}</code></div>
                            <div>→ <code>{p.options_after}</code></div>
                          </>
                        )}
                        {p.replaced.length > 0 && <div className="dup-note">置き換え: {p.replaced.join('、')}</div>}
                      </td>
                      <td className={r?.error ? 'ng' : ''}>{r ? (r.error ?? r.action) : ''}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {changed.length === 0 && <p className="notice">すべての作品がすでにこの設定になっています。</p>}
        </>
      )}
    </Modal>
  )
}
