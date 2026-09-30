import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { MEDIA_FOLDERS, api, mediaFileUrl, type EsdeGame, type MediaFile, type MediaFolder } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { openExternal, romStem } from '../../lib/esde'
import { Box3dDialog } from './Box3dDialog'
import { Lightbox } from './Lightbox'
import { LogoDialog } from './LogoDialog'
import { MiximageDialog } from './MiximageDialog'
import { UrlDialog } from './UrlDialog'

const FOLDER_LABELS: Record<MediaFolder, string> = {
  '3dboxes': '3Dボックス',
  backcovers: '裏表紙',
  covers: 'カバー',
  fanart: 'ファンアート',
  manuals: '説明書',
  marquees: 'ロゴ',
  miximages: 'miximage',
  physicalmedia: 'ディスク',
  screenshots: 'スクリーンショット',
  titlescreens: 'タイトル画面',
  videos: '動画',
}

type Dialog =
  | { type: 'url'; folder: MediaFolder }
  | { type: '3dbox' | 'logo' | 'miximage' }
  | { type: 'lightbox'; file: MediaFile }

type Props = { system: string; game: EsdeGame; title: string }

export function MediaPanel({ system, game, title }: Props) {
  const qc = useQueryClient()
  const media = useQuery({ queryKey: ['media', system, game.path], queryFn: () => api.gameMedia(system, game.path) })
  const caps = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities })
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState<MediaFolder | null>(null)

  const files = media.data?.files
  const has = (f: MediaFolder) => !!files?.[f]
  const label = title || romStem(game.path)

  async function refresh() {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['media', system, game.path] }),
      qc.invalidateQueries({ queryKey: ['coverage', system] }),
    ])
  }

  async function run(folder: MediaFolder, fn: () => Promise<unknown>) {
    setError(null)
    setBusy(folder)
    try {
      await fn()
      await refresh()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(null)
    }
  }

  const pickFile = (folder: MediaFolder) =>
    run(folder, async () => {
      const [source] = await api.pickLocal('file', `${FOLDER_LABELS[folder]}（${folder}）のファイルを選択`, folder === 'videos' ? 'video' : folder === 'manuals' ? 'pdf' : 'image')
      if (source) await api.importFile(system, folder, game.path, source)
    })

  const remove = (folder: MediaFolder) => {
    if (!confirm(`${FOLDER_LABELS[folder]}（${files?.[folder]?.filename}）を削除しますか？\n次の「Deckへプッシュ」でDeckからも削除されます。`)) return
    return run(folder, () => api.deleteMedia(system, folder, game.path))
  }

  if (media.error) return <ErrorBox error={media.error} />

  return (
    <div className="media-panel">
      {error != null && <ErrorBox error={error} />}
      <div className="media-grid">
        {MEDIA_FOLDERS.map((folder) => {
          const file = files?.[folder] ?? null
          return (
            <div key={folder} className={`media-card${file ? '' : ' missing'}`}>
              <div className="media-card-head">
                <span className="media-card-title">{FOLDER_LABELS[folder]}</span>
                <code className="media-card-folder">{folder}</code>
              </div>
              <div className="media-thumb">
                {busy === folder ? (
                  <span className="muted">処理中…</span>
                ) : file ? (
                  <MediaPreview system={system} file={file} onOpen={() => setDialog({ type: 'lightbox', file })} />
                ) : (
                  <span className="muted">{media.isLoading ? '…' : 'なし'}</span>
                )}
              </div>
              <div className="media-actions">
                <button className="btn small" onClick={() => pickFile(folder)}>{file ? '差し替え' : 'ファイル'}</button>
                <button className="btn small" onClick={() => setDialog({ type: 'url', folder })}>URL</button>
                {!file && (
                  <button className="btn small" title="Google画像検索" onClick={() => openExternal(`https://www.google.com/search?tbm=isch&q={q}`, `${label} ${folder}`)}>
                    検索
                  </button>
                )}
                {folder === '3dboxes' && (
                  <button className="btn small" disabled={!has('covers')} title={has('covers') ? undefined : 'カバー画像が必要です'} onClick={() => setDialog({ type: '3dbox' })}>
                    生成
                  </button>
                )}
                {folder === 'marquees' && (
                  <button className="btn small" disabled={!has('covers')} title={has('covers') ? undefined : 'カバー画像が必要です'} onClick={() => setDialog({ type: 'logo' })}>
                    切り出し
                  </button>
                )}
                {folder === 'miximages' && (
                  <button className="btn small" disabled={!has('screenshots')} title={has('screenshots') ? undefined : 'スクリーンショットが必要です'} onClick={() => setDialog({ type: 'miximage' })}>
                    生成
                  </button>
                )}
                {file && <button className="btn small danger" onClick={() => remove(folder)}>削除</button>}
              </div>
            </div>
          )
        })}
      </div>

      {dialog?.type === 'lightbox' && (
        <Lightbox system={system} file={dialog.file} onClose={() => setDialog(null)} />
      )}
      {dialog?.type === 'url' && (
        <UrlDialog
          system={system}
          folder={dialog.folder}
          path={game.path}
          ytdlp={caps.data?.ytdlp ?? false}
          onClose={() => setDialog(null)}
          onSaved={refresh}
        />
      )}
      {dialog?.type === '3dbox' && files?.covers && (
        <Box3dDialog system={system} path={game.path} defaultText={label} onClose={() => setDialog(null)} onSaved={refresh} />
      )}
      {dialog?.type === 'logo' && files?.covers && (
        <LogoDialog system={system} path={game.path} cover={files.covers} aiAvailable={caps.data?.ai_logo ?? false} onClose={() => setDialog(null)} onSaved={refresh} />
      )}
      {dialog?.type === 'miximage' && (
        <MiximageDialog system={system} path={game.path} onClose={() => setDialog(null)} onSaved={refresh} />
      )}
    </div>
  )
}

function MediaPreview({ system, file, onOpen }: { system: string; file: MediaFile; onOpen: () => void }) {
  if (file.kind === 'image') {
    return (
      <button className="thumb-btn" onClick={onOpen} title={file.filename}>
        <img src={mediaFileUrl(system, file, 320)} alt={file.filename} loading="lazy" />
      </button>
    )
  }
  if (file.kind === 'video') {
    return <video src={mediaFileUrl(system, file)} controls preload="metadata" />
  }
  return (
    <a href={mediaFileUrl(system, file)} target="_blank" rel="noopener" className="file-link">
      {file.filename}
    </a>
  )
}
