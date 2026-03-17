# backend/config.py
# =============================================================================
# Central configuration — all values from environment variables.
# Copy .env.example → .env and override as needed.
# =============================================================================
import os
from dotenv import load_dotenv

load_dotenv()

# ── Two separate signing secrets ──────────────────────────────────────────────
# IMPORTANT: Use different secrets so a leaked access-token secret cannot be
# used to forge refresh tokens, and vice-versa.
ACCESS_TOKEN_SECRET  = os.getenv("ACCESS_TOKEN_SECRET",  "access-secret-change-me-in-prod")
REFRESH_TOKEN_SECRET = os.getenv("REFRESH_TOKEN_SECRET", "refresh-secret-change-me-in-prod")

# Keep the old name as an alias so existing imports don't break
JWT_SECRET = ACCESS_TOKEN_SECRET

# ── Token lifetimes ───────────────────────────────────────────────────────────
ACCESS_TOKEN_TTL_SECONDS  = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS",  300))           # 5 minutes
REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", 60 * 60 * 24 * 7))  # 7 days

# Keep old name for any remaining references
JWT_EXPIRY_SECONDS = ACCESS_TOKEN_TTL_SECONDS

# ── Blacklist sweep interval ──────────────────────────────────────────────────
# How often (seconds) the background thread cleans up expired blacklist entries.
BLACKLIST_SWEEP_INTERVAL_SECONDS = int(os.getenv("BLACKLIST_SWEEP_INTERVAL_SECONDS", 60))

# ── HttpOnly cookie settings ──────────────────────────────────────────────────
COOKIE_NAME     = "refresh_token"
COOKIE_SECURE   = os.getenv("COOKIE_SECURE",   "false").lower() == "true"  # True in production (HTTPS only)
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")    # "lax" | "strict" | "none"
COOKIE_DOMAIN   = os.getenv("COOKIE_DOMAIN",   None)     # None = current domain
COOKIE_PATH     = "/api/auth"                             # Limit cookie scope to auth routes only

# ── Server ────────────────────────────────────────────────────────────────────
PORT         = int(os.getenv("PORT", 8000))
CORS_ORIGINS = os.getenv("CORS_ORIGIN", "http://localhost:5173").split(",")