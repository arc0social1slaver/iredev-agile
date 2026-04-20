# backend/src/server/websocket/ws_handler.py
# =============================================================================
# WebSocket handler — one persistent connection per user session.
#
# Artifact lifecycle
# ──────────────────
# [interview phase]
#   InterviewerAgent → interview_complete=True
#   → supervisor routes to review_turn
#   → review_turn calls interrupt() → graph PAUSES
#   → ws_handler detects __interrupt__ → emits "artifact" (interview_record)
#   → frontend shows artifact with Accept / Request Changes
#
# [accept]
#   frontend sends artifact_feedback {action: "accept"}
#   → ws_handler resumes graph with Command(resume={approved: True})
#   → review_turn_fn returns reviewed_interview_record
#   → ws_handler emits "artifact_accepted" for interview_record
#   → graph continues: supervisor → sprint_agent_turn
#   → SprintAgent builds product_backlog
#   → ws_handler emits "artifact" (product_backlog, awaitingFeedback=True)
#   → graph PAUSES again (sprint review interrupt)
#
# [revise]
#   frontend sends artifact_feedback {action: "revise", comment: "..."}
#   → ws_handler resumes graph with Command(resume={approved: False, feedback: "..."})
#   → review_turn_fn removes interview_record, sets review_feedback
#   → supervisor routes back to interviewer_turn
#   → ws_handler emits "revision_start"
#   → interviewer re-runs, produces new interview_record
#   → graph pauses at review_turn again
#   → ws_handler emits "artifact_revised" (new interview_record)
# =============================================================================

import json
import time
import re
import threading
import uuid
import logging
from typing import Any, Callable, Dict, List, Optional

from ..data.mock_db import (
    add_message,
    save_artifact,
    update_message_artifact,
)
from ..auth.auth_utils import get_user_id_for_token_ws
from src.orchestrator import build_graph

log = logging.getLogger(__name__)

MAX_REVISIONS = 5
FEEDBACK_TIMEOUT = 0  # 0 = wait forever (user controls when to respond)


# ─────────────────────────────────────────────────────────────────────────────
# WSHandler
# ─────────────────────────────────────────────────────────────────────────────

class WSHandler:

    def __init__(self) -> None:
        self._state: dict = {}
        self._state_lock = threading.Lock()

        # { user_id → {"ws": ws, "lock": lock} }
        self.active_ws: Dict[str, Dict] = {}

        # Pending artifact context per chat — used to correlate accept/revise
        # with the last artifact that was emitted.
        # { chat_id → {artifact_key, artifact_id, message_id, iteration} }
        self._artifact_ctx: Dict[str, Dict] = {}

        self.graph = build_graph()

    # =========================================================================
    # Token streaming
    # =========================================================================

    def _stream_tokens(self, text: str):
        """Yield (token, delay) pairs for word-level streaming."""
        words = re.findall(r"\S+\s*|\n+", text)
        for word in words:
            if word.rstrip().endswith((".", "!", "?", ":")):
                delay = 0.06
            elif "\n" in word:
                delay = 0.04
            else:
                delay = 0.025
            yield word, delay

    def _send_token_stream(self, ws, lock, chat_id: str, mess_id: str,
                            text: str, role: str) -> str:
        """Stream text token-by-token; return accumulated string."""
        accum = ""
        for token, delay in self._stream_tokens(text):
            accum += token
            ok = self._send(ws, lock, {
                "type": "token",
                "chatId": chat_id,
                "messageId": mess_id,
                "token": token,
                "role": role,
            })
            if not ok:
                break
            time.sleep(delay)

        self._send(ws, lock, {"type": "done", "chatId": chat_id, "messageId": mess_id})
        return accum

    # =========================================================================
    # Workflow runner
    # =========================================================================

    def run_iredev_workflow(self, initial_state: Any, user_id: str, chat_id: str):
        """
        Stream one segment of the LangGraph workflow.

        initial_state can be:
          - A WorkflowState dict  (new segment / first run)
          - A Command(resume=...) (resuming after interrupt)
        """
        ws_entry = self.active_ws.get(user_id, {})
        ws = ws_entry.get("ws")
        lock = ws_entry.get("lock")
        if not ws or not lock:
            log.warning("[WS] run_iredev_workflow: no active ws for user=%s", user_id)
            return

        config = {"configurable": {"thread_id": chat_id}}

        # Track which artifact keys existed before this segment
        known_artifact_keys: set = set()

        try:
            for step_output in self.graph.stream(initial_state, config=config):

                # ── Graph paused at interrupt() ────────────────────────────
                if "__interrupt__" in step_output:
                    interrupt_data = step_output["__interrupt__"]
                    self._on_graph_interrupt(interrupt_data, chat_id, ws, lock)
                    break

                # ── Normal node output ─────────────────────────────────────
                for node_name, updates in step_output.items():
                    if not updates:
                        continue
                    log.debug("[WS] node=%s updates=%s", node_name, list(updates.keys()))
                    self._dispatch_node(
                        node_name, updates, user_id, chat_id, ws, lock, known_artifact_keys
                    )

        except Exception as exc:
            log.error("[WS] workflow error user=%s chat=%s: %s",
                      user_id, chat_id, exc, exc_info=True)
            self._send(ws, lock, {
                "type": "error",
                "chatId": chat_id,
                "error": str(exc),
            })

    def _on_graph_interrupt(self, interrupt_data: Any, chat_id: str, ws, lock):
        """
        Called when graph.stream() yields __interrupt__.

        At this point review_turn has already been entered and called interrupt().
        The interrupt_data contains the review payload (requirements etc.).

        We need to emit the interview_record artifact to the frontend so the
        user sees the Accept / Request Changes bar.
        """
        log.info("[WS] Graph interrupted (review gate) chat=%s", chat_id)

        # Extract interview_record from interrupt payload
        payloads = interrupt_data[0].value

        record_content = payloads.get("artifact_data")

        if record_content is None:
            log.warning("[WS] interrupt payload has unexpected shape: %s", interrupt_data)
            return

        mess_id = str(uuid.uuid4())
        artifact_id = record_content.get("id", f"interview_record_{chat_id}")

        # Build display artifact from the review payload
        artifact_display = {
            "id": artifact_id,
            "content": json.dumps(record_content, indent=2, ensure_ascii=False),
            "language": "json",
        }

        # accum = self._send_token_stream(ws, lock, chat_id, mess_id, json.dumps(record_content, indent=4), "interviewer")
        # if accum.strip():
        #     add_message(chat_id=chat_id, role="interviewer", content=accum,
        #                 messID=mess_id)

        enriched = {**artifact_display, "awaitingFeedback": True}

        ws_payload = {
            "type": "artifact",
            "chatId": chat_id,
            "messageId": mess_id,
            "artifact": artifact_display,
            "awaitingFeedback": True,
            "iteration": 1,
            "maxIterations": MAX_REVISIONS,
        }

        self._send(ws, lock, ws_payload)

        # Update context
        self._artifact_ctx[chat_id] = {
            "artifact_key": payloads.get("artifact_key", "interview_record"),
            "artifact_id": artifact_id,
            "message_id": mess_id
        }

        # Persist
        save_artifact(chat_id, mess_id, enriched)

    def _dispatch_node(self, node_name: str, updates: Dict,
                        user_id: str, chat_id: str, ws, lock,
                        known_artifact_keys: set):
        """Route node output to the correct handler."""

        if node_name == "supervisor":
            return  # routing only, nothing to emit

        if node_name in ("interviewer_turn", "enduser_turn"):
            self._handle_conversation_turn(updates, chat_id, ws, lock)

        elif node_name == "review_turn":
            # This fires AFTER interrupt resumes — contains approve/reject result
            self._handle_review_result(updates, user_id, chat_id, ws, lock)

        elif node_name == "sprint_agent_turn":
            self._handle_sprint_agent(updates, chat_id, ws, lock, known_artifact_keys)
        elif node_name == "analyst_turn":
            self._handle_analyst_turn(updates, chat_id, ws, lock)
        elif node_name == "analyst_review_turn":
            pass  # not implemented yet


    def _handle_conversation_turn(self, updates: Dict, chat_id: str, ws, lock):
        """Stream the last conversation turn (interviewer or enduser)."""
        conversation = updates.get("conversation") or []
        if not conversation:
            return

        last = conversation[-1]
        role = last.get("role", "unknown")
        content = last.get("content", "").strip()
        if not content:
            return

        mess_id = str(uuid.uuid4())
        accum = self._send_token_stream(ws, lock, chat_id, mess_id, content, role)
        if accum.strip():
            add_message(chat_id=chat_id, role=role, content=accum, messID=mess_id)

    def _handle_review_result(self, updates: Dict, user_id: str,
                               chat_id: str, ws, lock):
        """
        Handle review_turn output after interrupt resumes.

        approved=True:
          - emit artifact_accepted for interview_record
          - graph will continue → sprint_agent_turn (handled in next iteration)

        approved=False:
          - emit revision_start so frontend shows "Revising..." spinner
          - graph re-routes to interviewer_turn; next interrupt will emit artifact_revised
        """
        ctx = self._artifact_ctx.get(chat_id, {})
        artifact_id = ctx.get("artifact_id", f"interview_record_{chat_id}")
        mess_id = ctx.get("message_id", str(uuid.uuid4()))
        approved = updates.get("review_approved", False)

        if approved:
            log.info("[WS] Review APPROVED chat=%s", chat_id)


            artifact_display = {
                "id": artifact_id,
                "content": json.dumps(updates.get("artifacts", {}).get("reviewed_interview_record"), indent=2, ensure_ascii=False),
                "language": "json",
            }

            # Mark artifact as accepted in DB
            save_artifact(
                chat_id, 
                mess_id, 
                {
                    **artifact_display, 
                    "accepted": True, 
                    "awaitingFeedback": False
                }
            )
            update_message_artifact(
                mess_id, 
                {
                    **artifact_display, 
                    "accepted": True, 
                    "awaitingFeedback": False
                }
            )

            # Notify frontend
            self._send(ws, lock, {
                "type": "artifact_accepted",
                "chatId": chat_id,
                "messageId": mess_id,
                "artifactId": artifact_id,
            })

            # Clear interview_record context — sprint agent will set new context
            self._artifact_ctx.pop(chat_id, None)

        else:
            log.info("[WS] Review REJECTED chat=%s", chat_id)

    def _handle_sprint_agent(self, updates: Dict, chat_id: str, ws, lock):
        """
        Handle SprintAgent output.

        Detects which new artifact was produced and emits the appropriate event.
        After the sprint agent runs, the graph will reach review_turn (via
        supervisor) which calls interrupt() — that is handled by _on_graph_interrupt
        for the product_backlog review.

        IMPORTANT: product_backlog review uses a separate mechanism:
          - SprintAgent produces product_backlog
          - Supervisor routes to review_turn (another interrupt)
          - That interrupt emits the product_backlog artifact

        For now we emit the artifact immediately when sprint_agent produces it,
        before the review interrupt fires.
        """

        artifact_id = updates.get("artifacts", {}).get("product_backlog", {}).get("id", f"product_backlog_{chat_id}")
        product_backlog_content = json.dumps(updates.get("artifacts", {}).get("product_backlog"), indent=2, ensure_ascii=False)
        artifact_display = {
                "id": artifact_id,
                "content": product_backlog_content,
                "language": "json",
            }

        # Emit artifact card
        mess_id = str(uuid.uuid4())
        enriched = {**artifact_display, "awaitingFeedback": True}

        # accum = self._send_token_stream(ws, lock, chat_id, mess_id,
        #                                      product_backlog_content, "Sprint Agent")
        # if accum.strip():
        #     add_message(chat_id=chat_id, role="Sprint Agent",
        #                 content=accum, messID=mess_id)

        self._send(ws, lock, {
            "type": "artifact",
            "chatId": chat_id,
            "messageId": mess_id,
            "artifact": enriched,
            "awaitingFeedback": True,
            "iteration": 1,
            "maxIterations": MAX_REVISIONS,
        })

        self._artifact_ctx[chat_id] = {
            "artifact_key": "product_backlog",
            "artifact_id": artifact_id,
            "message_id": mess_id,
            "iteration": 1,
        }

        save_artifact(chat_id, mess_id, enriched)

    def _handle_analyst_turn(self, updates: Dict, chat_id: str, ws, lock):
        artifact = updates.get("artifacts", {}).get("validated_product_backlog", {})
        validated_backlog_content = json.dumps(artifact, indent=2, ensure_ascii=False)
        artifact_display = {
                "id": artifact.get("id", f"validated_backlog_{chat_id}"),
                "content": validated_backlog_content,
                "language": "json",
        }
        mess_id = str(uuid.uuid4())
        # accum = self._send_token_stream(ws, lock, chat_id, mess_id,
        #                                      validated_backlog_content, "Analyst Agent")
        # if accum.strip():
        #     add_message(chat_id=chat_id, role="Analyst Agent",
        #                 content=accum, messID=mess_id)
        enriched = {**artifact_display, "awaitingFeedback": True}
        self._send(ws, lock, {
            "type": "artifact",
            "chatId": chat_id,
            "messageId": mess_id,
            "artifact": enriched,
            "awaitingFeedback": True,
            "iteration": 1,
            "maxIterations": MAX_REVISIONS,
        })
        self._artifact_ctx[chat_id] = {
            "artifact_key": "validated_product_backlog",
            "artifact_id": artifact.get("id", f"validated_backlog_{chat_id}"),
            "message_id": mess_id,
            "iteration": 1,
        }
        save_artifact(chat_id, mess_id, enriched)


    # =========================================================================
    # Per-connection state
    # =========================================================================

    def _init(self, ws_id: int, lock: threading.Lock, user_id: str, ws: Any):
        with self._state_lock:
            self._state[ws_id] = {"lock": lock, "stop": {}}
            self.active_ws[user_id] = {"ws": ws, "lock": lock}

    def _cleanup(self, ws_id: int):
        with self._state_lock:
            self._state.pop(ws_id, None)

    def _get(self, ws_id: int) -> Optional[dict]:
        return self._state.get(ws_id)

    def _reset_stop(self, ws_id: int, chat_id: str):
        s = self._get(ws_id)
        if s:
            with self._state_lock:
                if chat_id in s["stop"]:
                    s["stop"][chat_id].clear()

    def _set_stop(self, ws_id: int, chat_id: str):
        s = self._get(ws_id)
        if s:
            with self._state_lock:
                if chat_id in s["stop"]:
                    s["stop"][chat_id].set()

    # =========================================================================
    # Thread-safe send
    # =========================================================================

    def _send(self, ws, lock: threading.Lock, payload: dict) -> bool:
        try:
            with lock:
                ws.send(json.dumps(payload))
            return True
        except Exception as exc:
            log.debug("[WS] send failed: %s", exc)
            return False

    # =========================================================================
    # Connection entry point
    # =========================================================================

    def handle_connection(self, ws):
        from flask import request as flask_req

        token = flask_req.args.get("token", "")
        user_id = get_user_id_for_token_ws(token)

        if not user_id:
            log.warning("[WS] Rejected  token_prefix=%r", token[:20])
            try:
                ws.send(json.dumps({"type": "error", "error": "Unauthorized"}))
            except Exception:
                pass
            return

        lock = threading.Lock()
        ws_id = id(ws)
        self._init(ws_id, lock, user_id, ws)
        log.info("[WS] Connected  user=%s  ws=%s", user_id, ws_id)

        try:
            self._send(ws, lock, {"type": "connected", "userId": user_id})

            while True:
                try:
                    raw = ws.receive()
                except Exception as exc:
                    log.info("[WS] receive() raised: %s  ws=%s", exc, ws_id)
                    break
                if raw is None:
                    break
                self._dispatch(ws, lock, ws_id, user_id, raw)

        except Exception as exc:
            log.error("[WS] Unhandled  user=%s  err=%s", user_id, exc, exc_info=True)
        finally:
            self._cleanup(ws_id)
            log.info("[WS] Disconnected  user=%s  ws=%s", user_id, ws_id)

    # =========================================================================
    # Frame dispatcher
    # =========================================================================

    def _dispatch(self, ws, lock, ws_id: int, user_id: str, raw: str):
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("[WS] Bad JSON  user=%s: %r", user_id, raw)
            return

        ftype = frame.get("type", "")
        log.debug("[WS] → %s  user=%s", ftype, user_id)

        if ftype == "ping":
            self._send(ws, lock, {"type": "pong"})

        elif ftype == "chat_message":
            chat_id = frame.get("chatId", "").strip()
            content = frame.get("content", "").strip()
            sub_chat = int(frame.get("subChat", 0))

            if not chat_id or not content:
                self._send(ws, lock, {
                    "type": "error",
                    "error": "chat_message requires chatId and content",
                })
                return

            self._reset_stop(ws_id, chat_id)

            if sub_chat in (1, 2):
                role = "interviewer" if sub_chat == 1 else "enduser"
                mess_id = str(uuid.uuid4())
                resp = f"Hello from {role.capitalize()}"
                accum = self._send_token_stream(ws, lock, chat_id, mess_id, resp, role)
                if accum.strip():
                    add_message(chat_id=chat_id, role=role, content=accum,
                                messID=mess_id, subChatID=sub_chat)

        elif ftype == "stop_stream":
            chat_id = frame.get("chatId", "").strip()
            if chat_id:
                self._set_stop(ws_id, chat_id)

        elif ftype == "artifact_feedback":
            self._on_artifact_feedback(ws, lock, user_id, frame)

        else:
            log.debug("[WS] Unknown frame type='%s'", ftype)

    def _on_artifact_feedback(self, ws, lock, user_id: str, frame: dict):
        """Handle accept / revise from frontend."""
        chat_id = frame.get("chatId", "").strip()
        artifact_id = frame.get("artifactId", "").strip()
        action = frame.get("action", "").strip()
        comment = frame.get("comment", "").strip()

        if not artifact_id or action not in ("accept", "revise"):
            self._send(ws, lock, {
                "type": "error",
                "error": "artifact_feedback requires artifactId and action (accept|revise)",
            })
            return

        from langgraph.types import Command

        if action == "accept":
            resume_cmd = Command(resume={"approved": True, "feedback": ""})
        else:
            if not comment:
                self._send(ws, lock, {
                    "type": "error",
                    "error": "revise action requires a non-empty comment",
                })
                return
            resume_cmd = Command(resume={"approved": False, "feedback": comment})

        log.info("[WS] artifact_feedback action=%s chat=%s artifact=%s",
                 action, chat_id, artifact_id)

        # Run in background thread — never block the receive loop
        t = threading.Thread(
            target=self.run_iredev_workflow,
            args=(resume_cmd, user_id, chat_id),
            daemon=True,
        )
        t.start()


ws_handler = WSHandler()