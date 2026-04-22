# backend/mock_db.py
# =============================================================================
# In-memory mock database — resets on every server restart.
#
# Tables:
#   USERS     { user_id  → user_dict }
#   PROJECTS  { project_id → project_dict }
#   CHATS     { chat_id  → chat_dict }      (each chat belongs to a project)
#   MESSAGES  { chat_id  → {sub_chat_id → [message_dict]} }
# =============================================================================
import hashlib, uuid
from datetime import datetime


# ── Generic helpers ───────────────────────────────────────────────────────────


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# =============================================================================
# USERS
# =============================================================================
USERS: dict = {
    "u001": {
        "id": "u001",
        "name": "Demo User",
        "email": "demo@example.com",
        "password": _hash("password123"),
        "plan": "free",
    },
    "u002": {
        "id": "u002",
        "name": "Admin",
        "email": "admin@example.com",
        "password": _hash("admin123"),
        "plan": "pro",
    },
}


def find_user_by_email(email):
    for u in USERS.values():
        if u["email"].lower() == email.lower():
            return u
    return None


def find_user_by_id(uid):
    return USERS.get(uid)


def create_user(name, email, password):
    if find_user_by_email(email):
        raise ValueError(f"Email already registered.")
    uid = _new_id()
    u = {
        "id": uid,
        "name": name,
        "email": email,
        "password": _hash(password),
        "plan": "free",
    }
    USERS[uid] = u
    return u


def check_password(user, plain):
    return user["password"] == _hash(plain)


def safe_user(user):
    return {k: v for k, v in user.items() if k != "password"}


# =============================================================================
# PROJECTS
# =============================================================================
PROJECTS: dict = {}


def get_projects_for_user(user_id: str) -> list:
    """Return all projects owned by user, newest first."""
    return sorted(
        [p for p in PROJECTS.values() if p["userId"] == user_id],
        key=lambda p: p["createdAt"],
        reverse=True,
    )


def get_project(project_id: str):
    return PROJECTS.get(project_id)


def create_project(user_id: str, name: str, description: str = "") -> dict:
    pid = _new_id()
    project = {
        "id": pid,
        "userId": user_id,
        "name": name.strip(),
        "description": description.strip(),
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    PROJECTS[pid] = project
    return project


def update_project(project_id: str, name: str = None, description: str = None) -> dict | None:
    p = PROJECTS.get(project_id)
    if not p:
        return None
    if name is not None:
        p["name"] = name.strip()
    if description is not None:
        p["description"] = description.strip()
    p["updatedAt"] = _now()
    return p


def delete_project(project_id: str) -> bool:
    if project_id not in PROJECTS:
        return False
    del PROJECTS[project_id]
    # Also delete all chats (and their messages) belonging to this project
    chat_ids = [cid for cid, c in CHATS.items() if c.get("projectId") == project_id]
    for cid in chat_ids:
        CHATS.pop(cid, None)
        MESSAGES.pop(cid, None)
    return True


# =============================================================================
# CHATS  &  MESSAGES
# =============================================================================
CHATS: dict = {}
MESSAGES: dict = {}

# ── Chat CRUD ─────────────────────────────────────────────────────────────────


def get_chats_for_user(user_id: str) -> list:
    """Return chats not belonging to any project (legacy / top-level chats)."""
    return [c for c in CHATS.values() if c["userId"] == user_id and not c.get("projectId")]


def get_chats_for_project(project_id: str) -> list:
    """Return all chats belonging to a project, newest first."""
    return sorted(
        [c for c in CHATS.values() if c.get("projectId") == project_id],
        key=lambda c: c["createdAt"],
        reverse=True,
    )


def get_chat(chat_id: str):
    return CHATS.get(chat_id)


def create_chat(user_id: str, title: str, project_id: str = None) -> dict:
    cid = _new_id()
    chat = {
        "id": cid,
        "userId": user_id,
        "projectId": project_id,
        "title": title or "New conversation",
        "date": "Today",
        "createdAt": _now(),
    }
    CHATS[cid] = chat
    MESSAGES[cid] = {}
    # Update project updatedAt
    if project_id and project_id in PROJECTS:
        PROJECTS[project_id]["updatedAt"] = _now()
    return chat


def delete_chat(chat_id: str) -> bool:
    if chat_id not in CHATS:
        return False
    del CHATS[chat_id]
    MESSAGES.pop(chat_id, None)
    return True


# ── Message CRUD ──────────────────────────────────────────────────────────────


def get_messages(chat_id: str, sub_chat_id) -> list:
    return MESSAGES.get(chat_id, {}).get(int(sub_chat_id), [])


def add_message(
    chat_id: str,
    role: str,
    content: str,
    artifact: dict | None = None,
    messID: str | None = None,
    subChatID: int = 0,
) -> dict:
    mid = messID or _new_id()
    msg = {
        "id": mid,
        "chatId": chat_id,
        "role": role,
        "content": content,
        "createdAt": _now(),
    }
    if artifact:
        msg["artifact"] = artifact
    MESSAGES.setdefault(chat_id, {}).setdefault(int(subChatID), []).append(msg)
    if chat_id in CHATS:
        CHATS[chat_id]["date"] = "Today"
        # propagate updatedAt to project
        pid = CHATS[chat_id].get("projectId")
        if pid and pid in PROJECTS:
            PROJECTS[pid]["updatedAt"] = _now()
    return msg


# =============================================================================
# Artifacts
# =============================================================================

ARTIFACTS: dict = {}  # { artifact_id: artifact_dict }


def save_artifact(chat_id: str, message_id: str, artifact: dict) -> dict:
    entry = {**artifact, "chatId": chat_id, "messageId": message_id}
    ARTIFACTS[artifact["id"]] = entry
    return entry


def update_message_artifact(message_id: str, artifact: dict) -> bool:
    """
    Update the artifact stored on a message in-place.
    Called when an artifact is accepted/timed-out so the stored message
    reflects the final accepted state — meaning GET /messages will return
    accepted=True and awaitingFeedback=False on reload.
    Returns True if the message was found, False otherwise.
    """
    for conversations in MESSAGES.values():
        for msgs in conversations.values():
            for msg in msgs:
                if msg["id"] == message_id:
                    msg["artifact"] = artifact
                    return True
    return False