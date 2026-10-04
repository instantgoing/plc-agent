import { useEffect, useRef, type ReactNode } from 'react'
import { AgentEvent, type AgentRow } from './AgentActivity'
import { WorkbenchIcon } from './WorkbenchNavigation'

export function TopBar({ workspace, runtime, codex, agentOpen, onRefresh, onOpenAgent }: {
  workspace: string
  runtime?: string
  codex?: string
  agentOpen: boolean
  onRefresh: () => void
  onOpenAgent: () => void
}) {
  return <header className="topbar">
    <div className="brand-mark" aria-hidden="true"><WorkbenchIcon name="logic" size={19} /></div>
    <div className="brand"><strong>PLC<span> Agent</span></strong></div>
    <div className="workspace-name" title={workspace}>{workspace}</div>
    <div className="top-spacer" />
    <span className="sim-badge">SIMULATION</span>
    <span className="header-status"><i className={runtime === 'running' ? 'green' : 'gray'} />RUNTIME {runtime?.toUpperCase() || 'UNKNOWN'}</span>
    <span className="header-status"><i className={codex === 'ready' ? 'green' : 'red'} />AGENT {codex?.toUpperCase() || 'CHECKING'}</span>
    <button className="icon-button" type="button" aria-label="Refresh status" title="Refresh status" onClick={onRefresh}><WorkbenchIcon name="refresh" size={16} /></button>
    {!agentOpen && <button className="agent-reopen" type="button" aria-controls="codex-agent-panel" aria-expanded={false} onClick={onOpenAgent}>Open agent</button>}
  </header>
}

export function WorkspaceEmpty({ onFiles, onProject, onAgent }: { onFiles: () => void; onProject: () => void; onAgent: () => void }) {
  return <div className="editor-welcome">
    <div className="welcome-logo" aria-hidden="true"><WorkbenchIcon name="logic" size={34} /></div>
    <h1>PLC workspace</h1>
    <p>Open a file to inspect or edit Structured Text.</p>
    <div className="welcome-actions">
      <button type="button" onClick={onFiles}><WorkbenchIcon name="files" size={16} /> Browse project files</button>
      <button type="button" onClick={onProject}><WorkbenchIcon name="logic" size={16} /> Explore PLC symbols</button>
      <button type="button" onClick={onAgent}><WorkbenchIcon name="agent" size={16} /> Open PLC Agent</button>
    </div>
  </div>
}

type Session = { thread_id: string; title: string }

export function AgentPanel({ threadId, sessions, rows, active, input, setInput, onNew, onResume, onClose, onSend, onInterrupt, onSuggestion, renderText }: {
  threadId: string | null
  sessions: Session[]
  rows: AgentRow[]
  active: boolean
  input: string
  setInput: (value: string) => void
  onNew: () => void
  onResume: (id: string) => void
  onClose: () => void
  onSend: () => void
  onInterrupt: () => void
  onSuggestion: (prompt: string) => void
  renderText: (text: string) => ReactNode
}) {
  const streamRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const atBottom = useRef(true)

  useEffect(() => {
    if (atBottom.current && streamRef.current) streamRef.current.scrollTop = streamRef.current.scrollHeight
  }, [rows, active])
  useEffect(() => {
    const element = inputRef.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(Math.max(element.scrollHeight, 60), 500)}px`
  }, [input])

  return <aside className={`agent-panel${rows.length || active ? '' : ' is-empty'}`} id="codex-agent-panel" aria-label="PLC Agent">
    <div className="agent-head">
      <div className="agent-title"><span className="agent-glyph"><WorkbenchIcon name="agent" size={18} /></span><strong>PLC Agent</strong><small>{threadId ? `Thread ${threadId.slice(0, 8)}` : 'New thread'}</small></div>
      <div className="agent-head-actions">
        <button type="button" aria-label="New agent session" title="New session" onClick={onNew}><WorkbenchIcon name="plus" size={17} /></button>
        <select aria-label="Resume previous session" title="Resume previous session" value={threadId || ''} onChange={event => { if (event.target.value) onResume(event.target.value) }}><option value="">History</option>{sessions.map(item => <option key={item.thread_id} value={item.thread_id}>{item.title.slice(0, 35)}</option>)}</select>
        <button className="agent-close" type="button" aria-label="Close agent" title="Close agent" onClick={onClose}><WorkbenchIcon name="close" size={15} /></button>
      </div>
    </div>
    <div className="agent-stream" ref={streamRef} role="log" aria-label="Agent activity" aria-live="polite" aria-relevant="additions text" onScroll={event => {
      const element = event.currentTarget
      atBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 12
    }}>
      {rows.length ? rows.map((row, index) => <AgentEvent key={`${row.id || index}-${index}`} row={row} renderText={renderText} />) : !active && <div className="agent-empty"><div className="agent-context-meter">Context usage unavailable<span /></div><div className="agent-model-label">PLC Agent</div><div className="agent-quick-actions"><button type="button" onClick={() => onSuggestion('Explain the current PLC file and its control logic.')}>Explain</button><button type="button" onClick={() => onSuggestion('Review the current PLC file for safety interlocks.')}>Review</button><button type="button" onClick={() => onSuggestion('Suggest tests for the current PLC program.')}>Add Tests</button><button type="button" onClick={() => onSuggestion('Find where Motor is defined in this PLC project.')}>Find Motor</button><button type="button" onClick={() => onSuggestion('Check the current PLC program for compiler diagnostics.')}>Check Logic</button><button type="button" onClick={() => onSuggestion('Document the current PLC program and its I/O mapping.')}>Document</button><button type="button" onClick={() => onSuggestion('Review the current PLC program for simpler control logic without changing behavior.')}>Optimize</button></div><div className="agent-suggestions-label">Suggestions</div><button className="agent-suggestion-row" type="button" onClick={() => onSuggestion('Summarize the PLC project and its program structure.')}>Summarize this PLC project</button><button className="agent-suggestion-row" type="button" onClick={() => onSuggestion('Find where Motor is defined in this PLC project.')}>Find where Motor is defined</button></div>}
      {active && <div className="agent-working" role="status"><span className="pulse-dot" /> Agent is working… <button type="button" onClick={onInterrupt}>Interrupt</button></div>}
    </div>
    <div className="agent-compose">
      <div className="composer-shell">
        <div className="composer-entry"><textarea ref={inputRef} value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => {
          if (event.key === 'Escape' && active) { event.preventDefault(); onInterrupt() }
          else if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!active && input.trim()) onSend() }
        }} placeholder="Ask about this PLC project…" aria-label="Message the PLC Agent" />{active
          ? <button className="composer-stop" type="button" aria-label="Interrupt agent" title="Interrupt agent" onClick={onInterrupt}><WorkbenchIcon name="stop" size={17} /></button>
          : <button className="composer-send" type="button" aria-label="Send message" title="Send message" onClick={onSend} disabled={!input.trim()}><WorkbenchIcon name="send" size={18} /></button>}
        </div>
        <div className="composer-toolbar"><span>Enter to send · Shift+Enter for a new line</span></div>
      </div>
    </div>
  </aside>
}
