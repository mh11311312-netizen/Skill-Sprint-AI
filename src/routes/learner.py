from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from database.db import get_db
from security.auth import login_required
from src.progress import assess, get_progress, grade_quiz
from src.audit import now

bp = Blueprint("learner", __name__, url_prefix="/learner")


def _my_plan():
    db = get_db()
    eid = session.get("employee_id")
    if not eid:
        abort(403)
    e = db.employees.find_one({"employee_id": eid}) or abort(404)
    # the latest plan that a reviewer has approved at least once (it stays visible while it is being updated)
    plan = db.plans.find_one({"employee_id": eid, "approved_at": {"$exists": True}, "status": {"$ne": "Rejected"}},
                             sort=[("approved_at", -1)])
    return db, e, plan


@bp.route("/")
@login_required
def home():
    db, e, plan = _my_plan()
    result = assess(db, plan, e) if plan else None
    return render_template("learner.html", e=e, plan=plan, r=result)


@bp.route("/toggle", methods=["POST"])
@login_required
def toggle():
    db, e, plan = _my_plan()
    if not plan:
        abort(404)
    p = get_progress(db, plan)
    kind, key = request.form["kind"], request.form["key"]
    field = {"module": "modules_done", "checklist": "checklist_done", "task": "tasks_done"}[kind]
    if key in p[field]:
        db.progress.update_one({"_id": p["_id"]}, {"$unset": {f"{field}.{key}": ""}})
    else:
        db.progress.update_one({"_id": p["_id"]}, {"$set": {f"{field}.{key}": now()}})
    return redirect(url_for("learner.home") + f"#{request.form.get('anchor', '')}")


@bp.route("/quiz/<module_id>", methods=["GET", "POST"])
@login_required
def quiz(module_id):
    db, e, plan = _my_plan()
    if not plan:
        abort(404)
    module = next((m for m in plan["plan_json"]["modules"] if m["module_id"] == module_id), None) or abort(404)
    result = None
    if request.method == "POST":
        answers = {q["question_id"]: request.form.getlist(q["question_id"]) for q in module["quiz"]}
        score, correct, total, wrong = grade_quiz(module, answers)
        p = get_progress(db, plan)
        db.progress.update_one({"_id": p["_id"]}, {"$push": {"quiz_attempts": {
            "module_id": module_id, "score": score, "correct": correct, "total": total, "wrong": wrong, "at": now()}}})
        result = {"score": score, "correct": correct, "total": total, "wrong": wrong, "answers": answers}
        flash(f"Quiz submitted: {score}% ({correct}/{total}).", "success" if score >= 70 else "warning")
    return render_template("quiz.html", module=module, result=result, plan=plan)
