const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function toJson(res) {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
  return data
}

export const getKeyStatus = () =>
  fetch('/api/key', { credentials: 'same-origin' }).then(toJson)

export const saveKey = (provider, apiKey) =>
  fetch('/api/key', {
    method: 'POST',
    headers: JSON_HEADERS,
    credentials: 'same-origin',
    body: JSON.stringify({ provider, api_key: apiKey }),
  }).then(toJson)

export const removeKey = () =>
  fetch('/api/key', { method: 'DELETE', credentials: 'same-origin' }).then(toJson)

export const getGame = () =>
  fetch('/api/game', { credentials: 'same-origin' }).then(toJson)

export const resetGame = (color) =>
  fetch('/api/game/reset', {
    method: 'POST',
    headers: JSON_HEADERS,
    credentials: 'same-origin',
    body: JSON.stringify(color ? { color } : {}),
  }).then(toJson)

export const undoMove = () =>
  fetch('/api/game/undo', { method: 'POST', credentials: 'same-origin' }).then(toJson)

/**
 * POST to a server-sent-events endpoint and dispatch each event to handlers.
 * handlers: { user_move, move, strategy, token, done, error }
 */
export async function streamSSE(url, body, handlers) {
  const res = await fetch(url, {
    method: 'POST',
    headers: JSON_HEADERS,
    credentials: 'same-origin',
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.error || `Request failed (${res.status})`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      let event = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim()
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data && handlers[event]) handlers[event](JSON.parse(data))
    }
  }
}
