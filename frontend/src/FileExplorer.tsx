import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent, type MouseEvent } from 'react'
import { ApiError, post, type TreeNode } from './api'
import './file-explorer.css'

export type ExplorerMutation = {
  operation: 'create' | 'copy' | 'move' | 'delete' | 'restore'
  kind: 'file' | 'folder'
  path: string
  source?: string
  undo_token?: string
}

type Entry = Pick<TreeNode, 'path' | 'name' | 'kind'>
type ClipboardEntry = { path: string; mode: 'copy' | 'cut' }
type Undo = { mode: 'restore'; token: string; path: string }
  | { mode: 'move'; source: string; path: string }
  | { mode: 'delete'; path: string }
type Dialog = { mode: 'file' | 'folder' | 'rename'; parent: string; entry?: Entry; name: string }

type Props = {
  nodes: TreeNode[]
  workspace: string
  openFile: (path: string) => void
  askAI: (path: string) => void
  refresh: () => Promise<void>
  canMutate: (path: string) => boolean
  onMutation: (mutation: ExplorerMutation) => void
}

const parentOf = (path: string) => path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
const nameOf = (path: string) => path.split('/').at(-1) || path
export function FileExplorer({ nodes, workspace, openFile, askAI, refresh, canMutate, onMutation }: Props) {
  const [selected, setSelected] = useState<Entry | null>(null)
  const [clipboard, setClipboard] = useState<ClipboardEntry | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; entry: Entry | null } | null>(null)
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [query, setQuery] = useState('')
  const [filterOpen, setFilterOpen] = useState(false)
  const [hideSamples, setHideSamples] = useState(false)
  const [collapseKey, setCollapseKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [undo, setUndo] = useState<Undo | null>(null)
  const filterRef = useRef<HTMLInputElement>(null)
  const workspaceName = workspace.split(/[\\/]/).filter(Boolean).at(-1) || 'WORKSPACE'

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [menu])

  useEffect(() => { if (filterOpen) filterRef.current?.focus() }, [filterOpen])

  const visibleNodes = (items: TreeNode[]): TreeNode[] => items.flatMap(node => {
    if (hideSamples && (node.path === 'examples' || node.path === 'tests')) return []
    if (!query.trim()) return [node]
    const needle = query.trim().toLocaleLowerCase()
    if (node.name.toLocaleLowerCase().includes(needle)) return [node]
    if (node.kind === 'folder') {
      const children = visibleNodes(node.children || [])
      if (children.length) return [{ ...node, children }]
    }
    return []
  })
  const shown = visibleNodes(nodes)

  const showMenu = (event: MouseEvent, entry: Entry | null) => {
    event.preventDefault()
    event.stopPropagation()
    if (entry) setSelected(entry)
    setMenu({ x: Math.min(event.clientX, window.innerWidth - 210),
      y: Math.min(event.clientY, window.innerHeight - 320), entry })
  }

  const showToolbarMenu = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    const rect = event.currentTarget.getBoundingClientRect()
    setMenu({ x: Math.max(8, rect.right - 190), y: rect.bottom + 3, entry: null })
  }

  const applied = async (result: ExplorerMutation, nextUndo: Undo | null) => {
    onMutation(result)
    if (result.operation === 'move' && result.source) {
      const source = result.source, target = result.path
      setSelected(current => current && (current.path === source || current.path.startsWith(`${source}/`))
        ? { ...current, path: target + current.path.slice(source.length), name: nameOf(target + current.path.slice(source.length)) }
        : current)
      setClipboard(current => current && (current.path === source || current.path.startsWith(`${source}/`))
        ? { ...current, path: target + current.path.slice(source.length) } : current)
    } else if (result.operation === 'delete') {
      setSelected(current => current && (current.path === result.path || current.path.startsWith(`${result.path}/`)) ? null : current)
      setClipboard(current => current && (current.path === result.path || current.path.startsWith(`${result.path}/`)) ? null : current)
    }
    setUndo(nextUndo)
    if (result.operation !== 'delete') setQuery('')
    await refresh()
    setFeedback(`${result.operation === 'delete' ? 'Moved to recoverable trash' : 'Done'}: ${result.path}`)
  }

  const remove = async (path: string, recordUndo = true, confirm = true): Promise<ExplorerMutation | null> => {
    if (!canMutate(path)) return null
    if (confirm && !window.confirm(`Delete ${path}? You can undo this action.`)) return null
    let result: ExplorerMutation
    try {
      result = { ...await post<Omit<ExplorerMutation, 'operation'>>('/api/workspace/delete', { path }), operation: 'delete' }
    } catch (error) {
      if (!(error instanceof ApiError) || error.detail?.type !== 'hidden_contents') throw error
      const count = Number(error.detail.hidden_count || 0)
      if (!window.confirm(`${path} also contains ${count} item(s) hidden from this explorer. Move the entire folder to recoverable trash?`)) return null
      result = { ...await post<Omit<ExplorerMutation, 'operation'>>('/api/workspace/delete', { path, confirm_hidden: true }), operation: 'delete' }
    }
    await applied(result, recordUndo ? { mode: 'restore', token: result.undo_token!, path } : null)
    return result
  }

  const transfer = async (operation: 'copy' | 'move', source: string, parent: string, name?: string): Promise<ExplorerMutation | null> => {
    if (!canMutate(source)) return null
    const result = { ...await post<Omit<ExplorerMutation, 'operation'>>(`/api/workspace/${operation}`,
      { source, parent, ...(name === undefined ? {} : { name }) }), operation }
    await applied(result, operation === 'move'
      ? { mode: 'move', source: result.path, path: source }
      : { mode: 'delete', path: result.path })
    if (operation === 'move' && clipboard?.mode === 'cut' && clipboard.path === source) setClipboard(null)
    return result
  }

  const run = async (work: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true)
    setFeedback('')
    try { await work() } catch (error) { setFeedback(`Error: ${String(error)}`) }
    finally { setBusy(false); setMenu(null) }
  }

  const paste = (parent: string) => {
    if (!clipboard) return
    void run(() => transfer(clipboard.mode === 'cut' ? 'move' : 'copy', clipboard.path, parent))
  }

  const submitDialog = () => {
    if (!dialog) return
    const current = dialog
    void run(async () => {
      if (current.mode === 'rename') {
        await transfer('move', current.entry!.path, current.parent, current.name)
      } else {
        const result = { ...await post<Omit<ExplorerMutation, 'operation'>>('/api/workspace/create',
          { parent: current.parent, name: current.name, kind: current.mode }), operation: 'create' as const }
        await applied(result, { mode: 'delete', path: result.path })
        if (current.mode === 'file') openFile(result.path)
      }
      setDialog(null)
    })
  }

  const undoLast = () => {
    if (!undo) return
    const action = undo
    void run(async () => {
      if (action.mode === 'restore') {
        const result = { ...await post<Omit<ExplorerMutation, 'operation'>>('/api/workspace/restore', { undo_token: action.token }), operation: 'restore' as const }
        await applied(result, null)
      } else if (action.mode === 'move') {
        if (await transfer('move', action.source, parentOf(action.path), nameOf(action.path))) setUndo(null)
      } else {
        if (await remove(action.path, false, false)) setUndo(null)
      }
    })
  }

  const choose = (action: string, entry: Entry | null) => {
    setMenu(null)
    if (action === 'new-file' || action === 'new-folder') {
      setDialog({ mode: action === 'new-file' ? 'file' : 'folder',
        parent: entry?.kind === 'folder' ? entry.path : entry ? parentOf(entry.path) : '', name: '' })
    } else if (action === 'rename' && entry) {
      setDialog({ mode: 'rename', parent: parentOf(entry.path), entry, name: entry.name })
    } else if (action === 'open' && entry?.kind === 'file') openFile(entry.path)
    else if (action === 'ask-ai' && entry?.kind === 'file') askAI(entry.path)
    else if (action === 'copy' && entry) { setClipboard({ path: entry.path, mode: 'copy' }); setFeedback(`Copied: ${entry.path}`) }
    else if (action === 'cut' && entry) { setClipboard({ path: entry.path, mode: 'cut' }); setFeedback(`Cut: ${entry.path}`) }
    else if (action === 'paste') paste(entry?.kind === 'folder' ? entry.path : entry ? parentOf(entry.path) : '')
    else if (action === 'duplicate' && entry) void run(() => transfer('copy', entry.path, parentOf(entry.path)))
    else if (action === 'delete' && entry) void run(async () => { await remove(entry.path) })
    else if (action === 'copy-path' && entry) void run(async () => { await navigator.clipboard.writeText(entry.path); setFeedback(`Copied path: ${entry.path}`) })
    else if (action === 'filter') setFilterOpen(true)
    else if (action === 'hide-samples') setHideSamples(current => !current)
    else if (action === 'refresh') void run(refresh)
    else if (action === 'collapse') setCollapseKey(value => value + 1)
  }

  const keyboard = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || dialog) return
    if (event.key === 'Escape') { setMenu(null); setSelected(null); return }
    if (event.key === 'F2' && selected) { event.preventDefault(); choose('rename', selected) }
    else if (event.key === 'Delete' && selected) { event.preventDefault(); choose('delete', selected) }
    else if ((event.ctrlKey || event.metaKey) && selected && event.key.toLowerCase() === 'c') { event.preventDefault(); choose('copy', selected) }
    else if ((event.ctrlKey || event.metaKey) && selected && event.key.toLowerCase() === 'x') { event.preventDefault(); choose('cut', selected) }
    else if ((event.ctrlKey || event.metaKey) && clipboard && event.key.toLowerCase() === 'v') {
      event.preventDefault(); paste(selected?.kind === 'folder' ? selected.path : selected ? parentOf(selected.path) : '')
    }
  }

  const dragStart = (event: DragEvent, entry: Entry) => {
    event.dataTransfer.setData('application/x-plc-workspace-path', entry.path)
    event.dataTransfer.effectAllowed = 'move'
    setSelected(entry)
  }
  const drop = (event: DragEvent, parent: string) => {
    event.preventDefault()
    event.stopPropagation()
    const source = event.dataTransfer.getData('application/x-plc-workspace-path')
    if (source && source !== parent) void run(() => transfer('move', source, parent))
  }

  const renderTree = (items: TreeNode[]) => <div className="tree-list">{items.map(node => node.kind === 'folder'
    ? <details key={`${collapseKey}:${node.path}`} className="tree-folder" open={query ? true : undefined}>
      <summary draggable onDragStart={event => dragStart(event, node)} onDragOver={event => event.preventDefault()}
        onDrop={event => drop(event, node.path)} onClick={() => setSelected(node)} onContextMenu={event => showMenu(event, node)}
        className={selected?.path === node.path ? 'selected' : ''}>
        <span>▸ {node.name}</span><button type="button" className="tree-more" aria-label={`Actions for ${node.path}`}
          onClick={event => { event.preventDefault(); event.stopPropagation(); showMenu(event, node) }}>⋯</button>
      </summary>{renderTree(node.children || [])}</details>
    : <div key={node.path} className={`tree-file-row${selected?.path === node.path ? ' selected' : ''}${clipboard?.mode === 'cut' && clipboard.path === node.path ? ' cut' : ''}`}
      onContextMenu={event => showMenu(event, node)}>
      <button type="button" className="tree-file" draggable onDragStart={event => dragStart(event, node)}
        onClick={() => { setSelected(node); openFile(node.path) }}><span className="file-icon">{node.name.endsWith('.st') ? 'ST' : '◇'}</span>{node.name}</button>
      <button type="button" className="tree-more" aria-label={`Actions for ${node.path}`}
        onClick={event => showMenu(event, node)}>⋯</button>
    </div>)}</div>

  const menuItems: [string, string][] = menu?.entry?.kind === 'file'
    ? [['open', 'Open'], ['ask-ai', '用AI询问此文件'], ['new-file', 'New file here'], ['new-folder', 'New folder here'],
      ['rename', 'Rename · F2'], ['duplicate', 'Duplicate'], ['copy', 'Copy · Ctrl+C'], ['cut', 'Cut · Ctrl+X'],
      ['paste', 'Paste · Ctrl+V'], ['copy-path', 'Copy relative path'], ['delete', 'Delete']]
    : menu?.entry?.kind === 'folder'
      ? [['new-file', 'New file'], ['new-folder', 'New folder'], ['rename', 'Rename · F2'], ['duplicate', 'Duplicate'],
        ['copy', 'Copy · Ctrl+C'], ['cut', 'Cut · Ctrl+X'], ['paste', 'Paste · Ctrl+V'], ['copy-path', 'Copy relative path'], ['delete', 'Delete']]
      : [['new-file', 'New file'], ['new-folder', 'New folder'], ['paste', 'Paste · Ctrl+V'],
        ['filter', 'Filter files'], ['hide-samples', `${hideSamples ? '✓ ' : ''}Hide examples/tests`],
        ['refresh', 'Refresh'], ['collapse', 'Collapse all']]

  return <section className="file-explorer" tabIndex={0} onKeyDown={keyboard}>
    <div className="file-toolbar">
      <span title={workspace}>{workspaceName}</span>
      <button type="button" className="file-primary-action" title="New file" aria-label="New file" onClick={() => choose('new-file', null)}>＋</button>
      <button type="button" className="file-primary-action" title="New folder" aria-label="New folder" onClick={() => choose('new-folder', null)}>▣</button>
      <button type="button" title="More file actions" aria-label="More file actions" aria-haspopup="menu"
        aria-expanded={Boolean(menu && menu.entry === null)} onClick={showToolbarMenu}>⋯</button>
    </div>
    {filterOpen && <div className="file-filter"><input ref={filterRef} aria-label="Filter files" placeholder="Filter files and folders…" value={query}
      onChange={event => { setQuery(event.target.value); setSelected(null) }}
      onKeyDown={event => { if (event.key === 'Escape') { setFilterOpen(false); setQuery('') } }} />
      <button type="button" aria-label="Close filter" title="Close filter" onClick={() => { setFilterOpen(false); setQuery('') }}>×</button></div>}
    <div className="file-explorer-content" onContextMenu={event => showMenu(event, null)}
      onDragOver={event => event.preventDefault()} onDrop={event => drop(event, '')}>
      {shown.length ? renderTree(shown) : <div className="file-empty">No matching files. Right-click here to create one.</div>}
    </div>
    <div className="file-explorer-footer">{undo && <button type="button" onClick={undoLast} disabled={busy}>Undo last change</button>}
      {clipboard && <span>{clipboard.mode === 'cut' ? 'Cut' : 'Copied'}: {nameOf(clipboard.path)}</span>}</div>
    {feedback && <div className="file-feedback" role="status">{feedback}</div>}
    {menu && <div className="file-menu" role="menu" style={{ left: Math.max(8, menu.x), top: Math.max(8, menu.y) }}>
      {menuItems.filter(([key]) => key !== 'paste' || clipboard).map(([key, label]) => <button key={key} type="button"
        role="menuitem" disabled={busy} onClick={() => choose(key, menu.entry)}>{label}</button>)}
    </div>}
    {dialog && <div className="file-dialog-backdrop"><div className="file-dialog" role="dialog" aria-modal="true"
      aria-label={dialog.mode === 'rename' ? 'Rename item' : `New ${dialog.mode}`}>
      <strong>{dialog.mode === 'rename' ? 'Rename' : `New ${dialog.mode}`}</strong><small>{dialog.parent || workspace}</small>
      <input autoFocus aria-label="Name" value={dialog.name} onChange={event => setDialog({ ...dialog, name: event.target.value })}
        onKeyDown={event => { if (event.key === 'Enter') submitDialog(); if (event.key === 'Escape') setDialog(null) }} />
      <div><button type="button" onClick={() => setDialog(null)}>Cancel</button><button type="button" disabled={busy || !dialog.name.trim()}
        onClick={submitDialog}>{busy ? 'Working…' : 'Confirm'}</button></div>
    </div></div>}
  </section>
}
