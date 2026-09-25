import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from database.db import get_db
from security.auth import roles_required, hash_password
from src.audit import now, log_audit
from src.progress import assess
from src.routes.helpers import STAFF, EDITORS

bp = Blueprint("employees", __name__, url_prefix="/employees")
FIELDS = ("employee_id", "full_name", "role", "department", "experience_level", "location", "joining_date",
          "reporting_manager", "previous_experience")


@bp.route("/", methods=["GET", "POST"])
@roles_required(*STAFF)
def index():
    db = get_db()
    if request.method == "POST":
        from flask import session
        if session.get("app_role") not in EDITORS:
            abort(403)
        e = {k: request.form.get(k, "").strip() for k in FIELDS}
        if not e["employee_id"] or not e["role"] or db.employees.find_one({"employee_id": e["employee_id"]}):
            flash("Employee ID and role are required, and the ID must be unique.", "danger")
        else:
            e.update(training_status="Not Started", created_at=now())
            db.employees.insert_one(e)
            if request.form.get("create_login"):
                db.users.insert_one({"username": e["employee_id"].lower(), "password": hash_password(request.form.get("password") or "Employee@123"),
                                     "app_role": "employee", "employee_id": e["employee_id"], "created_at": now()})
            log_audit("create_employee", "employee", e["employee_id"])
            flash(f"Employee {e['employee_id']} created.", "success")
        return redirect(url_for("employees.index"))
    q = {}
    for f in ("role", "department", "training_status", "experience_level"):
        if request.args.get(f):
            q[f] = request.args[f]
    if request.args.get("search"):
        q["$or"] = [{"full_name": {"$regex": re.escape(request.args["search"]), "$options": "i"}},
                    {"employee_id": {"$regex": re.escape(request.args["search"]), "$options": "i"}}]
    emps = list(db.employees.find(q).sort("employee_id", 1))
    roles = list(db.roles.find().sort("role_id", 1))
    return render_template("employees.html", emps=emps, roles=roles,
                           departments=sorted({r["department"] for r in roles}))


@bp.route("/<employee_id>")
@roles_required(*STAFF)
def detail(employee_id):
    db = get_db()
    e = db.employees.find_one({"employee_id": employee_id}) or abort(404)
    plans = list(db.plans.find({"employee_id": employee_id}).sort("created_at", -1))
    approved = [p for p in plans if p.get("approved_at") and p["status"] != "Rejected"]
    progress = assess(db, approved[0], e) if approved else None
    return render_template("employee_detail.html", e=e, plans=plans, progress=progress)
