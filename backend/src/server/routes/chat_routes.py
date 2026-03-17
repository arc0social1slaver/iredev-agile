# backend/routes/chat_routes.py
# =============================================================================
# Chat REST endpoints (no streaming here — streaming is handled by WebSocket).
#
#   GET    /api/chats                        List all chats for current user
#   POST   /api/chats                        Create a new chat
#   DELETE /api/chats/<chat_id>              Delete a chat and all its messages
#   GET    /api/chats/<chat_id>/messages     List all messages in a chat
#   POST   /api/chats/<chat_id>/messages     Save a user message (returns saved msg)
#
# After the frontend POSTs a message here, it waits for the WebSocket to stream
# the AI reply back. The WebSocket handler lives in ws_handler.py.
# =============================================================================

import uuid
from flask import Blueprint, request, jsonify
import mock_db
from auth_utils import require_auth

chat_bp = Blueprint("chat", __name__)


# =============================================================================
# Conversations
# =============================================================================

@chat_bp.route("", methods=["GET"])
@require_auth
def list_chats(current_user):
    """
    GET /api/chats
    Return all chats for the authenticated user, newest first.
    """
    chats = mock_db.get_chats_for_user(current_user["id"])
    return jsonify(sorted(chats, key=lambda c: c["createdAt"], reverse=True)), 200


@chat_bp.route("", methods=["POST"])
@require_auth
def create_chat(current_user):
    """
    POST /api/chats
    Body: { "title": "My chat" }
    Create a new empty conversation.
    """
    data  = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()

    if not title:
        return jsonify({"error": "Validation error",
                        "message": "title is required."}), 400

    chat = mock_db.create_chat(user_id=current_user["id"], title=title)
    return jsonify(chat), 201


@chat_bp.route("/<chat_id>", methods=["DELETE"])
@require_auth
def delete_chat(current_user, chat_id):
    """
    DELETE /api/chats/<chat_id>
    Remove a chat and all its messages.
    """
    chat = mock_db.get_chat(chat_id)

    if not chat:
        return jsonify({"error": "Not found",
                        "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden",
                        "message": "You don't own this chat."}), 403

    mock_db.delete_chat(chat_id)
    return jsonify({"ok": True}), 200


# =============================================================================
# Messages
# =============================================================================

@chat_bp.route("/<chat_id>/messages", methods=["GET"])
@require_auth
def list_messages(current_user, chat_id):
    """
    GET /api/chats/<chat_id>/messages
    Return the full message history for a conversation (oldest first).
    """
    chat = mock_db.get_chat(chat_id)

    if not chat:
        return jsonify({"error": "Not found",
                        "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden",
                        "message": "You don't own this chat."}), 403

    return jsonify(mock_db.get_messages(chat_id)), 200


@chat_bp.route("/<chat_id>/messages", methods=["POST"])
@require_auth
def save_message(current_user, chat_id):
    """
    POST /api/chats/<chat_id>/messages
    Body: { "role": "user", "content": "Hello!" }

    Saves the user message and returns it with a server-assigned ID.

    The AI reply is NOT returned here.
    After this call, the frontend sends a WebSocket frame:
        { "type": "chat_message", "chatId": "...", "messageId": "...", "content": "..." }
    The backend then streams tokens back over the same WebSocket connection.

    Response 201:  saved message { id, chatId, role, content, createdAt }
    Response 400:  missing / invalid fields
    Response 403:  chat belongs to another user
    Response 404:  chat not found
    """
    chat = mock_db.get_chat(chat_id)

    if not chat:
        return jsonify({"error": "Not found",
                        "message": f"Chat '{chat_id}' does not exist."}), 404
    if chat["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden",
                        "message": "You don't own this chat."}), 403

    data    = request.get_json(silent=True) or {}
    role    = (data.get("role")    or "").strip()
    content = (data.get("content") or "").strip()

    if role not in ("user", "assistant"):
        return jsonify({"error": "Validation error",
                        "message": "role must be 'user' or 'assistant'."}), 400
    if not content:
        return jsonify({"error": "Validation error",
                        "message": "content is required."}), 400

    # Persist and return the message
    message = mock_db.add_message(chat_id=chat_id, role=role, content=content)
    return jsonify(message), 201