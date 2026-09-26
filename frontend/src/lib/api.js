export const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

export async function getJson(path, params, signal) {
  const res = await fetch(`${API_BASE}${path}?${new URLSearchParams(params)}`, { signal })
  const body = await res.json().catch(() => ({}))
  if (res.status === 429) {
    throw new Error('This app uses my Gemini API key and has reached its usage limit. Please try again in about 3 hours.')
  }
  if (!res.ok) {
    const error = new Error(body.detail || `Request failed (${res.status})`)
    error.status = res.status
    throw error
  }
  return body
}

// Research endpoints report their own reasons (a spent model quota, a filing that cannot be read) in `detail`.
export async function postJson(path, body, signal) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    signal,
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const error = new Error(data.detail || `Request failed (${res.status})`)
    error.status = res.status
    throw error
  }
  return data
}
