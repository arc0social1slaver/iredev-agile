// src/services/websocketService.js
// =============================================================================
// Low-level WebSocket client — singleton used by the whole app.
//
// Key design points:
//   - connect(token) takes the token explicitly so it always uses a fresh
//     token, not a stale one captured at module load time.
//   - Auto-reconnects on unexpected close (not on intentional close()).
//   - Emits _connected / _disconnected internal events so React knows the state.
//
// Client → Server frames:
//   { type: "ping" }
//   { type: "chat_message", chatId, messageId, content }
//   { type: "stop_stream",  chatId }
//
// Server → Client frames:
//   { type: "connected",  userId }
//   { type: "pong" }
//   { type: "token",      chatId, messageId, token }
//   { type: "done",       chatId, messageId }
//   { type: "artifact",   chatId, messageId, artifact }
//   { type: "error",      chatId?, messageId?, error }
// =============================================================================

// =============================================================================
// WebSocket client singleton.
//
// FIXES applied:
//   1. connect() is guarded: does nothing if a connection is already OPEN or
//      CONNECTING — stops duplicate connections firing on every React render.
//   2. Reconnect only happens for unexpected closes (code !== 1000 AND 1001).
//      Code 1001 = "going away" (page reload) — should not trigger reconnect.
//   3. Added isConnecting state to prevent race where connect() is called
//      twice before the socket reaches OPEN.
//   4. Debug logging added so connection lifecycle is visible in the browser
//      console.
// =============================================================================
 
// =============================================================================
// WebSocket client — uses the RAM access token (from tokenStore) for auth.
//
// The token is passed explicitly to connect() so:
//   - We always use the current token, not a stale captured value
//   - After a silent refresh, the reconnect loop re-reads the latest token
// =============================================================================

import { WS_BASE_URL, WS_RECONNECT_DELAY_MS } from '../config/env'
import { getAccessToken } from './tokenStore'

// HMR: decline hot swap so the wsService singleton and its open
// connection survive file saves during development.
if (import.meta.hot) {
  import.meta.hot.decline()
}


export class WebSocketService {
  constructor() {
    this._socket          = null
    this._handlers        = {}
    this._reconnectTimer  = null
    this._shouldReconnect = false
    this._token           = null
  }

  /**
   * Open the WebSocket connection.
   * Safe to call multiple times — does nothing if already OPEN or CONNECTING.
   *
   * @param {string} token  Access token — stored here for reconnect use.
   */
  connect(token) {
    if (!token) {
      console.warn('[WS] connect() called without token — skipping')
      return
    }

    const state = this._socket?.readyState
    if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) {
      console.debug('[WS] Already connected/connecting — skipping duplicate connect()')
      return
    }

    this._token           = token
    this._shouldReconnect = true
    this._openSocket()
  }

  /**
   * Close the connection permanently (no auto-reconnect).
   * Called on logout.
   */
  close() {
    this._shouldReconnect = false
    this._token           = null
    clearTimeout(this._reconnectTimer)
    if (this._socket) {
      this._socket.close(1000, 'Client logout')
      this._socket = null
    }
  }

  /** Register a handler. Returns an unsubscribe function. */
  on(eventType, handler) {
    if (!this._handlers[eventType]) this._handlers[eventType] = new Set()
    this._handlers[eventType].add(handler)
    return () => this._handlers[eventType]?.delete(handler)
  }

  /** Send a JSON payload. Warns if the socket is not open. */
  send(payload) {
    if (this._socket?.readyState === WebSocket.OPEN) {
      this._socket.send(JSON.stringify(payload))
    } else {
      console.warn('[WS] Cannot send — not connected. readyState:',
        this._socket?.readyState, 'Payload:', payload)
    }
  }

  sendChatMessage(chatId, messageId, content) {
    this.send({ type: 'chat_message', chatId, messageId, content })
  }

  stopStream(chatId) {
    this.send({ type: 'stop_stream', chatId })
  }

  ping() { this.send({ type: 'ping' }) }

  get isConnected() {
    return this._socket?.readyState === WebSocket.OPEN
  }

  // ---------------------------------------------------------------------------
  _openSocket() {
    // Always use the latest access token from RAM for reconnects.
    // If a silent refresh happened between disconnects, getAccessToken()
    // returns the new one rather than the stale one stored in this._token.
    const token = getAccessToken() || this._token
    if (!token) {
      console.warn('[WS] No access token available — cannot open socket')
      return
    }
    this._token = token   // keep _token in sync for close() check

    const url = `${WS_BASE_URL}/ws?token=${encodeURIComponent(token)}`
    console.info('[WS] Connecting to', url.replace(/token=.+/, 'token=<redacted>'))
    this._socket = new WebSocket(url)

    this._socket.onopen = () => {
      console.info('[WS] Connected ✓')
      this._emit('_connected', {})
    }

    this._socket.onmessage = (event) => {
      let msg
      try { msg = JSON.parse(event.data) }
      catch (err) { console.error('[WS] Bad frame:', event.data, err); return }
      console.debug('[WS] ←', msg.type, msg)
      this._emit(msg.type, msg)
    }

    this._socket.onclose = (event) => {
      console.info(`[WS] Closed code=${event.code} reason="${event.reason}"`)
      this._emit('_disconnected', { code: event.code })

      const shouldReconnect = (
        this._shouldReconnect &&
        event.code !== 1000 &&   // intentional close
        event.code !== 1001 &&   // page navigation
        event.code !== 1008      // policy violation (bad token — don't retry same token)
      )

      if (shouldReconnect) {
        console.info(`[WS] Reconnecting in ${WS_RECONNECT_DELAY_MS}ms…`)
        this._reconnectTimer = setTimeout(
          () => this._openSocket(),
          WS_RECONNECT_DELAY_MS,
        )
      }
    }

    this._socket.onerror = () => {
      console.error('[WS] Socket error')
      this._emit('_error', {})
    }
  }

  _emit(eventType, payload) {
    this._handlers[eventType]?.forEach(handler => {
      try { handler(payload) }
      catch (err) { console.error(`[WS] Handler threw for "${eventType}":`, err) }
    })
  }
}

export const wsService = new WebSocketService()