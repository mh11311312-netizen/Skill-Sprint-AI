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
    assert plan["generation"]["attempts"] == 2


def test_retry_limit_is_enforced(ctx):
    set_client_override(FakeLLM(fail_first=99))
    with pytest.raises(GenerationFailed):
        create_plan(ctx, _emp(ctx), "pytest")


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
