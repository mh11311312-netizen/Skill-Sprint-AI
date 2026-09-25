from flask import Blueprint, render_template, redirect, url_for, session
from database.db import get_db
from security.auth import login_required, roles_required
from src.routes.helpers import STAFF

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def home():
    if session.get("app_role") == "employee":
        return redirect(url_for("learner.home"))
    return redirect(url_for("main.dashboard"))


@bp.route("/dashboard")
@roles_required(*STAFF)
def dashboard():
    db = get_db()
    plans = list(db.plans.find({}, {"plan_json": 0}))
    by_status = {}
    for p in plans:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    validated = [p for p in plans if p.get("validation")]
    avg = lambda k: round(sum(p["validation"]["scores"][k] for p in validated) / len(validated), 1) if validated else 0
    emps = list(db.employees.find())
    training = {}
    for e in emps:
        training[e.get("training_status", "Not Started")] = training.get(e.get("training_status", "Not Started"), 0) + 1
    role_stats = []
    for r in db.roles.find().sort("role_id", 1):
        rp = [p for p in validated if p["role"] == r["name"]]
        role_stats.append({"role": r["name"],
                           "mandatory": db.requirements.count_documents({"roles": r["name"], "active": True, "obligation": "Mandatory"}),
                           "employees": sum(1 for e in emps if e["role"] == r["name"]),
                           "coverage": round(sum(p["validation"]["scores"]["coverage"] for p in rp) / len(rp), 1) if rp else None,
                           "progress": round(sum(e.get("progress_pct", 0) for e in emps if e["role"] == r["name"]) /
                                             max(1, sum(1 for e in emps if e["role"] == r["name"])), 1)})
    stats = {
        "documents_active": db.documents.count_documents({"status": "Active"}),
        "documents_superseded": db.documents.count_documents({"status": "Superseded"}),
        "documents_flagged": db.documents.count_documents({"trust": {"$ne": "Trusted"}}),
        "requirements": db.requirements.count_documents({"active": True}),
        "mandatory": db.requirements.count_documents({"active": True, "obligation": "Mandatory"}),
        "conflicts": db.conflicts.count_documents({"kind": "conflict", "type": {"$ne": "Scope-specific rule"}}),
        "roles": db.roles.count_documents({}), "employees": len(emps), "plans": len(plans),
        "pending_review": sum(1 for p in plans if p["status"] in ("Pending Review", "Outdated")),
        "avg_coverage": avg("coverage"), "avg_traceability": avg("traceability"),
        "security_events": db.security_events.count_documents({}),
    }
    flagged = [p for p in validated if p["validation"]["status"] != "Verified"][:8]
    return render_template("dashboard.html", stats=stats, by_status=by_status, training=training,
                           role_stats=role_stats, flagged=flagged)
