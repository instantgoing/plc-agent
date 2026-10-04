import type { Dispatch, SetStateAction } from 'react'

type IconName = 'files' | 'logic' | 'agent' | 'problems' | 'runtime' | 'changes' | 'refresh' | 'plus' | 'close' | 'send' | 'stop' | 'chevron'

export function WorkbenchIcon({ name, size = 18 }: { name: IconName; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const }
  const drawing = {
    files: <><path d="M4 5.5h6l2 2h8v11H4z" /><path d="M4 9h16" /></>,
    logic: <><rect x="3.5" y="5" width="17" height="14" rx="2" /><path d="M7 9h3m4 0h3M7 15h3m4 0h3M12 5v14" /></>,
    agent: <><path d="M12 3l1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z" /><path d="M19 16v5m-2.5-2.5h5M4 17v3m-1.5-1.5h3" /></>,
    problems: <><path d="M12 3 2.5 20h19z" /><path d="M12 9v5m0 3h.01" /></>,
    runtime: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 10l3 2-3 2m6 0h4" /></>,
    changes: <><path d="M7 4v12a4 4 0 0 0 4 4h6M17 4v8a4 4 0 0 1-4 4h-2" /><circle cx="7" cy="4" r="2" /><circle cx="17" cy="4" r="2" /><circle cx="17" cy="20" r="2" /></>,
    refresh: <><path d="M20 11a8 8 0 1 0-2 6" /><path d="M20 4v7h-7" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    close: <path d="M5 5l14 14M19 5 5 19" />,
    send: <><path d="M12 19V5m-6 6 6-6 6 6" /></>,
    stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
    chevron: <path d="m9 6 6 6-6 6" />,
  }[name]
  return <svg {...common}>{drawing}</svg>
}

type Panel = 'problems' | 'runtime' | 'variables' | 'watch' | 'forced' | 'trace' | 'ladder' | 'changes'

export function ActivityRail({ explorer, setExplorer, bottom, onOpenPanel, agentOpen, setAgentOpen }: {
  explorer: 'files' | 'plc'
  setExplorer: Dispatch<SetStateAction<'files' | 'plc'>>
  bottom: Panel
  onOpenPanel: (panel: Panel) => void
  agentOpen: boolean
  setAgentOpen: Dispatch<SetStateAction<boolean>>
}) {
  return <nav className="activity-rail" aria-label="PLC navigation">
    <div className="activity-rail-main">
      <button type="button" className={explorer === 'files' ? 'is-active' : ''} title="Project files" aria-label="Project files" aria-current={explorer === 'files' ? 'page' : undefined} onClick={() => setExplorer('files')}><WorkbenchIcon name="files" /></button>
      <button type="button" className={explorer === 'plc' ? 'is-active' : ''} title="PLC project context" aria-label="PLC project context" aria-current={explorer === 'plc' ? 'page' : undefined} onClick={() => setExplorer('plc')}><WorkbenchIcon name="logic" /></button>
      <div className="activity-rail-divider" />
      <button type="button" className={bottom === 'problems' ? 'is-open' : ''} title="PLC diagnostics" aria-label="PLC diagnostics" aria-current={bottom === 'problems' ? 'page' : undefined} onClick={() => onOpenPanel('problems')}><WorkbenchIcon name="problems" /></button>
      <button type="button" className={bottom === 'runtime' ? 'is-open' : ''} title="Compile and runtime" aria-label="Compile and runtime" aria-current={bottom === 'runtime' ? 'page' : undefined} onClick={() => onOpenPanel('runtime')}><WorkbenchIcon name="runtime" /></button>
      <button type="button" className={bottom === 'changes' ? 'is-open' : ''} title="Agent code changes" aria-label="Agent code changes" aria-current={bottom === 'changes' ? 'page' : undefined} onClick={() => onOpenPanel('changes')}><WorkbenchIcon name="changes" /></button>
    </div>
    <div className="activity-rail-bottom">
      <button type="button" className={agentOpen ? 'is-open' : ''} title={agentOpen ? 'Close PLC Agent' : 'Open PLC Agent'} aria-label={agentOpen ? 'Close PLC Agent' : 'Open PLC Agent'} aria-expanded={agentOpen} aria-controls="codex-agent-panel" onClick={() => setAgentOpen(open => !open)}><WorkbenchIcon name="agent" /></button>
    </div>
  </nav>
}
