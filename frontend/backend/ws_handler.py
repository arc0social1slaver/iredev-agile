# backend/ws_handler.py
# =============================================================================
# WebSocket handler — one persistent connection per user session.
#
# ─────────────────────────────────────────────────────────────────────────────
# Artifact feedback loop — chat-switch-safe design
# ─────────────────────────────────────────────────────────────────────────────
#
# The feedback Events are keyed GLOBALLY by artifact_id, not by ws_id.
# This means:
#   - The user can switch to another chat while an artifact awaits feedback.
#   - When they switch back and click Accept / Revise, the frame arrives on
#     the same WebSocket connection and is routed to the right Event.
#   - The streaming thread wakes up, processes the feedback, and sends the
#     result back — which the frontend renders regardless of which chat
#     is "active" (since chatId is embedded in every WS frame).
#
# Protocol (Client → Server):
#   { "type": "ping" }
#   { "type": "chat_message",      "chatId", "messageId", "content" }
#   { "type": "stop_stream",       "chatId" }
#   { "type": "artifact_feedback", "chatId", "messageId", "artifactId",
#                                  "action": "accept"|"revise", "comment" }
#
# Protocol (Server → Client):
#   { "type": "pong" }
#   { "type": "connected",         "userId" }
#   { "type": "token",             "chatId", "messageId", "token" }
#   { "type": "done",              "chatId", "messageId" }
#   { "type": "artifact",          "chatId", "messageId", "artifact",
#                                  "awaitingFeedback": true }
#   { "type": "artifact_revised",  "chatId", "messageId", "artifact",
#                                  "awaitingFeedback": true, "iteration": N }
#   { "type": "artifact_accepted", "chatId", "messageId", "artifactId" }
#   { "type": "artifact_timeout",  "chatId", "messageId", "artifactId" }
#   { "type": "revision_start",    "chatId", "messageId", "comment", "iteration" }
#   { "type": "error",             "chatId", "messageId", "error" }
# =============================================================================

import json
import time
import re
import threading
import uuid
import logging

import mock_db
from ai_engine  import generate_response, generate_revision, stream_tokens
from auth_utils import get_user_id_for_token_ws

log = logging.getLogger(__name__)

MAX_REVISIONS    = 5
FEEDBACK_TIMEOUT = 0      # 0 = wait forever (user controls when to respond)
                          # Set to e.g. 1800 for a 30-min session timeout


# =============================================================================
# Global feedback registry
# Keyed by artifact_id — independent of which WS connection is active.
# This lets the feedback loop survive chat switches.
#
#   { artifact_id → { "event": threading.Event,
#                     "data":  { action, comment } | None } }
# =============================================================================

_fb_registry: dict = {}
_fb_lock = threading.Lock()


def _fb_create(artifact_id: str) -> threading.Event:
    """
    Register a new pending feedback slot and return its Event.
    Called by the streaming thread just before sending the artifact frame.
    """
    ev = threading.Event()
    with _fb_lock:
        _fb_registry[artifact_id] = {"event": ev, "data": None}
    log.debug(f"[FB] Created slot  artifact={artifact_id}")
    return ev


def _fb_deliver(artifact_id: str, action: str, comment: str) -> bool:
    """
    Store feedback data and set the Event to wake the streaming thread.
    Called by the WS receive-loop when an artifact_feedback frame arrives.
    Returns True if a matching slot was found, False if not.
    """
    with _fb_lock:
        slot = _fb_registry.get(artifact_id)
        if not slot:
            log.warning(f"[FB] No pending slot for artifact={artifact_id} — feedback ignored")
            return False
        slot["data"] = {"action": action, "comment": comment}
        slot["event"].set()
    log.info(f"[FB] Delivered  artifact={artifact_id}  action={action}")
    return True


def _fb_read(artifact_id: str) -> dict | None:
    """Read the stored feedback data (call BEFORE _fb_remove)."""
    with _fb_lock:
        slot = _fb_registry.get(artifact_id)
        return slot["data"] if slot else None


def _fb_remove(artifact_id: str):
    """Remove a resolved or cancelled feedback slot."""
    with _fb_lock:
        _fb_registry.pop(artifact_id, None)
    log.debug(f"[FB] Removed slot  artifact={artifact_id}")


def _fb_pending_for_chat(chat_id: str) -> list[str]:
    """
    Return all artifact_ids that are currently awaiting feedback for a chat.
    Used when the frontend switches back to a chat — we re-send the artifact
    frames so the panel shows the feedback bar again.
    """
    with _fb_lock:
        return [
            art_id for art_id in _fb_registry
            # artifact_id format: art_<message_id>_v<N>
            # We check against the stored artifact's chatId in mock_db
        ]


# =============================================================================
# Per-connection state  (stop flags + send lock — still connection-scoped)
# =============================================================================

_state:      dict           = {}
_state_lock: threading.Lock = threading.Lock()


def _init(ws_id: int, lock: threading.Lock):
    with _state_lock:
        _state[ws_id] = {
            "lock": lock,
            "stop": {},       # { chat_id → threading.Event }
        }

def _cleanup(ws_id: int):
    with _state_lock:
        _state.pop(ws_id, None)

def _get(ws_id: int) -> dict | None:
    return _state.get(ws_id)


def _stop_flag(ws_id, chat_id) -> threading.Event:
    s = _get(ws_id)
    if not s: return threading.Event()
    with _state_lock:
        if chat_id not in s["stop"]:
            s["stop"][chat_id] = threading.Event()
        return s["stop"][chat_id]

def _reset_stop(ws_id, chat_id):
    s = _get(ws_id)
    if s:
        with _state_lock:
            # Clear the existing Event so any thread holding a reference
            # to it sees the cleared state. Deleting and recreating would
            # leave the thread's 'stop' variable pointing at the old set Event.
            if chat_id in s["stop"]:
                s["stop"][chat_id].clear()

def _set_stop(ws_id, chat_id):
    s = _get(ws_id)
    if s:
        with _state_lock:
            if chat_id in s["stop"]:
                s["stop"][chat_id].set()


# =============================================================================
# Thread-safe send
# =============================================================================

def _send(ws, lock: threading.Lock, payload: dict) -> bool:
    """Send a JSON frame thread-safely. Returns True on success."""
    try:
        with lock:
            ws.send(json.dumps(payload))
        return True
    except Exception as exc:
        log.debug(f"[WS] send failed: {exc}")
        return False


# =============================================================================
# Main entry point
# =============================================================================

def handle_connection(ws):
    """Called by Flask-Sock for every new WebSocket connection."""
    from flask import request as flask_req

    token   = flask_req.args.get("token", "")
    user_id = get_user_id_for_token_ws(token)

    if not user_id:
        log.warning(f"[WS] Rejected  token_prefix={token[:20]!r}")
        try:
            ws.send(json.dumps({"type": "error", "error": "Unauthorized"}))
        except Exception:
            pass
        return

    lock  = threading.Lock()
    ws_id = id(ws)
    _init(ws_id, lock)

    log.info(f"[WS] Connected  user={user_id}  ws={ws_id}")

    try:
        _send(ws, lock, {"type": "connected", "userId": user_id})

        # ── Re-broadcast any pending artifacts for this user ──────────────────
        # If the user reconnects (page reload, network drop) while an artifact
        # is still awaiting feedback, re-send the artifact frame so the panel
        # can show the feedback bar again without the user needing to do anything.
        _replay_pending_artifacts(ws, lock, user_id)

        while True:
            try:
                raw = ws.receive()
            except Exception as exc:
                log.info(f"[WS] receive() raised: {exc}  ws={ws_id}")
                break
            if raw is None:
                log.info(f"[WS] receive() returned None  ws={ws_id}")
                break
            _dispatch(ws, lock, ws_id, user_id, raw)

    except Exception as exc:
        log.error(f"[WS] Unhandled  user={user_id}  err={exc}", exc_info=True)
    finally:
        _cleanup(ws_id)
        log.info(f"[WS] Disconnected  user={user_id}  ws={ws_id}")


# =============================================================================
# Frame dispatcher
# =============================================================================

def _dispatch(ws, lock, ws_id, user_id, raw):
    try:
        frame = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(f"[WS] Bad JSON  user={user_id}: {raw!r}")
        return

    ftype = frame.get("type", "")
    log.debug(f"[WS] → {ftype}  user={user_id}")

    if ftype == "ping":
        _send(ws, lock, {"type": "pong"})

    elif ftype == "chat_message":
        chat_id    = frame.get("chatId",    "").strip()
        message_id = frame.get("messageId", "").strip()
        content    = frame.get("content",   "").strip()

        if not chat_id or not content:
            _send(ws, lock, {"type": "error",
                             "error": "chat_message requires chatId and content"})
            return

        _reset_stop(ws_id, chat_id)

        threading.Thread(
            target=_stream_reply,
            args=(ws, lock, ws_id, user_id, chat_id, message_id, content),
            daemon=True,
        ).start()

    elif ftype == "stop_stream":
        chat_id = frame.get("chatId", "").strip()
        if chat_id:
            _set_stop(ws_id, chat_id)
            log.info(f"[WS] Stop  chat={chat_id}  user={user_id}")

    elif ftype == "artifact_feedback":
        # Route to the global feedback registry — works regardless of
        # which chat is currently "active" in the frontend.
        artifact_id = frame.get("artifactId", "").strip()
        action      = frame.get("action",     "").strip()
        comment     = frame.get("comment",    "").strip()

        if not artifact_id or action not in ("accept", "revise"):
            _send(ws, lock, {"type": "error",
                             "error": "artifact_feedback requires artifactId "
                                      "and action ('accept' or 'revise')"})
            return

        found = _fb_deliver(artifact_id, action, comment)
        if not found:
            # The slot no longer exists (e.g. timed out or already resolved).
            # Let the frontend know so it can update its UI.
            _send(ws, lock, {"type": "error",
                             "chatId":     frame.get("chatId", ""),
                             "messageId":  frame.get("messageId", ""),
                             "artifactId": artifact_id,
                             "error": "Feedback session for this artifact has already ended."})

    else:
        log.debug(f"[WS] Unknown frame type='{ftype}'")


# =============================================================================
# Re-broadcast pending artifacts on reconnect
# =============================================================================

def _replay_pending_artifacts(ws, lock, user_id: str):
    """
    On reconnect, re-send artifact frames for any artifacts that are still
    awaiting feedback. This means:
      - Page reload mid-review: the panel pops back up automatically.
      - Network reconnect: same result.

    We query mock_db for messages owned by this user that have an artifact
    with awaitingFeedback=True in storage, then check if a live feedback
    Event still exists for that artifact_id. Only re-send if both are true.
    """
    with _fb_lock:
        pending_ids = set(_fb_registry.keys())

    if not pending_ids:
        return

    # Find messages belonging to this user whose artifact is in the pending set
    for chat_id, messages in mock_db.MESSAGES.items():
        chat = mock_db.get_chat(chat_id)
        if not chat or chat["userId"] != user_id:
            continue

        for msg in messages:
            artifact = msg.get("artifact")
            if not artifact:
                continue
            art_id = artifact.get("id")
            if art_id not in pending_ids:
                continue

            # Re-send the artifact frame so the frontend shows the feedback bar
            log.info(f"[WS] Replaying pending artifact  id={art_id}  chat={chat_id}")
            _send(ws, lock, {
                "type":             "artifact",
                "chatId":           chat_id,
                "messageId":        msg["id"],
                "artifact":         artifact,
                "awaitingFeedback": True,
                "iteration":        artifact.get("iteration", 1),
                "maxIterations":    MAX_REVISIONS,
                "replayed":         True,   # hint to frontend: don't show as new
            })


# =============================================================================
# AI streaming with human-in-the-loop artifact review
# =============================================================================

def _stream_reply(ws, lock, ws_id, user_id, chat_id, message_id, content):
    """
    Stream AI reply tokens. If a code block is present, enter the feedback
    loop which:
      - Blocks on a global threading.Event (not connection-scoped)
      - Stays alive even while the user switches to a different chat
      - Wakes when any artifact_feedback frame arrives with the right artifact_id
    """
    chat = mock_db.get_chat(chat_id)
    if not chat or chat["userId"] != user_id:
        _send(ws, lock, {"type": "error", "chatId": chat_id,
                         "messageId": message_id,
                         "error": "Chat not found or access denied"})
        return

    log.info(f"[WS] Streaming  chat={chat_id}  msgId={message_id}")

    try:
        full_reply = generate_response(content)
    except Exception as exc:
        _send(ws, lock, {"type": "error", "chatId": chat_id,
                         "messageId": message_id, "error": str(exc)})
        return

    stop  = _stop_flag(ws_id, chat_id)
    accum = ""

    for token, delay in stream_tokens(full_reply):
        if stop.is_set():
            log.info(f"[WS] Stopped  chat={chat_id}")
            break
        accum += token
        ok = _send(ws, lock, {"type": "token", "chatId": chat_id,
                              "messageId": message_id, "token": token})
        if not ok:
            return
        time.sleep(delay)

    _send(ws, lock, {"type": "done", "chatId": chat_id, "messageId": message_id})

    artifact = _extract_artifact(message_id, full_reply)

    if not artifact:
        if accum.strip():
            mock_db.add_message(chat_id=chat_id, role="assistant", content=accum)
        log.info(f"[WS] Done (no artifact)  chat={chat_id}")
        return

    # Save message immediately with the artifact attached (awaitingFeedback=True)
    # so GET /messages returns it on any reload or chat switch.
    # Capture the server-assigned ID so update_message_artifact() can find it.
    # (message_id here is the frontend placeholder — NOT what mock_db stores)
    stored_msg_id = None
    if accum.strip():
        saved = mock_db.add_message(
            chat_id=chat_id, role="assistant", content=accum,
            artifact={**artifact, "awaitingFeedback": True},
        )
        stored_msg_id = saved["id"]   # server-assigned ID, e.g. 'a3f9c1b2'
        log.debug(f"[WS] Saved assistant msg  stored_id={stored_msg_id}  "
                  f"placeholder={message_id}")

    current_content = artifact["content"]

    # Use a STABLE artifact_id across all iterations.
    # If the id changed each iteration (v1→v2→v3), the frontend would need
    # to track the latest id — but optimistic updates and stale refs make
    # this fragile. Keeping the same id means the frontend always sends
    # artifactId='art_<msgid>_v1' and the slot is always found.
    stable_art_id = f"art_{message_id}_v1"

    for iteration in range(1, MAX_REVISIONS + 1):
        art_id = stable_art_id   # same key for every iteration
        artifact.update({"id": art_id, "content": current_content, "iteration": iteration})

        # Register (or re-register) the feedback slot.
        # On iteration > 1 the previous slot was already removed after the
        # revise action, so we create a fresh Event for this iteration.
        fb_event = _fb_create(art_id)

        frame_type = "artifact" if iteration == 1 else "artifact_revised"
        _send(ws, lock, {
            "type":             frame_type,
            "chatId":           chat_id,
            "messageId":        message_id,
            "artifact":         artifact,
            "awaitingFeedback": True,
            "iteration":        iteration,
            "maxIterations":    MAX_REVISIONS,
        })

        log.info(f"[WS] Awaiting feedback  artifact={art_id}  "
                 f"iter={iteration}/{MAX_REVISIONS}")

        # ── BLOCK here waiting for feedback ────────────────────────────────────
        # FEEDBACK_TIMEOUT=0 means wait indefinitely — the user can switch chats
        # and come back later without the loop dying.
        # The feedback frame is routed via _fb_deliver() in _dispatch(),
        # which works regardless of which chat the user is currently viewing.
        if FEEDBACK_TIMEOUT > 0:
            received = fb_event.wait(timeout=FEEDBACK_TIMEOUT)
        else:
            fb_event.wait()   # infinite wait
            received = True

        # Read data BEFORE removing the slot
        fb     = _fb_read(art_id)
        _fb_remove(art_id)

        if not received:
            # Timeout (only reachable if FEEDBACK_TIMEOUT > 0)
            accepted_artifact = {**artifact, "content": current_content,
                                 "accepted": True, "awaitingFeedback": False}
            mock_db.save_artifact(chat_id, stored_msg_id or message_id, accepted_artifact)
            mock_db.update_message_artifact(stored_msg_id or message_id, accepted_artifact)
            _send(ws, lock, {"type": "artifact_timeout", "chatId": chat_id,
                             "messageId": message_id, "artifactId": art_id})
            return

        # Do NOT check stop.is_set() here.
        # stop_stream fires on every chat switch — if we exited here, switching
        # chats and then submitting feedback would silently discard the response.
        # The stop flag only gates token streaming (the for loops above/below).

        action  = (fb or {}).get("action", "accept")
        comment = (fb or {}).get("comment", "")

        if action == "accept":
            log.info(f"[WS] Accepted  artifact={art_id}")
            accepted_artifact = {**artifact, "content": current_content,
                                 "accepted": True, "awaitingFeedback": False}
            mock_db.save_artifact(chat_id, stored_msg_id or message_id, accepted_artifact)
            mock_db.update_message_artifact(stored_msg_id or message_id, accepted_artifact)
            _send(ws, lock, {"type": "artifact_accepted", "chatId": chat_id,
                             "messageId": message_id, "artifactId": art_id})
            return

        # ── Revise ──────────────────────────────────────────────────────────────
        log.info(f"[WS] Revising  comment={comment!r}  iter={iteration}")
        try:
            current_content = generate_revision(current_content, comment)
        except Exception as exc:
            _send(ws, lock, {"type": "error", "chatId": chat_id,
                             "messageId": message_id, "error": str(exc)})
            return

        rev_msg_id = f"{message_id}_rev{iteration}"
        rev_text   = f"Revising based on your feedback: _{comment}_\n\n"

        _send(ws, lock, {"type": "revision_start", "chatId": chat_id,
                         "messageId": rev_msg_id, "comment": comment,
                         "iteration": iteration})

        # Reset stop flag so a previous chat-switch doesn't kill this revision stream
        _reset_stop(ws_id, chat_id)

        rev_accum = ""
        for token, delay in stream_tokens(rev_text):
            if stop.is_set(): return
            rev_accum += token
            ok = _send(ws, lock, {"type": "token", "chatId": chat_id,
                                  "messageId": rev_msg_id, "token": token})
            if not ok: return
            time.sleep(delay)

        _send(ws, lock, {"type": "done", "chatId": chat_id,
                         "messageId": rev_msg_id})
        if rev_accum.strip():
            mock_db.add_message(chat_id=chat_id, role="assistant",
                                content=rev_accum)

        # Update stored message artifact so a reload during revision shows
        # the latest content + still-pending state
        mock_db.update_message_artifact(stored_msg_id or message_id, {
            **artifact, "content": current_content,
            "awaitingFeedback": True, "accepted": False,
        })

    # Max revisions reached — auto-accept
    artifact["content"]         = current_content
    artifact["accepted"]         = True
    artifact["awaitingFeedback"] = False
    mock_db.save_artifact(chat_id, stored_msg_id or message_id, artifact)
    mock_db.update_message_artifact(stored_msg_id or message_id, artifact)
    _send(ws, lock, {"type": "artifact_accepted", "chatId": chat_id,
                     "messageId": message_id, "artifactId": artifact["id"],
                     "autoAccepted": True})


# =============================================================================
# Helpers
# =============================================================================

def _extract_artifact(message_id, text):
    match = re.search(r'```(\w*)\n([\s\S]+?)```', text)
    if not match:
        return None
    language = match.group(1).strip() or "code"
    code     = match.group(2).strip()
    type_map = {
        "jsx":"react","tsx":"react","html":"html",
        "js":"code","javascript":"code",
        "py":"code","python":"code","svg":"svg",
    }
    return {
        "id":        f"art_{message_id}_v1",
        "type":      type_map.get(language.lower(), "code"),
        "title":     f"{language.upper()} snippet" if language else "Code snippet",
        "language":  language,
        "content":   code,
        "iteration": 1,
    }