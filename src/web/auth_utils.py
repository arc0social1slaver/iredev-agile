# backend/auth_utils.py
# =============================================================================
# JWT helpers for the dual-token (access + refresh) authentication system.
#
# Access token  — short-lived (5 min), signed with ACCESS_TOKEN_SECRET
#                 sent in the Authorization: Bearer header on every REST request
#                 stored in React useState (RAM only — never localStorage)
#
# Refresh token — long-lived (7 days), signed with REFRESH_TOKEN_SECRET
#                 sent only to POST /api/auth/refresh
#                 stored in an HttpOnly cookie (JS cannot read it)
#
# Blacklist     — any revoked token (access or refresh) is added here on logout
#                 checked on every verify_* call
# =============================================================================

import jwt
import datetime
import time
import uuid
import logging
from functools import wraps
from flask import request, jsonify

from config import (
    ACCESS_TOKEN_SECRET,
    REFRESH_TOKEN_SECRET,
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_TTL_SECONDS,
    COOKIE_NAME,
)
import mock_db
import token_blacklist

log = logging.getLogger(__name__)

LEEWAY = datetime.timedelta(seconds=10)   # tolerate small clock skew


# =============================================================================
# Token creation
# =============================================================================

def create_access_token(user_id: str) -> str:
    """
    Create a short-lived access token (5 minutes).
    Signed with ACCESS_TOKEN_SECRET.
    Payload claims:
      sub  — user ID
      jti  — unique token ID (used as blacklist key)
      type — "access"
      iat  — issued at
      exp  — expiry
    """
    now = datetime.datetime.utcnow()
    payload = {
        "sub":  user_id,
        "jti":  str(uuid.uuid4()),   # unique ID for blacklisting
        "type": "access",
        "iat":  now,
        "exp":  now + datetime.timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
    }
    token = jwt.encode(payload, ACCESS_TOKEN_SECRET, algorithm="HS256")
    log.debug(f"[auth] Access token created  user={user_id}  ttl={ACCESS_TOKEN_TTL_SECONDS}s")
    return token


def create_refresh_token(user_id: str) -> str:
    """
    Create a long-lived refresh token (7 days).
    Signed with REFRESH_TOKEN_SECRET (different from access token secret).
    Payload claims:
      sub  — user ID
      jti  — unique token ID
      type — "refresh"
      iat  — issued at
      exp  — expiry
    """
    now = datetime.datetime.utcnow()
    payload = {
        "sub":  user_id,
        "jti":  str(uuid.uuid4()),
        "type": "refresh",
        "iat":  now,
        "exp":  now + datetime.timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS),
    }
    token = jwt.encode(payload, REFRESH_TOKEN_SECRET, algorithm="HS256")
    log.debug(f"[auth] Refresh token created  user={user_id}  ttl={REFRESH_TOKEN_TTL_SECONDS}s")
    return token


# =============================================================================
# Token decoding
# =============================================================================

def decode_access_token(token: str) -> dict | None:
    """
    Verify and decode an access token.
    Returns the payload dict, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token,
            ACCESS_TOKEN_SECRET,
            algorithms=["HS256"],
            leeway=LEEWAY,
        )
        if payload.get("type") != "access":
            log.debug("[auth] decode_access_token: wrong type claim")
            return None
        return payload
    except jwt.ExpiredSignatureError:
        log.debug("[auth] Access token expired")
        return None
    except jwt.InvalidTokenError as e:
        log.debug(f"[auth] Access token invalid: {e}")
        return None


def decode_refresh_token(token: str) -> dict | None:
    """
    Verify and decode a refresh token.
    Returns the payload dict, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token,
            REFRESH_TOKEN_SECRET,
            algorithms=["HS256"],
            leeway=LEEWAY,
        )
        if payload.get("type") != "refresh":
            log.debug("[auth] decode_refresh_token: wrong type claim")
            return None
        return payload
    except jwt.ExpiredSignatureError:
        log.debug("[auth] Refresh token expired")
        return None
    except jwt.InvalidTokenError as e:
        log.debug(f"[auth] Refresh token invalid: {e}")
        return None


# =============================================================================
# Token verification (includes blacklist check)
# =============================================================================

def verify_access_token(token: str) -> str | None:
    """
    Fully verify an access token.
    Returns the user_id on success, None on any failure.

    Checks (in order):
      1. Non-empty string
      2. JWT signature + expiry (via decode_access_token)
      3. 'type' claim == 'access'
      4. Not in blacklist
      5. User still exists in USERS
    """
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None   # already logged in decode_*

    user_id = payload.get("sub")
    if not user_id:
        log.debug("[auth] verify_access_token: no 'sub' claim")
        return None

    # Blacklist check — covers explicitly revoked tokens (logout)
    if token_blacklist.is_blacklisted(token):
        log.debug(f"[auth] verify_access_token: blacklisted  user={user_id}")
        return None

    # User still exists
    if not mock_db.find_user_by_id(user_id):
        log.debug(f"[auth] verify_access_token: user not found  user_id={user_id}")
        return None

    log.debug(f"[auth] verify_access_token: OK  user={user_id}")
    return user_id


def verify_refresh_token(token: str) -> str | None:
    """
    Fully verify a refresh token.
    Returns the user_id on success, None on any failure.
    """
    if not token:
        return None

    payload = decode_refresh_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        log.debug("[auth] verify_refresh_token: no 'sub' claim")
        return None

    if token_blacklist.is_blacklisted(token):
        log.debug(f"[auth] verify_refresh_token: blacklisted  user={user_id}")
        return None

    if not mock_db.find_user_by_id(user_id):
        log.debug(f"[auth] verify_refresh_token: user not found  user_id={user_id}")
        return None

    log.debug(f"[auth] verify_refresh_token: OK  user={user_id}")
    return user_id


# =============================================================================
# Token expiry helpers (used when blacklisting)
# =============================================================================

def _get_exp(token: str, secret: str) -> float:
    """
    Extract the exp (expiry) timestamp from a JWT without strict validation.
    Used when blacklisting a token — we need the TTL even if it's already expired.
    Returns time.time() + 300 as a safe fallback if extraction fails.
    """
    try:
        payload = jwt.decode(
            token, secret, algorithms=["HS256"],
            options={"verify_exp": False},
            leeway=LEEWAY,
        )
        exp = payload.get("exp")
        if exp:
            return float(exp)
    except Exception:
        pass
    return time.time() + 300   # fallback: expire the blacklist entry in 5 min


def blacklist_token(token: str, is_refresh: bool = False) -> None:
    """
    Add a token to the blacklist with its natural expiry as the TTL.
    After the token's expiry, the blacklist entry is auto-removed by the sweep thread.

    :param token:      Raw JWT string.
    :param is_refresh: True if this is a refresh token (uses REFRESH_TOKEN_SECRET).
    """
    secret = REFRESH_TOKEN_SECRET if is_refresh else ACCESS_TOKEN_SECRET
    exp    = _get_exp(token, secret)
    token_blacklist.add(token, exp)


# =============================================================================
# Request helpers
# =============================================================================

def get_access_token_from_request() -> str | None:
    """Extract the Bearer access token from the Authorization header."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):]
    return None


def get_refresh_token_from_cookie() -> str | None:
    """Read the refresh token from the HttpOnly cookie."""
    return request.cookies.get(COOKIE_NAME)


# =============================================================================
# Route decorator
# =============================================================================

def require_auth(f):
    """
    Protects a route with access-token authentication.
    Extracts the Bearer token from the Authorization header,
    verifies it, and injects `current_user` as the first argument.
    Returns 401 if invalid.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = get_access_token_from_request()

        if not token:
            log.warning("[auth] require_auth: no Authorization header")
            return jsonify({
                "error":   "Missing token",
                "message": "Authorization: Bearer <access_token> header is required.",
            }), 401

        user_id = verify_access_token(token)
        if not user_id:
            log.warning(f"[auth] require_auth: invalid access token  first20={token[:20]}")
            return jsonify({
                "error":   "Invalid token",
                "message": "Access token is expired, malformed, or revoked. "
                           "Call POST /api/auth/refresh to get a new one.",
            }), 401

        user = mock_db.find_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 401

        return f(mock_db.safe_user(user), *args, **kwargs)

    return wrapper


# =============================================================================
# WebSocket authentication
# =============================================================================

def get_user_id_for_token_ws(token: str) -> str | None:
    """
    Verify an access token for a WebSocket connection.
    WebSocket sends the access token as a query param: /ws?token=<access_token>
    """
    return verify_access_token(token)