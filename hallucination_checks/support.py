"""Steps 15/31/32 - Source support and hallucination detection.
A generated statement is 'supported' only if the cited clause exists in an ACTIVE, TRUSTED document
and the statement is textually close to that clause. Numbers must also appear in the source."""
from config.loader import load_yaml
from src.text_utils import cosine, numbers


class SourceIndex:
    """Fast lookup of every stored clause by (document_id, section_id)."""

    def __init__(self, db):
        untrusted = load_yaml("precedence_rules.yaml")["untrusted_categories"]
        self.docs = {}
        for d in db.documents.find():
            self.docs.setdefault(d["document_id"], []).append(d)
        self.active_doc = {k: next((d for d in v if d["status"] == "Active"), None) for k, v in self.docs.items()}
        self.untrusted_docs = {k for k, d in self.active_doc.items()
                               if d and (d.get("trust") == "Untrusted" or d["category"] in untrusted)}
        self.chunks = {}
        for c in db.chunks.find():
            self.chunks.setdefault((c["document_id"], c["section_id"]), []).append(c)

    def check(self, doc_id, section_id):
        """Returns (status, chunk). status: valid | outdated | untrusted | quarantined | missing."""
        doc_id, section_id = str(doc_id).strip(), str(section_id).strip().lstrip("§ ")
        if doc_id not in self.docs:
            return "missing", None
        active = self.active_doc.get(doc_id)
        found = self.chunks.get((doc_id, section_id), [])
        cur = next((c for c in found if active and c["version"] == active["version"]), None)
        if cur is None:
            return ("outdated", found[0]) if found else ("missing", None)
        if doc_id in self.untrusted_docs:
            return "untrusted", cur
        if cur.get("quarantined"):
            return "quarantined", cur
        return "valid", cur


def support_score(statement, chunk_text):
    return round(cosine(statement, chunk_text), 3)


def unsupported_numbers(statement, chunk_text):
    """Numbers in the generated text that do not exist in the source (e.g. '90 days' when source says 60)."""
    src = numbers(chunk_text)
    return sorted(n for n in numbers(statement) if n not in src and not n.startswith("0"))
