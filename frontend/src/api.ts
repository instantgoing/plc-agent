export type TreeNode = { name: string; path: string; kind: 'file' | 'folder'; children?: TreeNode[] }
export type FileData = { path: string; content: string; version: string }
export type Diagnostic = { file: string; line: number; column: number; end_line?: number; end_column?: number; severity: string; message: string; code?: string | null }
export type WebEvent = { type: string; seq?: number; [key: string]: unknown }

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  const data = await response.json()
  if (!response.ok) {
    const detail = data.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `${response.status} ${response.statusText}`)
  }
  return data as T
}

export function post<T>(url: string, body: object = {}): Promise<T> {
  return api<T>(url, { method: 'POST', body: JSON.stringify(body) })
}

export function pathLink(text: string): { path: string; line: number } | null {
  const match = text.match(/((?:[\w.-]+\/)*[\w.-]+\.st):(\d+)/i)
  return match ? { path: match[1], line: Number(match[2]) } : null
}
