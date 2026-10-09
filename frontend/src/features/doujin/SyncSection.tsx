import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, doujinApi, type DoujinGame, type PullResult, type PushResult, type SyncStatus } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { useRunJob } from '../../lib/jobs'
import { DeckTextDialog } from './DeckTextDialog'
import { UpdateDialog } from './UpdateDialog'

type Props = {
  game: DoujinGame
  dirty: boolean
  onDone: (g: DoujinGame) => void
  onOpenSettings: () => void
}

/** Deckを正として、作品フォルダを取得・更新・反映する。 */
export function SyncSection({ game, dirty, onDone, onOpenSettings }: Props) {
  const runJob = useRunJob()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const bases = settings.data?.steam_deck.doujin_base ?? []
  const pcBase = settings.data?.windows.doujin_base ?? ''
  const [base, setBase] = useState('')
  const [busy, setBusy] = useState<'pull' | 'push' | 'status' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [pulled, setPulled] = useState<PullResult | null>(null)
  const [pushed, setPushed] = useState<PushResult | null>(null)
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const [showUpdate, setShowUpdate] = useState(false)
  const [showTexts, setShowTexts] = useState(false)
  const chosenBase = base || bases[0] || ''
  const hasLocal = !!game.local_path || (!!pcBase && !!game.deck_dir)

  async function act<T>(kind: 'pull' | 'push' | 'status', fn: () => Promise<T>, done: (r: T) => void) {
    setBusy(kind)
    setError(null)
    try {
      done(await fn())
      if (kind !== 'status') {
        setStatus(null)
        onDone(await doujinApi.get(game.id))
      }
    } catch (e) {
      setError(e)
    } finally {
      setBusy(null)
    }
  }

  const pull = (force = false) =>
    act('pull', () => runJob(() => doujinApi.pull(game.id, force)), (r) => { setPulled(r); setPushed(null) })
  const push = (force = false) =>
    act('push', () => runJob(() => doujinApi.push(game.id, game.deck_dir ? null : chosenBase, force)), (r) => { setPushed(r); setPulled(null) })
  const checkStatus = () =>
    act('status', () => doujinApi.syncStatus(game.id), (r) => { setStatus(r); setPulled(null); setPushed(null) })

  return (
    <div className="transfer">
      <div className="transfer-row">
        <span className="muted">
          Deck: {game.deck_dir || '（未転送）'}
          {game.version && <> ／ バージョン {game.version}</>}
        </span>
      </div>
      {!game.local_path && !pcBase && game.deck_dir && (
        <span className="muted">
          PC側の同人ゲームフォルダが未設定です。<button className="link" onClick={onOpenSettings}>設定を開く</button>
        </span>
      )}

      <div className="transfer-row">
        <button className="btn" disabled={busy !== null || !game.deck_dir || (!game.local_path && !pcBase)} onClick={() => pull()}>
          {busy === 'pull' ? '取得中…' : 'Deckから取得'}
        </button>
        <button className="btn" disabled={busy !== null || !hasLocal || dirty} onClick={() => setShowUpdate(true)}>
          更新データを適用
        </button>
        {!game.deck_dir && bases.length > 0 && (
          <select value={chosenBase} onChange={(e) => setBase(e.target.value)} aria-label="Deckの格納先">
            {bases.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        )}
        <button
          className="btn primary"
          disabled={busy !== null || !hasLocal || dirty || (!game.deck_dir && !chosenBase)}
          onClick={() => push()}
        >
          {busy === 'push' ? '反映中…' : 'Deckへ反映'}
        </button>
        <button className="btn small" disabled={busy !== null || !hasLocal} onClick={checkStatus}>
          {busy === 'status' ? '確認中…' : '差分を確認'}
        </button>
        <button className="btn small" disabled={!game.deck_dir} onClick={() => setShowTexts(true)}>
          テキストを読む
        </button>
      </div>
      <p className="hint">
        Deck上のファイルを正とします。「Deckから取得」→「更新データを適用」→「Deckへ反映」の順に使います。
        反映ではPCで変わったファイルだけを送り、Deckで変わったファイル（セーブなど）は上書きしません。どちらでもファイルは削除しません。
      </p>

      {pulled && (
        <div className="sync-result">
          <span className="notice">
            {pulled.downloaded}ファイルを取得しました（変更なし {pulled.unchanged}件{pulled.local_only ? `・PCにだけあるファイル ${pulled.local_only}件` : ''}）。
          </span>
          {pulled.kept_local.length > 0 && (
            <Conflict
              title={`PCで変更してまだ反映していない ${pulled.kept_local.length}ファイルは取得しませんでした。`}
              files={pulled.kept_local}
              action="Deckの内容で上書きして取得"
              onAction={() => pull(true)}
            />
          )}
        </div>
      )}
      {pushed && (
        <div className="sync-result">
          <span className="notice">
            {pushed.pushed}ファイルを反映しました（変更なし {pushed.unchanged}件
            {pushed.kept_remote.length ? `・Deckで変わったため送らなかったファイル ${pushed.kept_remote.length}件` : ''}）。
          </span>
          {pushed.conflicts.length > 0 && (
            <Conflict
              title={`PCとDeckの両方で変わっている ${pushed.conflicts.length}ファイルは送りませんでした。`}
              files={pushed.conflicts}
              action="PCの内容で上書きして反映"
              onAction={() => { if (confirm('Deckで変わった内容（セーブなど）が失われることがあります。PCの内容で上書きしますか？')) push(true) }}
            />
          )}
        </div>
      )}
      {status && (
        <div className="sync-result">
          {!status.synced_before && <span className="muted">まだDeckと同期していません。</span>}
          <FileList label="PCで変わった（反映すると送る）" files={status.local_changed} />
          <FileList label="Deckで変わった（取得すると更新される）" files={status.remote_changed} />
          <FileList label="両方で変わった" files={status.conflicts} danger />
          {!status.local_changed.length && !status.remote_changed.length && !status.conflicts.length && (
            <span className="notice">PCとDeckは同じ内容です。</span>
          )}
        </div>
      )}
      {error != null && <ErrorBox error={error} />}

      {showTexts && <DeckTextDialog game={game} onClose={() => setShowTexts(false)} />}
      {showUpdate && (
        <UpdateDialog
          game={game}
          onClose={() => setShowUpdate(false)}
          onApplied={(g) => { onDone(g); setPulled(null); setPushed(null); setStatus(null) }}
        />
      )}
    </div>
  )
}

function Conflict({ title, files, action, onAction }: { title: string; files: string[]; action: string; onAction: () => void }) {
  return (
    <div className="steam-state ng">
      <span>{title}</span>
      <FileList files={files} />
      <button className="btn small" onClick={onAction}>{action}</button>
    </div>
  )
}

function FileList({ label, files, danger }: { label?: string; files: string[]; danger?: boolean }) {
  if (files.length === 0) return null
  return (
    <details className="file-list" open={files.length <= 5}>
      <summary className={danger ? 'danger' : ''}>{label ? `${label}: ${files.length}件` : `${files.length}件`}</summary>
      <ul>
        {files.slice(0, 200).map((f) => <li key={f}><code>{f}</code></li>)}
        {files.length > 200 && <li className="muted">ほか {files.length - 200}件</li>}
      </ul>
    </details>
  )
}
