"""Pipeline 2 - Independent Python ground-truth validation. NO GenAI is used here.
Compares the GenAI plan with the Role Requirement Matrix and the stored source clauses, and
calculates coverage, traceability, consistency, missing / unsupported / contradiction counts."""
from config.loader import load_yaml
from src.audit import now
from src.text_utils import cosine
from role_matrix.extractor import stage_index
from hallucination_checks.support import SourceIndex, support_score, unsupported_numbers
from security.injection import scan_text

STATUS_ORDER = ["Contradictory", "Unsupported", "Incomplete", "Manual Review Required", "Verified with Warning", "Verified"]


def validate_plan(db, plan):
    rules = load_yaml("validation_rules.yaml")
    pj, role = plan["plan_json"], plan["role"]
    idx = SourceIndex(db)
    all_reqs = {r["requirement_id"]: r for r in db.requirements.find()}
    expected = {rid: r for rid, r in all_reqs.items() if r["active"] and role in r["roles"]}
    alias = {rid: r["duplicate_of"] for rid, r in all_reqs.items() if r.get("duplicate_of")}
    issues = []                                           # item-level findings

    def issue(kind, severity, where, message):
        issues.append({"kind": kind, "severity": severity, "where": where, "message": message})

    # ---------- 1. structural / schema-level business checks ----------
    if pj.get("role", "").strip().lower() != role.lower():
        issue("Invalid role", "High", "plan", f"Plan role '{pj.get('role')}' does not match employee role '{role}'.")
    seen = {}
    for m in pj["modules"]:
        for kind, items, key in (("task", m.get("tasks", []), "task_id"), ("question", m.get("quiz", []), "question_id")):
            for it in items:
                if it[key] in seen:
                    issue("Duplicate ID", "Medium", f"{m['module_id']}/{it[key]}", f"{kind} id {it[key]} is used more than once.")
                seen[it[key]] = True
    plan_text = str(pj)
    leaked = scan_text(plan_text)
    if leaked:
        issue("Security", "High", "plan", f"Generated plan contains suspicious instruction-like text: {', '.join(leaked)}.")

    # ---------- 2. requirement-level comparison (GenAI vs Python matrix) ----------
    generated = {}
    for m in pj["modules"]:
        for rc in m.get("requirements_covered", []):
            rid = rc["requirement_id"].strip()
            if rid in generated:
                issue("Duplicate learning content", "Low", f"{m['module_id']}/{rid}",
                      f"{rid} is covered in more than one module ({generated[rid]['module_id']} and {m['module_id']}).")
                continue
            generated[rid] = dict(rc, module_id=m["module_id"], module_stage=m["stage"])

    rows, covered_mandatory = [], set()
    for rid, g in generated.items():
        src_status, chunk = idx.check(g["source_document_id"], g["source_section_id"])
        canonical = alias.get(rid, rid)
        req = all_reqs.get(rid)
        exp = expected.get(canonical)
        sup = support_score(g["statement"], chunk["text"]) if chunk else 0.0
        bad_nums = unsupported_numbers(g["statement"], chunk["text"]) if chunk else []
        row = {"requirement_id": rid, "role": role, "module_id": g["module_id"],
               "genai": {"mandatory": g["mandatory"], "due_stage": g["due_stage"],
                         "source": f"{g['source_document_id']} §{g['source_section_id']}"},
               "python": ({"mandatory": exp["obligation"] == "Mandatory", "due_stage": exp["due_stage"],
                           "priority": exp["priority"], "source": f"{exp['document_id']} §{exp['section_id']}",
                           "text": exp["text"]} if exp else None),
               "source_check": src_status, "support": sup, "field_matches": {}, "explanation": ""}
        if f"{g['source_document_id']}-{g['source_section_id']}" != rid:
            issue("Traceability", "Medium", rid, f"Requirement id {rid} does not match its cited source "
                  f"{g['source_document_id']} §{g['source_section_id']}.")
        if src_status == "missing":
            row["status"], row["explanation"] = "Source Support Missing", "Cited document/section does not exist."
        elif src_status in ("untrusted", "quarantined"):
            row["status"], row["explanation"] = "Unsupported Requirement", "Cited source is untrusted or quarantined (adversarial)."
        elif src_status == "outdated":
            row["status"], row["explanation"] = "Outdated Source", "Cited section exists only in a superseded version."
        elif req and req.get("overridden_by"):
            row["status"] = "Contradiction Detected"
            row["explanation"] = f"Source is overridden by {req['overridden_by']} (precedence rules)."
        elif bad_nums:
            row["status"] = "Contradiction Detected"
            row["explanation"] = f"Numbers {', '.join(bad_nums)} do not appear in the cited source."
        elif sup < rules["support_similarity_min"]:
            row["status"], row["explanation"] = "Unsupported Requirement", f"Low similarity to the cited source ({sup}) - possible hallucination."
        elif req is None:
            if g["mandatory"]:
                row["status"], row["explanation"] = "Unsupported Requirement", "Cited clause is informational, not a mandatory requirement."
            else:
                row["status"], row["explanation"] = "Verified with Warning", "Informational clause used as learning content."
        elif exp is None:
            row["status"], row["explanation"] = "Manual Review Required", f"Valid requirement but not applicable to the role {role}."
        else:
            fm = {"mandatory": g["mandatory"] == (exp["obligation"] == "Mandatory"),
                  "source_document": g["source_document_id"] == exp["document_id"] or canonical != rid,
                  "source_section": g["source_section_id"] == exp["section_id"] or canonical != rid,
                  "due_stage": g["due_stage"] == exp["due_stage"]}
            row["field_matches"] = fm
            if not fm["mandatory"]:
                row["status"], row["explanation"] = "Partially Verified", "Mandatory/optional status differs from the matrix."
            elif not fm["due_stage"]:
                row["status"], row["explanation"] = "Verified with Warning", f"Due stage differs (matrix: {exp['due_stage']})."
            else:
                row["status"] = "Verified"
            if exp["obligation"] == "Mandatory":
                covered_mandatory.add(canonical)
        rows.append(row)

    for rid, exp in expected.items():
        if rid in covered_mandatory or any(alias.get(g, g) == rid for g in generated):
            continue
        if exp["obligation"] == "Mandatory":
            rows.append({"requirement_id": rid, "role": role, "module_id": None, "genai": None,
                         "python": {"mandatory": True, "due_stage": exp["due_stage"], "priority": exp["priority"],
                                    "source": f"{exp['document_id']} §{exp['section_id']}", "text": exp["text"]},
                         "source_check": "-", "support": None, "field_matches": {},
                         "status": "Requirement Missing", "explanation": "Mandatory requirement from the matrix is not covered."})
        else:
            rows.append({"requirement_id": rid, "role": role, "module_id": None, "genai": None,
                         "python": {"mandatory": False, "due_stage": exp["due_stage"], "priority": exp["priority"],
                                    "source": f"{exp['document_id']} §{exp['section_id']}", "text": exp["text"]},
                         "source_check": "-", "support": None, "field_matches": {},
                         "status": "Optional Not Included", "explanation": f"{exp['obligation']} item - inclusion is optional."})

    # ---------- 3. item-level traceability, hallucination and quiz checks ----------
    traced, total_items, mand_traced, mand_total = 0, 0, 0, 0
    for m in pj["modules"]:
        items = ([("requirement", rc, rc["statement"]) for rc in m.get("requirements_covered", [])] +
                 [("checklist", c, c["activity"]) for c in m.get("checklist", [])] +
                 [("task", t, t["description"] + " " + t["expected_outcome"]) for t in m.get("tasks", [])] +
                 [("quiz", q, q["question"] + " " + " ".join(q["correct_answers"])) for q in m.get("quiz", [])])
        for kind, it, text in items:
            total_items += 1
            st, chunk = idx.check(it["source_document_id"], it["source_section_id"])
            ok = st == "valid"
            traced += ok
            if m["mandatory"]:
                mand_total += 1
                mand_traced += ok
            where = f"{m['module_id']} {kind} [{it['source_document_id']} §{it['source_section_id']}]"
            if not ok:
                issue("Traceability", "High" if kind == "requirement" else "Medium", where, f"Source is {st}.")
                continue
            if kind == "quiz":
                _check_quiz(it, chunk, rules, issue, where)
            elif kind in ("task", "checklist"):
                s = support_score(text, chunk["text"])
                if s < rules["quiz_support_similarity_min"]:
                    issue("Possible hallucination", "Medium", where, f"{kind.title()} is weakly related to its cited source (similarity {s}).")
                nums = unsupported_numbers(text, chunk["text"])
                if nums:
                    issue("Unsupported fact", "High", where, f"Numbers {', '.join(nums)} are not in the cited source.")

    # ---------- 4. sequencing, prerequisites, duplicates, stage spread ----------
    _check_sequence(pj, expected, alias, issue)
    _check_duplicates(pj, rules, issue)
    day1 = sum(1 for m in pj["modules"] if m["stage"] == "Day 1")
    if pj["modules"] and day1 / len(pj["modules"]) > rules["day1_max_share"]:
        issue("Sequencing", "Medium", "plan", f"{day1} of {len(pj['modules'])} modules are on Day 1 - training is not staged.")
    for m in pj["modules"]:
        a = m.get("assessment") or {}
        if a.get("type") == "practical" and a.get("rubric") and sum(r["weight"] for r in a["rubric"]) != 100:
            issue("Assessment rubric", "Low", m["module_id"], "Rubric weights do not add up to 100.")

    # ---------- 5. scores and final status ----------
    mandatory_expected = [rid for rid, r in expected.items() if r["obligation"] == "Mandatory"]
    count = lambda *s: sum(1 for r in rows if r["status"] in s)
    compared = [r for r in rows if r["field_matches"]]
    field_total = sum(len(r["field_matches"]) for r in compared)
    field_ok = sum(sum(r["field_matches"].values()) for r in compared)
    scores = {
        "coverage": round(100 * len(covered_mandatory) / len(mandatory_expected), 1) if mandatory_expected else 0.0,
        "traceability": round(100 * traced / total_items, 1) if total_items else 0.0,
        "mandatory_traceability": round(100 * mand_traced / mand_total, 1) if mand_total else 0.0,
        "requirement_consistency": round(100 * field_ok / field_total, 1) if field_total else 0.0,
        "mandatory_expected": len(mandatory_expected), "mandatory_covered": len(covered_mandatory),
        "missing_count": count("Requirement Missing"),
        "unsupported_count": count("Unsupported Requirement", "Source Support Missing"),
        "contradiction_count": count("Contradiction Detected"),
        "outdated_count": count("Outdated Source"),
        "hallucination_flags": sum(1 for i in issues if i["kind"] in ("Possible hallucination", "Unsupported fact"))
                               + count("Unsupported Requirement"),
        "manual_review_count": count("Manual Review Required"),
    }
    high = [i for i in issues if i["severity"] == "High"]
    if scores["contradiction_count"] or scores["outdated_count"]:
        status = "Contradictory"
    elif scores["unsupported_count"] or any(i["kind"] in ("Unsupported fact", "Security") for i in high):
        status = "Unsupported"
    elif scores["missing_count"] or scores["coverage"] < 100:
        status = "Incomplete"
    elif scores["manual_review_count"] or high:
        status = "Manual Review Required"
    elif issues or count("Verified with Warning", "Partially Verified"):
        status = "Verified with Warning"
    else:
        status = "Verified"
    status_counts = {}
    for r in rows:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    return {"checked_at": now(), "status": status, "scores": scores, "rows": rows, "issues": issues,
            "status_counts": status_counts, "matrix_size": len(expected)}


def _check_quiz(q, chunk, rules, issue, where):
    if not set(q["correct_answers"]) <= set(q["options"]):
        issue("Quiz answer", "High", where, "Correct answer is not one of the options.")
    if len(set(o.strip().lower() for o in q["options"])) != len(q["options"]):
        issue("Quiz distractor", "Medium", where, "Options contain duplicates.")
    if q["type"] == "true_false" and sorted(q["options"]) != ["False", "True"]:
        issue("Quiz format", "Low", where, "True/False question must have exactly the options True and False.")
    if q["type"] in ("multiple_choice", "true_false", "scenario") and len(q["correct_answers"]) != 1:
        issue("Quiz answer", "Medium", where, f"{q['type']} question must have exactly one correct answer.")
    s = support_score(q["question"] + " " + " ".join(q["correct_answers"]), chunk["text"])
    if s < rules["quiz_support_similarity_min"]:
        issue("Possible hallucination", "Medium", where, f"Question is weakly related to its cited source (similarity {s}).")
    nums = unsupported_numbers(" ".join(q["correct_answers"]), chunk["text"])
    if nums:
        issue("Unsupported fact", "High", where, f"Correct answer uses {', '.join(nums)}, which is not in the source.")
    for wrong in set(q["options"]) - set(q["correct_answers"]):
        if wrong.strip().lower() in chunk["text"].lower() and len(wrong) > 12:
            issue("Quiz distractor", "Medium", where, f"Distractor '{wrong[:60]}' is literally stated in the source.")


def _check_sequence(pj, expected, alias, issue):
    mods = {m["module_id"]: m for m in pj["modules"]}
    req_module = {}
    for m in pj["modules"]:
        for rc in m.get("requirements_covered", []):
            req_module[alias.get(rc["requirement_id"], rc["requirement_id"])] = m
    for m in pj["modules"]:
        for p in m.get("prerequisites", []):
            if p not in mods:
                issue("Prerequisite", "Medium", m["module_id"], f"Prerequisite module {p} does not exist.")
            elif stage_index(mods[p]["stage"]) > stage_index(m["stage"]):
                issue("Sequencing", "High", m["module_id"], f"Scheduled before its prerequisite {p} ({mods[p]['stage']}).")
        for rc in m.get("requirements_covered", []):
            r = expected.get(alias.get(rc["requirement_id"], rc["requirement_id"]))
            for pre in (r or {}).get("prerequisites", []):
                pm = req_module.get(pre)
                if pm is None:
                    issue("Missing prerequisite", "Medium", m["module_id"], f"{r['requirement_id']} needs {pre}, which is not in the plan.")
                elif stage_index(pm["stage"]) > stage_index(m["stage"]):
                    issue("Sequencing", "High", m["module_id"],
                          f"{r['requirement_id']} ({m['stage']}) comes before its prerequisite {pre} ({pm['stage']}).")


def _check_duplicates(pj, rules, issue):
    th = rules["duplicate_similarity"]
    mods = pj["modules"]
    for i in range(len(mods)):
        for j in range(i + 1, len(mods)):
            if cosine(mods[i]["module_title"] + " " + mods[i]["purpose"], mods[j]["module_title"] + " " + mods[j]["purpose"]) >= th:
                issue("Duplicate learning content", "Medium", f"{mods[i]['module_id']}/{mods[j]['module_id']}", "Modules are near-duplicates.")
    qs = [(m["module_id"], q) for m in mods for q in m.get("quiz", [])]
    for i in range(len(qs)):
        for j in range(i + 1, len(qs)):
            if cosine(qs[i][1]["question"], qs[j][1]["question"]) >= th:
                issue("Duplicate learning content", "Low", f"{qs[i][1]['question_id']}/{qs[j][1]['question_id']}", "Quiz questions are near-duplicates.")
    tasks = [t for m in mods for t in m.get("tasks", [])]
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            if cosine(tasks[i]["description"], tasks[j]["description"]) >= th:
                issue("Duplicate learning content", "Low", f"{tasks[i]['task_id']}/{tasks[j]['task_id']}", "Tasks are near-duplicates.")


def run_validation(db, plan, user="system"):
    """Validates and stores the result. The plan moves to Verified or Pending Review."""
    result = validate_plan(db, plan)
    new_status = "Verified" if result["status"] == "Verified" else "Pending Review"
    if plan.get("status") in ("Approved",):
        new_status = plan["status"]
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"validation": result, "status": new_status},
                                               "$push": {"validation_history": {"at": result["checked_at"],
                                                         "status": result["status"], "scores": result["scores"]}}})
    return result
