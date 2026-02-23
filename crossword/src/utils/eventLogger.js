let events = []
let sessionStartTime = null

export function startSession(puzzleId) {
  sessionStartTime = Date.now()
  events = []
  logEvent('session_start', { puzzleId })
}

export function logEvent(type, data = {}) {
  events.push({
    type,
    timestamp: Date.now(),
    relativeMs: sessionStartTime ? Date.now() - sessionStartTime : 0,
    ...data,
  })
}

export function getEvents() {
  return [...events]
}

export function downloadLog() {
  const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const now = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  a.href = url
  a.download = `crossword_log_${now}.json`
  a.click()
  URL.revokeObjectURL(url)
}
