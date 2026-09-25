# Sitara Bank — Company Document Pack for SkillSprint AI

Start with `00_Company_Profile.md`.

## Folder structure

```
00_Company_Profile.md          Company profile, scenario, roles, precedence, statistics, matrix rules
documents/
  active/pdf, active/docx      21 current documents, each in PDF and DOCX
  superseded/pdf, docx         10 old v1.0 versions (for version-control tests)
  adversarial/pdf, docx        5 malicious / irrelevant documents (security tests)
markdown_source/               Editable source text of every document
data/
  documents_metadata.csv       Metadata of all 36 files
  roles.csv                    12 roles
  employees.csv                15 sample employee profiles (no sensitive data)
  requirements_master.csv      228 reference requirements (ground truth)
  role_requirement_matrix.csv  1247 role-requirement rows (active only)
  version_history.csv          v1.0 → v2.0 changes
  conflict_cases.csv           14 conflict / ambiguity / missing-source cases
  duplicate_cases.csv          Known duplicate requirements
  adversarial_cases.csv        10 prompt-injection and adversarial cases
  precedence_rules.yaml        Precedence hierarchy (copy into config/)
```

## Important notes

- `requirements_master.csv` is the **expected answer**. Your app must build its own matrix from the uploaded documents; use this file to test that your extractor produces the same result. Do not load it into the app as hard-coded output.
- ADV-01 and ADV-05 contain **hidden white 1-point text**. It is invisible when opened in Word or a PDF viewer but is extracted by pdfplumber and python-docx, which is exactly what the security tests need.
- Upload superseded files after the active ones (or vice versa) to test that the app keeps only the Active version.
- Keep a few documents aside (for example a new Loan Officer role or a revised SOP) to rehearse the hidden-document evaluation.
