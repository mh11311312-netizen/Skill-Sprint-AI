"""Step 37/38 - The JSON structure the GenAI model must return, validated with Pydantic."""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

Stage = Literal["Day 1", "Week 1", "Week 2", "First 30 Days", "First 60 Days", "First 90 Days"]
Level = Literal["Beginner", "Intermediate", "Advanced"]
SCHEMA_VERSION = "1.0"
ID = r"^[A-Za-z0-9_-]{1,40}$"          # ids are used as MongoDB keys, so no dots or spaces


class Sourced(BaseModel):
    source_document_id: str = Field(min_length=2)
    source_section_id: str = Field(min_length=1)


class CoveredRequirement(Sourced):
    requirement_id: str
    statement: str = Field(min_length=5)
    mandatory: bool
    due_stage: Stage


class ChecklistItem(Sourced):
    activity: str = Field(min_length=3)
    required: bool
    due_stage: Stage
    responsible: str = "Employee"


class Task(Sourced):
    task_id: str = Field(pattern=ID)
    description: str = Field(min_length=5)
    expected_outcome: str
    completion_criteria: str
    difficulty: Level
    due_stage: Stage
    scenario_based: bool = False


class QuizQuestion(Sourced):
    question_id: str = Field(pattern=ID)
    type: Literal["multiple_choice", "multiple_response", "true_false", "scenario"]
    question: str = Field(min_length=5)
    options: List[str] = Field(min_length=2)
    correct_answers: List[str] = Field(min_length=1)
    explanation: str
    difficulty: Level


class RubricItem(BaseModel):
    criterion: str
    weight: int = Field(ge=0, le=100)
    expected_performance: str
    pass_condition: str


class Assessment(BaseModel):
    type: Literal["knowledge", "practical", "scenario", "role_specific"]
    topic: str
    rubric: List[RubricItem] = []


class Module(BaseModel):
    module_id: str = Field(pattern=ID)
    module_title: str = Field(min_length=3)
    category: Literal["Policy", "Compliance", "Process", "Role Skills", "Orientation"]
    purpose: str
    stage: Stage
    mandatory: bool
    priority: Literal["High", "Medium", "Low"]
    difficulty: Level
    estimated_duration_minutes: int = Field(ge=5, le=600)
    prerequisites: List[str] = []
    learning_objectives: List[str] = Field(min_length=1)
    key_concepts: List[str] = []
    learning_activities: List[str] = []
    completion_criteria: str
    requirements_covered: List[CoveredRequirement] = Field(min_length=1)
    checklist: List[ChecklistItem] = []
    tasks: List[Task] = []
    quiz: List[QuizQuestion] = []
    assessment: Optional[Assessment] = None


class OnboardingPlan(BaseModel):
    role: str
    employee_id: str
    summary: str
    modules: List[Module] = Field(min_length=1)
    insufficient_information: List[str] = []

    @field_validator("modules")
    @classmethod
    def unique_module_ids(cls, v):
        ids = [m.module_id for m in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate module_id values")
        return v
