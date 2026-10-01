import { memo } from 'react'
import type { DebugState } from './debugStore'
export type Source = { file: string; line: number }
export type Logic = { kind: string; symbol?: string; variable_id?: string; type?: string; value?: number | boolean; source: Source; children?: Logic[]; child?: Logic; left?: Logic; right?: Logic; operator?: string; timer_type?: string; pt?: string; q_id?: string; et_id?: string }
export type LadderIR = { status: string; file: string; rungs: { id: string; owner: string; logic: Logic; output: Logic; source: Source }[]; unsupported: (Source & { construct: string })[]; source_hash: string; semantics: string }
export function observed(node: Logic, state: DebugState): unknown {
  if (node.kind === 'constant') return node.value
  if (node.variable_id) { const v = state.latest[node.variable_id]; return v && ['normal', 'forced'].includes(v.state) ? v.value : undefined }
  if (node.kind === 'not' && node.child) { const v = observed(node.child, state); return typeof v === 'boolean' ? !v : undefined }
  if (node.children) { const vs = node.children.map(n => observed(n, state)); return vs.some(v => typeof v !== 'boolean') ? undefined : node.kind === 'series' ? vs.every(Boolean) : vs.some(Boolean) }
  if (node.kind === 'comparison' && node.left && node.right) { const a = observed(node.left, state), b = observed(node.right, state); if ((typeof a !== 'number' && typeof a !== 'boolean') || (typeof b !== 'number' && typeof b !== 'boolean')) return undefined; return node.operator === '=' ? a === b : node.operator === '<>' ? a !== b : node.operator === '<' ? a < b : node.operator === '>' ? a > b : node.operator === '<=' ? a <= b : a >= b }
  return undefined
}
function LogicNode({ node, state, live, jump, inverted = false }: { node: Logic; state: DebugState; live: boolean; jump: (s: Source) => void; inverted?: boolean }) {
  const active = live && observed(node, state) === true
  if (node.kind === 'not' && node.child) return <LogicNode node={node.child} state={state} live={live} jump={jump} inverted={!inverted} />
  if (node.children) return <div className={`logic-${node.kind} ${active ? 'energized' : ''}`}>{node.children.map((child, i) => <LogicNode key={i} node={child} state={state} live={live} jump={jump} />)}</div>
  const value = node.variable_id ? state.latest[node.variable_id] : undefined
  const conducting = inverted ? live && observed(node, state) === false : active
  if (node.kind === 'timer') return <button className="ladder-timer" onClick={() => jump(node.source)}><strong>{node.timer_type} {node.symbol}</strong><span>PT {node.pt}</span><span>ET {live ? String(state.latest[node.et_id!]?.value ?? 'UNAVAILABLE') + ' ms' : '—'}</span><span className={live && state.latest[node.q_id!]?.value === true ? 'energized' : ''}>Q {live ? String(state.latest[node.q_id!]?.value ?? 'UNAVAILABLE') : '—'}</span></button>
  return <button title={`${node.variable_id || node.kind} → ${node.source.file}:${node.source.line}`} className={`ladder-element ${conducting ? 'energized' : ''} ${value?.state === 'forced' ? 'is-forced' : ''}`} onClick={() => jump(node.source)}><span>{node.symbol || (node.kind === 'comparison' ? `${node.left?.symbol || node.left?.value} ${node.operator} ${node.right?.symbol || node.right?.value}` : String(node.value))}</span><strong>{node.kind === 'coil' ? '( )' : node.kind === 'comparison' ? '[≥]' : inverted ? '|/|' : '| |'}</strong>{value?.state === 'forced' && <small>FORCED</small>}</button>
}
export const LiveLadder = memo(function LiveLadder({ ir, state, live, jump }: { ir: LadderIR | null; state: DebugState; live: boolean; jump: (s: Source) => void }) {
  if (!ir) return <div className="empty-panel">Open an ST file to inspect its read-only Ladder.</div>
  return <div className="ladder-panel"><div className="ladder-caption">{ir.status.toUpperCase()} · {live ? 'LIVE OBSERVATIONS' : 'OFFLINE / HIGHLIGHT DISABLED'} · Read only</div>{ir.rungs.map(rung => <div className="ladder-rung" key={rung.id}><button className="rung-source" onClick={() => jump(rung.source)}>{rung.owner}:{rung.source.line}</button><div className="rung-rail"><LogicNode node={rung.logic} state={state} live={live} jump={jump} /><span className="rung-wire" /><LogicNode node={rung.output} state={state} live={live} jump={jump} /></div></div>)}{ir.unsupported.map((item, i) => <button className="ladder-unsupported" key={i} onClick={() => jump(item)}>Source fallback: {item.construct} · {item.file}:{item.line}</button>)}<small>{ir.semantics}</small></div>
})
export function ladderVariables(ir: LadderIR | null): string[] {
  const ids = new Set<string>()
  const walk = (node: Logic) => { if (node.variable_id) ids.add(node.variable_id); if (node.q_id) ids.add(node.q_id); if (node.et_id) ids.add(node.et_id); node.children?.forEach(walk); if (node.child) walk(node.child); if (node.left) walk(node.left); if (node.right) walk(node.right) }
  ir?.rungs.forEach(r => { walk(r.logic); walk(r.output) })
  return [...ids]
}
