Now I have everything I need to write a thorough, well-structured guide covering everything used in this codebase.This is a comprehensive codebase. Let me write a thorough guide covering every concept used, grounded in the actual code.

Here's your complete guide to every React and WebSocket concept used in this project, organized from fundamentals to advanced patterns.

---

## Part 1 — React foundations

### How React renders UI

React is a **declarative UI library**. Instead of manually manipulating the DOM, you describe what the UI should look like given some state, and React figures out how to update the real DOM.

```jsx
// Declarative: "when streaming is true, show a Stop button"
{streaming
  ? <button onClick={cancelStream}>Stop</button>
  : <button onClick={submit}>Send</button>}
```

When `streaming` changes from `false` to `true`, React automatically swaps the buttons. You never touch the DOM directly.

### useState — local component state

The most fundamental hook. Returns a value and a setter. Every call to the setter schedules a re-render.

```jsx
const [text, setText] = useState('')      // string
const [streaming, setStreaming] = useState(false)  // boolean
const [messages, setMessages] = useState([])       // array
```

**Functional updates** — when new state depends on old state, always use the function form to avoid stale closure bugs:

```jsx
// ❌ Stale: 'streaming' may be outdated in closure
setStreaming(true)

// ✅ Safe: always reads the latest value
setAuthVersion(v => v + 1)
setMessages(prev => [...prev, newMessage])
```

This pattern appears throughout `useChat.js` wherever messages are accumulated.

### useEffect — side effects and lifecycle

`useEffect` runs code outside the render cycle — API calls, subscriptions, timers. The dependency array controls when it re-runs.

```jsx
// [] = run once on mount, cleanup on unmount
useEffect(() => {
  wsService.connect(token)
  return () => wsService.close()  // cleanup function
}, [])

// [authVersion] = re-run every time authVersion changes
useEffect(() => {
  if (authVersion === 0) return
  fetchChats()
}, [authVersion])

// no array = run after EVERY render (avoid this unless intentional)
useEffect(() => {
  activeChatIdRef.current = activeChatId  // sync ref to latest state
})
```

**Cleanup functions** are critical for subscriptions. The function returned from `useEffect` runs before the next effect fires and on unmount — used in `useWebSocket.js` to unregister event handlers.

### useRef — mutable values that don't trigger re-renders

`useRef` stores a value that persists across renders but whose changes don't cause re-renders. Two uses in this codebase:

**1. Avoiding stale closures** — callbacks registered once need to always call the latest handler:

```jsx
// In useWebSocket.js
const onTokenRef = useRef(onToken)
useEffect(() => { onTokenRef.current = onToken })  // sync on every render

// Handler registered once, but always calls the latest callback
wsService.on('token', (m) => onTokenRef.current?.(m))
```

Without the ref, the `wsService.on` callback would capture the *initial* `onToken` function and never see updates. With the ref, it always reads the current value.

**2. Stable values across renders** — `activeChatIdRef` in `useChat.js`:

```jsx
const activeChatIdRef = useRef(activeChatId)
useEffect(() => { activeChatIdRef.current = activeChatId }, [activeChatId])
```

This lets WS callbacks (which are registered once) always read the *current* `activeChatId` without being re-registered on every state change.

### useCallback — stable function references

`useCallback` returns a memoized function that only changes if its dependencies change. Used for:
- Functions passed as props (prevents child re-renders)
- Functions used in `useEffect` dependency arrays

```jsx
const sendMessage = useCallback(async (text) => {
  // ... complex logic
}, [activeChatId, streaming])  // only recreate when these change
```

The empty array `[]` in several callbacks like `handleToken` means the function is created once and never recreated — safe because all the values it needs are accessed via refs.

### Context — global state without prop drilling

Context lets any component in the tree read state without passing it through every level.

```jsx
// 1. Create
const AuthContext = createContext(null)

// 2. Provide (wraps the tree)
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

// 3. Consume (anywhere in the tree)
function Sidebar() {
  const { user, logout } = useAuth()
}
```

This project uses two contexts: `AuthContext` (login state) and `ChatContext` (wraps the `useChat` hook so all components share the same chat state without prop drilling).

### React StrictMode — the double-invoke

`<React.StrictMode>` in `main.jsx` wraps the whole app. In development it deliberately:
- Mounts → unmounts → remounts every component
- Calls every `useEffect` twice
- Calls every `useState` initializer twice

This catches bugs from missing cleanup. It's development-only and has no effect in production. This is why the auth guard in `silentRestore()` is important — without it StrictMode fires two `/refresh` calls.

---

## Part 2 — Singleton services and module-level state

### Why services are singletons

`websocketService.js`, `tokenStore.js`, and `apiClient.js` all export **module-level variables** — values that live at the top of the file, outside any function or class:

```js
// tokenStore.js
let _accessToken = null   // module-level: one instance for the whole app

export const getAccessToken = () => _accessToken
export const setAccessToken = (t) => { _accessToken = t }
```

In a browser, a JavaScript module is evaluated exactly once (except for Vite HMR — see below). Every `import` of `tokenStore.js` gets the *same* `_accessToken` variable. This is why the access token can be set in `chatService.login()` and immediately read in `apiClient.request()` without passing it anywhere.

### Vite HMR and `import.meta.hot.decline()`

Vite's Hot Module Replacement re-evaluates modules when files change. For most modules this is fine — it just updates the component. But for modules with singleton state (the access token, the WS connection, the refresh promise), re-evaluation would reset them to their initial values.

```js
// tokenStore.js
if (import.meta.hot) {
  import.meta.hot.decline()  // tell Vite: do a full page reload instead of hot swap
}
```

This is applied to `tokenStore.js`, `apiClient.js`, and `websocketService.js`. All other files (components, hooks, styles) continue to hot-reload normally.

---

## Part 3 — WebSocket fundamentals

### What a WebSocket is

HTTP is request-response: client asks, server answers, connection closes. WebSocket is a **persistent bidirectional pipe** — once opened, both sides can send messages at any time, in either direction.

```
HTTP:  Client ──request──▶ Server ──response──▶ Client   (closes)

WebSocket:
       Client ◀────────────────────────────────▶ Server  (stays open)
              ◀── token ──────────────────────
              ◀── token ──────────────────────
              ── chat_message ───────────────▶
              ◀── token ──────────────────────
              ── stop_stream ────────────────▶
```

### Close codes

WebSocket close events carry a numeric code:

| Code | Meaning | Should reconnect? |
|---|---|---|
| 1000 | Normal closure (intentional logout) | No |
| 1001 | Going away (page navigation, browser cleanup, StrictMode unmount) | No |
| 1008 | Policy violation (bad token) | No |
| 1006 | Abnormal closure (network drop) | Yes |

This is why `websocketService.js` explicitly excludes 1000, 1001, and 1008 from auto-reconnect.

### The browser WebSocket API

```js
const socket = new WebSocket('ws://localhost:8000/ws?token=...')

socket.onopen    = () => { /* connected */ }
socket.onmessage = (event) => { const data = JSON.parse(event.data) }
socket.onclose   = (event) => { /* event.code, event.reason */ }
socket.onerror   = () => { /* always followed by onclose */ }

socket.send(JSON.stringify({ type: 'ping' }))
socket.close(1000, 'Logout')
```

`readyState` values: `CONNECTING=0`, `OPEN=1`, `CLOSING=2`, `CLOSED=3`

### Thread safety with send lock (backend)

The browser's WebSocket is single-threaded — only one JS call at a time. But on the Flask backend, multiple Python threads run simultaneously (one per streaming reply). Without a lock, two threads calling `ws.send()` concurrently could corrupt the message. The `threading.Lock()` in `ws_handler.py` ensures sends are serialized:

```python
def _send(ws, lock: threading.Lock, payload: dict) -> bool:
    try:
        with lock:          # only one thread can send at a time
            ws.send(json.dumps(payload))
        return True
    except Exception:
        return False
```

---

## Part 4 — The pub/sub event system

`websocketService.js` implements a simple **publish/subscribe** pattern to decouple the raw socket from the React layer.

```js
// Subscribe: register a handler for an event type
const unsubscribe = wsService.on('token', ({ chatId, token }) => {
  appendToken(chatId, token)
})

// Unsubscribe: call the returned function (used in useEffect cleanup)
unsubscribe()

// Publish: called internally when a message arrives
_emit(eventType, payload) {
  this._handlers[eventType]?.forEach(handler => handler(payload))
}
```

**Why this pattern:** React components need to register handlers using `useEffect`. If the handlers were registered directly on the socket, every component re-render would create duplicate handlers. With pub/sub, `useWebSocket.js` registers exactly once and unregisters on cleanup — the socket doesn't know or care about React's lifecycle.

---

## Part 5 — Concurrent request deduplication

A classic problem: two things trigger the same async operation at the same time. Running it twice wastes resources and can cause bugs (double token rotation).

The solution is a **shared promise**:

```js
let _silentRestorePromise = null

export async function silentRestore() {
  if (hasAccessToken()) {
    // Fast path: already have token, skip /refresh
    return await fetchUser()
  }

  if (_silentRestorePromise) {
    // In-flight: share the existing promise
    return _silentRestorePromise
  }

  // Cold start: create the promise and store it
  _silentRestorePromise = (async () => {
    const token = await callRefreshEndpoint()
    setAccessToken(token)
    return await fetchUser()
  })()

  return _silentRestorePromise
}
```

`_doRefresh()` in `apiClient.js` uses the same pattern (`_refreshPromise`) for concurrent 401 responses — if five requests fail simultaneously, only one `/refresh` call is made and all five requests wait on the same promise.

---

## Part 6 — The human-in-the-loop pattern (threading.Event)

The artifact feedback loop requires the server to pause mid-execution and wait for user input. This is done with Python's `threading.Event`:

```python
# threading.Event is a simple boolean flag with blocking wait
event = threading.Event()

# Streaming thread: blocks here until event is set
event.wait()          # infinite wait (FEEDBACK_TIMEOUT = 0)
# or:
received = event.wait(timeout=300)  # wait up to 5 minutes

# Receive-loop thread: called when artifact_feedback frame arrives
event.set()           # wakes the sleeping thread
```

**Key design decision:** The events are keyed globally by `artifact_id`, not by connection ID. This means the feedback loop survives chat switches — the user can switch to another chat while the server waits, come back later, and submit feedback. The sleeping thread wakes regardless of which chat is currently "active" in the UI.

```python
# Global registry — independent of which connection is active
_fb_registry = {}  # { artifact_id → { event, data } }

def _fb_create(artifact_id):
    event = threading.Event()
    _fb_registry[artifact_id] = {"event": event, "data": None}
    return event

def _fb_deliver(artifact_id, action, comment):
    slot = _fb_registry.get(artifact_id)
    slot["data"] = {"action": action, "comment": comment}
    slot["event"].set()  # wake the sleeping thread
```

---

## Part 7 — The access token + refresh token security model

### Why two tokens

| | Access token | Refresh token |
|---|---|---|
| Lifetime | 5 minutes | 7 days |
| Storage | JavaScript RAM (`tokenStore.js`) | HttpOnly cookie |
| Sent on | Every REST request (`Authorization: Bearer`) | Only to `/api/auth/refresh` |
| Stolen by XSS? | Yes (lives in JS) — but only valid 5 min | No (cookie is not readable by JS) |

The short lifetime of the access token limits the damage if it's stolen. The refresh token, stored as an HttpOnly cookie, is never accessible to JavaScript at all — not even from the browser console.

### Silent refresh flow

```
Access token expires (or 401 received)
  ↓
apiClient intercepts the 401
  ↓
POST /api/auth/refresh
  (browser automatically sends HttpOnly cookie — no JS needed)
  ↓
Server: verify cookie, blacklist old refresh token, issue new pair
  ↓
New access_token stored in RAM
New refresh_token cookie set by server
  ↓
Original request retried with new access token
  ↓
User notices nothing
```

### Token blacklist with TTL

The blacklist stores SHA-256 hashes of revoked tokens (never raw tokens) with their expiry timestamps. A background thread sweeps expired entries every 60 seconds:

```python
_blacklist = {}  # { sha256(token) → expiry_timestamp }

def add(token, expires_at):
    key = sha256(token)
    _blacklist[key] = expires_at

def is_blacklisted(token):
    key = sha256(token)
    expiry = _blacklist.get(key)
    if expiry is None: return False       # not blacklisted
    if time.time() > expiry:              # already expired
        del _blacklist[key]               # clean up
        return False
    return True

# Background sweep thread
def _sweep_loop():
    while True:
        time.sleep(60)
        now = time.time()
        expired = [k for k, exp in _blacklist.items() if now > exp]
        for k in expired:
            del _blacklist[k]
```

---

## Part 8 — How all the pieces connect

Here's the complete data flow for sending a message:---

## Part 9 — Common patterns and why they exist

### The ref-for-stale-closure pattern

This appears in `useChat.js` for `activeChatIdRef` and `openArtifactRef`, and in `useWebSocket.js` for every callback:

```jsx
// Problem: WS handler registered once captures old activeChatId
useEffect(() => {
  wsService.on('token', ({ chatId }) => {
    if (chatId !== activeChatId) return  // ❌ stale! always sees initial value
  })
}, [])

// Solution: ref always points to latest value
const activeChatIdRef = useRef(activeChatId)
useEffect(() => { activeChatIdRef.current = activeChatId }, [activeChatId])

useEffect(() => {
  wsService.on('token', ({ chatId }) => {
    if (chatId !== activeChatIdRef.current) return  // ✅ always current
  })
}, [])
```

### Optimistic updates

Show the result before the server confirms it. If the server fails, roll back:

```jsx
// 1. Update UI immediately (feels instant)
setChats(prev => prev.filter(c => c.id !== id))

// 2. Tell server
try {
  await apiDeleteChat(id)
} catch {
  // 3. Roll back if server failed
  const restored = await apiFetchChats()
  setChats(restored)
}
```

### The placeholder ID pattern

The frontend generates a temporary ID (`ph_abc123`) for the assistant placeholder bubble before the server assigns a real ID. The first token frame from the server carries the real `messageId` — the handler reconciles them:

```jsx
// On first token: rename placeholder to server ID
setMessages(prev => prev.map(m =>
  m.id === placeholderId || m.id === messageId
    ? { ...m, id: messageId, content: m.content + token }
    : m
))
```

This is why `stored_msg_id` is captured in the backend — the server also needs the real ID it assigned (not the placeholder) to update the stored message correctly.

### Guard patterns for concurrent async operations

Three places use promise-sharing to prevent duplicate calls:

| Guard | Prevents |
|---|---|
| `_silentRestorePromise` | Two concurrent page-load restores calling `/refresh` twice |
| `_refreshPromise` | Multiple concurrent 401s each triggering their own `/refresh` |
| `wsService.connect()` OPEN/CONNECTING check | StrictMode double-mount opening two WS connections |

The pattern is always: check if already running → share the promise → start fresh if not.

---

## Summary table

| Concept | Where | Purpose |
|---|---|---|
| `useState` | Every component | Local reactive state |
| `useEffect([])` | AuthContext, useWebSocket | Run once on mount |
| `useEffect([dep])` | useChat (authVersion) | Re-run when dep changes |
| `useRef` | useChat, useWebSocket | Stable values / avoid stale closures |
| `useCallback` | useChat | Stable function identity |
| Context | AuthContext, ChatContext | Global state without prop drilling |
| Singleton module | tokenStore, wsService, apiClient | One instance shared by whole app |
| Pub/sub | websocketService | Decouple socket from React lifecycle |
| Promise sharing | silentRestore, _doRefresh | Deduplicate concurrent async calls |
| Optimistic update | sendMessage, deleteChat | Instant UI response before server confirms |
| Placeholder ID | useChat + ws_handler | Handle messages before server assigns real ID |
| `threading.Event` | ws_handler | Pause a thread waiting for user input |
| `threading.Lock` | ws_handler | Serialize concurrent `ws.send()` calls |
| `import.meta.hot.decline()` | tokenStore, apiClient, wsService | Prevent Vite HMR from resetting singleton state |
| StrictMode double-invoke | All `useEffect([])` | Development-only guard against missing cleanup |