"""Document validation, parsing, metadata, chunking and hidden-text detection."""
import glob
import os
from conftest import PACK
from document_processing.parser import parse_file
from document_processing.metadata import extract_metadata
from document_processing.structure import build_chunks
from document_validation.validator import validate_file, validate_metadata
from document_processing.ingest import ingest, IngestError
import pytest


def _one(pattern):
    return glob.glob(f"{PACK}/{pattern}")[0]


def test_pdf_parsing_keeps_page_numbers():
    parsed = parse_file(open(_one("active/pdf/POL-04*.pdf"), "rb").read(), "pdf")
    assert parsed["lines"] and all(l["page"] >= 1 for l in parsed["lines"])


def test_docx_metadata_from_control_table():
    parsed = parse_file(open(_one("active/docx/POL-04*.docx"), "rb").read(), "docx")
    meta = extract_metadata(parsed)
    assert meta["document_id"] == "POL-04" and meta["version"] == "2.0" and meta["category"] == "Policy"


def test_chunks_have_section_ids_and_applies_to():
    parsed = parse_file(open(_one("active/docx/POL-04*.docx"), "rb").read(), "docx")
    chunks = build_chunks(parsed, extract_metadata(parsed))
    ids = [c["section_id"] for c in chunks]
    assert "3.2" in ids
    c = next(c for c in chunks if c["section_id"] == "3.2")
    assert "60 days" in c["text"] and c["applies_to_raw"] == "All employees"


def test_hidden_white_text_is_detected_in_pdf_and_docx():
    for ext in ("pdf", "docx"):
        parsed = parse_file(open(_one(f"adversarial/{ext}/ADV-05*.{ext}"), "rb").read(), ext)
        assert any(l["hidden"] for l in parsed["lines"]), ext


def test_fallback_chunking_for_unnumbered_documents():
    text = b"Loan Handbook\n\nCredit Checks\nLoan Officers must verify income documents. They should record checks.\n"
    parsed = parse_file(text, "txt")
    chunks = build_chunks(parsed, {"document_id": "HB-09", "version": "1.0", "title": "Loan Handbook"})
    assert len(chunks) == 2 and chunks[0]["section_heading"] == "Credit Checks"


def test_invalid_type_empty_and_duplicate(ctx):
    errors, _, _ = validate_file("x.exe", b"abc", {"pdf", "docx"}, 10_000, ctx)
    assert any("not supported" in e for e in errors)
    errors, _, _ = validate_file("x.pdf", b"", {"pdf"}, 10_000, ctx)
    assert any("empty" in e for e in errors)
    data = open(_one("active/docx/POL-04*.docx"), "rb").read()
    errors, _, _ = validate_file("again.docx", data, {"docx"}, 10**7, ctx)
    assert any("Duplicate" in e for e in errors)


def test_missing_metadata_is_rejected():
    errors, _ = validate_metadata({"document_id": "POL-99"}, 500)
    assert any("title" in e for e in errors) and any("version" in e for e in errors)


def test_ingest_rejects_file_without_metadata(ctx, app):
    with pytest.raises(IngestError):
        ingest(ctx, "notes.txt", b"Some text without any control block at all, but long enough to read.", {}, app.config, "t")


def test_superseded_versions_are_not_active(ctx):
    active = ctx.documents.find_one({"document_id": "POL-04", "status": "Active"})
    old = ctx.documents.find_one({"document_id": "POL-04", "version": "1.0"})
    assert active["version"] == "2.0" and old["status"] == "Superseded"
