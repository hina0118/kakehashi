import { useState } from 'react'
import { DOUJIN_IMAGE_KINDS, api, doujinApi, doujinImageUrl, type DoujinGame, type DoujinImageKind } from '../../api'
import { Modal } from '../../components/Modal'

const KIND_INFO: Record<DoujinImageKind, { label: string; hint: string }> = {
  cover: { label: 'カバー', hint: '縦長 600×900（Steamのライブラリ表示）' },
  header: { label: 'ヘッダー', hint: '横長 920×430' },
  hero: { label: 'ヒーロー', hint: '背景 1920×620' },
  logo: { label: 'ロゴ', hint: '透過PNG推奨' },
  icon: { label: 'アイコン', hint: '正方形' },
}

type Props = { game: DoujinGame; onChanged: (g: DoujinGame) => void; onError: (e: unknown) => void }

export function DoujinImages({ game, onChanged, onError }: Props) {
  const [kind, setKind] = useState<DoujinImageKind>('cover')
  const [busy, setBusy] = useState(false)
  const [urlOpen, setUrlOpen] = useState(false)
  const [zoom, setZoom] = useState(false)
  const url = doujinImageUrl(game, kind, 480)

  async function run(fn: () => Promise<DoujinGame | null>) {
    setBusy(true)
    onError(null)
    try {
      const g = await fn()
      if (g) onChanged(g)
    } catch (e) {
      onError(e)
    } finally {
      setBusy(false)
    }
  }

  const pickFile = () => run(async () => {
    const [source] = await api.pickLocal('file', `${KIND_INFO[kind].label}の画像を選択`, 'image')
    return source ? doujinApi.importImageFile(game.id, kind, source) : null
  })

  return (
    <div className="doujin-images">
      <div className="image-kinds" role="tablist">
        {DOUJIN_IMAGE_KINDS.map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={k === kind}
            aria-label={KIND_INFO[k].label}
            className={`${k === kind ? 'active' : ''}${game.images[k] ? ' has' : ''}`}
            onClick={() => setKind(k)}
            title={KIND_INFO[k].hint}
          >
            {KIND_INFO[k].label}
          </button>
        ))}
      </div>
      <div className={`doujin-image-frame checker ${kind}`}>
        {busy ? (
          <span className="muted">処理中…</span>
        ) : url ? (
          <button className="thumb-btn" onClick={() => setZoom(true)}><img src={url} alt={KIND_INFO[kind].label} /></button>
        ) : (
          <span className="muted">{KIND_INFO[kind].hint}</span>
        )}
      </div>
      <div className="media-actions">
        <button className="btn small" onClick={pickFile} disabled={busy}>ファイル</button>
        <button className="btn small" onClick={() => setUrlOpen(true)} disabled={busy}>URL</button>
        {game.images[kind] && (
          <button className="btn small danger" disabled={busy} onClick={() => run(() => doujinApi.deleteImage(game.id, kind))}>削除</button>
        )}
      </div>

      {urlOpen && (
        <UrlPrompt
          title={`${KIND_INFO[kind].label}をURLから取得`}
          onClose={() => setUrlOpen(false)}
          onSubmit={(u) => { setUrlOpen(false); run(() => doujinApi.importImageUrl(game.id, kind, u)) }}
        />
      )}
      {zoom && url && (
        <Modal title={`${game.title} / ${KIND_INFO[kind].label}`} onClose={() => setZoom(false)} wide>
          <div className="lightbox checker"><img src={doujinImageUrl(game, kind)!} alt="" /></div>
        </Modal>
      )}
    </div>
  )
}

function UrlPrompt({ title, onClose, onSubmit }: { title: string; onClose: () => void; onSubmit: (url: string) => void }) {
  const [url, setUrl] = useState('')
  return (
    <Modal title={title} onClose={onClose}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); onSubmit(url.trim()) }}>
        <input autoFocus value={url} placeholder="https://" onChange={(e) => setUrl(e.target.value)} />
        <div className="form-actions">
          <button type="submit" className="btn primary" disabled={!url.trim().startsWith('http')}>取得</button>
        </div>
      </form>
    </Modal>
  )
}
