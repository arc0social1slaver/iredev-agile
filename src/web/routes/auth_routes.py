# backend/routes/auth_routes.py
# =============================================================================
# Authentication endpoints — dual-token (access + refresh) system.
#
#   POST /api/auth/register       Create account → access token + refresh cookie
#   POST /api/auth/login          Sign in        → access token + refresh cookie
#   POST /api/auth/refresh        Exchange refresh cookie → new access token
#   POST /api/auth/logout         Revoke both tokens, clear cookie
#   GET  /api/auth/me             Return current user profile
#
# Token flow:
#   Login  → server issues access_token (JSON body) + refresh_token (HttpOnly cookie)
#   Every request → client sends access_token in Authorization: Bearer header
#   Expiry (5 min) → client calls POST /api/auth/refresh (cookie sent automatically)
#   Server verifies refresh cookie, issues new access_token, rotates refresh cookie
#   Logout → both tokens are blacklisted, cookie is cleared
# =============================================================================

import time
import logging
from flask import Blueprint, request, jsonify, make_response

import mock_db
from auth_utils import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    blacklist_token,
    get_access_token_from_request,
    get_refresh_token_from_cookie,
    require_auth,
)
from config import (
    COOKIE_NAME,
    COOKIE_SECURE,
    COOKIE_SAMESITE,
    COOKIE_DOMAIN,
    COOKIE_PATH,
    REFRESH_TOKEN_TTL_SECONDS,
)

auth_bp = Blueprint("auth", __name__)
log     = logging.getLogger(__name__)


# =============================================================================
# Helper: build a response that sets the refresh-token HttpOnly cookie
# =============================================================================

def _set_refresh_cookie(response, refresh_token: str) -> None:
    """
    Attach the refresh token as an HttpOnly cookie to a Flask response.

    HttpOnly  — JavaScript cannot read this cookie at all.
                Even if the page has an XSS vulnerability, the attacker
                cannot steal the refresh token via document.cookie.

    Secure    — only sent over HTTPS (set to True in production).

    SameSite  — "lax" prevents CSRF on cross-site navigations.

    Path      — "/api/auth" means the browser only sends this cookie to
                auth endpoints, not to every single request.

    Max-Age   — browser deletes the cookie after REFRESH_TOKEN_TTL_SECONDS.
    """
    response.set_cookie(
        COOKIE_NAME,
        value    = refresh_token,
        max_age  = REFRESH_TOKEN_TTL_SECONDS,
        httponly = True,                   # JS cannot read
        secure   = COOKIE_SECURE,         # HTTPS only in prod
        samesite = COOKIE_SAMESITE,        # CSRF protection
        domain   = COOKIE_DOMAIN,
        path     = COOKIE_PATH,
    )


def _clear_refresh_cookie(response) -> None:
    """Delete the refresh-token cookie by setting max_age=0."""
    response.set_cookie(
        COOKIE_NAME,
        value    = "",
        max_age  = 0,
        httponly = True,
        secure   = COOKIE_SECURE,
        samesite = COOKIE_SAMESITE,
        domain   = COOKIE_DOMAIN,
        path     = COOKIE_PATH,
    )


# =============================================================================
# POST /api/auth/register
# =============================================================================

@auth_bp.route("/register", methods=["POST"])
def register():
    """
    Create a new user account.

    Request body: { "name": "Jane", "email": "jane@example.com", "password": "secret123" }

    Response 201 (JSON):
        { "access_token": "eyJ...", "user": { id, name, email, plan } }

    Response cookie (HttpOnly):
        refresh_token=eyJ...  (path=/api/auth, max_age=7 days)
    """
    data     = request.get_json(silent=True) or {}
    name     = (data.get("name")     or "").strip()
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not name:
        return jsonify({"error": "Validation", "message": "Name is required."}), 400
    if not email:
        return jsonify({"error": "Validation", "message": "Email is required."}), 400
    if not password or len(password) < 8:
        return jsonify({"error": "Validation",
                        "message": "Password must be at least 8 characters."}), 400

    try:
        user = mock_db.create_user(name=name, email=email, password=password)
    except ValueError as e:
        return jsonify({"error": "Conflict", "message": str(e)}), 409

    access_token  = create_access_token(user["id"])
    refresh_token = create_refresh_token(user["id"])

    resp = make_response(jsonify({
        "access_token": access_token,
        "user":         mock_db.safe_user(user),
    }), 201)
    _set_refresh_cookie(resp, refresh_token)

    log.info(f"[auth] Registered  user={user['id']}  email={email}")
    return resp


# =============================================================================
# POST /api/auth/login
# =============================================================================

@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Sign in with email + password.

    Request body: { "email": "demo@example.com", "password": "password123" }

    Response 200 (JSON):
        { "access_token": "eyJ...", "user": { id, name, email, plan } }

    Response cookie (HttpOnly):
        refresh_token=eyJ...  (path=/api/auth, max_age=7 days)
    """
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Validation",
                        "message": "Email and password are required."}), 400

    user = mock_db.find_user_by_email(email)
    if not user or not mock_db.check_password(user, password):
        return jsonify({"error": "Unauthorized",
                        "message": "Invalid email or password."}), 401

    access_token  = create_access_token(user["id"])
    refresh_token = create_refresh_token(user["id"])

    resp = make_response(jsonify({
        "access_token": access_token,
        "user":         mock_db.safe_user(user),
    }), 200)
    _set_refresh_cookie(resp, refresh_token)

    log.info(f"[auth] Login OK  user={user['id']}")
    return resp


# =============================================================================
# POST /api/auth/refresh
# =============================================================================

@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    """
    Exchange a valid refresh token for a new access token.

    The refresh token is read from the HttpOnly cookie — no request body needed.
    On success, the old refresh token is blacklisted (token rotation) and a
    new refresh cookie is set. This means a stolen refresh token can only be
    used once before it becomes invalid.

    Response 200 (JSON):
        { "access_token": "eyJ..." }

    Response cookie (HttpOnly):
        refresh_token=<new_token>  (rotated)

    Errors:
        401  missing, expired, or blacklisted refresh token
    """
    refresh_token = get_refresh_token_from_cookie()

    if not refresh_token:
        log.warning("[auth] /refresh: no refresh cookie present")
        return jsonify({"error": "Unauthorized",
                        "message": "No refresh token cookie found."}), 401

    user_id = verify_refresh_token(refresh_token)
    if not user_id:
        # Token is expired, malformed, or already blacklisted.
        # Clear the bad cookie so the browser doesn't keep sending it.
        resp = make_response(jsonify({"error": "Unauthorized",
                                      "message": "Refresh token is invalid or expired. "
                                                 "Please log in again."}), 401)
        _clear_refresh_cookie(resp)
        return resp

    # ── Token rotation ────────────────────────────────────────────────────────
    # Blacklist the old refresh token immediately. If an attacker intercepts
    # a refresh token, they can only use it once — the next legitimate call
    # will fail because the rotated token is already blacklisted.
    blacklist_token(refresh_token, is_refresh=True)

    # Issue fresh tokens
    new_access_token  = create_access_token(user_id)
    new_refresh_token = create_refresh_token(user_id)

    resp = make_response(jsonify({"access_token": new_access_token}), 200)
    _set_refresh_cookie(resp, new_refresh_token)

    log.info(f"[auth] Token refreshed  user={user_id}")
    return resp


# =============================================================================
# POST /api/auth/logout
# =============================================================================

@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout(current_user):
    """
    Revoke both the access token and the refresh token.

    Steps:
      1. Blacklist the access token from the Authorization header.
      2. Blacklist the refresh token from the cookie (if present).
      3. Clear the refresh-token cookie.

    This means:
      - The access token can't be used again (even within its 5-min window).
      - The refresh token can't be used to get new access tokens.
      - The browser's cookie is deleted.

    Requires: Authorization: Bearer <access_token>
    """
    access_token  = get_access_token_from_request()
    refresh_token = get_refresh_token_from_cookie()

    # Blacklist the access token — prevents reuse within its remaining TTL
    if access_token:
        blacklist_token(access_token, is_refresh=False)

    # Blacklist the refresh token — prevents token rotation abuse
    if refresh_token:
        blacklist_token(refresh_token, is_refresh=True)

    resp = make_response(jsonify({"ok": True,
                                  "message": "Logged out successfully."}), 200)
    _clear_refresh_cookie(resp)

    log.info(f"[auth] Logout  user={current_user['id']}")
    return resp


# =============================================================================
# GET /api/auth/me
# =============================================================================

@auth_bp.route("/me", methods=["GET"])
@require_auth
def me(current_user):
    """
    Return the current user's profile.
    Used on page load to validate a saved access token.

    Requires: Authorization: Bearer <access_token>
    """
    return jsonify({"user": current_user}), 200