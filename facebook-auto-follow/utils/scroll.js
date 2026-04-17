import { config } from '../config.js'
import { randDelay, randInt, randPick } from './random.js'
import { log } from './log.js'

/**
 * Perform a human-like scroll using keyboard Page Down.
 * Randomizes: number of presses, pause between each.
 *
 * @param {Function} callTool - async (toolName, args) => result
 * @param {number} times - how many Page Down presses (default random 1-3)
 */
export async function humanScrollDown(callTool, times = null) {
  const presses = times ?? randInt(1, 3)
  log(`Scrolling down (${presses} Page Down presses)...`)

  for (let i = 0; i < presses; i++) {
    await callTool('mcp__browsermcp__browser_press_key', { key: 'PageDown' })
    const delay = randDelay(config.scrollDelayMin, config.scrollDelayMax)
    await new Promise(r => setTimeout(r, delay))
  }
}

/**
 * Scroll up slightly (simulate reviewing).
 */
export async function humanScrollUp(callTool) {
  log('Scrolling up slightly...')
  await callTool('mcp__browsermcp__browser_press_key', { key: 'PageUp' })
  await new Promise(r => setTimeout(r, randDelay(500, 1000)))
}

/**
 * Random scroll — decides direction and magnitude randomly.
 */
export async function randomScroll(callTool) {
  const roll = Math.random()
  if (roll < 0.7) {
    await humanScrollDown(callTool)
  } else if (roll < 0.85) {
    await humanScrollUp(callTool)
  } else {
    // Just press ArrowDown for fine-grained scroll
    await callTool('mcp__browsermcp__browser_press_key', { key: 'ArrowDown' })
    await new Promise(r => setTimeout(r, randDelay(300, 800)))
  }
}