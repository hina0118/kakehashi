import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { doujinApi, type DoujinPatch } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'

export type DlsiteApply = { fields: DoujinPatch; addTags: string[]; coverUrl: string | null }

type Props = {
  workId: string
  current: { title: string; circle: string; release_date: string; url: string; store: string }
  hasCover: boolean
  onApply: (a: DlsiteApply) => void
  onClose: () => void
}

type Key = 'title' | 'circle' | 'release_date' | 'url' | 'tags' | 'cover'
type Row = { key: Key; label: string; now: string; next: string }

export function DlsiteDialog({ workId, current, hasCover, onApply, onClose }: Props) {
  const info = useQuery({ queryKey: ['dlsite', workId], queryFn: () => doujinApi.dlsite(workId) })
  // 空欄の項目だけを初期選択にし、手で入力済みの値はうっかり上書きしない
  const [picked, setPicked] = useState<Set<Key> | null>(null)
  const d = info.data

  const candidates: Row[] = d ? [
    { key: 'title', label: 'タイトル', now: current.title, next: d.title },
    { key: 'circle', label: 'サークル', now: current.circle, next: d.circle },
    { key: 'release_date', label: '発売日', now: current.release_date, next: d.release_date },
    { key: 'url', label: '作品ページ', now: current.url, next: d.url },
    { key: 'tags', label: 'ジャンルをタグに追加', now: '', next: d.genres.join('、') },
    { key: 'cover', label: 'カバー画像', now: hasCover ? '登録済み' : '', next: d.image_url ? '作品のメイン画像' : '' },
  ] : []
  const rows = candidates.filter((r) => r.next)

  const selected = picked ?? new Set(rows.filter((r) => !r.now || r.now === r.next).map((r) => r.key))

  function toggle(k: Key) {
    const next = new Set(selected)
    if (next.has(k)) next.delete(k)
    else next.add(k)
    setPicked(next)
  }

  function apply() {
    if (!d) return
    const fields: DoujinPatch = { work_id: d.work_id, store: current.store || 'dlsite' }
    if (selected.has('title')) fields.title = d.title
    if (selected.has('circle')) fields.circle = d.circle
    if (selected.has('release_date')) fields.release_date = d.release_date
    if (selected.has('url')) fields.url = d.url
    onApply({
      fields,
      addTags: selected.has('tags') ? d.genres : [],
      coverUrl: selected.has('cover') ? d.image_url : null,
    })
    onClose()
  }

  return (
    <Modal
      title={`DLsiteから取得（${workId}）`}
      onClose={onClose}
      wide
      footer={<button className="btn primary" disabled={!d || selected.size === 0} onClick={apply}>選んだ項目を反映</button>}
    >
      {info.isLoading && <p className="muted">DLsiteに問い合わせています…</p>}
      {info.error && <ErrorBox error={info.error} />}
      {d && (
        <div className="dlsite">
          {d.image_url && <img className="dlsite-image" src={d.image_url} alt="" referrerPolicy="no-referrer" />}
          <table className="dlsite-table">
            <thead>
              <tr><th /><th>項目</th><th>現在</th><th>DLsite</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} onClick={() => toggle(r.key)}>
                  <td><input type="checkbox" checked={selected.has(r.key)} onChange={() => toggle(r.key)} onClick={(e) => e.stopPropagation()} /></td>
                  <td className="nowrap">{r.label}</td>
                  <td className="muted">{r.now || '（空）'}</td>
                  <td>{r.next}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
