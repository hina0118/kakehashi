import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type JobView } from '../api'

/** バックグラウンドジョブの進捗を右下に表示する。実行中のジョブがある間だけ1秒ごとに更新する。 */
export function JobTray() {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<string | null>(null)
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: api.jobs,
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === 'running') ? 1000 : false),
  })

  const visible = (jobs.data ?? []).filter((j) => !dismissed.has(j.id)).slice(0, 5)
  const finishedOk = visible.filter((j) => j.status === 'done' && j.id !== expanded).map((j) => j.id).join(',')

  // 成功したジョブは少し経ったら自動で閉じる（失敗したものは内容を確認できるよう残す）
  useEffect(() => {
    if (!finishedOk) return
    const timer = setTimeout(() => setDismissed((d) => new Set([...d, ...finishedOk.split(',')])), 6000)
    return () => clearTimeout(timer)
  }, [finishedOk])

  if (visible.length === 0) return null

  return (
    <div className="job-tray" aria-live="polite">
      {visible.map((j) => (
        <JobCard
          key={j.id}
          job={j}
          expanded={expanded === j.id}
          onToggle={() => setExpanded(expanded === j.id ? null : j.id)}
          onDismiss={() => setDismissed((d) => new Set(d).add(j.id))}
        />
      ))}
    </div>
  )
}

function JobCard({ job, expanded, onToggle, onDismiss }: {
  job: JobView
  expanded: boolean
  onToggle: () => void
  onDismiss: () => void
}) {
  const pct = job.total > 0 ? Math.round((job.done / job.total) * 100) : null
  const last = job.messages.at(-1)
  return (
    <div className={`job-card ${job.status}`}>
      <div className="job-card-head">
        <button className="link job-title" onClick={onToggle}>{job.title}</button>
        <span className="job-status">
          {job.status === 'running' ? (pct !== null ? `${job.done}/${job.total}` : '実行中…') : job.status === 'done' ? '完了' : '失敗'}
        </span>
        {job.status !== 'running' && (
          <button className="icon-btn" aria-label="閉じる" onClick={onDismiss}>×</button>
        )}
      </div>
      {job.status === 'running' && (
        <div className="progress"><div style={{ width: `${pct ?? 100}%` }} className={pct === null ? 'indeterminate' : ''} /></div>
      )}
      {job.error && <div className="job-error">{job.error}</div>}
      {!job.error && last && !expanded && <div className="job-last">{last}</div>}
      {expanded && <pre className="job-log">{job.messages.join('\n') || '（ログなし）'}</pre>}
    </div>
  )
}
