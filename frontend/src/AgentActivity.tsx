import type { ReactNode } from 'react'
import { WorkbenchIcon } from './WorkbenchNavigation'

export type AgentRow = { kind: 'message' | 'tool' | 'error' | 'status'; text: string; id?: string; state?: string }

export function AgentEvent({ row, renderText }: { row: AgentRow; renderText: (text: string) => ReactNode }) {
  if (row.kind === 'tool') {
    const [name, ...summary] = row.text.split(' · ')
    const state = row.state === 'working' ? 'Running' : row.state === 'success' ? 'Completed' : row.state || 'Completed'
    const failed = /fail|error|reject/i.test(state)
    return <details className={`tool-card${row.state === 'working' ? ' is-running' : ''}${failed ? ' is-error' : ''}`}>
      <summary>
        <span className="tool-chevron"><WorkbenchIcon name="chevron" size={13} /></span>
        <span className="tool-name" title={name}>{name}</span>
        <span className="tool-state">{row.state === 'working' && <span className="activity-spinner" aria-hidden="true" />}{state}</span>
      </summary>
      <div className="tool-result">{summary.length ? renderText(summary.join(' · ')) : <span>{row.state === 'working' ? 'Waiting for tool result…' : 'No result details available.'}</span>}</div>
    </details>
  }
  if (row.kind === 'status' && row.text.startsWith('You: ')) {
    return <div className="agent-user-message"><span className="agent-event-label">You</span><div>{renderText(row.text.slice(5))}</div></div>
  }
  return <div className={`agent-row ${row.kind}`}>
    <span className="row-icon" aria-hidden="true">{row.kind === 'error' ? '!' : row.kind === 'status' ? '›' : '●'}</span>
    <div>{renderText(row.text)}</div>
  </div>
}
