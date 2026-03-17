// src/components/layout/ProtectedRoute.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Guards a section of the app behind authentication.
//
// - While auth is still initialising (checking localStorage), shows a spinner
// - If not authenticated, renders <LoginPage />
// - If authenticated, renders the children
//
// Usage in App.jsx / main.jsx:
//   <ProtectedRoute>
//     <ChatLayout />
//   </ProtectedRoute>
// ─────────────────────────────────────────────────────────────────────────────
import { useAuth }           from '../../context/AuthContext'
import { LoginPage }         from '../../pages/LoginPage'
import { LoadingSpinner }    from '../ui/LoadingSpinner'

export function ProtectedRoute({ children }) {
  const { isAuthenticated, initialising } = useAuth()

  // Still reading the token from localStorage — show a brief full-screen spinner
  if (initialising) {
    return (
      <div className="min-h-screen bg-[#F4F0E6] flex items-center justify-center">
        <LoadingSpinner size={28} className="text-[#C96A42]" />
      </div>
    )
  }

  // Not logged in → show login/register screen
  if (!isAuthenticated) {
    return <LoginPage />
  }

  // Authenticated → render the protected content
  return children
}