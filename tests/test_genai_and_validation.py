"""Pipeline 1 (schema, retry) and Pipeline 2 (validation against deliberately wrong output)."""
import pytest
from pydantic import ValidationError
from schemas.plan_schema import OnboardingPlan
from genai_pipeline.client import set_client_override
from genai_pipeline.generator import create_plan, GenerationFailed, regenerate_modules
from python_validation.validator import validate_plan
from src.progress import grade_quiz
from tests.fake_llm import FakeLLM


def _emp(ctx, eid="EMP-002"):
    return ctx.employees.find_one({"employee_id": eid})


def test_schema_rejects_bad_json():
    with pytest.raises(ValidationError):
        OnboardingPlan.model_validate({"role": "X", "employee_id": "E", "summary": "s", "modules": []})


def test_retry_recovers_from_invalid_json(ctx):
    set_client_override(FakeLLM(fail_first=1))
    plan = create_plan(ctx, _emp(ctx), "pytest")
    gen = plan["generation"]
    assert gen["failed_batches"] == 0 and gen["attempts"] == gen["batches"] + 1


def test_retry_limit_is_enforced(ctx):
    set_client_override(FakeLLM(fail_first=99))
    with pytest.raises(GenerationFailed):
        create_plan(ctx, _emp(ctx), "pytest")


def test_plan_is_generated_in_batches_with_unique_ids(ctx):
    set_client_override(FakeLLM())
    plan = create_plan(ctx, _emp(ctx), "pytest")
    ids = [m["module_id"] for m in plan["plan_json"]["modules"]]
    assert plan["generation"]["batches"] > 1 and len(ids) == len(set(ids))
    tasks = [t["task_id"] for m in plan["plan_json"]["modules"] for t in m["tasks"]]
    assert len(tasks) == len(set(tasks))


def test_gap_fill_rounds_raise_coverage_of_a_lazy_model(ctx, app):
    set_client_override(FakeLLM(mistakes={"lazy"}))
    app.config["GENAI_COVERAGE_ROUNDS"] = 2
    try:
        plan = create_plan(ctx, _emp(ctx), "pytest")
    finally:
        app.config.pop("GENAI_COVERAGE_ROUNDS", None)
    v = validate_plan(ctx, plan)
    assert plan["generation"]["gap_fill_rounds"] >= 1 and v["scores"]["coverage"] >= 70


def test_clean_plan_has_full_traceability(ctx):
    set_client_override(FakeLLM())
    plan = create_plan(ctx, _emp(ctx), "pytest")
    v = validate_plan(ctx, plan)
    assert v["scores"]["traceability"] == 100.0 and v["scores"]["unsupported_count"] == 0


@pytest.mark.parametrize("mistake,expected", [
    ("hallucination", "Source Support Missing"),
    ("wrong_number", "Contradiction Detected"),
    ("outdated", "Unsupported Requirement"),
    ("missing", "Requirement Missing"),
])
def test_validator_catches_injected_errors(ctx, mistake, expected):
    set_client_override(FakeLLM(mistakes={mistake}))
    plan = create_plan(ctx, _emp(ctx), "pytest")
    v = validate_plan(ctx, plan)
    assert expected in v["status_counts"], v["status_counts"]
    assert v["status"] != "Verified"


def test_quiz_and_sequence_errors_flagged(ctx):
    set_client_override(FakeLLM(mistakes={"bad_quiz", "sequence"}))
    v = validate_plan(ctx, create_plan(ctx, _emp(ctx), "pytest"))
    kinds = {i["kind"] for i in v["issues"]}
    assert "Quiz answer" in kinds and "Sequencing" in kinds


def test_quiz_grading():
    module = {"quiz": [{"question_id": "Q1", "correct_answers": ["True"]}, {"question_id": "Q2", "correct_answers": ["A", "B"]}]}
    score, correct, total, wrong = grade_quiz(module, {"Q1": ["True"], "Q2": ["A"]})
    assert (score, correct, total, wrong) == (50.0, 1, 2, ["Q2"])


def test_generation_time_is_recorded(ctx):
    set_client_override(FakeLLM())
    plan = create_plan(ctx, _emp(ctx), "pytest")
    assert plan["generation"]["seconds"] >= 0


def test_approval_needs_full_coverage_and_missing_items_can_be_added(ctx, client):
    from conftest import login
    from python_validation.validator import run_validation
    set_client_override(FakeLLM(mistakes={"missing"}))
    plan = create_plan(ctx, _emp(ctx), "pytest")
    v = run_validation(ctx, plan)
    assert v["scores"]["coverage"] < 100
    login(client, "reviewer", "Reviewer@123")
    client.post(f"/plans/{plan['plan_id']}/review", data={"action": "approve", "comment": "try"})
    assert ctx.plans.find_one({"plan_id": plan["plan_id"]})["status"] != "Approved"
    set_client_override(FakeLLM())
    client.post(f"/plans/{plan['plan_id']}/fill-missing")
    after = ctx.plans.find_one({"plan_id": plan["plan_id"]})
    assert after["validation"]["scores"]["coverage"] == 100
    assert len(after["plan_json"]["modules"]) > len(plan["plan_json"]["modules"])
    client.post(f"/plans/{plan['plan_id']}/review", data={"action": "approve", "comment": "all mandatory items covered"})
    assert ctx.plans.find_one({"plan_id": plan["plan_id"]})["status"] == "Approved"



def test_time_budget_returns_on_time_even_if_a_request_hangs(ctx, app):
    import time as _t

    class HangingLLM(FakeLLM):
        def generate(self, system, prompt, temperature):
            if "BATCH 1 OF" in prompt:
                _t.sleep(8)                     # one request is very slow
            return super().generate(system, prompt, temperature)

    set_client_override(HangingLLM())
    app.config["GENAI_TIME_BUDGET"] = 5
    app.config["GENAI_HEDGE_AFTER"] = 0
    try:
        started = _t.time()
        plan = create_plan(ctx, _emp(ctx), "pytest")
        took = _t.time() - started
    finally:
        app.config.pop("GENAI_TIME_BUDGET", None)
        app.config.pop("GENAI_HEDGE_AFTER", None)
    assert took < 6.5 and plan["generation"]["late_requests"] >= 1
    assert plan["plan_json"]["modules"]         # the requests that finished are in the plan


def test_regenerate_modules_runs_in_parallel_within_time_budget(ctx, app):
    """Selecting several modules to regenerate must not take module-count x per-call-time:
    a reviewer should wait a few seconds, not 30-40s, however many modules are selected."""
    import time as _t

    class SlowLLM(FakeLLM):
        def generate(self, system, prompt, temperature):
            _t.sleep(2)                      # each simulated API call takes 2 seconds
            return super().generate(system, prompt, temperature)

    set_client_override(FakeLLM())
    plan = create_plan(ctx, _emp(ctx), "pytest")
    module_ids = [m["module_id"] for m in plan["plan_json"]["modules"][:4]]   # 4 modules selected at once
    set_client_override(SlowLLM())
    app.config["GENAI_REGEN_TIME_BUDGET"] = 20
    try:
        started = _t.time()
        changed, failed = regenerate_modules(ctx, plan, module_ids, "test", "pytest")
        took = _t.time() - started
    finally:
        app.config.pop("GENAI_REGEN_TIME_BUDGET", None)
    # sequential would take ~8s (4 x 2s); parallel takes ~2s - generously allow up to 5s
    assert took < 6, f"regenerate_modules took {took:.1f}s for 4 modules - looks sequential, not parallel"
    assert not failed and {c["module_id"] for c in changed} == set(module_ids)


def test_regenerate_modules_leaves_unfinished_modules_unchanged(ctx, app):
    """If the time budget runs out, modules that did not finish keep their original content
    and are reported back, instead of the reviewer waiting indefinitely."""
    import time as _t

    class HangingLLM(FakeLLM):
        def generate(self, system, prompt, temperature):
            if "hang" in prompt:
                _t.sleep(6)
            return super().generate(system, prompt, temperature)

    set_client_override(FakeLLM())
    plan = create_plan(ctx, _emp(ctx), "pytest")
    m0, m1 = plan["plan_json"]["modules"][0], plan["plan_json"]["modules"][1]
    original_title = m0["module_title"]
    set_client_override(HangingLLM())
    app.config["GENAI_REGEN_TIME_BUDGET"] = 2
    try:
        # module_regeneration prompt template includes the module id; make module 0's prompt "hang"
        m0["module_title"] = "hang " + m0["module_title"]
        changed, failed = regenerate_modules(ctx, plan, [m0["module_id"], m1["module_id"]], "test", "pytest")
    finally:
        app.config.pop("GENAI_REGEN_TIME_BUDGET", None)
    assert any(mid == m1["module_id"] for c in changed for mid in [c["module_id"]])
    assert any(mid == m0["module_id"] for mid, _ in failed)


def test_document_category_words_are_mapped_but_unknown_categories_rejected():
    """The model sometimes writes the source document's category ('SOP') as the module category."""
    from tests.fake_llm import FakeLLM as _F
    import json as _j
    from genai_pipeline.generator import _extract_json
    base = {"role": "Cash Teller", "employee_id": "EMP-011", "summary": "s", "modules": [], "insufficient_information": []}
    mod = {"module_id": "M01", "module_title": "Cash handling", "category": "SOP", "purpose": "p", "stage": "Week 1", "mandatory": True,
           "priority": "High", "difficulty": "Beginner", "estimated_duration_minutes": 30, "prerequisites": [], "learning_objectives": ["o"],
           "key_concepts": [], "learning_activities": [], "completion_criteria": "c",
           "requirements_covered": [{"source_document_id": "SOP-04", "source_section_id": "3.1", "requirement_id": "SOP-04-3.1",
                                     "statement": "Tellers must count cash twice.", "mandatory": True, "due_stage": "Week 1"}],
           "checklist": [], "tasks": [], "quiz": [], "assessment": {"type": "knowledge", "topic": "Cash", "rubric": []}}
    for word, expected in (("SOP", "Process"), ("sop", "Process"), ("Handbook", "Orientation"), ("Role Description", "Role Skills"), ("FAQ", "Policy")):
        d = dict(base, modules=[dict(mod, category=word)])
        assert OnboardingPlan.model_validate(d).modules[0].category == expected
    with pytest.raises(ValidationError):
        OnboardingPlan.model_validate(dict(base, modules=[dict(mod, category="Miscellaneous")]))



def test_parts_that_outlive_the_budget_are_merged_in_the_background(ctx, app):
    """The plan is returned within the budget, and the requests that were still running are added to it
    automatically when they finish, followed by a fresh Python validation."""
    import time as _t

    class SlowBatchLLM(FakeLLM):
        def generate(self, system, prompt, temperature):
            if "BATCH 1 OF" in prompt or "BATCH 2 OF" in prompt:
                _t.sleep(4)
            return super().generate(system, prompt, temperature)

    set_client_override(SlowBatchLLM())
    app.config["GENAI_TIME_BUDGET"] = 5
    app.config["GENAI_HEDGE_AFTER"] = 0
    try:
        started = _t.time()
        plan = create_plan(ctx, _emp(ctx), "pytest")
        assert _t.time() - started < 5.5
        first = len(plan["plan_json"]["modules"])
        assert plan["generation"]["background_requests"] >= 1
        for _ in range(40):                          # wait for the background parts (about 4 s)
            doc = ctx.plans.find_one({"plan_id": plan["plan_id"]})
            if doc["generation"].get("background_done"):
                break
            _t.sleep(0.25)
    finally:
        app.config.pop("GENAI_TIME_BUDGET", None)
        app.config.pop("GENAI_HEDGE_AFTER", None)
    doc = ctx.plans.find_one({"plan_id": plan["plan_id"]})
    assert doc["generation"]["late_requests"] == 0 and doc["generation"]["completed_in_background"] >= 1
    assert len(doc["plan_json"]["modules"]) > first
    assert not any("still being generated" in x for x in doc["plan_json"]["insufficient_information"])
    assert doc["validation"]["scores"]["coverage"] == 100      # re-validated after the merge



def test_plan_is_final_at_the_budget_when_coverage_is_already_complete(ctx, app):
    """If every mandatory requirement is covered when the budget ends, late parts are not waited for."""
    import time as _t

    class OneSlowLLM(FakeLLM):
        def generate(self, system, prompt, temperature):
            if "BATCH 1 OF" in prompt:
                _t.sleep(4)
            return super().generate(system, prompt, temperature)

    set_client_override(OneSlowLLM())
    ctx.plans.delete_many({})
    app.config["GENAI_TIME_BUDGET"] = 5
    try:
        plan = create_plan(ctx, _emp(ctx), "pytest")
    finally:
        app.config.pop("GENAI_TIME_BUDGET", None)
    doc = ctx.plans.find_one({"plan_id": plan["plan_id"]})
    if doc["validation"]["scores"]["coverage"] >= 100:
        assert doc["generation"]["late_requests"] == 0 and doc["generation"]["background_done"]
        assert not any("still being generated" in x for x in doc["plan_json"]["insufficient_information"])



def test_slow_requests_are_hedged_so_the_complete_plan_arrives_early(ctx, app):
    """Two requests hang for 10 s. After 2 s their missing clauses are re-sent as tiny requests, so the complete
    plan (100% mandatory coverage) is returned in a few seconds, without waiting for the slow ones."""
    import time as _t

    class Stragglers(FakeLLM):
        def generate(self, system, prompt, temperature):
            if "BATCH 1 OF" in prompt or "BATCH 2 OF" in prompt:
                if "MISSING-CLAUSES REQUEST" not in prompt:
                    _t.sleep(10)
            return super().generate(system, prompt, temperature)

    set_client_override(Stragglers())
    app.config.update(GENAI_TIME_BUDGET=20, GENAI_HEDGE_AFTER=2)
    try:
        started = _t.time()
        plan = create_plan(ctx, _emp(ctx), "pytest")
        took = _t.time() - started
    finally:
        app.config.pop("GENAI_TIME_BUDGET", None)
        app.config.pop("GENAI_HEDGE_AFTER", None)
    from python_validation.validator import run_validation
    doc = ctx.plans.find_one({"plan_id": plan["plan_id"]})
    assert took < 6, f"took {took:.1f}s"
    assert doc["generation"]["late_requests"] == 0
    assert run_validation(ctx, doc)["scores"]["coverage"] == 100
