# AI Usage Declaration

This file records every use of AI tools during the project, as required by the SRS.
**Keep it updated daily.** Every AI-assisted part must be reviewed, understood, tested and, where needed, modified by the team.

## Tools used
| Tool | Purpose |
|---|---|
| Claude (Anthropic) | Planning, sample dataset generation, initial code scaffold, explanations |
| OpenAI API (GPT-5.6) | Runtime generation of onboarding plans (Pipeline 1) |
| Google Gemini API | Alternative provider for Pipeline 1 (switch in .env) |

## Log

| Date | Tool | What was generated / assisted | What we reviewed, changed or tested | Files |
|---|---|---|---|---|
| 2026-09-24 | Claude | Fictional company document pack (Sitara Bank) and CSV data | _fill in: what you checked/edited_ | sample_documents/ |
| 2026-09-24 | Claude | Initial Flask application scaffold: pipelines, templates, tests | _fill in: modules you reviewed, bugs you fixed, changes you made_ | all folders |
|  |  |  |  |  |

## Parts written or substantially changed by the team
_List them here as you work (e.g. "changed conflict threshold after testing", "added X report")._

## Prompts used for Gemini
Prompt templates are version-controlled in `prompt_templates/` (name, version, changelog).
