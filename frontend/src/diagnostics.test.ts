import { describe, expect, it } from 'vitest'
import { hasDirtyConflict, monacoMarkers } from './diagnostics'
import { pathLink } from './api'

describe('diagnostic and conflict mapping', () => {
  it('maps compiler locations to Monaco markers', () => {
    expect(monacoMarkers([{ file: 'Main.st', line: 18, column: 7, severity: 'error', message: 'Undefined Motor' }])[0])
      .toMatchObject({ startLineNumber: 18, startColumn: 7, endColumn: 8, severity: 8 })
  })
  it('protects dirty content after an external version change', () => {
    expect(hasDirtyConflict('mine', 'before', 'remote', 'old')).toBe(true)
    expect(hasDirtyConflict('before', 'before', 'remote', 'old')).toBe(false)
  })
  it('recognizes source locations in assistant messages', () => {
    expect(pathLink('See src/FB_Motor.st:28')).toEqual({ path: 'src/FB_Motor.st', line: 28 })
  })
})
