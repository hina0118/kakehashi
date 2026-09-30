import { useRef, useState, type PointerEvent } from 'react'
import { api, mediaFileUrl, previewUrl, type MediaFile, type PreviewInfo } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { useRunJob } from '../../lib/jobs'

type Props = {
  system: string
  path: string
  cover: MediaFile
  aiAvailable: boolean
  onClose: () => void
  onSaved: () => void
}

type Rect = { x1: number; y1: number; x2: number; y2: number }

export function LogoDialog({ system, path, cover, aiAvailable, onClose, onSaved }: Props) {
  const runJob = useRunJob()
  const imgRef = useRef<HTMLImageElement>(null)
  const [sel, setSel] = useState<Rect | null>(null)
  const [dragging, setDragging] = useState(false)
  const [preview, setPreview] = useState<PreviewInfo | null>(null)
  const [busy, setBusy] = useState<'crop' | 'ai' | 'save' | null>(null)
  const [error, setError] = useState<unknown>(null)

  function point(e: PointerEvent) {
    const r = imgRef.current!.getBoundingClientRect()
    return {
      x: Math.min(Math.max(e.clientX - r.left, 0), r.width),
      y: Math.min(Math.max(e.clientY - r.top, 0), r.height),
    }
  }

  function onDown(e: PointerEvent) {
    e.currentTarget.setPointerCapture(e.pointerId)
    const p = point(e)
    setSel({ x1: p.x, y1: p.y, x2: p.x, y2: p.y })
    setDragging(true)
  }

  function onMove(e: PointerEvent) {
    if (!dragging) return
    const p = point(e)
    setSel((s) => (s ? { ...s, x2: p.x, y2: p.y } : s))
  }

  /** 表示上の選択範囲を元画像の座標に変換する */
  function naturalBox(): [number, number, number, number] | null {
    const img = imgRef.current
    if (!img || !sel) return null
    const scale = img.naturalWidth / img.clientWidth
    const box = [
      Math.min(sel.x1, sel.x2), Math.min(sel.y1, sel.y2),
      Math.max(sel.x1, sel.x2), Math.max(sel.y1, sel.y2),
    ].map((v) => Math.round(v * scale)) as [number, number, number, number]
    return box[2] - box[0] >= 5 && box[3] - box[1] >= 5 ? box : null
  }

  async function act(kind: 'crop' | 'ai' | 'save', fn: () => Promise<void>) {
    setError(null)
    setBusy(kind)
    try {
      await fn()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(null)
    }
  }

  const crop = () => act('crop', async () => {
    const box = naturalBox()
    if (box) setPreview(await api.previewCrop(system, path, box))
  })
  const ai = () => act('ai', async () => {
    setPreview(await runJob(() => api.previewAiLogo(system, path)))
  })
  const save = () => act('save', async () => {
    if (!preview) return
    await api.savePreview(system, 'marquees', path, preview.id)
    onSaved()
    onClose()
  })

  const hasSelection = !!sel && Math.abs(sel.x2 - sel.x1) >= 3 && Math.abs(sel.y2 - sel.y1) >= 3
  const rect = sel && {
    left: Math.min(sel.x1, sel.x2), top: Math.min(sel.y1, sel.y2),
    width: Math.abs(sel.x2 - sel.x1), height: Math.abs(sel.y2 - sel.y1),
  }

  return (
    <Modal
      title="カバーからロゴを切り出す"
      onClose={onClose}
      wide
      footer={
        <>
          {aiAvailable && (
            <button className="btn" disabled={busy !== null} onClick={ai} title="Florence-2でロゴを検出し、BiRefNetで背景を除去します">
              {busy === 'ai' ? 'AIで抽出中…' : 'AIで抽出（背景透過）'}
            </button>
          )}
          <button className="btn" disabled={busy !== null || !hasSelection} onClick={crop}>
            {busy === 'crop' ? '切り出し中…' : '選択範囲を切り出す'}
          </button>
          <button className="btn primary" disabled={busy !== null || !preview} onClick={save}>
            {busy === 'save' ? '保存中…' : 'marquees に保存'}
          </button>
        </>
      }
    >
      <p className="hint">カバー画像の上をドラッグしてロゴの範囲を選んでください。</p>
      <div className="gen-layout">
        <div
          className="crop-area"
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={() => setDragging(false)}
        >
          <img ref={imgRef} src={mediaFileUrl(system, cover)} alt="カバー" draggable={false} />
          {rect && <div className="crop-rect" style={rect} />}
        </div>
        <div className="gen-preview checker">
          {preview ? <img src={previewUrl(preview)} alt="ロゴのプレビュー" /> : <span className="muted">プレビュー</span>}
        </div>
      </div>
      {error != null && <ErrorBox error={error} />}
    </Modal>
  )
}
