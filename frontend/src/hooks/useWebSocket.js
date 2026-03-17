// src/hooks/useWebSocket.js
// =============================================================================
// React hook that manages the WebSocket lifecycle.
//
// IMPORTANT TIMING: The WS connection must be opened AFTER the user logs in
// so a valid token is available. This hook does NOT call connect() itself —
// instead the caller (useChat / AuthContext) calls wsService.connect(token)
// at the right moment (after login succeeds).
//
// This hook's only job is to:
//   1. Register all event handlers on mount (using refs to avoid stale closures)
//   2. Unregister them on unmount
//
// Usage in useChat.js:
//   useWebSocket({ onToken, onDone, onError, onArtifact, onConnected })
// =============================================================================

import { useEffect, useRef } from 'react'
import { wsService }         from '../services/websocketService'

export function useWebSocket({
  onToken, onDone, onError,
  onArtifact, onArtifactRevised, onArtifactAccepted, onArtifactTimeout,
  onRevisionStart,
  onConnected, onDisconnected,
}) {
  // Keep all callbacks in refs so handlers registered once always call
  // the latest version (avoids stale closures without re-registering)
  const refs = {
    onToken:             useRef(onToken),
    onDone:              useRef(onDone),
    onError:             useRef(onError),
    onArtifact:          useRef(onArtifact),
    onArtifactRevised:   useRef(onArtifactRevised),
    onArtifactAccepted:  useRef(onArtifactAccepted),
    onArtifactTimeout:   useRef(onArtifactTimeout),
    onRevisionStart:     useRef(onRevisionStart),
    onConnected:         useRef(onConnected),
    onDisconnected:      useRef(onDisconnected),
  }

  // Sync refs on every render
  Object.entries({
    onToken, onDone, onError,
    onArtifact, onArtifactRevised, onArtifactAccepted, onArtifactTimeout,
    onRevisionStart, onConnected, onDisconnected,
  }).forEach(([k, v]) => { refs[k].current = v }) 

  // Register once, unregister on unmount
  useEffect(() => {
    const off = [
      wsService.on('token',             (m) => refs.onToken.current?.(m)),
      wsService.on('done',              (m) => refs.onDone.current?.(m)),
      wsService.on('error',             (m) => refs.onError.current?.(m)),
      wsService.on('artifact',          (m) => refs.onArtifact.current?.(m)),
      wsService.on('artifact_revised',  (m) => refs.onArtifactRevised.current?.(m)),
      wsService.on('artifact_accepted', (m) => refs.onArtifactAccepted.current?.(m)),
      wsService.on('artifact_timeout',  (m) => refs.onArtifactTimeout.current?.(m)),
      wsService.on('revision_start',    (m) => refs.onRevisionStart.current?.(m)),
      wsService.on('connected',         (m) => refs.onConnected.current?.(m)),
      wsService.on('_connected',        (m) => refs.onConnected.current?.(m)),
      wsService.on('_disconnected',     (m) => refs.onDisconnected.current?.(m)),
    ]
    return () => off.forEach(fn => fn())
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
}