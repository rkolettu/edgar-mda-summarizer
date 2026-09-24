export const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

export async function getJson(path, params, signal) {
  const res = await fetch(`${API_BASE}${path}?${new URLSearchParams(params)}`, { signal })
  const body = await res.json().catch(() => ({}))
  if (res.status === 429) {
    throw new Error('This app uses my Gemini API key and has reached its usage limit. Please try again in about 3 hours.')
  }
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`)
  return body
}
