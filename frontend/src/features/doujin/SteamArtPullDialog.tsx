import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { doujinApi, steamApi, steamGridImageUrl, type DoujinGame } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { useRunJob } from '../../lib/jobs'

const LABELS: Record<string, string> = { cover: 'カバー', header: 'ヘッダー', hero: 'ヒーロー', logo: 'ロゴ', icon: 'アイコン' }

type Props = { game: DoujinGame; onClose: () => void; onDone: (g: DoujinGame) => void }

/** Deck の Steam に設定されている画像を見ながら、台帳に取り込む種類を選ぶ。 */
export function SteamArtPullDialog({ game, onClose, onDone }: Props) {
  const runJob = useRunJob()
  const images = useQuery({ queryKey: ['steam-grid', game.id], queryFn: () => steamApi.gridImages(game.id), gcTime: 0 })
  const [checked, setChecked] = useState<Set<string> | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const list = images.data ?? []
  // 台帳にまだ無い種類だけを初期選択にする
  const selected = checked ?? new Set(list.filter((i) => !i.in_catalog).map((i) => i.kind))

  function toggle(kind: string) {
    const next = new Set(selected)
    if (next.has(kind)) next.delete(kind)
    else next.add(kind)
    setChecked(next)
  }

  async function pull() {
    setBusy(true)
    setError(null)
    try {
      const [r] = await runJob(() => steamApi.pullArt([game.id], [...selected], true))
      if (r.error) throw new Error(r.error)
      onDone(await doujinApi.get(game.id))
      onClose()
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Steamの画像を台帳に取り込む"
      onClose={onClose}
      wide
      footer={
        <button className="btn primary" disabled={busy || selected.size === 0} onClick={pull}>
          {busy ? '取り込み中…' : `${selected.size}種類を取り込む`}
        </button>
      }
    >
      <p className="hint">Deck の Steam に設定されている画像です。台帳に同じ種類の画像があるものは、選ぶと置き換えます。</p>
      {images.isLoading && <p className="muted">Deck から読み込んでいます…</p>}
      {(images.error ?? error) != null && <ErrorBox error={images.error ?? error} />}
      {images.isSuccess && list.length === 0 && <p className="muted">Steam に画像は設定されていません。</p>}
      <div className="steam-pull-grid">
        {list.map((img) => (
          <label key={img.kind} className={`steam-pull-item${selected.has(img.kind) ? ' selected' : ''}`}>
            <span className="steam-pull-head">
              <input type="checkbox" checked={selected.has(img.kind)} onChange={() => toggle(img.kind)} />
              {LABELS[img.kind] ?? img.kind}
              {img.in_catalog && <span className="badge">台帳にあり</span>}
            </span>
            <span className={`steam-pull-frame checker ${img.kind}`}>
              <img src={steamGridImageUrl(game.id, img.kind, img.filename)} alt={LABELS[img.kind]} />
            </span>
            <code className="muted">{img.filename.split('/').pop()}</code>
          </label>
        ))}
      </div>
    </Modal>
  )
}
