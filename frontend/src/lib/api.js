export const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

// The commit this page was built from (see vite.config.js). After a deploy, a tab left open would read the new
// API's data with the old code, so it reloads once to pick up the new build.
const BUILD = typeof __APP_BUILD__ === 'undefined' ? '' : __APP_BUILD__

function reloadIfRedeployed(res) {
  const server = res.headers.get('X-App-Build')
  if (!BUILD || !server || server === BUILD) return
  try {
    if (sessionStorage.getItem('reloadedForBuild') === server) return
    sessionStorage.setItem('reloadedForBuild', server)
  } catch {
    return
  }
  window.location.reload()
}

export async function getJson(path, params, signal) {
  const res = await fetch(`${API_BASE}${path}?${new URLSearchParams(params)}`, { signal })
  reloadIfRedeployed(res)
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
