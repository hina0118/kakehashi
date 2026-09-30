import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, steamApi, type Settings, type SteamUser } from '../../api'
import { ErrorBox } from '../../components/ErrorBox'

export function SettingsPage() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  if (settings.error) return <ErrorBox error={settings.error} />
  if (!settings.data) return <div className="empty-page">読み込み中…</div>
  return <SettingsForm initial={settings.data} />
}

const lines = (s: string) => s.split(/[\n,]/).map((v) => v.trim()).filter(Boolean)

function SettingsForm({ initial }: { initial: Settings }) {
  const qc = useQueryClient()
  const [host, setHost] = useState(initial.sync.host)
  const [port, setPort] = useState(String(initial.sync.port))
  const [username, setUsername] = useState(initial.sync.username)
  const [password, setPassword] = useState('')
  const [systems, setSystems] = useState(initial.systems.join('\n'))
  const [backupMax, setBackupMax] = useState(String(initial.backup_max))
  const [localMedia, setLocalMedia] = useState(initial.windows.media_base)
  const [romBase, setRomBase] = useState(initial.steam_deck.rom_base)
  const [gamelistBase, setGamelistBase] = useState(initial.steam_deck.gamelist_base)
  const [deckMedia, setDeckMedia] = useState(initial.steam_deck.media_base)
  const [doujinBase, setDoujinBase] = useState(initial.steam_deck.doujin_base.join('\n'))
  const [steamRoot, setSteamRoot] = useState(initial.steam_deck.steam_root)
  const [steamUser, setSteamUser] = useState(initial.steam_deck.steam_user)
  const [compatTool, setCompatTool] = useState(initial.steam_deck.default_compat_tool)
  const [launchOptions, setLaunchOptions] = useState(initial.steam_deck.default_launch_options)
  const [steamUsers, setSteamUsers] = useState<SteamUser[] | null>(null)
  // 未保存の変更があるうちは、保存済みの設定での接続確認と食い違うため確認させない
  const [dirty, setDirty] = useState(false)

  const save = useMutation({
    mutationFn: () =>
      api.saveSettings({
        systems: lines(systems),
        backup_max: Number(backupMax) || 0,
        windows: { ...initial.windows, media_base: localMedia },
        steam_deck: {
          ...initial.steam_deck,
          rom_base: romBase,
          gamelist_base: gamelistBase,
          media_base: deckMedia,
          doujin_base: lines(doujinBase),
          steam_root: steamRoot,
          steam_user: steamUser,
          default_compat_tool: compatTool,
          default_launch_options: launchOptions,
        },
        sync: { host, port: Number(port) || 22, username, ...(password ? { password } : {}) },
      }),
    onSuccess: (data) => {
      qc.setQueryData(['settings'], data)
      qc.invalidateQueries({ queryKey: ['systems'] })
      setPassword('')
      setDirty(false)
    },
  })
  const test = useMutation({ mutationFn: api.testConnection })
  const loadUsers = useMutation({
    mutationFn: steamApi.status,
    onSuccess: (s) => setSteamUsers(s.users),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    test.reset()
    save.mutate()
  }

  return (
    <form className="settings" onSubmit={submit} onChange={() => setDirty(true)}>
      <fieldset>
        <legend>Steam Deck への接続（SSH）</legend>
        <div className="form-row">
          <label className="field grow">
            <span className="field-label">ホスト（IPアドレス）</span>
            <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="192.168.1.xx" />
          </label>
          <label className="field">
            <span className="field-label">ポート</span>
            <input value={port} onChange={(e) => setPort(e.target.value)} inputMode="numeric" size={6} />
          </label>
        </div>
        <div className="form-row">
          <label className="field grow">
            <span className="field-label">ユーザー名</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label className="field grow">
            <span className="field-label">パスワード</span>
            <input
              type="password"
              value={password}
              autoComplete="off"
              onChange={(e) => setPassword(e.target.value)}
              placeholder={initial.sync.password_set ? '保存済み（変更する場合のみ入力）' : ''}
            />
          </label>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="btn"
            disabled={test.isPending || dirty}
            title={dirty ? '保存してから接続を確認します' : undefined}
            onClick={() => test.mutate()}
          >
            {test.isPending ? '確認中…' : '接続を確認'}
          </button>
          {test.data && <span className="notice">{test.data.message}</span>}
        </div>
        {test.error && <ErrorBox error={test.error} />}
      </fieldset>

      <fieldset>
        <legend>ES-DE</legend>
        <label className="field">
          <span className="field-label">機種（1行に1つ）</span>
          <textarea rows={5} value={systems} onChange={(e) => setSystems(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Deck: gamelist フォルダ</span>
          <input value={gamelistBase} onChange={(e) => setGamelistBase(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Deck: ROM フォルダ</span>
          <input value={romBase} onChange={(e) => setRomBase(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Deck: メディアフォルダ（downloaded_media）</span>
          <input value={deckMedia} onChange={(e) => setDeckMedia(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">PC: メディアフォルダ（downloaded_media）</span>
          <input value={localMedia} onChange={(e) => setLocalMedia(e.target.value)} />
        </label>
        <label className="field narrow">
          <span className="field-label">gamelist.xml のバックアップ世代数</span>
          <input value={backupMax} onChange={(e) => setBackupMax(e.target.value)} inputMode="numeric" />
        </label>
      </fieldset>

      <fieldset>
        <legend>同人ゲーム</legend>
        <label className="field">
          <span className="field-label">Deck: 格納先フォルダ（1行に1つ）</span>
          <textarea rows={3} value={doujinBase} onChange={(e) => setDoujinBase(e.target.value)} />
        </label>
      </fieldset>

      <fieldset>
        <legend>Steam（同人ゲームの登録先）</legend>
        <label className="field">
          <span className="field-label">Deck: Steam のフォルダ</span>
          <input value={steamRoot} onChange={(e) => setSteamRoot(e.target.value)} />
        </label>
        <div className="field">
          <span className="field-label">登録先のSteamアカウント</span>
          <span className="input-with-btn">
            {steamUsers ? (
              <select value={steamUser} onChange={(e) => setSteamUser(e.target.value)}>
                <option value="">自動（アカウントが1つだけのとき）</option>
                {steamUsers.map((u) => (
                  <option key={u.account_id} value={u.account_id}>
                    {u.persona_name || u.account_name || u.account_id}（{u.account_id}）
                  </option>
                ))}
              </select>
            ) : (
              <input value={steamUser} placeholder="自動（アカウントが1つだけのとき）" onChange={(e) => setSteamUser(e.target.value)} />
            )}
            <button
              type="button"
              className="btn small"
              disabled={loadUsers.isPending || dirty}
              title={dirty ? '接続設定を保存してから読み込みます' : undefined}
              onClick={() => loadUsers.mutate()}
            >
              {loadUsers.isPending ? '読み込み中…' : 'Deckから読み込む'}
            </button>
          </span>
        </div>
        {loadUsers.error && <ErrorBox error={loadUsers.error} />}
        <div className="form-row">
          <label className="field grow">
            <span className="field-label">既定の互換ツール</span>
            <input value={compatTool} list="compat-tools" onChange={(e) => setCompatTool(e.target.value)} />
            <datalist id="compat-tools">
              {['proton_experimental', 'proton_hotfix', 'proton_9', 'proton_8'].map((t) => <option key={t} value={t} />)}
            </datalist>
          </label>
          <label className="field grow">
            <span className="field-label">既定の起動オプション</span>
            <input value={launchOptions} onChange={(e) => setLaunchOptions(e.target.value)} />
          </label>
        </div>
        <p className="hint">
          起動オプションの既定値 <code>LANG=ja_JP.UTF-8 %command%</code> は、Shift-JISで作られたゲームの文字化けを防ぎます。
        </p>
      </fieldset>

      <div className="form-actions sticky">
        <button type="submit" className="btn primary" disabled={save.isPending}>
          {save.isPending ? '保存中…' : '保存'}
        </button>
        {save.isSuccess && !dirty && <span className="notice">保存しました。</span>}
        {save.error && <ErrorBox error={save.error} />}
      </div>
    </form>
  )
}
