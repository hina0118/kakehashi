import type { EditableField, EsdeGame, GameFields } from '../../api'
import {
  SEARCH_SITES, TRANSLATE_SITES, inputToReleaseDate, openExternal, releaseDateToInput, romStem,
} from '../../lib/esde'

type Props = {
  system: string
  game: EsdeGame
  edits: Partial<GameFields>
  onChange: (field: EditableField, value: string) => void
  onDiscard: () => void
}

const LABELS: Record<EditableField, string> = {
  name: 'タイトル',
  desc: '説明',
  releasedate: '発売日',
  developer: '開発',
  publisher: '発売元',
  genre: 'ジャンル',
}

export function GameEditor({ system, game, edits, onChange, onDiscard }: Props) {
  const value = (f: EditableField) => edits[f] ?? game[f]
  const changed = (f: EditableField) => f in edits
  const hasEdits = Object.keys(edits).length > 0
  const searchText = `${value('name') || romStem(game.path)} ${system}`

  const label = (f: EditableField) => (
    <span className="field-label">
      {LABELS[f]}
      {changed(f) && (
        <button className="link" title={`元の値: ${game[f] || '（空）'}`} onClick={() => onChange(f, game[f])}>
          元に戻す
        </button>
      )}
    </span>
  )

  return (
    <section className="editor">
      <div className="editor-head">
        <code className="editor-path">{game.path}</code>
        {!game.registered && <span className="badge">未登録（プッシュすると追加されます）</span>}
        {hasEdits && <button className="btn small" onClick={onDiscard}>このゲームの編集を破棄</button>}
      </div>

      <div className="form">
        <label className={`field${changed('name') ? ' changed' : ''}`}>
          {label('name')}
          <input value={value('name')} onChange={(e) => onChange('name', e.target.value)} />
        </label>

        <div className="form-row">
          <label className={`field${changed('releasedate') ? ' changed' : ''}`}>
            {label('releasedate')}
            <input
              type="date"
              value={releaseDateToInput(value('releasedate'))}
              onChange={(e) => onChange('releasedate', inputToReleaseDate(e.target.value))}
            />
          </label>
          <label className={`field grow${changed('genre') ? ' changed' : ''}`}>
            {label('genre')}
            <input
              value={value('genre')}
              placeholder="カンマ区切り（例: RPG, アクション）"
              onChange={(e) => onChange('genre', e.target.value)}
            />
          </label>
        </div>

        <div className="form-row">
          <label className={`field grow${changed('developer') ? ' changed' : ''}`}>
            {label('developer')}
            <input value={value('developer')} onChange={(e) => onChange('developer', e.target.value)} />
          </label>
          <label className={`field grow${changed('publisher') ? ' changed' : ''}`}>
            {label('publisher')}
            <input value={value('publisher')} onChange={(e) => onChange('publisher', e.target.value)} />
          </label>
        </div>

        <label className={`field${changed('desc') ? ' changed' : ''}`}>
          {label('desc')}
          <textarea rows={10} value={value('desc')} onChange={(e) => onChange('desc', e.target.value)} />
        </label>
      </div>

      <div className="link-bar">
        <span className="link-bar-label">検索</span>
        {SEARCH_SITES.map((s) => (
          <button key={s.label} className="btn small" onClick={() => openExternal(s.url, searchText)}>
            {s.label}
          </button>
        ))}
        <span className="link-bar-label">説明を翻訳</span>
        {TRANSLATE_SITES.map((s) => (
          <button
            key={s.label}
            className="btn small"
            disabled={!value('desc')}
            onClick={() => openExternal(s.url, value('desc'))}
          >
            {s.label}
          </button>
        ))}
      </div>

      {Object.keys(game.extra).length > 0 && (
        <details className="extra">
          <summary>その他のタグ（読み取り専用）</summary>
          <dl>
            {Object.entries(game.extra).map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </section>
  )
}
