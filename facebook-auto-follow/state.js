import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const STATE_FILE = path.join(__dirname, 'state.json')

export function loadState() {
  if (!fs.existsSync(STATE_FILE)) return null
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'))
  } catch {
    return null
  }
}

export function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2))
}

export function initState(groupUrl) {
  return {
    groupUrl,
    lastPostUrl: null,
    totalFollowed: 0,
    lastRun: new Date().toISOString()
  }
}

// Note: Must not be called concurrently — no file locking
export function updateState(updates) {
  const current = loadState() || {}
  const next = { ...current, ...updates, lastRun: new Date().toISOString() }
  saveState(next)
  return next
}
