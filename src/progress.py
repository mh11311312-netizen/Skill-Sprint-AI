"""Steps 50-56 - Progress tracking, progress assessment, weak-area detection and adaptive recommendations."""
from datetime import date, datetime
from config.loader import load_yaml
from src.audit import now


def _due_days():
    return {s["name"]: s["due_day"] for s in load_yaml("stages.yaml")["stages"]}


def get_progress(db, plan):
    p = db.progress.find_one({"plan_id": plan["plan_id"]})
    if not p:
        p = {"plan_id": plan["plan_id"], "employee_id": plan["employee_id"], "modules_done": {},
             "checklist_done": {}, "tasks_done": {}, "quiz_attempts": [], "created_at": now()}
        db.progress.insert_one(p)
    return p


def days_since_joining(employee):
    try:
        j = datetime.strptime(employee["joining_date"], "%Y-%m-%d").date()
    except (KeyError, ValueError, TypeError):
        return 0
    return max(0, (date.today() - j).days + 1)


def assess(db, plan, employee):
    """Returns percentages, status, weak areas and recommendations for one employee plan."""
    p = get_progress(db, plan)
    pass_mark = load_yaml("validation_rules.yaml")["quiz_pass_mark"]
    due = _due_days()
    mods = plan["plan_json"]["modules"]
    day = days_since_joining(employee)

    checklist = [(f"{m['module_id']}:{i}", c) for m in mods for i, c in enumerate(m.get("checklist", []))]
    tasks = [t for m in mods for t in m.get("tasks", [])]
    best, attempts = {}, {}
    for a in p["quiz_attempts"]:
        best[a["module_id"]] = max(best.get(a["module_id"], 0), a["score"])
        attempts.setdefault(a["module_id"], []).append(a)
    quiz_modules = [m for m in mods if m.get("quiz")]

    pct = lambda done, total: round(100 * done / total, 1) if total else 100.0
    module_pct = pct(sum(m["module_id"] in p["modules_done"] for m in mods), len(mods))
    checklist_pct = pct(sum(k in p["checklist_done"] for k, _ in checklist), len(checklist))
    task_pct = pct(sum(t["task_id"] in p["tasks_done"] for t in tasks), len(tasks))
    quiz_avg = round(sum(best.get(m["module_id"], 0) for m in quiz_modules) / len(quiz_modules), 1) if quiz_modules else 100.0
    overall = round(0.4 * module_pct + 0.2 * checklist_pct + 0.2 * task_pct + 0.2 * quiz_avg, 1)

    overdue = [m for m in mods if m["module_id"] not in p["modules_done"] and due.get(m["stage"], 999) < day]
    failed_twice = [mid for mid, a in attempts.items() if sum(x["score"] < pass_mark for x in a) >= 2]
    weak = []
    for m in quiz_modules:
        mid = m["module_id"]
        if mid in best and best[mid] < pass_mark:
            wrong = {q for a in attempts[mid] for q in a.get("wrong", [])}
            weak.append({"module_id": mid, "topic": m["module_title"], "best_score": best[mid],
                         "attempts": len(attempts[mid]), "wrong_questions": sorted(wrong)})
    incomplete_tasks = [t for t in tasks if t["task_id"] not in p["tasks_done"] and due.get(t["due_stage"], 999) < day]

    all_done = module_pct == 100.0
    quizzes_passed = all(best.get(m["module_id"], 0) >= pass_mark for m in quiz_modules)
    if all_done and quizzes_passed:
        status = "Completed"
    elif all_done:
        status = "Assessment Required"
    elif weak or failed_twice:
        status = "Requires Attention"
    elif overdue:
        status = "Behind Schedule"
    else:
        status = "On Track"

    recs = []
    for w in weak:
        recs.append({"type": "Revision module", "text": f"Revise '{w['topic']}' and re-read its source sections."})
        recs.append({"type": "Additional quiz", "text": f"Retake the {w['module_id']} quiz after revision."})
    for mid in failed_twice:
        recs.append({"type": "Manager review", "text": f"Quiz for {mid} failed twice - refer to the reporting manager (CMP-01 rule)."})
    for t in incomplete_tasks[:3]:
        recs.append({"type": "Additional task", "text": f"Overdue task {t['task_id']}: {t['description'][:90]}"})
    if all_done and quizzes_passed and quiz_avg >= 90:
        recs.append({"type": "Advanced module", "text": "Strong results - ready for advanced role modules."})
    result = {"module_pct": module_pct, "checklist_pct": checklist_pct, "task_pct": task_pct, "quiz_avg": quiz_avg,
              "overall": overall, "status": status, "day": day, "overdue": [m["module_id"] for m in overdue],
              "weak_areas": weak, "recommendations": recs, "best_scores": best, "progress": p}
    db.employees.update_one({"employee_id": plan["employee_id"]},
                            {"$set": {"training_status": status, "progress_pct": overall}})
    return result


def grade_quiz(module, answers):
    """answers: {question_id: [selected options]} -> score, wrong question ids."""
    qs = module.get("quiz", [])
    correct = sum(1 for q in qs if sorted(answers.get(q["question_id"], [])) == sorted(q["correct_answers"]))
    wrong = [q["question_id"] for q in qs if sorted(answers.get(q["question_id"], [])) != sorted(q["correct_answers"])]
    return (round(100 * correct / len(qs), 1) if qs else 100.0), correct, len(qs), wrong
