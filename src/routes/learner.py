"""Employee learning area: learning path, module pages with study material, checklist, tasks and quizzes."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from database.db import get_db
from security.auth import login_required
from config.loader import load_yaml
from role_matrix.extractor import stage_index
from src.progress import assess, get_progress, grade_quiz
from src.audit import now

bp = Blueprint("learner", __name__, url_prefix="/learner")

CATEGORY_STYLE = {                      # colour + icon used on module cards
    "Policy": ("policy", "journal-bookmark"),
    "Compliance": ("compliance", "shield-check"),
    "Process": ("process", "diagram-3"),
    "Role Skills": ("skills", "person-workspace"),
    "Orientation": ("orientation", "compass"),
}


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


def _module_state(m, p, r):
    """Completed / Overdue / In progress / Not started + share of checklist and tasks done."""
    items = [f"{m['module_id']}:{i}" for i in range(len(m.get("checklist", [])))]
    done = sum(k in p["checklist_done"] for k in items)
    done += sum(t["task_id"] in p["tasks_done"] for t in m.get("tasks", []))
    total = len(items) + len(m.get("tasks", []))
    pct = 100 if m["module_id"] in p["modules_done"] else (round(100 * done / total) if total else 0)
    if m["module_id"] in p["modules_done"]:
        state = "Completed"
    elif m["module_id"] in r["overdue"]:
        state = "Overdue"
    elif done or m["module_id"] in r["best_scores"]:
        state = "In progress"
    else:
        state = "Not started"
    return {"state": state, "pct": pct, "style": CATEGORY_STYLE.get(m.get("category"), ("policy", "book"))}


@bp.route("/")
@login_required
def home():
    db, e, plan = _my_plan()
    if not plan:
        return render_template("learner.html", e=e, plan=None, r=None)
    r = assess(db, plan, e)
    p = r["progress"]
    modules = sorted(plan["plan_json"]["modules"], key=lambda m: stage_index(m["stage"]))
    cards = {m["module_id"]: _module_state(m, p, r) for m in modules}
    next_module = next((m for m in modules if m["module_id"] not in p["modules_done"]), None)
    path = []
    for st in load_yaml("stages.yaml")["stages"]:
        in_stage = [m for m in modules if m["stage"] == st["name"]]
        if not in_stage:
            continue
        done = sum(m["module_id"] in p["modules_done"] for m in in_stage)
        path.append({"name": st["name"], "due_day": st["due_day"], "total": len(in_stage), "done": done,
                     "modules": in_stage,
                     "state": "done" if done == len(in_stage) else ("current" if next_module in in_stage else "upcoming")})
    return render_template("learner.html", e=e, plan=plan, r=r, path=path, cards=cards, next_module=next_module)


@bp.route("/module/<module_id>")
@login_required
def module(module_id):
    db, e, plan = _my_plan()
    if not plan:
        abort(404)
    m = next((x for x in plan["plan_json"]["modules"] if x["module_id"] == module_id), None) or abort(404)
    r = assess(db, plan, e)
    # Study material: the exact source clauses this module is built on (current active versions only)
    wanted = []
    for item in m.get("requirements_covered", []) + m.get("checklist", []):
        key = (item["source_document_id"], item["source_section_id"])
        if key not in wanted:
            wanted.append(key)
    material = []
    for doc_id, sec in wanted:
        d = db.documents.find_one({"document_id": doc_id, "status": "Active"})
        if not d:
            continue
        c = db.chunks.find_one({"document_id": doc_id, "version": d["version"], "section_id": sec, "quarantined": False})
        if c:
            material.append({"doc": d, "chunk": c})
    return render_template("learner_module.html", e=e, plan=plan, m=m, r=r, p=r["progress"],
                           card=_module_state(m, r["progress"], r), material=material)


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
    back = request.form.get("module")
    if back:
        return redirect(url_for("learner.module", module_id=back) + f"#{request.form.get('anchor', '')}")
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
