# backend/routes/chat_routes.py
# =============================================================================
# Chat REST endpoints (no streaming here — streaming is handled by WebSocket).
#
#   GET    /api/chats                            List top-level chats (no project)
#   POST   /api/chats                            Create a top-level chat
#   DELETE /api/chats/<chat_id>                  Delete a chat
#   GET    /api/chats/<chat_id>/<sub>/messages   List messages
#   POST   /api/chats/<chat_id>/<sub>/messages   Save a user message
#   POST   /api/chats/process/start/<chat_id>    Start requirement process
# =============================================================================

import uuid
from flask import Blueprint, request, jsonify
from ..data import mock_db
from ..auth.auth_utils import require_auth
from ..websocket.ws_handler import ws_handler
import logging

from concurrent.futures import ThreadPoolExecutor


logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor()
pending_taks = {}

chat_bp = Blueprint("chat", __name__)


# =============================================================================
# Conversations
# =============================================================================


@chat_bp.route("", methods=["GET"])
@require_auth
def list_chats(current_user):
    """
    GET /api/chats
    Return top-level chats (not inside any project) for the authenticated user.
    """
    chats = mock_db.get_chats_for_user(current_user["id"])
    return jsonify(sorted(chats, key=lambda c: c["createdAt"], reverse=True)), 200


@chat_bp.route("", methods=["POST"])
@require_auth
def create_chat(current_user):
    """
    POST /api/chats
    Body: { "title": "My chat", "projectId": "<optional>" }
    """
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    project_id = (data.get("projectId") or "").strip() or None

    if not title:
        return jsonify({"error": "Validation error", "message": "title is required."}), 400

    # If projectId given, verify ownership
    if project_id:
        project = mock_db.get_project(project_id)
        if not project:
            return jsonify({"error": "Not found", "message": f"Project '{project_id}' not found."}), 404
        if project["userId"] != current_user["id"]:
            return jsonify({"error": "Forbidden", "message": "You don't own this project."}), 403

    chat = mock_db.create_chat(user_id=current_user["id"], title=title, project_id=project_id)
    return jsonify(chat), 201


@chat_bp.route("/<chat_id>", methods=["DELETE"])
@require_auth
def delete_chat(current_user, chat_id):
    """DELETE /api/chats/<chat_id>"""
    chat = mock_db.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Not found", "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this chat."}), 403

    mock_db.delete_chat(chat_id)
    return jsonify({"ok": True}), 200


# =============================================================================
# Messages
# =============================================================================


@chat_bp.route("/<chat_id>/<sub_chat_id>/messages", methods=["GET"])
@require_auth
def list_messages(current_user, chat_id, sub_chat_id):
    chat = mock_db.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Not found", "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this chat."}), 403

    return jsonify(mock_db.get_messages(chat_id, sub_chat_id)), 200


@chat_bp.route("/<chat_id>/<sub_chat_id>/messages", methods=["POST"])
@require_auth
def save_message(current_user, chat_id, sub_chat_id):
    chat = mock_db.get_chat(chat_id)
    if not chat:
        return jsonify({"error": "Not found", "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this chat."}), 403

    data = request.get_json(silent=True) or {}
    role = (data.get("role") or "").strip()
    content = (data.get("content") or "").strip()

    if role not in ("user", "assistant"):
        return jsonify({"error": "Validation error", "message": "role must be 'user' or 'assistant'."}), 400
    if not content:
        return jsonify({"error": "Validation error", "message": "content is required."}), 400

    message = mock_db.add_message(chat_id=chat_id, role=role, content=content, subChatID=sub_chat_id)
    return jsonify(message), 201


@chat_bp.route("/process/start/<chat_id>", methods=["POST"])
@require_auth
def start(current_user, chat_id):
    req_id = str(uuid.uuid4())
    data = request.get_json(silent=True) or {}
    projDescr = data.get("projectDescription", "").strip()
    if not projDescr:
        return jsonify({"error": "Validation error", "message": "Project Description is required."}), 400

    initial_state = {
        # ── Session ───────────────────────────────────────────────────────
        "session_id": req_id,
        "project_description": projDescr,
        # ── Phase ─────────────────────────────────────────────────────────
        "system_phase": "sprint_zero_planning",
        # ── Artifacts ─────────────────────────────────────────────────────
        "artifacts": {},
        # ── Interview sub-state ───────────────────────────────────────────
        "conversation": [],
        "turn_count": 0,
        # max_turns is a SAFETY NET — the interviewer stops on its own
        # via interview_complete=True when completeness ≥ threshold (0.8).
        # Only change this if you have a specific token-budget constraint.
        "max_turns": data.get("maxIterations", 20),  # default 20
        "interview_complete": False,
        # ── Live requirements draft (populated incrementally per turn) ─────
        # InterviewerAgent.update_requirements appends here after each
        # stakeholder reply. write_interview_record copies this into
        # interview_record["requirements_identified"].
        "requirements_draft": [],
        "errors": [],
        "_workflow_started_message": False,
    }
    print(initial_state)

    task = executor.submit(
        ws_handler.run_iredev_workflow, initial_state, current_user["id"], chat_id
    )
    pending_taks[req_id] = task
    return {"request_id": data}