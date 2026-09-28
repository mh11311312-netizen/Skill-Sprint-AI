"""SkillSprint AI - Flask application entry point.  Run:  python app.py"""
import os
import time
from flask import Flask, render_template, session
from config.settings import Config
from database.db import init_db
from security.auth import csrf_token, verify_csrf


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    init_db(app)

    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(verify_csrf)

    @app.before_request
    def start_timer():
        from flask import g
        g.started = time.time()

    @app.after_request
    def log_slow_requests(response):
        # prints pages that take longer than 1 second, to find what is slow
        from flask import g, request
        took = time.time() - getattr(g, "started", time.time())
        if took > 1.0 and not request.path.startswith("/static"):
            print(f"[slow] {request.method} {request.path} took {took:.1f}s")
        return response

    @app.before_request
    def force_password_change():
        # accounts created with the default password must set their own before using the app
        from flask import request, redirect, url_for
        if session.get("must_change_password") and request.endpoint not in (
                "auth.change_password", "auth.logout", "static", "main.about"):
            return redirect(url_for("auth.change_password"))

    from src.routes import register_blueprints
    register_blueprints(app)

    @app.context_processor
    def inject_user():
        # pending_reviews is display-only (header bell + sidebar badge); it does not change any logic
        pending = 0
        if session.get("app_role") in ("admin", "training_manager", "reviewer", "manager"):
            cache = app.extensions.setdefault("pending_cache", {"at": 0.0, "n": 0})
            if time.time() - cache["at"] > 30:              # count at most every 30 seconds
                try:
                    from database.db import get_db
                    cache["n"] = get_db().plans.count_documents({"status": {"$in": ["Pending Review", "Outdated", "Generated"]}})
                    cache["at"] = time.time()
                except Exception:
                    pass
            pending = cache["n"]
        return {"current_user": session.get("username"), "current_role": session.get("app_role"),
                "current_employee": session.get("employee_id"), "pending_reviews": pending}

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="You do not have permission to open this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Page not found."), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("error.html", code=413, message="File is larger than the 10 MB limit."), 413

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message=str(getattr(e, "description", "Bad request"))), 400

    return app


if __name__ == "__main__":
    create_app().run(debug=os.getenv("FLASK_DEBUG", "1") == "1")
