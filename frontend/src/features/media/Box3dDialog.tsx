import { useEffect, useState } from 'react'
import { api, previewUrl, type PreviewInfo } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'

type Props = { system: string; path: string; defaultText: string; onClose: () => void; onSaved: () => void }

export function Box3dDialog({ system, path, defaultText, onClose, onSaved }: Props) {
  const [spineRatio, setSpineRatio] = useState(0.08)
  const [anglePct, setAnglePct] = useState(0.3)
  const [shadow, setShadow] = useState(true)
  const [spineText, setSpineText] = useState(defaultText)
  const [preview, setPreview] = useState<PreviewInfo | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)

  // スライダー操作中に連続で生成しないよう、操作が止まってから生成する
  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      api
        .preview3dbox(system, { path, spine_ratio: spineRatio, angle_pct: anglePct, shadow, spine_text: spineText })
        .then((p) => !cancelled && (setPreview(p), setError(null)))
        .catch((e) => !cancelled && setError(e))
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [system, path, spineRatio, anglePct, shadow, spineText])

  async function save() {
    if (!preview) return
    setSaving(true)
    try {
      await api.savePreview(system, '3dboxes', path, preview.id)
      onSaved()
      onClose()
    } catch (e) {
      setError(e)
      setSaving(false)
    }
  }

  return (
    <Modal
      title="カバーから3Dボックスを生成"
      onClose={onClose}
      wide
      footer={
        <button className="btn primary" disabled={!preview || saving} onClick={save}>
          {saving ? '保存中…' : '3dboxes に保存'}
        </button>
      }
    >
      <div className="gen-layout">
        <div className="gen-controls">
          <label className="field">
            <span className="field-label">背表紙の幅 {Math.round(spineRatio * 100)}%</span>
            <input type="range" min={0.02} max={0.25} step={0.01} value={spineRatio} onChange={(e) => setSpineRatio(Number(e.target.value))} />
          </label>
          <label className="field">
            <span className="field-label">奥行き {Math.round(anglePct * 100)}%</span>
            <input type="range" min={0.05} max={0.6} step={0.01} value={anglePct} onChange={(e) => setAnglePct(Number(e.target.value))} />
          </label>
          <label className="check">
            <input type="checkbox" checked={shadow} onChange={(e) => setShadow(e.target.checked)} />
            影をつける
          </label>
          <label className="field">
            <span className="field-label">背表紙のテキスト</span>
            <input value={spineText} onChange={(e) => setSpineText(e.target.value)} />
          </label>
          <p className="hint">PS2・PS3・PS4・PSP・PS Vita・PS1 は公式パッケージ風のテンプレートで装飾します。</p>
        </div>
        <div className="gen-preview checker">
          {preview ? <img src={previewUrl(preview)} alt="3Dボックスのプレビュー" /> : <span className="muted">生成中…</span>}
        </div>
      </div>
      {error != null && <ErrorBox error={error} />}
    </Modal>
  )
}
