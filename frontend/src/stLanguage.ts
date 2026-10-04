import type * as monaco from 'monaco-editor'

let registered = false

export function registerStructuredText(instance: typeof monaco) {
  if (registered) return
  registered = true
  const styles = getComputedStyle(document.documentElement)
  const color = (token: string) => styles.getPropertyValue(token).trim()
  const surface = color('--ui-surface-0')
  const surfaceRaised = color('--ui-surface-2')
  const text = color('--ui-text')
  const muted = color('--ui-text-subtle')
  const accent = color('--ui-accent')
  const border = color('--ui-border')
  instance.editor.defineTheme('plc-workbench', {
    base: 'vs-dark', inherit: true,
    rules: [
      { token: 'comment', foreground: muted.slice(1), fontStyle: 'italic' },
      { token: 'keyword', foreground: accent.slice(1) },
      { token: 'type', foreground: color('--ui-warning').slice(1) },
      { token: 'string', foreground: color('--ui-success').slice(1) },
      { token: 'number', foreground: color('--ui-warning').slice(1) },
    ],
    colors: {
      'editor.background': surface,
      'editor.foreground': text,
      'editorLineNumber.foreground': muted,
      'editorLineNumber.activeForeground': text,
      'editorCursor.foreground': accent,
      'editor.selectionBackground': `${accent}38`,
      'editor.lineHighlightBackground': surfaceRaised,
      'editorWidget.background': surfaceRaised,
      'editorWidget.border': border,
      'editorSuggestWidget.background': surfaceRaised,
      'editorSuggestWidget.border': border,
      'editorHoverWidget.background': surfaceRaised,
      'editorHoverWidget.border': border,
      'diffEditor.insertedTextBackground': `${accent}28`,
      'diffEditor.removedTextBackground': `${color('--ui-danger')}24`,
    },
  })
  instance.languages.register({ id: 'structured-text', extensions: ['.st'], aliases: ['Structured Text', 'ST'] })
  instance.languages.setMonarchTokensProvider('structured-text', {
    ignoreCase: true,
    keywords: ['PROGRAM', 'END_PROGRAM', 'FUNCTION_BLOCK', 'END_FUNCTION_BLOCK', 'FUNCTION', 'END_FUNCTION',
      'VAR', 'VAR_INPUT', 'VAR_OUTPUT', 'VAR_IN_OUT', 'VAR_GLOBAL', 'END_VAR', 'IF', 'THEN', 'ELSIF', 'ELSE',
      'END_IF', 'CASE', 'OF', 'END_CASE', 'FOR', 'TO', 'BY', 'DO', 'END_FOR', 'WHILE', 'END_WHILE',
      'REPEAT', 'UNTIL', 'END_REPEAT', 'RETURN', 'AT', 'AND', 'OR', 'NOT', 'XOR', 'MOD'],
    tokenizer: { root: [
      [/\/\/.*$/, 'comment'],
      [/\(\*/, 'comment', '@comment'],
      [/'.*?'/, 'string'],
      [/\b(?:TRUE|FALSE)\b/, 'number'],
      [/\b(?:BOOL|INT|DINT|REAL|TIME|STRING|WORD|BYTE)\b/, 'type'],
      [/\b\d+(?:\.\d+)?\b/, 'number'],
      [/%[IQM][A-Z]*[\d.]+/i, 'number'],
      [/[A-Za-z_][\w]*/, { cases: { '@keywords': 'keyword', '@default': 'identifier' } }],
      [/:=|=>|<=|>=|<>|[+\-*/=<>]/, 'operator']
    ], comment: [[/[^*]+/, 'comment'], [/\*\)/, 'comment', '@pop'], [/\*/, 'comment']] }
  })
}
