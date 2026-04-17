#!/usr/bin/env node
import { loadState, saveState, initState, updateState } from './state.js'
import { config } from './config.js'
import { log } from './utils/log.js'
import { randDelay, randInt } from './utils/random.js'
import { findFollowButtons, findPostTimestampLinks } from './utils/dom.js'
import { humanScrollDown, randomScroll } from './utils/scroll.js'
import { clickWithRetry } from './utils/click.js'
import { waitForDialog, closeDialog } from './utils/dialog.js'

const [,, command, groupUrl] = process.argv

// ── CLI ─────────────────────────────────────────────────────────────────────

if (!command || !['start', 'resume', 'status'].includes(command)) {
  console.log('Usage: node index.js <start|resume|status> [groupUrl]')
  process.exit(1)
}

if (command === 'status') {
  const state = loadState()
  if (!state) {
    console.log('No state found. Run: node index.js start <groupUrl>')
  } else {
    console.log(JSON.stringify(state, null, 2))
  }
  process.exit(0)
}

if (!groupUrl) {
  console.error('Error: groupUrl required for start/resume')
  process.exit(1)
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Call a browser MCP tool and return the result.
 * NOTE: This must be replaced with actual MCP tool invocation when run
 * inside Claude Code. The script is designed to be called via a wrapper
 * that intercepts tool calls and routes them to mcp__browsermcp__ tools.
 */
async function callTool(toolName, args) {
  throw new Error('callTool must be replaced with actual MCP tool invoker — see index.js comments')
}

/**
 * Snapshot → parse HTML → find follow buttons → click each.
 * Returns number of successful follows.
 */
async function processFollowables(html, callTool) {
  const buttons = findFollowButtons(html)
  log(`Found ${buttons.length} "Theo dõi" buttons`)
  let followed = 0

  for (const btn of buttons) {
    const success = await clickWithRetry(btn.ref, callTool)
    if (success) followed++
  }
  return followed
}

/**
 * Main processing loop for one post: open dialog → follow author → follow commenters → close.
 */
async function processPost(postUrl, callTool) {
  log(`Processing post: ${postUrl}`)

  // Click the timestamp link to open dialog
  const snapshot0 = await callTool('mcp__browsermcp__browser_snapshot', {})
  const links = findPostTimestampLinks(snapshot0.html ?? '')
  const link = links.find(l => l.url === postUrl) || links[0]
  if (!link) {
    log(`Could not find timestamp link for ${postUrl}, skipping`)
    return 0
  }

  await clickWithRetry(link.ref, callTool)
  await waitForDialog(callTool)

  // Follow author
  const snapshot1 = await callTool('mcp__browsermcp__browser_snapshot', {})
  const authorFollowed = await processFollowables(snapshot1.html ?? '', callTool)

  // Scroll comments and follow commenters
  let totalFollowed = authorFollowed
  let noNewButtonsCount = 0

  while (noNewButtonsCount < 3) {
    const beforeCount = totalFollowed
    await humanScrollDown(callTool)
    await new Promise(r => setTimeout(r, randDelay(800, 1500)))

    const snap = await callTool('mcp__browsermcp__browser_snapshot', {})
    const thisBatch = await processFollowables(snap.html ?? '', callTool)
    totalFollowed += thisBatch

    if (thisBatch === 0) {
      noNewButtonsCount++
    } else {
      noNewButtonsCount = 0
    }
  }

  await closeDialog(callTool)
  return totalFollowed
}

/**
 * Main feed loop.
 */
async function runFeed(groupUrl, callTool, startFromLastPost = false) {
  // Navigate to group
  await callTool('mcp__browsermcp__browser_navigate', { url: groupUrl })
  await new Promise(r => setTimeout(r, 3000)) // Wait for feed to load

  const savedState = loadState()
  const state = (savedState && savedState.groupUrl === groupUrl)
    ? savedState
    : initState(groupUrl)

  let postIndex = 0
  let consecutiveEmpty = 0

  while (consecutiveEmpty < 5) {
    const snapshot = await callTool('mcp__browsermcp__browser_snapshot', {})
    const html = snapshot.html ?? ''
    const postLinks = findPostTimestampLinks(html)

    if (postLinks.length === 0) {
      consecutiveEmpty++
      log(`No posts found (attempt ${consecutiveEmpty}/5), scrolling...`)
      await randomScroll(callTool)
      continue
    }

    consecutiveEmpty = 0

    for (const link of postLinks.slice(postIndex)) {
      if (state.lastPostUrl && link.url === state.lastPostUrl) {
        log('Reached last saved post — resuming from next')
        postIndex++
        continue
      }

      // "Read" the post a bit before interacting
      await new Promise(r => setTimeout(r, randDelay(config.readDelayMin, config.readDelayMax)))

      try {
        const followed = await processPost(link.url, callTool)
        state.totalFollowed = (state.totalFollowed || 0) + followed
        state.lastPostUrl = link.url
        saveState(state)
        log(`Total followed so far: ${state.totalFollowed}`)
      } catch (e) {
        log(`Error processing post ${link.url}: ${e.message}`)
      }

      postIndex++
    }

    // Scroll to load more posts
    await randomScroll(callTool)
  }

  log('Reached end of feed. Done.')
  return state
}

// ── Run ────────────────────────────────────────────────────────────────────────────

let startFromLastPost = false
if (command === 'resume') {
  startFromLastPost = true
}

try {
  const finalState = await runFeed(groupUrl, callTool, startFromLastPost)
  console.log('Final state:', JSON.stringify(finalState, null, 2))
} catch (e) {
  console.error('Fatal error:', e.message)
  process.exit(1)
}