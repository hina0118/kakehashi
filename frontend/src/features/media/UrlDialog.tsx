import { useState, type FormEvent } from 'react'
import { api, type MediaFolder } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { useRunJob } from '../../lib/jobs'

type Props = {
  system: string
  folder: MediaFolder
  path: string
  ytdlp: boolean
  onClose: () => void
  onSaved: () => void
}

export function UrlDialog({ system, folder, path, ytdlp, onClose, onSaved }: Props) {
  const runJob = useRunJob()
  const [url, setUrl] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setRunning(true)
    try {
      await runJob(() => api.importUrl(system, folder, path, url.trim()))
      onSaved()
      onClose()
    } catch (err) {
      setError(err)
    } finally {
      setRunning(false)
    }
  }

  return (
    <Modal title={`${folder} をURLから取得`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label className="field">
          <span className="field-label">URL</span>
          <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />
        </label>
        <p className="hint">
          {folder === 'videos' && ytdlp
            ? 'YouTubeなどの動画ページURL、または動画ファイルへの直リンクを指定できます（yt-dlpで取得）。'
            : '画像・動画・PDFファイルへの直リンクを指定してください。'}
          既存のファイルは置き換えられます。
        </p>
        {error != null && <ErrorBox error={error} />}
        <div className="form-actions">
          <button type="submit" className="btn primary" disabled={!url.trim() || running}>
            {running ? '取得中…' : '取得して登録'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
