// src/services/chatService.js
// ─────────────────────────────────────────────────────────────────────────────
// All REST API calls related to conversations and messages.
//
// Every function maps 1-to-1 to a backend endpoint.
// Components never call apiClient directly — they go through here.
//
// Expected backend contract
// ─────────────────────────
//
//  GET    /api/chats                   → Chat[]
//  POST   /api/chats                   → Chat         body: { title }
//  DELETE /api/chats/:chatId           → { ok: true }
//
//  GET    /api/chats/:chatId/messages  → Message[]
//  POST   /api/chats/:chatId/messages  → Message      body: { role, content }
//
//  POST   /api/auth/login              → { token, user }  body: { email, password }
//  POST   /api/auth/logout             → { ok: true }
//
// Chat shape:    { id, title, date, createdAt }
// Message shape: { id, chatId, role, content, artifact?, createdAt }
// ─────────────────────────────────────────────────────────────────────────────


// =============================================================================
// REST API calls for auth, chats, and messages.
//
// Auth functions work with access_token (in RAM) + refresh_token (HttpOnly
// cookie). They never read or write localStorage — that's apiClient's job.
// =============================================================================
import { get, post, del } from './apiClient'
import { setAccessToken, clearAccessToken } from './tokenStore'

// ── Auth ──────────────────────────────────────────────────────────────────────

/**
 * POST /api/auth/login
 * Returns { access_token, user }.
 * The server also sets the refresh_token HttpOnly cookie in the response.
 * We store access_token in RAM via tokenStore.
 */
export async function login(credentials) {
  const result = await post('/api/auth/login', credentials)
  setAccessToken(result.access_token)   // RAM only — never localStorage
  return result                         // caller gets { access_token, user }
}

/**
 * POST /api/auth/logout
 * Server blacklists both tokens and clears the cookie.
 * We clear the RAM access token.
 */
export async function logout() {
  try {
    await post('/api/auth/logout', {})
  } finally {
    clearAccessToken()   // always clear from RAM even if server call fails
  }
}

/**
 * POST /api/auth/register
 * Same flow as login.
 */
export async function register(data) {
  const result = await post('/api/auth/register', data)
  setAccessToken(result.access_token)
  return result
}

// ── Chats ─────────────────────────────────────────────────────────────────────

export const fetchChats   = ()            => get('/api/chats')
export const createChat   = (title)       => post('/api/chats', { title })
export const deleteChat   = (chatId)      => del(`/api/chats/${chatId}`)
export const fetchMessages = (chatId)     => get(`/api/chats/${chatId}/messages`)
export const sendMessage   = (chatId, content) =>
  post(`/api/chats/${chatId}/messages`, { role: 'user', content })