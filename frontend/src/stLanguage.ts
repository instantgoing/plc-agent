import type * as monaco from 'monaco-editor'

let registered = false

export function registerStructuredText(instance: typeof monaco) {
  if (registered) return
  registered = true
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
