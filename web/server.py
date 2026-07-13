"""
Dogbox Mailman — AI Email Client
Flask application entry point.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
from flask import Flask, render_template, redirect, jsonify

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    static_url_path="/static",
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SEND_FILE_MAX_AGE_DEFAULT=0,
)
app.secret_key = b"postbox-local-only"

DB_PATH = None


# ── Blueprints ──────────────────────────────────────────────────────────────────
from web.routes.accounts     import bp as accounts_bp
from web.routes.emails       import bp as emails_bp
from web.routes.compose      import bp as compose_bp
from web.routes.ai           import bp as ai_bp
from web.routes.oauth        import bp as oauth_bp
from web.routes.rules        import bp as rules_bp
from web.routes.import_mail  import bp as import_bp

app.register_blueprint(accounts_bp)
app.register_blueprint(emails_bp)
app.register_blueprint(compose_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(oauth_bp)
app.register_blueprint(rules_bp)
app.register_blueprint(import_bp)


# ── Shell route ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/favicon.ico")
def favicon():
    return redirect("/static/favicon.svg")


@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    def _kill():
        import time, os, signal
        time.sleep(0.3)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_kill, daemon=True).start()
    return jsonify({"ok": True})
