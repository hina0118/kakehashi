import type { ReactNode } from 'react'

export function ErrorBox({ error, children }: { error: unknown; children?: ReactNode }) {
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div className="error-box" role="alert">
      <span>{message}</span>
      {children}
    </div>
  )
}
