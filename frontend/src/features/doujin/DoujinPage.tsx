import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import {
  PLAY_STATUSES, PLAY_STATUS_LABELS, api, doujinApi, doujinImageUrl, type DoujinGame, type PlayStatus,
} from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { BulkRegisterDialog } from './BulkRegisterDialog'
import { DeckImportDialog } from './DeckImportDialog'
import { DoujinDetail } from './DoujinDetail'

type Sort = 'title' | 'circle' | 'updated' | 'created' | 'release'

const SORTERS: Record<Sort, (a: DoujinGame, b: DoujinGame) => number> = {
  title: (a, b) => a.title.localeCompare(b.title, 'ja'),
  circle: (a, b) => a.circle.localeCompare(b.circle, 'ja') || a.title.localeCompare(b.title, 'ja'),
  updated: (a, b) => b.updated_at.localeCompare(a.updated_at),
  created: (a, b) => b.created_at.localeCompare(a.created_at),
  release: (a, b) => b.release_date.localeCompare(a.release_date),
}

export function DoujinPage({ onOpenSettings }: { onOpenSettings: () => void }) {
  const qc = useQueryClient()
  const games = useQuery({ queryKey: ['doujin'], queryFn: doujinApi.list })
  const [selected, setSelected] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<PlayStatus | ''>('')
  const [tag, setTag] = useState('')
  const [deckFilter, setDeckFilter] = useState<'' | 'on' | 'off'>('')
  const [sort, setSort] = useState<Sort>('title')
  const [dialog, setDialog] = useState<'bulk' | 'deck' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const all = useMemo(() => games.data ?? [], [games.data])
  const allTags = useMemo(() => [...new Set(all.flatMap((g) => g.tags))].sort((a, b) => a.localeCompare(b, 'ja')), [all])

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return all
      .filter((g) => !status || g.play_status === status)
      .filter((g) => !tag || g.tags.includes(tag))
      .filter((g) => !deckFilter || (deckFilter === 'on') === !!g.deck_dir)
      .filter((g) => !q || [g.title, g.circle, g.work_id, ...g.tags].join(' ').toLowerCase().includes(q))
      .sort(SORTERS[sort])
  }, [all, query, status, tag, deckFilter, sort])

  const current = all.find((g) => g.id === selected) ?? null

  function upsert(g: DoujinGame) {
    qc.setQueryData<DoujinGame[]>(['doujin'], (prev = []) =>
      prev.some((x) => x.id === g.id) ? prev.map((x) => (x.id === g.id ? g : x)) : [...prev, g],
    )
  }

  const registerOne = useMutation({
    mutationFn: async () => {
      const [path] = await api.pickLocal('folder', '登録する作品のフォルダを選択')
      return path ? doujinApi.register(path) : null
    },
    onSuccess: (g) => {
      if (!g) return
      upsert(g)
      setSelected(g.id)
      setNotice(`「${g.title}」を登録しました。`)
    },
  })

  return (
    <div className="doujin">
      <div className="toolbar">
        <button className="btn primary" onClick={() => registerOne.mutate()} disabled={registerOne.isPending}>
          {registerOne.isPending ? '登録中…' : 'フォルダを登録'}
        </button>
        <button className="btn" onClick={() => setDialog('bulk')}>まとめて登録</button>
        <button className="btn" onClick={() => setDialog('deck')}>Deckから取り込み</button>
        <div className="toolbar-spacer" />
        {notice && <span className="notice">{notice}</span>}
      </div>

      {(games.error || registerOne.error) && <ErrorBox error={games.error ?? registerOne.error} />}

      <div className="esde-body">
        <aside className="game-list">
          <div className="game-list-controls">
            <input type="search" placeholder="タイトル・サークル・作品ID・タグ" value={query} onChange={(e) => setQuery(e.target.value)} />
            <div className="game-list-filters wrap">
              <select value={status} onChange={(e) => setStatus(e.target.value as PlayStatus | '')} aria-label="プレイ状況">
                <option value="">すべての状況</option>
                {PLAY_STATUSES.map((s) => <option key={s} value={s}>{PLAY_STATUS_LABELS[s]}</option>)}
              </select>
              <select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="タグ">
                <option value="">すべてのタグ</option>
                {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <select value={deckFilter} onChange={(e) => setDeckFilter(e.target.value as '' | 'on' | 'off')} aria-label="Deckへの転送">
                <option value="">Deck: すべて</option>
                <option value="on">Deckにある</option>
                <option value="off">Deckに無い</option>
              </select>
              <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="並び順">
                <option value="title">タイトル順</option>
                <option value="circle">サークル順</option>
                <option value="release">発売日の新しい順</option>
                <option value="created">登録の新しい順</option>
                <option value="updated">更新の新しい順</option>
              </select>
            </div>
          </div>
          <div className="game-list-count">{games.isLoading ? '読み込み中…' : `${rows.length} / ${all.length} 件`}</div>
          <ul className="game-list-items" role="listbox">
            {rows.map((g) => {
              const thumb = doujinImageUrl(g, 'cover', 96)
              return (
                <li
                  key={g.id}
                  role="option"
                  aria-selected={g.id === selected}
                  className={`game-row doujin-row${g.id === selected ? ' selected' : ''}`}
                  onClick={() => setSelected(g.id)}
                >
                  <span className="doujin-thumb">{thumb ? <img src={thumb} alt="" loading="lazy" /> : null}</span>
                  <span className="doujin-row-text">
                    <span className="game-row-name">{g.title || '（無題）'}</span>
                    <span className="doujin-row-sub">{g.circle || '　'}</span>
                  </span>
                  <span className={`status-badge ${g.play_status}`}>{PLAY_STATUS_LABELS[g.play_status]}</span>
                  {g.deck_dir && <span className="badge" title={g.deck_dir}>Deck</span>}
                </li>
              )
            })}
          </ul>
          {games.isSuccess && all.length === 0 && (
            <div className="empty-hint">
              <p>まだ登録がありません。</p>
              <p>「フォルダを登録」で作品フォルダを選ぶか、「まとめて登録」で作品フォルダの入った親フォルダを選んでください。</p>
            </div>
          )}
        </aside>

        {current ? (
          <DoujinDetail
            key={current.id}
            game={current}
            allTags={allTags}
            onSaved={upsert}
            onDeleted={() => {
              qc.setQueryData<DoujinGame[]>(['doujin'], (prev = []) => prev.filter((x) => x.id !== current.id))
              setSelected(null)
              setNotice(`「${current.title}」を台帳から削除しました。`)
            }}
            onOpenSettings={onOpenSettings}
          />
        ) : (
          <div className="editor editor-empty">作品を選択してください</div>
        )}
      </div>

      {dialog === 'bulk' && (
        <BulkRegisterDialog
          onClose={() => setDialog(null)}
          onRegistered={(created) => {
            created.forEach(upsert)
            setNotice(`${created.length}件を登録しました。`)
          }}
        />
      )}
      {dialog === 'deck' && (
        <DeckImportDialog
          onClose={() => setDialog(null)}
          onOpenSettings={onOpenSettings}
          onImported={(created) => {
            created.forEach(upsert)
            setNotice(`Deckから${created.length}件を取り込みました（既存の作品への紐づけを含む）。`)
          }}
        />
      )}
    </div>
  )
}
