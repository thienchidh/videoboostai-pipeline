import { config } from '../config.js'

export function log(...args) {
  if (config.debugMode) console.log('[fb-follow]', ...args)
}
