# backend/app.py
# =============================================================================
# Flask application entry point.
#
# FIXES:
#   1. Added logging configuration so auth rejections print to console.
#   2. Explicit threaded=True for Flask dev server — required for WebSocket
#      + REST to work simultaneously without blocking.
#   3. use_reloader=False prevents the reloader from killing WS connections.
# =============================================================================

# backend/app.py
import logging
from flask      import Flask, jsonify
from flask_cors import CORS
from flask_sock import Sock

from config             import PORT, CORS_ORIGINS
from routes.auth_routes import auth_bp
from routes.chat_routes import chat_bp
from ws_handler         import handle_connection
import token_blacklist

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.DEBUG,
    format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt = "%H:%M:%S",
)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# ── App ───────────────────────────────────────────────────────────────────────
app  = Flask(__name__)
sock = Sock(app)

# credentials=True is required so the browser sends the HttpOnly cookie
# on cross-origin requests (e.g. React dev server → Flask backend).
CORS(app, origins=CORS_ORIGINS, supports_credentials=True)

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(chat_bp, url_prefix="/api/chats")

# Start the blacklist sweep background thread
token_blacklist.start_sweep_thread()

# ── WebSocket endpoint ────────────────────────────────────────────────────────
@sock.route("/ws")
def websocket(ws):
    handle_connection(ws)

# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status":         "ok",
        "blacklist_size": token_blacklist.size(),
    }), 200

# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found", "message": str(e)}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed", "message": str(e)}), 405

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error", "message": str(e)}), 500

# ── Dev server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  Claude UI — Backend  (access_token + refresh_token)        ║
║  http://localhost:{PORT}                                       ║
╠══════════════════════════════════════════════════════════════╣
║  Auth                                                        ║
║    POST  /api/auth/register   → access_token (JSON)          ║
║                                 refresh_token (HttpOnly cookie)║
║    POST  /api/auth/login      → same as register             ║
║    POST  /api/auth/refresh    → new access_token (cookie auto)║
║    POST  /api/auth/logout     → blacklists both tokens       ║
║    GET   /api/auth/me         → current user                 ║
╠══════════════════════════════════════════════════════════════╣
║  Chats / Messages / WebSocket — unchanged                    ║
╠══════════════════════════════════════════════════════════════╣
║  Demo accounts                                               ║
║    demo@example.com   /  password123                         ║
║    admin@example.com  /  admin123                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    app.run(
        host         = "0.0.0.0",
        port         = PORT,
        debug        = True,
        use_reloader = False,
        threaded     = True,
    )