import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { api, post } from './api'
import { debugStore, readWatch, saveWatch, valueState, type DebugState, type DebugVariable, type Sample } from './debugStore'
import { LiveLadder, ladderVariables, type LadderIR } from './LiveLadder'
import { TracePlot } from './TracePlot'
import { ForceMenu } from './ForceMenu'
import './debugger.css'
import './debugger-layout.css'

export function Debugger({ panel, workspace, file, dirty, connected, jump, selectPanel }: { panel: string; workspace: string; file: string; dirty: boolean; connected: boolean; jump: (file: string, line: number) => void; selectPanel: (panel: 'watch' | 'trace' | 'forced') => void }) {
  const state = useSyncExternalStore(debugStore.subscribe, debugStore.getSnapshot)
  const [variables, setVariables] = useState<DebugVariable[]>([])
  const [watch, setWatch] = useState<string[]>([])
  const [pinned, setPinned] = useState<string[]>([])
  const [ready, setReady] = useState(false)
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<DebugVariable[]>([])
  const [signals, setSignals] = useState<string[]>([])
  const [samples, setSamples] = useState<Sample[]>([])
  const [traceInterval, setTraceInterval] = useState(100)
  const [zoomKey, setZoomKey] = useState(0)
  const [ir, setIr] = useState<LadderIR | null>(null)
  const [error, setError] = useState('')
  const [operation, setOperation] = useState('')
  const [now, setNow] = useState(Date.now())
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)
  useEffect(() => { const close = () => setMenu(null); const escape = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }; document.addEventListener('click', close); document.addEventListener('keydown', escape); return () => { document.removeEventListener('click', close); document.removeEventListener('keydown', escape) } }, [])
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(timer) }, [])
  useEffect(() => {
    if (!workspace) return
    setReady(false); setWatch(readWatch(workspace)); setReady(true)
  }, [workspace])
  useEffect(() => { if (ready && workspace) saveWatch(workspace, watch) }, [workspace, watch, ready])
  const refreshCatalog = useCallback(async () => {
    const result = await api<{ variables: DebugVariable[] }>('/api/debug/variables')
    setVariables(result.variables)
  }, [])
  useEffect(() => { void refreshCatalog().catch(e => setError(String(e))) }, [state.program_id, state.consistency, file, refreshCatalog])
  useEffect(() => {
    let canceled = false
    const timeout = setTimeout(() => { if (!query.trim()) { setMatches([]); return }; void api<{ variables: DebugVariable[] }>(`/api/debug/variables?query=${encodeURIComponent(query)}`).then(r => { if (!canceled) setMatches(r.variables) }).catch(e => setError(String(e))) }, 180)
    return () => { canceled = true; clearTimeout(timeout) }
  }, [query])
  useEffect(() => {
    let canceled = false
    if (!file.endsWith('.st')) { setIr(null); return }
    void api<LadderIR>(`/api/debug/ladder?file=${encodeURIComponent(file)}`).then(r => { if (!canceled) setIr(r) }).catch(e => setError(String(e)))
    return () => { canceled = true }
  }, [file, state.program_id, state.consistency, dirty])
  const byId = useMemo(() => new Map(variables.map(v => [v.id, v])), [variables])
  const monitored = [...new Set([...watch, ...(panel === 'variables' ? variables.map(v => v.id) : []), ...(panel === 'ladder' ? ladderVariables(ir) : [])])].slice(0, 100)
  useEffect(() => {
    if (!ready) return
    void post('/api/debug/subscribe', { consumer: 'ide', variables: monitored }).catch(e => setError(String(e)))
  }, [ready, monitored.join('|'), connected])
  useEffect(() => {
    let canceled = false
    setSamples([])
    void api<{ samples: Sample[] }>('/api/debug/trace').then(r => { if (!canceled) setSamples(current => [...new Map([...r.samples, ...current].map(s => [s.t_ms, s])).values()].sort((a, b) => a.t_ms - b.t_ms).slice(-10000)) }).catch(e => setError(String(e)))
    return () => { canceled = true }
  }, [state.trace.session_id, connected])
  useEffect(() => { const sample = state.trace_sample; if (sample) setSamples(current => current.at(-1)?.t_ms === sample.t_ms ? current : [...current, sample].slice(-10000)) }, [state.trace_sample])
  const fresh = connected && now - state.timestamp <= state.stale_after_ms
  const running = fresh && state.runtime === 'running'
  const matching = state.consistency === 'matched' && !dirty
  // An IR from a different file must never be colored with the loaded program.
  const loadedFileMatches = Boolean(ir && state.program?.source_file.replace(/\\/g, '/').endsWith('/' + ir.file))
  const live = running && matching && loadedFileMatches
  const operate = async (label: string, url: string, body: object) => {
    setOperation(label); setError('')
    try { const result = await post<{ success?: boolean; error?: { message: string }; tool_error?: string; failures?: { reason: string }[] }>(url, body); if (result.success === false) throw new Error(result.error?.message || result.tool_error || result.failures?.map(f => f.reason).join('; ') || 'Runtime rejected operation'); debugStore.update(await api<DebugState>('/api/debug/state')) }
    catch (e) { setError(String(e)) } finally { setOperation('') }
  }
  const forced = Object.keys(state.forced)
  const traceAction = (action: string) => void operate(`Trace ${action}`, '/api/debug/trace', { action, variables: signals.length ? signals : watch, sample_interval_ms: traceInterval })
  const addVariable = (id: string) => { if (panel === 'trace') setSignals(current => [...new Set([...(current.length ? current : watch), id])].slice(0, 100)); else setWatch(current => [...new Set([...current, id])].slice(0, 100)); setQuery('') }
  const renderRows = (ids: string[]) => <table><thead><tr><th>Variable / scope</th><th>Address</th><th>Type</th><th>Value / State</th><th>Actions</th></tr></thead><tbody>{ids.map(id => {
    const variable = byId.get(id), value = state.latest[id]
    const status = variable ? valueState(value, running ? 'running' : 'offline', now, state.stale_after_ms) : 'unresolved'
    const valid = status === 'normal' || status === 'forced'
    const disabled = !running || !matching || !variable?.forceable || Boolean(operation)
    return <tr key={id} data-variable-id={id} onContextMenu={event => { event.preventDefault(); setMenu({ id, x: Math.min(event.clientX, window.innerWidth - 185), y: Math.min(event.clientY, window.innerHeight - 150) }) }} className={status === 'forced' ? 'forced-row' : ''}><td><button className="symbol-source" onClick={() => variable && jump(variable.file, variable.line)}>{variable ? `${variable.owner}.${variable.name}` : id}</button><small>{id}</small></td><td>{variable?.address || '—'}</td><td>{variable?.type || '—'}</td><td className={`value-cell ${status}`}><strong>{valid ? typeof value.value === 'boolean' ? String(value.value).toUpperCase() : String(value.value) + (variable?.type === 'TIME' ? ' ms' : '') : '—'}</strong> <span className="debug-state">{status.toUpperCase()}</span></td><td>{variable?.type === 'BOOL' ? <><button disabled={disabled} onClick={() => void operate('Force TRUE', '/api/plc/force', { variables: { [id]: true } })}>TRUE</button><button disabled={disabled} onClick={() => void operate('Force FALSE', '/api/plc/force', { variables: { [id]: false } })}>FALSE</button></> : <button disabled={disabled} onClick={() => { const v = window.prompt(`Force ${id} (${variable?.type})`); if (v !== null) void operate('Set forced value', '/api/plc/force', { variables: { [id]: v } }) }}>Set Value</button>}<button disabled={!running || Boolean(operation) || !(id in state.forced)} onClick={() => void operate('Unforce', '/api/plc/unforce', { variables: [id] })}>Unforce</button>{panel === 'watch' && <><button aria-label={`Pin ${id}`} onClick={() => setPinned(current => current.includes(id) ? current.filter(i => i !== id) : [...current, id])}>{pinned.includes(id) ? 'Pinned' : 'Pin'}</button><button aria-label={`Remove ${id}`} onClick={() => setWatch(current => current.filter(i => i !== id))}>Remove</button></>}</td></tr>
  })}</tbody></table>
  const exportTrace = (csv: boolean) => {
    const ids = state.trace.signals.map(s => s.variable_id)
    const content = csv ? ['t_ms,' + ids.join(','), ...samples.map(s => [s.t_ms, ...ids.map(id => s.values[id] ?? '')].join(','))].join('\n') : JSON.stringify({ ...state.trace, samples }, null, 2)
    const url = URL.createObjectURL(new Blob([content], { type: csv ? 'text/csv' : 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = `trace-${state.trace.session_id || 'empty'}.${csv ? 'csv' : 'json'}`; a.click(); URL.revokeObjectURL(url)
  }
  return <div className="debug-workspace">
    <div className="debug-toolbar"><strong>{running ? 'RUNNING' : fresh ? state.runtime.toUpperCase() : 'STALE / OFFLINE'}</strong><button onClick={() => selectPanel('watch')}>Watch ({watch.length})</button><button onClick={() => selectPanel('trace')}>Trace</button><button className={forced.length ? 'forced-badge' : ''} onClick={() => selectPanel('forced')}>Forced ({forced.length})</button><label>Refresh <select aria-label="Debug refresh interval" value={state.interval_ms} onChange={e => void operate('Refresh rate', '/api/debug/config', { interval_ms: Number(e.target.value) })}><option value={100}>Fast · 100ms</option><option value={250}>Normal · 250ms</option><option value={500}>Slow · 500ms</option><option value={1000}>Slow · 1000ms</option></select></label><small>Read {state.poll_latency_ms}ms</small>{operation && <span>{operation}</span>}</div>
    {(!matching || !loadedFileMatches && panel === 'ladder') && <div className="debug-warning">{dirty ? 'SOURCE MODIFIED · unsaved changes' : state.consistency === 'mismatch' ? 'SOURCE CHANGED · Runtime is running an older build.' : state.consistency === 'unknown' ? 'PROGRAM IDENTITY UNKNOWN · Build & Run to establish a matching build.' : 'Visualization may not match runtime.'} Live highlighting disabled.</div>}
    {(panel === 'watch' || panel === 'trace') && <div className="watch-search"><input aria-label="Search watch symbols" value={query} placeholder="Add variable: search symbol or address…" onChange={e => setQuery(e.target.value)} /><button onClick={() => panel === 'watch' ? setWatch([]) : setSignals([])}>Clear {panel === 'watch' ? 'Watch' : 'Signals'}</button>{matches.length > 0 && <div className="watch-matches">{matches.map((v, i) => <button key={`${v.id}-${i}`} onClick={() => addVariable(v.id)}>{v.owner}.{v.name} <small>{v.type} · {v.address || v.scope} · {v.available ? v.id : 'UNAVAILABLE'}</small></button>)}</div>}</div>}
    {panel === 'watch' && <div className="variables-panel watch-panel">{renderRows([...watch].sort((a, b) => Number(pinned.includes(b)) - Number(pinned.includes(a))))}{!watch.length && <div className="empty-panel">Search and select symbols to add to Watch. Values come from the shared DebugSession.</div>}</div>}
    {panel === 'variables' && <div className="variables-panel">{renderRows(variables.map(v => v.id))}</div>}
    {panel === 'forced' && <div className="variables-panel"><div className="panel-controls"><strong>FORCED ({forced.length}) · TOOL-OBSERVED FORCES</strong><button disabled={!running || !forced.length || Boolean(operation)} onClick={() => void operate('Unforce All', '/api/plc/unforce', { variables: forced })}>Unforce All</button><small>Only forces confirmed through PLC tools are tracked.</small></div>{renderRows(forced)}</div>}
    {panel === 'trace' && <div className="trace-panel"><div className="panel-controls"><button disabled={!running || !matching || state.trace.state === 'recording' || !(signals.length || watch.length)} onClick={() => traceAction('start')}>Start Trace</button><button disabled={state.trace.state !== 'recording'} onClick={() => traceAction('pause')}>Pause</button><button disabled={state.trace.state !== 'recording'} onClick={() => traceAction('stop')}>Stop Trace</button><button onClick={() => { traceAction('clear'); setSamples([]) }}>Clear Trace</button><select aria-label="Trace sample interval" value={traceInterval} onChange={e => setTraceInterval(Number(e.target.value))}>{[100, 250, 500, 1000].map(ms => <option key={ms} value={ms}>{ms}ms</option>)}</select><button onClick={() => setZoomKey(k => k + 1)}>Reset Zoom</button><button onClick={() => exportTrace(false)}>JSON</button><button onClick={() => exportTrace(true)}>CSV</button><strong>{state.trace.state.toUpperCase()} · {samples.length}/10000</strong></div><div className="trace-signals">{(signals.length ? signals : watch).map(id => <button key={id} onClick={() => setSignals(current => current.filter(i => i !== id))}>{id} ×</button>)}</div><TracePlot samples={samples} meta={state.trace} zoomKey={zoomKey} /></div>}
    {panel === 'ladder' && <LiveLadder ir={ir} state={state} live={live} jump={s => jump(s.file, s.line)} />}
    {menu && <ForceMenu {...menu} variable={byId.get(menu.id)} enabled={running && matching && Boolean(byId.get(menu.id)?.forceable) && !operation} canRelease={running && menu.id in state.forced && !operation} force={value => void operate('Force value', '/api/plc/force', { variables: { [menu.id]: value } })} release={() => void operate('Unforce', '/api/plc/unforce', { variables: [menu.id] })} />}
    {error && <div className="error-line">Debug: {error}</div>}
  </div>
}
