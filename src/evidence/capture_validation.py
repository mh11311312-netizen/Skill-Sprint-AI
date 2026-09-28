"""Evidence capture for Deliverables 5 and 6.
Runs the REAL document pipeline, Role Requirement Matrix builder and Python validator (Pipeline 2),
generates one plan per role with Pipeline 1, and records every result the two PDFs need.
Default: offline stand-in model.  --live: the real API configured in .env."""
import copy
import csv
import glob
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
PACK = os.path.join(ROOT, "sample_documents", "Sitara_Bank_Company_Pack")
OUT = os.path.join(ROOT, "documentation", "evidence", "validation_capture.json")


def _csv(name):
    return list(csv.DictReader(open(os.path.join(PACK, "data", name), encoding="utf-8-sig")))


def _clean(d):
    return {k: (str(v) if k in ("at", "built_at", "checked_at") else v) for k, v in d.items() if k != "_id"}


def _norm_roles(txt):
    return sorted(x.strip() for x in txt.split(";") if x.strip())


def capture(live=False):
    from app import create_app
    from database.db import get_db
    from src.seed import seed
    from document_processing.ingest import ingest, IngestError
    from genai_pipeline.client import set_client_override, get_client
    from genai_pipeline import generator as G
    from python_validation.validator import validate_plan
    from schemas.plan_schema import OnboardingPlan
    from pydantic import ValidationError
    from role_matrix import extractor as ex
    from config.loader import load_yaml

    app = create_app({"USE_MONGOMOCK": True, "TESTING": not live, "WTF_CSRF_ENABLED": False, "MONGO_DB": "validation_evidence"})
    b = {"live": live, "captured_at": time.strftime("%Y-%m-%d %H:%M"), "rules": load_yaml("validation_rules.yaml")}
    with app.test_request_context():
        db = get_db()
        seed(db)
        # ---------------- ingest the whole pack ----------------
        ing = []
        for sub in ("active", "superseded", "adversarial"):
            for f in sorted(glob.glob(os.path.join(PACK, "documents", sub, "docx", "*.docx"))):
                try:
                    d, _, _ = ingest(db, os.path.basename(f), open(f, "rb").read(), {}, app.config, "evidence")
                    ing.append({"file": os.path.basename(f), "folder": sub, "status": d["status"], "trust": d["trust"], "chunks": d["chunk_count"]})
                except IngestError as e:
                    ing.append({"file": os.path.basename(f), "folder": sub, "error": "; ".join(e.errors)})
        b["ingest"] = ing
        b["chunks"] = {"total": db.chunks.count_documents({}), "active": db.chunks.count_documents({"status": "Active"}),
                       "quarantined": db.chunks.count_documents({"quarantined": True})}

        # ---------------- 1. requirement extraction ----------------
        reqs = {r["requirement_id"]: r for r in db.requirements.find()}
        samples = []
        for rid in ("POL-01-2.1", "POL-04-3.2", "POL-01-5.2", "SOP-04-3.1", "PRC-01-2.3", "POL-03-2.2", "FAQ-01-2.1"):
            r = reqs.get(rid)
            if r:
                samples.append({k: r.get(k) for k in ("requirement_id", "text", "obligation", "requirement_type", "roles", "role_scope",
                                                      "role_resolution", "due_stage", "priority", "assessment", "prerequisites",
                                                      "overridden_by", "duplicate_of", "active")})
        b["extraction_samples"] = samples
        # agreement with the team's hand-made answer key
        key = {r["requirement_id"]: r for r in _csv("requirements_master.csv")}
        agree = {"compared": 0, "obligation": 0, "due_stage": 0, "priority": 0, "roles": 0, "active": 0}
        diffs = []
        for rid, k in key.items():
            r = reqs.get(rid)
            if not r:
                diffs.append({"requirement_id": rid, "field": "presence", "answer_key": "present", "extracted": "not found"})
                continue
            agree["compared"] += 1
            key_active = k["include_in_active_matrix"].strip().lower() in ("yes", "true", "1")
            pairs = [("obligation", k["obligation"], r["obligation"]), ("due_stage", k["due_stage"], r["due_stage"]),
                     ("priority", k["priority"], r["priority"]),
                     ("roles", _norm_roles(k["applicable_roles"]), sorted(r["roles"])), ("active", key_active, bool(r["active"]))]
            for f, kv, rv in pairs:
                if kv == rv:
                    agree[f] += 1
                elif len(diffs) < 400:
                    diffs.append({"requirement_id": rid, "field": f, "answer_key": kv if f != "roles" else f"{len(kv)} roles",
                                  "extracted": rv if f != "roles" else f"{len(rv)} roles"})
        b["extraction_agreement"] = {"key_size": len(key), "extracted": len(reqs), **agree, "differences": diffs}
        by_ob = {}
        for r in reqs.values():
            by_ob[r["obligation"]] = by_ob.get(r["obligation"], 0) + 1
        b["extraction_by_obligation"] = by_ob
        b["extraction_by_resolution"] = {}
        for r in reqs.values():
            b["extraction_by_resolution"][r.get("role_resolution", "?")] = b["extraction_by_resolution"].get(r.get("role_resolution", "?"), 0) + 1

        # ---------------- 2. requirement matrix ----------------
        roles = [r["name"] for r in db.roles.find().sort("role_id", 1)]
        mat = []
        for ro in roles:
            rs = [r for r in reqs.values() if r["active"] and ro in r["roles"]]
            mat.append({"role": ro, "total": len(rs), "mandatory": sum(r["obligation"] == "Mandatory" for r in rs),
                        "recommended": sum(r["obligation"] == "Recommended" for r in rs), "optional": sum(r["obligation"] == "Optional" for r in rs),
                        "role_specific": sum(r["role_scope"] == "Role-Specific" for r in rs)})
        b["matrix"] = {"roles": mat, "total": len(reqs), "active": sum(r["active"] for r in reqs.values()),
                       "mandatory_active": sum(r["active"] and r["obligation"] == "Mandatory" for r in reqs.values()),
                       "role_specific_active": sum(r["active"] and r["role_scope"] == "Role-Specific" for r in reqs.values()),
                       "inactive": [{"requirement_id": r["requirement_id"], "overridden_by": r.get("overridden_by"), "duplicate_of": r.get("duplicate_of")}
                                    for r in reqs.values() if not r["active"]]}
        cso = sorted([r for r in reqs.values() if r["active"] and "Customer Service Officer" in r["roles"]],
                     key=lambda r: (ex.stage_index(r["due_stage"]), r["requirement_id"]))
        b["matrix_sample"] = [{k: r.get(k) for k in ("requirement_id", "text", "obligation", "requirement_type", "due_stage", "priority", "assessment", "role_scope")}
                              for r in cso[:14]]

        # ---------------- 7/8. contradictions and duplicates vs the answer key ----------------
        conf = [_clean(c) for c in db.conflicts.find()]
        b["conflicts"] = conf
        answer = _csv("conflict_cases.csv")
        found_pairs = []
        for c in conf:
            if c["kind"] == "conflict":
                found_pairs.append({c["a"]["id"], c["b"]["id"]})
        results = []
        import re
        for a in answer:
            ids = set()
            for m in re.finditer(r"([A-Z]{2,4}-\d{2})(?: v[\d.]+)? §([\d.]+)", a["statement_a"] + " " + a["statement_b"]):
                ids.add(f"{m.group(1)}-{m.group(2)}")
            hit = next((c for c in conf if c["kind"] == "conflict" and len({c["a"]["id"], c["b"]["id"]} & ids) >= 2), None)
            ref = next((c for c in conf if c["kind"] == "missing_reference" and c.get("statement") in ids), None)
            if hit:
                pv = re.sub(r" v[\d.]+", "", a["prevailing_source"]).replace(" §", "-")
                if a["prevailing_source"] == "Both valid":
                    ok, got = hit.get("status") == "Both valid", hit.get("status")
                else:
                    ok, got = hit.get("winner") == pv, hit.get("winner") or hit.get("status")
                results.append({"case": a["case_id"], "type": a["type"], "expected": a["prevailing_source"], "detected": True,
                                "result": got, "rule": hit.get("rule", ""), "correct": ok})
            elif ref:
                results.append({"case": a["case_id"], "type": a["type"], "expected": "Flag missing source", "detected": True,
                                "result": f"Missing reference: {ref['referenced']}", "rule": "Referenced document is not in the pack", "correct": True})
            else:
                results.append({"case": a["case_id"], "type": a["type"], "expected": a["prevailing_source"], "detected": False,
                                "result": "not detected", "rule": "", "correct": False})
        b["conflict_vs_key"] = results
        dkey = _csv("duplicate_cases.csv")
        b["duplicates_vs_key"] = [{"requirement_id": d["requirement_id"], "expected_duplicate_of": d["duplicate_of"],
                                   "detected_duplicate_of": (reqs.get(d["requirement_id"]) or {}).get("duplicate_of"),
                                   "correct": (reqs.get(d["requirement_id"]) or {}).get("duplicate_of") == d["duplicate_of"]} for d in dkey]

        # ---------------- plans for every role (Deliverable 6 + base plan for demos) ----------------
        if live:
            set_client_override(None)
            client = get_client()
        else:
            from tests.fake_llm import FakeLLM
            client = FakeLLM()
        set_client_override(client)
        b["model_used"] = getattr(client, "model", "unknown")
        plans = []
        for ro in roles:
            emp = db.employees.find_one({"role": ro})
            if not emp:
                continue
            t0 = time.time()
            try:
                plan = G.create_plan(db, emp, "evidence")
            except G.GenerationFailed as e:
                plans.append({"role": ro, "employee_id": emp["employee_id"], "error": str(e)})
                continue
            v = validate_plan(db, plan)
            plans.append({"role": ro, "employee_id": emp["employee_id"], "name": emp["full_name"], "plan_id": plan["plan_id"],
                          "seconds": round(time.time() - t0, 1), "modules": len(plan["plan_json"]["modules"]),
                          "status": v["status"], "scores": v["scores"], "status_counts": v["status_counts"],
                          "rows": v["rows"], "issues": v["issues"][:60], "issue_count": len(v["issues"])})
            if emp["employee_id"] == "EMP-002":
                base = plan
        b["plans"] = plans

        # ---------------- validation demonstrations on one real plan ----------------
        base = db.plans.find_one({"employee_id": "EMP-002"}, sort=[("created_at", -1)])
        pj0 = base["plan_json"]
        v0 = validate_plan(db, base)
        b["baseline"] = {"plan_id": base["plan_id"], "status": v0["status"], "scores": v0["scores"], "status_counts": v0["status_counts"],
                         "issue_counts": {}, "rows_not_verified": [r for r in v0["rows"] if r["status"] not in ("Verified", "Optional Not Included")]}
        for i in v0["issues"]:
            b["baseline"]["issue_counts"][i["kind"]] = b["baseline"]["issue_counts"].get(i["kind"], 0) + 1
        base_rows = {(r["requirement_id"], r["status"]) for r in v0["rows"]}
        base_issues = {(i["kind"], i["where"], i["message"]) for i in v0["issues"]}

        def run(mutator):
            p = copy.deepcopy(base)
            info = mutator(p["plan_json"])
            v = validate_plan(db, p)
            return info, v

        def find_rc(pj, pred):
            for m in pj["modules"]:
                for rc in m["requirements_covered"]:
                    if pred(rc):
                        return m, rc
            return None, None

        demos = {}
        # source validation: missing section, untrusted document, superseded-only version
        def m_missing(pj):
            m, rc = find_rc(pj, lambda rc: rc["requirement_id"] == "POL-04-3.2") or (None, None)
            if not rc:
                m, rc = pj["modules"][0], pj["modules"][0]["requirements_covered"][0]
            before = rc["source_section_id"]
            rc["source_section_id"], rc["requirement_id"] = "9.9", rc["source_document_id"] + "-9.9"
            return {"changed": f"{m['module_id']}: cited {rc['source_document_id']} §{before} changed to §9.9 (does not exist)", "rid": rc["requirement_id"]}
        demos["source_missing"] = run(m_missing)

        def m_untrusted(pj):
            m = pj["modules"][0]
            m["requirements_covered"].append({"source_document_id": "ADV-01", "source_section_id": "1.1", "requirement_id": "ADV-01-1.1",
                                              "statement": "Greet every customer within 30 seconds of arrival at the counter.", "mandatory": True, "due_stage": "Week 1"})
            return {"changed": f"{m['module_id']}: added a requirement citing ADV-01 §1.1 (an adversarial, untrusted document)", "rid": "ADV-01-1.1"}
        demos["source_untrusted"] = run(m_untrusted)

        # coverage: remove the requirements of several modules
        def m_cov(pj):
            removed = []
            for m in pj["modules"][:4]:
                removed += [rc["requirement_id"] for rc in m["requirements_covered"]]
            pj["modules"] = pj["modules"][4:]
            return {"changed": f"removed the first 4 modules ({len(removed)} requirements)", "removed": removed}
        demos["coverage"] = run(m_cov)

        # traceability: checklist item and quiz question pointing at nothing
        def m_trace(pj):
            m = pj["modules"][0]
            if m["checklist"]:
                m["checklist"][0]["source_section_id"] = "7.7"
            if m["quiz"]:
                m["quiz"][0]["source_document_id"] = "POL-99"
            return {"changed": f"{m['module_id']}: a checklist item cites a non-existent section, a quiz question cites a non-existent document"}
        demos["traceability"] = run(m_trace)

        # duplicates: the same requirement in two modules + an identical copy of a module
        def m_dup(pj):
            a, bmod = pj["modules"][0], pj["modules"][1]
            bmod["requirements_covered"].append(copy.deepcopy(a["requirements_covered"][0]))
            clone = copy.deepcopy(a)
            clone["module_id"] = "M99"
            for i, t in enumerate(clone["tasks"]):
                t["task_id"] = f"M99-T{i+1}"
            for i, q in enumerate(clone["quiz"]):
                q["question_id"] = f"M99-Q{i+1}"
            clone["requirements_covered"] = clone["requirements_covered"][:1]
            pj["modules"].append(clone)
            return {"changed": f"{a['requirements_covered'][0]['requirement_id']} added to {bmod['module_id']} as well; module {a['module_id']} copied as M99"}
        demos["duplicates"] = run(m_dup)

        # role relevance: a valid requirement that belongs to another role
        other = next((r for r in reqs.values() if r["active"] and "Customer Service Officer" not in r["roles"] and r["role_scope"] == "Role-Specific"
                      and r["obligation"] == "Mandatory"), None)
        def m_role(pj):
            m = pj["modules"][0]
            m["requirements_covered"].append({"source_document_id": other["document_id"], "source_section_id": other["section_id"],
                                              "requirement_id": other["requirement_id"], "statement": other["text"], "mandatory": True, "due_stage": other["due_stage"]})
            return {"changed": f"{m['module_id']}: added {other['requirement_id']} ({', '.join(other['roles'])} only) to a Customer Service Officer plan",
                    "rid": other["requirement_id"], "text": other["text"]}
        demos["role_relevance"] = run(m_role)

        # contradiction: an overruled source, and a changed number
        def m_contra(pj):
            m = pj["modules"][0]
            out = []
            cited = {rc["requirement_id"] for mm in pj["modules"] for rc in mm["requirements_covered"]}
            lost = next((r for r in reqs.values() if r.get("overridden_by") and r["requirement_id"] not in cited
                         and "Customer Service Officer" in r["roles"]), None) or \
                   next((r for r in reqs.values() if r.get("overridden_by") and r["requirement_id"] not in cited), None)
            if lost:
                m["requirements_covered"].append({"source_document_id": lost["document_id"], "source_section_id": lost["section_id"],
                                                  "requirement_id": lost["requirement_id"], "statement": lost["text"], "mandatory": True, "due_stage": lost["due_stage"]})
                out.append(f"added {lost['requirement_id']} (overruled by {lost['overridden_by']})")
            mm, rc = find_rc(pj, lambda rc: any(ch.isdigit() for ch in rc["statement"]) and rc["requirement_id"] != (lost or {}).get("requirement_id"))
            if rc:
                import re
                old = rc["statement"]
                rc["statement"] = re.sub(r"\d+", lambda x: str(int(x.group()) + 7), old, count=1)
                out.append(f"{rc['requirement_id']}: '{old}' changed to '{rc['statement']}'")
            return {"changed": "; ".join(out), "lost": lost and lost["requirement_id"], "lost_by": lost and lost["overridden_by"],
                    "num_rid": rc and rc["requirement_id"]}
        demos["contradiction"] = run(m_contra)

        # hallucination: an invented rule citing a real section, and an invented quiz fact
        def m_hall(pj):
            m, rc = find_rc(pj, lambda rc: True)
            old = rc["statement"]
            rc["statement"] = "Employees receive a free annual gym membership and two extra paid holidays after their first week."
            q = next((q for mm in pj["modules"] for q in mm["quiz"] if q["type"] in ("multiple_choice", "true_false")), None)
            qinfo = None
            if q:
                q["question"] = "How many free lunch vouchers does every new joiner receive per month?"
                q["options"], q["correct_answers"] = ["12", "20", "25"], ["25"]
                qinfo = q["question_id"]
            return {"changed": f"{rc['requirement_id']}: statement replaced with an invented benefit; quiz {qinfo} replaced with an invented fact",
                    "rid": rc["requirement_id"], "old": old, "quiz": qinfo}
        demos["hallucination"] = run(m_hall)

        # quiz answer not among the options, and a bad sequence
        def m_quiz(pj):
            q = next((q for m in pj["modules"] for q in m["quiz"] if q["type"] == "multiple_choice"), None) or pj["modules"][0]["quiz"][0]
            q["correct_answers"] = ["An answer that is not in the list"]
            late = next((m for m in pj["modules"] if m["stage"] != "Day 1"), pj["modules"][-1])
            first = next((m for m in pj["modules"] if m["stage"] == "Day 1"), pj["modules"][0])
            first["prerequisites"] = [late["module_id"]]
            return {"changed": f"quiz {q['question_id']}: correct answer set to a value outside its options; {first['module_id']} ({first['stage']}) made to depend on {late['module_id']} ({late['stage']})"}
        demos["quiz_sequence"] = run(m_quiz)

        # invalid skip reason
        def m_skip(pj):
            pj["insufficient_information"] = ["POL-02-3.1: overruled by POL-02-2.3", "POL-04-3.2: overruled by FAQ-02-1.1"]
            removed = []
            for m in pj["modules"]:
                keep = [rc for rc in m["requirements_covered"] if rc["requirement_id"] not in ("POL-02-3.1", "POL-04-3.2")]
                removed += [rc["requirement_id"] for rc in m["requirements_covered"] if rc not in keep]
                m["requirements_covered"] = keep or m["requirements_covered"]
            return {"changed": "model claims POL-02-3.1 is overruled by another clause of POL-02, and POL-04-3.2 is overruled by an FAQ"}
        demos["skip"] = run(m_skip)

        def pack(k, info_v, keep_status=None):
            info, v = info_v
            new_rows = [r for r in v["rows"] if (r["requirement_id"], r["status"]) not in base_rows]
            new_issues = [i for i in v["issues"] if (i["kind"], i["where"], i["message"]) not in base_issues]
            return {"info": info, "status": v["status"], "scores": v["scores"], "status_counts": v["status_counts"],
                    "new_rows": new_rows[:40], "new_issues": new_issues[:40]}
        b["demos"] = {k: pack(k, x) for k, x in demos.items()}

        # schema validation
        good = copy.deepcopy(pj0)
        cases = []
        def schema_case(title, mut):
            d = copy.deepcopy(good)
            mut(d)
            try:
                OnboardingPlan.model_validate(d)
                cases.append({"case": title, "result": "accepted", "errors": []})
            except ValidationError as e:
                cases.append({"case": title, "result": "rejected",
                              "errors": [{"loc": ".".join(str(x) for x in er["loc"]), "msg": er["msg"]} for er in e.errors()][:4]})
        schema_case("Valid plan returned by the model", lambda d: None)
        schema_case("Module category outside the allowed list", lambda d: d["modules"][0].__setitem__("category", "Miscellaneous"))
        schema_case("Module with no covered requirement", lambda d: d["modules"][0].__setitem__("requirements_covered", []))
        schema_case("Checklist item without a source", lambda d: d["modules"][0]["checklist"][0].pop("source_document_id") if d["modules"][0]["checklist"] else None)
        schema_case("Quiz type not supported", lambda d: d["modules"][0]["quiz"][0].__setitem__("type", "essay") if d["modules"][0]["quiz"] else None)
        schema_case("Duration of 2,000 minutes", lambda d: d["modules"][0].__setitem__("estimated_duration_minutes", 2000))
        schema_case("Required field 'modules' missing", lambda d: d.pop("modules"))
        b["schema_cases"] = cases
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(b, open(OUT, "w", encoding="utf-8"), indent=1, default=str)
    return b


if __name__ == "__main__":
    b = capture("--live" in sys.argv)
    print("plans", len(b["plans"]), "rows", sum(len(p.get("rows", [])) for p in b["plans"]))
