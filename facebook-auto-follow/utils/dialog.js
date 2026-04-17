import { config } from '../config.js'
import { randDelay } from './random.js'
import { log } from './log.js'
import { isDialogOpen, findCloseButton } from './dom.js'

/**
 * Wait for dialog to open by repeatedly snapshotting.
 * Times out after ~15s.
 */
export async function waitForDialog(callTool, timeoutMs = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const snapshot = await callTool('mcp__browsermcp__browser_snapshot', {})
    const html = snapshot.html ?? ''
    if (isDialogOpen(html)) {
      log('Dialog detected')
      return true
    }
    await new Promise(r => setTimeout(r, 500))
  }
  throw new Error('Dialog did not open within timeout')
}

/**
 * Close the open dialog.
 * Tries close button first, falls back to Escape key.
 */
export async function closeDialog(callTool) {
  const snapshot = await callTool('mcp__browsermcp__browser_snapshot', {})
  const html = snapshot.html ?? ''

  const closeBtn = findCloseButton(html)
  if (closeBtn && closeBtn.ref) {
    await callTool('mcp__browsermcp__browser_click', { element: 'close dialog', ref: closeBtn.ref })
  } else {
    // Fallback: press Escape
    log('No close button found, pressing Escape')
    await callTool('mcp__browsermcp__browser_press_key', { key: 'Escape' })
  }

  // Wait a moment for dialog to dismiss
  await new Promise(r => setTimeout(r, randDelay(500, 1000)))

  // Verify dialog is actually gone
  const verifySnapshot = await callTool('mcp__browsermcp__browser_snapshot', {})
  const verifyHtml = verifySnapshot.html ?? ''
  if (isDialogOpen(verifyHtml)) {
    // Try pressing Escape as fallback if close button didn't work
    log('Dialog still open, pressing Escape as fallback')
    await callTool('mcp__browsermcp__browser_press_key', { key: 'Escape' })
    await new Promise(r => setTimeout(r, randDelay(500, 1000)))
  }
}