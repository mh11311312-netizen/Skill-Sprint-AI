"""Upload pipeline: validate -> parse -> metadata -> chunk -> security scan -> version control -> save
-> rebuild matrix -> policy-update impact analysis."""
from config.loader import load_yaml
from src.audit import now, log_audit, log_security
from src.text_utils import version_number
from document_validation.validator import validate_file, validate_metadata
from document_processing.parser import parse_file
from document_processing.metadata import extract_metadata
from document_processing.structure import build_chunks
from security.injection import scan_text
from contradiction_checks.source_conflicts import precedence_level


class IngestError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def ingest(db, filename, data, form_meta, config, user):
    errors, ext, digest = validate_file(filename, data, config["ALLOWED_EXTENSIONS"], config["MAX_CONTENT_LENGTH"], db)
    if errors:
        raise IngestError(errors)
    try:
        parsed = parse_file(data, ext)
    except Exception as e:                                   # corrupted / password-protected file
        raise IngestError([f"Could not read the file: {e.__class__.__name__}"])

    embedded = extract_metadata(parsed)
    meta = dict(embedded)
    for k, v in form_meta.items():                           # values typed by the admin take priority
        if v and str(v).strip():
            meta[k] = str(v).strip()
    meta["version"] = str(version_number(meta.get("version", "0")) or meta.get("version", ""))
    text_len = sum(len(l["text"]) for l in parsed["lines"])
    errors, warnings = validate_metadata(meta, text_len)
    if errors:
        raise IngestError(errors)

    doc_id, ver = meta["document_id"], meta["version"]
    doc_key = f"{doc_id}@{ver}"
    if db.documents.find_one({"doc_key": doc_key}):
        raise IngestError([f"{doc_id} version {ver} already exists. Upload a new version number."])

    chunks = build_chunks(parsed, meta)
    if not chunks:
        raise IngestError(["No content sections could be extracted from this document."])

    # ---- security: hidden text + prompt injection + suspicious metadata ----
    flags = []
    for c in chunks:
        found = scan_text(c["text"])
        if c["hidden"]:
            found.append("Hidden text")
        c["injection_flags"] = found
        c["quarantined"] = bool(found)
        if found:
            flags.append({"section_id": c["section_id"], "types": found, "text": c["text"][:200]})
    sup = meta.get("supersedes", "") or ""
    if sup and sup.lower() != "none" and doc_id not in sup:
        flags.append({"section_id": "metadata", "types": ["Unauthorised supersede claim"], "text": f"Supersedes: {sup}"})
    prec = load_yaml("precedence_rules.yaml")
    trust = "Trusted"
    if meta["category"] in prec["untrusted_categories"] or meta.get("owner", "Unknown") in prec["untrusted_owners"]:
        trust = "Untrusted"
    elif flags:
        trust = "Suspicious"
    for f in flags:
        log_security("Adversarial content detected", f"{doc_id} §{f['section_id']}: {', '.join(f['types'])}",
                     "High", doc_id)

    # ---- version control ----
    status, superseded, changes = "Active", None, []
    current = db.documents.find_one({"document_id": doc_id, "status": "Active"})
    if current:
        if version_number(ver) > current["version_num"]:
            superseded = current
            db.documents.update_one({"_id": current["_id"]}, {"$set": {"status": "Superseded", "superseded_by": ver}})
            db.chunks.update_many({"document_id": doc_id, "version": current["version"]}, {"$set": {"status": "Superseded"}})
            changes = diff_versions(list(db.chunks.find({"document_id": doc_id, "version": current["version"]})), chunks)
        else:
            status = "Superseded"
            warnings.append(f"An active version ({current['version']}) is newer - this file was stored as Superseded.")

    if status == "Active" and str(embedded.get("status", "")).lower() == "superseded":
        status = "Superseded"
        warnings.append("The document declares itself Superseded, so it was not made active.")

    doc = {
        "doc_key": doc_key, "document_id": doc_id, "title": meta["title"], "category": meta["category"],
        "department": meta["department"], "version": ver, "version_num": version_number(ver), "status": status,
        "effective_date": meta["effective_date"], "review_date": meta.get("review_date", ""),
        "owner": meta.get("owner", "Unknown"), "supersedes": sup, "file_name": filename, "file_type": ext,
        "file_hash": digest, "uploaded_by": user, "uploaded_at": now(), "trust": trust,
        "precedence_level": precedence_level(meta["category"]), "security_flags": flags,
        "warnings": warnings, "chunk_count": len(chunks), "changes": changes,
        "previous_version": superseded["version"] if superseded else None,
        "embedded_metadata": embedded,
    }
    db.documents.insert_one(doc)
    for c in chunks:
        c["status"] = status
    db.chunks.insert_many(chunks)
    log_audit("upload_document", "document", doc_key, after={"status": status, "trust": trust}, user=user)

    from role_matrix.builder import rebuild_matrix
    summary = rebuild_matrix(db, user)
    impact = None
    if superseded:
        from src.impact import analyse_impact
        impact = analyse_impact(db, doc_id, superseded["version"], ver, changes)
    return doc, summary, impact


def diff_versions(old_chunks, new_chunks):
    old = {c["section_id"]: c["text"] for c in old_chunks}
    new = {c["section_id"]: c["text"] for c in new_chunks}
    out = []
    for sid in sorted(set(old) | set(new), key=lambda s: [int(x) for x in s.split(".") if x.isdigit()]):
        if sid not in old:
            out.append({"section_id": sid, "change": "Added", "old": "", "new": new[sid]})
        elif sid not in new:
            out.append({"section_id": sid, "change": "Removed", "old": old[sid], "new": ""})
        elif old[sid].strip() != new[sid].strip():
            out.append({"section_id": sid, "change": "Modified", "old": old[sid], "new": new[sid]})
    return out
