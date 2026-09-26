import json
import math
import os
import secrets
import re
import time
from datetime import datetime
import yaml
from concurrent.futures import ThreadPoolExecutor
from flask import current_app
from pydantic import ValidationError
from config.loader import load_yaml
from src.audit import now, log_audit
from schemas.plan_schema import OnboardingPlan, Module
from schemas.examples import plan_example, module_example
from genai_pipeline.client import get_client, GenAIError
from role_matrix import extractor as ex
from role_matrix.builder import role_names

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompt_templates")
COMPANY = "Sitara Bank Ltd."


class GenerationFailed(Exception):
    pass


def load_template(name):
    with open(os.path.join(TEMPLATE_DIR, f"{name}.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def stage_names():
    return ", ".join(s["name"] for s in load_yaml("stages.yaml")["stages"])


# ---------------- retrieval ----------------
def retrieve_sources(db, role, doc_ids=None):
    """Active, trusted, non-quarantined clauses that apply to the role (plus informational context)."""
    untrusted = load_yaml("precedence_rules.yaml")["untrusted_categories"]
    names = role_names(db)
    q = {"status": "Active", "trust": {"$ne": "Untrusted"}, "category": {"$nin": untrusted}}
    if doc_ids:
        q["document_id"] = {"$in": list(doc_ids)}
    docs = list(db.documents.find(q).sort("precedence_level", 1))
    selected = []
    for d in docs:
        rows = []
        for c in db.chunks.find({"document_id": d["document_id"], "version": d["version"]}):
            if c.get("quarantined"):
                continue
            roles, _, _ = ex.resolve_roles(c.get("applies_to_raw", ""), c["text"], names)
            if role in roles:
                rows.append(c)
        if rows:
            selected.append((d, rows))
    return selected


def format_sources(selected):
    parts = []
    for d, rows in selected:
        body = "\n".join(f"[{d['document_id']} §{c['section_id']}] ({c.get('section_heading', '')}) "
                         f"{ex.clean_text(c['text'])}" for c in rows)
        parts.append(f'<source_document id="{d["document_id"]}" version="{d["version"]}" '
                     f'title="{d["title"]}" category="{d["category"]}" effective_date="{d["effective_date"]}">\n'
                     f"{body}\n</source_document>")
    return "\n\n".join(parts)


# ---------------- API call with retry ----------------
def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Response does not contain a JSON object.")
    return json.loads(text[start:end + 1])


def call_with_retry(db, system, prompt, model_cls, purpose, request_id):
    cfg = current_app.config
    max_retries = max(1, cfg["GENAI_MAX_RETRIES"])
    try:
        client = get_client()
    except GenAIError as e:                               # missing key / unknown provider
        db.generation_logs.insert_one({"request_id": request_id, "purpose": purpose, "attempt": 1, "ok": False,
                                       "error": str(e), "at": now()})
        raise GenerationFailed(str(e))
    feedback, last_error = "", None
    for attempt in range(1, max_retries + 1):
        started = time.time()
        log = {"request_id": request_id, "purpose": purpose, "attempt": attempt, "model": getattr(client, "model", "?"),
               "prompt_chars": len(prompt) + len(feedback), "at": now()}
        try:
            raw = client.generate(system, prompt + feedback, cfg["GENAI_TEMPERATURE"])
            data = _extract_json(raw)
            if model_cls is None:
                obj = data
            elif isinstance(model_cls, type):
                obj = model_cls.model_validate(data)
            else:
                obj = model_cls(data)                    # custom validation function
            log.update(ok=True, seconds=round(time.time() - started, 2), response_chars=len(raw))
            db.generation_logs.insert_one(log)
            return obj, attempt
        except (GenAIError, ValueError, ValidationError, json.JSONDecodeError) as e:
            last_error = f"{e.__class__.__name__}: {str(e)[:1200]}"
            log.update(ok=False, seconds=round(time.time() - started, 2), error=last_error)
            db.generation_logs.insert_one(log)
            if isinstance(e, GenAIError) and "not configured" in str(e):
                break                                   # retrying cannot fix a missing key
            feedback = ("\n\nYOUR PREVIOUS ANSWER WAS REJECTED BY THE VALIDATOR:\n" + last_error +
                        "\nReturn a corrected JSON object only.")
            if not cfg.get("TESTING"):
                time.sleep(min(2 ** attempt, 8))
    raise GenerationFailed(f"Generation failed after {attempt} attempt(s). Last error: {last_error}")


# ---------------- plan generation (in batches) ----------------
# A role can have 80+ mandatory requirements. One huge request makes the model stop early
# (low coverage). So the approved sources are split into small batches, each batch is sent
# as a separate request, and the returned modules are merged into one plan.

def _setting(name, default):
    """Reads a number from the app config or .env (0 is a valid value)."""
    value = current_app.config.get(name)
    if value is None:
        value = os.getenv(name, default)
    return int(value)


def _conflict_groups(db, doc_ids):
    """Documents that conflict with each other are kept in the same batch, so the model can
    apply the precedence rules itself (e.g. FAQ-02 and POL-04 are always sent together)."""
    parent = {d: d for d in doc_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for c in db.conflicts.find({"kind": "conflict"}):
        a, b = c["a"]["document_id"], c["b"]["document_id"]
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups = {}
    for d in doc_ids:
        groups.setdefault(find(d), []).append(d)
    return list(groups.values())


def make_batches(db, selected, max_clauses):
    """Packs (document, clauses) pairs into batches of at most max_clauses clauses."""
    by_id = {d["document_id"]: (d, rows) for d, rows in selected}
    groups = _conflict_groups(db, list(by_id))
    groups.sort(key=lambda g: min(by_id[d][0]["precedence_level"] for d in g))
    batches, current, size = [], [], 0
    for g in groups:
        g_size = sum(len(by_id[d][1]) for d in g)
        if current and size + g_size > max_clauses:
            batches.append(current)
            current, size = [], 0
        current.extend(by_id[d] for d in g)
        size += g_size
    if current:
        batches.append(current)
    return batches


def _batch_prompt(tpl, employee, batch, number, total):
    clauses = sum(len(rows) for _, rows in batch)
    values = {"company": COMPANY, "employee_id": employee["employee_id"], "role": employee["role"],
              "department": employee.get("department", ""), "experience_level": employee.get("experience_level", "Beginner"),
              "joining_date": employee.get("joining_date", ""), "previous_experience": employee.get("previous_experience", "None"),
              "stages": stage_names(), "min_modules": 1, "max_modules": max(2, math.ceil(clauses / 6)),
              "schema_example": plan_example(), "sources": format_sources(batch)}
    note = (f"\n\nBATCH {number} OF {total}: the other documents are handled in separate requests. "
            f"Cover EVERY mandatory requirement in the sources above - do not skip any, even if the plan becomes long. "
            f"Use only these sources.")
    return tpl["system"].format(**values), tpl["user"].format(**values) + note


def _renumber(batch_modules, start):
    """Gives every module a unique id (M01, M02 ...) and fixes task, question and prerequisite ids."""
    mapping = {}
    for i, m in enumerate(batch_modules):
        mapping[m["module_id"]] = f"M{start + i:02d}"
    for m in batch_modules:
        new_id = mapping[m["module_id"]]
        m["module_id"] = new_id
        m["prerequisites"] = [mapping[p] for p in m.get("prerequisites", []) if p in mapping]
        for k, t in enumerate(m.get("tasks", []), start=1):
            t["task_id"] = f"{new_id}-T{k}"
        for k, q in enumerate(m.get("quiz", []), start=1):
            q["question_id"] = f"{new_id}-Q{k}"
    return batch_modules


OBLIGATION_RX = re.compile(r"\b(must|shall|required|mandatory)\b", re.I)


def _cited(modules):
    return {(rc["source_document_id"].strip(), rc["source_section_id"].strip().lstrip("§ "))
            for m in modules for rc in m.get("requirements_covered", [])}


def _uncovered(selected, modules):
    """Pipeline 1 self-check: clauses the model was asked to cover (they contain must/shall/required)
    but did not cite. This only re-reads the prompt sources; Pipeline 2 still validates independently."""
    cited = _cited(modules)
    out = []
    for d, rows in selected:
        missing = [c for c in rows if OBLIGATION_RX.search(ex.clean_text(c["text"]))
                   and (d["document_id"], c["section_id"]) not in cited]
        if missing:
            out.append((d, missing))
    return out


def _add_conflict_context(db, uncovered, selected):
    """If an uncovered clause conflicts with another source, the other clause is added to the same request,
    so the model can still decide with the precedence rules instead of blindly covering the weaker rule."""
    lookup = {(d["document_id"], c["section_id"]): (d, c) for d, rows in selected for c in rows}
    extra = {}
    keys = {(d["document_id"], c["section_id"]) for d, rows in uncovered for c in rows}
    for cf in db.conflicts.find({"kind": "conflict"}):
        a = (cf["a"]["document_id"], cf["a"]["section_id"])
        b = (cf["b"]["document_id"], cf["b"]["section_id"])
        for mine, other in ((a, b), (b, a)):
            if mine in keys and other in lookup and other not in keys:
                extra.setdefault(other[0], []).append(lookup[other])
    merged = {d["document_id"]: (d, list(rows)) for d, rows in uncovered}
    for doc_id, pairs in extra.items():
        d = pairs[0][0]
        rows = merged.setdefault(doc_id, (d, []))[1]
        for _, c in pairs:
            if c not in rows:
                rows.append(c)
    return list(merged.values())


def generate_plan_json(db, employee, request_id):
    tpl = load_template("onboarding_plan")
    selected = retrieve_sources(db, employee["role"])
    if not selected:
        raise GenerationFailed(f"No approved source documents apply to the role '{employee['role']}'.")
    batches = make_batches(db, selected, _setting("GENAI_BATCH_CLAUSES", 15))
    total = len(batches)
    app = current_app._get_current_object()
    workers = max(1, _setting("GENAI_PARALLEL", 3))

    def run_batches(batch_list, label, note_extra=""):
        n = len(batch_list)

        def run(index_batch):
            index, batch = index_batch
            with app.app_context():                 # each thread needs its own Flask context
                system, prompt = _batch_prompt(tpl, employee, batch, index, n)
                try:
                    plan, attempts = call_with_retry(db, system, prompt + note_extra, OnboardingPlan,
                                                     f"{label} {index}/{n}", request_id)
                    return index, plan.model_dump(), attempts, None
                except GenerationFailed as e:
                    return index, None, 0, str(e)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return sorted(pool.map(run, enumerate(batch_list, start=1)), key=lambda r: r[0])

    modules, summaries, missing_info = [], [], []
    attempts_total, failed_total, calls = 0, 0, 0

    def merge(results, batch_list):
        nonlocal attempts_total, failed_total, calls
        for index, part, attempts, err in results:
            calls += 1
            attempts_total += attempts
            if err:
                failed_total += 1
                docs = ", ".join(d["document_id"] for d, _ in batch_list[index - 1])
                missing_info.append(f"Batch ({docs}) could not be generated: {err[:200]}")
                continue
            modules.extend(_renumber(part["modules"], len(modules) + 1))
            summaries.append(part.get("summary", ""))
            missing_info.extend(part.get("insufficient_information", []))

    # pass 1: every approved source, in batches
    merge(run_batches(batches, "onboarding_plan batch"), batches)
    if not modules:
        raise GenerationFailed(f"All {total} batches failed. See Logs & audit for the API error.")

    # gap-fill rounds: send only the obligation clauses that were not covered yet
    rounds_done = 0
    gap_note = ("\n\nGAP-FILL REQUEST: the clauses above were NOT covered by the modules generated so far. "
                "Create new modules that cover EACH mandatory clause above in requirements_covered. "
                "If a clause is overruled by a higher-authority source shown above, do not cover it and write "
                "its id in insufficient_information instead.")
    for _ in range(_setting("GENAI_COVERAGE_ROUNDS", 2)):
        gaps = _uncovered(selected, modules)
        if not gaps:
            break
        gap_batches = make_batches(db, _add_conflict_context(db, gaps, selected), _setting("GENAI_BATCH_CLAUSES", 15))
        merge(run_batches(gap_batches, "gap_fill batch", gap_note), gap_batches)
        rounds_done += 1

    plan = OnboardingPlan.model_validate({
        "role": employee["role"], "employee_id": employee["employee_id"],
        "summary": " ".join(s for s in summaries if s)[:2000] or "Onboarding plan generated from approved sources.",
        "modules": modules, "insufficient_information": missing_info})
    meta = {"model": getattr(get_client(), "model", "?"), "provider": current_app.config.get("GENAI_PROVIDER"),
            "prompt_template": tpl["name"], "prompt_version": tpl["version"],
            "temperature": current_app.config["GENAI_TEMPERATURE"], "generated_at": now(),
            "attempts": attempts_total, "batches": calls, "failed_batches": failed_total,
            "gap_fill_rounds": rounds_done,
            "source_versions": {d["document_id"]: d["version"] for d, _ in selected},
            "source_clause_count": sum(len(r) for _, r in selected)}
    return plan.model_dump(), meta


def create_plan(db, employee, user):
    plan_id = f"PLN-{employee['employee_id']}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"
    plan_json, meta = generate_plan_json(db, employee, plan_id)
    doc = {"plan_id": plan_id, "employee_id": employee["employee_id"], "role": employee["role"],
           "department": employee.get("department"), "experience_level": employee.get("experience_level"),
           "status": "Generated", "plan_json": plan_json, "original_plan_json": plan_json,
           "generation": meta, "created_by": user, "created_at": now(), "comments": [], "overrides": []}
    db.plans.insert_one(doc)
    log_audit("generate_plan", "plan", plan_id, after={"modules": len(plan_json["modules"])}, user=user)
    return doc


def regenerate_modules(db, plan, module_ids, reason, user):
    """Step 59 - selective regeneration: only the listed modules are rewritten."""
    tpl = load_template("module_regeneration")
    modules = plan["plan_json"]["modules"]
    changed = []
    for m in modules:
        if m["module_id"] not in module_ids:
            continue
        doc_ids = {rc["source_document_id"] for rc in m.get("requirements_covered", [])}
        selected = retrieve_sources(db, plan["role"], doc_ids) or retrieve_sources(db, plan["role"])
        values = {"company": COMPANY, "role": plan["role"], "experience_level": plan.get("experience_level", "Beginner"),
                  "stages": stage_names(), "reason": reason, "module_id": m["module_id"],
                  "current_module": json.dumps(m, indent=1), "sources": format_sources(selected)}
        new, _ = call_with_retry(db, tpl["system"].format(**values), tpl["user"].format(**values),
                                 Module, "module_regeneration", plan["plan_id"])
        new = new.model_dump()
        new["module_id"] = m["module_id"]
        changed.append({"module_id": m["module_id"], "before": m, "after": new})
        m.clear(); m.update(new)
    gen = plan.get("generation", {})
    gen.setdefault("regenerations", []).append({"at": now(), "modules": module_ids, "reason": reason,
                                                "prompt_version": tpl["version"]})
    gen["source_versions"] = {d["document_id"]: d["version"] for d in db.documents.find({"status": "Active"})}
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"plan_json": plan["plan_json"], "generation": gen},
                                               "$unset": {"outdated": ""}})
    log_audit("regenerate_modules", "plan", plan["plan_id"], before=[c["before"]["module_title"] for c in changed],
              after=[c["after"]["module_title"] for c in changed], comment=reason, user=user)
    return changed


def topic_module(db, topic, role=None):
    """Hallucination challenge: only generate if the approved sources really cover the topic."""
    from src.text_utils import cosine
    threshold = load_yaml("validation_rules.yaml")["topic_min_similarity"]
    untrusted = load_yaml("precedence_rules.yaml")["untrusted_categories"]
    active = {d["document_id"]: d for d in db.documents.find({"status": "Active", "trust": {"$ne": "Untrusted"},
                                                              "category": {"$nin": untrusted}})}
    scored = []
    for c in db.chunks.find({"status": "Active", "quarantined": False}):
        if c["document_id"] in active:
            s = cosine(topic, c["text"])
            if s > 0:
                scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0] if scored else 0.0
    if best < threshold:
        return {"refused": True, "best_similarity": round(best, 2),
                "reason": "The approved company documents do not contain enough information about this topic. "
                          "Nothing was generated; the request was routed to manual review."}
    top = [c for s, c in scored[:12] if s >= threshold]
    grouped = {}
    for c in top:
        grouped.setdefault(c["document_id"], []).append(c)
    selected = [(active[k], v) for k, v in grouped.items()]
    tpl = load_template("topic_module")
    values = {"company": COMPANY, "topic": topic, "stages": stage_names(), "schema_example": module_example(),
              "sources": format_sources(selected)}
    def check(data):
        if data.get("insufficient_information") is True:
            return data
        return Module.model_validate(data).model_dump()

    data, _ = call_with_retry(db, tpl["system"].format(**values), tpl["user"].format(**values), check,
                              "topic_module", f"TOPIC-{datetime.now():%Y%m%d%H%M%S}")
    if data.get("insufficient_information") is True:
        return {"refused": True, "best_similarity": round(best, 2), "reason": data.get("reason", "Model reported insufficient information.")}
    module = data
    return {"refused": False, "best_similarity": round(best, 2), "module": module,
            "sources": [f"{c['document_id']} §{c['section_id']}" for c in top]}