"""Hidden-data readiness: a pack of documents the app has never seen, in a different format,
with a new role, a revised policy, a conflicting FAQ, an adversarial file and invalid files."""
import os
import pytest
from conftest import ROOT
from document_processing.ingest import ingest, IngestError
from role_matrix.builder import rebuild_matrix
from src.audit import now

PACK = os.path.join(ROOT, "hidden_test_ready", "mock_hidden_pack")


def _load(ctx, app, name, meta=None):
    return ingest(ctx, name, open(os.path.join(PACK, name), "rb").read(), meta or {}, app.config, "pytest")


def test_hidden_pack(ctx, app):
    if not ctx.roles.find_one({"name": "Loan Officer"}):
        ctx.roles.insert_one({"role_id": "ROLE-99", "name": "Loan Officer", "department": "Consumer Lending",
                              "default_level": "Beginner", "description": "", "created_at": now()})
        rebuild_matrix(ctx)
    # new role document without numbered clauses (fallback chunking)
    _load(ctx, app, "RD-02_v1.0_Loan_Officer_Role_Guide.docx")
    loan = {r["requirement_id"] for r in ctx.requirements.find({"roles": "Loan Officer", "document_id": "RD-02", "active": True})}
    assert {"RD-02-1.1", "RD-02-1.2", "RD-02-2.2", "RD-02-3.1"} <= loan
    # revised policy supersedes the old version
    _load(ctx, app, "POL-03_v3.0_Leave_Policy.pdf")
    assert ctx.documents.find_one({"document_id": "POL-03", "version": "2.0"})["status"] == "Superseded"
    # conflicting FAQ loses to the role description by precedence
    _load(ctx, app, "FAQ-03_v1.0_Lending_FAQ.pdf")
    assert ctx.requirements.find_one({"requirement_id": "FAQ-03-1.1"})["overridden_by"] == "RD-02-2.2"
    # adversarial document is untrusted and its hidden instruction is quarantined
    doc, _, _ = _load(ctx, app, "ADV-06_v1.0_Lending_Team_Notes.docx")
    assert doc["trust"] == "Untrusted" and any("Hidden text" in f["types"] for f in doc["security_flags"])
    # invalid files are rejected with clear messages
    for bad in ("broken_file.pdf", "virus.exe", "empty_document.docx", "no_metadata_Branch_Hours.docx"):
        with pytest.raises(IngestError):
            _load(ctx, app, bad)
    # the same file works once the admin types the metadata in the upload form
    doc, _, _ = _load(ctx, app, "no_metadata_Branch_Hours.docx", {"document_id": "POL-10", "title": "Branch Hours",
                      "category": "Policy", "department": "Operations", "version": "1.0", "effective_date": "2026-09-01"})
    assert doc["trust"] == "Trusted" and ctx.requirements.find_one({"requirement_id": "POL-10-1.1"})
