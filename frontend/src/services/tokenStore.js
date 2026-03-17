// src/services/tokenStore.js
// =============================================================================
// In-memory access token store — the ONLY place the access token lives.
//
// Never written to localStorage, sessionStorage, or any cookie.
// Lost on full page reload (by design) — silentRestore() recovers it via the
// HttpOnly refresh cookie.
//
// HMR note:
//   Vite Hot Module Replacement re-evaluates modules when files change, which
//   would reset _accessToken to null on every save during development.
//   import.meta.hot.decline() tells Vite to do a full page reload instead of
//   a hot swap when THIS specific module changes — preserving the token.
//   For all other modules (components, hooks, etc.) HMR still works normally.
// =============================================================================

// Opt out of HMR for this module only — a hot swap would reset _accessToken.
// Other modules continue to hot-reload as normal.
if (import.meta.hot) {
  import.meta.hot.decline()
}

let _accessToken = null

export const setAccessToken  = (token) => { _accessToken = token }
export const clearAccessToken = ()      => { _accessToken = null  }
export const getAccessToken  = ()       => _accessToken
export const hasAccessToken  = ()       => _accessToken !== null