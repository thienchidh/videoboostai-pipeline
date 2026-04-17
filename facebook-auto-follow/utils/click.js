import { config } from '../config.js'
import { randDelay, randInt } from './random.js'
import { log } from './log.js'

/**
 * Perform a human-like hover then click on an element by its ref.
 * Uses mcp__browsermcp__browser_hover then browser_click.
 * Adds randomized delay before and after.
 *
 * @param {string} ref - Element ref from browser snapshot
 * @param {Function} callTool - async (toolName, args) => result
 */
export async function humanClick(ref, callTool) {
  // Hover first
  await callTool('mcp__browsermcp__browser_hover', { element: 'hover target', ref })
  const hoverDelay = randDelay(config.hoverDelayMin, config.hoverDelayMax)
  log(`Hovering ${hoverDelay}ms...`)
  await new Promise(r => setTimeout(r, hoverDelay))

  // Click
  await callTool('mcp__browsermcp__browser_click', { element: 'click target', ref })

  const actionDelay = randDelay(config.actionDelayMin, config.actionDelayMax)
  log(`Clicked, waiting ${actionDelay}ms...`)
  await new Promise(r => setTimeout(r, actionDelay))
}

/**
 * Click retry wrapper — tries up to maxRetries times.
 */
export async function clickWithRetry(ref, callTool) {
  let lastError
  for (let i = 0; i < config.maxRetries; i++) {
    try {
      await humanClick(ref, callTool)
      return true
    } catch (e) {
      lastError = e
      log(`Click attempt ${i + 1} failed: ${e.message}`)
      if (i < config.maxRetries - 1) {
        const delay = randDelay(config.actionDelayMin, config.actionDelayMax)
        await new Promise(r => setTimeout(r, delay))
      }
    }
  }
  log(`Click failed after ${config.maxRetries} attempts: ${lastError.message}`)
  return false
}