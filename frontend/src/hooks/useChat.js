// src/hooks/useChat.js
// =============================================================================
// Central chat state hook — handles streaming, artifacts, and feedback loop.
//
// WebSocket events handled:
//   token            → append to assistant bubble
//   done             → mark message finished
//   artifact         → attach artifact (awaitingFeedback=true → show feedback bar)
//   artifact_revised → update artifact with new version, still awaiting feedback
//   artifact_accepted→ mark artifact as accepted, hide feedback bar
//   artifact_timeout → auto-accepted after timeout
//   revision_start   → add new "Revising..." assistant message
//   error            → show error in bubble
// =============================================================================
import { useState, useCallback, useEffect, useRef } from 'react'
import { useWebSocket }  from './useWebSocket'
import { wsService }     from '../services/websocketService'
import {
  fetchChats    as apiFetchChats,
  createChat    as apiCreateChat,
  deleteChat    as apiDeleteChat,
  fetchMessages as apiFetchMessages,
  sendMessage   as apiSendMessage,
} from '../services/chatService'
import { SAMPLE_CHATS } from '../data/sampleData'
import { uid }          from '../utils/helpers'
import { useAuth }      from '../context/AuthContext'

export function useChat() {
  const [chats,           setChats]           = useState([])
  const [activeChatId,    setActiveChatId]    = useState(null)
  const [messages,        setMessages]        = useState([])
  const [streaming,       setStreaming]       = useState(false)
  const [openArtifact,    setOpenArtifact]    = useState(null)
  const [loadingChats,    setLoadingChats]    = useState(true)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [error,           setError]           = useState(null)
  const [wsConnected,     setWsConnected]     = useState(false)

  // authVersion from AuthContext — increments on every login.
  // We use it as a dependency so loadChats re-runs after logout→login.
  const { authVersion } = useAuth()

  const activeChatIdRef   = useRef(activeChatId)
  const placeholderIdRef  = useRef(null)   // current assistant placeholder id

  useEffect(() => { activeChatIdRef.current = activeChatId }, [activeChatId])

  // ── Helper: update a message by its id ────────────────────────────────────
  const updateMessage = useCallback((id, updater) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, ...updater(m) } : m))
  }, [])

  // ── Helper: find message by id or placeholder ──────────────────────────────
  const findMessageId = useCallback((messageId) => {
    // Returns the id we should use to look up the message in state
    // (could be the server id or the placeholder id on first token)
    return messageId
  }, [])

  // ── WebSocket event handlers ───────────────────────────────────────────────

  // Each streamed word — append to the right bubble
  const handleToken = useCallback(({ chatId, messageId, token }) => {
    if (chatId !== activeChatIdRef.current) return
    setMessages(prev => prev.map(m => {
      if (m.id === messageId || m.id === placeholderIdRef.current) {
        return { ...m, id: messageId, content: m.content + token }
      }
      return m
    }))
  }, [])

  // Stream finished — remove cursor
  const handleDone = useCallback(({ chatId, messageId }) => {
    if (chatId !== activeChatIdRef.current) return
    setMessages(prev => prev.map(m =>
      m.id === messageId || m.id === placeholderIdRef.current
        ? { ...m, id: messageId, streaming: false }
        : m
    ))
    placeholderIdRef.current = null
    setStreaming(false)
  }, [])

  // New artifact arrived — attach to message, mark awaitingFeedback.
  // NOTE: We do NOT guard on activeChatId here. The backend sends artifact
  // frames for the chat that generated them, which may differ from the
  // chat the user is currently viewing. We always update the message state
  // so switching back shows the card. We only open the panel if active.
  const handleArtifact = useCallback(({ chatId, messageId, artifact,
                                         awaitingFeedback, iteration, maxIterations,
                                         replayed }) => {
    const enriched = { ...artifact, awaitingFeedback, iteration, maxIterations,
                        messageId, chatId }

    // Always update the stored message — works for any chat
    setMessages(prev => prev.map(m =>
      m.id === messageId || m.id === placeholderIdRef.current
        ? { ...m, artifact: enriched }
        : m
    ))

    // Only open the panel if the user is currently looking at this chat.
    // On a replayed frame (reconnect) or cross-chat update, don't hijack
    // the panel — the user will open it when they switch back.
    if (chatId === activeChatIdRef.current && !replayed) {
      setOpenArtifact(enriched)
    }
  }, [])

  // Revised artifact — backend finished the revision, new content ready.
  // Clear the 'revising' spinner and restore awaitingFeedback so the user
  // can review the new version and accept or request more changes.
  const handleArtifactRevised = useCallback(({ chatId, messageId, artifact,
                                                awaitingFeedback, iteration, maxIterations,
                                                replayed }) => {
    // revising:false — clear the spinner set by the optimistic revise update
    const enriched = { ...artifact, awaitingFeedback, iteration, maxIterations,
                        messageId, chatId, revising: false }

    // Match by artifactId (stable across iterations) or messageId fallback
    setMessages(prev => prev.map(m => {
      if (!m.artifact) return m
      const match = m.artifact.id === artifact.id || m.id === messageId
      return match ? { ...m, artifact: enriched } : m
    }))

    if (chatId === activeChatIdRef.current && !replayed) {
      setOpenArtifact(enriched)
    }
  }, [])

  // Artifact accepted — works for any chat (accepted=true removes feedback bar
  // from the message card regardless of which chat is currently active)
  const handleArtifactAccepted = useCallback(({ chatId, messageId, artifactId, autoAccepted }) => {
    // Match by artifactId (stable across the placeholder→server-ID rename)
    // rather than messageId, which may be the placeholder and not match
    // the server-assigned ID that was adopted after the first token frame.
    setMessages(prev => prev.map(m => {
      if (!m.artifact) return m
      // Match by artifact ID or by message ID (covers both cases)
      const artMatch = m.artifact.id === artifactId
      const msgMatch = m.id === messageId
      if (!artMatch && !msgMatch) return m
      return {
        ...m,
        artifact: {
          ...m.artifact,
          accepted:         true,
          awaitingFeedback: false,
        }
      }
    }))

    // Update the open panel too
    setOpenArtifact(prev => {
      if (!prev) return null
      // Match by artifactId or by the panel's own messageId
      if (prev.id !== artifactId && prev.messageId !== messageId) return prev
      return { ...prev, accepted: true, awaitingFeedback: false }
    })
  }, [])

  // Feedback timed out — same treatment as accepted (backend auto-accepted)
  const handleArtifactTimeout = useCallback(({ chatId, messageId, artifactId }) => {
    if (chatId !== activeChatIdRef.current) return
    handleArtifactAccepted({ chatId, messageId, artifactId, autoAccepted: true })
  }, [handleArtifactAccepted])

  // Backend is about to stream revision tokens — add a new assistant bubble
  const handleRevisionStart = useCallback(({ chatId, messageId, comment, iteration }) => {
    if (chatId !== activeChatIdRef.current) return

    setMessages(prev => [...prev, {
      id:        messageId,
      role:      'assistant',
      content:   '',
      streaming: true,
      isRevision: true,
      revisionComment: comment,
      iteration,
    }])
    // Track this as the current placeholder so token handler can find it
    placeholderIdRef.current = messageId
    setStreaming(true)
  }, [])

  const handleWsError = useCallback(({ chatId, messageId, artifactId, error: serverError }) => {
    // Artifact feedback slot expired (server restart mid-review).
    // Clear awaitingFeedback so the bar disappears gracefully.
    if (artifactId) {
      setMessages(prev => prev.map(m => {
        if (!m.artifact || m.artifact.id !== artifactId) return m
        return { ...m, artifact: { ...m.artifact, awaitingFeedback: false } }
      }))
      setOpenArtifact(prev =>
        prev && prev.id === artifactId
          ? { ...prev, awaitingFeedback: false }
          : prev
      )
      setError(serverError || 'Feedback session has ended for this artifact.')
      return
    }

    // Regular streaming error
    if (chatId && chatId !== activeChatIdRef.current) return
    setMessages(prev => prev.map(m =>
      m.id === messageId || m.id === placeholderIdRef.current
        ? { ...m, content: `⚠️ ${serverError || 'Something went wrong.'}`,
            streaming: false, isError: true }
        : m
    ))
    placeholderIdRef.current = null
    setStreaming(false)
    setError(serverError || 'Failed to get a response.')
  }, [])

  // Wire up all WS handlers
  useWebSocket({
    onToken:           handleToken,
    onDone:            handleDone,
    onError:           handleWsError,
    onArtifact:        handleArtifact,
    onArtifactRevised: handleArtifactRevised,
    onArtifactAccepted:handleArtifactAccepted,
    onArtifactTimeout: handleArtifactTimeout,
    onRevisionStart:   handleRevisionStart,
    onConnected:       () => setWsConnected(true),
    onDisconnected:    () => setWsConnected(false),
  })

  // ── Load sidebar on mount ──────────────────────────────────────────────────
  useEffect(() => {
    // Skip the initial run when authVersion is 0 (not yet authenticated)
    if (authVersion === 0) return

    // Reset state so the sidebar shows the loading skeleton
    // instead of stale chats from the previous session
    setChats([])
    setActiveChatId(null)
    setMessages([])
    setOpenArtifact(null)
    setLoadingChats(true)

    async function load() {
      try {
        const data = await apiFetchChats()
        setChats(data)
      } catch (err) {
        console.warn('[useChat] fetchChats failed — using sample data:', err.message)
        setChats(SAMPLE_CHATS)
      } finally {
        setLoadingChats(false)
      }
    }
    load()
  }, [authVersion])  // re-runs every time the user logs in

  // ── Actions ────────────────────────────────────────────────────────────────

  const newChat = useCallback(() => {
    if (activeChatId) wsService.stopStream(activeChatId)
    placeholderIdRef.current = null
    setActiveChatId(null)
    setMessages([])
    setOpenArtifact(null)
    setError(null)
    setStreaming(false)
  }, [activeChatId])

  const selectChat = useCallback(async (id) => {
    if (id === activeChatId) return
    if (activeChatId) wsService.stopStream(activeChatId)
    placeholderIdRef.current = null
    setActiveChatId(id)
    setMessages([])
    setOpenArtifact(null)
    setError(null)
    setStreaming(false)
    setLoadingMessages(true)
    try {
      const messages = await apiFetchMessages(id)
      // Keep awaitingFeedback as-is — if the backend still has a live
      // feedback slot, the bar should show so the user can respond.
      // If the slot is gone (server restart), the user will get an error
      // frame when they try to submit, which is handled in handleWsError.
      setMessages(messages)
    } catch {
      setError('Could not load messages. Please try again.')
    } finally {
      setLoadingMessages(false)
    }
  }, [activeChatId])

  const deleteChat = useCallback(async (id) => {
    if (id === activeChatId) {
      wsService.stopStream(id)
      placeholderIdRef.current = null
      setActiveChatId(null)
      setMessages([])
      setOpenArtifact(null)
      setStreaming(false)
    }
    setChats(prev => prev.filter(c => c.id !== id))
    try { await apiDeleteChat(id) } catch {
      try { setChats(await apiFetchChats()) } catch {}
    }
  }, [activeChatId])

  const cancelStream = useCallback(() => {
    if (activeChatId) wsService.stopStream(activeChatId)
    setStreaming(false)
    setMessages(prev => prev.map(m => m.streaming ? { ...m, streaming: false } : m))
    placeholderIdRef.current = null
  }, [activeChatId])

  /**
   * Send a user message → saves via REST → triggers WS streaming.
   */
  const sendMessage = useCallback(async (text) => {
    if (!text.trim() || streaming) return
    setError(null)

    const trimmed = text.trim()
    let chatId    = activeChatId

    // Create new chat if needed
    if (!chatId) {
      const title  = trimmed.slice(0, 50) + (trimmed.length > 50 ? '…' : '')
      const tempId = `temp_${uid()}`
      setChats(prev => [{ id: tempId, title, date: 'Today' }, ...prev])
      setActiveChatId(tempId)
      chatId = tempId
      try {
        const serverChat = await apiCreateChat(title)
        setChats(prev => prev.map(c => c.id === tempId ? serverChat : c))
        setActiveChatId(serverChat.id)
        chatId = serverChat.id
      } catch {
        setChats(prev => prev.filter(c => c.id !== tempId))
        setActiveChatId(null)
        setError('Could not create conversation. Please try again.')
        return
      }
    }

    // Optimistic user bubble
    const localUserMsgId = `local_${uid()}`
    setMessages(prev => [...prev, { id: localUserMsgId, role: 'user', content: trimmed }])

    // Empty assistant placeholder with cursor
    const placeholderId = `ph_${uid()}`
    placeholderIdRef.current = placeholderId
    setMessages(prev => [...prev, { id: placeholderId, role: 'assistant', content: '', streaming: true }])
    setStreaming(true)

    try {
      const savedMsg = await apiSendMessage(chatId, trimmed)
      setMessages(prev => prev.map(m => m.id === localUserMsgId ? savedMsg : m))
      wsService.sendChatMessage(chatId, placeholderId, trimmed)
    } catch (err) {
      setMessages(prev => prev.filter(m => m.id !== placeholderId))
      placeholderIdRef.current = null
      setStreaming(false)
      setError('Failed to send. Please try again.')
    }
  }, [activeChatId, streaming])

  /**
   * Send artifact feedback to the backend.
   * The backend is blocking on a threading.Event — this unblocks it.
   *
   * @param {'accept'|'revise'} action
   * @param {string} comment  - The revision request (empty string for accept)
   */
  // Ref that always points to the current openArtifact.
  // Using a ref here means sendArtifactFeedback never holds a stale closure
  // (deps array [activeChatId, openArtifact] would re-create the callback on
  //  every panel state change, but the ref always reads the latest value).
  const openArtifactRef = useRef(null)
  useEffect(() => { openArtifactRef.current = openArtifact }, [openArtifact])

  const sendArtifactFeedback = useCallback((action, comment = '') => {
    const art = openArtifactRef.current   // always the latest, never stale
    if (!art) {
      console.warn('[useChat] sendArtifactFeedback: no open artifact')
      return
    }

    // chatId and messageId were attached to the artifact object in handleArtifact.
    // artifactId is art.id which includes the version suffix (e.g. art_ph_abc_v1).
    const chatId    = art.chatId    || activeChatIdRef.current
    const messageId = art.messageId || ''

    console.debug('[useChat] sendArtifactFeedback', { action, comment, artifactId: art.id, chatId, messageId })

    wsService.send({
      type:       'artifact_feedback',
      chatId,
      messageId,
      artifactId: art.id,
      action,
      comment,
    })

    // Optimistic UI update — different per action:
    //   accept → hide bar immediately, show accepted badge
    //   revise → hide bar, show 'Revising…' spinner until artifact_revised arrives
    // We never keep awaitingFeedback:true after a click — that prevents double-submit.
    const optimisticUpdate = (prev) => {
      if (!prev) return null
      if (action === 'accept') {
        return { ...prev, awaitingFeedback: false, accepted: true }
      }
      // revise: clear feedback bar, mark as revising so UI shows spinner
      return { ...prev, awaitingFeedback: false, revising: true }
    }

    // Update the open panel
    setOpenArtifact(optimisticUpdate)

    // Update the message in the list so switching chats and back
    // doesn't restore the awaiting-feedback card with the old state
    setMessages(prev => prev.map(m => {
      if (!m.artifact || m.artifact.id !== art.id) return m
      return { ...m, artifact: optimisticUpdate(m.artifact) }
    }))
  }, [])   // stable — reads current values via refs

  return {
    chats, messages, activeChatId,
    streaming, openArtifact,
    loadingChats, loadingMessages,
    error, wsConnected,
    setOpenArtifact, setError,
    newChat, selectChat, deleteChat,
    sendMessage, cancelStream,
    sendArtifactFeedback,
  }
}