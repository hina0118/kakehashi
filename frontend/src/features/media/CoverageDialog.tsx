import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { MEDIA_FOLDERS, api, type EsdeGame, type MediaFolder } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'
import { romStem } from '../../lib/esde'

type Props = {
  system: string
  games: EsdeGame[]
  onSelect: (path: string) => void
  onClose: () => void
}

export function CoverageDialog({ system, games, onSelect, onClose }: Props) {
  const coverage = useQuery({ queryKey: ['coverage', system], queryFn: () => api.coverage(system) })
  const [folders, setFolders] = useState<Set<MediaFolder>>(new Set(MEDIA_FOLDERS))
  const [onlyMissing, setOnlyMissing] = useState(true)

  const rows = useMemo(() => {
    const cov = coverage.data ?? {}
    return games.map((g) => {
      const have = cov[romStem(g.path)] ?? {}
      const missing = [...folders].filter((f) => !have[f]).length
      return { game: g, have, missing }
    })
  }, [coverage.data, games, folders])

  const shown = onlyMissing ? rows.filter((r) => r.missing > 0) : rows
  const cols = MEDIA_FOLDERS.filter((f) => folders.has(f))

  function toggle(f: MediaFolder) {
    setFolders((prev) => {
      const next = new Set(prev)
      if (next.has(f)) next.delete(f)
      else next.add(f)
      return next
    })
  }

  return (
    <Modal title={`メディアチェック（${system}）`} onClose={onClose} wide>
      <div className="coverage-controls">
        <span className="field-label">確認する種類</span>
        {MEDIA_FOLDERS.map((f) => (
          <label key={f} className="check">
            <input type="checkbox" checked={folders.has(f)} onChange={() => toggle(f)} />
            {f}
          </label>
        ))}
      </div>
      <div className="coverage-summary">
        <label className="check">
          <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
          足りないものがあるゲームだけ表示
        </label>
        <span className="muted">{games.length} 件中 {rows.filter((r) => r.missing > 0).length} 件に不足あり</span>
      </div>
      {coverage.error && <ErrorBox error={coverage.error} />}
      <div className="coverage-table-wrap">
        <table className="coverage-table">
          <thead>
            <tr>
              <th>タイトル</th>
              {cols.map((f) => <th key={f}>{f}</th>)}
            </tr>
          </thead>
          <tbody>
            {shown.map(({ game, have }) => (
              <tr key={game.path} onClick={() => { onSelect(game.path); onClose() }}>
                <td className="coverage-title">{game.name || romStem(game.path)}</td>
                {cols.map((f) => (
                  <td key={f} className={have[f] ? 'ok' : 'ng'}>{have[f] ? '○' : '—'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">行をクリックするとそのゲームを開きます。</p>
    </Modal>
  )
}
