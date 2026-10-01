import { useCallback, useEffect, useRef, useState } from 'react'
import Editor, { DiffEditor, type OnMount } from '@monaco-editor/react'
import type * as monaco from 'monaco-editor'
import { api, post, pathLink, type Diagnostic, type FileData, type TreeNode, type WebEvent } from './api'
import { hasDirtyConflict, monacoMarkers } from './diagnostics'
import { registerStructuredText } from './stLanguage'
import { Debugger } from './Debugger'
import { debugStore } from './debugStore'

type Tab = FileData & { savedContent: string; external?: FileData }
type ContextItem = { name?: string; symbol?: string; kind?: string; address?: string; type?: string; file: string; line: number; inputs?: ContextItem[]; outputs?: ContextItem[]; locals?: ContextItem[]; inouts?: ContextItem[] }
type Health = { workspace: string; codex: string; mcp: string; runtime: string; project: string; environment: string; agent_active: boolean }
type Change = { path: string; source: string }
type AgentRow = { kind: 'message' | 'tool' | 'error' | 'status'; text: string; id?: string; state?: string }

const stored = (key: string, fallback: string) => { try { return localStorage.getItem(key) || fallback } catch { return fallback } }

function Tree({ nodes, openFile }: { nodes: TreeNode[]; openFile: (path: string) => void }) {
  return <div className="tree-list">{nodes.map(node => node.kind === 'folder'
    ? <details key={node.path} className="tree-folder"><summary>▸ {node.name}</summary><Tree nodes={node.children || []} openFile={openFile} /></details>
    : <button key={node.path} className="tree-file" onClick={() => openFile(node.path)}><span className="file-icon">{node.name.endsWith('.st') ? 'ST' : '◇'}</span>{node.name}</button>)}</div>
}

function LinkText({ text, jump }: { text: string; jump: (path: string, line: number) => void }) {
  const links = text.split(/((?:[\w.-]+\/)*[\w.-]+\.st:\d+)/gi)
  return <>{links.map((piece, i) => {
    const link = pathLink(piece)
    return link ? <button className="inline-link" key={i} onClick={() => jump(link.path, link.line)}>{piece}</button> : <span key={i}>{piece}</span>
  })}</>
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [workspaceError, setWorkspaceError] = useState('')
  const [connection, setConnection] = useState('connecting')
  const [tree, setTree] = useState<TreeNode[]>([])
  const [explorer, setExplorer] = useState<'files' | 'plc'>('files')
  const [pous, setPous] = useState<ContextItem[]>([])
  const [globals, setGlobals] = useState<ContextItem[]>([])
  const [io, setIo] = useState<{ inputs: ContextItem[]; outputs: ContextItem[]; memory: ContextItem[] }>({ inputs: [], outputs: [], memory: [] })
  const [tabs, setTabs] = useState<Tab[]>([])
  const [active, setActive] = useState('')
  const [storageWorkspace, setStorageWorkspace] = useState('')
  const [restored, setRestored] = useState(false)
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([])
  const [bottom, setBottom] = useState<'problems' | 'runtime' | 'variables' | 'changes' | 'trace' | 'watch' | 'forced' | 'ladder'>('problems')
  const [busy, setBusy] = useState('')
  const [runtimeError, setRuntimeError] = useState('')
  const [verifyPlan, setVerifyPlan] = useState('')
  const [changes, setChanges] = useState<Change[]>([])
  const [diff, setDiff] = useState<{ path: string; before: string; after: string } | null>(null)
  const [agentInput, setAgentInput] = useState('')
  const [agentRows, setAgentRows] = useState<AgentRow[]>([])
  const [agentActive, setAgentActive] = useState(false)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [sessions, setSessions] = useState<{ thread_id: string; title: string }[]>([])
  const [agentError, setAgentError] = useState('')
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<typeof monaco | null>(null)
  const saveRef = useRef<() => void>(() => {})
  const seq = useRef(0)
  const tabsRef = useRef(tabs)
  tabsRef.current = tabs
  const activeTab = tabs.find(tab => tab.path === active)
  const dirty = (tab: Tab) => tab.content !== tab.savedContent

  const refreshHealth = useCallback(async () => {
    try { setHealth(await api<Health>('/api/health')) } catch (error) { setWorkspaceError(`Workspace: ${String(error)}`) }
  }, [])
  const refreshTree = useCallback(async () => {
    try { setTree((await api<{ nodes: TreeNode[] }>('/api/workspace/tree')).nodes) } catch (error) { setWorkspaceError(`Workspace: ${String(error)}`) }
  }, [])
  const refreshContext = useCallback(async () => {
    try {
      const [p, g, i] = await Promise.all([
        api<{ items: ContextItem[] }>('/api/project/context?detail=pous'),
        api<{ items: ContextItem[] }>('/api/project/context?detail=globals'),
        api<{ io: { inputs: ContextItem[]; outputs: ContextItem[]; memory: ContextItem[] } }>('/api/project/context?detail=io')
      ])
      setPous(p.items); setGlobals(g.items); setIo(i.io)
    } catch (error) { setWorkspaceError(`Project Context: ${String(error)}`) }
  }, [])
  const refreshChanges = useCallback(async () => {
    try { setChanges((await api<{ files: Change[] }>('/api/changes')).files) } catch { /* status bar reports connection */ }
  }, [])
  const refreshSessions = useCallback(async () => {
    try {
      const result = await api<{ current_thread_id: string | null; active: boolean; sessions: { thread_id: string; title: string }[] }>('/api/agent/sessions')
      setThreadId(result.current_thread_id); setAgentActive(result.active); setSessions(result.sessions)
    } catch (error) { setAgentError(String(error)) }
  }, [])

  const openFile = useCallback(async (path: string, line?: number) => {
    if (tabsRef.current.some(tab => tab.path === path)) {
      setActive(path)
      if (line) setTimeout(() => { editorRef.current?.revealLineInCenter(line); editorRef.current?.setPosition({ lineNumber: line, column: 1 }); editorRef.current?.focus() }, 80)
      return
    }
    try {
      const file = await api<FileData>(`/api/workspace/file?path=${encodeURIComponent(path)}`)
      setTabs(current => [...current, { ...file, savedContent: file.content }])
      setActive(path)
      setDiff(null)
      if (line) setTimeout(() => { editorRef.current?.revealLineInCenter(line); editorRef.current?.setPosition({ lineNumber: line, column: 1 }); editorRef.current?.focus() }, 120)
    } catch (error) { setWorkspaceError(`Workspace: ${String(error)}`) }
  }, [])

  const externalChange = useCallback(async (path: string) => {
    const tab = tabsRef.current.find(item => item.path === path)
    if (!tab) return
    try {
      const remote = await api<FileData>(`/api/workspace/file?path=${encodeURIComponent(path)}`)
      setTabs(current => current.map(item => item.path !== path ? item :
        hasDirtyConflict(item.content, item.savedContent, remote.version, item.version)
          ? { ...item, external: remote }
          : { ...remote, savedContent: remote.content }))
    } catch (error) { setWorkspaceError(`Workspace: ${String(error)}`) }
  }, [])

  const handleEvent = useCallback((event: WebEvent) => {
    if (event.type === 'debug.values') { debugStore.update(event); return }
    if (event.type === 'debug.error') { debugStore.offline(); return }
    if (event.seq && event.seq <= seq.current) return
    if (event.seq) seq.current = event.seq
    if (event.type === 'connection.ready') { setAgentActive(Boolean(event.active)); setThreadId(event.thread_id as string | null); return }
    if (event.type === 'history.truncated') { setAgentRows(current => [...current, { kind: 'status', text: String(event.message) }]); return }
    if (event.type === 'thread.started') { setThreadId(event.thread_id as string); return }
    if (event.type === 'file.changed') {
      void externalChange(event.path as string); void refreshChanges(); void refreshTree(); void refreshContext()
      return
    }
    if (event.type === 'agent.message.delta') {
      const id = String(event.id)
      setAgentRows(current => {
        const index = current.findIndex(row => row.kind === 'message' && row.id === id)
        if (index < 0) return [...current, { kind: 'message', id, text: String(event.text) }]
        return current.map((row, i) => i === index ? { ...row, text: row.text + String(event.text) } : row)
      })
    }
    if (event.type === 'agent.status') setAgentRows(current => [...current, { kind: 'status', text: String(event.message) }])
    if (event.type === 'tool.started') setAgentRows(current => [...current, { kind: 'tool', id: String(event.id), text: String(event.tool), state: 'working' }])
    if (event.type === 'tool.completed') setAgentRows(current => current.map(row => row.id === String(event.id) && row.kind === 'tool'
      ? { ...row, state: String(event.status), text: `${String(event.tool)} · ${String(event.summary)}` } : row))
    if (event.type === 'agent.error') { setAgentError(String(event.message)); setAgentRows(current => [...current, { kind: 'error', text: String(event.message) }]) }
    if (event.type === 'agent.result') {
      const result = event.result as { final_message?: string; files_modified?: string[]; diagnostics?: Diagnostic[] }
      if (result.diagnostics && Array.isArray(result.diagnostics)) setDiagnostics(result.diagnostics)
      if (result.final_message) setAgentRows(current => current.some(row => row.kind === 'message' && row.text.includes(result.final_message!))
        ? current : [...current, { kind: 'message', text: result.final_message! }])
      result.files_modified?.filter(path => path.endsWith('.st')).forEach(path => { void post<{ diagnostics: Diagnostic[] }>('/api/plc/check', { file: path }).then(response => setDiagnostics(current => [...current.filter(item => item.file !== path), ...(response.diagnostics || [])])) })
      void refreshSessions(); void refreshChanges()
    }
    if (event.type === 'agent.idle') { setAgentActive(false); void refreshHealth() }
  }, [externalChange, refreshChanges, refreshContext, refreshHealth, refreshSessions, refreshTree])

  useEffect(() => {
    void refreshHealth(); void refreshTree(); void refreshContext(); void refreshChanges(); void refreshSessions()
    void (async () => {
      try {
        const status = await api<{ workspace: string }>('/api/workspace/status')
        setStorageWorkspace(status.workspace)
        let paths: string[] = []
        try { paths = JSON.parse(stored(`plc-open-files:${status.workspace}`, '[]')) as string[] } catch { /* invalid local UI state */ }
        for (const path of paths.slice(0, 8)) await openFile(path)
        const selected = stored(`plc-active-file:${status.workspace}`, '')
        if (selected && paths.includes(selected)) setActive(selected)
      } catch (error) {
        setWorkspaceError(`Workspace: ${String(error)}`)
      } finally { setRestored(true) }
    })()
  }, []) // restore only once
  useEffect(() => {
    if (!restored || !storageWorkspace) return
    localStorage.setItem(`plc-open-files:${storageWorkspace}`, JSON.stringify(tabs.map(tab => tab.path)))
    localStorage.setItem(`plc-active-file:${storageWorkspace}`, active)
  }, [tabs, active, restored, storageWorkspace])
  useEffect(() => { const timer = setInterval(() => { void refreshHealth() }, 5000); return () => clearInterval(timer) }, [refreshHealth])
  useEffect(() => {
    let socket: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let closed = false
    const connect = () => {
      setConnection('connecting')
      const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(`${scheme}//${location.host}/ws/events?after=${seq.current}`)
      socket.onopen = () => setConnection('connected')
      socket.onmessage = message => { try { handleEvent(JSON.parse(message.data) as WebEvent) } catch { /* malformed event is ignored */ } }
      socket.onerror = () => setConnection('error')
      socket.onclose = () => { debugStore.offline(); if (!closed) { setConnection('reconnecting'); timer = setTimeout(connect, 2000) } }
    }
    connect()
    return () => { closed = true; if (timer) clearTimeout(timer); socket?.close() }
  }, [handleEvent])

  const save = useCallback(async (path: string): Promise<boolean> => {
    const tab = tabsRef.current.find(item => item.path === path)
    if (!tab) return false
    if (tab.external) { setWorkspaceError(`Workspace conflict: ${path} changed externally. Compare, reload, or keep your version first.`); return false }
    try {
      const result = await api<{ version: string }>('/api/workspace/file', { method: 'PUT', body: JSON.stringify({ path, content: tab.content, expected_version: tab.version }) })
      setTabs(current => current.map(item => item.path === path ? { ...item, version: result.version, savedContent: tab.content } : item))
      setWorkspaceError('')
      return true
    } catch (error) { setWorkspaceError(`Workspace: ${String(error)}`); await externalChange(path); return false }
  }, [externalChange])
  saveRef.current = () => { if (active) void save(active) }

  const onMount: OnMount = (editor, monacoInstance) => {
    editorRef.current = editor; monacoRef.current = monacoInstance
    editor.addCommand(monacoInstance.KeyMod.CtrlCmd | monacoInstance.KeyCode.KeyS, () => saveRef.current())
    monacoInstance.editor.setModelMarkers(editor.getModel()!, 'plc-check', monacoMarkers(diagnostics.filter(item => item.file === active)))
  }
  useEffect(() => {
    const model = editorRef.current?.getModel()
    if (model && monacoRef.current) monacoRef.current.editor.setModelMarkers(model, 'plc-check', monacoMarkers(diagnostics.filter(item => item.file === active)))
  }, [diagnostics, active])

  const check = async () => {
    if (!activeTab?.path.endsWith('.st')) return
    if (dirty(activeTab) && !(await save(activeTab.path))) return
    setBusy('Checking ST…')
    try {
      const result = await post<{ diagnostics: Diagnostic[]; error?: { message: string } }>('/api/plc/check', { file: activeTab.path })
      setDiagnostics(current => [...current.filter(item => item.file !== activeTab.path), ...(result.diagnostics || [])])
      setBottom('problems')
      if (result.error) setWorkspaceError(`Compiler: ${result.error.message}`)
    } catch (error) { setWorkspaceError(`Compiler: ${String(error)}`) } finally { setBusy('') }
  }
  const runRuntime = async (action: 'start' | 'stop' | 'compile' | 'verify' | 'build-run') => {
    if ((action === 'compile' || action === 'build-run') && activeTab && dirty(activeTab) && !(await save(activeTab.path))) return
    setBusy(`${action[0].toUpperCase() + action.slice(1)}ing…`); setRuntimeError('')
    try {
      const file = (action === 'compile' || action === 'build-run') ? active : action === 'verify' ? verifyPlan : ''
      if (action === 'verify' && !file) throw new Error('Select a project JSON verification plan first')
      const response = await post<{ success: boolean; passed?: boolean; diagnostics?: Diagnostic[]; error?: { message: string } }>(`/api/plc/${action === 'build-run' ? 'compile' : action}`, file ? { file } : {})
      if (response.diagnostics) setDiagnostics(response.diagnostics)
      if (!response.success || (action === 'verify' && response.passed !== true)) setRuntimeError(response.error?.message || `${action} failed`)
      if (action === 'build-run' && response.success) { const started = await post<{ success: boolean; error?: { message: string } }>('/api/plc/start'); if (!started.success) setRuntimeError(started.error?.message || 'Start failed') }
      await refreshHealth()
    } catch (error) { setRuntimeError(String(error)) } finally { setBusy('') }
  }
  const sendAgent = async () => {
    const message = agentInput.trim(); if (!message) return
    setAgentError(''); setAgentActive(true); setAgentInput(''); setAgentRows(current => [...current, { kind: 'status', text: `You: ${message}` }])
    try { await post('/api/agent/message', { message }) } catch (error) { setAgentActive(false); setAgentError(String(error)) }
  }
  const askSelection = () => {
    const selection = editorRef.current?.getSelection(); const model = editorRef.current?.getModel()
    if (!selection || !model || !active) return
    const text = model.getValueInRange(selection)
    if (text) setAgentInput(current => `${current}\nCurrent selection: ${active}:${selection.startLineNumber}-${selection.endLineNumber}\n\`\`\`st\n${text}\n\`\`\``.trim())
  }
  const showDiff = async (path: string) => {
    try { const result = await api<{ before: string; after: string }>(`/api/changes/diff?path=${encodeURIComponent(path)}`); setDiff({ path, ...result }); setBottom('changes') }
    catch (error) { setWorkspaceError(`Changes: ${String(error)}`) }
  }
  const closeTab = (path: string) => {
    const tab = tabsRef.current.find(item => item.path === path)
    if (tab && dirty(tab) && !window.confirm(`${path} has unsaved edits. Close it?`)) return
    setTabs(current => current.filter(item => item.path !== path)); if (active === path) setActive(tabsRef.current.find(item => item.path !== path)?.path || '')
  }
  const fileGroups = [
    ['Programs', pous.filter(item => item.kind === 'program')], ['Function Blocks', pous.filter(item => item.kind === 'function_block')],
    ['Functions', pous.filter(item => item.kind === 'function')], ['Globals', globals], ['Inputs', io.inputs], ['Outputs', io.outputs]
  ] as const
  const collectFiles = (nodes: TreeNode[]): TreeNode[] => nodes.flatMap(node => node.kind === 'file' ? [node] : collectFiles(node.children || []))
  const plans = collectFiles(tree).filter(node => node.name.endsWith('.json'))

  return <div className="app-shell">
    <header className="topbar"><div className="brand-mark">∿</div><div className="brand"><strong>PLC<span>AGENT</span></strong><small>ENGINEERING WORKSPACE</small></div><div className="top-separator" /><div className="workspace-name">{health?.workspace?.split(/[\\/]/).pop() || 'Workspace'} <span className="crumb">/</span> <span className="crumb">Structured Text</span></div><div className="top-spacer" /><span className="sim-badge">SIMULATION</span><span className="header-status"><i className={health?.runtime === 'running' ? 'green' : 'gray'} />PLC {health?.runtime?.toUpperCase() || 'UNKNOWN'}</span><span className="header-status"><i className={health?.codex === 'ready' ? 'green' : 'red'} />CODEX {health?.codex?.toUpperCase() || 'CHECKING'}</span><button className="icon-button" title="Refresh status" onClick={() => void refreshHealth()}>↻</button></header>
    <main className="main-grid">
      <aside className="sidebar"><div className="side-head"><span>PROJECT NAVIGATOR</span><button onClick={() => { void refreshTree(); void refreshContext() }} title="Refresh">↻</button></div><div className="segmented"><button className={explorer === 'files' ? 'selected' : ''} onClick={() => setExplorer('files')}>FILES</button><button className={explorer === 'plc' ? 'selected' : ''} onClick={() => setExplorer('plc')}>PLC</button></div><div className="sidebar-content">{explorer === 'files' ? <><div className="section-title">WORKSPACE <span>{tree.length}</span></div><Tree nodes={tree} openFile={path => void openFile(path)} /></> : <><div className="section-title">PLC PROJECT <span>{pous.length + globals.length}</span></div>{fileGroups.map(([title, items]) => <details key={title} open className="plc-group"><summary>{title} <em>{items.length}</em></summary>{items.map((item, index) => <button key={`${item.file}-${item.line}-${index}`} onClick={() => void openFile(item.file, item.line)}><span className="symbol-icon">{item.address ? '↳' : '◇'}</span><span>{item.address && <small>{item.address}</small>}{item.name || item.symbol}</span></button>)}</details>)}</>}</div><div className="side-foot">P3 PROJECT CONTEXT <span className={health?.project === 'ready' ? 'live-dot' : ''}>●</span></div></aside>
      <section className="editor-zone"><div className="editor-toolbar"><span className="editor-label">SOURCE EDITOR</span><div className="editor-actions"><button onClick={askSelection} disabled={!active}>Ask Codex ↗</button><button onClick={() => void check()} disabled={!active?.endsWith('.st') || Boolean(busy)}>Check</button><button onClick={() => active && void save(active)} disabled={!active || Boolean(busy)}>Save <kbd>Ctrl+S</kbd></button></div></div><div className="tabbar">{tabs.length ? tabs.map(tab => <div key={tab.path} className={`tab ${active === tab.path ? 'active' : ''}`}><button onClick={() => { setActive(tab.path); setDiff(null) }}>{dirty(tab) ? <span className="dirty-dot">●</span> : <span className="tab-st">{tab.path.endsWith('.st') ? 'ST' : '◇'}</span>}{tab.path.split('/').pop()}{tab.external && <b className="conflict-dot">!</b>}</button><button className="tab-close" onClick={() => closeTab(tab.path)}>×</button></div>) : <span className="empty-tabs">Open a file from Explorer to begin</span>}</div><div className="editor-body">{diff ? <><div className="diff-heading"><span>DIFF · {diff.path}</span><button onClick={() => setDiff(null)}>Close diff ×</button></div><DiffEditor height="calc(100% - 29px)" original={diff.before} modified={diff.after} language={diff.path.endsWith('.st') ? 'structured-text' : 'plaintext'} theme="vs-dark" beforeMount={registerStructuredText} options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false } }} /></> : activeTab ? <Editor path={activeTab.path} value={activeTab.content} language={activeTab.path.endsWith('.st') ? 'structured-text' : 'plaintext'} theme="vs-dark" beforeMount={registerStructuredText} onMount={onMount} onChange={value => setTabs(current => current.map(tab => tab.path === active ? { ...tab, content: value ?? '' } : tab))} options={{ fontSize: 13, fontFamily: 'Cascadia Code, Consolas, monospace', lineHeight: 21, minimap: { enabled: false }, glyphMargin: true, scrollBeyondLastLine: false, automaticLayout: true, wordWrap: 'off', tabSize: 2 }} /> : <div className="editor-welcome"><div className="welcome-logo">∿</div><h1>Industrial Cursor</h1><p>Your PLC engineering workspace is ready.</p><div><span>01</span> Open a Structured Text file</div><div><span>02</span> Inspect symbols and I/O</div><div><span>03</span> Ask Codex to engineer and verify</div></div>}</div>{activeTab?.external && <div className="conflict-banner"><strong>File changed externally</strong><span>{activeTab.path} has unsaved edits.</span><button onClick={() => { setDiff({ path: activeTab.path, before: activeTab.content, after: activeTab.external!.content }) }}>View Diff</button><button onClick={() => setTabs(current => current.map(tab => tab.path === active ? { ...tab.external!, savedContent: tab.external!.content } : tab))}>Reload</button><button onClick={() => setTabs(current => current.map(tab => tab.path === active ? { ...tab, version: tab.external!.version, external: undefined } : tab))}>Keep Mine</button></div>}</section>
      <aside className="agent-panel"><div className="agent-head"><div><span className="agent-glyph">✦</span><strong>Codex Agent</strong><small>{threadId ? `Thread ${threadId.slice(0, 8)}` : 'New thread'}</small></div><div className="agent-head-actions"><button title="New session" onClick={() => { void post('/api/agent/sessions/new').then(() => { setAgentRows([]); setThreadId(null); void refreshSessions() }).catch(error => setAgentError(String(error))) }}>＋</button><select title="Resume previous session" value={threadId || ''} onChange={event => { if (event.target.value) void post('/api/agent/sessions/resume', { thread_id: event.target.value }).then(() => { setAgentRows([]); void refreshSessions() }).catch(error => setAgentError(String(error))) }}><option value="">Sessions</option>{sessions.map(item => <option key={item.thread_id} value={item.thread_id}>{item.title.slice(0, 35)}</option>)}</select></div></div><div className="agent-stream">{agentRows.length ? agentRows.map((row, index) => <div className={`agent-row ${row.kind}`} key={`${row.id || index}-${index}`}><span className="row-icon">{row.kind === 'tool' ? row.state === 'working' ? '◌' : '✓' : row.kind === 'error' ? '!' : row.kind === 'status' ? '→' : '✦'}</span><div><LinkText text={row.text} jump={(path, line) => void openFile(path, line)} />{row.kind === 'tool' && row.state === 'working' && <span className="working-label"> WORKING</span>}</div></div>) : <div className="agent-empty"><div className="agent-empty-icon">✦</div><h3>Engineer with Codex</h3><p>Ask about a symbol, request an ST edit, or verify PLC behavior. Tool activity appears here.</p><div className="suggestion" onClick={() => setAgentInput('检查当前工程，告诉我 Motor 是在哪里定义的。')}>Find where Motor is defined →</div></div>}{agentActive && <div className="agent-working"><span className="pulse-dot" /> Codex is working… <button onClick={() => void post('/api/agent/interrupt')}>Interrupt</button></div>}</div><div className="agent-compose"><textarea value={agentInput} onChange={event => setAgentInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendAgent() } }} placeholder="Ask Codex about this PLC project…" /><div><span>Enter to send · Shift+Enter for line break</span><button onClick={() => void sendAgent()} disabled={agentActive || !agentInput.trim()}>Send ↗</button></div></div></aside>
    </main>
    <section className="bottom-dock"><div className="dock-tabs">{(['problems', 'runtime', 'variables', 'watch', 'forced', 'trace', 'ladder', 'changes'] as const).map(tab => <button key={tab} className={bottom === tab ? 'active' : ''} onClick={() => { setBottom(tab) }}>{tab.toUpperCase()}{tab === 'problems' && <em>{diagnostics.length}</em>}{tab === 'changes' && <em>{changes.length}</em>}</button>)}<div className="dock-spacer" /><span className="operation-label">{busy || 'READY'}</span></div><div className="dock-content"><Debugger panel={bottom} workspace={storageWorkspace} file={active} dirty={tabs.some(tab => tab.path.endsWith('.st') && dirty(tab))} connected={connection === 'connected'} jump={(file, line) => void openFile(file, line)} selectPanel={setBottom} />{bottom === 'problems' && <div className="problem-list">{diagnostics.length ? diagnostics.map((item, index) => <button key={index} onClick={() => void openFile(item.file, item.line)}><span className={item.severity === 'warning' ? 'warn' : 'error'}>●</span><strong>{item.file}:{item.line}:{item.column}</strong><span>{item.message}</span></button>) : <div className="empty-panel">No compiler diagnostics. Open an ST file and run Check.</div>}</div>}{bottom === 'runtime' && <div className="runtime-panel"><div><strong>SIMULATION RUNTIME</strong><span className={`runtime-value ${health?.runtime}`}>{health?.runtime?.toUpperCase() || 'UNKNOWN'}</span><small>MatIEC / OpenPLC test environment</small></div><div className="runtime-controls"><button disabled={Boolean(busy) || !active?.endsWith('.st')} onClick={() => void runRuntime('build-run')}>Build &amp; Run</button><button disabled={Boolean(busy) || !active?.endsWith('.st')} onClick={() => void runRuntime('compile')}>Compile & Load</button><button disabled={Boolean(busy)} onClick={() => void runRuntime('start')}>Start</button><button disabled={Boolean(busy)} onClick={() => void runRuntime('stop')}>Stop</button><select value={verifyPlan} onChange={event => setVerifyPlan(event.target.value)}><option value="">Select JSON plan</option>{plans.map(plan => <option key={plan.path} value={plan.path}>{plan.path}</option>)}</select><button disabled={Boolean(busy) || !verifyPlan} onClick={() => void runRuntime('verify')}>Verify plan</button></div></div>}{bottom === 'changes' && <div className="changes-panel">{changes.length ? changes.map(change => <button key={change.path} onClick={() => void showDiff(change.path)}><span>M</span>{change.path}<small>{change.source}</small></button>) : <div className="empty-panel">No changes observed in this Web IDE session.</div>}</div>}{runtimeError && <div className="error-line">Runtime: {runtimeError}</div>}</div></section>
    <footer className="statusbar"><div><span className="status-led" />{health?.runtime?.toUpperCase() || 'PLC UNKNOWN'} <span className="status-divider">│</span> MCP {health?.mcp?.toUpperCase() || 'CHECKING'} <span className="status-divider">│</span> CODEX {health?.codex?.toUpperCase() || 'CHECKING'}</div><div>{workspaceError || agentError || (connection === 'connected' ? `${diagnostics.filter(d => d.severity === 'error').length} errors · ${diagnostics.filter(d => d.severity === 'warning').length} warnings` : `Agent connection ${connection}`)}</div><div>{active ? `${active} · ${activeTab && dirty(activeTab) ? 'UNSAVED' : 'SAVED'}` : 'PLC-AGENT WEB IDE'} <span className="status-divider">│</span> {connection.toUpperCase()}</div></footer>
  </div>
}
