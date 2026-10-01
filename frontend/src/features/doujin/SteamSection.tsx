import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  STEAM_ART_KINDS, api, doujinApi, steamApi, steamArtUrl, summarizeArt, type DoujinGame, type SteamArtKind,
} from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { useRunJob } from '../../lib/jobs'
import { SteamArtPullDialog } from './SteamArtPullDialog'

const ART_LABELS: Record<SteamArtKind, string> = {
  portrait: 'カバー',
  header: 'ヘッダー',
  hero: 'ヒーロー',
  logo: 'ロゴ',
  icon: 'アイコン',
}

type Props = {
  game: DoujinGame
  compatTool: string
  launchOptions: string
  onCompatTool: (v: string) => void
  onLaunchOptions: (v: string) => void
  onDone: (g: DoujinGame) => void
  dirty: boolean
}

export function SteamSection({ game, compatTool, launchOptions, onCompatTool, onLaunchOptions, onDone, dirty }: Props) {
  const runJob = useRunJob()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const tools = useQuery({ queryKey: ['steam-compat-tools'], queryFn: steamApi.compatTools, retry: false })
  // 反映したときに画像がどう扱われるか（Deckにつながらないときは表示しない）
  const artStatus = useQuery({
    queryKey: ['steam-art-status', game.id, game.updated_at, JSON.stringify(game.images), game.steam_registered_at],
    queryFn: () => steamApi.artStatus(game.id),
    retry: false,
  })
  const statusOf = (k: string) => artStatus.data?.find((d) => d.slot === k)
  const [busy, setBusy] = useState<'apply' | 'remove' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [overwriteArt, setOverwriteArt] = useState(false)
  const [showPull, setShowPull] = useState(false)
  // 作れなかった（元になる画像が無い）種類。URLが変わったら確認し直す
  const [missingArt, setMissingArt] = useState<Record<string, boolean>>({})

  const defaults = settings.data?.steam_deck
  const registered = !!game.steam_registered_at
  const missing = !game.deck_dir ? 'Deckへ転送してから登録できます。' : !game.exe ? '起動ファイルを設定してください。' : null
  const isWindows = /\.(exe|bat|msi|lnk)$/i.test(game.exe)
  const toolOptions = [...new Set([...(tools.data ?? []), compatTool].filter(Boolean))]

  async function run(kind: 'apply' | 'remove') {
    if (kind === 'remove' && !confirm(`「${game.title}」をSteamから外しますか？\nゲーム本体やセーブデータは削除しません。`)) return
    setBusy(kind)
    setError(null)
    setMessage(null)
    try {
      const [r] = await runJob(() => (kind === 'apply' ? steamApi.apply([game.id], overwriteArt) : steamApi.remove([game.id])))
      if (r.error) throw new Error(r.error)
      const artSummary = kind === 'apply' ? summarizeArt(r.art) : ''
      setMessage(
        kind === 'apply'
          ? `Steamに${r.action}しました${artSummary ? `（画像: ${artSummary}）` : ''}。DeckでSteamを起動すると反映されます。`
          : 'Steamから外しました。',
      )
      artStatus.refetch()
      onDone(await doujinApi.get(game.id))
    } catch (e) {
      setError(e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <fieldset className="doujin-section">
      <legend>Steam</legend>
      <div className="transfer-row">
        {registered ? (
          <span className="status-badge cleared">登録済み</span>
        ) : (
          <span className="status-badge">未登録</span>
        )}
        {game.steam_appid && <span className="muted">appID {game.steam_appid}</span>}
        {game.steam_registered_at && (
          <span className="muted">{new Date(game.steam_registered_at).toLocaleString('ja-JP')}</span>
        )}
      </div>

      <div className="steam-art">
        {STEAM_ART_KINDS.map((k) => (
          <figure key={k} className={`steam-art-item ${k}`}>
            <div className={`steam-art-frame${missingArt[steamArtUrl(game, k)] ? '' : ' checker'}`}>
              {missingArt[steamArtUrl(game, k)] ? (
                <span className="muted">なし</span>
              ) : (
                <img
                  src={steamArtUrl(game, k)}
                  alt={ART_LABELS[k]}
                  loading="lazy"
                  onError={() => setMissingArt((m) => ({ ...m, [steamArtUrl(game, k)]: true }))}
                />
              )}
            </div>
            <figcaption>
              {ART_LABELS[k]}
              {statusOf(k) && statusOf(k)!.status !== 'no_source' && (
                <span className={`art-status ${statusOf(k)!.status}`} title={statusOf(k)!.label}>{shortLabel(statusOf(k)!.status)}</span>
              )}
            </figcaption>
          </figure>
        ))}
      </div>
      <p className="hint">
        台帳の画像からSteam用の各サイズを作ります。比率が合わないものは、ぼかした背景に収めます。ロゴとアイコンは台帳に登録したときだけ送ります。
        反映するときは種類ごとに、台帳の画像が前回から変わったものだけを書き込みます。Steamで設定し直した画像は残します。
      </p>
      <div className="transfer-row">
        <label className="check">
          <input type="checkbox" checked={overwriteArt} onChange={(e) => setOverwriteArt(e.target.checked)} />
          判定に関係なく台帳の画像で置き換える
        </label>
        <button
          className="btn small"
          disabled={!game.steam_appid && !(game.deck_dir && game.exe)}
          title="Steam で設定済みの画像（カバー・ヘッダーなど）を台帳に取り込みます"
          onClick={() => setShowPull(true)}
        >
          Steamの画像を台帳に取り込む
        </button>
      </div>
      {showPull && <SteamArtPullDialog game={game} onClose={() => setShowPull(false)} onDone={onDone} />}

      <div className="form-row">
        <label className="field grow">
          <span className="field-label">互換ツール（Proton）</span>
          <select value={compatTool} onChange={(e) => onCompatTool(e.target.value)} disabled={!isWindows && !!game.exe}>
            <option value="">{registered ? '変更しない（Steamの現在の設定のまま）' : `既定（${defaults?.default_compat_tool || '未設定'}）`}</option>
            {toolOptions.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="field grow">
          <span className="field-label">起動オプション</span>
          <input
            value={launchOptions}
            placeholder={registered ? '空欄ならSteamの現在の設定のまま' : `既定: ${defaults?.default_launch_options || '（なし）'}`}
            onChange={(e) => onLaunchOptions(e.target.value)}
          />
        </label>
      </div>
      {!isWindows && game.exe && <p className="hint">起動ファイルがWindows用ではないため、Protonは割り当てません。</p>}

      <div className="transfer-row">
        <button className="btn primary" disabled={busy !== null || !!missing || dirty} onClick={() => run('apply')}>
          {busy === 'apply' ? '書き込み中…' : registered ? 'Steamの登録を更新' : 'Steamに登録'}
        </button>
        {game.steam_appid !== null && registered && (
          <button className="btn danger" disabled={busy !== null} onClick={() => run('remove')}>
            {busy === 'remove' ? '解除中…' : 'Steamから外す'}
          </button>
        )}
        {missing && <span className="muted">{missing}</span>}
        {dirty && !missing && <span className="muted">保存が終わるまでお待ちください。</span>}
      </div>
      <p className="hint">
        書き込みはDeckのSteamが終了している間だけできます。デスクトップモードに切り替え、Steamを終了してから実行してください。
      </p>
      {message && <span className="notice">{message}</span>}
      {error != null && <ErrorBox error={error} />}
    </fieldset>
  )
}

const SHORT_LABELS: Record<string, string> = {
  new: '新規',
  updated: '更新あり',
  forced: '置き換え',
  same: '変更なし',
  steam_changed: 'Steamで変更',
  unmanaged: 'Steamで設定',
  conflict: '両方で変更',
}

function shortLabel(status: string): string {
  return SHORT_LABELS[status] ?? status
}
