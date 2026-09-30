import { useId, useState, type KeyboardEvent } from 'react'

type Props = { value: string[]; suggestions: string[]; onChange: (tags: string[]) => void }

/** Enter・カンマ・読点でタグを確定する入力欄。既存のタグを候補として出す。 */
export function TagInput({ value, suggestions, onChange }: Props) {
  const [text, setText] = useState('')
  const listId = useId()

  function commit(raw: string) {
    const tags = raw.split(/[,、，]/).map((t) => t.trim()).filter(Boolean)
    if (tags.length) onChange([...new Set([...value, ...tags])])
    setText('')
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing) return
    if (e.key === 'Enter' || e.key === ',' || e.key === '、') {
      e.preventDefault()
      commit(text)
    } else if (e.key === 'Backspace' && !text && value.length) {
      onChange(value.slice(0, -1))
    }
  }

  return (
    <div className="tag-input">
      {value.map((t) => (
        <span key={t} className="chip">
          {t}
          <button aria-label={`${t} を外す`} onClick={() => onChange(value.filter((x) => x !== t))}>×</button>
        </span>
      ))}
      <input
        list={listId}
        value={text}
        placeholder={value.length ? '' : 'タグを入力して Enter'}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => text && commit(text)}
      />
      <datalist id={listId}>
        {suggestions.filter((s) => !value.includes(s)).map((s) => <option key={s} value={s} />)}
      </datalist>
    </div>
  )
}
