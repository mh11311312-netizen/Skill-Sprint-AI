# Code Guide (Roman Urdu) – pehle yeh parhein

Yeh file aap ke liye hai taake live code-change aur bug-fix round mein aap ko pata ho ke kaunsi cheez kahan hai.

## 1. Poora flow aik nazar mein
```
Document upload (src/routes/documents.py)
  -> document_processing/ingest.py
       1. document_validation/validator.py   file type, size, empty, duplicate, metadata check
       2. document_processing/parser.py      PDF/DOCX se text + page/paragraph + hidden text flag
       3. document_processing/metadata.py    "Document Control" table se ID, version, dates
       4. document_processing/structure.py   "2.1", "2.2" clauses mein todna (chunks)
       5. security/injection.py              prompt injection dhoondna -> quarantine
       6. version control                    naya version Active, purana Superseded
       7. role_matrix/builder.py             Role Requirement Matrix dobara banana
       8. src/impact.py                      purane plans jo is document ko cite karte hain -> Outdated

Plan generate (src/routes/plans.py -> generate)
  -> genai_pipeline/generator.py   role ke clauses select + prompt template + Gemini call + retry
  -> schemas/plan_schema.py        Pydantic se JSON check
  -> python_validation/validator.py  Python ground truth se comparison (koi AI nahi)
```

## 2. Kaunsi cheez badalni ho to kahan jayein
| Kaam | File |
|---|---|
| Stages ya un ke din badalne hain | `config/stages.yaml` |
| Precedence (Policy > SOP ...) badalni hai | `config/precedence_rules.yaml` |
| Hallucination / conflict threshold | `config/validation_rules.yaml` |
| "must/should/may" ke rules | `config/requirement_rules.yaml` |
| Naya validation status ya rule | `python_validation/validator.py` (section 2 aur 3) |
| Prompt badalna (version barhana na bhoolein) | `prompt_templates/onboarding_plan.yaml` |
| JSON mein naya field | `schemas/plan_schema.py` + `schemas/examples.py` + template |
| Naya report | `src/reports.py` (REPORTS dict + build function) |
| Progress status ke rules | `src/progress.py` (assess function) |
| Nayi injection pattern | `security/injection.py` (PATTERNS list) |
| Naya page | `src/routes/<file>.py` + `templates/<page>.html` + `templates/base.html` mein link |

## 3. Important concepts (evaluator poochega)
- **Requirement ID** = `<DocumentID>-<SectionID>`, jaise `POL-04-3.2`. Isi se traceability hoti hai.
- **Ground truth independent hai**: `role_matrix/` sirf regex/rules use karta hai, Gemini ko call nahi karta.
- **Duplicate** (`duplicate_of`) aur **overridden** (`overridden_by`) requirements matrix mein inactive hoti hain.
- **Scope-specific rule**: sab ke liye 70% pass mark aur AML roles ke liye 80% – yeh conflict nahi, dono valid.
- **Quarantine**: flagged clause na Gemini ko jata hai, na requirement banta hai.
- **Retry**: `GENAI_MAX_RETRIES` (default 3). Har attempt `generation_logs` collection mein.
- **Override**: reviewer kisi item/plan ka status badal sakta hai lekin comment zaroori, original status audit mein rehta hai.

## 4. MongoDB collections (Compass mein dekhein)
users, roles, employees, documents, chunks, requirements, conflicts, plans, generation_logs, progress,
audit_log, security_events, matrix_builds, impact_reports, review_requests

## 5. Debug karne ka tareeqa
1. Terminal mein error ki last line parhein – file aur line number wahin hota hai.
2. `python -m pytest -q` chala kar dekhein kaunsa test fail hua.
3. Compass mein related collection kholen (e.g. `generation_logs` mein Gemini ka error).
4. Validation galat lage to plan page ka "GenAI vs Python" tab dekhein – har row ka explanation hota hai.
