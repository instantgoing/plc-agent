import { describe, expect, it, vi } from 'vitest'
import { readWatch, saveWatch, valueState, debugStore } from './debugStore'
import { observed } from './LiveLadder'

describe('online debugger', () => {
  it('persists only stable IDs and refuses malformed storage', () => {
    const values = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (key: string) => values.get(key), setItem: (key: string, value: string) => values.set(key, value) })
    saveWatch('workspace', ['main.motor1:running', 'main.motor2:running', 'main.motor1:running'])
    expect(readWatch('workspace')).toEqual(['main.motor1:running', 'main.motor2:running'])
    expect([...values.values()][0]).not.toContain('value')
    values.set('plc-watch:workspace', '{bad')
    expect(readWatch('workspace')).toEqual([])
  })
  it('marks stale and unavailable data explicitly', () => {
    expect(valueState({ value: true, last_updated: 100, state: 'normal' }, 'running', 2000, 1500)).toBe('stale')
    expect(valueState({ value: true, last_updated: 100, state: 'forced' }, 'offline', 200, 1500)).toBe('unavailable')
  })
  it('isolates instances and never evaluates unknown live inputs', () => {
    const state = { ...debugStore.getSnapshot(), latest: { 'main.motor1:running': { value: true, last_updated: 1, state: 'normal' }, 'main.motor2:running': { value: false, last_updated: 1, state: 'normal' } } }
    const source = { file: 'Main.st', line: 1 }
    expect(observed({ kind: 'contact', variable_id: 'main.motor1:running', source }, state)).toBe(true)
    expect(observed({ kind: 'contact', variable_id: 'main.motor2:running', source }, state)).toBe(false)
    expect(observed({ kind: 'not', child: { kind: 'contact', variable_id: 'unknown', source }, source }, state)).toBeUndefined()
    debugStore.update(state)
    debugStore.offline()
    expect(observed({ kind: 'contact', variable_id: 'main.motor1:running', source }, debugStore.getSnapshot())).toBeUndefined()
  })
})
