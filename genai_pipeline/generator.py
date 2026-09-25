"""Pipeline 1 - GenAI generation.
Selects the approved source clauses for the role, fills a versioned prompt template, calls the API,
checks the JSON with Pydantic, retries a limited number of times, and logs every attempt."""
import json
import secrets
import os
import re
import time
from datetime import datetime
import yaml
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


# ---------------- plan generation ----------------
def build_plan_prompt(db, employee):
    tpl = load_template("onboarding_plan")
    selected = retrieve_sources(db, employee["role"])
    if not selected:
        raise GenerationFailed(f"No approved source documents apply to the role '{employee['role']}'.")
    values = {"company": COMPANY, "employee_id": employee["employee_id"], "role": employee["role"],
              "department": employee.get("department", ""), "experience_level": employee.get("experience_level", "Beginner"),
              "joining_date": employee.get("joining_date", ""), "previous_experience": employee.get("previous_experience", "None"),
              "stages": stage_names(), "min_modules": 6, "max_modules": 10, "schema_example": plan_example(),
              "sources": format_sources(selected)}
    return tpl, tpl["system"].format(**values), tpl["user"].format(**values), selected


def generate_plan_json(db, employee, request_id):
    tpl, system, prompt, selected = build_plan_prompt(db, employee)
    plan, attempts = call_with_retry(db, system, prompt, OnboardingPlan, "onboarding_plan", request_id)
    meta = {"model": getattr(get_client(), "model", "?"), "provider": current_app.config.get("GENAI_PROVIDER"), "prompt_template": tpl["name"],
            "prompt_version": tpl["version"], "temperature": current_app.config["GENAI_TEMPERATURE"],
            "generated_at": now(), "attempts": attempts,
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
