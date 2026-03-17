# backend/ai_engine.py
# =============================================================================
# Mock AI engine — generates responses and artifact revisions.
#
# Public API:
#   generate_response(user_message)          → full reply string
#   generate_revision(artifact, feedback)    → revised artifact content string
#   stream_tokens(text)                      → generator of (token, delay)
# =============================================================================

import re


# =============================================================================
# Response bank  (initial replies, keyed by topic)
# =============================================================================

_RESPONSES: dict[str, str] = {

    "greeting": """\
Hello! I'm Claude, an AI assistant made by Anthropic. I can help you with \
writing, coding, analysis, research, creative work, and much more.

What would you like to work on today?\
""",

    "react": """\
Here's a clean, reusable React custom hook:

```jsx
// hooks/useLocalStorage.js
import { useState, useEffect } from 'react'

export function useLocalStorage(key, initialValue) {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored ? JSON.parse(stored) : initialValue
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value))
  }, [key, value])

  return [value, setValue]
}
```

**Usage — exactly like useState:**
```jsx
const [theme, setTheme] = useLocalStorage('theme', 'light')
```

**Why this works well:**
1. **Lazy initialisation** — the callback in `useState` runs only once on mount
2. **Automatic sync** — `useEffect` keeps localStorage in sync with state
3. **Error safety** — `try/catch` guards against corrupted stored JSON\
""",

    "python": """\
Here's a solid pandas data-cleaning workflow:

```python
import pandas as pd

# 1. Load and inspect
df = pd.read_csv('data.csv')
print(df.shape)
print(df.dtypes)

# 2. Clean — drop rows missing key fields
df = df.dropna(subset=['name', 'price'])
df['price'] = pd.to_numeric(df['price'], errors='coerce')
df = df.dropna(subset=['price'])

# 3. Transform — add derived column
df['price_usd'] = (df['price'] * 1.08).round(2)

# 4. Aggregate
summary = (
    df
    .groupby('category')
    .agg(
        count     = ('name',      'count'),
        avg_price = ('price_usd', 'mean'),
        total     = ('price_usd', 'sum'),
    )
    .round(2)
    .reset_index()
    .sort_values('total', ascending=False)
)
print(summary)
```

**Key techniques:**
- `dropna(subset=[...])` — only drops rows where specific columns are null
- `pd.to_numeric(errors='coerce')` — converts bad strings to NaN instead of crashing
- Named aggregation syntax is cleaner than a plain dict\
""",

    "javascript": """\
Here's a robust async utility with automatic retries:

```javascript
// utils/fetchWithRetry.js

export async function fetchWithRetry(url, options = {}, retries = 3) {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, {
        ...options,
        headers: { 'Content-Type': 'application/json', ...options.headers },
      })

      if (res.status >= 400 && res.status < 500) {
        throw new Error(`Client error ${res.status}`)
      }
      if (!res.ok) throw new Error(`Server error ${res.status}`)

      return await res.json()

    } catch (err) {
      if (attempt === retries) throw err

      const delay = 500 * 2 ** (attempt - 1)
      console.warn(`Attempt ${attempt} failed. Retrying in ${delay}ms…`)
      await new Promise(r => setTimeout(r, delay))
    }
  }
}
```

Exponential back-off means transient hiccups resolve automatically \
without hammering the server.\
""",

    "write": """\
Here's a polished follow-up email template:

---

**Subject:** Following up — [Topic]

Hi [Name],

I hope you're doing well.

I wanted to follow up on our conversation about **[topic]**. \
Here are the suggested next steps:

1. **[Action item 1]** — *Owner: You / Due: [Date]*
2. **[Action item 2]** — *Owner: [Name] / Due: [Date]*
3. **[Action item 3]** — *Owner: Both / Due: [Date]*

Please let me know if anything looks off or if you'd like to adjust the timeline. \
Happy to jump on a quick call if that's easier.

Best regards,
[Your name]
[Title] · [Company]

---

Want me to adjust the tone (more formal, more casual, or more persuasive)?\
""",

    "explain": """\
Great question — let me break this down clearly.

**The core idea** has three moving parts:

1. **Input** — what you start with: data, a user request, or a system trigger.
2. **Processing** — the logic that transforms the input.
3. **Output** — the result returned to the caller or shown in the UI.

**Example:**
```
User clicks "Load data"
  → HTTP GET /api/data      (input)
  → Server queries DB       (processing)
  → JSON response           (output)
  → React renders the list  (UI update)
```

Keeping these stages separate makes each one **independently testable** \
and much easier to debug.

Would you like me to go deeper on any specific stage?\
""",

    "default": """\
That's an interesting question! Here's how I'd approach it:

**Step 1 — Understand the goal**
Clarify exactly what success looks like before writing any code. \
A clear definition of "done" saves hours of rework.

**Step 2 — Break it into small pieces**
Decompose the task into the smallest units that can be built and tested independently.

**Step 3 — Build incrementally**
Start with the simplest thing that works, then layer complexity on top.

**Step 4 — Validate as you go**
Test each small piece. Catching bugs at a function boundary is far easier \
than debugging a chain of five functions that are all subtly wrong.

Would you like me to apply this approach to your specific problem?\
""",
}


# =============================================================================
# Revision bank  (mock responses to artifact feedback, keyed by keyword)
# Each entry maps a feedback keyword → a full revised artifact content string.
# In a real app this would call an LLM with the original artifact + feedback.
# =============================================================================

_REVISION_RESPONSES: dict[str, str] = {

    # Feedback about colours / styling
    "color": """\
// Revised — updated color scheme to blue as requested

export function useLocalStorage(key, initialValue) {
  // Color theme is now handled through CSS variables
  // Primary: #2563EB (blue-600), Secondary: #1D4ED8 (blue-700)
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored ? JSON.parse(stored) : initialValue
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    // Apply the blue theme when the value is 'blue'
    if (key === 'theme') {
      document.documentElement.style.setProperty(
        '--color-primary', value === 'blue' ? '#2563EB' : '#C96A42'
      )
    }
    localStorage.setItem(key, JSON.stringify(value))
  }, [key, value])

  return [value, setValue]
}
""",

    # Feedback about adding types / TypeScript
    "type": """\
// Revised — added TypeScript types as requested

import { useState, useEffect } from 'react'

export function useLocalStorage<T>(
  key: string,
  initialValue: T
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored ? (JSON.parse(stored) as T) : initialValue
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value))
  }, [key, value])

  return [value, setValue]
}
""",

    # Feedback about error handling
    "error": """\
// Revised — improved error handling with callbacks as requested

import { useState, useEffect, useCallback } from 'react'

export function useLocalStorage(key, initialValue, onError) {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored ? JSON.parse(stored) : initialValue
    } catch (err) {
      onError?.(`Read error for key "${key}": ${err.message}`)
      return initialValue
    }
  })

  const setStoredValue = useCallback((newValue) => {
    try {
      setValue(newValue)
      localStorage.setItem(key, JSON.stringify(newValue))
    } catch (err) {
      onError?.(`Write error for key "${key}": ${err.message}`)
    }
  }, [key, onError])

  // Sync across tabs — listen for storage events from other windows
  useEffect(() => {
    function handleStorageEvent(e) {
      if (e.key === key && e.newValue !== null) {
        try {
          setValue(JSON.parse(e.newValue))
        } catch (err) {
          onError?.(`Sync error: ${err.message}`)
        }
      }
    }
    window.addEventListener('storage', handleStorageEvent)
    return () => window.removeEventListener('storage', handleStorageEvent)
  }, [key, onError])

  return [value, setStoredValue]
}
""",

    # Feedback about comments / documentation
    "comment": """\
// Revised — added detailed JSDoc comments as requested

import { useState, useEffect } from 'react'

/**
 * A custom hook that synchronises React state with localStorage.
 *
 * @template T
 * @param {string} key           - The localStorage key to use for storage.
 * @param {T}      initialValue  - The value to use if nothing is stored yet.
 * @returns {[T, function(T): void]}  A [value, setter] tuple, like useState.
 *
 * @example
 * const [darkMode, setDarkMode] = useLocalStorage('darkMode', false)
 */
export function useLocalStorage(key, initialValue) {
  /**
   * Lazy initialiser — reads from localStorage only once, on first render.
   * Avoids reading on every re-render, which would be wasteful.
   */
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key)
      // If nothing is stored, fall back to the caller-supplied initialValue
      return stored !== null ? JSON.parse(stored) : initialValue
    } catch {
      // Corrupt JSON or SecurityError (e.g. private browsing) — use default
      return initialValue
    }
  })

  /**
   * Keep localStorage in sync whenever the state value changes.
   * Also runs on mount so the initial value is written if nothing was stored.
   */
  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value))
  }, [key, value])

  return [value, setValue]
}
""",

    # Generic / default revision
    "default": """\
// Revised — refactored for clarity and added remove() helper as requested

import { useState, useEffect, useCallback } from 'react'

export function useLocalStorage(key, initialValue) {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored !== null ? JSON.parse(stored) : initialValue
    } catch {
      return initialValue
    }
  })

  // Update state and persist to localStorage
  const set = useCallback((newValue) => {
    setValue(newValue)
  }, [])

  // Remove the key from localStorage and reset to initialValue
  const remove = useCallback(() => {
    localStorage.removeItem(key)
    setValue(initialValue)
  }, [key, initialValue])

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value))
  }, [key, value])

  return [value, set, remove]
}
""",
}


# =============================================================================
# Public functions
# =============================================================================

def generate_response(user_message: str) -> str:
    """
    Pick the best canned reply for a user message.
    Uses keyword scanning — sufficient for mock purposes.
    """
    key = _pick_response_key(user_message)
    return _RESPONSES[key]


def generate_revision(original_content: str, feedback: str) -> str:
    """
    Produce a revised artifact based on the original content and user feedback.

    In a real app this would send both the original code and the feedback
    to an LLM and return its revised output. Here we pick a mock revision
    based on keywords found in the feedback text.

    :param original_content: The current artifact source code
    :param feedback:         The user's revision request
    :returns:                A revised artifact content string
    """
    key = _pick_revision_key(feedback)
    return _REVISION_RESPONSES[key]


def stream_tokens(text: str):
    """
    Split text into word-level tokens and yield each with a realistic delay.

    Yields: (token: str, delay: float)

    Callers:
        for token, delay in stream_tokens(text):
            time.sleep(delay)
            ws.send(token)
    """
    # Keep whitespace attached to each word so the client reconstructs faithfully
    words = re.findall(r'\S+\s*|\n+', text)

    for word in words:
        if word.rstrip().endswith(('.', '!', '?', ':')):
            delay = 0.06   # longer pause after sentence-ending punctuation
        elif '\n' in word:
            delay = 0.04   # medium pause after newline
        else:
            delay = 0.025  # fast for regular words

        yield word, delay


# =============================================================================
# Private helpers
# =============================================================================

def _pick_response_key(message: str) -> str:
    t = message.lower()
    if any(w in t for w in ("hello", "hi ", "hey ", "good morning")):
        return "greeting"
    if any(w in t for w in ("react", "component", "hook", "jsx", "frontend", "dashboard")):
        return "react"
    if any(w in t for w in ("python", "pandas", "numpy", "django", "flask")):
        return "python"
    if any(w in t for w in ("javascript", "js", "node", "async", "await", "fetch")):
        return "javascript"
    if any(w in t for w in ("write", "email", "draft", "letter", "compose")):
        return "write"
    if any(w in t for w in ("explain", "what is", "how does", "how do", "why")):
        return "explain"
    return "default"


def _pick_revision_key(feedback: str) -> str:
    t = feedback.lower()
    if any(w in t for w in ("color", "colour", "blue", "red", "green", "style", "theme")):
        return "color"
    if any(w in t for w in ("type", "typescript", "ts", "interface", "generic")):
        return "type"
    if any(w in t for w in ("error", "catch", "handle", "try", "exception", "safe")):
        return "error"
    if any(w in t for w in ("comment", "doc", "jsdoc", "explain", "document")):
        return "comment"
    return "default"