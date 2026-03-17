// src/context/AuthContext.jsx
// =============================================================================
// Authentication state — access_token + refresh_token dual-token system.
//
// Token storage:
//   access_token  → RAM only (tokenStore.js module variable)
//   refresh_token → HttpOnly cookie (browser holds it, JS never sees it)
//   user profile  → localStorage (non-sensitive, just for display on reload)
//
// On startup:
//   silentRestore() → POST /api/auth/refresh (browser sends cookie) → new access_token in RAM
//   If cookie is gone/expired → user sees login screen
//
// On 401 during normal use:
//   apiClient.js silently calls /refresh → retries the original request
//   If refresh fails → onUnauthenticated() fires → _handleExpiry() clears state
//
// authVersion:
//   Increments on every successful login/register/restore.
//   useChat watches it as a useEffect dependency to re-fetch chats.
// =============================================================================
import {
  createContext, useContext, useState,
  useEffect, useCallback,
} from 'react'
import {
  login    as apiLogin,
  logout   as apiLogout,
  register as apiRegister,
} from '../services/chatService'
import { silentRestore, onUnauthenticated, resetSilentRestore } from '../services/apiClient'
import { clearAccessToken, getAccessToken } from '../services/tokenStore'
import { wsService }                        from '../services/websocketService'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,         setUser]        = useState(null)
  const [initialising, setInitialising]= useState(true)
  const [authLoading,  setAuthLoading] = useState(false)
  const [authError,    setAuthError]   = useState(null)
  const [authVersion,  setAuthVersion] = useState(0)

  const isAuthenticated = user !== null

  // ── Shared post-auth setup ──────────────────────────────────────────────────
  // Called after any successful authentication (login, register, silent restore).
  function _onAuthSuccess(newUser, accessToken) {
    setUser(newUser)
    localStorage.setItem('auth_user', JSON.stringify(newUser))  // profile only, no token
    wsService.connect(accessToken)
    setAuthVersion(v => v + 1)
  }

  // ── Called when a refresh attempt fails (session fully expired) ─────────────
  function _handleExpiry() {
    console.info('[AuthContext] Session expired')
    wsService.close()
    clearAccessToken()
    resetSilentRestore()   // allow the next login to call /refresh fresh
    localStorage.removeItem('auth_user')
    setUser(null)
    setAuthVersion(0)
  }

  // ── Silent restore on page load ─────────────────────────────────────────────
  // Uses the HttpOnly refresh cookie — no localStorage token read.
  useEffect(() => {
    async function restore() {
      try {
        const restoredUser = await silentRestore()  // sets accessToken in RAM internally
        if (restoredUser) {
          const token = getAccessToken()
          _onAuthSuccess(restoredUser, token)
        }
      } catch {
        // No valid session — show login screen
      } finally {
        setInitialising(false)
      }
    }
    restore()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Session expiry listener ─────────────────────────────────────────────────
  useEffect(() => {
    return onUnauthenticated(_handleExpiry)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Login ───────────────────────────────────────────────────────────────────
  const login = useCallback(async (credentials) => {
    setAuthError(null)
    setAuthLoading(true)
    try {
      // chatService.login() → POST /api/auth/login
      //   stores access_token in RAM, returns { access_token, user }
      //   server sets refresh_token HttpOnly cookie
      const result = await apiLogin(credentials)
      _onAuthSuccess(result.user, result.access_token)
      return result
    } catch (err) {
      const msg = err.status === 401
        ? 'Invalid email or password.'
        : err.message || 'Login failed. Please try again.'
      setAuthError(msg)
      throw err
    } finally {
      setAuthLoading(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Register ────────────────────────────────────────────────────────────────
  const register = useCallback(async ({ name, email, password }) => {
    setAuthError(null)
    setAuthLoading(true)
    try {
      // chatService.register() → POST /api/auth/register
      //   stores access_token in RAM, returns { access_token, user }
      //   server sets refresh_token HttpOnly cookie
      const result = await apiRegister({ name, email, password })
      _onAuthSuccess(result.user, result.access_token)
      return result
    } catch (err) {
      const msg =
        err.status === 409 ? 'An account with that email already exists.' :
        err.status === 400 ? (err.data?.message || 'Please check your details.') :
        err.message || 'Registration failed. Please try again.'
      setAuthError(msg)
      throw err
    } finally {
      setAuthLoading(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Logout ──────────────────────────────────────────────────────────────────
  const logout = useCallback(async () => {
    setAuthLoading(true)
    wsService.close()                   // close WS while access token still valid
    try {
      await apiLogout()                 // POST /api/auth/logout, clears access token from RAM
    } catch {
      clearAccessToken()                // ensure RAM is cleared even if server call fails
    }
    resetSilentRestore()               // allow the next login/page-load to restore fresh
    localStorage.removeItem('auth_user')
    setUser(null)
    setAuthVersion(0)
    setAuthLoading(false)
  }, [])

  const clearAuthError = useCallback(() => setAuthError(null), [])

  return (
    <AuthContext.Provider value={{
      user,
      isAuthenticated,
      initialising,
      authLoading,
      authError,
      authVersion,
      login,
      register,
      logout,
      clearAuthError,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}