import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, Response
from pydantic import ValidationError
from database.db import get_db
from security.auth import roles_required
from genai_pipeline.generator import create_plan, regenerate_modules, generate_plan_json, GenerationFailed, topic_module
from python_validation.validator import run_validation
from comparison_engine.consistency import compare_generations
from schemas.plan_schema import Module
from src.audit import now, log_audit
from src.routes.helpers import STAFF, EDITORS, REVIEWERS

bp = Blueprint("plans", __name__, url_prefix="/plans")


def _plan(plan_id):
    return get_db().plans.find_one({"plan_id": plan_id}) or abort(404)


@bp.route("/")
@roles_required(*STAFF)
def index():
    q = {}
    for f in ("role", "status", "employee_id"):
        if request.args.get(f):
            q[f] = request.args[f]
    if request.args.get("verification"):
        q["validation.status"] = request.args["verification"]
    db = get_db()
    plans = list(db.plans.find(q, {"plan_json": 0, "original_plan_json": 0}).sort("created_at", -1))
    return render_template("plans.html", plans=plans, roles=list(db.roles.find().sort("role_id", 1)))


@bp.route("/generate/<employee_id>", methods=["POST"])
@roles_required(*EDITORS)
def generate(employee_id):
    db = get_db()
    e = db.employees.find_one({"employee_id": employee_id}) or abort(404)
    try:
        plan = create_plan(db, e, session["username"])
        result = run_validation(db, plan, session["username"])
        flash(f"Plan generated and validated: {result['status']} (coverage {result['scores']['coverage']}%, "
              f"traceability {result['scores']['traceability']}%).", "success" if result["status"] == "Verified" else "warning")
        return redirect(url_for("plans.detail", plan_id=plan["plan_id"]))
    except GenerationFailed as ex:
        flash(str(ex), "danger")
        return redirect(url_for("employees.detail", employee_id=employee_id))


@bp.route("/<plan_id>")
@roles_required(*STAFF)
def detail(plan_id):
    db = get_db()
    plan = _plan(plan_id)
    logs = list(db.generation_logs.find({"request_id": plan_id}).sort("at", 1))
    audit = list(db.audit_log.find({"entity": "plan", "entity_id": plan_id}).sort("at", -1))
    return render_template("plan_detail.html", plan=plan, logs=logs, audit=audit,
                           employee=db.employees.find_one({"employee_id": plan["employee_id"]}))


@bp.route("/<plan_id>/validate", methods=["POST"])
@roles_required(*STAFF)
def validate(plan_id):
    r = run_validation(get_db(), _plan(plan_id), session["username"])
    flash(f"Python validation finished: {r['status']}.", "info")
    return redirect(url_for("plans.detail", plan_id=plan_id))


@bp.route("/<plan_id>/review", methods=["POST"])
@roles_required(*REVIEWERS)
def review(plan_id):
    db = get_db()
    plan = _plan(plan_id)
    action, comment = request.form["action"], request.form.get("comment", "").strip()
    vstatus = (plan.get("validation") or {}).get("status")
    if action == "comment":
        db.plans.update_one({"_id": plan["_id"]}, {"$push": {"comments": {"by": session["username"], "at": now(), "text": comment}}})
        log_audit("comment", "plan", plan_id, comment=comment)
    elif action in ("approve", "reject"):
        new = "Approved" if action == "approve" else "Rejected"
        override = action == "approve" and vstatus != "Verified"
        if override and not comment:
            flash("Approving a plan that is not Verified is an override - a justification comment is required.", "danger")
            return redirect(url_for("plans.detail", plan_id=plan_id))
        upd = {"$set": {"status": new, "reviewed_by": session["username"], "reviewed_at": now()}}
        if new == "Approved":
            upd["$set"]["approved_at"] = now()
        if override:
            upd["$push"] = {"overrides": {"by": session["username"], "at": now(), "original_validation_status": vstatus,
                                          "decision": new, "comment": comment}}
        db.plans.update_one({"_id": plan["_id"]}, upd)
        log_audit("override_approve" if override else action, "plan", plan_id,
                  before={"status": plan["status"], "validation": vstatus}, after=new, comment=comment)
        if new == "Approved":
            db.employees.update_one({"employee_id": plan["employee_id"]}, {"$set": {"active_plan": plan_id, "training_status": "On Track"}})
        flash(f"Plan {new.lower()}.", "success")
    return redirect(url_for("plans.detail", plan_id=plan_id))


@bp.route("/<plan_id>/item-override", methods=["POST"])
@roles_required(*REVIEWERS)
def item_override(plan_id):
    """Reviewer overrides the status of one comparison row. The original stays in the audit trail."""
    db = get_db()
    plan = _plan(plan_id)
    rid, new, comment = request.form["requirement_id"], request.form["new_status"], request.form.get("comment", "")
    rows = plan["validation"]["rows"]
    for r in rows:
        if r["requirement_id"] == rid:
            before = r["status"]
            r.setdefault("original_status", before)
            r["status"], r["override"] = new, {"by": session["username"], "at": now(), "comment": comment}
            db.plans.update_one({"_id": plan["_id"]}, {"$set": {"validation.rows": rows},
                                                       "$push": {"overrides": {"by": session["username"], "at": now(),
                                                                 "requirement_id": rid, "original_status": before,
                                                                 "decision": new, "comment": comment}}})
            log_audit("override_item", "plan", plan_id, before=before, after=new, comment=f"{rid}: {comment}")
            flash(f"{rid} overridden: {before} -> {new}.", "info")
    return redirect(url_for("plans.detail", plan_id=plan_id) + "#comparison")


@bp.route("/<plan_id>/module/<module_id>/edit", methods=["POST"])
@roles_required(*REVIEWERS)
def edit_module(plan_id, module_id):
    db = get_db()
    plan = _plan(plan_id)
    try:
        new = Module.model_validate(json.loads(request.form["module_json"])).model_dump()
    except (json.JSONDecodeError, ValidationError) as ex:
        flash(f"Edit rejected - JSON does not match the schema: {str(ex)[:400]}", "danger")
        return redirect(url_for("plans.detail", plan_id=plan_id))
    mods = plan["plan_json"]["modules"]
    for i, m in enumerate(mods):
        if m["module_id"] == module_id:
            before = m
            mods[i] = new
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"plan_json": plan["plan_json"]}})
    log_audit("edit_module", "plan", plan_id, before=before.get("module_title"), after=new["module_title"],
              comment=request.form.get("comment", ""))
    run_validation(db, db.plans.find_one({"_id": plan["_id"]}), session["username"])
    flash(f"Module {module_id} edited and the plan was re-validated.", "success")
    return redirect(url_for("plans.detail", plan_id=plan_id))


@bp.route("/<plan_id>/regenerate", methods=["POST"])
@roles_required(*REVIEWERS)
def regenerate(plan_id):
    db = get_db()
    plan = _plan(plan_id)
    ids = request.form.getlist("module_ids") or (plan.get("outdated") or {}).get("modules", [])
    if not ids:
        flash("Select at least one module to regenerate.", "warning")
        return redirect(url_for("plans.detail", plan_id=plan_id))
    reason = request.form.get("reason") or "Reviewer requested regeneration"
    try:
        regenerate_modules(db, plan, ids, reason, session["username"])
        plan = db.plans.find_one({"_id": plan["_id"]})
        if plan["status"] == "Outdated":
            db.plans.update_one({"_id": plan["_id"]}, {"$set": {"status": "Pending Review"}})
        r = run_validation(db, db.plans.find_one({"_id": plan["_id"]}), session["username"])
        flash(f"Regenerated {', '.join(ids)} only. Re-validation: {r['status']}.", "success")
    except GenerationFailed as ex:
        flash(str(ex), "danger")
    return redirect(url_for("plans.detail", plan_id=plan_id))


@bp.route("/<plan_id>/consistency", methods=["POST"])
@roles_required(*EDITORS)
def consistency(plan_id):
    db = get_db()
    plan = _plan(plan_id)
    e = db.employees.find_one({"employee_id": plan["employee_id"]})
    try:
        second, _ = generate_plan_json(db, e, f"{plan_id}-consistency")
        result = compare_generations(plan["original_plan_json"], second)
        result["at"] = now()
        db.plans.update_one({"_id": plan["_id"]}, {"$set": {"consistency": result}})
        flash(f"Consistency score {result['consistency_score']}%" + (" - major differences flagged." if result["major_difference"] else "."),
              "warning" if result["major_difference"] else "success")
    except GenerationFailed as ex:
        flash(str(ex), "danger")
    return redirect(url_for("plans.detail", plan_id=plan_id) + "#consistency")


@bp.route("/<plan_id>/json")
@roles_required(*STAFF)
def download_json(plan_id):
    plan = _plan(plan_id)
    body = json.dumps({"plan_id": plan_id, "generation": plan.get("generation"), "plan": plan["plan_json"]}, indent=2, default=str)
    return Response(body, mimetype="application/json", headers={"Content-Disposition": f"attachment; filename={plan_id}.json"})


@bp.route("/compare")
@roles_required(*STAFF)
def compare():
    db = get_db()
    all_plans = list(db.plans.find({}, {"plan_json": 0}).sort("created_at", -1))
    a, b = request.args.get("a"), request.args.get("b")
    pa, pb = (db.plans.find_one({"plan_id": a}) if a else None), (db.plans.find_one({"plan_id": b}) if b else None)
    diff = None
    if pa and pb:
        ra = {rc["requirement_id"] for m in pa["plan_json"]["modules"] for rc in m["requirements_covered"]}
        rb = {rc["requirement_id"] for m in pb["plan_json"]["modules"] for rc in m["requirements_covered"]}
        diff = {"common": sorted(ra & rb), "only_a": sorted(ra - rb), "only_b": sorted(rb - ra),
                "consistency": compare_generations(pa["plan_json"], pb["plan_json"])}
    return render_template("plan_compare.html", all_plans=all_plans, pa=pa, pb=pb, diff=diff)


@bp.route("/review-queue")
@roles_required(*REVIEWERS)
def review_queue():
    db = get_db()
    plans = list(db.plans.find({"status": {"$in": ["Pending Review", "Outdated", "Generated"]}},
                               {"plan_json": 0, "original_plan_json": 0}).sort("created_at", -1))
    return render_template("review_queue.html", plans=plans)


@bp.route("/impact")
@roles_required(*STAFF)
def impact():
    db = get_db()
    reports = list(db.impact_reports.find().sort("detected_at", -1))
    outdated = list(db.plans.find({"status": "Outdated"}, {"plan_json": 0, "original_plan_json": 0}))
    return render_template("impact.html", reports=reports, outdated=outdated)


@bp.route("/topic", methods=["GET", "POST"])
@roles_required(*EDITORS)
def topic():
    result = None
    if request.method == "POST":
        t = request.form.get("topic", "").strip()
        try:
            result = topic_module(get_db(), t)
            result["topic"] = t
            log_audit("topic_request", "topic", t, after="refused" if result["refused"] else "generated")
            if result["refused"]:
                get_db().review_requests.insert_one({"topic": t, "reason": result["reason"], "at": now(),
                                                     "by": session["username"], "status": "Manual Review Required"})
        except GenerationFailed as ex:
            flash(str(ex), "danger")
    return render_template("topic.html", result=result)
