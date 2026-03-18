"""
Culinara — Unified Flask Server
Serves the main app at / and the agent dashboard at /agents/
"""

import os
import sys

from flask import Flask, send_from_directory, request, Response

# Add agents/ to Python path so dashboard.py can import shared, jon_snow, etc.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents"))

app = Flask(__name__, static_folder=None)

# ── Auth for /agents/ ────────────────────────────────────────────────────────

DASH_USER = os.environ.get("DASHBOARD_USER", "admin")
DASH_PASS = os.environ.get("DASHBOARD_PASS", "")

@app.before_request
def check_agents_auth():
    """Require basic auth for all /agents/ routes."""
    if request.path.startswith("/agents"):
        if not DASH_PASS:
            return  # No password set = auth disabled (local dev)
        auth = request.authorization
        if not auth or auth.username != DASH_USER or auth.password != DASH_PASS:
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="Culinara Agents"'}
            )

# ── Main app: serve index.html ───────────────────────────────────────────────

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def serve_index():
    return send_from_directory(ROOT_DIR, "index.html")

# ── Mount agent dashboard ────────────────────────────────────────────────────

from dashboard import create_dashboard_blueprint
app.register_blueprint(create_dashboard_blueprint(), url_prefix="/agents")

# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print()
    print("  Culinara")
    print(f"  http://localhost:{port}")
    print(f"  http://localhost:{port}/agents/")
    print()
    app.run(host="0.0.0.0", port=port, debug=False)
