// src/pages/LoginPage.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Full-page login / register screen shown when the user is not authenticated.
// Matches Claude's clean, minimal aesthetic.
//
// - Toggles between "Sign in" and "Create account" mode
// - Calls useAuth().login() on submit
// - Displays server-side auth errors inline
// Uses useAuth().login() for sign-in and useAuth().register() for sign-up.
// Token handling is fully inside AuthContext — this component never touches
// tokens or localStorage.

import { useState } from 'react'
import { useAuth }  from '../context/AuthContext'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

export function LoginPage() {
  const [mode,     setMode]     = useState('login')   // 'login' | 'register'
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [name,     setName]     = useState('')         // register only

  const { login, register, authLoading, authError, clearAuthError } = useAuth()

  async function handleSubmit(e) {
    e.preventDefault()
    if (authLoading) return

    try {
      if (mode === 'login') {
        await login({ email, password })
      } else {
        await register({ name, email, password })
      }
      // On success: AuthContext sets user → ProtectedRoute shows ChatLayout
    } catch {
      // authError is already set in AuthContext — displayed below
    }
  }

  function handleFieldChange(setter) {
    return (e) => { clearAuthError(); setter(e.target.value) }
  }

  return (
    <div className="min-h-screen bg-[#F4F0E6] flex items-center justify-center px-4">
      <div className="w-full max-w-[380px]">

        {/* Logo + heading */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-11 h-11 rounded-2xl bg-[#C96A42] flex items-center
                          justify-center mb-4 shadow-sm">
            <span className="text-white text-lg font-semibold">C</span>
          </div>
          <h1 className="text-[22px] font-semibold text-[#1A1410] tracking-[-0.02em]">
            {mode === 'login' ? 'Welcome back' : 'Create your account'}
          </h1>
          <p className="text-[13px] text-[#8A7F72] mt-1">
            {mode === 'login'
              ? 'Sign in to continue to Claude'
              : 'Start chatting with Claude today'}
          </p>
        </div>

        {/* Form card */}
        <div className="bg-white rounded-2xl border border-[#E8E3D9]
                        shadow-[0_2px_12px_rgba(0,0,0,0.06)] p-6">
          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Name — register only */}
            {mode === 'register' && (
              <div>
                <label className={labelClass}>Full name</label>
                <input
                  type="text"
                  value={name}
                  onChange={handleFieldChange(setName)}
                  placeholder="Jane Smith"
                  required
                  className={inputClass}
                />
              </div>
            )}

            {/* Email */}
            <div>
              <label className={labelClass}>Email address</label>
              <input
                type="email"
                value={email}
                onChange={handleFieldChange(setEmail)}
                placeholder="you@example.com"
                required
                autoComplete="email"
                className={inputClass}
              />
            </div>

            {/* Password */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className={labelClass}>Password</label>
                {mode === 'login' && (
                  <button type="button"
                    className="text-[11px] text-[#C96A42] hover:underline">
                    Forgot password?
                  </button>
                )}
              </div>
              <input
                type="password"
                value={password}
                onChange={handleFieldChange(setPassword)}
                placeholder="••••••••"
                required
                minLength={8}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                className={inputClass}
              />
            </div>

            {/* Auth error */}
            {authError && (
              <div className="flex items-start gap-2 px-3 py-2.5 bg-red-50
                              border border-red-200 rounded-lg text-[12px] text-red-600">
                <span className="mt-px">⚠</span>
                <span>{authError}</span>
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={authLoading}
              className="w-full h-10 bg-[#C96A42] hover:bg-[#B85E38]
                         text-white text-[13px] font-semibold rounded-xl
                         transition-colors flex items-center justify-center gap-2
                         disabled:opacity-60 disabled:cursor-not-allowed mt-1"
            >
              {authLoading && <LoadingSpinner size={14} />}
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </button>
          </form>

          {/* Mode toggle */}
          <div className="mt-5 pt-4 border-t border-[#F0ECE6]
                          text-center text-[12px] text-[#8A7F72]">
            {mode === 'login' ? (
              <>Don't have an account?{' '}
                <button onClick={() => { setMode('register'); clearAuthError() }}
                  className="text-[#C96A42] font-medium hover:underline">
                  Sign up
                </button>
              </>
            ) : (
              <>Already have an account?{' '}
                <button onClick={() => { setMode('login'); clearAuthError() }}
                  className="text-[#C96A42] font-medium hover:underline">
                  Sign in
                </button>
              </>
            )}
          </div>
        </div>

        {/* Demo credentials hint */}
        <div className="mt-4 p-3 bg-white/60 rounded-xl border border-[#E8E3D9]
                        text-[11px] text-[#8A7F72] text-center">
          Demo: <span className="font-mono text-[#3D3530]">demo@example.com</span>{' / '}
          <span className="font-mono text-[#3D3530]">password123</span>
        </div>

        <p className="text-center text-[11px] text-[#C0B8AE] mt-4">
          By continuing you agree to our{' '}
          <span className="underline cursor-pointer">Terms</span> and{' '}
          <span className="underline cursor-pointer">Privacy Policy</span>
        </p>
      </div>
    </div>
  )
}

const labelClass = 'block text-[12px] font-medium text-[#3D3530] mb-1.5'
const inputClass  =
  'w-full h-9 px-3 bg-[#FAF8F5] border border-[#E8E3D9] rounded-lg ' +
  'text-[13px] text-[#1A1410] placeholder:text-[#C0B8AE] ' +
  'focus:outline-none focus:ring-2 focus:ring-[#C96A42]/20 ' +
  'focus:border-[#C96A42]/60 transition-all'