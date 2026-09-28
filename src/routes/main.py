import re
from flask import Blueprint, render_template, redirect, url_for, session, request
from database.db import get_db
from security.auth import login_required, roles_required
from src.routes.helpers import STAFF

bp = Blueprint("main", __name__)


@bp.route("/")
def home():
    """Visitors who are not signed in see the About page; signed-in users go to their workspace."""
    if "username" not in session:
        return render_template("about.html")
    if session.get("app_role") == "employee":
        return redirect(url_for("learner.home"))
    return redirect(url_for("main.dashboard"))


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/dashboard")
@roles_required(*STAFF)
def dashboard():
    db = get_db()
    # only the fields the dashboard shows (the full plan JSON and validation rows are large)
    plans = list(db.plans.find({}, {"plan_id": 1, "employee_id": 1, "role": 1, "status": 1, "created_at": 1,
                                    "approved_at": 1, "generation.model": 1, "generation.prompt_version": 1,
                                    "validation.status": 1, "validation.scores": 1}))
    by_status = {}
    for p in plans:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    validated = [p for p in plans if p.get("validation")]
    avg = lambda k: round(sum(p["validation"]["scores"][k] for p in validated) / len(validated), 1) if validated else 0
    emps = list(db.employees.find())
    training = {}
    for e in emps:
        training[e.get("training_status", "Not Started")] = training.get(e.get("training_status", "Not Started"), 0) + 1
    # one aggregation instead of one count per role
    mandatory_by_role = {g["_id"]: g["n"] for g in db.requirements.aggregate([
        {"$match": {"active": True, "obligation": "Mandatory"}}, {"$unwind": "$roles"},
        {"$group": {"_id": "$roles", "n": {"$sum": 1}}}])}
    doc_status = {g["_id"]: g["n"] for g in db.documents.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    doc_untrusted = db.documents.count_documents({"trust": {"$ne": "Trusted"}})
    req_counts = {g["_id"]: g["n"] for g in db.requirements.aggregate([
        {"$match": {"active": True}}, {"$group": {"_id": "$obligation", "n": {"$sum": 1}}}])}
    roles = list(db.roles.find({}, {"name": 1, "role_id": 1}).sort("role_id", 1))
    role_stats = []
    for r in roles:
        rp = [p for p in validated if p["role"] == r["name"]]
        role_stats.append({"role": r["name"],
                           "mandatory": mandatory_by_role.get(r["name"], 0),
                           "employees": sum(1 for e in emps if e["role"] == r["name"]),
                           "coverage": round(sum(p["validation"]["scores"]["coverage"] for p in rp) / len(rp), 1) if rp else None,
                           "progress": round(sum(e.get("progress_pct", 0) for e in emps if e["role"] == r["name"]) /
                                             max(1, sum(1 for e in emps if e["role"] == r["name"])), 1)})
    stats = {
        "documents_active": doc_status.get("Active", 0),
        "documents_superseded": doc_status.get("Superseded", 0),
        "documents_flagged": doc_untrusted,
        "requirements": sum(req_counts.values()),
        "mandatory": req_counts.get("Mandatory", 0),
        "conflicts": db.conflicts.count_documents({"kind": "conflict", "type": {"$ne": "Scope-specific rule"}}),
        "roles": len(roles), "employees": len(emps), "plans": len(plans),
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


@bp.route("/search")
@roles_required(*STAFF)
def search():
    """One search box for employees, roles, documents, requirements, plan modules and statuses."""
    db = get_db()
    q = request.args.get("q", "").strip()
    results = {"employees": [], "roles": [], "documents": [], "requirements": [], "modules": [], "plans": []}
    if len(q) >= 2:
        rx = {"$regex": re.escape(q), "$options": "i"}
        results["employees"] = list(db.employees.find(
            {"$or": [{"full_name": rx}, {"employee_id": rx}, {"role": rx}, {"department": rx}, {"training_status": rx}]}).limit(25))
        results["roles"] = list(db.roles.find({"$or": [{"name": rx}, {"department": rx}, {"description": rx}]}).limit(25))
        results["documents"] = list(db.documents.find(
            {"$or": [{"document_id": rx}, {"title": rx}, {"category": rx}, {"status": rx}, {"trust": rx}]},
            {"doc_key": 1, "document_id": 1, "title": 1, "version": 1, "status": 1, "trust": 1, "category": 1}).limit(25))
        results["requirements"] = list(db.requirements.find(
            {"$or": [{"requirement_id": rx}, {"text": rx}]},
            {"requirement_id": 1, "text": 1, "document_id": 1, "version": 1, "section_id": 1, "obligation": 1, "active": 1,
             "overridden_by": 1, "duplicate_of": 1}).limit(25))
        for p in db.plans.find({"$or": [{"plan_json.modules.module_title": rx}, {"status": rx}, {"validation.status": rx},
                                        {"plan_id": rx}, {"employee_id": rx}]},
                               {"plan_id": 1, "employee_id": 1, "role": 1, "status": 1, "validation.status": 1,
                                "plan_json.modules.module_id": 1, "plan_json.modules.module_title": 1,
                                "plan_json.modules.stage": 1}).limit(50):
            hits = [m for m in p.get("plan_json", {}).get("modules", []) if re.search(re.escape(q), m.get("module_title", ""), re.I)]
            for m in hits[:10]:
                results["modules"].append({"plan": p, "module": m})
            if not hits:
                results["plans"].append(p)
    total = sum(len(v) for v in results.values())
    return render_template("search.html", q=q, results=results, total=total)
