import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, previewUrl } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'

type Props = { system: string; path: string; onClose: () => void; onSaved: () => void }

export function MiximageDialog({ system, path, onClose, onSaved }: Props) {
  const preview = useQuery({
    queryKey: ['preview-miximage', system, path],
    queryFn: () => api.previewMiximage(system, path),
    gcTime: 0,
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function save() {
    if (!preview.data) return
    setSaving(true)
    try {
      await api.savePreview(system, 'miximages', path, preview.data.id)
      onSaved()
      onClose()
    } catch (e) {
      setError(e)
      setSaving(false)
    }
  }

  return (
    <Modal
      title="miximage を生成"
      onClose={onClose}
      wide
      footer={
        <button className="btn primary" disabled={!preview.data || saving} onClick={save}>
          {saving ? '保存中…' : 'miximages に保存'}
        </button>
      }
    >
      <p className="hint">
        スクリーンショットを背景に、ロゴ（右上）・3Dボックスとディスク（左下）を重ねます。無い素材は省きます。
      </p>
      <div className="gen-preview wide checker">
        {preview.data ? <img src={previewUrl(preview.data)} alt="miximage のプレビュー" /> : <span className="muted">生成中…</span>}
      </div>
      {(preview.error ?? error) != null && <ErrorBox error={preview.error ?? error} />}
    </Modal>
  )
}
