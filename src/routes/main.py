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
    # ---- display-only summaries for the dashboard (no business logic changes) ----
    from datetime import date, datetime, timedelta
    today = date.today()
    days14 = [today - timedelta(days=i) for i in range(13, -1, -1)]

    def series(dates):
        counts = {d: 0 for d in days14}
        for d in dates:
            if isinstance(d, datetime):
                d = d.date()
            elif isinstance(d, str):
                try:
                    d = datetime.strptime(d[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
            if d in counts:
                counts[d] += 1
        return [counts[d] for d in days14]

    all_docs = list(db.documents.find({}, {"uploaded_at": 1, "document_id": 1, "title": 1, "file_type": 1,
                                           "trust": 1, "status": 1, "doc_key": 1, "version": 1}))
    spark = {
        "plans": series(p.get("created_at") for p in plans),
        "approved": series(p.get("approved_at") for p in plans if p.get("approved_at")),
        "docs": series(d.get("uploaded_at") for d in all_docs),
        "employees": series(e.get("joining_date") for e in emps),
    }
    week = {k: sum(v[-7:]) for k, v in spark.items()}
    activity = [{"day": d.strftime("%a"), "date": d.strftime("%d %b"), "count": c, "today": d == today}
                for d, c in zip(days14[-7:], spark["plans"][-7:])]

    departments = {}
    for e in emps:
        dep = departments.setdefault(e.get("department") or "Other", {"name": e.get("department") or "Other",
                                                                        "employees": 0, "completed": 0, "progress": 0.0})
        dep["employees"] += 1
        dep["completed"] += e.get("training_status") == "Completed"
        dep["progress"] += e.get("progress_pct", 0) or 0
    departments = sorted(departments.values(), key=lambda d: -d["employees"])
    for d in departments:
        d["progress"] = round(d["progress"] / d["employees"], 1) if d["employees"] else 0.0

    recent_docs = sorted([d for d in all_docs if d.get("uploaded_at")], key=lambda d: d["uploaded_at"], reverse=True)[:4]
    alerts = []
    for p in flagged[:3]:
        alerts.append({"text": f"{p['employee_id']} plan is {p['validation']['status'].lower()}",
                       "sub": f"{p['role']} · coverage {p['validation']['scores']['coverage']}%",
                       "level": "High" if p["validation"]["status"] in ("Contradictory", "Unsupported") else "Medium",
                       "link": url_for("plans.detail", plan_id=p["plan_id"])})
    for ev in db.security_events.find({"severity": "High"}).sort("at", -1).limit(2):
        alerts.append({"text": ev["event"], "sub": ev["detail"][:70], "level": "High", "link": url_for("admin.security"),
                       "at": ev.get("at")})
    training_rows = sorted(emps, key=lambda e: (-(e.get("progress_pct") or 0), e["employee_id"]))[:6]
    latest = max(plans, key=lambda p: p.get("created_at") or datetime.min, default=None)
    health = {"model": (latest or {}).get("generation", {}).get("model", "not used yet"),
              "prompt": (latest or {}).get("generation", {}).get("prompt_version", "-"),
              "last": (latest or {}).get("created_at"),
              "approved": sum(1 for p in plans if p["status"] == "Approved"),
              "validated": len(validated)}
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
    return render_template("dashboard.html", stats=stats, by_status=by_status, training=training,
                           role_stats=role_stats, flagged=flagged, activity=activity, spark=spark, week=week,
                           departments=departments, recent_docs=recent_docs, alerts=alerts,
                           training_rows=training_rows, health=health, greeting=greeting,
                           today_label=today.strftime("%A, %d %B %Y"))
