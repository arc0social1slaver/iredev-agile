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
from typing import Dict, Any

from ..data.mock_db import (
    add_message,
    save_artifact,
    update_message_artifact
)
from ..auth.auth_utils import get_user_id_for_token_ws
from src.orchestrator import build_graph

log = logging.getLogger(__name__)

MAX_REVISIONS = 5
FEEDBACK_TIMEOUT = 0  # 0 = wait forever (user controls when to respond)
# Set to e.g. 1800 for a 30-min session timeout


class WSHandler:

    def __init__(self) -> None:

        self._fb_registry: dict = {}
        self._fb_lock = threading.Lock()

        self._state: dict = {}
        self._state_lock: threading.Lock = threading.Lock()

        self.graph = build_graph()
        self.active_ws = {}

    def send_token(self, ws, lock, chat_id, messId, full_response, role):
        accum = ""

        for token, delay in self.stream_tokens(full_response):
            accum += token
            ok = self._send(
                ws,
                lock,
                {
                    "type": "token",
                    "chatId": chat_id,
                    "messageId": messId,
                    "token": token,
                    "role": role,
                },
            )
            if not ok:
                break
            time.sleep(delay)

        self._send(
            ws,
            lock,
            {
                "type": "done",
                "chatId": chat_id,
                "messageId": messId,
            },
        )
        return accum
    
    def stream_tokens(self, text: str):
        """
        Split text into word-level tokens and yield each with a realistic delay.

        Yields: (token: str, delay: float)

        Callers:
            for token, delay in stream_tokens(text):
                time.sleep(delay)
                ws.send(token)
        """
        # Keep whitespace attached to each word so the client reconstructs faithfully
        words = re.findall(r"\S+\s*|\n+", text)

        for word in words:
            if word.rstrip().endswith((".", "!", "?", ":")):
                delay = 0.06  # longer pause after sentence-ending punctuation
            elif "\n" in word:
                delay = 0.04  # medium pause after newline
            else:
                delay = 0.025  # fast for regular words

            yield word, delay

    def run_iredev_workflow(self, initial_state: Any, user_id, chat_id):
        cur_ws = self.active_ws[user_id].get("ws")
        cur_lock = self.active_ws[user_id].get("lock")
        config = {"configurable": {"thread_id": chat_id}}
        for step_output in self.graph.stream(initial_state, config=config):
            if "__interrupt__" in step_output:
                break
            for node_name, updates in step_output.items():
                if updates:
                    if node_name != "sprint_agent_turn" and node_name != "review":
                        conversation = updates.get("conversation")
                        if conversation:
                            last = conversation[-1]
                            role = last.get("role", "unknown")
                            messId = str(uuid.uuid4())
                            accum = self.send_token(
                                cur_ws,
                                cur_lock,
                                chat_id,
                                messId,
                                last.get("content", ""),
                                role,
                            )
                            if isinstance(accum, str) and accum.strip():
                                add_message(
                                    chat_id=chat_id,
                                    role=role,
                                    content=accum,
                                    messID=messId,
                                )
                    elif node_name == "sprint_agent_turn":
                        import json

                        artifacts = updates.get("artifacts") or {}
                        messId = updates.get("metadata", {}).get("messID")
                        feedback = updates.get("review_feedback")
                        review_approved = updates.get("review_approved")
                        accum = None
                        # log.info(f"{feedback} and {review_approved}")

                        if (
                            not "review_feedback" in updates
                            and not "review_approved" in updates
                        ):
                            accum = self.send_token(
                                cur_ws,
                                cur_lock,
                                chat_id,
                                messId,
                                json.dumps(artifacts, indent=4),
                                "Sprint Agent",
                            )
                        artifact_display = {
                            "id": artifacts.get("product_backlog", {}).get("id", ""),
                            "content": json.dumps(
                                artifacts.get("product_backlog", {}), indent=4
                            ),
                            "language": "json",
                        }
                        # log.info(json.dumps(artifact_display, indent=4, default=str))
                        if feedback and review_approved == False:
                            self._send(
                                cur_ws,
                                cur_lock,
                                {
                                    "type": "artifact_revised",
                                    "chatId": chat_id,
                                    "messageId": messId,
                                    "artifact": artifact_display,
                                    "awaitingFeedback": True,
                                    "iteration": 1,
                                    "maxIterations": MAX_REVISIONS,
                                },
                            )
                        elif review_approved == True:
                            self._send(
                                cur_ws,
                                cur_lock,
                                {
                                    "type": "artifact_accepted",
                                    "chatId": chat_id,
                                    "messageId": messId,
                                    "artifactId": artifacts.get(
                                        "product_backlog", {}
                                    ).get("id", ""),
                                },
                            )
                        else:
                            self._send(
                                cur_ws,
                                cur_lock,
                                {
                                    "type": "artifact",
                                    "chatId": chat_id,
                                    "messageId": messId,
                                    "artifact": artifact_display,
                                    "awaitingFeedback": True,
                                    "iteration": 1,
                                    "maxIterations": MAX_REVISIONS,
                                },
                            )
                        if isinstance(accum, str) and accum.strip():
                            save_artifact(
                                chat_id,
                                messId,
                                artifact={
                                    **artifact_display,
                                    "awaitingFeedback": True,
                                },
                            )
                            add_message(
                                chat_id=chat_id,
                                role=role,
                                content=json.dumps(artifacts, indent=4),
                                artifact={
                                    **artifact_display,
                                    "awaitingFeedback": True,
                                },
                                messID=messId,
                            )
                        elif review_approved == True:
                            save_artifact(
                                chat_id,
                                messId,
                                artifact={
                                    **artifact_display,
                                    "accepted": True,
                                    "awaitingFeedback": False,
                                },
                            )
                            update_message_artifact(
                                message_id=messId,
                                artifact={
                                    **artifact_display,
                                    "accepted": True,
                                    "awaitingFeedback": False,
                                },
                            )
                        else:
                            save_artifact(
                                chat_id,
                                messId,
                                artifact={
                                    **artifact_display,
                                    "awaitingFeedback": True,
                                },
                            )
                            update_message_artifact(
                                message_id=messId,
                                artifact={
                                    **artifact_display,
                                    "awaitingFeedback": True,
                                },
                            )
                        # updates.pop("review_feedback", None)
                        # updates.get("review_approved", None)
    
    # =============================================================================
    # Per-connection state  (stop flags + send lock — still connection-scoped)
    # =============================================================================

    def _init(self, ws_id: int, lock: threading.Lock, user_id: str, ws: Any):
        with self._state_lock:
            self._state[ws_id] = {
                "lock": lock,
                "stop": {},  # { chat_id → threading.Event }
            }
            self.active_ws[user_id] = {"ws": ws, "lock": lock}

    def _cleanup(self, ws_id: int):
        with self._state_lock:
            self._state.pop(ws_id, None)

    def _get(self, ws_id: int) -> dict | None:
        return self._state.get(ws_id)

    def _stop_flag(self, ws_id, chat_id) -> threading.Event:
        s = self._get(ws_id)
        if not s:
            return threading.Event()
        with self._state_lock:
            if chat_id not in s["stop"]:
                s["stop"][chat_id] = threading.Event()
            return s["stop"][chat_id]

    def _reset_stop(self, ws_id, chat_id):
        s = self._get(ws_id)
        if s:
            with self._state_lock:
                # Clear the existing Event so any thread holding a reference
                # to it sees the cleared state. Deleting and recreating would
                # leave the thread's 'stop' variable pointing at the old set Event.
                if chat_id in s["stop"]:
                    s["stop"][chat_id].clear()

    def _set_stop(self, ws_id, chat_id):
        s = self._get(ws_id)
        if s:
            with self._state_lock:
                if chat_id in s["stop"]:
                    s["stop"][chat_id].set()

    # =============================================================================
    # Thread-safe send
    # =============================================================================

    def _send(self, ws, lock: threading.Lock, payload: dict) -> bool:
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

    def handle_connection(self, ws):
        """Called by Flask-Sock for every new WebSocket connection."""
        from flask import request as flask_req

        token = flask_req.args.get("token", "")
        user_id = get_user_id_for_token_ws(token)

        if not user_id:
            log.warning(f"[WS] Rejected  token_prefix={token[:20]!r}")
            try:
                ws.send(json.dumps({"type": "error", "error": "Unauthorized"}))
            except Exception:
                pass
            return

        lock = threading.Lock()
        ws_id = id(ws)
        self._init(ws_id, lock, user_id, ws)

        log.info(f"[WS] Connected  user={user_id}  ws={ws_id}")

        try:
            self._send(ws, lock, {"type": "connected", "userId": user_id})

            while True:
                try:
                    raw = ws.receive()
                except Exception as exc:
                    log.info(f"[WS] receive() raised: {exc}  ws={ws_id}")
                    break
                if raw is None:
                    log.info(f"[WS] receive() returned None  ws={ws_id}")
                    break
                self._dispatch(ws, lock, ws_id, user_id, raw)

        except Exception as exc:
            log.error(f"[WS] Unhandled  user={user_id}  err={exc}", exc_info=True)
        finally:
            self._cleanup(ws_id)
            log.info(f"[WS] Disconnected  user={user_id}  ws={ws_id}")

    # =============================================================================
    # Frame dispatcher
    # =============================================================================

    def _dispatch(self, ws, lock, ws_id, user_id, raw):
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            log.warning(f"[WS] Bad JSON  user={user_id}: {raw!r}")
            return

        ftype = frame.get("type", "")
        log.debug(f"[WS] → {ftype}  user={user_id}")

        if ftype == "ping":
            self._send(ws, lock, {"type": "pong"})

        elif ftype == "chat_message":
            chat_id = frame.get("chatId", "").strip()
            message_id = frame.get("messageId", "").strip()
            content = frame.get("content", "").strip()
            subChat = int(frame.get("subChat", 0))

            if not chat_id or not content:
                self._send(
                    ws,
                    lock,
                    {
                        "type": "error",
                        "error": "chat_message requires chatId and content",
                    },
                )
                return

            self._reset_stop(ws_id, chat_id)

            response = ""
            role = "assistant"
            if subChat == 1:
                response = "This is hello from Interviewer"
                role = "interviewer"
            elif subChat == 2:
                response = "This is hello from EndUser"
                role = "enduser"

            messId = str(uuid.uuid4())
            accum = self.send_token(
                ws,
                lock,
                chat_id,
                messId,
                response,
                role,
            )
            if isinstance(accum, str) and accum.strip():
                add_message(
                    chat_id=chat_id,
                    role=role,
                    content=accum,
                    messID=messId,
                    subChatID=subChat,
                )
        elif ftype == "stop_stream":
            chat_id = frame.get("chatId", "").strip()
            if chat_id:
                self._set_stop(ws_id, chat_id)
                log.info(f"[WS] Stop  chat={chat_id}  user={user_id}")

        elif ftype == "artifact_feedback":
            # Route to the global feedback registry — works regardless of
            # which chat is currently "active" in the frontend.
            chat_id = frame.get("chatId", "").strip()
            artifact_id = frame.get("artifactId", "").strip()
            action = frame.get("action", "").strip()
            comment = frame.get("comment", "").strip()
            # human_user_queue = self.active_human_queue.get(user_id)

            if not artifact_id or action not in ("accept", "revise"):
                self._send(
                    ws,
                    lock,
                    {
                        "type": "error",
                        "error": "artifact_feedback requires artifactId "
                        "and action ('accept' or 'revise')",
                    },
                )
                return

            from langgraph.types import Command

            self.run_iredev_workflow(
                Command(resume={"action": action, "feedback": comment}),
                user_id,
                chat_id,
            )
        else:
            log.debug(f"[WS] Unknown frame type='{ftype}'")

ws_handler = WSHandler()
