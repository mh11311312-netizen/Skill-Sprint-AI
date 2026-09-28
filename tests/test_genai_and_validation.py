"""Pipeline 1 (schema, retry) and Pipeline 2 (validation against deliberately wrong output)."""
import pytest
from pydantic import ValidationError
from schemas.plan_schema import OnboardingPlan
from genai_pipeline.client import set_client_override
from genai_pipeline.generator import create_plan, GenerationFailed
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
    try:
        started = _t.time()
        plan = create_plan(ctx, _emp(ctx), "pytest")
        took = _t.time() - started
    finally:
        app.config.pop("GENAI_TIME_BUDGET", None)
    assert took < 6.5 and plan["generation"]["late_requests"] >= 1
    assert plan["plan_json"]["modules"]         # the requests that finished are in the plan
