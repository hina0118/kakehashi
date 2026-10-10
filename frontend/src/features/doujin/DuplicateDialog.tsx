import { useState } from 'react'
import { DUPLICATE_REASON_LABELS, doujinApi, type DoujinGame, type DuplicateHit } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { useRunJob } from '../../lib/jobs'

type Props = {
  path: string
  hits: DuplicateHit[]
  onClose: () => void
  /** 別の作品として登録する */
  onRegister: () => void
  /** 既存の作品の更新データとして使う（PC側の作品フォルダは用意済み） */
  onUseAsUpdate: (game: DoujinGame) => void
}

/** 登録しようとしたフォルダが、台帳の作品と同じかもしれないときに選んでもらう。 */
export function DuplicateDialog({ path, hits, onClose, onRegister, onUseAsUpdate }: Props) {
  const runJob = useRunJob()
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)

  async function applyAsUpdate(hit: DuplicateHit) {
    setBusy(hit.id)
    setError(null)
    try {
      // PC側に作品フォルダが無ければ、Deckを正として先に取得しておく
      if (!hit.has_local) await runJob(() => doujinApi.pull(hit.id))
      onUseAsUpdate(await doujinApi.get(hit.id))
    } catch (e) {
      setError(e)
      setBusy(null)
    }
  }

  return (
    <Modal
      title="同じ作品が台帳にあるかもしれません"
      onClose={onClose}
      wide
      footer={
        <button className="btn" disabled={busy !== null} onClick={onRegister}>別の作品として登録</button>
      }
    >
      <p className="hint">
        <code>{path}</code> は、次の作品と同じかもしれません。新しいバージョンやパッチなら、登録せずに既存の作品の「更新データ」として使うと、
        Deck上のセーブやSteamのプレイ記録を引き継げます。
      </p>
      <ul className="dup-list">
        {hits.map((h) => {
          const canUpdate = h.has_local || !!h.deck_dir
          return (
            <li key={h.id}>
              <div>
                <div>{h.title || '（無題）'}</div>
                <div className="muted">
                  {h.reasons.map((r) => DUPLICATE_REASON_LABELS[r]).join('・')}が一致
                  {h.deck_dir && ` ／ Deck: ${h.deck_dir}`}
                </div>
              </div>
              <button
                className="btn primary"
                disabled={busy !== null || !canUpdate}
                title={canUpdate ? undefined : 'PCにもDeckにも作品フォルダが無いため使えません'}
                onClick={() => applyAsUpdate(h)}
              >
                {busy === h.id ? 'Deckから取得中…' : h.has_local ? 'この作品の更新データとして使う' : 'Deckから取得して更新データとして使う'}
              </button>
            </li>
          )
        })}
      </ul>
      {error != null && <ErrorBox error={error} />}
    </Modal>
  )
}
