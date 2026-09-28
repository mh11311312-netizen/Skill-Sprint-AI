"""Pipeline 1 - GenAI generation.
Selects the approved source clauses for the role, fills a versioned prompt template, calls the API,
checks the JSON with Pydantic, retries a limited number of times, and logs every attempt."""
import json
import math
import os
import secrets
import re
import threading
import time
from datetime import datetime
import yaml
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from flask import current_app
from pydantic import ValidationError
from config.loader import load_yaml
from src.audit import now, log_audit
from schemas.plan_schema import OnboardingPlan, Module
from schemas.examples import plan_example, module_example
from genai_pipeline.client import get_client, GenAIError
from role_matrix import extractor as ex
from role_matrix.builder import role_names
from contradiction_checks.source_conflicts import parse_skip_claims, skip_claim_problem

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
    """Active, trusted, non-quarantined clauses that apply to the role (plus informational context).
    Uses two database queries in total (documents, then all their chunks) to keep remote databases fast."""
    untrusted = load_yaml("precedence_rules.yaml")["untrusted_categories"]
    names = role_names(db)
    q = {"status": "Active", "trust": {"$ne": "Untrusted"}, "category": {"$nin": untrusted}}
    if doc_ids:
        q["document_id"] = {"$in": list(doc_ids)}
    docs = list(db.documents.find(q).sort("precedence_level", 1))
    if not docs:
        return []
    by_doc = {}
    for c in db.chunks.find({"$or": [{"document_id": d["document_id"], "version": d["version"]} for d in docs],
                             "quarantined": {"$ne": True}}):
        by_doc.setdefault(c["document_id"], []).append(c)
    selected = []
    for d in docs:
        rows = []
        for c in by_doc.get(d["document_id"], []):
            roles, _, _ = ex.resolve_roles(c.get("applies_to_raw", ""), c["text"], names)
            if role in roles:
                rows.append(c)
        if rows:
            selected.append((d, rows))
    return selected


def format_sources(selected):
    parts = []
    for d, rows in selected:
        body = "\n".join(("[REFERENCE ONLY - covered in another request; use it only to apply precedence] "
                           if c.get("_reference") else "") +
                          f"[{d['document_id']} §{c['section_id']}] ({c.get('section_heading', '')}) "
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


def call_with_retry(db, system, prompt, model_cls, purpose, request_id, deadline=None):
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
        if attempt > 1 and deadline and time.time() > deadline - 3:
            last_error = last_error or "time budget reached"
            break                                       # no time left for another try
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
            pause = min(2 ** attempt, 8)
            if not cfg.get("TESTING") and not (deadline and time.time() + pause > deadline - 3):
                time.sleep(pause)
    raise GenerationFailed(f"Generation failed after {attempt} attempt(s). Last error: {last_error}")


# ---------------- plan generation (in batches) ----------------
# A role can have 80+ mandatory requirements. One huge request makes the model stop early
# (low coverage). So the approved sources are split into small batches, each batch is sent
# as a separate request, and the returned modules are merged into one plan.

OBLIGATION_RX = re.compile(r"\b(must|shall|required|mandatory)\b", re.I)
RULE_RX = re.compile(r"\b(must|shall|required|mandatory|should|may)\b")


def _is_requirement(text):
    """Clauses the plan must cover. GENAI_COVER_ALL=1 (default): every requirement - mandatory, recommended and
    optional; purely informational sentences are never required. GENAI_COVER_ALL=0: mandatory clauses only."""
    t = ex.clean_text(text)
    if _setting("GENAI_COVER_ALL", 1):
        return ex.obligation(t) != "Informational"
    return bool(OBLIGATION_RX.search(t))


def _compact():
    return bool(_setting("GENAI_COMPACT_OUTPUT", 1))


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


def make_batches(db, selected, max_clauses, pool=None):
    """Splits the clauses into small requests of at most max_clauses clauses so every request is short and
    they can all run at the same time. If a clause conflicts with a clause that sits in another request,
    that other clause is attached as REFERENCE ONLY, so the model can still apply the precedence rules."""
    pool = pool or selected
    lookup = {(d["document_id"], c["section_id"]): (d, c) for d, rows in pool for c in rows}
    partners = {}
    for cf in db.conflicts.find({"kind": "conflict"}, {"a.document_id": 1, "a.section_id": 1, "b.document_id": 1, "b.section_id": 1}):
        a = (cf["a"]["document_id"], cf["a"]["section_id"])
        b = (cf["b"]["document_id"], cf["b"]["section_id"])
        partners.setdefault(a, set()).add(b)
        partners.setdefault(b, set()).add(a)
    items = [(d, c) for d, rows in selected for c in rows]
    batches = []
    for start in range(0, len(items), max(1, max_clauses)):
        chunk = items[start:start + max_clauses]
        keys = {(d["document_id"], c["section_id"]) for d, c in chunk}
        grouped = {}
        for d, c in chunk:
            grouped.setdefault(d["document_id"], (d, []))[1].append(c)
        for d, c in chunk:
            for other in partners.get((d["document_id"], c["section_id"]), ()):
                if other in lookup and other not in keys:
                    od, oc = lookup[other]
                    keys.add(other)
                    grouped.setdefault(od["document_id"], (od, []))[1].append(dict(oc, _reference=True))
        batch = list(grouped.values())
        # a request with no must/should/may clause would only produce filler - skip it (faster and cheaper)
        if any(RULE_RX.search(ex.clean_text(c["text"])) for _, rows in batch for c in rows if not c.get("_reference")):
            batches.append(batch)
    return batches


def _batch_prompt(tpl, employee, batch, number, total):
    clauses = sum(1 for _, rows in batch for c in rows if not c.get("_reference"))
    values = {"company": COMPANY, "employee_id": employee["employee_id"], "role": employee["role"],
              "department": employee.get("department", ""), "experience_level": employee.get("experience_level", "Beginner"),
              "joining_date": employee.get("joining_date", ""), "previous_experience": employee.get("previous_experience", "None"),
              "stages": stage_names(), "min_modules": 1,
              "max_modules": (max(1, sum(1 for _, rows in batch if any(not c.get("_reference") for c in rows))) if _compact()
                              else max(2, math.ceil(clauses / 6))),
              "schema_example": plan_example(), "sources": format_sources(batch)}
    # checklist of the clauses in THIS request that contain must/shall/required (read from the prompt sources
    # themselves, not from the Python matrix) - small models cover far more when given an explicit list
    must_ids = [f"{d['document_id']}-{c['section_id']}" for d, rows in batch for c in rows
                if not c.get("_reference") and _is_requirement(c["text"])]
    note = (f"\n\nBATCH {number} OF {total}: the other documents are handled in separate requests. Use only these sources.")
    if _compact():
        # the answer's length decides how long the model takes, so plans are written in a compact form
        note += ("\nCOMPACT OUTPUT (speed): write ONE module per source document in this batch. In each: exactly 1 learning objective, 1 checklist "
                 "item, 1 practical task and 2 quiz questions; key_concepts and learning_activities as empty lists; purpose, "
                 "descriptions, questions and explanations in at most 15 words each. requirements_covered must still list "
                 "EVERY clause on the coverage checklist - coverage matters more than anything else.")
    if must_ids:
        note += ("\nCOVERAGE CHECKLIST - requirements_covered across your modules must contain EACH of these ids, mandatory AND optional "
                 f"({len(must_ids)} in total): " + ", ".join(must_ids) +
                 "\nThe ONLY allowed reason to leave an id out: another clause shown above says the opposite about the same "
                 "thing (for example a different number of days) AND comes from a higher-authority document. In that case "
                 "put '<id>: overruled by <other id>' in insufficient_information. General, informational, obvious or "
                 "already-known clauses are NOT a reason to skip - cover them. Never list an id without that explanation."
                 "\nBefore answering, check every id on this list is present.")
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


def _cited(modules):
    return {(rc["source_document_id"].strip(), rc["source_section_id"].strip().lstrip("§ "))
            for m in modules for rc in m.get("requirements_covered", [])}


def _uncovered(selected, modules):
    """Pipeline 1 self-check: clauses the model was asked to cover (they contain must/shall/required)
    but did not cite. This only re-reads the prompt sources; Pipeline 2 still validates independently."""
    cited = _cited(modules)
    out = []
    for d, rows in selected:
        missing = [c for c in rows if _is_requirement(c["text"])
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


# Requests still running when the time budget ends are not thrown away: they keep running and their modules
# are merged into the saved plan when they finish, after which Python validates the plan again.
_PENDING = {}                     # request_id -> list of (future, batch_note, docs)
_MERGE_LOCK = threading.Lock()


def generate_plan_json(db, employee, request_id, budget=None, finish_in_background=True):
    started = time.time()
    tpl = load_template("onboarding_plan")
    selected = retrieve_sources(db, employee["role"])
    if not selected:
        raise GenerationFailed(f"No approved source documents apply to the role '{employee['role']}'.")
    batches = make_batches(db, selected, _setting("GENAI_BATCH_CLAUSES", 6))
    total = len(batches)
    app = current_app._get_current_object()
    workers = max(1, _setting("GENAI_PARALLEL", 32))   # all requests in one wave
    if budget is None:
        budget = _setting("GENAI_TIME_BUDGET", 30)      # seconds for the whole plan (0 = no limit)
    deadline = started + budget - 3 if budget else None  # 3 s kept for Python validation
    background = bool(deadline) and finish_in_background and bool(_setting("GENAI_FINISH_IN_BACKGROUND", 1))
    retry_deadline = None if background else deadline    # background parts may still retry after the budget

    def run_batches(batch_list, label, note_extra=""):
        n = len(batch_list)

        def run(index_batch):
            index, batch = index_batch
            with app.app_context():                 # each thread needs its own Flask context
                system, prompt = _batch_prompt(tpl, employee, batch, index, n)
                try:
                    plan, attempts = call_with_retry(db, system, prompt + note_extra, OnboardingPlan,
                                                     f"{label} {index}/{n}", request_id, retry_deadline)
                    return index, plan.model_dump(), attempts, None
                except GenerationFailed as e:
                    return index, None, 0, str(e)

        pool = ThreadPoolExecutor(max_workers=max(1, min(workers, n)))
        futures = {pool.submit(run, item): item[0] for item in enumerate(batch_list, start=1)}
        # wait at most until the deadline; requests still running after that are left out of the plan
        done, late = wait(futures, timeout=None if deadline is None else max(0.0, deadline - time.time()))
        pool.shutdown(wait=False, cancel_futures=not background)
        results = [f.result() for f in done]
        for f in late:
            docs = ", ".join(d["document_id"] for d, _ in batch_list[futures[f] - 1])
            if background:
                note = f"Batch ({docs}) is still being generated after the {budget} s time budget; it is added automatically when it finishes."
                _PENDING.setdefault(request_id, []).append((f, note))
                results.append((futures[f], None, 0, "__late__:" + note))
            else:
                results.append((futures[f], None, 0, "did not finish within the time budget"))
        return sorted(results, key=lambda r: r[0])

    modules, summaries, missing_info = [], [], []
    attempts_total, failed_total, calls = 0, 0, 0

    def merge(results, batch_list):
        nonlocal attempts_total, failed_total, calls
        for index, part, attempts, err in results:
            calls += 1
            attempts_total += attempts
            if err and err.startswith("__late__:"):
                missing_info.append(err[len("__late__:"):])     # removed again when the background part is merged
                continue
            if err:
                failed_total += 1
                docs = ", ".join(d["document_id"] for d, _ in batch_list[index - 1])
                missing_info.append(f"Batch ({docs}) could not be generated: {err[:200]}")
                continue
            modules.extend(_renumber(part["modules"], len(modules) + 1))
            summaries.append(part.get("summary", ""))
            missing_info.extend(part.get("insufficient_information", []))

    # pass 1: every approved source, in batches. Answers are merged as they arrive; the plan is returned as
    # soon as every mandatory clause is covered. Requests that are slow ("stragglers") are hedged: after
    # GENAI_HEDGE_AFTER seconds the clauses still missing are sent again as very small requests, and whichever
    # answer arrives first is used.
    category_of = {d["document_id"]: d["category"] for d, _ in selected}

    def still_needed():
        skipped = {a for a, b in parse_skip_claims(missing_info) if not skip_claim_problem(a, b, category_of)}
        out = []
        for d, rows in _uncovered(selected, modules):
            keep = [c for c in rows if f"{d['document_id']}-{c['section_id']}" not in skipped]
            if keep:
                out.append((d, keep))
        return out

    def make_run(batch_list, label, note_extra=""):
        n = len(batch_list)

        def run(index):
            with app.app_context():                 # each thread needs its own Flask context
                system, prompt = _batch_prompt(tpl, employee, batch_list[index - 1], index, n)
                try:
                    part, attempts = call_with_retry(db, system, prompt + note_extra, OnboardingPlan,
                                                     f"{label} {index}/{n}", request_id, retry_deadline)
                    return index, part.model_dump(), attempts, None
                except GenerationFailed as e:
                    return index, None, 0, str(e)
        return run

    hedge_note = ("\n\nMISSING-CLAUSES REQUEST (speed): the clauses above are still missing from the plan. Write ONE short "
                  "module that lists EACH clause above (mandatory, recommended or optional) in requirements_covered, with "
                  "mandatory=true only for must/shall/required clauses, unless a higher-authority clause shown above overrules "
                  "it (then write '<id>: overruled by <other id>' in insufficient_information).")
    hedge_after = float(current_app.config.get("GENAI_HEDGE_AFTER", os.getenv("GENAI_HEDGE_AFTER", budget * 0.3 if budget else 0)) or 0)
    # two hedge rounds: the second one re-sends whatever is still missing, in even smaller pieces
    hedge_times = [started + hedge_after, started + hedge_after + (budget - 3 - hedge_after) * 0.5] if (hedge_after and budget) else []
    sent_ids = set()
    pool = ThreadPoolExecutor(max_workers=max(1, workers) * 2)
    run_main = make_run(batches, "onboarding_plan batch")
    outstanding = {pool.submit(run_main, i): ("main", i, batches) for i in range(1, total + 1)}
    covered_early, wait_until = False, deadline
    while outstanding:
        stops = [t for t in (wait_until, hedge_times[0] if hedge_times else None) if t]
        timeout = max(0.0, min(stops) - time.time()) if stops else None
        done, _ = wait(list(outstanding), timeout=timeout, return_when=FIRST_COMPLETED)
        for f in done:
            _, index, blist = outstanding.pop(f)
            merge([f.result()], blist)
        if modules and not still_needed():
            covered_early = True                     # every mandatory clause is in: no need to wait for the rest
            break
        if hedge_times and time.time() >= hedge_times[0]:
            second = len(hedge_times) == 1
            hedge_times.pop(0)
            gaps = still_needed()
            if second:                                  # round 2: only clauses not already re-sent in round 1
                gaps = [(d, [c for c in rows if f"{d['document_id']}-{c['section_id']}" not in sent_ids]) for d, rows in gaps]
                gaps = [(d, rows) for d, rows in gaps if rows]
            if gaps and outstanding:
                sent_ids.update(f"{d['document_id']}-{c['section_id']}" for d, rows in gaps for c in rows)
                hb = make_batches(db, gaps, 1 if second else _setting("GENAI_HEDGE_CLAUSES", 2), pool=selected)
                run_h = make_run(hb, "hedge batch", hedge_note)
                for i in range(1, len(hb) + 1):
                    outstanding[pool.submit(run_h, i)] = ("hedge", i, hb)
        if wait_until and time.time() >= wait_until:
            if modules:
                break
            wait_until = None                        # nothing arrived yet: wait for the first answer so the plan is never empty

    if covered_early:
        for f in outstanding:
            f.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        outstanding = {}
    else:
        pool.shutdown(wait=False, cancel_futures=not background)
    for f, (kind, index, blist) in outstanding.items():
        docs = ", ".join(d["document_id"] for d, _ in blist[index - 1])
        if background:
            note = f"Batch ({docs}) is still being generated after the {budget} s time budget; it is added automatically when it finishes."
            _PENDING.setdefault(request_id, []).append((f, note))
            missing_info.append(note)
        else:
            missing_info.append(f"Batch ({docs}) could not be generated: did not finish within the time budget")
    if not modules:
        _PENDING.pop(request_id, None)
        raise GenerationFailed(f"All {total} batches failed. See Logs & audit for the API error.")

    # gap-fill rounds: send only the obligation clauses that were not covered yet
    rounds_done = 0
    gap_note = ("\n\nGAP-FILL REQUEST: the clauses above were NOT covered by the modules generated so far. "
                "Create new modules that cover EACH mandatory clause above in requirements_covered. "
                "Skip a clause only if another clause shown above contradicts it and comes from a higher-authority "
                "document; then write '<id>: overruled by <other id>' in insufficient_information.")
    for _ in range(_setting("GENAI_COVERAGE_ROUNDS", 0)):
        gaps = _uncovered(selected, modules)
        if not gaps or (deadline and deadline - time.time() < 12):
            break                                   # no time left: the reviewer can use "Add missing requirements"
        # skips the model justified wrongly (same document, or a weaker document) are sent back with a correction
        bad = [f"{a} ({why})" for a, b in parse_skip_claims(missing_info)
               if (why := skip_claim_problem(a, b, category_of))]
        note = gap_note
        if bad:
            note += ("\nYOUR EARLIER SKIP REASONS WERE WRONG for these ids - they are NOT overruled and must be covered: "
                     + "; ".join(bad[:60]))
        gap_batches = make_batches(db, gaps, _setting("GENAI_BATCH_CLAUSES", 6), pool=selected)
        merge(run_batches(gap_batches, "gap_fill batch", note), gap_batches)
        rounds_done += 1

    plan = OnboardingPlan.model_validate({
        "role": employee["role"], "employee_id": employee["employee_id"],
        "summary": " ".join(s for s in summaries if s)[:2000] or "Onboarding plan generated from approved sources.",
        "modules": modules, "insufficient_information": missing_info})
    meta = {"model": getattr(get_client(), "model", "?"), "provider": current_app.config.get("GENAI_PROVIDER"),
            "prompt_template": tpl["name"], "prompt_version": tpl["version"],
            "temperature": current_app.config["GENAI_TEMPERATURE"], "generated_at": now(),
            "attempts": attempts_total, "batches": calls, "failed_batches": failed_total,
            "gap_fill_rounds": rounds_done, "seconds": round(time.time() - started, 1),
            "time_budget": budget, "late_requests": sum(1 for x in missing_info if "time budget" in x),
            "background_requests": len(_PENDING.get(request_id, [])),
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
    _finish_in_background(db, plan_id, time.time() - meta["seconds"])
    return doc


def _finish_in_background(db, plan_id, started):
    """Attach the requests that outlived the time budget: each one merges its modules into the saved plan when
    it finishes; when the last one is in, the plan is validated again by Python."""
    pending = _PENDING.pop(plan_id, [])
    if not pending:
        return
    app = current_app._get_current_object()
    state = {"left": len(pending)}
    # validate the first version now, before any late part can be merged, so a later merge is never overwritten
    from python_validation.validator import run_validation
    with _MERGE_LOCK:
        result = run_validation(db, db.plans.find_one({"plan_id": plan_id}), "system")
        all_in = result["scores"]["coverage"] >= 100 and (
            not _setting("GENAI_COVER_ALL", 1) or not result.get("status_counts", {}).get("Optional Not Included"))
        if all_in:
            # every requirement is already covered: the parts still running would only add repeated
            # modules, so the plan is complete now and they are discarded
            plan = db.plans.find_one({"plan_id": plan_id})
            pj, gen = plan["plan_json"], plan["generation"]
            notes = {n for _, n in pending}
            pj["insufficient_information"] = [x for x in pj.get("insufficient_information", []) if x not in notes]
            gen.update(late_requests=0, background_requests=0, discarded_late_requests=len(pending), background_done=True,
                       seconds_total=gen.get("seconds"))
            db.plans.update_one({"_id": plan["_id"]}, {"$set": {"plan_json": pj, "original_plan_json": pj, "generation": gen}})
            for f, _ in pending:
                f.cancel()
            return

    def merge_late(fut, note):
        try:
            index, part, attempts, err = fut.result()
        except Exception as e:                     # never let a background error break anything
            part, err = None, f"{e.__class__.__name__}: {e}"
        with _MERGE_LOCK, app.app_context():
            plan = db.plans.find_one({"plan_id": plan_id})
            if not plan:
                return
            pj, gen = plan["plan_json"], plan.get("generation", {})
            notes = [x for x in pj.get("insufficient_information", []) if x != note]
            if part:
                pj["modules"].extend(_renumber(part["modules"], len(pj["modules"]) + 1))
                notes.extend(part.get("insufficient_information", []))
                gen["completed_in_background"] = gen.get("completed_in_background", 0) + 1
            else:
                notes.append(note.split(" is still")[0] + f" could not be generated: {str(err)[:200]}")
                gen["failed_batches"] = gen.get("failed_batches", 0) + 1
            pj["insufficient_information"] = notes
            state["left"] -= 1
            gen["late_requests"] = state["left"]
            gen["seconds_total"] = round(time.time() - started, 1)
            upd = {"plan_json": pj, "generation": gen}
            if plan.get("status") in ("Generated", "Pending Review", "Verified"):
                upd["original_plan_json"] = pj
            db.plans.update_one({"_id": plan["_id"]}, {"$set": upd})
            if state["left"] == 0:
                from python_validation.validator import run_validation
                log_audit("plan_completed_in_background", "plan", plan_id, after={"modules": len(pj["modules"]),
                          "seconds_total": gen["seconds_total"]}, user="system")
                if plan.get("status") != "Approved":
                    run_validation(db, db.plans.find_one({"_id": plan["_id"]}), "system")
                db.plans.update_one({"_id": plan["_id"]}, {"$set": {"generation.background_done": True}})

    for fut, note in pending:
        fut.add_done_callback(lambda f, n=note: merge_late(f, n))


def add_missing_modules(db, plan, requirement_ids, user):
    """Reviewer action after validation: send only the clauses of the missing mandatory requirements
    to the model, append the new modules to the plan, and keep everything else unchanged."""
    started = time.time()
    tpl = load_template("onboarding_plan")
    wanted = {}
    for rid in requirement_ids:
        r = db.requirements.find_one({"requirement_id": rid})
        if r:
            wanted.setdefault(r["document_id"], set()).add(r["section_id"])
    selected = []
    for d, rows in retrieve_sources(db, plan["role"], list(wanted)):
        keep = [c for c in rows if c["section_id"] in wanted.get(d["document_id"], set())]
        if keep:
            selected.append((d, keep))
    if not selected:
        raise GenerationFailed("The missing requirements have no approved source clauses for this role.")
    employee = db.employees.find_one({"employee_id": plan["employee_id"]}) or {
        "employee_id": plan["employee_id"], "role": plan["role"], "experience_level": plan.get("experience_level", "Beginner")}
    batches = make_batches(db, selected, _setting("GENAI_BATCH_CLAUSES", 6), pool=retrieve_sources(db, plan["role"]))
    note = ("\n\nMISSING-REQUIREMENTS REQUEST: a reviewer found that the plan does not yet cover the mandatory clauses above. "
            "Create modules that cover EACH of them in requirements_covered. Follow the precedence rules if a clause is overruled.")
    app = current_app._get_current_object()

    def run(index_batch):
        index, batch = index_batch
        with app.app_context():
            system, prompt = _batch_prompt(tpl, employee, batch, index, len(batches))
            try:
                part, _ = call_with_retry(db, system, prompt + note, OnboardingPlan,
                                          f"missing_requirements {index}/{len(batches)}", plan["plan_id"])
                return part.model_dump()["modules"]
            except GenerationFailed:
                return []

    with ThreadPoolExecutor(max_workers=max(1, min(_setting("GENAI_PARALLEL", 32), len(batches)))) as pool:
        new_modules = [m for mods in pool.map(run, enumerate(batches, start=1)) for m in mods]
    if not new_modules:
        raise GenerationFailed("The model did not return any module for the missing requirements. See Logs & audit.")
    modules = plan["plan_json"]["modules"]
    modules.extend(_renumber(new_modules, len(modules) + 1))
    gen = plan.get("generation", {})
    gen.setdefault("regenerations", []).append({"at": now(), "modules": [m["module_id"] for m in new_modules],
                                                "reason": f"Added modules for {len(requirement_ids)} missing requirements",
                                                "prompt_version": tpl["version"], "seconds": round(time.time() - started, 1)})
    db.plans.update_one({"_id": plan["_id"]}, {"$set": {"plan_json": plan["plan_json"], "generation": gen}})
    log_audit("add_missing_modules", "plan", plan["plan_id"], after=[m["module_title"] for m in new_modules],
              comment=", ".join(requirement_ids[:20]), user=user)
    return new_modules


def regenerate_modules(db, plan, module_ids, reason, user):
    """Step 59 - selective regeneration: only the listed modules are rewritten.
    Runs one request per module IN PARALLEL, with a short time budget (viva-friendly: a
    reviewer should not wait 30-40s for 3-4 modules run one after another)."""
    tpl = load_template("module_regeneration")
    modules = plan["plan_json"]["modules"]
    targets = [m for m in modules if m["module_id"] in module_ids]
    budget = _setting("GENAI_REGEN_TIME_BUDGET", 10)   # seconds for the WHOLE selection, not per module
    deadline = time.time() + budget if budget else None
    app = current_app._get_current_object()

    def run(m):
        with app.app_context():
            doc_ids = {rc["source_document_id"] for rc in m.get("requirements_covered", [])}
            selected = retrieve_sources(db, plan["role"], doc_ids) or retrieve_sources(db, plan["role"])
            values = {"company": COMPANY, "role": plan["role"], "experience_level": plan.get("experience_level", "Beginner"),
                      "stages": stage_names(), "reason": reason, "module_id": m["module_id"],
                      "current_module": json.dumps(m, indent=1), "sources": format_sources(selected)}
            try:
                new, _ = call_with_retry(db, tpl["system"].format(**values), tpl["user"].format(**values),
                                         Module, "module_regeneration", plan["plan_id"], deadline)
                new = new.model_dump(); new["module_id"] = m["module_id"]
                return m["module_id"], new, None
            except GenerationFailed as e:
                return m["module_id"], None, str(e)

    pool = ThreadPoolExecutor(max_workers=max(1, min(len(targets), 8)))
    futures = {pool.submit(run, m): m for m in targets}
    done, late = wait(futures, timeout=None if deadline is None else max(0.0, deadline - time.time()))
    pool.shutdown(wait=False, cancel_futures=True)
    results = {}
    for f in done:
        mid, new, err = f.result()
        results[mid] = (new, err)
    for f in late:
        results[futures[f]["module_id"]] = (None, "did not finish within the time budget")

    changed, failed = [], []
    by_id = {m["module_id"]: m for m in modules}
    for mid, (new, err) in results.items():
        if new is None:
            failed.append((mid, err))
            continue
        m = by_id[mid]
        changed.append({"module_id": mid, "before": dict(m), "after": new})
        m.clear(); m.update(new)
    if changed:
        gen = plan.get("generation", {})
        gen.setdefault("regenerations", []).append({"at": now(), "modules": [c["module_id"] for c in changed],
                                                    "reason": reason, "prompt_version": tpl["version"],
                                                    "failed": failed or None})
        gen["source_versions"] = {d["document_id"]: d["version"] for d in db.documents.find({"status": "Active"})}
        db.plans.update_one({"_id": plan["_id"]}, {"$set": {"plan_json": plan["plan_json"], "generation": gen},
                                                   "$unset": {"outdated": ""}})
        log_audit("regenerate_modules", "plan", plan["plan_id"], before=[c["before"]["module_title"] for c in changed],
                  after=[c["after"]["module_title"] for c in changed], comment=reason, user=user)
    if failed and not changed:
        raise GenerationFailed("None of the selected modules could be regenerated in time: "
                               + "; ".join(f"{mid} ({err})" for mid, err in failed))
    return changed, failed


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
