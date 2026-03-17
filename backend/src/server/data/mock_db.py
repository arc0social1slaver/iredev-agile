# backend/mock_db.py
# =============================================================================
# In-memory mock database — resets on every server restart.
#
# Tables:
#   USERS     { user_id  → user_dict }
#   CHATS     { chat_id  → chat_dict }
#   MESSAGES  { chat_id  → [message_dict, ...] }
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
    "u001": {"id":"u001","name":"Demo User","email":"demo@example.com",
             "password":_hash("password123"),"plan":"free"},
    "u002": {"id":"u002","name":"Admin","email":"admin@example.com",
             "password":_hash("admin123"),"plan":"pro"},
}

def find_user_by_email(email):
    for u in USERS.values():
        if u["email"].lower() == email.lower(): return u
    return None

def find_user_by_id(uid): return USERS.get(uid)

def create_user(name, email, password):
    if find_user_by_email(email): raise ValueError(f"Email already registered.")
    uid = _new_id()
    u = {"id":uid,"name":name,"email":email,"password":_hash(password),"plan":"free"}
    USERS[uid] = u
    return u

def check_password(user, plain): return user["password"] == _hash(plain)
def safe_user(user): return {k:v for k,v in user.items() if k != "password"}


# NOTE: The old TOKENS dict has been removed.
# Token revocation is now handled by token_blacklist.py which uses
# SHA-256 hashed keys with automatic TTL cleanup.


# =============================================================================
# CHATS  &  MESSAGES
# =============================================================================
CHATS: dict = {}
MESSAGES: dict = {}


def _seed():
    """Pre-populate demo conversations for user u001."""

    # ── Chat 1: React dashboard ───────────────────────────────────────────────
    CHATS["c1"] = {"id":"c1","userId":"u001","title":"Build a React dashboard",
                   "date":"Today","createdAt":_now()}
    MESSAGES["c1"] = [
        {"id":"m1","chatId":"c1","role":"user",
         "content":"Can you build me a simple dashboard in React?","createdAt":_now()},
        {"id":"m2","chatId":"c1","role":"assistant",
         "content":(
             "Sure! Here's a clean dashboard layout:\n\n"
             "```jsx\nexport function Dashboard() {\n"
             "  return (\n    <div className=\"grid grid-cols-3 gap-4 p-6\">\n"
             "      <StatCard title=\"Users\"   value=\"1,240\" />\n"
             "      <StatCard title=\"Revenue\" value=\"$8,320\" />\n"
             "      <StatCard title=\"Orders\"  value=\"340\" />\n"
             "    </div>\n  )\n}\n```\n\n"
             "Each **StatCard** receives a `title` and `value` prop. "
             "Want me to add charts or live data fetching?"
         ),
         "artifact":{
             "id":"art_m2_v1","type":"react","language":"jsx",
             "title":"JSX snippet","iteration":1,"accepted":True,
             "content":(
                 "export function Dashboard() {\n"
                 "  return (\n    <div className=\"grid grid-cols-3 gap-4 p-6\">\n"
                 "      <StatCard title=\"Users\"   value=\"1,240\" />\n"
                 "      <StatCard title=\"Revenue\" value=\"$8,320\" />\n"
                 "      <StatCard title=\"Orders\"  value=\"340\" />\n"
                 "    </div>\n  )\n}"
             ),
         },"createdAt":_now()},
    ]

    # ── Chat 2: async/await ───────────────────────────────────────────────────
    CHATS["c2"] = {"id":"c2","userId":"u001","title":"Explain async/await in JS",
                   "date":"Today","createdAt":_now()}
    MESSAGES["c2"] = [
        {"id":"m3","chatId":"c2","role":"user",
         "content":"Explain async/await in JavaScript simply.","createdAt":_now()},
        {"id":"m4","chatId":"c2","role":"assistant",
         "content":(
             "**async/await** makes asynchronous code read like synchronous code.\n\n"
             "- `async` marks a function — it always returns a **Promise**\n"
             "- `await` pauses until a Promise resolves\n\n"
             "```javascript\nasync function getUser() {\n"
             "  const res  = await fetch('/api/user')\n"
             "  const user = await res.json()\n  console.log(user)\n}\n```\n\n"
             "Think of `await` as: **\"wait here until done, then continue.\"**"
         ),
         "artifact":{
             "id":"art_m4_v1","type":"code","language":"javascript",
             "title":"JAVASCRIPT snippet","iteration":1,"accepted":True,
             "content":(
                 "async function getUser() {\n"
                 "  const res  = await fetch('/api/user')\n"
                 "  const user = await res.json()\n"
                 "  console.log(user)\n}"
             ),
         },"createdAt":_now()},
    ]

    # ── Stub chats (no messages yet) ──────────────────────────────────────────
    for cid, title, date in [
        ("c3","Python pandas cheatsheet","Yesterday"),
        ("c4","Travel itinerary — Tokyo","Yesterday"),
        ("c5","Marketing email for SaaS","Mar 12"),
    ]:
        CHATS[cid] = {"id":cid,"userId":"u001","title":title,
                      "date":date,"createdAt":_now()}
        MESSAGES[cid] = []


_seed()


# ── Chat CRUD ─────────────────────────────────────────────────────────────────

def get_chats_for_user(user_id: str) -> list:
    return [c for c in CHATS.values() if c["userId"] == user_id]

def get_chat(chat_id: str): return CHATS.get(chat_id)

def create_chat(user_id: str, title: str) -> dict:
    cid = _new_id()
    chat = {"id":cid,"userId":user_id,"title":title or "New conversation",
            "date":"Today","createdAt":_now()}
    CHATS[cid] = chat
    MESSAGES[cid] = []
    return chat

def delete_chat(chat_id: str) -> bool:
    if chat_id not in CHATS: return False
    del CHATS[chat_id]
    MESSAGES.pop(chat_id, None)
    return True


# ── Message CRUD ──────────────────────────────────────────────────────────────

def get_messages(chat_id: str) -> list:
    return MESSAGES.get(chat_id, [])

def add_message(chat_id: str, role: str, content: str,
                artifact: dict | None = None) -> dict:
    """
    Persist a message.  If artifact is provided it is stored on the
    message dict so GET /messages can return it on reload.
    """
    mid = _new_id()
    msg = {"id":mid,"chatId":chat_id,"role":role,
           "content":content,"createdAt":_now()}
    if artifact:
        msg["artifact"] = artifact   # persisted so reload restores the card
    MESSAGES.setdefault(chat_id, []).append(msg)
    if chat_id in CHATS:
        CHATS[chat_id]["date"] = "Today"
    return msg


# =============================================================================
# Artifacts  (saved after accept)
# =============================================================================

ARTIFACTS: dict = {}  # { artifact_id: artifact_dict }

def save_artifact(chat_id: str, message_id: str, artifact: dict) -> dict:
    """Persist an accepted artifact so it can be retrieved later."""
    entry = {**artifact, 'chatId': chat_id, 'messageId': message_id}
    ARTIFACTS[artifact['id']] = entry
    return entry

def get_artifact(artifact_id: str) -> dict | None:
    return ARTIFACTS.get(artifact_id)


def update_message_artifact(message_id: str, artifact: dict) -> bool:
    """
    Update the artifact stored on a message in-place.
    Called when an artifact is accepted/timed-out so the stored message
    reflects the final accepted state — meaning GET /messages will return
    accepted=True and awaitingFeedback=False on reload.
    Returns True if the message was found, False otherwise.
    """
    for msgs in MESSAGES.values():
        for msg in msgs:
            if msg["id"] == message_id:
                msg["artifact"] = artifact
                return True
    return False