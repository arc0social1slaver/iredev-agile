# backend/routes/project_routes.py
# =============================================================================
# Project REST endpoints.
#
#   GET    /api/projects                          List all projects for current user
#   POST   /api/projects                          Create a new project
#   PUT    /api/projects/<project_id>             Update project name/description
#   DELETE /api/projects/<project_id>             Delete project + all its chats
#   GET    /api/projects/<project_id>/chats       List chats in a project
#   POST   /api/projects/<project_id>/chats       Create a chat inside a project
# =============================================================================

import logging
from flask import Blueprint, request, jsonify
from ..data import mock_db
from ..auth.auth_utils import require_auth

project_bp = Blueprint("project", __name__)
log = logging.getLogger(__name__)


# =============================================================================
# Projects CRUD
# =============================================================================


@project_bp.route("", methods=["GET"])
@require_auth
def list_projects(current_user):
    """
    GET /api/projects
    Return all projects for the authenticated user, newest first.
    """
    projects = mock_db.get_projects_for_user(current_user["id"])
    return jsonify(projects), 200


@project_bp.route("", methods=["POST"])
@require_auth
def create_project(current_user):
    """
    POST /api/projects
    Body: { "name": "My Project", "description": "Optional description" }
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    if not name:
        return jsonify({"error": "Validation error", "message": "name is required."}), 400

    project = mock_db.create_project(
        user_id=current_user["id"],
        name=name,
        description=description,
    )
    log.info("[project] Created  user=%s  project=%s  name=%s", current_user["id"], project["id"], name)
    return jsonify(project), 201


@project_bp.route("/<project_id>", methods=["PUT"])
@require_auth
def update_project(current_user, project_id):
    """
    PUT /api/projects/<project_id>
    Body: { "name": "New name", "description": "New desc" }
    """
    project = mock_db.get_project(project_id)
    if not project:
        return jsonify({"error": "Not found", "message": f"Project '{project_id}' not found."}), 404
    if project["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this project."}), 403

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip() or None
    description = data.get("description")
    if description is not None:
        description = description.strip()

    updated = mock_db.update_project(project_id, name=name, description=description)
    return jsonify(updated), 200


@project_bp.route("/<project_id>", methods=["DELETE"])
@require_auth
def delete_project(current_user, project_id):
    """
    DELETE /api/projects/<project_id>
    Removes the project and all its chats/messages.
    """
    project = mock_db.get_project(project_id)
    if not project:
        return jsonify({"error": "Not found", "message": f"Project '{project_id}' not found."}), 404
    if project["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this project."}), 403

    mock_db.delete_project(project_id)
    log.info("[project] Deleted  user=%s  project=%s", current_user["id"], project_id)
    return jsonify({"ok": True}), 200


# =============================================================================
# Chats inside a project
# =============================================================================


@project_bp.route("/<project_id>/chats", methods=["GET"])
@require_auth
def list_project_chats(current_user, project_id):
    """
    GET /api/projects/<project_id>/chats
    Return all chats in the project.
    """
    project = mock_db.get_project(project_id)
    if not project:
        return jsonify({"error": "Not found", "message": f"Project '{project_id}' not found."}), 404
    if project["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this project."}), 403

    chats = mock_db.get_chats_for_project(project_id)
    return jsonify(chats), 200


@project_bp.route("/<project_id>/chats", methods=["POST"])
@require_auth
def create_project_chat(current_user, project_id):
    """
    POST /api/projects/<project_id>/chats
    Body: { "title": "Requirement Process #1" }
    Creates a new chat (requirement process run) inside the project.
    """
    project = mock_db.get_project(project_id)
    if not project:
        return jsonify({"error": "Not found", "message": f"Project '{project_id}' not found."}), 404
    if project["userId"] != current_user["id"]:
        return jsonify({"error": "Forbidden", "message": "You don't own this project."}), 403

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Validation error", "message": "title is required."}), 400

    chat = mock_db.create_chat(
        user_id=current_user["id"],
        title=title,
        project_id=project_id,
    )
    log.info("[project] Chat created  project=%s  chat=%s", project_id, chat["id"])
    return jsonify(chat), 201