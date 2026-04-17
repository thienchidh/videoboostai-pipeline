/**
 * Parse HTML from browser snapshot to find elements.
 * Uses simple regex-based parsing (no DOMParser dependency in Node).
 */

/**
 * Find all "Theo dõi" buttons that are clickable (not already following).
 * Returns array of element identifiers {tag, text, ref} for clicking.
 */
export function findFollowButtons(html) {
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
    // Skip if contains "Đang theo dõi" anywhere
    if (inner === 'Theo dõi') {
      results.push({ tag, text: inner, raw: match[0] })
    }
  }

  return results
}

/**
 * Find timestamp links in the feed that open post dialogs.
 * These are typically <a> tags with href containing /groups/{id}/posts/{postId}
 */
export function findPostTimestampLinks(html) {
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
  // Facebook dialogs typically have role="dialog" or contain specific classes
  return html.includes('role="dialog"') || html.includes('aria-modal="true"')
}

/**
 * Find the "Đóng" (close) button in the dialog.
 */
export function findCloseButton(html) {
  // Close button can be a div with "Đóng" text or an X icon button
  const closeRegex = /<(button|div|span|a)[^>]*aria-label="([^"]*Đóng[^"]*)"[^>]*>/gi
  let match = closeRegex.exec(html)
  if (match) return { ariaLabel: match[2], raw: match[0] }

  // Fallback: button with "Đóng" text
  const btnCloseRegex = /<(button|div)[^>]*>[^<]*Đóng[^<]*<\/(button|div)>/gi
  match = btnCloseRegex.exec(html)
  if (match) return { text: 'Đóng', raw: match[0] }

  return null
}