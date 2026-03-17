// src/main.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Entry point — wraps the app in context providers then mounts it.
//
// Provider order matters:
//   AuthProvider  → must be outermost (ChatProvider needs auth state)
//   ChatProvider  → must be inside AuthProvider
//   App           → consumes both contexts
// ─────────────────────────────────────────────────────────────────────────────
import React                from 'react'
import ReactDOM             from 'react-dom/client'
import App                  from './App'
import { AuthProvider }     from './context/AuthContext'
import { ChatProvider }     from './context/ChatContext'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {/* Auth state (user, login, logout) available everywhere */}
    <AuthProvider>
      {/* Chat state (messages, sendMessage, etc.) available everywhere */}
      <ChatProvider>
        <App />
      </ChatProvider>
    </AuthProvider>
  </React.StrictMode>
)