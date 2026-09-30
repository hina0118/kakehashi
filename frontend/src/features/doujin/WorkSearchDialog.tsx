import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { STORES, STORE_LABELS, doujinApi, type StoreId, type WorkHit } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { searchQueryFrom } from '../../lib/works'

type Props = {
  title: string
  onSelect: (hit: WorkHit) => void
  onClose: () => void
}

/** タイトルで販売サイトを検索し、作品を選ばせる。 */
export function WorkSearchDialog({ title, onSelect, onClose }: Props) {
  const [text, setText] = useState(() => searchQueryFrom(title))
  const [stores, setStores] = useState<Set<StoreId>>(new Set(STORES))
  const [query, setQuery] = useState<{ q: string; stores: StoreId[] } | null>(() =>
    searchQueryFrom(title) ? { q: searchQueryFrom(title), stores: [...STORES] } : null,
  )
  const result = useQuery({
    queryKey: ['work-search', query?.q, query?.stores.join(',')],
    queryFn: () => doujinApi.searchWorks(query!.q, query!.stores),
    enabled: !!query,
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (text.trim()) setQuery({ q: text.trim(), stores: [...stores] })
  }

  function toggle(s: StoreId) {
    setStores((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }

  const hits = result.data?.hits ?? []
  const errors = Object.entries(result.data?.errors ?? {})

  return (
    <Modal title="作品を検索" onClose={onClose} wide>
      <form className="form" onSubmit={submit}>
        <span className="input-with-btn">
          <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="タイトル・サークル名" />
          <button type="submit" className="btn primary" disabled={!text.trim() || stores.size === 0}>
            {result.isFetching ? '検索中…' : '検索'}
          </button>
        </span>
        <div className="chip-list">
          {STORES.map((s) => (
            <label key={s} className="check">
              <input type="checkbox" checked={stores.has(s)} onChange={() => toggle(s)} />
              {STORE_LABELS[s]}
            </label>
          ))}
        </div>
      </form>
      <p className="hint">元のタイトル: {title || '（空）'}。見つからないときは、言葉を短くするか、ひらがな・カタカナを変えて試してください。</p>

      {result.error && <ErrorBox error={result.error} />}
      {errors.map(([s, msg]) => (
        <p key={s} className="muted">{STORE_LABELS[s] ?? s} は検索できませんでした: {msg}</p>
      ))}
      {result.isSuccess && hits.length === 0 && <p className="muted">見つかりませんでした。</p>}

      <ul className="work-hits">
        {hits.map((h) => (
          <li key={`${h.store}:${h.work_id}`}>
            <button className="work-hit" onClick={() => { onSelect(h); onClose() }}>
              <span className="work-hit-image">
                {h.image_url ? <img src={h.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" /> : null}
              </span>
              <span className="work-hit-text">
                <span className="work-hit-title">{h.title}</span>
                <span className="muted">{[h.circle, h.kind].filter(Boolean).join(' / ')}</span>
                <span className="work-hit-meta">
                  <span className={`badge store-${h.store}`}>{STORE_LABELS[h.store]}</span>
                  <code>{h.work_id}</code>
                </span>
              </span>
            </button>
            <a className="link" href={h.url} target="_blank" rel="noopener">作品ページ</a>
          </li>
        ))}
      </ul>
    </Modal>
  )
}
