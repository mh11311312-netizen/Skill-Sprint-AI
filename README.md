A Flask web application that reads company documents (PDF/DOCX) and turns them into personalised, role-based onboarding plans with a GenAI model (OpenAI or Google Gemini, chosen in '.env') and then checks every generated item against an independent Python ground-truth pipeline before anyone is allowed to trust it.

Sample company:Sitara Bank Ltd.(fictional, Karachi) – 21 active documents, 10 superseded versions,
5 adversarial documents, 12 roles, 15 employees (see 'sample_documents/').

#Two pipelines

Pipeline 1 – GenAI,Pipeline 2 – Python validation 
| Folder | `genai_pipeline/`, `prompt_templates/`, `schemas/` | `role_matrix/`, `python_validation/`, `hallucination_checks/`, `contradiction_checks/`, `comparison_engine/` |
| Input | Employee profile + approved source clauses for the role | Uploaded documents only |
| Output | Structured JSON plan (Pydantic-validated) | Role Requirement Matrix + validation result |
| Uses AI? | Yes (OpenAI or Gemini) | **No** |

Validation statuses: Verified, Verified with Warning, Partially Verified, Source Support Missing, Requirement Missing,
Unsupported Requirement, Outdated Source, Contradiction Detected, Manual Review Required.
Scores: coverage, traceability, requirement consistency, generation consistency, missing / unsupported / contradiction counts.

## Features (mapped to the SRS)
- Upload with validation: type, size (10 MB), empty, duplicate (SHA-256), metadata, dates, versions.
- Parsing with page / paragraph references; numbered-clause chunking with a fallback for unseen formats.
- Version control: only the Active version is used; superseded versions are kept for history and impact analysis.
- Security: prompt-injection scanner, hidden-text detection (white / tiny font in PDF and DOCX), quarantine,
  untrusted categories, source delimiters in prompts, bcrypt passwords, role-based access, CSRF protection.
- Role Requirement Matrix built by rules in `config/*.yaml` – obligation, type, roles, stage, priority, assessment,
  prerequisites; conflicts and duplicates between sources resolved with `config/precedence_rules.yaml`.
- GenAI generation with versioned prompt templates, limited retries with validator feedback, full API logging.
- Python validation: source existence, outdated/untrusted sources, number checks, similarity support (hallucination),
  coverage, role relevance, quiz answer/distractor checks, prerequisites and sequencing, duplicates.
- Human review: approve / reject / comment, edit a module (schema-checked), item-level overrides with justification,
  regenerate selected modules, full audit trail.
- Policy update impact: diff between versions, affected plans / modules / quiz questions / tasks, selective regeneration.
- Hallucination challenge: topic requests are refused and routed to manual review when sources do not cover them.
- Employee learning view: modules, checklist, tasks, quizzes, progress status, weak areas, adaptive recommendations.
- Dashboards (admin, role, employee), search & filters, plan comparison, 8 reports with CSV / Excel / PDF export.

## Setup (Windows, VS Code)

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # then edit .env: MONGO_URI, SECRET_KEY, GENAI_PROVIDER and its API key
python -m src.seed            # creates users, roles and employees (never requirements)
python app.py                 # open http://127.0.0.1:5000
```

1. Log in as `admin / Admin@123`.
2. **Documents** → select all files in `sample_documents/Sitara_Bank_Company_Pack/documents/active/pdf/`
   (or docx), then `superseded/` and `adversarial/`, and upload. The matrix is rebuilt automatically.
3. **Employees** → open an employee → *Generate personalised plan with GenAI*. Validation runs automatically.
4. **Review queue** → approve, reject, override or regenerate.
5. Log in as the employee (`emp-002 / Employee@123`) to complete modules and quizzes.
6. Upload a new version of a policy (higher version number) → **Policy impact**.

View the data with **MongoDB Compass** using the same `MONGO_URI` (database `skillsprint`).

### Demo accounts (change before deployment)
| Username | Password | Access |
|---|---|---|
| admin | Admin@123 | everything |
| trainer | Trainer@123 | documents, roles, employees, generation |
| reviewer | Reviewer@123 | review, approve, override |
| evaluator | Evaluator@123 | admin access for the evaluation team |
| emp-001 … emp-015 | Employee@123 | own learning plan only |

## Hidden evaluation documents / new role
No code change is needed: upload the documents (PDF/DOCX with a document control block, or fill the metadata form),
add the new role on **Roles** (the matrix is rebuilt), add an employee, generate. Unknown role names found in
"Applies to" lines are listed on **Conflicts & duplicates**. See `hidden_test_ready/README.md`.

## Tests
```bash
python -m pytest -q
```
Tests use an in-memory MongoDB (`mongomock`) and a local stand-in for the Gemini API (`tests/fake_llm.py`)
that can inject deliberate mistakes (hallucinated requirement, wrong number, outdated/untrusted source, missing
requirement, wrong quiz answer, bad sequencing) to prove that Pipeline 2 catches them. The application itself
always calls the real API.

## Deployment (Render + MongoDB Atlas)
`render.yaml` is included. Set `MONGO_URI`, `GENAI_PROVIDER` and the matching API key as environment variables, allow Render's IP
(or 0.0.0.0/0) in Atlas Network Access, then run `python -m src.seed` once from the Render shell.

## Known limitations
- Conflict detection and hallucination support use TF-IDF similarity and rules – thresholds live in
  `config/validation_rules.yaml` and are documented heuristics, not guarantees. Conflicts that need
  reasoning without numbers or opposite wording (e.g. "60 days" vs "end of probation") may be missed.
- Scanned (image-only) PDFs are rejected as empty; OCR is not included.
- Switch provider or model in `.env` (`GENAI_PROVIDER`, `OPENAI_MODEL`, `GEMINI_MODEL`) - no code change.
- GPT-5 family models ignore the temperature setting (they use their fixed default); consistency is
  measured by the consistency check instead.

## AI usage
See `AI_USAGE.md`.
