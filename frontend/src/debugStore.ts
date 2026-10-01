import type { WebEvent } from './api'

export type DebugVariable = { id: string; name: string; owner: string; scope: string; type: string; address?: string; available: boolean; forceable: boolean; file: string; line: number }
export type Sample = { t_ms: number; timestamp: number; values: Record<string, number | boolean> }
export type TraceMeta = { session_id: string | null; state: string; signals: { variable_id: string; type: string }[]; sample_interval_ms: number; capacity: number; sample_count: number }
export type DebugState = { runtime: string; consistency: string; timestamp: number; interval_ms: number; stale_after_ms: number; program_id: string | null; program?: { source_file: string }; forced: Record<string, unknown>; latest: Record<string, { value: unknown; state: string; last_updated: number | null }>; trace: TraceMeta; trace_sample?: Sample; poll_latency_ms: number }
const initial: DebugState = { runtime: 'offline', consistency: 'unknown', timestamp: 0, interval_ms: 250, stale_after_ms: 1500, program_id: null, forced: {}, latest: {}, trace: { session_id: null, state: 'idle', signals: [], sample_interval_ms: 100, capacity: 10000, sample_count: 0 }, poll_latency_ms: 0 }
let state = initial
const listeners = new Set<() => void>()
export const debugStore = {
  getSnapshot: () => state,
  subscribe: (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn) } },
  update: (event: WebEvent | DebugState) => {
    state = event as DebugState
    listeners.forEach(fn => fn())
  },
  offline: () => {
    state = { ...state, runtime: 'offline', latest: Object.fromEntries(Object.entries(state.latest).map(([id, v]) => [id, { ...v, value: null, state: 'unavailable' }])), trace: { ...state.trace, state: state.trace.state === 'recording' ? 'interrupted' : state.trace.state } }
    listeners.forEach(fn => fn())
  }
}
export function valueState(value: DebugState['latest'][string] | undefined, runtime: string, now: number, staleMs: number) {
  if (!value) return 'unavailable'
  if (runtime !== 'running') return value.state === 'unresolved' ? 'unresolved' : 'unavailable'
  if (value.last_updated && now - value.last_updated > staleMs) return 'stale'
  return value.state
}
export function readWatch(workspace: string): string[] {
  try { const raw: unknown = JSON.parse(localStorage.getItem(`plc-watch:${workspace}`) || '[]'); return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string').slice(0, 100) : [] } catch { return [] }
}
export function saveWatch(workspace: string, ids: string[]) { localStorage.setItem(`plc-watch:${workspace}`, JSON.stringify([...new Set(ids)].slice(0, 100))) }
