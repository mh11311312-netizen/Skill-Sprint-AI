"""Reads the 'Document Control' block (or markdown front matter) that sits at the top of a document."""
import re

LABELS = {
    "document id": "document_id", "doc id": "document_id", "title": "title", "category": "category",
    "department": "department", "version": "version", "status": "status", "effective date": "effective_date",
    "review / expiry date": "review_date", "review date": "review_date", "expiry date": "review_date",
    "document owner": "owner", "owner": "owner", "supersedes": "supersedes",
    "document_id": "document_id", "effective_date": "effective_date", "review_date": "review_date",
}
_LABEL_RX = re.compile(r"^(" + "|".join(sorted(map(re.escape, LABELS), key=len, reverse=True)) + r")\s*[:|]?\s+(.+)$", re.I)


def extract_metadata(parsed):
    meta = {}
    for table in parsed.get("tables", [])[:2]:            # DOCX control table
        for row in table:
            if len(row) >= 2 and row[0].strip().lower() in LABELS:
                meta.setdefault(LABELS[row[0].strip().lower()], row[1].strip())
    for line in parsed["lines"][:40]:                     # PDF / TXT / MD control lines
        m = _LABEL_RX.match(line["text"])
        if m:
            meta.setdefault(LABELS[m.group(1).lower()], m.group(2).strip())
    return meta


def control_line(text):
    """True if a line is part of the control block (so it is not treated as content)."""
    return bool(_LABEL_RX.match(text)) or text.strip() in ("---", "Document Control")
