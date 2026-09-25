from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_db
from security.auth import check_password
from src.audit import log_audit, log_security

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        user = get_db().users.find_one({"username": username})
        if user and check_password(request.form.get("password", ""), user["password"]):
            session.clear()
            session.update(username=user["username"], app_role=user["app_role"], employee_id=user.get("employee_id"))
            log_audit("login", "user", username, user=username)
            nxt = request.args.get("next")
            return redirect(nxt if nxt and nxt.startswith("/") else url_for("main.home"))
        log_security("Failed login", f"username={username}", "Low")
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
