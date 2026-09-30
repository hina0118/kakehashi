import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  PLAY_STATUSES, PLAY_STATUS_LABELS, api, doujinApi, type DoujinGame, type DoujinPatch, type PlayStatus,
} from '../../api'
import { ErrorBox } from '../../components/ErrorBox'
import { useRunJob } from '../../lib/jobs'
import { DlsiteDialog, type DlsiteApply } from './DlsiteDialog'
import { DoujinImages } from './DoujinImages'
import { TagInput } from './TagInput'

type Draft = Required<Omit<DoujinPatch, 'rating'>> & { rating: number | null }

const FIELDS = [
  'title', 'circle', 'work_id', 'store', 'url', 'tags', 'description', 'release_date',
  'play_status', 'rating', 'notes', 'local_path', 'exe', 'deck_dir',
] as const

const STORES = [
  { value: '', label: '（未設定）' },
  { value: 'dlsite', label: 'DLsite' },
  { value: 'fanza', label: 'FANZA' },
  { value: 'booth', label: 'BOOTH' },
  { value: 'steam', label: 'Steam' },
  { value: 'other', label: 'その他' },
]

function toDraft(g: DoujinGame): Draft {
  return Object.fromEntries(FIELDS.map((f) => [f, g[f]])) as Draft
}

function diff(draft: Draft, g: DoujinGame): DoujinPatch {
  const out: Record<string, unknown> = {}
  for (const f of FIELDS) {
    const a = draft[f]
    const b = g[f]
    if (JSON.stringify(a) !== JSON.stringify(b)) out[f] = a
  }
  return out as DoujinPatch
}

type Props = {
  game: DoujinGame
  allTags: string[]
  onSaved: (g: DoujinGame) => void
  onDeleted: () => void
  onOpenSettings: () => void
}

export function DoujinDetail({ game, allTags, onSaved, onDeleted, onOpenSettings }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(game))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [showDlsite, setShowDlsite] = useState(false)
  const [exeCandidates, setExeCandidates] = useState<string[] | null>(null)
  // サーバ側で値が変わったとき（転送で deck_dir が入った、画像を取り込んだ等）は、
  // ユーザーがまだ触っていない項目だけを新しい値に合わせる。そうしないと古い値を自動保存で書き戻してしまう。
  const [base, setBase] = useState(game)
  if (base !== game) {
    setBase(game)
    setDraft((d) => {
      const next = { ...d } as Record<string, unknown>
      for (const f of FIELDS) {
        if (JSON.stringify(d[f]) === JSON.stringify(base[f])) next[f] = game[f]
      }
      return next as Draft
    })
  }

  const pending = diff(draft, game)
  const pendingKeys = Object.keys(pending).join(',')

  // 入力が止まってから自動保存する。作品を切り替えたとき（アンマウント時）は即座に保存する。
  const latest = useRef({ pending, id: game.id, onSaved })
  useEffect(() => {
    latest.current = { pending, id: game.id, onSaved }
  })
  useEffect(() => {
    if (!pendingKeys) return
    const timer = setTimeout(async () => {
      setSaving(true)
      try {
        onSaved(await doujinApi.update(game.id, latest.current.pending))
        setError(null)
      } catch (e) {
        setError(e)
      } finally {
        setSaving(false)
      }
    }, 700)
    return () => clearTimeout(timer)
  }, [draft, pendingKeys, game.id, onSaved])
  useEffect(() => () => {
    const { pending: p, id, onSaved: done } = latest.current
    if (Object.keys(p).length > 0) doujinApi.update(id, p).then(done).catch(() => {})
  }, [])

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }))

  async function findExe() {
    setError(null)
    try {
      setExeCandidates(await doujinApi.exeCandidates(game.id))
    } catch (e) {
      setError(e)
    }
  }

  async function changeLocalFolder() {
    const [path] = await api.pickLocal('folder', 'PC上の作品フォルダを選択')
    if (path) set('local_path', path)
  }

  async function applyDlsite(a: DlsiteApply) {
    setDraft((d) => ({ ...d, ...a.fields, tags: a.addTags.length ? [...new Set([...d.tags, ...a.addTags])] : d.tags }))
    if (a.coverUrl) {
      try {
        onSaved(await doujinApi.importImageUrl(game.id, 'cover', a.coverUrl))
      } catch (e) {
        setError(e)
      }
    }
  }

  async function remove() {
    if (!confirm(`「${game.title}」を台帳から削除しますか？\nPCやDeckにあるゲーム本体は削除しません。`)) return
    try {
      await doujinApi.remove(game.id)
      latest.current.pending = {}
      onDeleted()
    } catch (e) {
      setError(e)
    }
  }

  const isDlsite = /^(RJ|RE|VJ|BJ)\d{6,8}$/i.test(draft.work_id.trim())

  return (
    <section className="editor doujin-detail">
      <div className="editor-head">
        <span className="save-state">{saving ? '保存中…' : pendingKeys ? '編集中…' : '保存済み'}</span>
        <button className="btn small danger" onClick={remove}>台帳から削除</button>
      </div>
      {error != null && <ErrorBox error={error} />}

      <div className="doujin-top">
        <DoujinImages game={game} onChanged={onSaved} onError={setError} />
        <div className="form">
          <label className="field">
            <span className="field-label">タイトル</span>
            <input value={draft.title} onChange={(e) => set('title', e.target.value)} />
          </label>
          <div className="form-row">
            <label className="field grow">
              <span className="field-label">サークル</span>
              <input value={draft.circle} onChange={(e) => set('circle', e.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">発売日</span>
              <input type="date" value={draft.release_date} onChange={(e) => set('release_date', e.target.value)} />
            </label>
          </div>
          <div className="form-row">
            <label className="field">
              <span className="field-label">プレイ状況</span>
              <select value={draft.play_status} onChange={(e) => set('play_status', e.target.value as PlayStatus)}>
                {PLAY_STATUSES.map((s) => <option key={s} value={s}>{PLAY_STATUS_LABELS[s]}</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field-label">評価</span>
              <select
                value={draft.rating ?? ''}
                onChange={(e) => set('rating', e.target.value === '' ? null : Number(e.target.value))}
              >
                <option value="">未評価</option>
                {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{'★'.repeat(n)}{'☆'.repeat(5 - n)}</option>)}
              </select>
            </label>
          </div>
          <div className="field">
            <span className="field-label">タグ</span>
            <TagInput value={draft.tags} suggestions={allTags} onChange={(tags) => set('tags', tags)} />
          </div>
        </div>
      </div>

      <div className="form">
        <div className="form-row">
          <label className="field">
            <span className="field-label">販売サイト</span>
            <select value={draft.store} onChange={(e) => set('store', e.target.value)}>
              {STORES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
          <label className="field grow">
            <span className="field-label">作品ID</span>
            <span className="input-with-btn">
              <input value={draft.work_id} placeholder="RJ01234567 / d_123456" onChange={(e) => set('work_id', e.target.value)} />
              <button className="btn small" disabled={!isDlsite} title={isDlsite ? undefined : 'DLsiteの作品ID（RJ…）を入力すると使えます'} onClick={() => setShowDlsite(true)}>
                DLsiteから取得
              </button>
            </span>
          </label>
        </div>
        <label className="field">
          <span className="field-label">作品ページ</span>
          <span className="input-with-btn">
            <input value={draft.url} placeholder="https://" onChange={(e) => set('url', e.target.value)} />
            <button className="btn small" disabled={!draft.url.startsWith('http')} onClick={() => window.open(draft.url, '_blank', 'noopener')}>
              開く
            </button>
          </span>
        </label>
        <label className="field">
          <span className="field-label">説明</span>
          <textarea rows={5} value={draft.description} onChange={(e) => set('description', e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">メモ（攻略状況・セーブの場所など）</span>
          <textarea rows={3} value={draft.notes} onChange={(e) => set('notes', e.target.value)} />
        </label>
      </div>

      <fieldset className="doujin-section">
        <legend>ファイル</legend>
        <label className="field">
          <span className="field-label">PC上の作品フォルダ</span>
          <span className="input-with-btn">
            <input value={draft.local_path} placeholder="（未設定）" onChange={(e) => set('local_path', e.target.value)} />
            <button className="btn small" onClick={changeLocalFolder}>選択</button>
          </span>
        </label>
        <label className="field">
          <span className="field-label">起動ファイル（作品フォルダからの相対パス）</span>
          <span className="input-with-btn">
            <input value={draft.exe} placeholder="Game.exe" onChange={(e) => set('exe', e.target.value)} />
            <button className="btn small" onClick={findExe} disabled={!draft.local_path && !draft.deck_dir}>候補を探す</button>
          </span>
        </label>
        {exeCandidates && (
          <div className="chip-list">
            {exeCandidates.length === 0 && <span className="muted">起動ファイルの候補が見つかりませんでした。</span>}
            {exeCandidates.map((c) => (
              <button key={c} className={`chip${c === draft.exe ? ' active' : ''}`} onClick={() => set('exe', c)}>{c}</button>
            ))}
          </div>
        )}
        <TransferSection game={game} draftLocalPath={draft.local_path} onDone={onSaved} onOpenSettings={onOpenSettings} />
        <label className="field">
          <span className="field-label">Deck上の作品フォルダ</span>
          <input value={draft.deck_dir} placeholder="（未転送）" onChange={(e) => set('deck_dir', e.target.value)} />
        </label>
      </fieldset>

      {showDlsite && (
        <DlsiteDialog workId={draft.work_id.trim()} current={draft} hasCover={!!game.images.cover} onApply={applyDlsite} onClose={() => setShowDlsite(false)} />
      )}
    </section>
  )
}

function TransferSection({ game, draftLocalPath, onDone, onOpenSettings }: {
  game: DoujinGame
  draftLocalPath: string
  onDone: (g: DoujinGame) => void
  onOpenSettings: () => void
}) {
  const runJob = useRunJob()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const bases = settings.data?.steam_deck.doujin_base ?? []
  const [base, setBase] = useState('')
  const [overwrite, setOverwrite] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<string | null>(null)
  const chosenBase = base || bases[0] || ''
  const saved = draftLocalPath === game.local_path

  async function transfer() {
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const r = await runJob(() => doujinApi.transfer(game.id, game.deck_dir ? null : chosenBase, overwrite))
      setResult(`${r.transferred}ファイルを送信しました（送信済み ${r.skipped}件${r.errors.length ? `・失敗 ${r.errors.length}件` : ''}）。`)
      onDone(await doujinApi.get(game.id))
    } catch (e) {
      setError(e)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="transfer">
      <div className="transfer-row">
        {game.deck_dir ? (
          <span className="muted">送信先: {game.deck_dir}（変わったファイルだけを送ります）</span>
        ) : bases.length > 0 ? (
          <label className="field-inline">
            Deckの格納先
            <select value={chosenBase} onChange={(e) => setBase(e.target.value)}>
              {bases.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
        ) : (
          <span className="muted">
            Deckの格納先が未設定です。<button className="link" onClick={onOpenSettings}>設定を開く</button>
          </span>
        )}
      </div>
      <div className="transfer-row">
        <label className="check">
          <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
          同じサイズのファイルも送り直す
        </label>
        <button
          className="btn"
          disabled={running || !game.local_path || !saved || (!game.deck_dir && !chosenBase)}
          title={!game.local_path ? 'PC上の作品フォルダを設定してください' : undefined}
          onClick={transfer}
        >
          {running ? '転送中…' : 'Deckへ転送'}
        </button>
        {game.transferred_at && <span className="muted">前回: {new Date(game.transferred_at).toLocaleString('ja-JP')}</span>}
      </div>
      {result && <span className="notice">{result}</span>}
      {error != null && <ErrorBox error={error} />}
    </div>
  )
}
