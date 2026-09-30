import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { STORE_LABELS, doujinApi, type DoujinPatch } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'

export type WorkApply = { fields: DoujinPatch; addTags: string[]; coverUrl: string | null }

type Props = {
  store: string
  workId: string
  current: { title: string; circle: string; release_date: string; url: string }
  hasCover: boolean
  onApply: (a: WorkApply) => void
  onClose: () => void
}

type Key = 'title' | 'circle' | 'release_date' | 'url' | 'tags' | 'cover'
type Row = { key: Key; label: string; now: string; next: string }

/** 販売サイトの作品情報を取得し、反映する項目を選ばせる。 */
export function WorkInfoDialog({ store, workId, current, hasCover, onApply, onClose }: Props) {
  const info = useQuery({ queryKey: ['work', store, workId], queryFn: () => doujinApi.fetchWork(store, workId) })
  const label = STORE_LABELS[store] ?? store
  // 空欄の項目だけを初期選択にし、手で入力済みの値はうっかり上書きしない
  const [picked, setPicked] = useState<Set<Key> | null>(null)
  const d = info.data

  const candidates: Row[] = d ? [
    { key: 'title', label: 'タイトル', now: current.title, next: d.title },
    { key: 'circle', label: 'サークル・ブランド', now: current.circle, next: d.circle },
    { key: 'release_date', label: '発売日', now: current.release_date, next: d.release_date },
    { key: 'url', label: '作品ページ', now: current.url, next: d.url },
    { key: 'tags', label: 'ジャンルをタグに追加', now: '', next: d.genres.join('、') },
    { key: 'cover', label: 'カバー画像', now: hasCover ? '登録済み' : '', next: d.image_url ? '作品のパッケージ画像' : '' },
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
    const fields: DoujinPatch = { work_id: d.work_id, store: d.store }
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
      title={`作品情報を取得（${label} ${workId}）`}
      onClose={onClose}
      wide
      footer={<button className="btn primary" disabled={!d} onClick={apply}>選んだ項目を反映</button>}
    >
      {info.isLoading && <p className="muted">{label}に問い合わせています…</p>}
      {info.error && <ErrorBox error={info.error} />}
      {d && (
        <div className="dlsite">
          {d.image_url && <img className="dlsite-image" src={d.image_url} alt="" referrerPolicy="no-referrer" />}
          <table className="dlsite-table">
            <thead>
              <tr><th /><th>項目</th><th>現在</th><th>{label}</th></tr>
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
      {d && selected.size === 0 && <p className="hint">項目を選ばなくても、作品IDと販売サイトは設定されます。</p>}
    </Modal>
  )
}
