import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { doujinApi, type DoujinGame } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { Modal } from '../../components/Modal'

type Props = { game: DoujinGame; onClose: () => void }

const README = /(read ?me|はじめに|説明|取扱|操作)/i

/** Deck上の作品フォルダにあるテキストファイル（readmeなど）を読む。Deck側は変更しない。 */
export function DeckTextDialog({ game, onClose }: Props) {
  const files = useQuery({ queryKey: ['deck-texts', game.id], queryFn: () => doujinApi.deckTexts(game.id) })
  const [picked, setPicked] = useState<string | null>(null)
  const selected = picked ?? files.data?.find((f) => README.test(f.path))?.path ?? files.data?.[0]?.path ?? null
  const text = useQuery({
    queryKey: ['deck-text', game.id, selected],
    queryFn: () => doujinApi.deckText(game.id, selected!),
    enabled: selected !== null,
  })

  return (
    <Modal title={`テキストファイル — ${game.title || game.deck_dir}`} onClose={onClose} wide>
      {files.isLoading && <p className="muted">Deckの作品フォルダを調べています…</p>}
      {files.error != null && <ErrorBox error={files.error} />}
      {files.data?.length === 0 && <p className="muted">作品フォルダにテキストファイルはありません。</p>}
      {files.data && files.data.length > 0 && (
        <div className="text-viewer">
          <ul className="text-files">
            {files.data.map((f) => (
              <li key={f.path}>
                <button className={f.path === selected ? 'active' : ''} title={f.path} onClick={() => setPicked(f.path)}>
                  {f.path}
                  <span className="muted">{formatSize(f.size)}</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="text-body">
            {text.isFetching && <p className="muted">読み込んでいます…</p>}
            {text.error != null && <ErrorBox error={text.error} />}
            {text.data && !text.isFetching && (
              <>
                <p className="muted">
                  {text.data.encoding}
                  {text.data.truncated && '・大きいため先頭の512KBだけを表示しています'}
                </p>
                <pre>{text.data.text}</pre>
              </>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

function formatSize(n: number): string {
  return n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`
}
