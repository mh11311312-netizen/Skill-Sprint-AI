import os
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

    from src.routes import register_blueprints
    register_blueprints(app)

    @app.context_processor
    def inject_user():
        return {"current_user": session.get("username"), "current_role": session.get("app_role"),
                "current_employee": session.get("employee_id")}

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
