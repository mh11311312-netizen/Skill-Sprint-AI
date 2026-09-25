from flask import Blueprint, render_template, request, redirect, url_for, flash
from database.db import get_db
from security.auth import roles_required, hash_password, APP_ROLES
from src.audit import now, log_audit
from src.routes.helpers import STAFF

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/users", methods=["GET", "POST"])
@roles_required("admin")
def users():
    db = get_db()
    if request.method == "POST":
        u = request.form["username"].strip().lower()
        role = request.form["app_role"]
        if not u or role not in APP_ROLES or db.users.find_one({"username": u}) or len(request.form["password"]) < 8:
            flash("Username must be unique, role valid and password at least 8 characters.", "danger")
        else:
            db.users.insert_one({"username": u, "password": hash_password(request.form["password"]), "app_role": role,
                                 "employee_id": request.form.get("employee_id") or None, "created_at": now()})
            log_audit("create_user", "user", u, after=role)
            flash(f"User {u} created.", "success")
        return redirect(url_for("admin.users"))
    return render_template("users.html", users=list(db.users.find({}, {"password": 0}).sort("username", 1)),
                           roles=APP_ROLES, employees=list(db.employees.find().sort("employee_id", 1)))


@bp.route("/security")
@roles_required(*STAFF)
def security():
    db = get_db()
    return render_template("security.html",
                           events=list(db.security_events.find().sort("at", -1).limit(300)),
                           quarantined=list(db.chunks.find({"quarantined": True})),
                           docs=list(db.documents.find({"trust": {"$ne": "Trusted"}})))


@bp.route("/logs")
@roles_required(*STAFF)
def logs():
    db = get_db()
    return render_template("logs.html", gen=list(db.generation_logs.find().sort("at", -1).limit(200)),
                           audit=list(db.audit_log.find().sort("at", -1).limit(300)),
                           builds=list(db.matrix_builds.find().sort("built_at", -1).limit(20)))
