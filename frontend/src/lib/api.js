// In production the backend is served from the same site under /api (Vercel Services); in local dev it runs on :8000.
const DEFAULT_API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : ''
export const API_BASE = (import.meta.env.VITE_API_URL || DEFAULT_API_BASE).replace(/\/$/, '')

export async function getJson(path, params, signal) {
  const res = await fetch(`${API_BASE}${path}?${new URLSearchParams(params)}`, { signal })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`)
  return body
}
