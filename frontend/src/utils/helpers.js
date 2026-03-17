// src/utils/helpers.js
// ─────────────────────────────────────────────────────────────────────────────
// Pure helper functions — no React, no side-effects.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Group an array of chat objects by their .date string.
 * Returns: { 'Today': [...], 'Yesterday': [...], 'Mar 12': [...] }
 */
export function groupByDate(chats) {
  return chats.reduce((groups, chat) => {
    const key = chat.date || 'Older'
    if (!groups[key]) groups[key] = []
    groups[key].push(chat)
    return groups
  }, {})
}

/**
 * Generate a short random ID string, e.g. "k7x2m9p".
 * Used to create temporary IDs for optimistic UI updates.
 */
export function uid() {
  return Math.random().toString(36).slice(2, 9)
}

/**
 * Format an ISO timestamp into a human-readable relative label.
 * e.g. "Today", "Yesterday", "Mar 12"
 *
 * @param {string|Date} timestamp
 * @returns {string}
 */
export function formatChatDate(timestamp) {
  if (!timestamp) return 'Today'
  const date = new Date(timestamp)
  const now  = new Date()

  const sameDay = (a, b) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth()    === b.getMonth()    &&
    a.getDate()     === b.getDate()

  if (sameDay(date, now)) return 'Today'

  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay(date, yesterday)) return 'Yesterday'

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}