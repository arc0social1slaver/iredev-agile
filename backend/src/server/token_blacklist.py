# backend/token_blacklist.py
# =============================================================================
# In-memory token blacklist with automatic TTL-based cleanup.
#
# Purpose
# ───────
# When a user logs out, we immediately add their access token and refresh
# token to this blacklist. Any subsequent request using a blacklisted token
# is rejected — even if the JWT signature is still valid and not yet expired.
#
# Storage
# ───────
# A plain Python dict:
#   { jti_or_token_hash → expiry_timestamp (float, UTC epoch seconds) }
#
# We store the JTI (JWT ID) when present, or a SHA-256 hash of the token
# otherwise. We never store the raw token string in the blacklist — hashing
# protects against exposing token values if the blacklist is ever logged.
#
# TTL (Time To Live)
# ──────────────────
# Each blacklist entry stores the token's original expiry time.
# A background daemon thread runs every BLACKLIST_SWEEP_INTERVAL_SECONDS
# and deletes entries whose expiry has passed — the token would have been
# invalid anyway by then, so keeping the entry wastes memory.
#
# Thread safety
# ─────────────
# All dict operations are protected by a threading.Lock.
# =============================================================================

import hashlib
import time
import threading
import logging

from config import BLACKLIST_SWEEP_INTERVAL_SECONDS

log = logging.getLogger(__name__)

# ── Internal state ─────────────────────────────────────────────────────────────

# { token_key → expiry_unix_timestamp }
_blacklist: dict[str, float] = {}
_lock = threading.Lock()


# =============================================================================
# Public API
# =============================================================================

def add(token: str, expires_at: float) -> None:
    """
    Add a token to the blacklist.

    :param token:      Raw JWT string.
    :param expires_at: Unix timestamp (UTC) when the token naturally expires.
                       The blacklist entry will be swept after this time.
    """
    key = _token_key(token)
    with _lock:
        _blacklist[key] = expires_at
    log.debug(f"[blacklist] Added  key={key[:16]}…  expires_at={expires_at:.0f}")


def is_blacklisted(token: str) -> bool:
    """
    Return True if the token has been explicitly revoked (is in the blacklist).
    Automatically removes the entry if it has already expired.
    """
    key = _token_key(token)
    with _lock:
        expiry = _blacklist.get(key)
        if expiry is None:
            return False   # not in blacklist

        if time.time() > expiry:
            # Entry has naturally expired — clean it up and treat as not blacklisted.
            # The JWT is also expired, so the request would be rejected by
            # decode_token() anyway. We still remove the entry to free memory.
            del _blacklist[key]
            log.debug(f"[blacklist] Expired entry removed on read  key={key[:16]}…")
            return False

    return True


def size() -> int:
    """Return the current number of entries in the blacklist (for monitoring)."""
    with _lock:
        return len(_blacklist)


# =============================================================================
# Background sweep — runs in a daemon thread started by start_sweep_thread()
# =============================================================================

def _sweep() -> int:
    """
    Remove all entries whose expiry timestamp is in the past.
    Returns the number of entries removed.
    """
    now    = time.time()
    with _lock:
        expired_keys = [k for k, exp in _blacklist.items() if now > exp]
        for k in expired_keys:
            del _blacklist[k]

    if expired_keys:
        log.info(f"[blacklist] Sweep removed {len(expired_keys)} expired entries. "
                 f"Remaining: {len(_blacklist)}")
    return len(expired_keys)


def _sweep_loop() -> None:
    """Daemon thread target — sweeps the blacklist on a fixed interval."""
    log.info(f"[blacklist] Sweep thread started "
             f"(interval={BLACKLIST_SWEEP_INTERVAL_SECONDS}s)")
    while True:
        time.sleep(BLACKLIST_SWEEP_INTERVAL_SECONDS)
        _sweep()


def start_sweep_thread() -> threading.Thread:
    """
    Start the background sweep thread.
    Call this once at application startup (from app.py).
    Returns the Thread object (daemon=True, so it won't block shutdown).
    """
    t = threading.Thread(target=_sweep_loop, daemon=True, name="blacklist-sweep")
    t.start()
    return t


# =============================================================================
# Private helpers
# =============================================================================

def _token_key(token: str) -> str:
    """
    Return a stable, fixed-length key for a token.
    We hash the token so raw values are never stored in the blacklist dict.
    """
    return hashlib.sha256(token.encode()).hexdigest()