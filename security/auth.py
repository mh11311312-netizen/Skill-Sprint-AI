"""Login, password hashing, role-based access control and CSRF protection."""
import secrets
from functools import wraps
import bcrypt
from flask import session, redirect, url_for, flash, abort, request, current_app

APP_ROLES = ["admin", "training_manager", "reviewer", "manager", "employee"]


def hash_password(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw, hashed):
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if "username" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def roles_required(*roles):
    """@roles_required("admin", "reviewer") -> only these application roles may open the page."""
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if "username" not in session:
                return redirect(url_for("auth.login", next=request.path))
            if session.get("app_role") not in roles:
                from src.audit import log_security
                log_security("Unauthorized access attempt", f"{session.get('username')} -> {request.path}", "Low")
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def verify_csrf():
    if not current_app.config.get("WTF_CSRF_ENABLED", True):
        return
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not sent or sent != session.get("_csrf"):
            abort(400, "Invalid or missing CSRF token")
