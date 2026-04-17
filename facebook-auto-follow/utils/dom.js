/**
 * Parse HTML from browser snapshot to find elements.
 * Uses simple regex-based parsing (no DOMParser dependency in Node).
 */

/**
 * Find all "Theo dõi" buttons that are clickable (not already following).
 * Returns array of { text, tag } — text is the button label, used as selector.
 */
export function findFollowButtons(html) {
  if (!html || typeof html !== 'string') return []
  const results = []

  // Match buttons that say exactly "Theo dõi" (not "Đang theo dõi")
  // Pattern: <button ...>Theo dõi</button> or <div ...>Theo dõi</div> etc.
  const buttonRegex = /<(button|div|span|a|role="button")[^>]*>([^<]*Theo dõi[^<]*)<\/\1>/gi
  let match
  while ((match = buttonRegex.exec(html)) !== null) {
    const tag = match[1].toLowerCase()
    const inner = match[2].trim()
    // Skip if already "Đang theo dõi"
    if (inner.includes('Đang theo dõi')) continue
    if (inner === 'Theo dõi') {
      results.push({ text: inner, tag })
    }
  }

  return results
}

/**
 * Find timestamp links in the feed that open post dialogs.
 * Returns array of { url, text } — text is the link text, used as selector.
 */
export function findPostTimestampLinks(html) {
  if (!html || typeof html !== 'string') return []
  const results = []
  // Match links to posts: /groups/.../posts/... or facebook.com/groups/.../posts/...
  const postLinkRegex = /href="([^"]*\/groups\/[^"]*\/posts\/[^"]*)"[^>]*>([^<]*)<\/a>/gi
  let match
  while ((match = postLinkRegex.exec(html)) !== null) {
    results.push({ url: match[1], text: match[2].trim() })
  }
  return results
}

/**
 * Check if a dialog/post modal is present in the HTML snapshot.
 */
export function isDialogOpen(html) {
  if (!html || typeof html !== 'string') return false
  // Facebook dialogs typically have role="dialog" or contain specific classes
  return html.includes('role="dialog"') || html.includes('aria-modal="true"')
}

/**
 * Find the "Đóng" (close) button in the dialog.
 * Returns { ariaLabel } — the aria-label value, used as selector.
 */
export function findCloseButton(html) {
  if (!html || typeof html !== 'string') return null
  // Try aria-label first (more specific)
  const closeRegex = /<(button|div|span|a)[^>]*aria-label="([^"]*Đóng[^"]*)"[^>]*>/gi
  let match = closeRegex.exec(html)
  if (match) return { ariaLabel: match[2] }

  // Fallback: button with "Đóng" text
  const btnCloseRegex = /<(button|div)[^>]*>[^<]*Đóng[^<]*<\/(button|div)>/gi
  match = btnCloseRegex.exec(html)
  if (match) return { ariaLabel: 'Đóng' }

  return null
}