"""Steps 57-59 - Policy update detection, impact analysis and selective regeneration targets."""
from src.audit import now, log_audit


def _cites(item, doc_id, sections):
    if item.get("source_document_id") != doc_id:
        return False
    return not sections or item.get("source_section_id") in sections


def analyse_impact(db, doc_id, old_version, new_version, changes):
    """Finds every plan, module, quiz question, task and checklist item that cites a changed section."""
    changed = {c["section_id"] for c in changes}
    report = {"document_id": doc_id, "old_version": old_version, "new_version": new_version,
              "changed_sections": sorted(changed), "plans": [], "detected_at": now()}
    for plan in db.plans.find({"status": {"$nin": ["Rejected"]}}):
        affected_modules, questions, tasks, checklist = [], [], [], []
        for m in plan["plan_json"].get("modules", []):
            hit = False
            for rc in m.get("requirements_covered", []):
                if _cites(rc, doc_id, changed):
                    hit = True
            for q in m.get("quiz", []):
                if _cites(q, doc_id, changed):
                    questions.append(q["question_id"]); hit = True
            for t in m.get("tasks", []):
                if _cites(t, doc_id, changed):
                    tasks.append(t["task_id"]); hit = True
            for i, ci in enumerate(m.get("checklist", [])):
                if _cites(ci, doc_id, changed):
                    checklist.append(f"{m['module_id']}:{i}"); hit = True
            if hit:
                affected_modules.append(m["module_id"])
        if affected_modules:
            outdated = {"document_id": doc_id, "old_version": old_version, "new_version": new_version,
                        "changed_sections": sorted(changed), "modules": affected_modules,
                        "questions": questions, "tasks": tasks, "checklist": checklist, "detected_at": now()}
            db.plans.update_one({"_id": plan["_id"]}, {"$set": {"status": "Outdated", "outdated": outdated,
                                                                  "status_before_outdated": plan["status"]}})
            log_audit("plan_outdated", "plan", plan["plan_id"], before=plan["status"], after="Outdated",
                      comment=f"{doc_id} v{old_version} -> v{new_version}")
            report["plans"].append({"plan_id": plan["plan_id"], "employee_id": plan["employee_id"],
                                    "role": plan["role"], **outdated})
    db.impact_reports.insert_one(report)
    return report
