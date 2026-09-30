import { useState } from 'react'
import { JobTray } from './components/JobTray'
import { DoujinPage } from './features/doujin/DoujinPage'
import { EsdePage } from './features/esde/EsdePage'
import { SettingsPage } from './features/settings/SettingsPage'

type Page = 'esde' | 'doujin' | 'settings'

const NAV: { id: Page; label: string; disabled?: boolean }[] = [
  { id: 'esde', label: 'ES-DE' },
  { id: 'doujin', label: '同人ゲーム' },
  { id: 'settings', label: '設定' },
]

export default function App() {
  const [page, setPageState] = useState<Page>('esde')
  const [visited, setVisited] = useState<Set<Page>>(new Set(['esde']))
  const setPage = (p: Page) => {
    setPageState(p)
    setVisited((v) => (v.has(p) ? v : new Set(v).add(p)))
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="brand">kakehashi</h1>
        <nav className="nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`nav-item${page === n.id ? ' active' : ''}`}
              disabled={n.disabled}
              title={n.disabled ? '準備中' : undefined}
              onClick={() => setPage(n.id)}
            >
              {n.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="app-main">
        {/* 未プッシュの編集を失わないよう、ES-DE画面は切り替えても破棄しない */}
        <div className="page" hidden={page !== 'esde'}>
          <EsdePage onOpenSettings={() => setPage('settings')} />
        </div>
        {/* 絞り込み状態を保つため、一度開いたら破棄しない */}
        {visited.has('doujin') && (
          <div className="page" hidden={page !== 'doujin'}>
            <DoujinPage onOpenSettings={() => setPage('settings')} />
          </div>
        )}
        {page === 'settings' && (
          <div className="page">
            <SettingsPage />
          </div>
        )}
      </main>
      <JobTray />
    </div>
  )
}
