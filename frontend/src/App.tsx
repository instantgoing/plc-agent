import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import Editor, { DiffEditor, type OnMount } from '@monaco-editor/react'
import type * as monaco from 'monaco-editor'
import { api, post, pathLink, type Diagnostic, type FileData, type TreeNode, type WebEvent } from './api'
import { hasDirtyConflict, monacoMarkers } from './diagnostics'
import { registerStructuredText } from './stLanguage'
import { Debugger } from './Debugger'
import { debugStore } from './debugStore'
import { FileExplorer, type ExplorerMutation } from './FileExplorer'
import { ActivityRail, WorkbenchIcon } from './WorkbenchNavigation'
import type { AgentRow } from './AgentActivity'
import { AgentPanel, TopBar, WorkspaceEmpty } from './WorkbenchPanels'

type Tab = FileData & { savedContent: string; external?: FileData }
type ContextItem = { name?: string; symbol?: string; kind?: string; address?: string; type?: string; file: string; line: number; inputs?: ContextItem[]; outputs?: ContextItem[]; locals?: ContextItem[]; inouts?: ContextItem[] }
type Health = { workspace: string; codex: string; mcp: string; runtime: string; project: string; environment: string; agent_active: boolean }
type Change = { path: string; source: string }
type ResizePanel = 'sidebar' | 'agent' | 'dock'

const readPanelSize = (key: string, fallback: number) => {
  const value = Number(stored(key, String(fallback)))
  return Number.isFinite(value) && value > 0 ? value : fallback
}

const stored = (key: string, fallback: string) => { try { return localStorage.getItem(key) || fallback } catch { return fallback } }
const within = (path: string, base: string) => path === base || path.startsWith(`${base}/`)
const relocated = (path: string, source: string, target: string) => within(path, source) ? target + path.slice(source.length) : path

function moveTabFocus(event: KeyboardEvent<HTMLButtonElement>) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  const buttons = Array.from(event.currentTarget.closest('[role="tablist"]')?.querySelectorAll<HTMLButtonElement>('[role="tab"]') || [])
  const current = buttons.indexOf(event.currentTarget)
  if (current < 0 || !buttons.length) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
    : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
  buttons[next]?.focus()
  buttons[next]?.click()
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
  const [agentOpen, setAgentOpen] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [dockOpen, setDockOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [paletteQuery, setPaletteQuery] = useState('')
  const [paletteIndex, setPaletteIndex] = useState(0)
  const [sidebarWidth, setSidebarWidth] = useState(() => readPanelSize('plc-sidebar-width', 300))
  const [agentWidth, setAgentWidth] = useState(() => readPanelSize('plc-agent-width', 300))
  const [dockHeight, setDockHeight] = useState(() => readPanelSize('plc-dock-height', 300))
  const [resizing, setResizing] = useState<ResizePanel | null>(null)
  const shellRef = useRef<HTMLDivElement | null>(null)
  const mainRef = useRef<HTMLElement | null>(null)
  const resizeRef = useRef<{ panel: ResizePanel; pointerId: number; startPosition: number; startSize: number } | null>(null)
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<typeof monaco | null>(null)
  const saveRef = useRef<() => void>(() => {})
  const seq = useRef(0)
  const tabsRef = useRef(tabs)
  tabsRef.current = tabs
  const activeTab = tabs.find(tab => tab.path === active)
  const dirty = (tab: Tab) => tab.content !== tab.savedContent

  useEffect(() => {
    try {
      localStorage.setItem('plc-sidebar-width', String(sidebarWidth))
      localStorage.setItem('plc-agent-width', String(agentWidth))
      localStorage.setItem('plc-dock-height', String(dockHeight))
    } catch {}
  }, [sidebarWidth, agentWidth, dockHeight])

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { setPaletteOpen(false); return }
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return
      const key = event.key.toLowerCase()
      if (key === 'p' && event.shiftKey) { event.preventDefault(); setPaletteQuery(''); setPaletteIndex(0); setPaletteOpen(true); return }
      if (key === 'b' && !event.shiftKey) { event.preventDefault(); setSidebarOpen(open => !open) }
      if (key === 'j' && !event.shiftKey) { event.preventDefault(); setDockOpen(open => !open) }
      if (key === 'm' && event.shiftKey) { event.preventDefault(); setBottom('problems'); setDockOpen(true) }
      if (key === 'l' && !event.shiftKey) { event.preventDefault(); setAgentOpen(true); requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('.agent-compose textarea')?.focus()) }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const panelElement = (panel: ResizePanel) => panel === 'dock'
    ? shellRef.current?.querySelector('.bottom-dock')
    : mainRef.current?.querySelector(panel === 'sidebar' ? '.sidebar' : '.agent-panel')

  const panelSize = (panel: ResizePanel) => {
    const bounds = panelElement(panel)?.getBoundingClientRect()
    return panel === 'dock' ? bounds?.height ?? dockHeight : bounds?.width ?? (panel === 'sidebar' ? sidebarWidth : agentWidth)
  }

  const resizePanel = (panel: ResizePanel, requested: number) => {
    if (panel === 'dock') {
      const maximum = Math.max(160, (shellRef.current?.clientHeight ?? window.innerHeight) - 48 - 31 - 8 - 220)
      setDockHeight(Math.max(160, Math.min(requested, maximum)))
      return
    }
    const compact = window.matchMedia('(max-width: 760px)').matches
    const otherWidth = panel === 'sidebar' ? (compact || !agentOpen ? 0 : panelSize('agent')) : (sidebarOpen ? panelSize('sidebar') : 0)
    const minimum = panel === 'sidebar' ? 170 : 280
    const railWidth = compact ? 44 : 48
    const editorMinimum = compact ? 220 : 280
    const maximum = Math.max(minimum, (mainRef.current?.clientWidth ?? window.innerWidth) - railWidth - otherWidth - editorMinimum - (compact || !agentOpen ? 8 : 16))
    if (panel === 'sidebar') setSidebarWidth(Math.max(minimum, Math.min(requested, maximum)))
    else setAgentWidth(Math.max(minimum, Math.min(requested, maximum)))
  }

  const startResize = (panel: ResizePanel, event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    resizeRef.current = { panel, pointerId: event.pointerId, startPosition: panel === 'dock' ? event.clientY : event.clientX, startSize: panelSize(panel) }
    event.currentTarget.setPointerCapture(event.pointerId)
    setResizing(panel)
  }

  const moveResize = (event: PointerEvent<HTMLDivElement>) => {
    const drag = resizeRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const delta = (drag.panel === 'dock' ? event.clientY : event.clientX) - drag.startPosition
    resizePanel(drag.panel, drag.startSize + (drag.panel === 'sidebar' ? delta : -delta))
  }

  const endResize = (event: PointerEvent<HTMLDivElement>) => {
    if (resizeRef.current?.pointerId !== event.pointerId) return
    resizeRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    setResizing(null)
  }

  const keyResize = (panel: ResizePanel, event: KeyboardEvent<HTMLDivElement>) => {
    const direction = panel === 'sidebar' ? { ArrowLeft: -1, ArrowRight: 1 }
      : panel === 'agent' ? { ArrowLeft: 1, ArrowRight: -1 }
      : { ArrowUp: 1, ArrowDown: -1 }
    const step = direction[event.key as keyof typeof direction]
    if (!step) return
    event.preventDefault()
    resizePanel(panel, panelSize(panel) + step * 20)
  }

  const splitter = (panel: ResizePanel) => <div
    className={`panel-splitter panel-splitter-${panel}${resizing === panel ? ' active' : ''}`}
    role="separator"
    aria-label={`Resize ${panel === 'sidebar' ? 'project sidebar' : panel === 'agent' ? 'PLC Agent panel' : 'bottom panel'}`}
    aria-orientation={panel === 'dock' ? 'horizontal' : 'vertical'}
    aria-valuenow={Math.round(panel === 'dock' ? dockHeight : panel === 'sidebar' ? sidebarWidth : agentWidth)}
    tabIndex={0}
    title="Drag to resize; use arrow keys when focused"
    onPointerDown={event => startResize(panel, event)}
    onPointerMove={moveResize}
    onPointerUp={endResize}
    onPointerCancel={endResize}
    onLostPointerCapture={endResize}
    onKeyDown={event => keyResize(panel, event)}
  />

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
    setAgentOpen(true)
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
  const canMutate = (path: string) => {
    if (tabsRef.current.some(tab => within(tab.path, path) && (dirty(tab) || tab.external))) {
      setWorkspaceError(`Save or resolve unsaved changes under ${path} before changing files.`)
      return false
    }
    return true
  }
  const onExplorerMutation = (mutation: ExplorerMutation) => {
    if (mutation.operation === 'move' && mutation.source && mutation.source !== mutation.path) {
      const source = mutation.source, target = mutation.path
      setTabs(current => current.map(tab => within(tab.path, source)
        ? { ...tab, path: relocated(tab.path, source, target),
            external: tab.external ? { ...tab.external, path: relocated(tab.external.path, source, target) } : undefined }
        : tab))
      setActive(current => relocated(current, source, target))
      setDiff(current => current ? { ...current, path: relocated(current.path, source, target) } : null)
      setVerifyPlan(current => relocated(current, source, target))
      setDiagnostics(current => current.map(item => ({ ...item, file: relocated(item.file, source, target) })))
    } else if (mutation.operation === 'delete') {
      const path = mutation.path
      const nextActive = tabsRef.current.find(tab => !within(tab.path, path))?.path || ''
      setTabs(current => current.filter(tab => !within(tab.path, path)))
      setActive(current => within(current, path) ? nextActive : current)
      setDiff(current => current && within(current.path, path) ? null : current)
      setVerifyPlan(current => within(current, path) ? '' : current)
      setDiagnostics(current => current.filter(item => !within(item.file, path)))
    }
    setWorkspaceError('')
  }
  const askFileWithAI = (path: string) => {
    setAgentOpen(true)
    setAgentInput(current => `${current ? `${current}\n` : ''}请查看文件 ${path}。我的问题是：`)
  }
  const fileGroups = [
    ['Programs', pous.filter(item => item.kind === 'program')], ['Function Blocks', pous.filter(item => item.kind === 'function_block')],
    ['Functions', pous.filter(item => item.kind === 'function')], ['Globals', globals], ['Inputs', io.inputs], ['Outputs', io.outputs]
  ] as const
  const collectFiles = (nodes: TreeNode[]): TreeNode[] => nodes.flatMap(node => node.kind === 'file' ? [node] : collectFiles(node.children || []))
  const plans = collectFiles(tree).filter(node => node.name.endsWith('.json'))
  const paletteCommands = [
    { label: 'View: Show Explorer', run: () => { setExplorer('files'); setSidebarOpen(true) } },
    { label: 'View: Show PLC Project', run: () => { setExplorer('plc'); setSidebarOpen(true) } },
    { label: 'View: Show Problems', run: () => { setBottom('problems'); setDockOpen(true) } },
    { label: 'View: Show Runtime Output', run: () => { setBottom('runtime'); setDockOpen(true) } },
    { label: 'View: Show PLC Agent', run: () => { setAgentOpen(true); requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('.agent-compose textarea')?.focus()) } },
    { label: 'File: Save Active File', run: () => { if (active) void save(active) } },
    { label: 'PLC: Check Active Program', run: () => { if (active?.endsWith('.st')) void check() } },
    { label: 'PLC: Refresh Project', run: () => { void refreshTree(); void refreshContext() } },
  ]
  const visibleCommands = paletteCommands.filter(command => command.label.toLowerCase().includes(paletteQuery.trim().replace(/^>/, '').toLowerCase()))
  const runPaletteCommand = (index: number) => {
    visibleCommands[index]?.run()
    setPaletteOpen(false)
  }

  return <div className={`app-shell${resizing ? ' is-resizing' : ''}${agentOpen ? '' : ' agent-hidden'}${sidebarOpen ? '' : ' sidebar-hidden'}${dockOpen ? '' : ' dock-hidden'}`} ref={shellRef} style={{ '--sidebar-width': `${sidebarWidth}px`, '--agent-width': `${agentWidth}px`, '--dock-height': `${dockHeight}px` } as CSSProperties}>
    {paletteOpen && <div className="command-palette-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setPaletteOpen(false) }}><div className="command-palette" role="dialog" aria-label="Command palette"><input autoFocus aria-label="Type a command" value={paletteQuery} onChange={event => { setPaletteQuery(event.target.value); setPaletteIndex(0) }} onKeyDown={event => { if (event.key === 'ArrowDown') { event.preventDefault(); setPaletteIndex(index => Math.min(index + 1, visibleCommands.length - 1)) } else if (event.key === 'ArrowUp') { event.preventDefault(); setPaletteIndex(index => Math.max(0, index - 1)) } else if (event.key === 'Enter') { event.preventDefault(); runPaletteCommand(paletteIndex) } }} placeholder=">" /><div className="command-palette-list" role="listbox" aria-label="Commands">{visibleCommands.map((command, index) => <button key={command.label} type="button" role="option" aria-selected={index === paletteIndex} className={index === paletteIndex ? 'selected' : ''} onMouseEnter={() => setPaletteIndex(index)} onClick={() => runPaletteCommand(index)}>{command.label}</button>)}</div></div></div>}
    <TopBar
      workspace={health?.workspace?.split(/[\\/]/).pop() || 'Workspace'}
      runtime={health?.runtime}
      codex={health?.codex}
      agentOpen={agentOpen}
      onRefresh={() => void refreshHealth()}
      onOpenAgent={() => setAgentOpen(true)}
    />
    <main className="main-grid" ref={mainRef}>
      <ActivityRail explorer={explorer} setExplorer={value => { setExplorer(value); setSidebarOpen(true) }} bottom={bottom} onOpenPanel={panel => { setBottom(panel); setDockOpen(true) }} agentOpen={agentOpen} setAgentOpen={setAgentOpen} />
      {splitter('sidebar')}
      {splitter('agent')}
      <aside className="sidebar">
        <div className="side-head"><span>{explorer === 'files' ? 'EXPLORER' : 'PLC PROJECT'}</span>{explorer === 'plc' && <button type="button" onClick={() => { void refreshTree(); void refreshContext() }} title="Refresh project context" aria-label="Refresh project context"><WorkbenchIcon name="refresh" size={15} /></button>}</div>
        <div className="segmented"><button className={explorer === 'files' ? 'selected' : ''} onClick={() => setExplorer('files')}>FILES</button><button className={explorer === 'plc' ? 'selected' : ''} onClick={() => setExplorer('plc')}>PLC</button></div>
        {explorer === 'files' ? <FileExplorer nodes={tree} workspace={storageWorkspace || health?.workspace || ''}
          openFile={path => void openFile(path)} askAI={askFileWithAI}
          refresh={async () => { await refreshTree(); void refreshContext(); void refreshChanges() }}
          canMutate={canMutate} onMutation={onExplorerMutation} />
          : <div className="sidebar-content"><div className="section-title">PLC PROJECT <span>{pous.length + globals.length}</span></div>{fileGroups.map(([title, items]) => <details key={title} open className="plc-group"><summary>{title} <em>{items.length}</em></summary>{items.map((item, index) => <button key={`${item.file}-${item.line}-${index}`} onClick={() => void openFile(item.file, item.line)}><span className="symbol-icon">{item.address ? '↳' : '◇'}</span><span>{item.address && <small>{item.address}</small>}{item.name || item.symbol}</span></button>)}</details>)}</div>}
        <div className="side-foot">PROJECT CONTEXT <span className={health?.project === 'ready' ? 'live-dot' : ''}>●</span></div>
      </aside>
      <section className="editor-zone"><div className="editor-toolbar"><span className="editor-label">{active ? active.replace("/", " › ") : "SOURCE EDITOR"}</span><div className="editor-actions"><button onClick={askSelection} disabled={!active}>Ask PLC Agent ↗</button><button onClick={() => void check()} disabled={!active?.endsWith('.st') || Boolean(busy)}>Check</button><button onClick={() => active && void save(active)} disabled={!active || Boolean(busy)}>Save <kbd>Ctrl+S</kbd></button></div></div><div className="tabbar" role="tablist" aria-label="Open files">{tabs.length ? tabs.map(tab => <div key={tab.path} className={`tab ${active === tab.path ? 'active' : ''}`}><button role="tab" aria-selected={active === tab.path} tabIndex={active === tab.path ? 0 : -1} onKeyDown={moveTabFocus} title={tab.path} onClick={() => { setActive(tab.path); setDiff(null) }}>{dirty(tab) ? <span className="dirty-dot">●</span> : <span className="tab-st">{tab.path.endsWith('.st') ? 'ST' : '◇'}</span>}{tab.path.split('/').pop()}{tab.external && <b className="conflict-dot">!</b>}</button><button className="tab-close" aria-label={`Close ${tab.path.split('/').pop()}`} title="Close tab" onClick={() => closeTab(tab.path)}>×</button></div>) : <span className="empty-tabs">Open a file from Explorer to begin</span>}</div><div className="editor-body">{diff ? <><div className="diff-heading"><span>DIFF · {diff.path}</span><button onClick={() => setDiff(null)}>Close diff ×</button></div><DiffEditor height="calc(100% - 29px)" original={diff.before} modified={diff.after} language={diff.path.endsWith('.st') ? 'structured-text' : 'plaintext'} theme="plc-workbench" beforeMount={registerStructuredText} options={{ readOnly: true, renderSideBySide: true, fontSize: 14, lineHeight: 19, minimap: { enabled: false } }} /></> : activeTab ? <Editor path={activeTab.path} value={activeTab.content} language={activeTab.path.endsWith('.st') ? 'structured-text' : 'plaintext'} theme="plc-workbench" beforeMount={registerStructuredText} onMount={onMount} onChange={value => setTabs(current => current.map(tab => tab.path === active ? { ...tab, content: value ?? '' } : tab))} options={{ fontSize: 14, fontFamily: 'Consolas, Courier New, monospace', lineNumbersMinChars: 3, lineHeight: 19, minimap: { enabled: true }, glyphMargin: true, scrollBeyondLastLine: false, automaticLayout: true, wordWrap: 'off', tabSize: 2 }} /> : <WorkspaceEmpty onFiles={() => setExplorer('files')} onProject={() => setExplorer('plc')} onAgent={() => setAgentOpen(true)} />}</div>{activeTab?.external && <div className="conflict-banner"><strong>File changed externally</strong><span>{activeTab.path} has unsaved edits.</span><button onClick={() => { setDiff({ path: activeTab.path, before: activeTab.content, after: activeTab.external!.content }) }}>View Diff</button><button onClick={() => setTabs(current => current.map(tab => tab.path === active ? { ...tab.external!, savedContent: tab.external!.content } : tab))}>Reload</button><button onClick={() => setTabs(current => current.map(tab => tab.path === active ? { ...tab, version: tab.external!.version, external: undefined } : tab))}>Keep Mine</button></div>}</section>
      <AgentPanel
        threadId={threadId}
        sessions={sessions}
        rows={agentRows}
        active={agentActive}
        input={agentInput}
        setInput={setAgentInput}
        onNew={() => { void post('/api/agent/sessions/new').then(() => { setAgentRows([]); setThreadId(null); void refreshSessions() }).catch(error => setAgentError(String(error))) }}
        onResume={id => { void post('/api/agent/sessions/resume', { thread_id: id }).then(() => { setAgentRows([]); void refreshSessions() }).catch(error => setAgentError(String(error))) }}
        onClose={() => setAgentOpen(false)}
        onSend={() => void sendAgent()}
        onInterrupt={() => void post('/api/agent/interrupt')}
        onSuggestion={setAgentInput}
        renderText={text => <LinkText text={text} jump={(path, line) => void openFile(path, line)} />}
      />
    </main>
    {splitter('dock')}
    <section className="bottom-dock"><div className="dock-tabs" role="tablist" aria-label="Output panels">{(['problems', 'runtime', 'variables', 'watch', 'forced', 'trace', 'ladder', 'changes'] as const).map(tab => <button key={tab} role="tab" aria-selected={bottom === tab} tabIndex={bottom === tab ? 0 : -1} onKeyDown={moveTabFocus} className={bottom === tab ? 'active' : ''} onClick={() => { setBottom(tab) }}>{tab.toUpperCase()}{tab === 'problems' && <em>{diagnostics.length}</em>}{tab === 'changes' && <em>{changes.length}</em>}</button>)}<div className="dock-spacer" /><span className={`operation-label${busy ? ' is-busy' : ''}`} role="status">{busy && <span className="activity-spinner" aria-hidden="true" />}{busy || 'READY'}</span><button className="dock-close" type="button" aria-label="Close bottom panel" title="Close panel" onClick={() => setDockOpen(false)}>×</button></div><div className="dock-content"><Debugger panel={bottom} workspace={storageWorkspace} file={active} dirty={tabs.some(tab => tab.path.endsWith('.st') && dirty(tab))} connected={connection === 'connected'} jump={(file, line) => void openFile(file, line)} selectPanel={setBottom} />{bottom === 'problems' && <div className="problem-list">{diagnostics.length ? diagnostics.map((item, index) => <button key={index} onClick={() => void openFile(item.file, item.line)}><span className={item.severity === 'warning' ? 'warn' : 'error'}>●</span><strong>{item.file}:{item.line}:{item.column}</strong><span>{item.message}</span></button>) : <div className="empty-panel">No compiler diagnostics. Open an ST file and run Check.</div>}</div>}{bottom === 'runtime' && <div className="runtime-panel"><div><strong>SIMULATION RUNTIME</strong><span className={`runtime-value ${health?.runtime}`}>{health?.runtime?.toUpperCase() || 'UNKNOWN'}</span><small>MatIEC / OpenPLC test environment</small></div><div className="runtime-controls"><button disabled={Boolean(busy) || !active?.endsWith('.st')} onClick={() => void runRuntime('build-run')}>Build &amp; Run</button><button disabled={Boolean(busy) || !active?.endsWith('.st')} onClick={() => void runRuntime('compile')}>Compile & Load</button><button disabled={Boolean(busy)} onClick={() => void runRuntime('start')}>Start</button><button disabled={Boolean(busy)} onClick={() => void runRuntime('stop')}>Stop</button><select value={verifyPlan} onChange={event => setVerifyPlan(event.target.value)}><option value="">Select JSON plan</option>{plans.map(plan => <option key={plan.path} value={plan.path}>{plan.path}</option>)}</select><button disabled={Boolean(busy) || !verifyPlan} onClick={() => void runRuntime('verify')}>Verify plan</button></div></div>}{bottom === 'changes' && <div className="changes-panel">{changes.length ? changes.map(change => <button key={change.path} onClick={() => void showDiff(change.path)}><span>M</span>{change.path}<small>{change.source}</small></button>) : <div className="empty-panel">No changes observed in this Web IDE session.</div>}</div>}{runtimeError && <div className="error-line">Runtime: {runtimeError}</div>}</div></section>
    <footer className="statusbar"><div><span className="status-led" />{health?.runtime?.toUpperCase() || 'PLC UNKNOWN'} <span className="status-divider">│</span> MCP {health?.mcp?.toUpperCase() || 'CHECKING'} <span className="status-divider">│</span> AGENT {health?.codex?.toUpperCase() || 'CHECKING'}</div><div>{workspaceError || agentError || (connection === 'connected' ? `${diagnostics.filter(d => d.severity === 'error').length} errors · ${diagnostics.filter(d => d.severity === 'warning').length} warnings` : `Agent connection ${connection}`)}</div><div>{active ? `${active} · ${activeTab && dirty(activeTab) ? 'UNSAVED' : 'SAVED'}` : 'PLC-AGENT WEB IDE'} <span className="status-divider">│</span> {connection.toUpperCase()}</div></footer>
  </div>
}
