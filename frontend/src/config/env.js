// src/config/env.js
// ─────────────────────────────────────────────────────────────────────────────
// Central place for all environment-driven configuration.
//
// In development Vite exposes variables prefixed with VITE_ from your .env file.
// Copy .env.example → .env and fill in your backend URLs.
//
// Usage anywhere in the app:
//   import { API_BASE_URL, WS_BASE_URL } from '../config/env'
// ─────────────────────────────────────────────────────────────────────────────

/** Base URL for all REST API calls, e.g. "http://localhost:8000" */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

/** Base URL for WebSocket connections, e.g. "ws://localhost:8000" */
export const WS_BASE_URL =
  import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000'

/** How long (ms) to wait before declaring a REST request timed out */
export const REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_REQUEST_TIMEOUT_MS) || 30_000

/** How long (ms) to wait before trying to reconnect a dropped WebSocket */
export const WS_RECONNECT_DELAY_MS = 2_000