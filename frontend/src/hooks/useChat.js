// src/hooks/useChat.js
// =============================================================================
// Central chat state hook — handles streaming, artifacts, and feedback loop.
//
// WebSocket events handled:
//   token            → append to assistant bubble
//   done             → mark message finished
//   artifact         → attach artifact (awaitingFeedback=true → show feedback bar)
//   artifact_accepted→ mark artifact as accepted, hide feedback bar
//   error            → show error in bubble
// =============================================================================
import { useState, useCallback, useEffect, useRef } from "react";
import { useWebSocket } from "./useWebSocket";
import { wsService }    from "../services/websocketService";
import {
  fetchMessages as apiFetchMessages,
  sendMessage   as apiSendMessage,
  createChat    as apiCreateChat,
  deleteChat    as apiDeleteChat,
  startReq,
  createProjectChat,
} from "../services/chatService";
import { uid }     from "../utils/helpers";
import { useAuth } from "../context/AuthContext";

export function useChat() {
  const [activeChatId,    setActiveChatId]    = useState(null);
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [subChat,         setSubChat]         = useState(null);
  const [messages,        setMessages]        = useState([]);
  const [streaming,       setStreaming]       = useState(false);
  const [openArtifact,    setOpenArtifact]    = useState(null);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error,           setError]           = useState(null);
  const [wsConnected,     setWsConnected]     = useState(false);

  const { authVersion } = useAuth();

  const activeChatIdRef  = useRef(activeChatId);
  const placeholderIdRef = useRef(null);

  useEffect(() => { activeChatIdRef.current = activeChatId; }, [activeChatId]);

  // ── Reset when user logs out ───────────────────────────────────────────────
  useEffect(() => {
    if (authVersion === 0) {
      setActiveChatId(null);
      setActiveProjectId(null);
      setMessages([]);
      setOpenArtifact(null);
      setStreaming(false);
    }
  }, [authVersion]);

  // ── WebSocket handlers ────────────────────────────────────────────────────

  const handleToken = useCallback(({ chatId, messageId, token, role }) => {
    if (chatId !== activeChatIdRef.current) return;
    setMessages((prev) => {
      const idx = prev.findIndex(
        (m) => m.id === messageId || m.id === placeholderIdRef.current
      );
      if (idx !== -1) {
        return prev.map((m, i) =>
          i === idx ? { ...m, content: m.content + token } : m
        );
      }
      placeholderIdRef.current = messageId;
      return [
        ...prev,
        { id: messageId, role: role || "assistant", content: token, streaming: true },
      ];
    });
  }, []);

  const handleDone = useCallback(({ chatId, messageId }) => {
    if (chatId !== activeChatIdRef.current) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId || m.id === placeholderIdRef.current
          ? { ...m, id: messageId, streaming: false }
          : m
      )
    );
    placeholderIdRef.current = null;
    setStreaming(false);
  }, []);

  const handleArtifact = useCallback(
    ({ chatId, messageId, artifact, awaitingFeedback, iteration }) => {
      const enriched = { ...artifact, awaitingFeedback, iteration, messageId, chatId };
      setMessages((prev) => {
        const exists = prev.some(
          (m) => m.id === messageId || m.id === placeholderIdRef.current
        );
        if (exists) {
          return prev.map((m) =>
            m.id === messageId || m.id === placeholderIdRef.current
              ? { ...m, id: messageId, artifact: enriched }
              : m
          );
        }
        return [
          ...prev,
          { id: messageId, role: "assistant", content: "", streaming: false, artifact: enriched },
        ];
      });
      if (chatId === activeChatIdRef.current) {
        setOpenArtifact(enriched);
      }
    },
    []
  );

  const handleArtifactAccepted = useCallback(
    ({ chatId, messageId, artifactId }) => {
      setMessages((prev) =>
        prev.map((m) => {
          if (!m.artifact) return m;
          if (m.artifact.id !== artifactId && m.id !== messageId) return m;
          return { ...m, artifact: { ...m.artifact, accepted: true, awaitingFeedback: false } };
        })
      );
      setOpenArtifact((prev) => {
        if (!prev) return null;
        if (prev.id !== artifactId && prev.messageId !== messageId) return prev;
        return { ...prev, accepted: true, awaitingFeedback: false };
      });
    },
    []
  );

  const handleWsError = useCallback(
    ({ chatId, messageId, artifactId, error: serverError }) => {
      if (artifactId) {
        setMessages((prev) =>
          prev.map((m) => {
            if (!m.artifact || m.artifact.id !== artifactId) return m;
            return { ...m, artifact: { ...m.artifact, awaitingFeedback: false } };
          })
        );
        setOpenArtifact((prev) =>
          prev && prev.id === artifactId ? { ...prev, awaitingFeedback: false } : prev
        );
        setError(serverError || "Feedback session has ended for this artifact.");
        return;
      }
      if (chatId && chatId !== activeChatIdRef.current) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId || m.id === placeholderIdRef.current
            ? { ...m, content: `⚠️ ${serverError || "Something went wrong."}`, streaming: false, isError: true }
            : m
        )
      );
      placeholderIdRef.current = null;
      setStreaming(false);
      setError(serverError || "Failed to get a response.");
    },
    []
  );

  useWebSocket({
    onToken:            handleToken,
    onDone:             handleDone,
    onError:            handleWsError,
    onArtifact:         handleArtifact,
    onArtifactAccepted: handleArtifactAccepted,
    onConnected:        () => setWsConnected(true),
    onDisconnected:     () => setWsConnected(false),
  });

  // ── Actions ───────────────────────────────────────────────────────────────

  /** Select a chat (called from sidebar or after creating a new one) */
  const selectChat = useCallback(
    async (id, newSubChat = 0, projectId = null) => {
      if (id === activeChatId && subChat === newSubChat) return;
      if (activeChatId) wsService.stopStream(activeChatId);
      placeholderIdRef.current = null;
      setActiveChatId(id);
      setActiveProjectId(projectId);
      setSubChat(newSubChat);
      setMessages([]);
      setOpenArtifact(null);
      setError(null);
      setStreaming(false);
      setLoadingMessages(true);
      try {
        const msgs = await apiFetchMessages(id, newSubChat);
        setMessages(msgs);
      } catch {
        setError("Could not load messages. Please try again.");
      } finally {
        setLoadingMessages(false);
      }
    },
    [activeChatId, subChat]
  );

  const clearActiveChat = useCallback(() => {
    if (activeChatId) wsService.stopStream(activeChatId);
    placeholderIdRef.current = null;
    setActiveChatId(null);
    setActiveProjectId(null);
    setMessages([]);
    setOpenArtifact(null);
    setError(null);
    setStreaming(false);
  }, [activeChatId]);

  const deleteChat = useCallback(
    async (id) => {
      if (id === activeChatId) {
        wsService.stopStream(id);
        placeholderIdRef.current = null;
        setActiveChatId(null);
        setMessages([]);
        setOpenArtifact(null);
        setStreaming(false);
      }
      try {
        await apiDeleteChat(id);
      } catch {}
    },
    [activeChatId]
  );

  const cancelStream = useCallback(() => {
    if (activeChatId) wsService.stopStream(activeChatId);
    setStreaming(false);
    setMessages((prev) => prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)));
    placeholderIdRef.current = null;
  }, [activeChatId]);

  const sendMessage = useCallback(
    async (text) => {
      if (!text.trim() || streaming) return;
      setError(null);
      const trimmed = text.trim();
      let chatId = activeChatId;

      // Create top-level chat if no active chat
      if (!chatId) {
        const title  = trimmed.slice(0, 50) + (trimmed.length > 50 ? "…" : "");
        const tempId = `temp_${uid()}`;
        setActiveChatId(tempId);
        chatId = tempId;
        try {
          const serverChat = await apiCreateChat(title);
          setActiveChatId(serverChat.id);
          chatId = serverChat.id;
        } catch {
          setActiveChatId(null);
          setError("Could not create conversation. Please try again.");
          return;
        }
      }

      const localId = `local_${uid()}`;
      setMessages((prev) => [...prev, { id: localId, role: "user", content: trimmed }]);
      setStreaming(true);

      try {
        const saved = await apiSendMessage(chatId, trimmed, subChat);
        setMessages((prev) => prev.map((m) => (m.id === localId ? saved : m)));
        wsService.sendChatMessage(chatId, `ph_${uid()}`, trimmed, subChat);
      } catch {
        placeholderIdRef.current = null;
        setStreaming(false);
        setError("Failed to send. Please try again.");
      }
    },
    [activeChatId, streaming, subChat]
  );

  /** Start a requirement process inside a project chat */
  const handleStartProcess = useCallback(
    async (config, projectId) => {
      const title  = `Requirements — ${config.projectName || "New Process"}`;
      const tempId = `temp_${uid()}`;
      setActiveChatId(tempId);
      setActiveProjectId(projectId);
      setSubChat(0);
      setMessages([]);

      let chatId = tempId;
      try {
        let serverChat;
        if (projectId) {
          serverChat = await createProjectChat(projectId, title);
        } else {
          serverChat = await apiCreateChat(title);
        }
        setActiveChatId(serverChat.id);
        chatId = serverChat.id;
      } catch {
        setActiveChatId(null);
        setError("Could not create conversation. Please try again.");
        return;
      }

      setStreaming(true);
      try {
        await startReq(config, chatId);
      } catch {
        placeholderIdRef.current = null;
        setStreaming(false);
        setError("Failed to start process. Please try again.");
      }

      return chatId;
    },
    []
  );

  const openArtifactRef = useRef(null);
  useEffect(() => { openArtifactRef.current = openArtifact; }, [openArtifact]);

  const sendArtifactFeedback = useCallback((action, comment = "") => {
    const art    = openArtifactRef.current;
    if (!art) return;
    const chatId    = art.chatId || activeChatIdRef.current;
    const messageId = art.messageId || "";
    wsService.send({ type: "artifact_feedback", chatId, messageId, artifactId: art.id, action, comment });

    const optimistic = (prev) => {
      if (!prev) return null;
      return action === "accept"
        ? { ...prev, awaitingFeedback: false, accepted: true }
        : { ...prev, awaitingFeedback: false, revising: true };
    };
    setOpenArtifact(optimistic);
    setMessages((prev) =>
      prev.map((m) => {
        if (!m.artifact || m.artifact.id !== art.id) return m;
        return { ...m, artifact: optimistic(m.artifact) };
      })
    );
  }, []);

  return {
    activeChatId,
    activeProjectId,
    subChat,
    messages,
    streaming,
    openArtifact,
    loadingMessages,
    error,
    wsConnected,
    setOpenArtifact,
    setError,
    setSubChat,
    selectChat,
    clearActiveChat,
    deleteChat,
    sendMessage,
    cancelStream,
    sendArtifactFeedback,
    handleStartProcess,
  };
}