# Architecture

```
Browser (Jinja + Bootstrap, local assets)
   │
Flask app (app.py → src/routes/* blueprints, role-based access, CSRF)
   │
   ├── Document intake: document_validation → document_processing → security
   ├── Ground truth:    role_matrix (+ contradiction_checks/source_conflicts)     [no AI]
   ├── Pipeline 1:      genai_pipeline (client, generator) + prompt_templates + schemas   [Gemini]
   ├── Pipeline 2:      python_validation + hallucination_checks + comparison_engine     [no AI]
   ├── Services:        src/progress.py, src/impact.py, src/reports.py, src/audit.py
   │
MongoDB Atlas (pymongo) – collections listed in database/db.py
```

Design decisions
- Clause-level chunks keep document ID, version, section ID and page/paragraph so every generated item can be traced.
- The matrix is rebuilt from stored chunks (not from files) so adding a role or a document never needs code changes.
- The GenAI model receives only Active, trusted, non-quarantined clauses wrapped in `<source_document>` tags.
- Pydantic validates structure; Python rules validate meaning; humans decide on anything flagged.
