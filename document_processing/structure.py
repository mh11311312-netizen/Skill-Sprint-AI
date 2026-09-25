"""Step 7 - Chunking. Splits a document into traceable chunks.
Primary format:   '2. Heading'  ->  'Applies to: ...'  ->  '2.1 clause', '2.2 clause'
Fallback format:  any document without numbered clauses is split by headings and sentences,
so unseen (hidden evaluation) documents can still be processed without code changes."""
import re
from document_processing.metadata import control_line

HEADING = re.compile(r"^(\d{1,2})\.\s+(\S.{0,120})$")
CLAUSE = re.compile(r"^(\d{1,2}\.\d{1,2})\s+(\S.*)$")
APPLIES = re.compile(r"^applies to\s*:\s*(.+)$", re.I)
FOOTER = re.compile(r"\|\s*Page\s+\d+|^Page \d+( of \d+)?$", re.I)


def build_chunks(parsed, meta):
    raw = [l for l in parsed["lines"] if not FOOTER.search(l["text"])]
    # control-block lines (Document ID, Version ...) are only removed from the top of the document
    first = next((i for i, l in enumerate(raw) if HEADING.match(l["text"]) or CLAUSE.match(l["text"])), len(raw))
    head = [l for l in raw[:first] if not control_line(l["text"])
            and l["text"].strip() != meta.get("title", "").strip()]
    lines = head + raw[first:]
    chunks = _numbered(lines)
    if not chunks:
        chunks = _fallback(lines)
    doc_id, ver = meta["document_id"], str(meta["version"])
    for i, c in enumerate(chunks, start=1):
        c["chunk_id"] = f"{doc_id}@{ver}#C{i:03d}"
        c["document_id"], c["version"] = doc_id, ver
    return chunks


def _numbered(lines):
    chunks, sec_no, heading, applies, current = [], None, "", "", None
    for l in lines:
        t = l["text"]
        mc, mh, ma = CLAUSE.match(t), HEADING.match(t), APPLIES.match(t)
        if mc:
            current = {"section_id": mc.group(1), "section_no": sec_no or mc.group(1).split(".")[0],
                       "section_heading": heading, "applies_to_raw": applies, "text": mc.group(2),
                       "page": l["page"], "para": l["para"], "hidden": l["hidden"]}
            chunks.append(current)
        elif mh and not t.endswith((".", ",", ";")) and len(t.split()) <= 14:
            sec_no, heading, applies, current = mh.group(1), mh.group(2).strip(), "", None
        elif ma:
            applies = ma.group(1).strip()
        elif current is not None:
            current["text"] += " " + t                  # wrapped line of the same clause
            current["hidden"] = current["hidden"] or l["hidden"]
    return chunks


def _fallback(lines):
    chunks, heading, sec, n, applies = [], "General", 1, 0, ""
    for l in lines:
        t = l["text"]
        ma = APPLIES.match(t)
        if ma:
            applies = ma.group(1).strip()
            continue
        looks_heading = (l.get("style", "").startswith("Heading") or
                         (len(t.split()) <= 8 and not t.endswith((".", ":", ";")) and t[:1].isupper()))
        if looks_heading:
            if n:
                sec += 1
            heading, n, applies = t.strip("# "), 0, ""
            continue
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", t):
            if len(sentence.split()) < 3:
                continue
            n += 1
            chunks.append({"section_id": f"{sec}.{n}", "section_no": str(sec), "section_heading": heading,
                           "applies_to_raw": applies, "text": sentence.strip(), "page": l["page"],
                           "para": l["para"], "hidden": l["hidden"]})
    return chunks
