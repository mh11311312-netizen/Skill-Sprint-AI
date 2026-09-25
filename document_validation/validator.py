"""Step 5 - Document validation: file type, size, empty file, duplicates, version and date metadata."""
import hashlib
import re
from datetime import date, datetime

CATEGORIES = ["Policy", "Compliance", "SOP", "Handbook", "Role Description", "Process Manual",
              "FAQ", "Guideline", "Informal Guidance"]
REQUIRED_META = ["document_id", "title", "category", "department", "version", "effective_date"]


def file_hash(data):
    return hashlib.sha256(data).hexdigest()


def validate_file(filename, data, allowed_ext, max_bytes, db):
    """Checks done before parsing. Returns (errors, extension, sha256)."""
    errors = []
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_ext:
        errors.append(f"File type '.{ext}' is not supported. Allowed: {', '.join(sorted(allowed_ext))}.")
    if len(data) == 0:
        errors.append("The file is empty.")
    if len(data) > max_bytes:
        errors.append(f"File is larger than {max_bytes // (1024 * 1024)} MB.")
    digest = file_hash(data)
    dup = db.documents.find_one({"file_hash": digest})
    if dup:
        errors.append(f"Duplicate document: this exact file was already uploaded as {dup['document_id']} v{dup['version']}.")
    return errors, ext, digest


def parse_date(value):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def validate_metadata(meta, text_length):
    """Checks done after parsing. Returns (errors, warnings)."""
    errors, warnings = [], []
    if text_length < 40:
        errors.append("The document contains no readable text (empty or scanned image).")
    for field in REQUIRED_META:
        if not str(meta.get(field, "")).strip():
            errors.append(f"Missing metadata: {field.replace('_', ' ')}.")
    if meta.get("document_id") and not re.match(r"^[A-Z]{2,5}-[A-Z0-9-]{1,10}$", meta["document_id"]):
        errors.append("Document ID must look like POL-04 or SOP-12.")
    if meta.get("version") and not re.match(r"^v?\d+(\.\d+)?$", str(meta["version"]).strip()):
        errors.append("Version must be a number such as 1.0 or 2.1.")
    if meta.get("category") and meta["category"] not in CATEGORIES:
        errors.append(f"Unknown category '{meta['category']}'.")
    eff = parse_date(meta.get("effective_date", "")) if meta.get("effective_date") else None
    if meta.get("effective_date") and not eff:
        errors.append("Effective date must be in YYYY-MM-DD format.")
    rev = parse_date(meta.get("review_date", "")) if meta.get("review_date") else None
    if eff and rev and rev < eff:
        errors.append("Review/expiry date is before the effective date.")
    if rev and rev < date.today():
        warnings.append(f"Document review/expiry date {rev} has passed - content may be outdated.")
    if eff and eff > date.today():
        warnings.append(f"Effective date {eff} is in the future - the document is not yet in force.")
    return errors, warnings
