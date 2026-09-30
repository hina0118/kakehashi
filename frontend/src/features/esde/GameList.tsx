import { useMemo, useState } from 'react'
import type { EsdeGame, GameFields } from '../../api'
import { romStem } from '../../lib/esde'

type Props = {
  games: EsdeGame[]
  loading: boolean
  edits: Record<string, Partial<GameFields>>
  selected: string | null
  onSelect: (path: string) => void
  showUnregistered: boolean
  onToggleUnregistered: (v: boolean) => void
}

type Filter = 'all' | 'edited' | 'untitled'

export function GameList({ games, loading, edits, selected, onSelect, showUnregistered, onToggleUnregistered }: Props) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return games
      .map((g) => ({ game: g, name: edits[g.path]?.name ?? g.name }))
      .filter(({ game, name }) => {
        if (filter === 'edited' && !edits[game.path]) return false
        if (filter === 'untitled' && name) return false
        return !q || name.toLowerCase().includes(q) || game.path.toLowerCase().includes(q)
      })
  }, [games, edits, query, filter])

  return (
    <aside className="game-list">
      <div className="game-list-controls">
        <input
          type="search"
          placeholder="タイトル・ファイル名で絞り込み"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="game-list-filters">
          <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
            <option value="all">すべて</option>
            <option value="edited">編集中のみ</option>
            <option value="untitled">タイトル未入力</option>
          </select>
          <label className="check">
            <input type="checkbox" checked={showUnregistered} onChange={(e) => onToggleUnregistered(e.target.checked)} />
            未登録ROMも表示
          </label>
        </div>
      </div>
      <div className="game-list-count">
        {loading ? '読み込み中…' : `${rows.length} / ${games.length} 件`}
      </div>
      <ul className="game-list-items" role="listbox">
        {rows.map(({ game, name }) => (
          <li
            key={game.path}
            role="option"
            aria-selected={game.path === selected}
            className={`game-row${game.path === selected ? ' selected' : ''}`}
            onClick={() => onSelect(game.path)}
          >
            <span className={`game-row-name${name ? '' : ' placeholder'}`}>{name || romStem(game.path)}</span>
            {!game.registered && <span className="badge">未登録</span>}
            {edits[game.path] && <span className="dot" title="未プッシュの編集あり" />}
          </li>
        ))}
      </ul>
    </aside>
  )
}
