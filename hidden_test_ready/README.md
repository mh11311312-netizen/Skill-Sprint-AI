# Hidden evaluation readiness

The application contains no hard-coded document names, requirement IDs or outputs.

For an unseen document pack:
1. Documents → upload. If a file has no document control block, upload it alone and fill in the metadata form
   (Document ID, title, category, department, version, effective date).
2. Documents without numbered clauses are chunked by headings and sentences (fallback chunker).
3. Roles → add any new role. The matrix is rebuilt from stored chunks immediately.
4. Requirement Matrix → check the extracted requirements; Conflicts → check conflicts and unknown role names.
5. Employees → add the hidden employee profile → Generate plan.
6. Tune thresholds in `config/validation_rules.yaml` or precedence in `config/precedence_rules.yaml` if needed –
   no code change and no redeploy of logic.
