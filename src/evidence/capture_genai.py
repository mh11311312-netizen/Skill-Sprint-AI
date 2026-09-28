"""Runs the REAL Pipeline 1 code and records everything the SRS asks for in "GenAI Pipeline Evidence":
real prompts, real responses, generation logs, deliberate failures and the retry that recovers from them.
Default: an offline stand-in model (no key, no cost).  --live: the real API configured in .env."""
import glob
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

NONJSON = "Sure! Here is your onboarding plan: {modules: [ not valid json"


class Recorder:
    """Wraps any client (real or stand-in), records every call, and can inject faults for the failure demos."""
    def __init__(self, inner, script=None, real_response=None):
        self.inner, self.script, self.real_response = inner, list(script or []), real_response
        self.model = getattr(inner, "model", "unknown")
        self.calls = []

    def generate(self, system, prompt, temperature):
        t0 = time.time()
        step = self.script.pop(0) if self.script else "pass"
        rec = {"fault": step if step != "pass" else None, "system_chars": len(system), "prompt_chars": len(prompt), "prompt_tail": prompt[-620:]}
        try:
            if step == "nonjson":
                text = NONJSON
            elif step == "schema":
                from genai_pipeline.generator import _extract_json
                d = _extract_json(self.real_response)
                m = d["modules"][0]
                m["category"] = "Miscellaneous"          # not an allowed value
                m["requirements_covered"] = []           # a module must cover at least one requirement
                text = json.dumps(d)
            elif step.startswith("hang:"):
                time.sleep(float(step.split(":")[1]))
                text = self.inner.generate(system, prompt, temperature)
            else:
                text = self.inner.generate(system, prompt, temperature)
            rec.update(ok=True, response=text, seconds=round(time.time() - t0, 2))
            return text
        except Exception as e:
            rec.update(ok=False, error=f"{e.__class__.__name__}: {e}", seconds=round(time.time() - t0, 2))
            raise
        finally:
            self.calls.append(rec)


def _logs(db, rid):
    return [{k: (str(v) if k == "at" else v) for k, v in l.items() if k != "_id"} for l in db.generation_logs.find({"request_id": rid}).sort("at", 1)]


def capture(live=False):
    from app import create_app
    from database.db import get_db
    from src.seed import seed
    from document_processing.ingest import ingest
    from genai_pipeline.client import set_client_override, get_client
    from genai_pipeline import generator as G
    from schemas.plan_schema import OnboardingPlan
    from python_validation.validator import run_validation
    from config.loader import load_yaml

    app = create_app({"USE_MONGOMOCK": True, "TESTING": not live, "WTF_CSRF_ENABLED": False, "MONGO_DB": "genai_evidence"})
    pack = os.path.join(ROOT, "sample_documents", "Sitara_Bank_Company_Pack", "documents", "active", "docx")
    bundle = {"live": live, "captured_at": time.strftime("%Y-%m-%d %H:%M"), "scenarios": {}}
    with app.test_request_context():
        db = get_db()
        seed(db)
        for f in sorted(glob.glob(pack + "/*.docx")):
            ingest(db, os.path.basename(f), open(f, "rb").read(), {}, app.config, "evidence")
        if live:
            set_client_override(None)
            inner = get_client()
        else:
            sys.path.insert(0, ROOT)
            from tests.fake_llm import FakeLLM
            inner = FakeLLM()
        cfg = app.config
        bundle["config"] = {k: cfg.get(k) for k in ("GENAI_PROVIDER", "OPENAI_MODEL", "GEMINI_MODEL", "GENAI_TEMPERATURE", "GENAI_MAX_RETRIES",
                                                     "GENAI_TIMEOUT_SECONDS", "GENAI_REASONING_EFFORT")}
        for k, d in (("GENAI_BATCH_CLAUSES", 6), ("GENAI_PARALLEL", 32), ("GENAI_COVERAGE_ROUNDS", 0), ("GENAI_TIME_BUDGET", 30), ("GENAI_REGEN_TIME_BUDGET", 10)):
            bundle["config"][k] = G._setting(k, d)
        bundle["model_used"] = getattr(inner, "model", "unknown")
        emp = db.employees.find_one({"employee_id": "EMP-002"})
        bundle["employee"] = {"employee_id": emp["employee_id"], "role": emp["role"], "experience_level": emp["experience_level"]}

        # ---- A. one complete, normal plan generation ----
        rec = Recorder(inner)
        set_client_override(rec)
        t0 = time.time()
        plan = G.create_plan(db, emp, "evidence")
        seconds = round(time.time() - t0, 1)
        n_seconds = seconds
        result = run_validation(db, plan, "evidence")
        oks = [c for c in rec.calls if c.get("ok")]
        sample = next((c for c in oks if "COVERAGE CHECKLIST" in c["prompt_tail"] or True), oks[0])
        # reconstruct the full prompt of a recorded call: it is stored only as chars, so re-derive one real batch prompt
        tpl = G.load_template("onboarding_plan")
        sources = G.retrieve_sources(db, emp["role"])
        batches = G.make_batches(db, G._add_conflict_context(db, sources, sources), G._setting("GENAI_BATCH_CLAUSES", 6))
        system, prompt = G._batch_prompt(tpl, emp, batches[1] if len(batches) > 1 else batches[0], 2 if len(batches) > 1 else 1, len(batches))
        real_resp = None
        set_client_override(inner)
        real_resp = inner.generate(system, prompt, cfg["GENAI_TEMPERATURE"])
        bundle["scenarios"]["normal"] = {
            "plan_id": plan["plan_id"], "seconds": seconds, "calls": len(rec.calls), "batches": plan["generation"].get("batches"),
            "modules": len(plan["plan_json"]["modules"]), "gen_meta": {k: v for k, v in plan["generation"].items() if k not in ("source_versions",)},
            "validation": {"status": result["status"], "scores": result["scores"]},
            "logs": _logs(db, plan["plan_id"]),
            "first_module": plan["plan_json"]["modules"][0],
            "sample": {"system": system, "prompt": prompt, "response": real_resp, "model": getattr(inner, "model", "?"),
                       "purpose": f"onboarding_plan batch {2 if len(batches) > 1 else 1}/{len(batches)}"},
            "avg_seconds": round(sum(c["seconds"] for c in oks) / max(1, len(oks)), 2),
            "prompt_chars_total": sum(c["prompt_chars"] for c in rec.calls),
            "response_chars_total": sum(len(c.get("response", "")) for c in oks),
        }
        # ---- B. retry that recovers: bad text -> schema-invalid JSON -> valid ----
        rb = Recorder(inner, ["nonjson", "schema", "pass"], real_response=real_resp)
        set_client_override(rb)
        obj, attempts = G.call_with_retry(db, system, prompt, OnboardingPlan, "retry demo (real batch prompt)", "evidence-retry")
        bundle["scenarios"]["retry"] = {"attempts": attempts, "logs": _logs(db, "evidence-retry"),
                                        "calls": [{k: v for k, v in c.items() if k != "response"} for c in rb.calls],
                                        "feedback_attempt2": rb.calls[1]["prompt_tail"], "feedback_attempt3": rb.calls[2]["prompt_tail"]}
        # ---- C. retries exhausted ----
        rc = Recorder(inner, ["nonjson"] * cfg["GENAI_MAX_RETRIES"], real_response=real_resp)
        set_client_override(rc)
        try:
            G.call_with_retry(db, system, prompt, OnboardingPlan, "exhausted demo", "evidence-exhausted")
            msg = "(unexpectedly succeeded)"
        except G.GenerationFailed as e:
            msg = str(e)
        bundle["scenarios"]["exhausted"] = {"message": msg, "logs": _logs(db, "evidence-exhausted")}
        # ---- D. time budget: one request hangs, the plan still returns on time ----
        # offline: answers are instant, so a 5 s budget and a 9 s hang are enough.
        # live: real answers take several seconds each, so the budget must leave room for the normal
        # requests to finish (based on how long the normal plan took above) while one request hangs past it.
        if live:
            budget = int(max(30, n_seconds * 1.5 + 10))
            hang = budget + 10
        else:
            budget, hang = 5, 9
        old_budget = cfg.get("GENAI_TIME_BUDGET")
        cfg["GENAI_TIME_BUDGET"] = budget
        rd = Recorder(inner, [f"hang:{hang}"])
        set_client_override(rd)
        t0 = time.time()
        try:
            pj, meta = G.generate_plan_json(db, emp, "evidence-budget", finish_in_background=False)
            bundle["scenarios"]["budget"] = {"budget": budget, "hang": hang, "seconds": round(time.time() - t0, 1), "late": meta.get("late_requests"),
                                             "modules": len(pj["modules"]), "notes": [x for x in pj.get("insufficient_information", []) if "time budget" in x][:2]}
        except G.GenerationFailed as e:
            # never lose the rest of the evidence because of this one demonstration
            bundle["scenarios"]["budget"] = {"budget": budget, "hang": hang, "seconds": round(time.time() - t0, 1), "late": "all",
                                             "modules": 0, "notes": [str(e)], "failed": True}
        finally:
            if old_budget is None:
                cfg.pop("GENAI_TIME_BUDGET", None)
            else:
                cfg["GENAI_TIME_BUDGET"] = old_budget
        bundle["schema"] = OnboardingPlan.model_json_schema()
        bundle["templates"] = {}
        for name in ("onboarding_plan", "module_regeneration", "topic_module"):
            y = load_yaml(f"../prompt_templates/{name}.yaml") if False else None
        import yaml
        for name in ("onboarding_plan", "module_regeneration", "topic_module"):
            bundle["templates"][name] = yaml.safe_load(open(os.path.join(ROOT, "prompt_templates", name + ".yaml"), encoding="utf-8"))
    out = os.path.join(ROOT, "documentation", "evidence", "genai_capture.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(bundle, open(out, "w", encoding="utf-8"), indent=1, default=str)
    return bundle


if __name__ == "__main__":
    b = capture("--live" in sys.argv)
    print("captured", {k: (v if not isinstance(v, dict) else "...") for k, v in b["scenarios"]["normal"].items() if k in ("seconds", "calls", "modules")})
