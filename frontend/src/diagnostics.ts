import type { Diagnostic } from './api'

export function monacoMarkers(diagnostics: Diagnostic[]) {
  return diagnostics.map(item => ({
    startLineNumber: Math.max(1, item.line || 1),
    startColumn: Math.max(1, item.column || 1),
    endLineNumber: Math.max(1, item.end_line || item.line || 1),
    endColumn: Math.max(2, item.end_column || (item.column || 1) + 1),
    severity: item.severity === 'warning' ? 4 : item.severity === 'info' ? 2 : 8,
    message: item.message,
    code: item.code || undefined
  }))
}

export function hasDirtyConflict(content: string, savedContent: string, remoteVersion: string, savedVersion: string) {
  return content !== savedContent && remoteVersion !== savedVersion
}
