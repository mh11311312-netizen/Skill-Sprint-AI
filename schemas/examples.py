"""A compact example of the JSON shape, inserted into prompts (shorter than a full JSON Schema)."""
import json

MODULE_EXAMPLE = {
    "module_id": "M01", "module_title": "Information Security Essentials", "category": "Policy",
    "purpose": "...", "stage": "Week 1", "mandatory": True, "priority": "High", "difficulty": "Beginner",
    "estimated_duration_minutes": 60, "prerequisites": [], "learning_objectives": ["..."],
    "key_concepts": ["..."], "learning_activities": ["..."], "completion_criteria": "...",
    "requirements_covered": [{"requirement_id": "POL-04-3.2", "statement": "...", "mandatory": True,
                              "due_stage": "Week 1", "source_document_id": "POL-04", "source_section_id": "3.2"}],
    "checklist": [{"activity": "...", "required": True, "due_stage": "Week 1", "responsible": "Employee",
                   "source_document_id": "POL-04", "source_section_id": "2.2"}],
    "tasks": [{"task_id": "M01-T1", "description": "...", "expected_outcome": "...", "completion_criteria": "...",
               "difficulty": "Beginner", "due_stage": "Week 1", "scenario_based": True,
               "source_document_id": "POL-04", "source_section_id": "5.1"}],
    "quiz": [{"question_id": "M01-Q1", "type": "multiple_choice", "question": "...",
              "options": ["...", "...", "...", "..."], "correct_answers": ["..."], "explanation": "...",
              "difficulty": "Beginner", "source_document_id": "POL-04", "source_section_id": "3.2"}],
    "assessment": {"type": "practical", "topic": "...",
                   "rubric": [{"criterion": "...", "weight": 100, "expected_performance": "...", "pass_condition": "..."}]},
}
PLAN_EXAMPLE = {"role": "...", "employee_id": "...", "summary": "...", "modules": [MODULE_EXAMPLE],
                "insufficient_information": []}


def plan_example():
    return json.dumps(PLAN_EXAMPLE, indent=1)


def module_example():
    return json.dumps(MODULE_EXAMPLE, indent=1)
